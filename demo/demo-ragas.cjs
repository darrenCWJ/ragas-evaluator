'use strict';
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE_URL = 'http://localhost:8000';
const VIDEO_DIR = path.join(__dirname);
const OUTPUT_NAME = 'demo-ragas.webm';
const REHEARSAL = process.argv.includes('--rehearse');

// Project pre-seeded via API: id=3, name=my-rag-bot
// Experiment id=6 already completed, bot_config_id=7 (CSV)
const PROJECT_JSON = JSON.stringify({
  id: 3, name: 'my-rag-bot', description: 'Demo RAG evaluation project',
  created_at: '2026-04-24 18:30:22', updated_at: '2026-04-24 18:30:22',
  judge_model_assignments: null,
});

// ── helpers ───────────────────────────────────────────────────────────────────

async function injectOverlays(page) {
  await page.evaluate(() => {
    if (!document.getElementById('demo-cursor')) {
      const c = document.createElement('div');
      c.id = 'demo-cursor';
      c.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d="M5 3L19 12L12 13L9 20L5 3Z" fill="white" stroke="black" stroke-width="1.5" stroke-linejoin="round"/>
      </svg>`;
      c.style.cssText = `position:fixed;z-index:999999;pointer-events:none;
        width:24px;height:24px;filter:drop-shadow(1px 1px 2px rgba(0,0,0,0.4));
        left:640px;top:360px;`;
      document.body.appendChild(c);
      document.addEventListener('mousemove', e => {
        c.style.left = e.clientX + 'px';
        c.style.top  = e.clientY + 'px';
      });
    }
    if (!document.getElementById('demo-subtitle')) {
      const bar = document.createElement('div');
      bar.id = 'demo-subtitle';
      bar.style.cssText = `position:fixed;bottom:0;left:0;right:0;z-index:999998;
        text-align:center;padding:14px 32px;background:rgba(0,0,0,0.80);
        color:#fff;font-family:-apple-system,"Segoe UI",sans-serif;
        font-size:17px;font-weight:500;letter-spacing:0.3px;
        transition:opacity 0.3s;pointer-events:none;opacity:0;`;
      document.body.appendChild(bar);
    }
  });
}

async function showSubtitle(page, text) {
  await page.evaluate(t => {
    const bar = document.getElementById('demo-subtitle');
    if (!bar) return;
    bar.textContent = t;
    bar.style.opacity = t ? '1' : '0';
  }, text);
  if (text) await page.waitForTimeout(700);
}

async function moveTo(page, x, y, steps = 22) {
  await page.mouse.move(x, y, { steps });
  await page.waitForTimeout(100);
}

async function sweepRow(page, y, fromX = 280, toX = 1000) {
  await moveTo(page, fromX, y, 18);
  await page.waitForTimeout(150);
  await moveTo(page, toX, y, 28);
  await page.waitForTimeout(200);
}

async function scrollTo(page, targetY) {
  const currentY = await page.evaluate(() => window.scrollY);
  const steps = 8;
  const delta = (targetY - currentY) / steps;
  for (let i = 1; i <= steps; i++) {
    await page.evaluate(y => window.scrollTo({ top: y, behavior: 'instant' }), Math.round(currentY + delta * i));
    await page.waitForTimeout(160);
  }
  await injectOverlays(page);
  await page.waitForTimeout(300);
}

async function moveAndClick(page, selector, label, opts = {}) {
  const { postDelay = 900 } = opts;
  const el = page.locator(selector).first();
  if (!await el.isVisible().catch(() => false)) {
    console.warn(`WARN: skip click "${label}" — not visible`);
    return false;
  }
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  if (box) await moveTo(page, box.x + box.width / 2, box.y + box.height / 2, 18);
  await page.waitForTimeout(300);
  await el.click();
  await page.waitForTimeout(postDelay);
  return true;
}

async function typeSlowly(page, selector, text, label, delay = 40) {
  const el = page.locator(selector).first();
  if (!await el.isVisible().catch(() => false)) { console.warn(`WARN: skip type "${label}"`); return; }
  await moveAndClick(page, selector, label, { postDelay: 300 });
  await el.fill('');
  await el.pressSequentially(text, { delay });
  await page.waitForTimeout(400);
}

async function hoverEl(page, selector, label) {
  const el = page.locator(selector).first();
  const box = await el.boundingBox().catch(() => null);
  if (!box) { console.warn(`WARN: hover "${label}" no bbox`); return; }
  await moveTo(page, box.x + box.width / 2, box.y + box.height / 2, 20);
  await page.waitForTimeout(600);
}

async function ensureVisible(page, selector, label) {
  const visible = await page.locator(selector).first().isVisible().catch(() => false);
  if (!visible) {
    const dump = await page.evaluate(() =>
      Array.from(document.querySelectorAll('button,input,select,textarea'))
        .filter(e => e.offsetParent)
        .map(e => `${e.tagName} "${(e.textContent || e.placeholder || '').trim().substring(0, 35)}"`)
        .slice(0, 20).join('\n  ')
    );
    console.error(`REHEARSAL FAIL: "${label}" not found (${selector})\n  Visible:\n  ${dump}`);
    return false;
  }
  console.log(`REHEARSAL OK: "${label}"`);
  return true;
}

// seedProject: set localStorage then navigate; React reads it on mount
async function seedProject(page, targetPath) {
  // Navigate to origin to ensure same-origin localStorage access
  const cur = page.url();
  if (!cur.startsWith(BASE_URL)) {
    await page.goto(BASE_URL + '/app/setup');
    await page.waitForTimeout(500);
  }
  await page.evaluate(json => localStorage.setItem('ragas_selected_project', json), PROJECT_JSON);
  if (targetPath) {
    await page.goto(BASE_URL + targetPath);
    // Wait for the app to fully load
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(800);
  }
}

// clickProjectInDropdown: reliably selects a project by name from the open dropdown
async function clickProjectInDropdown(page, name) {
  // Use Playwright's hasText filter which does contains-matching
  const btn = page.locator('button').filter({ hasText: name });
  // Exclude the main project selector toggle button (shows full project name as toggle)
  // The dropdown item button has a specific class structure
  const count = await btn.count();
  for (let i = 0; i < count; i++) {
    const b = btn.nth(i);
    const text = (await b.textContent() || '').trim();
    // The dropdown item button contains the name + optional description; skip the selector toggle
    if (text.startsWith(name) || text.includes(name)) {
      const box = await b.boundingBox();
      if (box) {
        await b.click();
        return true;
      }
    }
  }
  // Fallback: evaluate click on the inner name div
  await page.evaluate(n => {
    const divs = [...document.querySelectorAll('div.truncate.font-medium')];
    const match = divs.find(d => d.textContent && d.textContent.trim() === n);
    if (match) {
      const btn = match.closest('button');
      if (btn) btn.click();
    }
  }, name);
  return false;
}

// ── rehearsal ─────────────────────────────────────────────────────────────────

async function runRehearsal(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await ctx.newPage();
  let ok = true;
  console.log('\n=== REHEARSAL ===\n');

  // 00: empty landing
  await page.goto(`${BASE_URL}/app/setup`);
  await page.waitForTimeout(1200);
  ok = await ensureVisible(page, 'button:has-text("Select project")', 'Select project button') && ok;

  // open dropdown → new project form
  await page.locator('button:has-text("Select project")').first().click();
  await page.waitForTimeout(600);
  ok = await ensureVisible(page, 'button:has-text("New project")', 'New project button') && ok;
  await page.locator('button:has-text("New project")').first().click();
  await page.waitForTimeout(500);
  ok = await ensureVisible(page, 'input[placeholder*="name"], input[placeholder*="Name"]', 'Project name input') && ok;
  ok = await ensureVisible(page, 'button:has-text("Cancel")', 'Cancel button') && ok;
  await page.locator('button:has-text("Cancel")').first().click();
  await page.waitForTimeout(500);

  // select my-rag-bot: set localStorage then reload so React reads it on mount
  await page.evaluate(json => localStorage.setItem('ragas_selected_project', json), PROJECT_JSON);
  await page.reload();
  await page.waitForTimeout(1500);

  // 01 Setup — with project
  ok = await ensureVisible(page, 'input[type="radio"]', 'Connector type radios') && ok;
  ok = await ensureVisible(page, 'button:has-text("Save")', 'Save connector button') && ok;

  // 02 Build
  await seedProject(page, '/app/build');
  ok = await ensureVisible(page, 'select', 'Chunking method select') && ok;
  ok = await ensureVisible(page, 'button:has-text("Save Config")', 'Save Config button') && ok;

  // 03 Test
  await seedProject(page, '/app/test');
  try { await page.waitForSelector('button:has-text("Generate Test Set")', { timeout: 4000 }); } catch {}
  ok = await ensureVisible(page, 'button:has-text("Generate Test Set")', 'Generate Test Set button') && ok;

  // 04 Experiment — should have completed experiment now
  await seedProject(page, '/app/experiment');
  try { await page.waitForSelector('input[placeholder*="Baseline"]', { timeout: 4000 }); } catch {}
  ok = await ensureVisible(page, 'input[placeholder*="Baseline"]', 'Experiment name input') && ok;
  ok = await ensureVisible(page, 'button:has-text("Internal RAG")', 'Internal RAG button') && ok;

  // 05 Analyze
  await seedProject(page, '/app/analyze');
  try { await page.waitForSelector('select', { timeout: 4000 }); } catch {}
  ok = await ensureVisible(page, 'select', 'Experiment select') && ok;

  await ctx.close();
  console.log(`\n=== REHEARSAL ${ok ? 'PASSED' : 'FAILED'} ===\n`);
  if (!ok) process.exit(1);
}

// ── recording ─────────────────────────────────────────────────────────────────

async function runRecording(browser) {
  const ctx = await browser.newContext({
    recordVideo: { dir: VIDEO_DIR, size: { width: 1280, height: 720 } },
    viewport: { width: 1280, height: 720 },
  });
  const page = await ctx.newPage();

  try {
    // ── SCENE 1: Problem statement ─────────────────────────────────────────
    await page.goto(`${BASE_URL}/app/setup`);
    await page.waitForTimeout(1500);
    await injectOverlays(page);

    await showSubtitle(page, 'RAG chatbots are hard to evaluate — until now');
    // sweep cursor slowly down the sidebar nav
    for (const y of [90, 160, 230, 300, 370, 420]) {
      await moveTo(page, 120, y, 20);
      await page.waitForTimeout(500);
    }
    await showSubtitle(page, 'Ragas Platform — a 5-step pipeline from setup to insights');
    await sweepRow(page, 360);
    await sweepRow(page, 260);
    await page.waitForTimeout(1000);
    await showSubtitle(page, '');

    // ── SCENE 2: Create a project ──────────────────────────────────────────
    await showSubtitle(page, 'Step 1 — Create a project');
    await page.waitForTimeout(600);
    await moveAndClick(page, 'button:has-text("Select project")', 'Select project', { postDelay: 700 });
    await moveAndClick(page, 'button:has-text("New project")', 'New project', { postDelay: 600 });
    await injectOverlays(page);

    await typeSlowly(page, 'input[placeholder*="name"], input[placeholder*="Name"]', 'my-rag-bot', 'project name');
    await page.waitForTimeout(800);
    await showSubtitle(page, '');
    await moveAndClick(page, 'button:has-text("Cancel")', 'Cancel', { postDelay: 600 });

    // pick the existing my-rag-bot: visually open dropdown then select via localStorage + reload
    await moveAndClick(page, 'button:has-text("Select project")', 'Select project', { postDelay: 800 });
    // Move cursor to where the project item appears in the dropdown list
    await moveTo(page, 260, 320, 20);
    await page.waitForTimeout(600);
    await moveTo(page, 260, 280, 15);
    await page.waitForTimeout(400);
    // Set localStorage and reload so React reads the project on mount
    await page.evaluate(json => localStorage.setItem('ragas_selected_project', json), PROJECT_JSON);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1200);
    await injectOverlays(page);

    // ── SCENE 3: Setup — bot connector + CSV upload ────────────────────────
    await showSubtitle(page, 'Step 2 — Connect your bot or import test data');
    await page.waitForTimeout(700);

    // sweep across connector type options
    await sweepRow(page, 310, 280, 980);
    await showSubtitle(page, 'Supports Glean, OpenAI, Claude, Gemini, DeepSeek, and custom APIs');
    await page.waitForTimeout(1800);
    await showSubtitle(page, '');

    // scroll to reveal connector form (Glean is pre-selected)
    await scrollTo(page, 320);
    for (const sel of [
      'input[placeholder*="My Glean Bot"]',
      'input[placeholder*="Glean API token"]',
      'input[placeholder*="your-company"]',
    ]) {
      await hoverEl(page, sel, sel);
    }
    await hoverEl(page, 'button:has-text("Save")', 'Save button');

    await showSubtitle(page, 'Configure once — reuse across every experiment');
    await page.waitForTimeout(2000);
    await showSubtitle(page, '');

    // scroll down further to CSV upload section and uploaded file
    await scrollTo(page, 700);
    await sweepRow(page, 400, 280, 900);
    await sweepRow(page, 500, 280, 900);
    await showSubtitle(page, 'Or import a CSV of real bot responses — no live API needed');
    await page.waitForTimeout(2200);
    await showSubtitle(page, '');
    await scrollTo(page, 0);

    // ── SCENE 4: Build — RAG pipeline config ──────────────────────────────
    await showSubtitle(page, 'Step 3 — Configure your RAG pipeline');
    await seedProject(page, '/app/build');
    await injectOverlays(page);

    await sweepRow(page, 200, 280, 980);
    await sweepRow(page, 300, 280, 980);
    await hoverEl(page, 'select', 'Chunking method');
    await hoverEl(page, 'input[value="512"]', 'Chunk size');

    await showSubtitle(page, 'Choose chunk size, overlap, embedding model, and retrieval strategy');
    await page.waitForTimeout(1800);
    await showSubtitle(page, '');

    // scroll down to show embedding section
    await scrollTo(page, 520);
    await sweepRow(page, 350, 280, 980);
    await sweepRow(page, 480, 280, 980);
    await page.waitForTimeout(800);
    await scrollTo(page, 0);

    // ── SCENE 5: Test — generate test questions ────────────────────────────
    await showSubtitle(page, 'Step 4 — Generate synthetic test questions automatically');
    await seedProject(page, '/app/test');
    await injectOverlays(page);

    await sweepRow(page, 220, 280, 980);
    await hoverEl(page, 'input[value="10"]', 'Test set size');
    await hoverEl(page, 'label:has-text("Use Personas")', 'Use Personas label');
    await sweepRow(page, 380, 280, 980);

    await showSubtitle(page, 'LLM-generated Q&A pairs across different user personas');
    await page.waitForTimeout(2000);
    await showSubtitle(page, '');

    // scroll to show "Fast" vs "Full (Knowledge Graph)" mode buttons
    await scrollTo(page, 420);
    await sweepRow(page, 300, 280, 980);
    await hoverEl(page, 'button:has-text("Fast")', 'Fast mode button');
    await hoverEl(page, 'button:has-text("Full")', 'Full KG mode button');
    await showSubtitle(page, 'Fast mode for quick iteration, full Knowledge Graph for deeper coverage');
    await page.waitForTimeout(2200);
    await showSubtitle(page, '');
    await scrollTo(page, 0);

    // ── SCENE 6: Experiment — configure & run ─────────────────────────────
    await showSubtitle(page, 'Step 5 — Run an experiment against your bot');
    await seedProject(page, '/app/experiment');
    await injectOverlays(page);

    await sweepRow(page, 270, 280, 980);
    await hoverEl(page, 'input[placeholder*="Baseline"]', 'Experiment name');

    // toggle Internal RAG ↔ External Bot so viewer sees the UI react
    await moveAndClick(page, 'button:has-text("Internal RAG")', 'Internal RAG', { postDelay: 900 });
    await injectOverlays(page);
    await moveAndClick(page, 'button:has-text("External Bot")', 'External Bot', { postDelay: 900 });
    await injectOverlays(page);

    await showSubtitle(page, 'Test your internal RAG pipeline or any external bot API');
    await page.waitForTimeout(1800);
    await showSubtitle(page, '');

    // scroll down to see the completed experiment
    await scrollTo(page, 480);
    await sweepRow(page, 360, 280, 980);
    await sweepRow(page, 460, 280, 980);
    await showSubtitle(page, 'Baseline Evaluation — completed and ready to analyze');
    await page.waitForTimeout(2200);
    await showSubtitle(page, '');
    await scrollTo(page, 0);

    // ── SCENE 7: Analyze — metric results ─────────────────────────────────
    await showSubtitle(page, 'Step 6 — Review scores across 20+ quality metrics');
    await seedProject(page, '/app/analyze');
    await injectOverlays(page);

    // select the completed experiment
    await page.evaluate(() => {
      const sel = document.querySelector('select');
      if (sel && sel.options.length > 1) {
        sel.value = sel.options[1].value;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    await page.waitForTimeout(1600);
    await injectOverlays(page);

    await showSubtitle(page, 'Faithfulness, Answer Relevancy, Semantic Similarity, and more…');
    await sweepRow(page, 320, 280, 980);
    await page.waitForTimeout(600);
    await showSubtitle(page, '');

    // scroll through the metric bars in steps
    for (const y of [220, 420, 620]) {
      await scrollTo(page, y);
      await sweepRow(page, Math.min(y + 80, 620), 280, 980);
      await page.waitForTimeout(500);
    }

    await showSubtitle(page, 'See exactly where your bot excels — and where it falls short');
    await page.waitForTimeout(2300);
    await showSubtitle(page, '');

    // scroll to Suggestions section
    await page.evaluate(() => {
      const h = [...document.querySelectorAll('h3')].find(el => el.textContent.includes('Suggestion'));
      if (h) h.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await injectOverlays(page);
    await page.waitForTimeout(700);
    await sweepRow(page, 300, 280, 980);
    await sweepRow(page, 440, 280, 980);
    await showSubtitle(page, 'Actionable suggestions to improve your pipeline — generated automatically');
    await page.waitForTimeout(3000);
    await showSubtitle(page, '');

    // ── SCENE 8: Outro ─────────────────────────────────────────────────────
    await scrollTo(page, 0);
    await injectOverlays(page);
    // final sweep of sidebar nav
    for (const [x, y] of [[120,90],[120,170],[120,250],[120,330],[120,410],[640,300],[900,300]]) {
      await moveTo(page, x, y, 22);
      await page.waitForTimeout(380);
    }
    await showSubtitle(page, 'Ragas Platform — know your RAG bot is actually working');
    await page.waitForTimeout(4500);
    await showSubtitle(page, '');
    await page.waitForTimeout(1200);

  } catch (err) {
    console.error('DEMO ERROR:', err.message, err.stack);
  } finally {
    await ctx.close();
    const video = page.video();
    if (video) {
      const src = await video.path();
      const dest = path.join(VIDEO_DIR, OUTPUT_NAME);
      try { fs.copyFileSync(src, dest); console.log('\nVideo saved:', dest); }
      catch (e) { console.error('Copy failed:', e.message, '\nSource:', src); }
    }
    await browser.close();
  }
}

// ── entry ─────────────────────────────────────────────────────────────────────
(async () => {
  const browser = await chromium.launch({ headless: true });
  if (REHEARSAL) { await runRehearsal(browser); await browser.close(); }
  else await runRecording(browser);
})();

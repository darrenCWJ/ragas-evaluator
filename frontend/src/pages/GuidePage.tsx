import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  LLM_METRICS,
  NVIDIA_METRICS,
  EMBEDDING_METRICS,
  STRING_METRICS,
  DOMAIN_METRICS,
  JUDGE_METRICS,
  METRIC_DESCRIPTIONS,
} from '../components/experiment/runner/MetricSelection';

const SECTIONS = [
  { id: 'overview', label: 'What is Tribunal?' },
  { id: 'path-external', label: 'Test an external agent' },
  { id: 'path-rag', label: 'Build & evaluate a RAG pipeline' },
  { id: 'datasets', label: 'Dataset format reference' },
  { id: 'metrics', label: 'Metric glossary' },
  { id: 'skills', label: 'Skill Arena' },
  { id: 'feedback', label: 'Human feedback' },
  { id: 'faq', label: 'FAQ' },
] as const;

interface ColumnSpec {
  column: string;
  aliases: string;
  required: boolean;
  unlocks: string;
}

const DATASET_COLUMNS: ColumnSpec[] = [
  {
    column: 'question',
    aliases: 'question, query, user_input, input',
    required: true,
    unlocks: 'All metrics (the prompt sent to your AI)',
  },
  {
    column: 'reference_answer',
    aliases: 'reference_answer, answer, expected_answer, reference, ground_truth, output',
    required: true,
    unlocks: 'Correctness metrics (factual_correctness, semantic_similarity, string metrics)',
  },
  {
    column: 'reference_contexts',
    aliases: 'reference_contexts, contexts, context, sources',
    required: false,
    unlocks: 'Context metrics (faithfulness, context_precision/recall, groundedness…)',
  },
  {
    column: 'category',
    aliases: 'category (map manually)',
    required: false,
    unlocks: 'Per-category breakdowns and refusal_accuracy (tag refusal questions)',
  },
  {
    column: 'turns',
    aliases: 'turns (map manually)',
    required: false,
    unlocks: 'Multi-turn conversation testing and conversation_retention',
  },
  {
    column: 'reference_sql',
    aliases: 'reference_sql, ref_sql, expected_sql, sql',
    required: false,
    unlocks: 'sql_semantic_equivalence (text-to-SQL evaluation)',
  },
  {
    column: 'schema_contexts',
    aliases: 'schema_contexts, schema, ddl',
    required: false,
    unlocks: 'Schema context for SQL evaluation',
  },
  {
    column: 'reference_data',
    aliases: 'reference_data, ref_data, expected_data',
    required: false,
    unlocks: 'datacompy_score (structured data comparison)',
  },
  {
    column: 'reference_tool_calls',
    aliases: 'reference_tool_calls, tool_calls, expected_tool_calls',
    required: false,
    unlocks: 'tool_call_f1 (agent experiments — expected tool calls as a JSON array)',
  },
];

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-bold text-accent">
        {n}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium text-text-primary">{title}</p>
        <p className="text-sm text-text-secondary">{children}</p>
      </div>
    </li>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-6 rounded-xl border border-border bg-card p-6 space-y-4">
      <h2 className="text-base font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function MetricGlossaryGroup({
  label,
  metrics,
  cost,
}: {
  label: string;
  metrics: string[];
  cost: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-medium text-text-primary">{label}</span>
        <span className="flex items-center gap-3">
          <span className="rounded-full bg-elevated px-2 py-0.5 text-2xs text-text-muted">
            {cost}
          </span>
          <svg
            className={`h-3.5 w-3.5 text-text-muted transition-transform ${open ? 'rotate-90' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-border/60 px-4 py-3">
          {metrics.map((m) => (
            <div key={m}>
              <p className="text-xs font-semibold text-text-primary">{m.replace(/_/g, ' ')}</p>
              <p className="text-xs text-text-secondary leading-relaxed">
                {METRIC_DESCRIPTIONS[m] ?? 'No description available.'}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-sm font-medium text-text-primary">{q}</p>
      <p className="text-sm text-text-secondary">{children}</p>
    </div>
  );
}

export default function GuidePage() {
  return (
    <div className="mx-auto flex max-w-5xl gap-8">
      {/* Section nav */}
      <nav className="sticky top-6 hidden h-fit w-52 shrink-0 space-y-1 lg:block">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="block rounded-md px-3 py-1.5 text-xs text-text-secondary transition hover:bg-elevated hover:text-text-primary"
          >
            {s.label}
          </a>
        ))}
      </nav>

      <div className="min-w-0 flex-1 space-y-6">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">Guide</h1>
          <p className="text-sm text-text-secondary">
            Everything you need to go from zero to a finished evaluation — no prior experience
            required.
          </p>
        </div>

        <Section id="overview" title="What is Tribunal?">
          <p className="text-sm text-text-secondary leading-relaxed">
            Tribunal tests AI systems the way QA tests software. You give it a set of questions
            with known-good answers, point it at an AI (yours or an external one), and it scores
            every response with a battery of metrics — then helps you understand{' '}
            <em>why</em> answers failed and whether your fixes actually worked.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed">
            There are two ways to use it. If you already have an AI agent or chatbot running
            somewhere, follow{' '}
            <a href="#path-external" className="text-accent hover:underline">
              Test an external agent
            </a>
            . If you want to build a retrieval pipeline from your documents and tune it, follow{' '}
            <a href="#path-rag" className="text-accent hover:underline">
              Build &amp; evaluate a RAG pipeline
            </a>
            .
          </p>
        </Section>

        <Section id="path-external" title="Path A — Test an external AI agent">
          <ol className="space-y-4">
            <Step n={1} title="Create a project (Setup)">
              Projects keep your test sets, experiments, and results together. Name it after the
              bot you are testing.
            </Step>
            <Step n={2} title="Connect your bot (Experiment → Bot connectors)">
              Add a bot connector: OpenAI/Claude/Gemini/DeepSeek with your prompt, a custom HTTP
              endpoint, or a CSV of pre-recorded answers if your bot can&apos;t be called live.
            </Step>
            <Step n={3} title="Upload test questions (Test)">
              Upload a CSV/JSON with questions and expected answers — see the{' '}
              <a href="#datasets" className="text-accent hover:underline">
                dataset reference
              </a>{' '}
              for columns. Approve the questions you want to use.
            </Step>
            <Step n={4} title="Create and run an experiment (Experiment)">
              Pick &quot;External bot&quot; mode, your connector, and your test set. Choose metrics
              — anything grayed out needs a dataset column you didn&apos;t provide. Hit run and
              watch live progress.
            </Step>
            <Step n={5} title="Read the results (Analyze)">
              Every question gets per-metric scores with explanations. Use the suggestions panel
              for fixes, annotate a sample to calibrate the judges, and re-run to compare against
              your baseline.
            </Step>
          </ol>
        </Section>

        <Section id="path-rag" title="Path B — Build & evaluate a RAG pipeline">
          <ol className="space-y-4">
            <Step n={1} title="Upload documents (Setup)">
              Add the documents your AI should answer from — PDF, Word, text, and more.
            </Step>
            <Step n={2} title="Chunk and embed (Build)">
              Split documents into chunks (six strategies available) and embed them. Different
              chunking choices materially change retrieval quality — that&apos;s what you&apos;ll
              be tuning.
            </Step>
            <Step n={3} title="Create a RAG config (Build)">
              Combine a chunk config + embedding + retrieval settings (top-k, thresholds, query
              expansion) + an answering model into a named configuration.
            </Step>
            <Step n={4} title="Generate a test set (Test)">
              Tribunal generates questions from your own documents — optionally with personas and
              a knowledge graph for harder multi-hop questions. Review and approve them.
            </Step>
            <Step n={5} title="Run experiments and iterate (Experiment → Analyze)">
              Run the test set against your RAG config. Context metrics (faithfulness, context
              recall…) tell you whether retrieval or generation is the weak link. Change one
              thing, re-run, compare deltas.
            </Step>
          </ol>
        </Section>

        <Section id="datasets" title="Dataset format reference">
          <p className="text-sm text-text-secondary">
            The uploader auto-detects common column names and lets you map the rest manually. Two
            columns are required; every optional column unlocks more metrics.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="py-2 pr-4 font-medium">Column</th>
                  <th className="py-2 pr-4 font-medium">Auto-detected names</th>
                  <th className="py-2 pr-4 font-medium">Required</th>
                  <th className="py-2 font-medium">Unlocks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {DATASET_COLUMNS.map((c) => (
                  <tr key={c.column}>
                    <td className="py-2 pr-4 font-mono text-accent">{c.column}</td>
                    <td className="py-2 pr-4 text-text-muted">{c.aliases}</td>
                    <td className="py-2 pr-4">
                      {c.required ? (
                        <span className="text-score-low">required</span>
                      ) : (
                        <span className="text-text-muted">optional</span>
                      )}
                    </td>
                    <td className="py-2 text-text-secondary">{c.unlocks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-text-muted">
            Example CSV row:{' '}
            <code className="rounded bg-elevated px-1.5 py-0.5 font-mono">
              &quot;What is the refund window?&quot;,&quot;30 days from delivery&quot;,&quot;[Refunds
              are accepted within 30 days…]&quot;
            </code>
          </p>
        </Section>

        <Section id="metrics" title="Metric glossary">
          <p className="text-sm text-text-secondary">
            Metrics are grouped by how they work and what they cost. Start with the
            &quot;Recommended&quot; preset; add string metrics for free signal.
          </p>
          <div className="space-y-2">
            <MetricGlossaryGroup
              label="LLM metrics"
              metrics={LLM_METRICS}
              cost="uses judge LLM — costs API calls"
            />
            <MetricGlossaryGroup
              label="NVIDIA metrics"
              metrics={NVIDIA_METRICS}
              cost="dual LLM judge"
            />
            <MetricGlossaryGroup
              label="Embedding metrics"
              metrics={EMBEDDING_METRICS}
              cost="embeddings only — cheap"
            />
            <MetricGlossaryGroup
              label="String metrics"
              metrics={STRING_METRICS}
              cost="free — instant, no LLM"
            />
            <MetricGlossaryGroup
              label="Domain metrics"
              metrics={DOMAIN_METRICS}
              cost="needs SQL / data columns"
            />
            <MetricGlossaryGroup
              label="Judge metrics"
              metrics={JUDGE_METRICS}
              cost="multiple LLM judges"
            />
          </div>
          <p className="text-xs text-text-muted">
            Grayed-out metrics in the experiment runner are missing a dataset capability — hover
            them to see exactly what&apos;s needed, or check the chips under the test-set picker.
          </p>
        </Section>

        <Section id="skills" title="Skill Arena">
          <p className="text-sm text-text-secondary leading-relaxed">
            A <strong>skill</strong> is a markdown instruction file (SKILL.md) that changes how a
            model behaves — formatting rules, tone, prohibitions, workflows. The Skill Arena
            answers: <em>does the model actually follow it?</em>
          </p>
          <p className="text-sm text-text-secondary leading-relaxed">
            Upload a skill and Tribunal extracts its testable directives. Run a trial across
            several models (plus a no-skill baseline) on a test set: each cell gets an{' '}
            <strong>adherence</strong> score (which directives were followed),{' '}
            <strong>format compliance</strong> (deterministic checks), and <strong>lift</strong>{' '}
            (improvement over the baseline). The matrix shows which model follows your skill best.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed">
            Multi-file skills (SKILL.md + references/ + scripts/) upload as a <strong>.zip</strong>.
            Run those with <strong>agentic mode</strong>: the model gets a <code>read_file</code>{' '}
            tool and pulls reference files on demand — exactly how progressive-disclosure skills
            work in a real harness. Skills that ask the user questions get an{' '}
            <code>ask_user</code> tool answered by a simulated user; add a{' '}
            <code>user_inputs</code> list to a question&apos;s metadata to script exact replies.
          </p>
        </Section>

        <Section id="feedback" title="Human feedback & judge calibration">
          <p className="text-sm text-text-secondary leading-relaxed">
            Automated judges are not perfect — so Tribunal asks you to spot-check them. On a
            completed experiment, the <strong>Human Annotation</strong> panel samples 20% of
            results for you to rate. The <strong>judge dashboard</strong> lets you mark individual
            evaluator claims as accurate or wrong; evaluators that fall below the reliability
            threshold are excluded and scores recalculate automatically. Annotations also feed{' '}
            <strong>judge calibration</strong>, which ranks judge models by agreement with you.
          </p>
        </Section>

        <Section id="faq" title="FAQ & troubleshooting">
          <div className="space-y-4">
            <Faq q="Why are some metrics grayed out?">
              The selected test set lacks a column they need (contexts, categories, turns, SQL, or
              reference data). Hover the metric for the exact reason, or re-upload your dataset
              with the missing column mapped.
            </Faq>
            <Faq q="Judge model says 'missing API key'">
              Each judge model needs its provider key (OPENAI_API_KEY, ANTHROPIC_API_KEY,
              GOOGLE_API_KEY) in the server environment. Pick a model whose key is configured, or
              add the key and restart.
            </Faq>
            <Faq q="My experiment seems stuck">
              Open the Workers page — it shows every running job with question-level progress and
              memory usage. A stuck task can be cleared there; the experiment can then be re-run.
            </Faq>
            <Faq q="Generation is slow or the worker is offline">
              Heavy jobs (knowledge graphs, test generation, experiments) can run on remote
              workers via KG_WORKER_URLS. With no workers configured everything runs on the main
              app — fine for small projects, slower for big ones.
            </Faq>
            <Faq q="What do I do with the results?">
              Start in Analyze: read the suggestions panel, apply a suggested fix (e.g. a
              guardrail snippet), re-run, and check the delta view — it tells you whether the fix
              improved, regressed, or did nothing, with confidence intervals.
            </Faq>
          </div>
          <p className="text-xs text-text-muted">
            Still stuck? The{' '}
            <Link to="/start" className="text-accent hover:underline">
              Start page
            </Link>{' '}
            tracks exactly which step of the pipeline you&apos;re on.
          </p>
        </Section>
      </div>
    </div>
  );
}

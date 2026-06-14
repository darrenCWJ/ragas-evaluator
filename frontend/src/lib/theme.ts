// Theme switching — dark ("Instrument") is the default; light is opt-in and
// persisted. Tokens live as CSS variables on :root / html[data-theme='light'].

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'tribunal-theme';

export function getTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === 'light') {
    document.documentElement.dataset.theme = 'light';
  } else {
    delete document.documentElement.dataset.theme;
  }
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // localStorage unavailable (private mode) — theme just won't persist
  }
  applyTheme(theme);
}

/** Call once before first render to avoid a theme flash. */
export function initTheme(): void {
  applyTheme(getTheme());
}

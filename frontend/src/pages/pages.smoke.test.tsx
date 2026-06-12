// Smoke tests: every page must render inside the real providers without
// crashing, both with no project selected and with a project selected while
// the API is unreachable (all fetches reject). This exercises the guard
// ("select a project") branches and the error/loading branches of every page.
import { act, render } from '@testing-library/react';
import type { ComponentType } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider } from '../contexts/AuthContext';
import { ProjectProvider } from '../contexts/ProjectContext';

// sigma requires WebGL, which jsdom does not provide — stub the graph canvas.
vi.mock('../components/kg/KGGraphView', () => ({
  default: () => null,
}));

import AnalyzePage from './AnalyzePage';
import BuildPage from './BuildPage';
import ExperimentPage from './ExperimentPage';
import KnowledgeGraphPage from './KnowledgeGraphPage';
import LoginPage from './LoginPage';
import PersonasPage from './PersonasPage';
import SetupPage from './SetupPage';
import SkillsPage from './SkillsPage';
import StartPage from './StartPage';
import TestPage from './TestPage';
import WorkersPage from './WorkersPage';

const PAGES: ReadonlyArray<[string, ComponentType]> = [
  ['AnalyzePage', AnalyzePage],
  ['BuildPage', BuildPage],
  ['ExperimentPage', ExperimentPage],
  ['KnowledgeGraphPage', KnowledgeGraphPage],
  ['LoginPage', LoginPage],
  ['PersonasPage', PersonasPage],
  ['SetupPage', SetupPage],
  ['SkillsPage', SkillsPage],
  ['StartPage', StartPage],
  ['TestPage', TestPage],
  ['WorkersPage', WorkersPage],
];

const STORAGE_KEY = 'ragas_selected_project';

function renderPage(Page: ComponentType) {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ProjectProvider>
          <Page />
        </ProjectProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

/** Flush the mount-time fetches (which all reject) and the resulting state updates. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('NetworkError: API unreachable');
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe.each(PAGES)('%s', (_name, Page) => {
  it('renders without crashing when no project is selected', async () => {
    const { container } = renderPage(Page);
    await settle();
    expect(container).toBeInTheDocument();
  });

  it('renders without crashing with a project selected and the API down', async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ id: 1, name: 'Smoke Project', description: '', created_at: '2026-01-01' }),
    );
    const { container } = renderPage(Page);
    await settle();
    expect(container).toBeInTheDocument();
  });
});

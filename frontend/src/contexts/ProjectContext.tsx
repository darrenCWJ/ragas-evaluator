import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import type { Project } from '../lib/api';

interface ProjectContextValue {
  project: Project | null;
  setProject: (p: Project) => void;
  clearProject: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

const STORAGE_KEY = 'tribunal_selected_project';
// Pre-rename key — migrated on first read, removed once the new key is written.
const LEGACY_STORAGE_KEY = 'ragas_selected_project';

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [project, setProjectState] = useState<Project | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_STORAGE_KEY);
      return stored ? (JSON.parse(stored) as Project) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (project) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    } else {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    }
  }, [project]);

  const setProject = useCallback((p: Project) => setProjectState(p), []);
  const clearProject = useCallback(() => setProjectState(null), []);

  return (
    <ProjectContext.Provider value={{ project, setProject, clearProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProject must be used within ProjectProvider');
  return ctx;
}

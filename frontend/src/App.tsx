import { Routes, Route, Navigate } from 'react-router-dom';
import { ProjectProvider } from './contexts/ProjectContext';
import ErrorBoundary from './components/ErrorBoundary';
import WorkspaceLayout from './layouts/WorkspaceLayout';
import StartPage from './pages/StartPage';
import SetupPage from './pages/SetupPage';
import BuildPage from './pages/BuildPage';
import TestPage from './pages/TestPage';
import ExperimentPage from './pages/ExperimentPage';
import AnalyzePage from './pages/AnalyzePage';
import KnowledgeGraphPage from './pages/KnowledgeGraphPage';
import PersonasPage from './pages/PersonasPage';
import SkillsPage from './pages/SkillsPage';
import WorkersPage from './pages/WorkersPage';

export default function App() {
  return (
    <ErrorBoundary>
      <ProjectProvider>
        <Routes>
          <Route element={<WorkspaceLayout />}>
            <Route index element={<Navigate to="start" replace />} />
            <Route path="start" element={<StartPage />} />
            <Route path="setup" element={<SetupPage />} />
            <Route path="build" element={<BuildPage />} />
            <Route path="test" element={<TestPage />} />
            <Route path="experiment" element={<ExperimentPage />} />
            <Route path="analyze" element={<AnalyzePage />} />
            <Route path="knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route path="personas" element={<PersonasPage />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route path="workers" element={<WorkersPage />} />
          </Route>
          <Route path="*" element={<Navigate to="start" replace />} />
        </Routes>
      </ProjectProvider>
    </ErrorBoundary>
  );
}

import { Routes, Route, Navigate } from "react-router-dom";
import { ProjectProvider } from "./contexts/ProjectContext";
import WorkspaceLayout from "./layouts/WorkspaceLayout";
import SetupPage from "./pages/SetupPage";
import BuildPage from "./pages/BuildPage";
import TestPage from "./pages/TestPage";
import ExperimentPage from "./pages/ExperimentPage";
import AnalyzePage from "./pages/AnalyzePage";
import KnowledgeGraphPage from "./pages/KnowledgeGraphPage";

export default function App() {
  return (
    <ProjectProvider>
      <Routes>
        <Route element={<WorkspaceLayout />}>
          <Route index element={<Navigate to="setup" replace />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="build" element={<BuildPage />} />
          <Route path="test" element={<TestPage />} />
          <Route path="experiment" element={<ExperimentPage />} />
          <Route path="analyze" element={<AnalyzePage />} />
          <Route path="knowledge-graph" element={<KnowledgeGraphPage />} />
        </Route>
        <Route path="*" element={<Navigate to="setup" replace />} />
      </Routes>
    </ProjectProvider>
  );
}

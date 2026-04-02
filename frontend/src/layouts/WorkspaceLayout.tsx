import { Outlet, Navigate, useLocation } from "react-router-dom";
import { useProject } from "../contexts/ProjectContext";
import Stepper from "../components/Stepper";
import ProjectSelector from "../components/ProjectSelector";

export default function WorkspaceLayout() {
  const { project } = useProject();
  const location = useLocation();

  // Route guard: redirect to setup if no project (except setup itself)
  const isSetup = location.pathname.endsWith("/setup") || location.pathname === "/app" || location.pathname === "/app/";
  if (!project && !isSetup) {
    return <Navigate to="/setup" replace />;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-base">
        {/* Logo area */}
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/20">
            <span className="text-sm font-bold text-accent">R</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-text-primary leading-tight">Ragas</div>
            <div className="text-[10px] font-medium uppercase tracking-widest text-text-muted">Platform</div>
          </div>
        </div>

        {/* Stepper nav */}
        <div className="flex-1 overflow-y-auto">
          <Stepper />
        </div>

        {/* Sidebar footer */}
        <div className="border-t border-border px-4 py-3">
          <div className="text-[10px] text-text-muted">v0.2.0</div>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-border bg-card px-6 py-3">
          <h1 className="text-sm font-medium text-text-secondary">
            Pipeline Workspace
          </h1>
          <ProjectSelector />
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto bg-deep p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

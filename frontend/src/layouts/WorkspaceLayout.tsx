import { useState, useCallback, useEffect } from "react";
import { Outlet, Navigate, useLocation } from "react-router-dom";
import { useProject } from "../contexts/ProjectContext";
import Stepper from "../components/Stepper";
import ProjectSelector from "../components/ProjectSelector";

export default function WorkspaceLayout() {
  const { project } = useProject();
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Close mobile nav on route change
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  const toggleMobileNav = useCallback(() => {
    setMobileNavOpen((prev) => !prev);
  }, []);

  // Route guard: redirect to setup if no project (except setup itself)
  const isSetup = location.pathname.endsWith("/setup") || location.pathname === "/app" || location.pathname === "/app/";
  if (!project && !isSetup) {
    return <Navigate to="/setup" replace />;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-60 shrink-0 flex-col border-r border-border bg-base">
        {/* Logo area */}
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/20">
            <span className="text-sm font-bold text-accent">R</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-text-primary leading-tight">Ragas</div>
            <div className="text-2xs font-medium uppercase tracking-widest text-text-muted">Platform</div>
          </div>
        </div>

        {/* Stepper nav */}
        <div className="flex-1 overflow-y-auto">
          <Stepper />
        </div>

        {/* Sidebar footer */}
        <div className="border-t border-border px-4 py-3">
          <div className="text-2xs text-text-muted">v0.3.3-alpha</div>
        </div>
      </aside>

      {/* Mobile drawer overlay */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-60 flex-col border-r border-border bg-base
          transition-transform duration-200
          md:hidden
          ${mobileNavOpen ? "flex translate-x-0" : "flex -translate-x-full"}
        `}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/20">
              <span className="text-sm font-bold text-accent">R</span>
            </div>
            <div>
              <div className="text-sm font-semibold text-text-primary leading-tight">Ragas</div>
              <div className="text-2xs font-medium uppercase tracking-widest text-text-muted">Platform</div>
            </div>
          </div>
          <button
            onClick={() => setMobileNavOpen(false)}
            className="rounded-md p-1 text-text-muted transition hover:bg-elevated hover:text-text-primary"
            aria-label="Close navigation"
          >
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <Stepper />
        </div>
        <div className="border-t border-border px-4 py-3">
          <div className="text-2xs text-text-muted">v0.3.3-alpha</div>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-border bg-card px-4 py-3 md:px-6">
          <div className="flex items-center gap-3">
            {/* Mobile hamburger */}
            <button
              onClick={toggleMobileNav}
              className="rounded-md p-1.5 text-text-secondary transition hover:bg-elevated hover:text-text-primary md:hidden"
              aria-label="Open navigation"
            >
              <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
              </svg>
            </button>
            <h1 className="text-sm font-medium text-text-secondary">
              Pipeline Workspace
            </h1>
          </div>
          <ProjectSelector />
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto bg-deep p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

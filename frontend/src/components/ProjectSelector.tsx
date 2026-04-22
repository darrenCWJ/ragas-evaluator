import { useState, useEffect, useRef } from "react";
import { useProject } from "../contexts/ProjectContext";
import { fetchProjects, createProject, deleteProject, type Project } from "../lib/api";

export default function ProjectSelector() {
  const { project, setProject, clearProject } = useProject();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchProjects();
      setProjects(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
        setConfirmDeleteId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (p: Project) => {
    setProject(p);
    setOpen(false);
    setCreating(false);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setSubmitting(true);
    try {
      const created = await createProject({
        name: newName.trim(),
        description: newDesc.trim(),
      });
      setProjects((prev) => [...prev, created]);
      setProject(created);
      setNewName("");
      setNewDesc("");
      setCreating(false);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (p: Project) => {
    if (confirmDeleteId !== p.id) {
      setConfirmDeleteId(p.id);
      return;
    }
    setDeleting(true);
    try {
      await deleteProject(p.id);
      setProjects((prev) => prev.filter((x) => x.id !== p.id));
      if (project?.id === p.id) clearProject();
      setConfirmDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5
                   text-sm transition-colors hover:border-border-focus hover:bg-elevated
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_6px_rgba(129,140,248,0.5)]" />
        <span className="max-w-[180px] truncate text-text-primary">
          {project ? project.name : "Select project..."}
        </span>
        <svg
          className={`h-3.5 w-3.5 text-text-muted transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-72 rounded-xl border border-border bg-card shadow-2xl shadow-black/40">
          {/* Error banner */}
          {error && (
            <div className="flex items-center justify-between border-b border-border bg-score-low/10 px-3 py-2 text-xs text-score-low">
              <span className="truncate">{error}</span>
              <button
                onClick={() => void load()}
                className="ml-2 shrink-0 rounded px-2 py-0.5 text-text-secondary hover:bg-elevated hover:text-text-primary"
              >
                Retry
              </button>
            </div>
          )}

          {/* Loading state */}
          {loading && (
            <div className="flex items-center justify-center py-6 text-sm text-text-muted">
              <span className="mr-2 inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              Loading projects...
            </div>
          )}

          {/* Project list */}
          {!loading && !creating && (
            <div className="max-h-52 overflow-y-auto py-1.5">
              {projects.length === 0 && !error && (
                <div className="px-3 py-4 text-center text-xs text-text-muted">
                  No projects yet. Create one below.
                </div>
              )}
              {projects.map((p) => (
                <div
                  key={p.id}
                  className={`group flex items-center gap-2.5 px-3 py-2 text-sm transition-colors hover:bg-elevated
                    ${project?.id === p.id ? "bg-accent-glow" : ""}`}
                >
                  <button
                    onClick={() => handleSelect(p)}
                    className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                  >
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        project?.id === p.id ? "bg-accent" : "bg-text-muted"
                      }`}
                    />
                    <div className="min-w-0">
                      <div className="truncate font-medium text-text-primary">{p.name}</div>
                      {p.description && (
                        <div className="truncate text-xs text-text-muted">{p.description}</div>
                      )}
                    </div>
                  </button>
                  {confirmDeleteId === p.id ? (
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={() => void handleDelete(p)}
                        disabled={deleting}
                        className="rounded px-1.5 py-0.5 text-xs font-medium text-score-low hover:bg-score-low/10 disabled:opacity-40"
                      >
                        {deleting ? "..." : "Delete"}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded px-1.5 py-0.5 text-xs text-text-muted hover:bg-elevated hover:text-text-primary"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(p.id)}
                      className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:bg-elevated hover:text-score-low group-hover:opacity-100"
                      title="Delete project"
                    >
                      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Create form */}
          {creating && (
            <form onSubmit={(e) => void handleCreate(e)} className="p-3">
              <div className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
                New Project
              </div>
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Project name"
                className="mb-2 w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary
                           placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
              <input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="Description (optional)"
                className="mb-3 w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary
                           placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className="flex-1 rounded-lg border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-elevated"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !newName.trim()}
                  className="flex-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-deep
                             disabled:opacity-40 hover:bg-accent/90"
                >
                  {submitting ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          )}

          {/* Footer action */}
          {!creating && !loading && (
            <div className="border-t border-border p-1.5">
              <button
                onClick={() => setCreating(true)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-accent hover:bg-elevated"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New project
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

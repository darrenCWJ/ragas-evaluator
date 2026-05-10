import { useState, useEffect, useCallback } from "react";
import {
  fetchWorkersStatus,
  clearWorkerPersonaTask,
  clearWorkerBuildTask,
  type WorkerInfo,
  type WorkerTask,
} from "../lib/api";

function elapsed(startedAt: number | undefined): string {
  if (!startedAt) return "—";
  const seconds = Math.floor(Date.now() / 1000 - startedAt);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function taskLabel(task: WorkerTask): string {
  if (task.type === "kg_build") {
    return `KG Build (${task.kg_source ?? "chunks"})`;
  }
  return `Persona Generation (${task.num_personas ?? "?"} personas)`;
}

export default function WorkersPage() {
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [configured, setConfigured] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const data = await fetchWorkersStatus();
      setWorkers(data.workers);
      setConfigured(data.total_configured);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch worker status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loop = async () => {
      while (!cancelled) {
        await poll();
        await new Promise((r) => setTimeout(r, 5000));
      }
    };
    loop();
    return () => { cancelled = true; };
  }, [poll]);

  const handleClear = async (task: WorkerTask) => {
    const key = `${task.type}-${task.project_id}`;
    setClearing(key);
    try {
      if (task.type === "persona_generation") {
        await clearWorkerPersonaTask(task.project_id);
      } else {
        await clearWorkerBuildTask(task.project_id, task.kg_source);
      }
      await poll();
    } catch {
      // Next poll will reflect the state
    } finally {
      setClearing(null);
    }
  };

  const allTasks = workers.flatMap((w) =>
    (w.tasks ?? []).map((t) => ({ ...t, workerUrl: w.url })),
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  if (configured === 0) {
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        <h1 className="text-lg font-semibold text-text-primary">Workers</h1>
        <div className="rounded-xl border border-border bg-card p-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-elevated">
            <svg className="h-6 w-6 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
            </svg>
          </div>
          <p className="text-sm text-text-secondary">
            No workers configured. Set{" "}
            <code className="rounded bg-elevated px-1.5 py-0.5 text-xs font-mono text-accent">
              KG_WORKER_URLS
            </code>{" "}
            in your environment to enable worker offloading.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Workers</h1>
        <span className="text-xs text-text-muted">
          {configured} configured &middot; auto-refreshing every 5s
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Worker cards */}
      <div className="grid gap-4 sm:grid-cols-2">
        {workers.map((w) => (
          <div
            key={w.url}
            className="rounded-xl border border-border bg-card p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    w.reachable ? "bg-emerald-400" : "bg-red-400"
                  }`}
                />
                <span className="text-sm font-medium text-text-primary truncate max-w-[200px]">
                  {w.url.replace(/^https?:\/\//, "")}
                </span>
              </div>
              {w.rss_mb != null && (
                <span className="text-xs text-text-muted">
                  {w.rss_mb} MB
                </span>
              )}
            </div>

            {!w.reachable ? (
              <p className="text-xs text-red-400">{w.error ?? "Unreachable"}</p>
            ) : (
              <div className="space-y-2">
                <div className="flex gap-4 text-xs text-text-muted">
                  <div className="flex-1">
                    <div className="flex justify-between mb-1">
                      <span>KG builds</span>
                      <span>{w.active_kg_builds ?? 0}/{w.max_concurrent_kg ?? "?"}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-elevated overflow-hidden">
                      <div
                        className="h-full rounded-full bg-accent transition-all"
                        style={{
                          width: `${Math.min(100, ((w.active_kg_builds ?? 0) / (w.max_concurrent_kg ?? 1)) * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between mb-1">
                      <span>Personas</span>
                      <span>{w.active_persona_builds ?? 0}/{w.max_concurrent_personas ?? "?"}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-elevated overflow-hidden">
                      <div
                        className="h-full rounded-full bg-purple-400 transition-all"
                        style={{
                          width: `${Math.min(100, ((w.active_persona_builds ?? 0) / (w.max_concurrent_personas ?? 1)) * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Active tasks table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-text-primary">
            Active Tasks
            {allTasks.length > 0 && (
              <span className="ml-2 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent/20 px-1.5 text-xs font-semibold text-accent">
                {allTasks.length}
              </span>
            )}
          </h2>
        </div>

        {allTasks.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-text-muted">
            No active tasks
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-muted">
                <th className="px-4 py-2 font-medium">Project</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Worker</th>
                <th className="px-4 py-2 font-medium">Elapsed</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {allTasks.map((task) => {
                const key = `${task.type}-${task.project_id}`;
                return (
                  <tr key={key} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-2.5 text-text-primary font-mono text-xs">
                      #{task.project_id}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
                          task.type === "kg_build"
                            ? "bg-accent/10 text-accent"
                            : "bg-purple-400/10 text-purple-400"
                        }`}
                      >
                        {taskLabel(task)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-text-muted text-xs truncate max-w-[140px]">
                      {task.workerUrl?.replace(/^https?:\/\//, "") ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-text-muted font-mono text-xs">
                      {elapsed(task.started_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => handleClear(task)}
                        disabled={clearing === key}
                        className="rounded-md px-2 py-1 text-xs text-red-400 transition hover:bg-red-400/10 disabled:opacity-50"
                      >
                        {clearing === key ? "Clearing..." : "Clear"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

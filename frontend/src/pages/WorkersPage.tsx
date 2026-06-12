import { useState, useEffect, useCallback } from 'react';
import {
  fetchWorkersStatus,
  clearWorkerPersonaTask,
  clearWorkerBuildTask,
  type WorkerInfo,
  type WorkerTask,
} from '../lib/api';
import UserAccountsCard from '../components/admin/UserAccountsCard';

function elapsed(startedAt: number | undefined): string {
  if (!startedAt) return '—';
  const seconds = Math.floor(Date.now() / 1000 - startedAt);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

const STAGE_LABELS: Record<string, string> = {
  building_knowledge_graph: 'Starting...',
  kg_extracting_headlines: 'Headlines',
  kg_splitting_headlines: 'Splitting',
  kg_extracting_keyphrases: 'Keyphrases',
  kg_building_overlap: 'Overlap',
  kg_extracting_summaries: 'Summaries',
  kg_embedding_summaries: 'Embedding',
  kg_filtering_nodes: 'Filtering',
  kg_extracting_themes: 'Themes',
  kg_extracting_entities: 'Entities',
  kg_building_summary_similarity: 'Similarity',
  kg_building_entity_overlap: 'Entity overlap',
  kg_combined_extraction: 'Combined extraction',
};

function taskLabel(task: WorkerTask): string {
  if (task.type === 'kg_build') {
    return `KG Build (${task.kg_source ?? 'chunks'})`;
  }
  if (task.type === 'experiment') {
    return `Experiment #${task.experiment_id ?? '?'}`;
  }
  if (task.type === 'testgen') {
    return 'Test Generation';
  }
  if (task.type === 'skill_trial') {
    return `Skill Trial${task.trial_name ? ` — ${task.trial_name}` : ''}`;
  }
  return `Persona Generation (${task.num_personas ?? '?'} personas)`;
}

function taskStatus(task: WorkerTask): string {
  if (task.type === 'kg_build' && task.stage) {
    const label = STAGE_LABELS[task.stage] ?? task.stage;
    const step =
      task.completed_steps != null ? `${task.completed_steps + 1}/${task.total_steps ?? 11}` : '';
    const batch = task.batch_total ? ` (${task.batch_current ?? 0}/${task.batch_total})` : '';
    return `${label} ${step}${batch}`.trim();
  }
  if (task.type === 'experiment') {
    const phase = task.phase ?? 'running';
    if (task.total && task.total > 0) {
      return `${phase} — ${task.current ?? 0}/${task.total} questions`;
    }
    return phase;
  }
  if (task.type === 'testgen') {
    const qs = task.questions_generated ?? 0;
    const stage = task.stage ?? 'generating';
    return qs > 0 ? `${stage} — ${qs} generated` : stage;
  }
  if (task.type === 'skill_trial') {
    const phase = task.phase ?? 'running';
    if (task.total && task.total > 0) {
      return `${phase} — ${task.current ?? 0}/${task.total} cells`;
    }
    return phase;
  }
  return '';
}

/** "What is being processed" — project name first, id as fallback. */
function taskSubject(task: WorkerTask): string {
  if (task.type === 'experiment' && !task.project_name) {
    return `Exp #${task.experiment_id}`;
  }
  return task.project_name ?? `#${task.project_id}`;
}

function CapacityCell({
  label,
  active,
  max,
  barClass,
}: {
  label: string;
  active?: number;
  max?: number;
  barClass: string;
}) {
  // A worker that doesn't run this task type reports no max — hide the cell.
  if (max == null) return null;
  return (
    <div>
      <div className="flex justify-between mb-1">
        <span>{label}</span>
        <span>
          {active ?? 0}/{max}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-elevated overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barClass}`}
          style={{ width: `${Math.min(100, ((active ?? 0) / Math.max(1, max)) * 100)}%` }}
        />
      </div>
    </div>
  );
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
      setError(err instanceof Error ? err.message : 'Failed to fetch worker status');
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
    return () => {
      cancelled = true;
    };
  }, [poll]);

  const handleClear = async (task: WorkerTask) => {
    const key = `${task.type}-${task.project_id ?? task.experiment_id}`;
    setClearing(key);
    try {
      if (task.type === 'persona_generation') {
        await clearWorkerPersonaTask(task.project_id);
      } else if (task.type === 'kg_build') {
        await clearWorkerBuildTask(task.project_id, task.kg_source);
      }
      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear worker task');
    } finally {
      setClearing(null);
    }
  };

  const allTasks = workers.flatMap((w) => (w.tasks ?? []).map((t) => ({ ...t, workerUrl: w.url })));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  const remoteCount = Math.max(0, configured - 1);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Workers</h1>
        <span className="text-xs text-text-muted">
          main app + {remoteCount} remote &middot; auto-refreshing every 5s
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {remoteCount === 0 && (
        <div className="rounded-lg border border-border bg-card px-4 py-2 text-xs text-text-muted">
          No remote workers configured — all work runs on the main app. Set{' '}
          <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-accent">
            KG_WORKER_URLS
          </code>{' '}
          to offload heavy jobs.
        </div>
      )}

      {/* Worker cards */}
      <div className="grid gap-4 sm:grid-cols-2">
        {workers.map((w) => (
          <div key={w.url} className="rounded-xl border border-border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    w.reachable ? 'bg-emerald-400' : 'bg-red-400'
                  }`}
                />
                <span className="text-sm font-medium text-text-primary truncate max-w-[200px]">
                  {w.is_local ? 'Main app (local)' : w.url.replace(/^https?:\/\//, '')}
                </span>
              </div>
              {w.rss_mb != null && (
                <span
                  className="text-xs text-text-muted"
                  title={w.peak_rss_mb != null ? `Peak: ${w.peak_rss_mb} MB` : undefined}
                >
                  {w.rss_mb} MB
                  {w.peak_rss_mb != null && (
                    <span className="text-text-muted/60"> / peak {w.peak_rss_mb}</span>
                  )}
                </span>
              )}
            </div>

            {!w.reachable ? (
              <p className="text-xs text-red-400">{w.error ?? 'Unreachable'}</p>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-3 text-xs text-text-muted">
                  <CapacityCell
                    label="KG builds"
                    active={w.active_kg_builds}
                    max={w.max_concurrent_kg}
                    barClass="bg-accent"
                  />
                  <CapacityCell
                    label="Personas"
                    active={w.active_persona_builds}
                    max={w.max_concurrent_personas}
                    barClass="bg-purple-400"
                  />
                  <CapacityCell
                    label="Experiments"
                    active={w.active_experiments}
                    max={w.max_concurrent_experiments}
                    barClass="bg-emerald-400"
                  />
                  <CapacityCell
                    label="Test gen"
                    active={w.active_testgens}
                    max={w.max_concurrent_testgens}
                    barClass="bg-amber-400"
                  />
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
          <div className="px-4 py-8 text-center text-sm text-text-muted">No active tasks</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-muted">
                <th className="px-4 py-2 font-medium">Project</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Worker</th>
                <th className="px-4 py-2 font-medium">Elapsed</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {allTasks.map((task) => {
                const key = `${task.type}-${task.project_id ?? task.experiment_id}`;
                return (
                  <tr key={key} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-2.5 text-xs text-text-primary">
                      <span className="block max-w-[160px] truncate" title={taskSubject(task)}>
                        {taskSubject(task)}
                      </span>
                      {task.project_name && (
                        <span className="font-mono text-2xs text-text-muted">
                          {task.type === 'experiment'
                            ? `exp #${task.experiment_id}`
                            : `project #${task.project_id}`}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
                          task.type === 'kg_build'
                            ? 'bg-accent/10 text-accent'
                            : task.type === 'experiment'
                              ? 'bg-emerald-400/10 text-emerald-400'
                              : task.type === 'testgen'
                                ? 'bg-amber-400/10 text-amber-400'
                                : task.type === 'skill_trial'
                                  ? 'bg-sky-400/10 text-sky-400'
                                  : 'bg-purple-400/10 text-purple-400'
                        }`}
                      >
                        {taskLabel(task)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {task.stale ? (
                        <span className="inline-flex items-center gap-1 text-amber-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                          Stale
                        </span>
                      ) : taskStatus(task) ? (
                        <span className="text-text-secondary">{taskStatus(task)}</span>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-text-muted text-xs truncate max-w-[140px]">
                      {task.workerUrl?.replace(/^https?:\/\//, '') ?? '—'}
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
                        {clearing === key ? 'Clearing...' : 'Clear'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <UserAccountsCard />
    </div>
  );
}

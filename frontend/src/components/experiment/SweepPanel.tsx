import { useState } from 'react';
import {
  cancelSweep,
  createSweep,
  deleteSweep,
  fetchSweepLeaderboard,
  fetchSweeps,
} from '../../api';
import type { RagConfig, SweepLeaderboard, TestSet } from '../../api';
import { Button, ErrorAlert, FormField, TextInput } from '../ui';
import { useFetch } from '../../hooks/useFetch';
import { usePolling } from '../../hooks/usePolling';

interface Props {
  projectId: number;
  testSets: TestSet[];
  ragConfigs: RagConfig[];
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-elevated text-text-muted',
  running: 'bg-accent/15 text-accent',
  completed: 'bg-score-high/15 text-score-high',
  completed_with_failures: 'bg-score-mid/15 text-score-mid',
  failed: 'bg-score-low/15 text-score-low',
  cancelled: 'bg-elevated text-text-muted',
};

/** Parse a comma-separated list of numbers; invalid entries are dropped. */
function parseNumberList(input: string): number[] {
  return input
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
}

function parseStringList(input: string): string[] {
  return input
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function formatParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([key, value]) => `${key}=${value}`)
    .join(', ');
}

/** Parameter sweeps: grid over retrieval params → judge-free leaderboard. */
export default function SweepPanel({ projectId, testSets, ragConfigs }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [testSetId, setTestSetId] = useState<number | ''>(testSets[0]?.id ?? '');
  const [ragConfigId, setRagConfigId] = useState<number | ''>(ragConfigs[0]?.id ?? '');
  const [topKList, setTopKList] = useState('3, 5, 10');
  const [alphaList, setAlphaList] = useState('');
  const [thresholdList, setThresholdList] = useState('');
  const [mmrList, setMmrList] = useState('');
  const [modelList, setModelList] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [boardSweepId, setBoardSweepId] = useState<number | null>(null);
  const [board, setBoard] = useState<SweepLeaderboard | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);

  const sweepsFetch = useFetch(() => fetchSweeps(projectId), [projectId]);
  const sweeps = sweepsFetch.data ?? [];
  const anyActive = sweeps.some((s) => s.status === 'pending' || s.status === 'running');

  usePolling(
    async () => {
      await sweepsFetch.reload();
      return 'continue';
    },
    5000,
    anyActive,
  );

  function buildGrid(): Record<string, unknown[]> {
    const grid: Record<string, unknown[]> = {};
    const topK = parseNumberList(topKList);
    const alpha = parseNumberList(alphaList);
    const thresholds = parseNumberList(thresholdList);
    const mmr = parseNumberList(mmrList);
    const models = parseStringList(modelList);
    if (topK.length) grid.top_k = topK;
    if (alpha.length) grid.alpha = alpha;
    if (thresholds.length) grid.score_threshold = thresholds;
    if (mmr.length) grid.mmr_lambda = mmr;
    if (models.length) grid.llm_model = models;
    return grid;
  }

  const grid = buildGrid();
  const comboCount = Object.values(grid).reduce((acc, values) => acc * values.length, 1);
  const hasGrid = Object.keys(grid).length > 0;

  async function handleCreate() {
    if (!name.trim() || testSetId === '' || ragConfigId === '' || !hasGrid) return;
    setCreating(true);
    setFormError(null);
    try {
      await createSweep(projectId, {
        name: name.trim(),
        test_set_id: testSetId as number,
        rag_config_id: ragConfigId as number,
        grid,
      });
      setName('');
      setShowForm(false);
      await sweepsFetch.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to create sweep');
    } finally {
      setCreating(false);
    }
  }

  async function handleCancel(sweepId: number) {
    setActionError(null);
    try {
      await cancelSweep(projectId, sweepId);
      await sweepsFetch.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Cancel failed');
    }
  }

  async function handleDelete(sweepId: number) {
    setActionError(null);
    try {
      await deleteSweep(projectId, sweepId);
      setConfirmDeleteId(null);
      if (boardSweepId === sweepId) setBoardSweepId(null);
      await sweepsFetch.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Delete failed');
      setConfirmDeleteId(null);
    }
  }

  async function handleToggleBoard(sweepId: number) {
    if (boardSweepId === sweepId) {
      setBoardSweepId(null);
      return;
    }
    setBoardSweepId(sweepId);
    setBoard(null);
    setBoardLoading(true);
    try {
      setBoard(await fetchSweepLeaderboard(projectId, sweepId));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to load leaderboard');
    } finally {
      setBoardLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Parameter Sweeps</h3>
          <p className="text-xs text-text-muted">
            Grid-search retrieval parameters with judge-free metrics; rank combos by retrieval hit
            rate, then judge only the finalists.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Close' : 'New Sweep'}
        </Button>
      </div>

      {showForm && (
        <div className="mb-4 space-y-3 rounded-lg border border-border/60 bg-card/40 p-4">
          <div className="grid grid-cols-2 gap-3">
            <FormField label="Name">
              <TextInput
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. top_k sweep"
              />
            </FormField>
            <FormField label="Test Set">
              <select
                value={testSetId}
                onChange={(e) => setTestSetId(e.target.value ? Number(e.target.value) : '')}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                {testSets.map((ts) => (
                  <option key={ts.id} value={ts.id}>
                    {ts.name}
                  </option>
                ))}
              </select>
            </FormField>
          </div>
          <FormField
            label="Base RAG Config"
            hint="Each combination starts from this config and overrides the swept fields"
          >
            <select
              value={ragConfigId}
              onChange={(e) => setRagConfigId(e.target.value ? Number(e.target.value) : '')}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            >
              {ragConfigs.map((rc) => (
                <option key={rc.id} value={rc.id}>
                  {rc.name}
                </option>
              ))}
            </select>
          </FormField>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="top_k values" hint="Comma-separated, e.g. 3, 5, 10">
              <TextInput value={topKList} onChange={(e) => setTopKList(e.target.value)} />
            </FormField>
            <FormField label="alpha values" hint="Hybrid weighting, e.g. 0.3, 0.5, 0.7">
              <TextInput value={alphaList} onChange={(e) => setAlphaList(e.target.value)} />
            </FormField>
            <FormField label="score_threshold values" hint="e.g. 0.2, 0.35">
              <TextInput value={thresholdList} onChange={(e) => setThresholdList(e.target.value)} />
            </FormField>
            <FormField label="mmr_lambda values" hint="e.g. 0.5, 0.7">
              <TextInput value={mmrList} onChange={(e) => setMmrList(e.target.value)} />
            </FormField>
          </div>
          <FormField label="llm_model values (optional)" hint="e.g. gpt-4o-mini, gpt-4o">
            <TextInput value={modelList} onChange={(e) => setModelList(e.target.value)} />
          </FormField>

          <div className="flex items-center justify-between">
            <span className={`text-xs ${comboCount > 36 ? 'text-score-low' : 'text-text-muted'}`}>
              {hasGrid
                ? `${comboCount} combination${comboCount !== 1 ? 's' : ''} (max 36)`
                : 'Add at least one parameter list'}
            </span>
            <Button
              onClick={handleCreate}
              loading={creating}
              disabled={
                !name.trim() ||
                testSetId === '' ||
                ragConfigId === '' ||
                !hasGrid ||
                comboCount > 36
              }
            >
              Start Sweep
            </Button>
          </div>
          <ErrorAlert message={formError} onDismiss={() => setFormError(null)} />
        </div>
      )}

      <ErrorAlert message={actionError} onDismiss={() => setActionError(null)} />
      {sweepsFetch.error && <ErrorAlert message={sweepsFetch.error} />}

      {sweeps.length === 0 ? (
        <p className="py-3 text-center text-xs text-text-muted">No sweeps yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {sweeps.map((sweep) => (
            <li key={sweep.id} className="rounded-lg bg-card px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-text-primary">
                    {sweep.name}
                  </span>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider ${STATUS_STYLES[sweep.status] ?? 'bg-elevated text-text-muted'}`}
                  >
                    {sweep.status.split('_').join(' ')}
                  </span>
                  <span className="shrink-0 text-2xs text-text-muted">
                    {Object.entries(sweep.run_counts)
                      .map(([status, count]) => `${count} ${status}`)
                      .join(' · ')}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => handleToggleBoard(sweep.id)}
                    className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
                  >
                    {boardSweepId === sweep.id ? 'Hide' : 'Leaderboard'}
                  </button>
                  {(sweep.status === 'pending' || sweep.status === 'running') && (
                    <button
                      onClick={() => handleCancel(sweep.id)}
                      className="rounded px-2 py-1 text-xs text-score-mid hover:bg-score-mid/10"
                    >
                      Cancel
                    </button>
                  )}
                  {sweep.status !== 'running' &&
                    (confirmDeleteId === sweep.id ? (
                      <span className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(sweep.id)}
                          className="rounded bg-score-low/20 px-2 py-1 text-xs text-score-low hover:bg-score-low/30"
                        >
                          Yes
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded bg-elevated px-2 py-1 text-xs text-text-secondary hover:bg-border"
                        >
                          No
                        </button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(sweep.id)}
                        className="rounded px-2 py-1 text-xs text-text-muted hover:text-score-low"
                      >
                        Delete
                      </button>
                    ))}
                </div>
              </div>

              {sweep.error_message && (
                <p className="mt-1 text-xs text-score-low">{sweep.error_message}</p>
              )}

              {boardSweepId === sweep.id && (
                <div className="mt-3 border-t border-border pt-3">
                  {boardLoading ? (
                    <p className="text-xs text-text-muted">Loading leaderboard…</p>
                  ) : board && board.leaderboard.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead>
                          <tr className="text-2xs uppercase tracking-wider text-text-muted">
                            <th className="py-1 pr-3">#</th>
                            <th className="py-1 pr-3">Params</th>
                            <th className="py-1 pr-3">Hit Rate</th>
                            <th className="py-1 pr-3">MRR</th>
                            <th className="py-1 pr-3">Overall</th>
                            <th className="py-1 pr-3">Results</th>
                            <th className="py-1">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {board.leaderboard.map((entry, idx) => (
                            <tr key={entry.run_id} className="border-t border-border/50">
                              <td className="py-1.5 pr-3 text-text-muted">{idx + 1}</td>
                              <td className="py-1.5 pr-3 font-mono text-text-primary">
                                {formatParams(entry.params)}
                              </td>
                              <td className="py-1.5 pr-3">
                                {entry.aggregate_metrics?.retrieval_hit_rate ?? '—'}
                              </td>
                              <td className="py-1.5 pr-3">
                                {entry.aggregate_metrics?.retrieval_mrr ?? '—'}
                              </td>
                              <td className="py-1.5 pr-3">{entry.overall_score ?? '—'}</td>
                              <td className="py-1.5 pr-3">{entry.result_count}</td>
                              <td className="py-1.5 text-text-muted">{entry.status}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-xs text-text-muted">No leaderboard entries yet.</p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

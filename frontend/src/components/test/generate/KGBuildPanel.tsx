import type { KGBuildProgress, KnowledgeGraphInfo } from '../../../lib/api';
import {
  ApiError,
  buildKnowledgeGraph,
  deleteKnowledgeGraph,
  fetchKGBuildProgress,
  resetKnowledgeGraph,
} from '../../../lib/api';

/** Status card shown when the knowledge graph is selected as the generation source. */
export function KgSourceInfoCard({ kgInfo }: { kgInfo: KnowledgeGraphInfo | null }) {
  return (
    <div className="sm:col-span-2">
      {kgInfo?.exists && kgInfo.is_complete ? (
        <div className="rounded-lg border border-accent/20 bg-accent/5 px-3 py-2.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-medium text-accent">Knowledge Graph ready</span>
            <span className="tabular-nums text-text-muted">
              {kgInfo.num_nodes?.toLocaleString()} nodes
            </span>
          </div>
          <p className="mt-0.5 text-text-muted">
            Node texts will be used as the generation source. The stored KG is reused directly — no
            rebuild.
          </p>
        </div>
      ) : kgInfo?.exists && !kgInfo.is_complete ? (
        <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2.5 text-xs text-yellow-400">
          Knowledge graph build is incomplete ({kgInfo.completed_steps}/{kgInfo.total_steps} steps).
          Finish building it before using it as a source.
        </div>
      ) : (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2.5 text-xs text-red-400">
          No knowledge graph found for this project. Build one in the <strong>Build</strong> tab
          first.
        </div>
      )}
    </div>
  );
}

interface DocKgStatusRowProps {
  projectId: number;
  generating: boolean;
  docKgInfo: KnowledgeGraphInfo | null;
  docKgBuilding: boolean;
  setDocKgBuilding: (building: boolean) => void;
  loadDocKgInfo: () => void;
  overlapMaxNodes: number | null;
}

/** Document KG status + build button (shown when Graph RAG uses the Documents source). */
export function DocKgStatusRow({
  projectId,
  generating,
  docKgInfo,
  docKgBuilding,
  setDocKgBuilding,
  loadDocKgInfo,
  overlapMaxNodes,
}: DocKgStatusRowProps) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border/60 bg-deep px-3 py-2 text-xs">
      {docKgBuilding ? (
        <span className="flex items-center gap-1.5 text-text-muted">
          <svg className="h-3 w-3 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          Building document KG…
        </span>
      ) : docKgInfo?.exists ? (
        <span className={docKgInfo.chunks_stale ? 'text-amber-400' : 'text-green-400'}>
          {docKgInfo.chunks_stale
            ? `Document KG stale (${docKgInfo.num_nodes ?? 0} nodes)`
            : `Document KG ready (${docKgInfo.num_nodes ?? 0} nodes)`}
        </span>
      ) : (
        <span className="text-text-muted">Document KG not built</span>
      )}
      <button
        type="button"
        disabled={generating || docKgBuilding}
        onClick={async () => {
          setDocKgBuilding(true);
          try {
            await buildKnowledgeGraph(projectId, null, overlapMaxNodes, 'documents');
            // Poll until complete
            const poll = setInterval(async () => {
              try {
                const prog = await fetchKGBuildProgress(projectId, 'documents');
                if (!prog.active) {
                  clearInterval(poll);
                  setDocKgBuilding(false);
                  loadDocKgInfo();
                }
              } catch {
                clearInterval(poll);
                setDocKgBuilding(false);
              }
            }, 3000);
          } catch {
            setDocKgBuilding(false);
          }
        }}
        className="ml-3 rounded border border-accent/40 px-2 py-0.5 text-accent transition hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {docKgInfo?.exists ? (docKgInfo.chunks_stale ? 'Rebuild' : 'Rebuild') : 'Build'}
      </button>
    </div>
  );
}

interface KGBuildPanelProps {
  projectId: number;
  chunkConfigId: number;
  generating: boolean;
  kgInfo: KnowledgeGraphInfo | null;
  setKgInfo: (info: KnowledgeGraphInfo) => void;
  kgBuilding: boolean;
  setKgBuilding: (building: boolean) => void;
  kgProgress: KGBuildProgress | null;
  overlapMaxNodes: number | null;
  setOverlapMaxNodes: (value: number | null) => void;
  fastKgMode: boolean;
  setFastKgMode: (value: boolean) => void;
  onError: (message: string | null) => void;
}

/** Chunk knowledge-graph card: info, build progress, and build/delete/reset controls. */
export default function KGBuildPanel({
  projectId,
  chunkConfigId,
  generating,
  kgInfo,
  setKgInfo,
  kgBuilding,
  setKgBuilding,
  kgProgress,
  overlapMaxNodes,
  setOverlapMaxNodes,
  fastKgMode,
  setFastKgMode,
  onError,
}: KGBuildPanelProps) {
  return (
    <div className="sm:col-span-2 rounded-lg border border-border bg-elevated/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
          Knowledge Graph
        </h4>
        {kgInfo?.exists && (
          <button
            type="button"
            onClick={async () => {
              try {
                await deleteKnowledgeGraph(projectId);
                setKgInfo({ exists: false });
              } catch {
                onError('Failed to delete knowledge graph');
              }
            }}
            disabled={generating || kgBuilding}
            className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40"
          >
            Delete
          </button>
        )}
      </div>

      {kgBuilding ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <span className="text-sm text-text-primary">
              {kgProgress?.stage === 'kg_resuming_from_checkpoint'
                ? 'Resuming from checkpoint...'
                : kgProgress?.stage === 'kg_extracting_headlines'
                  ? 'Extracting headlines...'
                  : kgProgress?.stage === 'kg_splitting_headlines'
                    ? 'Splitting headlines...'
                    : kgProgress?.stage === 'kg_extracting_keyphrases'
                      ? 'Extracting keyphrases...'
                      : kgProgress?.stage === 'kg_building_overlap'
                        ? 'Building overlap scores...'
                        : kgProgress?.stage === 'kg_filtering_nodes'
                          ? 'Filtering nodes...'
                          : kgProgress?.stage === 'kg_extracting_themes'
                            ? 'Extracting themes...'
                            : kgProgress?.stage === 'kg_extracting_entities'
                              ? 'Extracting entities...'
                              : kgProgress?.stage === 'kg_building_summary_similarity'
                                ? 'Building similarity...'
                                : kgProgress?.stage === 'kg_building_entity_overlap'
                                  ? 'Building entity overlap...'
                                  : 'Building knowledge graph...'}
            </span>
          </div>
          {kgProgress?.batch_total && kgProgress.batch_total > 1 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>
                  Batch {kgProgress.batch_current ?? 0}/{kgProgress.batch_total}
                </span>
                <span>
                  {kgProgress.nodes_processed ?? 0}/{kgProgress.nodes_total ?? 0} nodes
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-bg-tertiary overflow-hidden">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{
                    width: `${((kgProgress.nodes_processed ?? 0) / (kgProgress.nodes_total || 1)) * 100}%`,
                  }}
                />
              </div>
            </div>
          )}
          <p className="text-xs text-text-muted">
            This may take 30-60 minutes for large document sets.
          </p>
        </div>
      ) : kgInfo?.exists ? (
        <div className="text-sm text-text-secondary space-y-1">
          <p>
            {kgInfo.num_nodes} nodes from {kgInfo.num_chunks} chunks
          </p>
          <p className="text-xs text-text-muted">
            Built {kgInfo.created_at ? new Date(kgInfo.created_at).toLocaleString() : ''}
            {kgInfo.is_complete === false && ` (partial — step ${kgInfo.completed_steps ?? 0}/11)`}
          </p>
          {kgInfo.is_complete === false && (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={async () => {
                  try {
                    setKgBuilding(true);
                    await buildKnowledgeGraph(
                      projectId,
                      kgInfo.chunk_config_id ?? chunkConfigId ?? null,
                      overlapMaxNodes,
                      'chunks',
                      fastKgMode,
                    );
                  } catch (err) {
                    setKgBuilding(false);
                    onError(err instanceof ApiError ? err.message : 'Failed to resume KG build');
                  }
                }}
                className="px-3 py-1 text-xs rounded bg-accent text-white hover:bg-accent/90"
              >
                Resume Build
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await resetKnowledgeGraph(projectId);
                    setKgInfo({ exists: false });
                  } catch (err) {
                    onError(err instanceof ApiError ? err.message : 'Failed to reset KG');
                  }
                }}
                className="px-3 py-1 text-xs rounded border border-red-300 text-red-600 hover:bg-red-50"
              >
                Reset
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-text-muted">
            Pre-build a knowledge graph for faster "Full" persona generation and richer test sets.
          </p>

          {/* Fast mode toggle */}
          <label className="flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={fastKgMode}
              onChange={(e) => setFastKgMode(e.target.checked)}
              className="mt-0.5 accent-accent"
            />
            <div>
              <span className="text-xs font-medium text-text-secondary">Fast build mode</span>
              <p className="mt-0.5 text-[10px] leading-relaxed text-text-muted">
                Combines keyphrases, summary, themes, entities &amp; filter into{' '}
                <strong className="text-text-secondary">one LLM call per node</strong> instead of 5
                — roughly 3× faster. Slight quality trade-off.
              </p>
            </div>
          </label>

          <div className="flex items-center gap-3">
            <label className="text-xs text-text-secondary whitespace-nowrap">
              Overlap node cap
            </label>
            <select
              value={overlapMaxNodes === null ? 'none' : String(overlapMaxNodes)}
              onChange={(e) =>
                setOverlapMaxNodes(e.target.value === 'none' ? null : Number(e.target.value))
              }
              className="rounded border border-border bg-bg-secondary px-2 py-1 text-xs"
            >
              <option value="250">250 (~1 min)</option>
              <option value="500">500 (~3-5 min)</option>
              <option value="750">750 (~8-12 min)</option>
              <option value="1000">1000 (~15-20 min)</option>
              <option value="1500">1500 (~35-45 min)</option>
              <option value="none">No limit (can be very slow)</option>
            </select>
          </div>
          <button
            type="button"
            onClick={async () => {
              try {
                setKgBuilding(true);
                await buildKnowledgeGraph(
                  projectId,
                  chunkConfigId,
                  overlapMaxNodes,
                  'chunks',
                  fastKgMode,
                );
              } catch (err) {
                setKgBuilding(false);
                onError(err instanceof ApiError ? err.message : 'Failed to start KG build');
              }
            }}
            disabled={generating}
            className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/20 disabled:opacity-40"
          >
            Generate Knowledge Graph
          </button>
        </div>
      )}
    </div>
  );
}

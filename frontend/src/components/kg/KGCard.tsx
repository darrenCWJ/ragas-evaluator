import { useState, useEffect, useRef } from "react";
import type { KGListItem } from "../../lib/api";
import {
  buildKnowledgeGraph,
  resetKnowledgeGraph,
  rebuildKGLinks,
  updateKnowledgeGraph,
  fetchKGBuildProgress,
} from "../../lib/api";

interface KGCardProps {
  kg: KGListItem;
  onSelect: (kg: KGListItem) => void;
  onRefresh: () => void;
}

const STAGE_LABELS: Record<string, string> = {
  building_knowledge_graph: "Starting build...",
  kg_extracting_headlines: "Extracting headlines...",
  kg_splitting_headlines: "Splitting headlines...",
  kg_extracting_keyphrases: "Extracting keyphrases...",
  kg_building_overlap: "Building overlap scores...",
  kg_extracting_summaries: "Extracting summaries...",
  kg_embedding_summaries: "Embedding summaries...",
  kg_filtering_nodes: "Filtering low-quality nodes...",
  kg_extracting_themes: "Extracting themes...",
  kg_extracting_entities: "Extracting entities...",
  kg_building_summary_similarity: "Building summary similarity...",
  kg_building_entity_overlap: "Building entity overlap...",
  kg_resuming_from_checkpoint: "Resuming from checkpoint...",
  // Incremental update stages
  kg_diffing_chunks: "Comparing chunks...",
  kg_removing_old_nodes: "Removing deleted nodes...",
  kg_reindexing_nodes: "Re-indexing nodes...",
  kg_processing_new_chunks: "Processing new chunks...",
  kg_rebuilding_links: "Rebuilding links...",
  incremental_kg_extracting_headlines: "New chunks: extracting headlines...",
  incremental_kg_splitting_headlines: "New chunks: splitting headlines...",
  incremental_kg_extracting_keyphrases: "New chunks: extracting keyphrases...",
  incremental_kg_extracting_summaries: "New chunks: extracting summaries...",
  incremental_kg_filtering_nodes: "New chunks: filtering nodes...",
  incremental_kg_embedding_summaries: "New chunks: embedding summaries...",
  incremental_kg_extracting_themes: "New chunks: extracting themes...",
  incremental_kg_extracting_entities: "New chunks: extracting entities...",
};

const OVERLAP_OPTIONS = [
  { value: 250, label: "250 nodes", time: "~1 min" },
  { value: 500, label: "500 nodes", time: "~3-5 min" },
  { value: 750, label: "750 nodes", time: "~8-12 min" },
  { value: 1000, label: "1000 nodes", time: "~15-20 min" },
  { value: 1500, label: "1500 nodes", time: "~35-45 min" },
  { value: 0, label: "No limit", time: "can be slow" },
] as const;

export default function KGCard({ kg, onSelect, onRefresh }: KGCardProps) {
  const [building, setBuilding] = useState(false);
  const [buildStage, setBuildStage] = useState<string | null>(null);
  const [buildProgress, setBuildProgress] = useState<{
    batch_current?: number;
    batch_total?: number;
    nodes_processed?: number;
    nodes_total?: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRebuildLinks, setShowRebuildLinks] = useState(false);
  const [overlapMaxNodes, setOverlapMaxNodes] = useState<number | null>(500);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isComplete = kg.is_complete;
  const isPartial = !isComplete && kg.completed_steps > 0;

  // Poll progress while building
  useEffect(() => {
    if (!building) return;

    const poll = async () => {
      try {
        const progress = await fetchKGBuildProgress(kg.project_id);
        if (progress.stage) setBuildStage(progress.stage);
        if (progress.batch_total != null) {
          setBuildProgress({
            batch_current: progress.batch_current,
            batch_total: progress.batch_total,
            nodes_processed: progress.nodes_processed,
            nodes_total: progress.nodes_total,
          });
        }
        if (!progress.active && progress.is_complete) {
          setBuilding(false);
          setBuildStage(null);
          setShowRebuildLinks(false);
          onRefresh();
        }
      } catch {
        // Ignore poll errors
      }
    };

    pollRef.current = setInterval(poll, 2000);
    poll();

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [building, kg.project_id, onRefresh]);

  const handleResume = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!kg.chunk_config_id) {
      setError("Missing chunk config — rebuild from the Test page");
      return;
    }
    try {
      setError(null);
      setBuilding(true);
      await buildKnowledgeGraph(kg.project_id, kg.chunk_config_id);
    } catch (err) {
      setBuilding(false);
      setError((err as Error).message || "Failed to resume build");
    }
  };

  const handleReset = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setError(null);
      await resetKnowledgeGraph(kg.project_id);
      onRefresh();
    } catch (err) {
      setError((err as Error).message || "Failed to reset");
    }
  };

  const handleRebuildLinks = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setError(null);
      setBuilding(true);
      setBuildStage("kg_building_overlap");
      await rebuildKGLinks(kg.project_id, overlapMaxNodes);
    } catch (err) {
      setBuilding(false);
      setBuildStage(null);
      setError((err as Error).message || "Failed to rebuild links");
    }
  };

  const handleUpdate = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!kg.chunk_config_id) {
      setError("Missing chunk config — rebuild from the Test page");
      return;
    }
    try {
      setError(null);
      setBuilding(true);
      setBuildStage("kg_diffing_chunks");
      await updateKnowledgeGraph(kg.project_id, kg.chunk_config_id);
    } catch (err) {
      setBuilding(false);
      setBuildStage(null);
      setError((err as Error).message || "Failed to update KG");
    }
  };

  const statusLabel = building
    ? "Building..."
    : isComplete
      ? "Complete"
      : isPartial
        ? `Partial (${kg.completed_steps}/${kg.total_steps})`
        : "Empty";

  const statusColor = building
    ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
    : isComplete
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      : isPartial
        ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
        : "bg-red-500/15 text-red-400 border-red-500/30";

  const date = new Date(kg.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className="group relative w-full text-left rounded-xl border border-border bg-card
        p-5 transition-all duration-300
        hover:border-accent/40 hover:shadow-[0_0_24px_rgba(129,140,248,0.08)]"
    >
      {/* Glow effect on hover */}
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-accent/[0.03] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

      <div className="relative">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-text-primary truncate">
              {kg.project_name}
            </h3>
            <p className="text-micro text-text-muted mt-0.5">
              {date}
            </p>
          </div>
          <span
            className={`shrink-0 rounded-md border px-2 py-0.5 text-2xs font-medium ${statusColor}`}
          >
            {statusLabel}
          </span>
        </div>

        {/* Building progress */}
        {building && buildStage && (
          <div className="mb-3 rounded-lg bg-blue-500/5 border border-blue-500/10 px-3 py-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 shrink-0 animate-spin rounded-full border border-blue-400 border-t-transparent" />
              <span className="text-micro text-blue-300 truncate">
                {STAGE_LABELS[buildStage] ?? buildStage}
              </span>
            </div>
            {buildProgress?.batch_total != null && buildProgress.batch_total > 0 && (
              <>
                <div className="h-1 w-full rounded-full bg-blue-900/40 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-blue-400 transition-all duration-500"
                    style={{
                      width: `${Math.min(100, Math.round(((buildProgress.batch_current ?? 0) / buildProgress.batch_total) * 100))}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between text-2xs text-blue-400/60 font-mono">
                  <span>
                    {buildProgress.batch_current ?? 0}/{buildProgress.batch_total} chunks
                  </span>
                  {buildProgress.nodes_total != null && buildProgress.nodes_total > 0 && (
                    <span>{buildProgress.nodes_processed ?? 0}/{buildProgress.nodes_total} nodes</span>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mb-3 rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2">
            <span className="text-micro text-red-400">{error}</span>
          </div>
        )}

        {/* Stats grid */}
        <div className="grid grid-cols-3 gap-3">
          <StatCell label="Nodes" value={kg.num_nodes} />
          <StatCell label="Chunks" value={kg.num_chunks} />
          <StatCell
            label="Steps"
            value={`${kg.completed_steps}/${kg.total_steps}`}
          />
        </div>

        {/* Actions for partial KGs */}
        {isPartial && !building && (
          <div className="mt-4 flex items-center gap-2">
            <button
              onClick={handleResume}
              className="flex items-center gap-1.5 rounded-lg bg-accent/10 border border-accent/20 px-3 py-1.5
                text-micro font-medium text-accent transition hover:bg-accent/20"
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
              </svg>
              Resume
            </button>
            <button
              onClick={handleReset}
              className="rounded-lg border border-red-500/20 px-3 py-1.5
                text-micro font-medium text-red-400 transition hover:bg-red-500/10"
            >
              Reset
            </button>
          </div>
        )}

        {/* Stale chunks warning + update button */}
        {kg.chunks_stale && !building && (
          <div className="mt-3 rounded-lg bg-amber-500/5 border border-amber-500/15 px-3 py-2.5">
            <div className="flex items-center gap-2 mb-1.5">
              <svg className="h-3.5 w-3.5 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
              </svg>
              <span className="text-micro text-amber-300 font-medium">
                Documents changed since last build
              </span>
            </div>
            <button
              onClick={handleUpdate}
              className="w-full rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-1.5
                text-micro font-medium text-amber-300 transition hover:bg-amber-500/20"
            >
              Update KG (incremental)
            </button>
          </div>
        )}

        {/* Actions for complete KGs */}
        {isComplete && !building && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center gap-2">
              {/* Explore */}
              <button
                onClick={() => onSelect(kg)}
                className="flex items-center gap-1.5 text-micro text-text-muted transition-colors hover:text-accent"
              >
                <span>Explore graph</span>
                <svg
                  className="h-3 w-3 transition-transform group-hover:translate-x-0.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                </svg>
              </button>

              <span className="text-border">|</span>

              {/* Rebuild links toggle */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowRebuildLinks((v) => !v);
                }}
                className={`flex items-center gap-1 text-micro transition-colors ${
                  showRebuildLinks ? "text-accent" : "text-text-muted hover:text-text-secondary"
                }`}
              >
                <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
                </svg>
                <span>Rebuild links</span>
              </button>
            </div>

            {/* Rebuild links panel */}
            {showRebuildLinks && (
              <div
                className="rounded-lg border border-border bg-deep/60 p-3 space-y-2.5"
                onClick={(e) => e.stopPropagation()}
              >
                <p className="text-micro text-text-muted">
                  Re-run only the overlap/linking step with a different node cap.
                  Keeps existing headlines and keyphrases.
                </p>
                <div className="flex items-center gap-2">
                  <label className="text-micro text-text-secondary whitespace-nowrap">
                    Node cap
                  </label>
                  <select
                    value={overlapMaxNodes === null ? "0" : String(overlapMaxNodes)}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setOverlapMaxNodes(v === 0 ? null : v);
                    }}
                    className="flex-1 rounded border border-border bg-card px-2 py-1 text-micro text-text-primary"
                  >
                    {OVERLAP_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label} ({opt.time})
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={handleRebuildLinks}
                  className="w-full rounded-lg bg-accent/10 border border-accent/20 px-3 py-1.5
                    text-micro font-medium text-accent transition hover:bg-accent/20"
                >
                  Rebuild Links
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg bg-deep/60 px-3 py-2">
      <div className="text-micro text-text-muted">{label}</div>
      <div className="text-sm font-mono font-semibold text-text-primary mt-0.5">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import {
  fetchSuggestions,
  generateSuggestions,
  applySuggestionsBatch,
  fetchChunkConfigs,
  fetchEmbeddingConfigs,
  ApiError,
} from "../../lib/api";
import type {
  Suggestion,
  BatchApplyResult,
  ChunkConfig,
  EmbeddingConfig,
} from "../../lib/api";

interface Props {
  projectId: number;
  experimentId: number;
  onExperimentCreated?: () => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; suggestions: Suggestion[] };

const PRIORITY_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  high: {
    bg: "bg-red-500/15",
    text: "text-red-400",
    label: "High",
  },
  medium: {
    bg: "bg-amber-500/15",
    text: "text-amber-400",
    label: "Medium",
  },
  low: {
    bg: "bg-emerald-500/15",
    text: "text-emerald-400",
    label: "Low",
  },
};

const CATEGORY_ORDER = ["retrieval", "generation", "embedding", "chunking"];

/** Fields that need a dropdown instead of text input */
const CONFIG_ID_FIELDS = new Set(["chunk_config_id", "embedding_config_id"]);

/** Fields with fixed enum options */
const ENUM_FIELD_OPTIONS: Record<string, { value: string; label: string }[]> = {
  response_mode: [
    { value: "single_shot", label: "Single Shot" },
    { value: "multi_step", label: "Multi Step" },
  ],
  search_type: [
    { value: "dense", label: "Dense" },
    { value: "sparse", label: "Sparse" },
    { value: "hybrid", label: "Hybrid" },
  ],
};

const DROPDOWN_FIELDS = new Set([
  ...CONFIG_ID_FIELDS,
  ...Object.keys(ENUM_FIELD_OPTIONS),
]);

/** Friendly display names for raw config field names */
const FIELD_LABELS: Record<string, string> = {
  chunk_config_id: "Chunking Config",
  embedding_config_id: "Embedding Config",
  top_k: "Top K",
  alpha: "Alpha",
  max_steps: "Max Steps",
  search_type: "Search Type",
  response_mode: "Response Mode",
  system_prompt: "System Prompt",
};

function categoryLabel(cat: string): string {
  return cat.charAt(0).toUpperCase() + cat.slice(1);
}

export default function ExperimentSuggestions({
  projectId,
  experimentId,
  onExperimentCreated,
}: Props) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [generating, setGenerating] = useState(false);

  // Config options for dropdowns
  const [chunkConfigs, setChunkConfigs] = useState<ChunkConfig[]>([]);
  const [embeddingConfigs, setEmbeddingConfigs] = useState<EmbeddingConfig[]>(
    [],
  );

  // Batch apply state
  const [overrides, setOverrides] = useState<Record<number, string>>({});
  const [staged, setStaged] = useState<Set<number>>(new Set());
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const suggestions = await fetchSuggestions(projectId, experimentId);
      setState({ status: "loaded", suggestions });
    } catch (err) {
      setState({
        status: "error",
        message: (err as Error).message || "Failed to load suggestions",
      });
    }
  }, [projectId, experimentId]);

  // Load suggestions and config options
  useEffect(() => {
    load();
    fetchChunkConfigs(projectId).then(setChunkConfigs).catch(() => {});
    fetchEmbeddingConfigs(projectId).then(setEmbeddingConfigs).catch(() => {});
  }, [load, projectId]);

  // Reset batch state on experiment change
  useEffect(() => {
    setOverrides({});
    setStaged(new Set());
    setApplyError(null);
    setSuccessMsg(null);
  }, [experimentId]);

  const handleGenerate = async () => {
    setGenerating(true);
    setSuccessMsg(null);
    setApplyError(null);
    try {
      const result = await generateSuggestions(projectId, experimentId);
      setState({ status: "loaded", suggestions: result.suggestions });
      setOverrides({});
      setStaged(new Set());
    } catch (err) {
      setState({
        status: "error",
        message: (err as Error).message || "Failed to generate suggestions",
      });
    } finally {
      setGenerating(false);
    }
  };

  const toggleStaged = (id: number) => {
    setStaged((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setOverride = (id: number, value: string) => {
    setOverrides((prev) => ({ ...prev, [id]: value }));
  };

  const handleBatchApply = async () => {
    if (state.status !== "loaded" || staged.size === 0) return;

    // Validate that dropdown fields have a selection
    for (const s of state.suggestions) {
      if (
        staged.has(s.id) &&
        s.config_field &&
        DROPDOWN_FIELDS.has(s.config_field) &&
        !overrides[s.id]?.trim()
      ) {
        const label = FIELD_LABELS[s.config_field] ?? s.config_field;
        setApplyError(`Please select a value for "${label}" before applying`);
        return;
      }
    }

    setApplying(true);
    setApplyError(null);
    setSuccessMsg(null);
    try {
      const items = [...staged].map((id) => ({
        suggestion_id: id,
        override_value: overrides[id]?.trim() || undefined,
      }));
      const result: BatchApplyResult = await applySuggestionsBatch(
        projectId,
        experimentId,
        items,
      );
      const appliedIds = new Set(result.suggestions.map((s) => s.id));
      setState({
        status: "loaded",
        suggestions: state.suggestions.map((s) =>
          appliedIds.has(s.id) ? { ...s, implemented: true } : s,
        ),
      });
      setStaged(new Set());
      setSuccessMsg(
        `Created iteration experiment: ${result.new_experiment.name}`,
      );
      onExperimentCreated?.();
    } catch (err) {
      const apiErr = err as ApiError;
      setApplyError(apiErr.message || "Failed to apply suggestions");
    } finally {
      setApplying(false);
    }
  };

  /* ── Loading ── */
  if (state.status === "loading") {
    return (
      <div className="space-y-3">
        <div className="h-5 w-40 animate-pulse rounded-lg bg-elevated" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-xl bg-elevated" />
        ))}
      </div>
    );
  }

  /* ── Error ── */
  if (state.status === "error") {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-center">
        <p className="text-sm font-medium text-red-300">
          Failed to load suggestions
        </p>
        <p className="mt-1 text-xs text-red-300/70">{state.message}</p>
        <button
          onClick={load}
          className="mt-3 rounded-lg border border-red-500/30 px-4 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/20"
        >
          Retry
        </button>
      </div>
    );
  }

  const { suggestions } = state;

  const actionable = suggestions.filter(
    (s) => s.config_field && !s.implemented,
  );

  /* Group by category */
  const grouped = new Map<string, Suggestion[]>();
  for (const s of suggestions) {
    const list = grouped.get(s.category) ?? [];
    list.push(s);
    grouped.set(s.category, list);
  }
  const sortedCategories = CATEGORY_ORDER.filter((c) => grouped.has(c));
  for (const c of grouped.keys()) {
    if (!sortedCategories.includes(c)) sortedCategories.push(c);
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
          Suggestions
        </h3>
        {suggestions.length > 0 ? (
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="rounded-lg border border-border/60 px-3 py-1 text-xs font-medium text-text-secondary transition hover:bg-elevated disabled:opacity-40"
          >
            {generating ? "Regenerating..." : "Regenerate"}
          </button>
        ) : null}
      </div>

      {/* Empty — no suggestions */}
      {suggestions.length === 0 && !generating && (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
          <p className="text-sm text-text-muted">
            No suggestions yet for this experiment.
          </p>
          <button
            onClick={handleGenerate}
            className="mt-4 rounded-lg bg-accent/15 px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/25 disabled:opacity-40"
          >
            Generate Suggestions
          </button>
        </div>
      )}

      {/* Generating spinner */}
      {generating && suggestions.length === 0 && (
        <div className="flex items-center justify-center gap-2 py-8">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <span className="text-sm text-text-secondary">
            Analyzing metrics...
          </span>
        </div>
      )}

      {/* Success message */}
      {successMsg && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {successMsg}
          <span className="ml-1 text-emerald-300/60">
            (switch to Experiment page to run it)
          </span>
        </div>
      )}

      {/* Apply error */}
      {applyError && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {applyError}
        </div>
      )}

      {/* Grouped suggestions */}
      {sortedCategories.map((cat) => {
        const items = grouped.get(cat)!;
        return (
          <div key={cat} className="space-y-2">
            <div className="flex items-center gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                {categoryLabel(cat)}
              </h4>
              <span className="rounded-full bg-elevated px-2 py-0.5 text-2xs font-medium text-text-muted">
                {items.length}
              </span>
            </div>
            {items.map((s) => (
              <SuggestionCard
                key={s.id}
                suggestion={s}
                isStaged={staged.has(s.id)}
                overrideValue={overrides[s.id] ?? ""}
                onToggleStaged={() => toggleStaged(s.id)}
                onOverrideChange={(v) => setOverride(s.id, v)}
                chunkConfigs={chunkConfigs}
                embeddingConfigs={embeddingConfigs}
              />
            ))}
          </div>
        );
      })}

      {/* Batch apply bar */}
      {actionable.length > 0 && (
        <div className="sticky bottom-0 flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
          <span className="text-xs text-text-secondary">
            {staged.size} of {actionable.length} suggestion
            {actionable.length !== 1 ? "s" : ""} selected
          </span>
          <div className="flex items-center gap-2">
            {staged.size > 0 && staged.size < actionable.length && (
              <button
                onClick={() =>
                  setStaged(new Set(actionable.map((s) => s.id)))
                }
                className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:bg-elevated"
              >
                Select All
              </button>
            )}
            {staged.size === actionable.length && actionable.length > 1 && (
              <button
                onClick={() => setStaged(new Set())}
                className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:bg-elevated"
              >
                Deselect All
              </button>
            )}
            <button
              onClick={handleBatchApply}
              disabled={applying || staged.size === 0}
              className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-base transition hover:bg-accent/90 disabled:opacity-40"
            >
              {applying ? (
                <span className="flex items-center gap-1.5">
                  <span className="h-3 w-3 animate-spin rounded-full border border-base border-t-transparent" />
                  Applying...
                </span>
              ) : (
                `Apply ${staged.size} Change${staged.size !== 1 ? "s" : ""}`
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Suggestion Card ── */

interface CardProps {
  suggestion: Suggestion;
  isStaged: boolean;
  overrideValue: string;
  onToggleStaged: () => void;
  onOverrideChange: (value: string) => void;
  chunkConfigs: ChunkConfig[];
  embeddingConfigs: EmbeddingConfig[];
}

function SuggestionCard({
  suggestion: s,
  isStaged,
  overrideValue,
  onToggleStaged,
  onOverrideChange,
  chunkConfigs,
  embeddingConfigs,
}: CardProps) {
  const priority = PRIORITY_STYLES[s.priority] ?? PRIORITY_STYLES["low"]!;
  const isActionable = s.config_field && !s.implemented;
  const hasDropdown = s.config_field && DROPDOWN_FIELDS.has(s.config_field);

  // Build dropdown options
  const dropdownOptions: { value: string; label: string }[] =
    s.config_field === "chunk_config_id"
      ? chunkConfigs.map((c) => ({ value: String(c.id), label: `${c.name} (${c.method})` }))
      : s.config_field === "embedding_config_id"
        ? embeddingConfigs.map((c) => ({ value: String(c.id), label: `${c.name} (${c.model_name})` }))
        : (s.config_field ? ENUM_FIELD_OPTIONS[s.config_field] : undefined) ?? [];

  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        isStaged ? "border-accent/40 bg-accent/5" : "border-border bg-card"
      }`}
    >
      <div className="flex items-start gap-3">
        {/* Checkbox for actionable suggestions */}
        {isActionable ? (
          <button
            onClick={onToggleStaged}
            className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
              isStaged
                ? "border-accent bg-accent text-base"
                : "border-border bg-base hover:border-text-muted"
            }`}
          >
            {isStaged && (
              <svg
                className="h-3 w-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={3}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4.5 12.75l6 6 9-13.5"
                />
              </svg>
            )}
          </button>
        ) : (
          <div className="mt-0.5 w-4 shrink-0" />
        )}

        {/* Priority badge */}
        <span
          className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-2xs font-bold uppercase tracking-wider ${priority.bg} ${priority.text}`}
        >
          {priority.label}
        </span>

        <div className="min-w-0 flex-1">
          {/* Signal */}
          <p className="text-xs text-text-muted">{s.signal}</p>
          {/* Suggestion text */}
          <p className="mt-1 text-sm text-text-primary">{s.suggestion}</p>

          {/* Status / config info */}
          <div className="mt-2">
            {s.implemented ? (
              <span className="flex items-center gap-1 text-xs font-medium text-emerald-400">
                <svg
                  className="h-3.5 w-3.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4.5 12.75l6 6 9-13.5"
                  />
                </svg>
                Applied
              </span>
            ) : s.config_field ? (
              <div className="space-y-2">
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-text-muted">Adjust:</span>
                  <span className="font-medium text-text-primary">
                    {FIELD_LABELS[s.config_field!] ?? s.config_field}
                  </span>
                  {s.suggested_value && (
                    <>
                      <span className="text-text-muted">to</span>
                      <span className="font-mono text-text-primary">
                        {s.suggested_value}
                      </span>
                    </>
                  )}
                </div>
                {/* Input — shown when staged */}
                {isStaged && (
                  hasDropdown ? (
                    <select
                      value={overrideValue}
                      onChange={(e) => onOverrideChange(e.target.value)}
                      className="block w-full max-w-xs rounded-lg border border-border bg-base px-3 py-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
                    >
                      <option value="">
                        {CONFIG_ID_FIELDS.has(s.config_field!) ? "Select a config..." : "Select an option..."}
                      </option>
                      {dropdownOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={overrideValue}
                      onChange={(e) => onOverrideChange(e.target.value)}
                      placeholder={
                        s.suggested_value
                          ? `Override (default: ${s.suggested_value})`
                          : "Enter value"
                      }
                      className="block w-full max-w-xs rounded-lg border border-border bg-base px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:border-accent focus:outline-none"
                    />
                  )
                )}
              </div>
            ) : (
              <span className="text-xs italic text-text-muted">
                Manual review needed
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

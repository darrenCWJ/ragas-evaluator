import { useState, useEffect, useCallback } from "react";
import {
  fetchSuggestions,
  generateSuggestions,
  applySuggestion,
  ApiError,
} from "../../lib/api";
import type { Suggestion, ApplySuggestionResult } from "../../lib/api";

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

  useEffect(() => {
    load();
  }, [load]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const result = await generateSuggestions(projectId, experimentId);
      setState({ status: "loaded", suggestions: result.suggestions });
    } catch (err) {
      setState({
        status: "error",
        message: (err as Error).message || "Failed to generate suggestions",
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleApplied = (
    suggestionId: number,
    result: ApplySuggestionResult,
  ) => {
    if (state.status !== "loaded") return;
    setState({
      status: "loaded",
      suggestions: state.suggestions.map((s) =>
        s.id === suggestionId ? { ...s, implemented: true } : s,
      ),
    });
    onExperimentCreated?.();
    // The success message is shown inline by the SuggestionCard
    void result; // used by card component
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

  /* Group by category */
  const grouped = new Map<string, Suggestion[]>();
  for (const s of suggestions) {
    const list = grouped.get(s.category) ?? [];
    list.push(s);
    grouped.set(s.category, list);
  }
  const sortedCategories = CATEGORY_ORDER.filter((c) => grouped.has(c));
  // Include any categories not in the predefined order
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
            disabled={generating}
            className="mt-4 rounded-lg bg-accent/15 px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/25 disabled:opacity-40"
          >
            {generating ? "Generating..." : "Generate Suggestions"}
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

      {/* Empty after generate */}
      {suggestions.length === 0 && !generating && state.status === "loaded" && (
        <></>
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
              <span className="rounded-full bg-elevated px-2 py-0.5 text-[10px] font-medium text-text-muted">
                {items.length}
              </span>
            </div>
            {items.map((s) => (
              <SuggestionCard
                key={s.id}
                suggestion={s}
                projectId={projectId}
                onApplied={handleApplied}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ── Suggestion Card ── */

interface CardProps {
  suggestion: Suggestion;
  projectId: number;
  onApplied: (id: number, result: ApplySuggestionResult) => void;
}

function SuggestionCard({ suggestion: s, projectId, onApplied }: CardProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [applying, setApplying] = useState(false);
  const [overrideValue, setOverrideValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const priority = PRIORITY_STYLES[s.priority] ?? PRIORITY_STYLES["low"]!;

  const handleConfirm = async () => {
    setApplying(true);
    setError(null);
    try {
      const body = overrideValue.trim()
        ? { override_value: overrideValue.trim() }
        : undefined;
      const result = await applySuggestion(projectId, s.id, body);
      setShowConfirm(false);
      setSuccessMsg(
        `Created iteration experiment: ${result.new_experiment.name}`,
      );
      onApplied(s.id, result);
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.status === 409 && /already applied/i.test(apiErr.message)) {
        // Already implemented — update state
        setShowConfirm(false);
        onApplied(s.id, {} as ApplySuggestionResult);
      } else if (apiErr.status === 400) {
        // Validation error — keep panel open for override adjustment
        setError(apiErr.message);
      } else if (apiErr.status === 409) {
        // Other 409 (no RAG config, etc.)
        setError(apiErr.message);
        setShowConfirm(false);
      } else {
        setError(apiErr.message || "Failed to apply suggestion");
      }
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-start gap-3">
        {/* Priority badge */}
        <span
          className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${priority.bg} ${priority.text}`}
        >
          {priority.label}
        </span>

        <div className="min-w-0 flex-1">
          {/* Signal */}
          <p className="text-xs text-text-muted">{s.signal}</p>
          {/* Suggestion text */}
          <p className="mt-1 text-sm text-text-primary">{s.suggestion}</p>

          {/* Action row */}
          <div className="mt-2 flex items-center gap-2">
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
              <button
                onClick={() => {
                  setShowConfirm(true);
                  setError(null);
                }}
                disabled={applying || showConfirm}
                className="rounded-lg bg-accent/15 px-3 py-1 text-xs font-medium text-accent transition hover:bg-accent/25 disabled:opacity-40"
              >
                {applying ? (
                  <span className="flex items-center gap-1.5">
                    <span className="h-3 w-3 animate-spin rounded-full border border-accent border-t-transparent" />
                    Applying...
                  </span>
                ) : (
                  "Apply"
                )}
              </button>
            ) : (
              <span className="text-xs italic text-text-muted">
                Manual review needed
              </span>
            )}
          </div>

          {/* Success message */}
          {successMsg && (
            <div className="mt-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {successMsg}
              <span className="ml-1 text-emerald-300/60">
                (switch to Experiment page to run it)
              </span>
            </div>
          )}

          {/* Inline confirmation panel */}
          {showConfirm && !s.implemented && (
            <div className="mt-3 rounded-lg border border-accent/20 bg-accent/5 px-4 py-3">
              <p className="text-xs font-medium text-text-secondary">
                Apply suggestion
              </p>
              <div className="mt-2 space-y-1 text-xs">
                <div className="flex gap-2">
                  <span className="text-text-muted">Config field:</span>
                  <span className="font-mono text-text-primary">
                    {s.config_field}
                  </span>
                </div>
                <div className="flex gap-2">
                  <span className="text-text-muted">Suggested change:</span>
                  <span className="font-mono text-text-primary">
                    {s.suggested_value ?? "requires manual input"}
                  </span>
                </div>
              </div>

              {/* Override input */}
              <div className="mt-3">
                <label className="text-[11px] text-text-muted">
                  Override value (optional)
                </label>
                <input
                  type="text"
                  value={overrideValue}
                  onChange={(e) => setOverrideValue(e.target.value)}
                  placeholder={s.suggested_value ?? "Enter value"}
                  className="mt-1 block w-full rounded-lg border border-border bg-base px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:border-accent focus:outline-none"
                />
              </div>

              {/* Error */}
              {error && (
                <p className="mt-2 text-xs text-red-400">{error}</p>
              )}

              {/* Buttons */}
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={handleConfirm}
                  disabled={applying}
                  className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-base transition hover:bg-accent/90 disabled:opacity-40"
                >
                  {applying ? (
                    <span className="flex items-center gap-1.5">
                      <span className="h-3 w-3 animate-spin rounded-full border border-base border-t-transparent" />
                      Applying...
                    </span>
                  ) : (
                    "Confirm"
                  )}
                </button>
                <button
                  onClick={() => {
                    setShowConfirm(false);
                    setError(null);
                  }}
                  disabled={applying}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:bg-elevated disabled:opacity-40"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

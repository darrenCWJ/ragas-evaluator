import { useState, useRef, useCallback } from "react";
import { fetchExperimentHistory } from "../../lib/api";
import type { HistoryExperiment } from "../../lib/api";
import { scoreBgColor, scoreTextColor } from "./scoreUtils";

interface Props {
  projectId: number;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; experiments: HistoryExperiment[] };

const DEFAULT_VISIBLE = 10;

export default function ExperimentHistory({ projectId }: Props) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [showAll, setShowAll] = useState(false);
  const hasLoaded = useRef(false);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const experiments = await fetchExperimentHistory(projectId);
      setState({ status: "loaded", experiments });
    } catch (err) {
      setState({
        status: "error",
        message: (err as Error).message || "Failed to load history",
      });
    }
  }, [projectId]);

  const handleToggle = () => {
    const nextOpen = !open;
    setOpen(nextOpen);
    // Lazy load on first expand
    if (nextOpen && !hasLoaded.current) {
      hasLoaded.current = true;
      load();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleToggle();
    }
  };

  return (
    <section className="rounded-xl border border-border bg-card">
      {/* Disclosure header */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        className="flex cursor-pointer items-center justify-between px-5 py-4 select-none"
      >
        <div className="flex items-center gap-2">
          <svg
            className="h-4 w-4 text-text-muted"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
            History
          </span>
        </div>
        <svg
          className={`h-4 w-4 text-text-muted transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </div>

      {/* Collapsible body */}
      <div
        className={`grid transition-[grid-template-rows] duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border px-5 py-4">
            {/* Loading */}
            {state.status === "loading" && (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="h-14 animate-pulse rounded-lg bg-elevated"
                  />
                ))}
              </div>
            )}

            {/* Idle — shouldn't be visible but safe fallback */}
            {state.status === "idle" && (
              <p className="text-sm text-text-muted">Loading...</p>
            )}

            {/* Error */}
            {state.status === "error" && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-center">
                <p className="text-sm font-medium text-red-300">
                  Failed to load history
                </p>
                <p className="mt-1 text-xs text-red-300/70">{state.message}</p>
                <button
                  onClick={load}
                  className="mt-3 rounded-lg border border-red-500/30 px-4 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/20"
                >
                  Retry
                </button>
              </div>
            )}

            {/* Loaded — empty */}
            {state.status === "loaded" && state.experiments.length === 0 && (
              <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
                <p className="text-sm text-text-muted">
                  No completed experiments yet. Run an experiment to see
                  history.
                </p>
              </div>
            )}

            {/* Loaded — with data */}
            {state.status === "loaded" && state.experiments.length > 0 && (
              <div className="space-y-5">
                {/* Score trend sparkline */}
                <ScoreTrend experiments={state.experiments} />

                {/* Timeline */}
                <div className="relative pl-6">
                  {/* Vertical line */}
                  <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />

                  <div className="space-y-3">
                    {(showAll
                      ? state.experiments
                      : state.experiments.slice(0, DEFAULT_VISIBLE)
                    ).map((exp) => (
                      <TimelineEntry key={exp.id} experiment={exp} />
                    ))}
                  </div>

                  {/* Show all toggle */}
                  {state.experiments.length > DEFAULT_VISIBLE && (
                    <button
                      onClick={() => setShowAll((p) => !p)}
                      className="mt-3 ml-2 text-xs font-medium text-accent transition hover:text-accent/80"
                    >
                      {showAll
                        ? "Show less"
                        : `Show all (${state.experiments.length})`}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Score Trend Sparkline ── */

function ScoreTrend({
  experiments,
}: {
  experiments: HistoryExperiment[];
}) {
  // Show last 12 experiments, oldest on left, newest on right
  const recent = experiments.slice(0, 12).reverse();

  if (recent.length < 2) return null;

  return (
    <div className="rounded-lg border border-border/60 bg-elevated/30 px-4 py-3">
      <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
        Score Trend
      </p>
      <div className="flex items-end gap-1">
        {recent.map((exp, i) => {
          const score = exp.overall_score;
          const heightPct = score !== null ? Math.max(score * 100, 8) : 8;
          return (
            <div
              key={exp.id}
              className="flex flex-1 flex-col items-center gap-1"
            >
              {/* Bar */}
              <div
                className={`w-full max-w-[20px] rounded-t transition-all duration-300 ${
                  score !== null ? scoreBarColor(score) : "bg-border"
                }`}
                style={{ height: `${heightPct * 0.4}px` }}
                title={`${exp.name}: ${score !== null ? (score * 100).toFixed(0) + "%" : "N/A"}`}
              />
              {/* Dot */}
              <div
                className={`h-2 w-2 rounded-full ${
                  score !== null ? dotBgColor(score) : "bg-border"
                }`}
              />
              {/* Label for first/last */}
              {(i === 0 || i === recent.length - 1) && (
                <span className="mt-0.5 text-[8px] text-text-muted truncate max-w-[40px]">
                  {score !== null ? `${(score * 100).toFixed(0)}%` : "—"}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Bar color for sparkline (same thresholds, different use) */
function scoreBarColor(v: number): string {
  if (v >= 0.8) return "bg-score-high/60";
  if (v >= 0.5) return "bg-score-mid/60";
  return "bg-score-low/60";
}

function dotBgColor(v: number): string {
  if (v >= 0.8) return "bg-score-high";
  if (v >= 0.5) return "bg-score-mid";
  return "bg-score-low";
}

/* ── Timeline Entry ── */

function TimelineEntry({
  experiment,
}: {
  experiment: HistoryExperiment;
}) {
  const score = experiment.overall_score;

  // Format date
  const completedDate = experiment.completed_at
    ? new Date(experiment.completed_at)
    : null;
  const dateStr = completedDate
    ? completedDate.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Unknown date";

  return (
    <div className="relative flex items-start gap-3">
      {/* Timeline dot */}
      <div
        className={`absolute left-[-18px] top-2.5 h-3 w-3 rounded-full border-2 border-card ${
          score !== null ? dotBgColor(score) : "bg-border"
        }`}
      />

      {/* Card */}
      <div className="flex-1 rounded-lg border border-border/60 bg-elevated/30 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-text-primary">
              {experiment.name}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              {experiment.rag_config_name && (
                <>
                  <span className="text-text-muted">
                    {experiment.rag_config_name}
                  </span>
                  <span className="text-text-muted/50">&middot;</span>
                </>
              )}
              <span className="text-text-muted">{dateStr}</span>
              {experiment.result_count != null && (
                <>
                  <span className="text-text-muted/50">&middot;</span>
                  <span className="text-text-muted">
                    {experiment.result_count} questions
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Score badge */}
          {score !== null ? (
            <div
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-mono text-sm font-bold ${scoreBgColor(score)} ${scoreTextColor(score)}`}
            >
              {(score * 100).toFixed(0)}
            </div>
          ) : (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-border/30 font-mono text-sm text-text-muted">
              —
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

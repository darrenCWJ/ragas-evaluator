import { useState, useEffect, useCallback } from "react";
import { compareExperiments, ApiError } from "../../lib/api";
import type { CompareResult, CompareQuestionData } from "../../lib/api";
import {
  humanizeMetric,
  scoreBarColor,
  scoreTextColor,
} from "./scoreUtils";

interface Props {
  projectId: number;
  experimentIds: number[];
  onClose: () => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string; httpStatus?: number }
  | { status: "loaded"; data: CompareResult };

/** Experiment color palette for distinguishing bars */
const EXP_COLORS = [
  { bar: "bg-indigo-400", text: "text-indigo-300", dot: "bg-indigo-400" },
  { bar: "bg-emerald-400", text: "text-emerald-300", dot: "bg-emerald-400" },
  { bar: "bg-amber-400", text: "text-amber-300", dot: "bg-amber-400" },
  { bar: "bg-rose-400", text: "text-rose-300", dot: "bg-rose-400" },
  { bar: "bg-cyan-400", text: "text-cyan-300", dot: "bg-cyan-400" },
] as const;

function expColor(i: number) {
  return EXP_COLORS[i % EXP_COLORS.length]!;
}

export default function ExperimentCompare({
  projectId,
  experimentIds,
  onClose,
}: Props) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const data = await compareExperiments(projectId, experimentIds);
      setState({ status: "loaded", data });
    } catch (err) {
      const httpStatus =
        err instanceof ApiError ? err.status : undefined;
      setState({
        status: "error",
        message: (err as Error).message || "Failed to load comparison",
        httpStatus,
      });
    }
  }, [projectId, experimentIds]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Loading ── */
  if (state.status === "loading") {
    return (
      <div className="space-y-4">
        <div className="h-6 w-56 animate-pulse rounded-lg bg-elevated" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-xl bg-elevated"
            />
          ))}
        </div>
      </div>
    );
  }

  /* ── Error state with audit-added differentiation ── */
  if (state.status === "error") {
    const isNonRetryable =
      state.httpStatus === 409 || state.httpStatus === 413;

    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-center">
        <p className="text-sm font-medium text-red-300">
          {state.httpStatus === 409
            ? "Comparison Failed"
            : state.httpStatus === 413
              ? "Too Many Results"
              : "Failed to load comparison"}
        </p>
        <p className="mt-1 text-xs text-red-300/70">
          {state.httpStatus === 413
            ? "Too many results \u2014 select fewer experiments."
            : state.message}
        </p>
        <div className="mt-3 flex items-center justify-center gap-2">
          {!isNonRetryable && (
            <button
              onClick={load}
              className="rounded-lg border border-red-500/30 px-4 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/20"
            >
              Retry
            </button>
          )}
          <button
            onClick={onClose}
            className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-text-secondary transition hover:bg-elevated"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  const { data } = state;
  const experiments = data.experiments;

  // Collect all metric names across all experiments
  const allMetricNames = new Set<string>();
  for (const exp of experiments) {
    if (exp.aggregate_metrics) {
      for (const key of Object.keys(exp.aggregate_metrics)) {
        allMetricNames.add(key);
      }
    }
  }
  const metricNames = Array.from(allMetricNames).sort();

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-text-primary">
            Comparing {experiments.length} Experiments
          </h3>
          <div className="mt-2 flex flex-wrap gap-3">
            {experiments.map((exp, i) => (
              <div key={exp.id} className="flex items-center gap-1.5">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${expColor(i).dot}`}
                />
                <span className="text-xs text-text-secondary">{exp.name}</span>
              </div>
            ))}
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:bg-elevated hover:text-text-primary"
        >
          Close
        </button>
      </div>

      {/* ── Aggregate metrics comparison ── */}
      {metricNames.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-6 text-center">
          <p className="text-sm text-text-muted">
            No comparison data available.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5 space-y-5">
          {metricNames.map((metricName) => {
            // Get scores per experiment
            const scores = experiments.map((exp) => ({
              id: exp.id,
              name: exp.name,
              value: exp.aggregate_metrics?.[metricName] ?? null,
            }));

            // Find best score
            const validScores = scores.filter(
              (s): s is typeof s & { value: number } => s.value !== null,
            );
            const bestValue =
              validScores.length > 0
                ? Math.max(...validScores.map((s) => s.value))
                : null;

            return (
              <div key={metricName}>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                  {humanizeMetric(metricName)}
                </p>
                <div className="space-y-1.5">
                  {scores.map((score, i) => {
                    const isBest =
                      bestValue !== null && score.value === bestValue;
                    return (
                      <div
                        key={score.id}
                        className="flex items-center gap-3"
                      >
                        <span
                          className={`inline-block h-2 w-2 shrink-0 rounded-full ${expColor(i).dot}`}
                        />
                        <span className="w-28 shrink-0 truncate text-xs text-text-secondary">
                          {score.name}
                        </span>
                        <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                          {score.value !== null && (
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${expColor(i).bar} ${isBest ? "opacity-100" : "opacity-60"}`}
                              style={{
                                width: `${Math.max(score.value * 100, 1)}%`,
                              }}
                            />
                          )}
                        </div>
                        <span
                          className={`w-12 text-right font-mono text-xs font-semibold ${
                            score.value !== null
                              ? scoreTextColor(score.value)
                              : "text-text-muted"
                          }`}
                        >
                          {score.value !== null
                            ? `${(score.value * 100).toFixed(0)}%`
                            : "N/A"}
                        </span>
                        {isBest && (
                          <svg
                            className="h-3.5 w-3.5 shrink-0 text-score-high"
                            fill="currentColor"
                            viewBox="0 0 20 20"
                          >
                            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                          </svg>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Per-question comparison ── */}
      {data.questions.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
          <p className="text-sm text-text-muted">
            No per-question results available.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-text-secondary">
            Per-Question Comparison
          </h3>
          {data.questions.map((q) => (
            <CompareQuestionRow
              key={q.test_question_id}
              question={q}
              experiments={experiments}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Per-question expandable row ── */

function CompareQuestionRow({
  question,
  experiments,
}: {
  question: CompareQuestionData;
  experiments: CompareResult["experiments"];
}) {
  const [open, setOpen] = useState(false);

  const handleToggle = () => setOpen((prev) => !prev);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleToggle();
    }
  };

  // Compute per-experiment average score
  const expScores = experiments.map((exp, i) => {
    const expData = question.experiments[exp.id];
    if (!expData) return { id: exp.id, idx: i, avg: null };
    const vals = Object.values(expData.metrics).filter(
      (v): v is number => typeof v === "number",
    );
    const avg = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    return { id: exp.id, idx: i, avg };
  });

  return (
    <div className="rounded-lg border border-border bg-card transition hover:border-border-focus">
      {/* Collapsed header */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        className="flex cursor-pointer items-center gap-3 px-4 py-3 select-none"
      >
        {/* Chevron */}
        <svg
          className={`h-4 w-4 shrink-0 text-text-muted transition-transform duration-200 ${open ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9 5l7 7-7 7"
          />
        </svg>

        {/* Question text */}
        <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
          {question.question}
        </span>

        {/* Type badge */}
        <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
          {question.question_type}
        </span>

        {/* Per-experiment score dots */}
        <div className="hidden shrink-0 items-center gap-2 sm:flex">
          {expScores.map((es) => (
            <div
              key={es.id}
              className="flex items-center gap-1"
              title={`${experiments[es.idx]?.name ?? "Experiment"}: ${es.avg !== null ? (es.avg * 100).toFixed(0) + "%" : "N/A"}`}
            >
              <span
                className={`inline-block h-2 w-2 rounded-full ${expColor(es.idx).dot}`}
              />
              <span
                className={`font-mono text-[10px] font-semibold ${
                  es.avg !== null ? scoreTextColor(es.avg) : "text-text-muted"
                }`}
              >
                {es.avg !== null ? (es.avg * 100).toFixed(0) : "—"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Expanded detail */}
      <div
        className={`grid transition-[grid-template-rows] duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border px-4 py-4 space-y-5">
            {/* Reference answer */}
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Reference Answer
              </p>
              <p className="text-sm text-text-primary whitespace-pre-wrap">
                {question.reference_answer}
              </p>
            </div>

            {/* Side-by-side experiment details */}
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns: `repeat(${experiments.length}, minmax(0, 1fr))`,
              }}
            >
              {experiments.map((exp, i) => {
                const expData = question.experiments[exp.id];
                return (
                  <div
                    key={exp.id}
                    className="rounded-lg border border-border/60 bg-elevated/30 p-3 space-y-3"
                  >
                    {/* Experiment name header */}
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`inline-block h-2.5 w-2.5 rounded-full ${expColor(i).dot}`}
                      />
                      <span className="text-xs font-semibold text-text-primary truncate">
                        {exp.name}
                      </span>
                    </div>

                    {!expData ? (
                      <p className="text-xs italic text-text-muted">
                        No data for this experiment
                      </p>
                    ) : (
                      <>
                        {/* Response */}
                        <div>
                          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                            Response
                          </p>
                          {expData.response ? (
                            <p className="text-xs text-text-secondary whitespace-pre-wrap line-clamp-6">
                              {expData.response}
                            </p>
                          ) : (
                            <p className="text-xs italic text-text-muted">
                              No response
                            </p>
                          )}
                        </div>

                        {/* Contexts */}
                        {expData.retrieved_contexts.length > 0 && (
                          <div>
                            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                              Contexts ({expData.retrieved_contexts.length})
                            </p>
                            <div className="space-y-1">
                              {expData.retrieved_contexts
                                .slice(0, 3)
                                .map((ctx, ci) => (
                                  <p
                                    key={ci}
                                    className="truncate text-[10px] text-text-muted"
                                    title={ctx.content}
                                  >
                                    {ci + 1}. {ctx.content}
                                  </p>
                                ))}
                              {expData.retrieved_contexts.length > 3 && (
                                <p className="text-[10px] text-text-muted">
                                  +{expData.retrieved_contexts.length - 3} more
                                </p>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Metrics */}
                        <div>
                          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                            Metrics
                          </p>
                          <div className="space-y-1">
                            {Object.entries(expData.metrics)
                              .filter(
                                (e): e is [string, number] =>
                                  typeof e[1] === "number",
                              )
                              .sort((a, b) => b[1] - a[1])
                              .map(([name, value]) => (
                                <div
                                  key={name}
                                  className="flex items-center gap-2"
                                >
                                  <span className="w-20 shrink-0 truncate text-[10px] text-text-muted">
                                    {humanizeMetric(name)}
                                  </span>
                                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
                                    <div
                                      className={`h-full rounded-full ${scoreBarColor(value)}`}
                                      style={{
                                        width: `${Math.max(value * 100, 2)}%`,
                                      }}
                                    />
                                  </div>
                                  <span
                                    className={`w-8 text-right font-mono text-[10px] font-semibold ${scoreTextColor(value)}`}
                                  >
                                    {(value * 100).toFixed(0)}
                                  </span>
                                </div>
                              ))}
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

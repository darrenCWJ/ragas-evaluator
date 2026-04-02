import { useState, useEffect, useCallback } from "react";
import { fetchExperimentDelta, ApiError } from "../../lib/api";
import type { DeltaResult } from "../../lib/api";
import { humanizeMetric, scoreBarColor, scoreTextColor } from "./scoreUtils";

interface Props {
  projectId: number;
  experimentId: number;
}

type LoadState =
  | { status: "loading" }
  | { status: "no-baseline" }
  | { status: "error"; message: string }
  | { status: "loaded"; data: DeltaResult };

export default function ExperimentDelta({ projectId, experimentId }: Props) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const data = await fetchExperimentDelta(projectId, experimentId);
      setState({ status: "loaded", data });
    } catch (err) {
      if ((err as ApiError).status === 404) {
        setState({ status: "no-baseline" });
      } else {
        setState({
          status: "error",
          message: (err as Error).message || "Failed to load delta",
        });
      }
    }
  }, [projectId, experimentId]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Loading ── */
  if (state.status === "loading") {
    return (
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded-lg bg-elevated" />
        <div className="h-24 animate-pulse rounded-xl bg-elevated" />
      </div>
    );
  }

  /* ── No baseline (info, not error) ── */
  if (state.status === "no-baseline") {
    return (
      <div className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
          Delta Comparison
        </h3>
        <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-5 py-4">
          <p className="text-sm text-blue-300/80">
            This experiment is not an iteration — no baseline to compare
            against.
          </p>
        </div>
      </div>
    );
  }

  /* ── Error ── */
  if (state.status === "error") {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-center">
        <p className="text-sm font-medium text-red-300">
          Failed to load delta
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

  const { data } = state;
  const metricEntries = Object.entries(data.metric_deltas);

  return (
    <div className="space-y-5">
      {/* Header */}
      <h3 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
        Delta vs{" "}
        <span className="normal-case text-accent">
          {data.baseline_experiment_name}
        </span>
      </h3>

      {/* Config changes */}
      {data.config_changes.length === 0 ? (
        <p className="text-xs text-text-muted">No configuration changes.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-elevated/50">
                <th className="px-3 py-2 text-left font-medium text-text-secondary">
                  Field
                </th>
                <th className="px-3 py-2 text-left font-medium text-text-secondary">
                  Baseline
                </th>
                <th className="px-3 py-2 text-left font-medium text-text-secondary">
                  Iteration
                </th>
              </tr>
            </thead>
            <tbody>
              {data.config_changes.map((c) => (
                <tr key={c.field} className="border-b border-border/50">
                  <td className="px-3 py-2 font-medium text-text-primary">
                    {humanizeMetric(c.field)}
                  </td>
                  <td className="px-3 py-2 font-mono text-text-muted">
                    {String(c.old_value ?? "—")}
                  </td>
                  <td className="px-3 py-2 font-mono text-accent">
                    {String(c.new_value ?? "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Aggregate metric deltas */}
      {metricEntries.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Metric Deltas
          </h4>
          <div className="space-y-2.5">
            {metricEntries.map(([name, md]) => (
              <div key={name} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-text-secondary">
                    {humanizeMetric(name)}
                  </span>
                  <span className="flex items-center gap-2">
                    {md.baseline !== null && (
                      <span className="text-text-muted">
                        {(md.baseline * 100).toFixed(0)}
                      </span>
                    )}
                    <span className="text-text-muted">→</span>
                    {md.iteration !== null && (
                      <span
                        className={`font-semibold ${md.iteration !== null ? scoreTextColor(md.iteration) : ""}`}
                      >
                        {(md.iteration * 100).toFixed(0)}
                      </span>
                    )}
                    {md.delta !== null && (
                      <span
                        className={`font-mono text-[11px] font-bold ${md.improved === true ? "text-emerald-400" : md.improved === false ? "text-red-400" : "text-text-muted"}`}
                      >
                        {md.improved === true
                          ? `↑+${(md.delta * 100).toFixed(1)}`
                          : md.improved === false
                            ? `↓${(md.delta * 100).toFixed(1)}`
                            : "—"}
                      </span>
                    )}
                  </span>
                </div>
                {/* Side-by-side bars */}
                <div className="flex gap-1">
                  {md.baseline !== null && (
                    <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
                      <div
                        className={`h-full rounded-full opacity-40 ${scoreBarColor(md.baseline)}`}
                        style={{
                          width: `${Math.max(md.baseline * 100, 1)}%`,
                        }}
                      />
                    </div>
                  )}
                  {md.iteration !== null && (
                    <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
                      <div
                        className={`h-full rounded-full ${scoreBarColor(md.iteration)}`}
                        style={{
                          width: `${Math.max(md.iteration * 100, 1)}%`,
                        }}
                      />
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-question deltas */}
      {data.per_question_deltas.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Per-Question Deltas
          </h4>
          <div className="space-y-1">
            {data.per_question_deltas.map((q) => (
              <QuestionDeltaRow key={q.test_question_id} q={q} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Per-question expandable row ── */

import type { QuestionDelta as QD } from "../../lib/api";

function QuestionDeltaRow({ q }: { q: QD }) {
  const [expanded, setExpanded] = useState(false);

  const metricEntries = Object.entries(q.metrics);
  // Average delta for overall indicator
  const deltas = metricEntries
    .map(([, m]) => m.delta)
    .filter((d): d is number => d !== null);
  const avgDelta = deltas.length > 0
    ? deltas.reduce((a, b) => a + b, 0) / deltas.length
    : null;

  return (
    <div className="rounded-lg border border-border/50 bg-elevated/30">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        className="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs hover:bg-elevated/50"
      >
        <svg
          className={`h-3 w-3 shrink-0 text-text-muted transition-transform ${expanded ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M8.25 4.5l7.5 7.5-7.5 7.5"
          />
        </svg>
        <span className="min-w-0 flex-1 truncate text-text-primary">
          {q.question ?? `Question #${q.test_question_id}`}
        </span>
        {avgDelta !== null && (
          <span
            className={`shrink-0 font-mono text-[11px] font-bold ${avgDelta > 0 ? "text-emerald-400" : avgDelta < 0 ? "text-red-400" : "text-text-muted"}`}
          >
            {avgDelta > 0
              ? `↑+${(avgDelta * 100).toFixed(1)}`
              : avgDelta < 0
                ? `↓${(avgDelta * 100).toFixed(1)}`
                : "—"}
          </span>
        )}
      </div>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-2">
          <div className="space-y-1.5">
            {metricEntries.map(([name, m]) => (
              <div
                key={name}
                className="flex items-center justify-between text-[11px]"
              >
                <span className="text-text-muted">
                  {humanizeMetric(name)}
                </span>
                <span className="flex items-center gap-2">
                  <span className="text-text-muted">
                    {m.baseline !== null
                      ? (m.baseline * 100).toFixed(0)
                      : "—"}
                  </span>
                  <span className="text-text-muted">→</span>
                  <span className="text-text-primary">
                    {m.iteration !== null
                      ? (m.iteration * 100).toFixed(0)
                      : "—"}
                  </span>
                  {m.delta !== null && (
                    <span
                      className={`font-mono font-bold ${m.delta > 0 ? "text-emerald-400" : m.delta < 0 ? "text-red-400" : "text-text-muted"}`}
                    >
                      {m.delta > 0
                        ? `+${(m.delta * 100).toFixed(1)}`
                        : (m.delta * 100).toFixed(1)}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

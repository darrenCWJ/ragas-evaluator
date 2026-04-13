import { useState, useEffect, useCallback } from "react";
import {
  fetchExperiment,
  fetchExperimentResults,
  exportExperiment,
  ApiError,
} from "../../lib/api";
import type { Experiment, ExperimentResult } from "../../lib/api";
import QuestionResultRow from "./QuestionResultRow";
import MultiLLMJudgeDashboard from "./MultiLLMJudgeDashboard";
import {
  humanizeMetric,
  scoreBarColor,
  scoreBgColor,
  scoreTextColor,
} from "./scoreUtils";

interface Props {
  projectId: number;
  experimentId: number;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; experiment: Experiment; results: ExperimentResult[] };

export default function ExperimentResults({ projectId, experimentId }: Props) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [exp, results] = await Promise.all([
        fetchExperiment(projectId, experimentId),
        fetchExperimentResults(projectId, experimentId),
      ]);
      setState({ status: "loaded", experiment: exp, results });
    } catch (err) {
      setState({
        status: "error",
        message: (err as Error).message || "Failed to load results",
      });
    }
  }, [projectId, experimentId]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Export handler ── */
  const [exporting, setExporting] = useState<"csv" | "json" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExport = async (format: "csv" | "json") => {
    setExporting(format);
    setExportError(null);
    try {
      await exportExperiment(projectId, experimentId, format);
    } catch (err) {
      const apiErr = err as ApiError;
      setExportError(apiErr.message || `Failed to export ${format}`);
    } finally {
      setExporting(null);
    }
  };

  /* ── Loading skeleton ── */
  if (state.status === "loading") {
    return (
      <div className="space-y-4">
        <div className="h-6 w-48 animate-pulse rounded-lg bg-elevated" />
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-xl bg-elevated"
            />
          ))}
        </div>
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-lg bg-elevated"
            />
          ))}
        </div>
      </div>
    );
  }

  /* ── Error state with retry ── */
  if (state.status === "error") {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-center">
        <p className="text-sm font-medium text-red-300">
          Failed to load results
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

  const { experiment, results } = state;
  const hasJudge = results.some((r) => "multi_llm_judge" in r.metrics);
  const [activeTab, setActiveTab] = useState<"results" | "judge">("results");

  const agg = experiment.aggregate_metrics;

  /* Compute overall score from aggregate metrics */
  let overallScore: number | null = null;
  let metricEntries: [string, number][] = [];

  if (agg) {
    metricEntries = Object.entries(agg).filter(
      (e): e is [string, number] => e[1] !== null,
    );
    if (metricEntries.length > 0) {
      overallScore =
        metricEntries.reduce((sum, [, v]) => sum + v, 0) /
        metricEntries.length;
    }
  }

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 border-b border-border">
          <button
            onClick={() => setActiveTab("results")}
            className={`px-4 py-2 text-sm font-medium transition border-b-2 -mb-px ${
              activeTab === "results"
                ? "border-accent text-accent"
                : "border-transparent text-text-muted hover:text-text-secondary"
            }`}
          >
            Results
          </button>
          {hasJudge && (
            <button
              onClick={() => setActiveTab("judge")}
              className={`px-4 py-2 text-sm font-medium transition border-b-2 -mb-px ${
                activeTab === "judge"
                  ? "border-accent text-accent"
                  : "border-transparent text-text-muted hover:text-text-secondary"
              }`}
            >
              Judge Reliability
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">
            {results.length} question{results.length !== 1 ? "s" : ""} evaluated
          </span>
          {/* Export buttons */}
          <button
            onClick={() => handleExport("csv")}
            disabled={exporting !== null}
            className="flex items-center gap-1 rounded-lg border border-border/60 px-2.5 py-1 text-micro font-medium text-text-secondary transition hover:bg-elevated disabled:opacity-40"
          >
            {exporting === "csv" ? (
              <span className="h-3 w-3 animate-spin rounded-full border border-text-secondary border-t-transparent" />
            ) : (
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
            )}
            CSV
          </button>
          <button
            onClick={() => handleExport("json")}
            disabled={exporting !== null}
            className="flex items-center gap-1 rounded-lg border border-border/60 px-2.5 py-1 text-micro font-medium text-text-secondary transition hover:bg-elevated disabled:opacity-40"
          >
            {exporting === "json" ? (
              <span className="h-3 w-3 animate-spin rounded-full border border-text-secondary border-t-transparent" />
            ) : (
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
            )}
            JSON
          </button>
        </div>
      </div>

      {/* Export error */}
      {exportError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {exportError}
        </div>
      )}

      {/* ── Aggregate metrics ── */}
      {agg === null || agg === undefined || metricEntries.length === 0 ? (
        /* Null / empty aggregate metrics */
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-6 text-center">
          <p className="text-sm text-text-muted">
            Metrics not computed for this experiment.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5">
          {/* Overall score */}
          {overallScore !== null && (
            <div className="mb-5 flex items-center gap-4">
              <div
                className={`flex h-14 w-14 items-center justify-center rounded-2xl font-mono text-lg font-bold ${scoreBgColor(overallScore)} ${scoreTextColor(overallScore)}`}
              >
                {(overallScore * 100).toFixed(0)}
              </div>
              <div>
                <p className="text-sm font-semibold text-text-primary">
                  Overall Score
                </p>
                <p className="text-xs text-text-secondary">
                  Average across {metricEntries.length} metric
                  {metricEntries.length !== 1 ? "s" : ""}
                </p>
              </div>
            </div>
          )}

          {/* Per-metric bars */}
          <div className="space-y-3">
            {metricEntries
              .sort((a, b) => b[1] - a[1])
              .map(([name, value]) => (
                <div key={name} className="flex items-center gap-3">
                  <span className="w-36 shrink-0 truncate text-xs font-medium text-text-secondary">
                    {humanizeMetric(name)}
                  </span>
                  <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(value)}`}
                      style={{ width: `${Math.max(value * 100, 1)}%` }}
                    />
                  </div>
                  <span
                    className={`w-10 text-right font-mono text-xs font-semibold ${scoreTextColor(value)}`}
                  >
                    {(value * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {activeTab === "results" && (
        <>
          {/* ── Empty results ── */}
          {results.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
              <p className="text-sm text-text-muted">
                No per-question results available.
              </p>
            </div>
          ) : (
            /* ── Per-question results ── */
            <div className="space-y-1.5">
              {results.map((r) => (
                <QuestionResultRow
                  key={r.id}
                  result={r}
                  projectId={projectId}
                  experimentId={experimentId}
                />
              ))}
            </div>
          )}
        </>
      )}

      {activeTab === "judge" && hasJudge && (
        <MultiLLMJudgeDashboard projectId={projectId} experimentId={experimentId} />
      )}
    </div>
  );
}

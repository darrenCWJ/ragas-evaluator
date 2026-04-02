import { useState, useEffect, useRef, useCallback } from "react";
import {
  runExperimentSSE,
  fetchExperiment,
} from "../../lib/api";
import type {
  Experiment,
  ExperimentSSEHandle,
  SSEStartedEvent,
  SSEProgressEvent,
} from "../../lib/api";

interface Props {
  projectId: number;
  experiment: Experiment;
  onComplete: () => void;
}

const DEFAULT_METRICS = [
  "faithfulness",
  "answer_relevancy",
  "context_precision",
  "context_recall",
  "factual_correctness",
  "semantic_similarity",
];

const ALL_METRICS = [
  "faithfulness",
  "answer_relevancy",
  "context_precision",
  "context_recall",
  "context_entities_recall",
  "noise_sensitivity",
  "factual_correctness",
  "semantic_similarity",
];

type RunState =
  | { phase: "idle" }
  | { phase: "running"; current: number; total: number; currentQuestion: string; lastError?: string }
  | { phase: "completed"; resultCount: number }
  | { phase: "error"; message: string }
  | { phase: "connection_lost"; lastCurrent: number; lastTotal: number };

export default function ExperimentRunner({
  projectId,
  experiment,
  onComplete,
}: Props) {
  const [selectedMetrics, setSelectedMetrics] = useState<Set<string>>(
    () => new Set(DEFAULT_METRICS),
  );
  const [runState, setRunState] = useState<RunState>({ phase: "idle" });
  const [errorCount, setErrorCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const handleRef = useRef<ExperimentSSEHandle | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      handleRef.current?.abort();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startTimer = useCallback(() => {
    setElapsed(0);
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const toggleMetric = (metric: string) => {
    setSelectedMetrics((prev) => {
      const next = new Set(prev);
      if (next.has(metric)) {
        next.delete(metric);
      } else {
        next.add(metric);
      }
      return next;
    });
  };

  const handleRun = () => {
    if (selectedMetrics.size === 0) return;

    setRunState({ phase: "running", current: 0, total: 0, currentQuestion: "" });
    setErrorCount(0);
    startTimer();

    const handle = runExperimentSSE(
      projectId,
      experiment.id,
      Array.from(selectedMetrics),
      {
        onStarted: (data: SSEStartedEvent) => {
          setRunState({
            phase: "running",
            current: 0,
            total: data.total_questions,
            currentQuestion: "",
          });
        },
        onProgress: (data: SSEProgressEvent) => {
          if (data.error) {
            setErrorCount((prev) => prev + 1);
          }
          setRunState({
            phase: "running",
            current: data.current,
            total: data.total,
            currentQuestion: data.question,
            lastError: data.error || undefined,
          });
        },
        onCompleted: (data) => {
          stopTimer();
          setRunState({ phase: "completed", resultCount: data.result_count });
          onComplete();
        },
        onError: (data) => {
          stopTimer();
          setRunState({ phase: "error", message: data.message });
          onComplete();
        },
        onConnectionError: (_err, lastProgress) => {
          stopTimer();
          setRunState({
            phase: "connection_lost",
            lastCurrent: lastProgress?.current ?? 0,
            lastTotal: lastProgress?.total ?? 0,
          });
        },
      },
    );

    handleRef.current = handle;
  };

  const handleAbort = () => {
    handleRef.current?.abort();
    handleRef.current = null;
    stopTimer();
    setRunState({ phase: "idle" });
  };

  const handleRefreshStatus = async () => {
    setRefreshing(true);
    try {
      const exp = await fetchExperiment(projectId, experiment.id);
      if (exp.status === "completed" || exp.status === "failed") {
        setRunState({ phase: "idle" });
        onComplete();
      }
    } catch {
      // Stay in current state
    } finally {
      setRefreshing(false);
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div>
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-accent">
        Run Experiment
      </h3>

      {/* Idle — metric selection + run button */}
      {runState.phase === "idle" && (
        <div className="space-y-4">
          <div>
            <label className="mb-2 block text-xs font-medium text-text-secondary">
              Select Metrics
            </label>
            <div className="flex flex-wrap gap-2">
              {ALL_METRICS.map((metric) => {
                const checked = selectedMetrics.has(metric);
                return (
                  <button
                    key={metric}
                    type="button"
                    onClick={() => toggleMetric(metric)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                      checked
                        ? "border-accent/50 bg-accent/15 text-accent"
                        : "border-border bg-card text-text-muted hover:border-border-focus hover:text-text-secondary"
                    }`}
                  >
                    {metric.replace(/_/g, " ")}
                  </button>
                );
              })}
            </div>
            {selectedMetrics.size === 0 && (
              <p className="mt-1.5 text-xs text-red-400">
                Select at least one metric
              </p>
            )}
          </div>

          <button
            onClick={handleRun}
            disabled={selectedMetrics.size === 0}
            className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Run Experiment
          </button>
        </div>
      )}

      {/* Running — progress bar */}
      {runState.phase === "running" && (
        <div className="space-y-4">
          {/* Progress bar */}
          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="font-medium text-text-primary">
                {runState.total > 0
                  ? `${runState.current} / ${runState.total} questions`
                  : "Starting..."}
              </span>
              <span className="font-mono text-text-muted">
                {formatTime(elapsed)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-elevated">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{
                  width:
                    runState.total > 0
                      ? `${(runState.current / runState.total) * 100}%`
                      : "0%",
                }}
              />
            </div>
            {runState.total > 0 && (
              <p className="mt-1 text-right text-xs text-text-muted">
                {Math.round((runState.current / runState.total) * 100)}%
              </p>
            )}
          </div>

          {/* Current question */}
          {runState.currentQuestion && (
            <div className={`rounded-lg border px-3 py-2 ${
              runState.lastError
                ? "border-yellow-500/30 bg-yellow-500/5"
                : "border-border bg-card/50"
            }`}>
              <div className="flex items-center gap-1.5">
                <p className={`text-xs ${runState.lastError ? "text-yellow-400" : "text-text-muted"}`}>
                  {runState.lastError ? "Failed:" : "Evaluating:"}
                </p>
              </div>
              <p className={`mt-0.5 truncate text-sm ${
                runState.lastError ? "text-yellow-300/80" : "text-text-secondary"
              }`}>
                {runState.currentQuestion}
              </p>
            </div>
          )}

          {/* Abort */}
          <button
            onClick={handleAbort}
            className="rounded-lg border border-red-500/30 px-4 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/10"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Completed */}
      {runState.phase === "completed" && errorCount === 0 && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3">
          <p className="text-sm font-medium text-green-300">
            Experiment completed
          </p>
          <p className="mt-0.5 text-xs text-green-300/70">
            {runState.resultCount} results recorded in {formatTime(elapsed)}
          </p>
        </div>
      )}

      {/* Completed with partial failures */}
      {runState.phase === "completed" && errorCount > 0 && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3">
          <p className="text-sm font-medium text-yellow-300">
            Experiment completed with errors
          </p>
          <p className="mt-0.5 text-xs text-yellow-300/70">
            {runState.resultCount - errorCount} of {runState.resultCount} questions
            succeeded, {errorCount} failed &middot; {formatTime(elapsed)}
          </p>
        </div>
      )}

      {/* Error */}
      {runState.phase === "error" && (
        <div className="space-y-3">
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
            <p className="text-sm font-medium text-red-300">
              Experiment failed
            </p>
            <p className="mt-0.5 text-xs text-red-300/70">
              {runState.message}
            </p>
          </div>
          <button
            onClick={() => setRunState({ phase: "idle" })}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent"
          >
            Back to metrics
          </button>
        </div>
      )}

      {/* Connection lost */}
      {runState.phase === "connection_lost" && (
        <div className="space-y-3">
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3">
            <p className="text-sm font-medium text-yellow-300">
              Connection lost
            </p>
            <p className="mt-0.5 text-xs text-yellow-300/70">
              Last progress: {runState.lastCurrent} / {runState.lastTotal}{" "}
              questions completed before disconnect
            </p>
          </div>
          <button
            onClick={handleRefreshStatus}
            disabled={refreshing}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent disabled:opacity-40"
          >
            {refreshing ? "Checking..." : "Refresh Status"}
          </button>
        </div>
      )}
    </div>
  );
}

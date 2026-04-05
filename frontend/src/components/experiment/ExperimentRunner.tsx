import { useState, useEffect, useRef, useCallback } from "react";
import {
  runExperimentSSE,
  fetchExperiment,
  fetchCustomMetrics,
} from "../../lib/api";
import type {
  Experiment,
  CustomMetric,
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

const LLM_METRICS = [
  "faithfulness",
  "answer_relevancy",
  "context_precision",
  "context_recall",
  "context_entities_recall",
  "noise_sensitivity",
  "factual_correctness",
  "summarization_score",
  "aspect_critic",
  "rubrics_score",
];

const NVIDIA_METRICS = [
  "answer_accuracy",
  "context_relevance",
  "response_groundedness",
];

const EMBEDDING_METRICS = [
  "semantic_similarity",
];

const STRING_METRICS = [
  "non_llm_string_similarity",
  "bleu_score",
  "rouge_score",
  "chrf_score",
  "exact_match",
  "string_presence",
];

const METRIC_DESCRIPTIONS: Record<string, string> = {
  // LLM Metrics
  faithfulness:
    "Measures if the response is factually consistent with the retrieved context. Every claim should be supported by the context.",
  answer_relevancy:
    "Measures how relevant the response is to the user's question. Penalises incomplete or redundant answers.",
  context_precision:
    "Measures how well retrieved contexts are ranked — whether relevant chunks appear before irrelevant ones.",
  context_recall:
    "Measures how much of the reference answer can be attributed to the retrieved context. Catches missing retrieval.",
  context_entities_recall:
    "Measures the proportion of entities in the reference that also appear in the retrieved contexts.",
  noise_sensitivity:
    "Measures how much irrelevant context (noise) degrades the response quality compared to the reference.",
  factual_correctness:
    "Compares the response to a reference answer by decomposing both into claims and checking overlap.",
  summarization_score:
    "Evaluates how well a summary captures the key information from the source context.",
  aspect_critic:
    "Binary LLM judge that evaluates a specific aspect (e.g. harmfulness, correctness) and returns yes/no.",
  rubrics_score:
    "LLM judge that scores the response against user-defined rubric criteria with detailed reasoning.",
  // NVIDIA Metrics
  answer_accuracy:
    "Dual LLM-as-a-Judge that measures agreement between the response and a reference answer. Scores from two perspectives then averages.",
  context_relevance:
    "Dual LLM-as-a-Judge that evaluates whether retrieved contexts are pertinent to the query. Two independent ratings averaged.",
  response_groundedness:
    "Dual LLM-as-a-Judge that checks if every claim in the response is supported by the retrieved contexts.",
  // Embedding Metrics
  semantic_similarity:
    "Cosine similarity between embeddings of the response and the reference answer. No LLM needed.",
  // String Metrics
  non_llm_string_similarity:
    "Character-level string distance (Levenshtein) between the response and reference. Fast, no LLM needed.",
  bleu_score:
    "BLEU n-gram precision score comparing response to reference. Common in machine translation evaluation.",
  rouge_score:
    "ROUGE recall-oriented score measuring n-gram overlap between response and reference.",
  chrf_score:
    "chrF character n-gram F-score. More robust than BLEU for morphologically rich text.",
  exact_match:
    "Returns 1 if the response exactly matches the reference (after normalisation), 0 otherwise.",
  string_presence:
    "Checks whether the reference string appears anywhere in the response. Simple substring match.",
};

interface MetricGroupProps {
  label: string;
  labelClass: string;
  metrics: string[];
  selected: Set<string>;
  onToggle: (metric: string) => void;
  activeClass: string;
  inactiveClass: string;
}

function MetricGroup({ label, labelClass, metrics, selected, onToggle, activeClass, inactiveClass }: MetricGroupProps) {
  return (
    <div>
      <label className={`mb-2 block text-xs font-medium ${labelClass}`}>
        {label}
      </label>
      <div className="flex flex-wrap gap-2">
        {metrics.map((metric) => {
          const checked = selected.has(metric);
          return (
            <button
              key={metric}
              type="button"
              onClick={() => onToggle(metric)}
              title={METRIC_DESCRIPTIONS[metric]}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                checked ? activeClass : inactiveClass
              }`}
            >
              {metric.replace(/_/g, " ")}
            </button>
          );
        })}
      </div>
    </div>
  );
}

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
  const [customMetrics, setCustomMetrics] = useState<CustomMetric[]>([]);
  const [selectedMetrics, setSelectedMetrics] = useState<Set<string>>(
    () => new Set(DEFAULT_METRICS),
  );
  const [runState, setRunState] = useState<RunState>({ phase: "idle" });
  const [errorCount, setErrorCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const handleRef = useRef<ExperimentSSEHandle | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Load custom metrics for this project
  useEffect(() => {
    fetchCustomMetrics(projectId)
      .then(setCustomMetrics)
      .catch(() => setCustomMetrics([]));
  }, [projectId]);

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
          <div className="space-y-3">
            {/* LLM Metrics */}
            <MetricGroup
              label="LLM Metrics"
              labelClass="text-text-secondary"
              metrics={LLM_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-accent/50 bg-accent/15 text-accent"
              inactiveClass="border-border bg-card text-text-muted hover:border-border-focus hover:text-text-secondary"
            />

            {/* NVIDIA Metrics */}
            <MetricGroup
              label="NVIDIA Metrics"
              labelClass="text-green-400"
              metrics={NVIDIA_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-green-500/50 bg-green-500/15 text-green-400"
              inactiveClass="border-border bg-card text-text-muted hover:border-green-500/30 hover:text-text-secondary"
            />

            {/* Embedding Metrics */}
            <MetricGroup
              label="Embedding Metrics"
              labelClass="text-sky-400"
              metrics={EMBEDDING_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-sky-500/50 bg-sky-500/15 text-sky-400"
              inactiveClass="border-border bg-card text-text-muted hover:border-sky-500/30 hover:text-text-secondary"
            />

            {/* String Metrics */}
            <MetricGroup
              label="String Metrics"
              labelClass="text-amber-400"
              metrics={STRING_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-amber-500/50 bg-amber-500/15 text-amber-400"
              inactiveClass="border-border bg-card text-text-muted hover:border-amber-500/30 hover:text-text-secondary"
            />

            {/* Custom metrics */}
            {customMetrics.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-medium text-purple-400">
                  Custom Metrics
                </label>
                <div className="flex flex-wrap gap-2">
                  {customMetrics.map((cm) => {
                    const checked = selectedMetrics.has(cm.name);
                    return (
                      <button
                        key={cm.name}
                        type="button"
                        onClick={() => toggleMetric(cm.name)}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                          checked
                            ? "border-purple-500/50 bg-purple-500/15 text-purple-400"
                            : "border-border bg-card text-text-muted hover:border-purple-500/30 hover:text-text-secondary"
                        }`}
                        title={`${cm.metric_type.replace(/_/g, " ")} (${cm.min_score}–${cm.max_score})`}
                      >
                        {cm.name.replace(/_/g, " ")}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

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

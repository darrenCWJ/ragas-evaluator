import { useState, useEffect, useRef, useCallback } from "react";
import {
  runExperimentSSE,
  observeExperimentProgress,
  fetchExperiment,
  fetchProgressSnapshot,
  fetchCustomMetrics,
  fetchJudgeModels,
  fetchProject,
  updateProjectJudgeDefaults,
  cancelExperiment,
} from "../../lib/api";
import type {
  Experiment,
  CustomMetric,
  JudgeModel,
  ExperimentSSEHandle,
  SSEStartedEvent,
  SSEProgressEvent,
  SSECompletionItem,
  InFlightDetail,
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
  "instance_rubrics",
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

/** Metrics that require retrieved contexts to produce meaningful results. */
const CONTEXT_REQUIRED_METRICS = new Set([
  "faithfulness",
  "context_precision",
  "context_recall",
  "context_entities_recall",
  "noise_sensitivity",
  "summarization_score",
  "context_relevance",
  "response_groundedness",
  "aspect_critic",
  "rubrics_score",
  "instance_rubrics",
]);

const DOMAIN_METRICS = [
  "sql_semantic_equivalence",
  "datacompy_score",
];

const JUDGE_METRICS = ["multi_llm_judge"];

/** Specialized metrics that need infrastructure not yet available (multi-turn, tool calls, etc.) */
const COMING_SOON_METRICS = [
  { name: "agent_goal_accuracy", reason: "Requires multi-turn agentic conversation history" },
  { name: "topic_adherence", reason: "Requires multi-turn conversation and predefined topic list" },
  { name: "tool_call_accuracy", reason: "Requires tool/function call data from agent interactions" },
  { name: "tool_call_f1", reason: "Requires tool/function call data from agent interactions" },
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
  instance_rubrics:
    "Per-instance rubric evaluation using SingleTurnSample. Scores response against rubric criteria on a 1-5 scale, normalised to 0-1.",
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
  // Domain-Specific Metrics
  sql_semantic_equivalence:
    "Compares a generated SQL query against a reference SQL for semantic equivalence, optionally using schema context.",
  datacompy_score:
    "Compares structured/tabular data between response and reference using row-level or column-level matching.",
};

interface MetricGroupProps {
  label: string;
  labelClass: string;
  metrics: string[];
  selected: Set<string>;
  onToggle: (metric: string) => void;
  activeClass: string;
  inactiveClass: string;
  disabledMetrics?: Set<string>;
  disabledReasons?: Record<string, string>;
}

function MetricGroup({ label, labelClass, metrics, selected, onToggle, activeClass, inactiveClass, disabledMetrics, disabledReasons }: MetricGroupProps) {
  return (
    <div>
      <label className={`mb-2 block text-xs font-medium ${labelClass}`}>
        {label}
      </label>
      <div className="flex flex-wrap gap-2">
        {metrics.map((metric) => {
          const checked = selected.has(metric);
          const disabled = disabledMetrics?.has(metric) ?? false;
          const disabledReason = disabled
            ? (disabledReasons?.[metric] ?? "requires retrieved contexts (not available for this connector)")
            : null;
          return (
            <button
              key={metric}
              type="button"
              onClick={() => !disabled && onToggle(metric)}
              title={
                disabled
                  ? `${metric.replace(/_/g, " ")} — ${disabledReason}`
                  : METRIC_DESCRIPTIONS[metric]
              }
              disabled={disabled}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                disabled
                  ? "cursor-not-allowed border-border/50 bg-card/30 text-text-muted/40 line-through"
                  : checked
                    ? activeClass
                    : inactiveClass
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
  | { phase: "running"; current: number; total: number; currentQuestion: string; lastError?: string; inFlight: string[]; scoringMetrics: string[]; inFlightDetails: InFlightDetail[]; }
  | { phase: "completed"; resultCount: number }
  | { phase: "error"; message: string }
  | { phase: "connection_lost"; lastCurrent: number; lastTotal: number };

export default function ExperimentRunner({
  projectId,
  experiment,
  onComplete,
}: Props) {
  const isBotExperiment = experiment.bot_config_id != null;
  const connectorType = experiment.connector_type ?? null;
  const botReturnsContexts = experiment.bot_returns_contexts ?? false;
  const hasContexts = !isBotExperiment || botReturnsContexts || (experiment.has_reference_contexts ?? false);
  const hasRefSql = experiment.has_reference_sql ?? false;
  const hasRefData = experiment.has_reference_data ?? false;

  const disabledMetrics = (() => {
    const disabled = hasContexts ? new Set<string>() : new Set(CONTEXT_REQUIRED_METRICS);
    if (!hasRefSql) disabled.add("sql_semantic_equivalence");
    if (!hasRefData) disabled.add("datacompy_score");
    return disabled;
  })();

  const [customMetrics, setCustomMetrics] = useState<CustomMetric[]>([]);
  const [selectedMetrics, setSelectedMetrics] = useState<Set<string>>(new Set());
  const [runState, setRunState] = useState<RunState>({ phase: "idle" });
  const [errorCount, setErrorCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const handleRef = useRef<ExperimentSSEHandle | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [completedLog, setCompletedLog] = useState<SSECompletionItem[]>([]);
  const [experimentMeta, setExperimentMeta] = useState<{ name: string; model: string; testSet: string } | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const DEFAULT_RUBRICS: Record<string, string> = {
    score1_description: "The response is completely incorrect or irrelevant.",
    score2_description: "The response is partially correct but has significant errors.",
    score3_description: "The response is mostly correct but could be improved.",
    score4_description: "The response is correct and well-structured.",
    score5_description: "The response is excellent, accurate, and comprehensive.",
  };

  const isCsvExperiment = connectorType === "csv";
  const [concurrency, setConcurrency] = useState(isCsvExperiment ? 10 : isBotExperiment ? 2 : 5);
  const [rubrics, setRubrics] = useState<Record<string, string>>({ ...DEFAULT_RUBRICS });
  const [judgeEvaluators, setJudgeEvaluators] = useState(5);

  // Multi-model judge state — seed with fallback list so dropdowns are usable immediately
  const FALLBACK_MODELS: JudgeModel[] = [
    { id: "gpt-4o",                  name: "GPT-4o",                    provider: "openai",   available: true  },
    { id: "gpt-4o-mini",             name: "GPT-4o Mini",               provider: "openai",   available: true  },
    { id: "gpt-4.1",                 name: "GPT-4.1",                   provider: "openai",   available: true  },
    { id: "gpt-4.1-mini",            name: "GPT-4.1 Mini",              provider: "openai",   available: true  },
    { id: "claude-opus-4-5",         name: "Claude Opus 4.5",           provider: "anthropic",available: false },
    { id: "claude-sonnet-4-5",       name: "Claude Sonnet 4.5",         provider: "anthropic",available: false },
    { id: "claude-haiku-4-5",        name: "Claude Haiku 4.5",          provider: "anthropic",available: false },
    { id: "gemini-2.0-flash",        name: "Gemini 2.0 Flash",          provider: "gemini",   available: false },
    { id: "gemini-1.5-pro",          name: "Gemini 1.5 Pro",            provider: "gemini",   available: false },
    { id: "azure.claude-haiku-4-5",  name: "Claude Haiku 4.5 (Azure)",  provider: "gateway",  available: false },
    { id: "azure.claude-sonnet-4-5", name: "Claude Sonnet 4.5 (Azure)", provider: "gateway",  available: false },
    { id: "rsn.claude-haiku-4-5",    name: "Claude Haiku 4.5 (RSN)",    provider: "gateway",  available: false },
    { id: "rsn.claude-sonnet-4-5",   name: "Claude Sonnet 4.5 (RSN)",   provider: "gateway",  available: false },
    { id: "rsn.claude-opus-4-5",     name: "Claude Opus 4.5 (RSN)",     provider: "gateway",  available: false },
    { id: "gemini-2.5-flash",        name: "Gemini 2.5 Flash",          provider: "gateway",  available: false },
    { id: "gemini-2.5-flash-lite",   name: "Gemini 2.5 Flash Lite",     provider: "gateway",  available: false },
  ];
  const [availableModels, setAvailableModels] = useState<JudgeModel[]>(FALLBACK_MODELS);
  const [judgeModelSlots, setJudgeModelSlots] = useState<string[]>(["gpt-4o-mini", "gpt-4o-mini", "gpt-4o-mini"]);
  const [judgeTempSlots, setJudgeTempSlots] = useState<number[]>([0.3, 0.525, 0.75]);
  const [savingDefaults, setSavingDefaults] = useState(false);

  // Derived: judge selected + missing key check (placed after all useState declarations)
  const judgeSelected =
    selectedMetrics.has("multi_llm_judge") ||
    customMetrics.some((cm) => (cm.metric_type === "criteria_judge" || cm.metric_type === "reference_judge") && selectedMetrics.has(cm.name));
  const missingKeyModels = judgeSelected
    ? judgeModelSlots.filter((id) => {
        const m = availableModels.find((am) => am.id === id);
        return m ? !m.available : false;
      })
    : [];
  const hasMissingKeys = missingKeyModels.length > 0;

  const updateRubric = (key: string, value: string) => {
    setRubrics((prev) => ({ ...prev, [key]: value }));
  };

  const resetRubrics = () => {
    setRubrics({ ...DEFAULT_RUBRICS });
  };

  // Load custom metrics, available judge models, and project judge defaults
  useEffect(() => {
    fetchCustomMetrics(projectId)
      .then(setCustomMetrics)
      .catch(() => setCustomMetrics([]));
    fetchJudgeModels()
      .then((data) => setAvailableModels(data.models))
      .catch(() => setAvailableModels([]));
    fetchProject(projectId)
      .then((proj) => {
        if (proj.judge_model_assignments && proj.judge_model_assignments.length > 0) {
          setJudgeModelSlots(proj.judge_model_assignments);
          // Restore linear temperatures for the saved slots
          const n = proj.judge_model_assignments.length;
          if (n === 1) {
            setJudgeTempSlots([0.3]);
          } else {
            setJudgeTempSlots(Array.from({ length: n }, (_, i) => Math.round((0.3 + (0.45 / (n - 1)) * i) * 1000) / 1000));
          }
        }
      })
      .catch(() => {});
  }, [projectId]);

  // Auto-scroll log to bottom when new items arrive
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [completedLog.length]);

  // Cleanup on unmount — only abort the SSE observer, NOT the background task
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

  // Auto-reconnect to a running experiment on mount
  useEffect(() => {
    if (experiment.status !== "running") return;
    // Already observing
    if (handleRef.current) return;

    setRunState({ phase: "running", current: 0, total: 0, currentQuestion: "Reconnecting...", inFlight: [], scoringMetrics: [], inFlightDetails: [] });
    startTimer();

    // Pre-populate state from snapshot so the UI shows real progress immediately
    // instead of "Initializing..." until the first SSE event arrives.
    fetchProgressSnapshot(projectId, experiment.id).then((snapshot) => {
      if (!snapshot || snapshot.total === 0) return;
      setRunState((prev) => {
        if (prev.phase !== "running" || prev.total > 0) return prev;
        return {
          phase: "running",
          current: snapshot.current,
          total: snapshot.total,
          currentQuestion: snapshot.question,
          inFlight: snapshot.in_flight,
          scoringMetrics: snapshot.scoring_metrics,
          inFlightDetails: snapshot.in_flight_details,
        };
      });
    }).catch(() => {});

    const handle = observeExperimentProgress(projectId, experiment.id, {
      onStarted: (data: SSEStartedEvent) => {
        if (data.experiment_name) {
          setExperimentMeta({
            name: data.experiment_name,
            model: data.model ?? "",
            testSet: data.test_set_name ?? "",
          });
        }
        // Update total from the started event, but preserve any progress already shown
        setRunState((prev) => ({
          ...prev,
          phase: "running" as const,
          total: data.total_questions,
        } as typeof prev));
      },
      onProgress: (data: SSEProgressEvent) => {
        if (data.error) setErrorCount((prev) => prev + 1);
        if (data.new_completions?.length) {
          setCompletedLog((prev) => [...prev, ...data.new_completions!]);
        }
        setRunState({
          phase: "running",
          current: data.current,
          total: data.total,
          currentQuestion: data.question,
          lastError: data.error || undefined,
          inFlight: data.in_flight ?? [],
          scoringMetrics: data.scoring_metrics ?? [],
          inFlightDetails: data.in_flight_details ?? [],
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
    });

    handleRef.current = handle;
  }, [experiment.status, experiment.id, projectId, onComplete, startTimer, stopTimer]);

  const toggleMetric = (metric: string) => {
    if (disabledMetrics.has(metric)) return;
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

    setRunState({ phase: "running", current: 0, total: 0, currentQuestion: "", inFlight: [], scoringMetrics: [], inFlightDetails: [] });
    setErrorCount(0);
    setCompletedLog([]);
    setExperimentMeta(null);
    startTimer();

    const handle = runExperimentSSE(
      projectId,
      experiment.id,
      Array.from(selectedMetrics),
      {
        onStarted: (data: SSEStartedEvent) => {
          if (data.experiment_name) {
            setExperimentMeta({
              name: data.experiment_name,
              model: data.model ?? "",
              testSet: data.test_set_name ?? "",
            });
          }
          setRunState({
            phase: "running",
            current: 0,
            total: data.total_questions,
            currentQuestion: "",
            inFlight: [],
            scoringMetrics: [],
            inFlightDetails: [],
          });
        },
        onProgress: (data: SSEProgressEvent) => {
          if (data.error) {
            setErrorCount((prev) => prev + 1);
          }
          if (data.new_completions?.length) {
            setCompletedLog((prev) => [...prev, ...data.new_completions!]);
          }
          setRunState({
            phase: "running",
            current: data.current,
            total: data.total,
            currentQuestion: data.question,
            lastError: data.error || undefined,
            inFlight: data.in_flight ?? [],
            scoringMetrics: data.scoring_metrics ?? [],
            inFlightDetails: data.in_flight_details ?? [],
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
      selectedMetrics.has("rubrics_score") ? rubrics : null,
      concurrency,
      judgeModelSlots.length,
      judgeModelSlots,
      judgeTempSlots,
    );

    handleRef.current = handle;
  };

  const handleAbort = () => {
    // Signal the server to stop processing remaining questions
    cancelExperiment(projectId, experiment.id).catch(() => {});
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
          {!hasContexts && (
            <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-300/80">
              {connectorType
                ? `The ${connectorType} connector does not return retrieved contexts — context-dependent metrics are disabled.`
                : "No retrieved contexts available — context-dependent metrics are disabled."}
            </div>
          )}

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
              disabledMetrics={disabledMetrics}
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
              disabledMetrics={disabledMetrics}
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
              disabledMetrics={disabledMetrics}
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
              disabledMetrics={disabledMetrics}
            />

            {/* Domain-Specific Metrics */}
            <MetricGroup
              label="Domain-Specific Metrics"
              labelClass="text-teal-400"
              metrics={DOMAIN_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-teal-500/50 bg-teal-500/15 text-teal-400"
              inactiveClass="border-border bg-card text-text-muted hover:border-teal-500/30 hover:text-text-secondary"
              disabledMetrics={disabledMetrics}
              disabledReasons={{
                sql_semantic_equivalence: "no questions in this test set have reference_sql metadata",
                datacompy_score: "no questions in this test set have reference_data metadata",
              }}
            />

            {/* Judge Metrics */}
            <MetricGroup
              label="Judge Metrics"
              labelClass="text-violet-400"
              metrics={JUDGE_METRICS}
              selected={selectedMetrics}
              onToggle={toggleMetric}
              activeClass="border-violet-500/50 bg-violet-500/15 text-violet-400"
              inactiveClass="border-border bg-card text-text-muted hover:border-violet-500/30 hover:text-text-secondary"
            />

            {/* Coming Soon — specialized metrics */}
            <div>
              <label className="mb-2 block text-xs font-medium text-text-muted">
                Specialized Metrics <span className="font-normal">(coming soon)</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {COMING_SOON_METRICS.map((m) => (
                  <button
                    key={m.name}
                    type="button"
                    disabled
                    title={m.reason}
                    className="cursor-not-allowed rounded-lg border border-border/30 bg-card/20 px-3 py-1.5 text-xs font-medium text-text-muted/40 line-through"
                  >
                    {m.name.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>

            {/* Custom metrics */}
            {customMetrics.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-medium text-purple-400">
                  Custom Metrics
                </label>
                <div className="flex flex-wrap gap-2">
                  {customMetrics.map((cm) => {
                    const checked = selectedMetrics.has(cm.name);
                    const needsContexts = cm.metric_type === "rubrics" || cm.metric_type === "instance_rubrics";
                    const disabled = needsContexts && !hasContexts;
                    return (
                      <button
                        key={cm.name}
                        type="button"
                        onClick={() => !disabled && toggleMetric(cm.name)}
                        disabled={disabled}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                          disabled
                            ? "cursor-not-allowed border-border/50 bg-card/30 text-text-muted/40 line-through"
                            : checked
                              ? "border-purple-500/50 bg-purple-500/15 text-purple-400"
                              : "border-border bg-card text-text-muted hover:border-purple-500/30 hover:text-text-secondary"
                        }`}
                        title={
                          disabled
                            ? `${cm.name.replace(/_/g, " ")} — requires retrieved contexts (not available for this connector)`
                            : `${cm.metric_type.replace(/_/g, " ")} (${cm.min_score}–${cm.max_score})`
                        }
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

          {/* Rubric editor — shown when rubrics_score is selected */}
          {selectedMetrics.has("rubrics_score") && (
            <div className="rounded-lg border border-accent/20 bg-accent/5 p-4">
              <div className="mb-3 flex items-center justify-between">
                <label className="text-xs font-medium text-accent">
                  Rubric Criteria (1–5 scale)
                </label>
                <button
                  type="button"
                  onClick={resetRubrics}
                  className="text-xs text-text-muted transition hover:text-accent"
                >
                  Reset to defaults
                </button>
              </div>
              <div className="space-y-2">
                {([1, 2, 3, 4, 5] as const).map((n) => {
                  const key = `score${n}_description`;
                  return (
                    <div key={key} className="flex items-start gap-2">
                      <span className="mt-1.5 w-5 shrink-0 text-center text-xs font-bold text-text-muted">
                        {n}
                      </span>
                      <input
                        type="text"
                        value={rubrics[key] ?? ""}
                        onChange={(e) => updateRubric(key, e.target.value)}
                        className="flex-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                        placeholder={`Describe what a score of ${n} means...`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* LLM Judge Settings — shown when multi_llm_judge, criteria_judge, or reference_judge is selected */}
          {(selectedMetrics.has("multi_llm_judge") || customMetrics.some((cm) => (cm.metric_type === "criteria_judge" || cm.metric_type === "reference_judge") && selectedMetrics.has(cm.name))) && (
            <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-4 py-3 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-violet-400">LLM Judge Settings</p>
                <button
                  type="button"
                  onClick={async () => {
                    setSavingDefaults(true);
                    try {
                      await updateProjectJudgeDefaults(projectId, judgeModelSlots);
                    } finally {
                      setSavingDefaults(false);
                    }
                  }}
                  disabled={savingDefaults}
                  className="text-2xs text-violet-400/70 hover:text-violet-400 transition disabled:opacity-40"
                >
                  {savingDefaults ? "Saving..." : "Save as project default"}
                </button>
              </div>

              {/* Per-slot model selectors */}
              <div className="space-y-2">
                {/* Column headers */}
                <div className="flex items-center gap-2">
                  <span className="w-20 shrink-0" />
                  <span className="flex-1 text-2xs font-medium text-text-muted">Model</span>
                  <span className="w-16 shrink-0 text-center text-2xs font-medium text-text-muted">Temp</span>
                  {judgeModelSlots.length > 1 && <span className="w-5 shrink-0" />}
                </div>
                {judgeModelSlots.map((modelId, i) => {
                  const model = availableModels.find(m => m.id === modelId);
                  const unavailable = model ? !model.available : false;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span className="w-20 shrink-0 text-2xs text-text-muted">Evaluator {i + 1}</span>
                      <select
                        value={modelId}
                        onChange={(e) => {
                          const next = [...judgeModelSlots];
                          next[i] = e.target.value;
                          setJudgeModelSlots(next);
                        }}
                        className="flex-1 rounded-lg border border-border bg-input px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-violet-500/50"
                      >
                        {availableModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}{!m.available ? " ⚠ No API key" : ""}
                          </option>
                        ))}
                      </select>
                      {unavailable && (
                        <span className="shrink-0 text-2xs text-yellow-500">⚠ key missing</span>
                      )}
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={judgeTempSlots[i] ?? 0.5}
                        onChange={(e) => {
                          const next = [...judgeTempSlots];
                          next[i] = Math.min(1, Math.max(0, parseFloat(e.target.value) || 0));
                          setJudgeTempSlots(next);
                        }}
                        className="w-16 shrink-0 rounded-lg border border-border bg-input px-2 py-1.5 text-center text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-violet-500/50"
                        title="Temperature (0–1)"
                      />
                      {judgeModelSlots.length > 1 && (
                        <button
                          type="button"
                          onClick={() => {
                            setJudgeModelSlots((prev) => prev.filter((_, idx) => idx !== i));
                            setJudgeTempSlots((prev) => prev.filter((_, idx) => idx !== i));
                          }}
                          className="shrink-0 rounded p-1 text-text-muted hover:text-red-400 transition"
                        >
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Add evaluator button */}
              <button
                type="button"
                onClick={() => {
                  setJudgeModelSlots((prev) => [...prev, "gpt-4o-mini"]);
                  setJudgeTempSlots((prev) => [...prev, 0.5]);
                }}
                className="text-2xs text-violet-400 hover:text-violet-300 transition"
              >
                + Add Evaluator
              </button>

              <p className="text-2xs text-text-muted">
                Each evaluator uses a different model and temperature for diverse perspectives.
                Human annotations drive per-evaluator reliability scoring.
              </p>
            </div>
          )}

          {/* Concurrency control */}
          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-text-secondary">
              Parallel questions
            </label>
            <input
              type="range"
              min={1}
              max={20}
              value={concurrency}
              onChange={(e) => setConcurrency(Number(e.target.value))}
              className="h-1.5 w-32 cursor-pointer accent-accent"
            />
            <span className="w-6 text-center text-xs font-mono text-text-primary">
              {concurrency}
            </span>
            <span className="text-xs text-text-muted">
              {concurrency === 1 ? "(sequential)" : concurrency >= 15 ? "(aggressive)" : ""}
            </span>
          </div>

          <div className="flex flex-col items-start gap-1">
            <button
              onClick={handleRun}
              disabled={selectedMetrics.size === 0 || hasMissingKeys}
              className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Run Experiment
            </button>
            {hasMissingKeys && (
              <p className="text-2xs text-yellow-500">
                Missing API key for: {[...new Set(missingKeyModels)].join(", ")}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Running — progress + live Q&A feed */}
      {runState.phase === "running" && (
        <div className="space-y-4">
          {/* Experiment info banner */}
          {experimentMeta && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-card/50 px-3 py-2">
              <span className="text-xs font-medium text-text-primary">{experimentMeta.name}</span>
              <span className="text-xs text-text-muted">{experimentMeta.model}</span>
              <span className="text-xs text-text-muted">{experimentMeta.testSet}</span>
            </div>
          )}

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

          {/* Initializing status — shown before any question completes */}
          {runState.current === 0 && runState.inFlightDetails.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
              {runState.currentQuestion || "Initializing..."}
            </div>
          )}

          {/* In-flight questions with per-question pipeline */}
          {runState.inFlightDetails.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-text-muted">
                Processing ({runState.inFlightDetails.length} in parallel)
              </p>
              <div className="space-y-2">
                {runState.inFlightDetails.map((detail, i) => {
                  const totalMetrics = detail.metrics_done.length + detail.metrics_active.length + detail.metrics_pending.length;
                  const doneCount = detail.metrics_done.length;
                  const scoringPct = totalMetrics > 0 ? (doneCount / totalMetrics) * 100 : 0;

                  return (
                    <div
                      key={i}
                      className="rounded-lg border border-border/60 bg-card/50 px-3 py-2.5"
                    >
                      {/* Question text */}
                      <p className="mb-2 text-xs leading-relaxed text-text-secondary">{detail.question}</p>

                      {/* Pipeline steps */}
                      <div className="space-y-1.5">
                        {/* Step 1: Querying */}
                        <div className="flex items-center gap-2">
                          {detail.phase === "querying" ? (
                            <svg className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-400" viewBox="0 0 24 24" fill="none">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          ) : (
                            <svg className="h-3.5 w-3.5 shrink-0 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                          <span className={`text-xs ${detail.phase === "querying" ? "text-blue-300" : "text-text-muted"}`}>
                            {connectorType === "csv" ? "Using pre-loaded data" : isBotExperiment ? "Querying bot" : "Running RAG pipeline"}
                          </span>
                        </div>

                        {/* Step 2: Scoring metrics */}
                        <div className="flex items-center gap-2">
                          {detail.phase === "querying" ? (
                            <div className="h-3.5 w-3.5 shrink-0 rounded-full border border-border" />
                          ) : doneCount < totalMetrics ? (
                            <svg className="h-3.5 w-3.5 shrink-0 animate-spin text-purple-400" viewBox="0 0 24 24" fill="none">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          ) : (
                            <svg className="h-3.5 w-3.5 shrink-0 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                          <span className={`text-xs ${detail.phase === "scoring" ? "text-purple-300" : "text-text-muted"}`}>
                            Evaluating metrics {detail.phase === "scoring" && totalMetrics > 0 ? `(${doneCount}/${totalMetrics})` : ""}
                          </span>
                        </div>

                        {/* Metric progress bar + detail when scoring */}
                        {detail.phase === "scoring" && totalMetrics > 0 && (
                          <div className="pl-[22px]">
                            {/* Mini progress bar */}
                            <div className="mb-1.5 h-1 overflow-hidden rounded-full bg-elevated">
                              <div
                                className="h-full rounded-full bg-purple-500 transition-all duration-300"
                                style={{ width: `${scoringPct}%` }}
                              />
                            </div>
                            {/* Metric chips */}
                            <div className="flex flex-wrap gap-1">
                              {detail.metrics_done.map((m) => (
                                <span key={m} className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-green-500/10 text-green-400">
                                  {m.replace(/_/g, " ")} ✓
                                </span>
                              ))}
                              {detail.metrics_active.map((m) => (
                                <span key={m} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium bg-purple-500/10 text-purple-300">
                                  <span className="inline-block h-1 w-1 animate-pulse rounded-full bg-purple-400" />
                                  {m.replace(/_/g, " ")}
                                </span>
                              ))}
                              {detail.metrics_pending.map((m) => (
                                <span key={m} className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-zinc-500/10 text-text-muted">
                                  {m.replace(/_/g, " ")}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Live Q&A feed */}
          {completedLog.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-text-muted">
                Completed ({completedLog.length})
              </p>
              <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-border bg-elevated/30 p-2">
                {completedLog.map((item, i) => (
                  <div
                    key={i}
                    className={`rounded-lg border px-3 py-2 ${
                      item.error
                        ? "border-red-500/20 bg-red-500/5"
                        : "border-border/60 bg-card/50"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 shrink-0 text-xs font-medium text-text-muted">Q:</span>
                      <p className="text-xs leading-relaxed text-text-secondary">{item.question}</p>
                    </div>
                    {item.error ? (
                      <div className="mt-1.5 flex items-start gap-2">
                        <span className="mt-0.5 shrink-0 text-xs font-medium text-red-400">E:</span>
                        <p className="text-xs leading-relaxed text-red-300/80">{item.error}</p>
                      </div>
                    ) : item.response ? (
                      <div className="mt-1.5 flex items-start gap-2">
                        <span className="mt-0.5 shrink-0 text-xs font-medium text-accent">A:</span>
                        <p className="text-xs leading-relaxed text-text-primary">{item.response}</p>
                      </div>
                    ) : null}
                    {/* Per-question metric scores */}
                    {item.metrics && Object.keys(item.metrics).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5 border-t border-border/40 pt-2">
                        {Object.entries(item.metrics).map(([name, value]) => (
                          <span
                            key={name}
                            className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              value === null
                                ? "bg-zinc-500/10 text-text-muted"
                                : value >= 0.7
                                  ? "bg-green-500/10 text-green-400"
                                  : value >= 0.4
                                    ? "bg-yellow-500/10 text-yellow-400"
                                    : "bg-red-500/10 text-red-400"
                            }`}
                          >
                            {name.replace(/_/g, " ")}: {value !== null ? value.toFixed(2) : "—"}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
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

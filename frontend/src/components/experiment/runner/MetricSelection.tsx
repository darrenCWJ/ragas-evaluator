import type { Dispatch, SetStateAction } from 'react';
import type { CustomMetric } from '../../../lib/api';

export const LLM_METRICS = [
  'faithfulness',
  'answer_relevancy',
  'context_precision',
  'context_recall',
  'context_entities_recall',
  'noise_sensitivity',
  'factual_correctness',
  'summarization_score',
  'aspect_critic',
  'rubrics_score',
  'instance_rubrics',
  'refusal_accuracy',
  'conversation_retention',
];

/** One-click selection presets — the guided "options kinds" for metric choice. */
export const PRESET_RECOMMENDED = [
  'faithfulness',
  'answer_relevancy',
  'context_precision',
  'context_recall',
  'factual_correctness',
  'semantic_similarity',
  'refusal_accuracy',
];

export const NVIDIA_METRICS = ['answer_accuracy', 'context_relevance', 'response_groundedness'];

export const EMBEDDING_METRICS = ['semantic_similarity'];

export const STRING_METRICS = [
  'non_llm_string_similarity',
  'bleu_score',
  'rouge_score',
  'chrf_score',
  'exact_match',
  'string_presence',
];

/** Metrics that require retrieved contexts to produce meaningful results. */
export const CONTEXT_REQUIRED_METRICS = new Set([
  'faithfulness',
  'context_precision',
  'context_recall',
  'context_entities_recall',
  'noise_sensitivity',
  'summarization_score',
  'context_relevance',
  'response_groundedness',
  'aspect_critic',
  'rubrics_score',
  'instance_rubrics',
]);

export const DOMAIN_METRICS = ['sql_semantic_equivalence', 'datacompy_score'];

export const JUDGE_METRICS = ['multi_llm_judge'];

/** Specialized metrics that need infrastructure not yet available (tool calls, etc.) */
export const COMING_SOON_METRICS = [
  { name: 'agent_goal_accuracy', reason: 'Requires agentic goal/outcome annotations' },
  { name: 'topic_adherence', reason: 'Requires a predefined topic list per conversation' },
  {
    name: 'tool_call_accuracy',
    reason: 'Requires tool/function call data from agent interactions',
  },
  { name: 'tool_call_f1', reason: 'Requires tool/function call data from agent interactions' },
];

export const METRIC_DESCRIPTIONS: Record<string, string> = {
  // LLM Metrics
  faithfulness:
    'Measures if the response is factually consistent with the retrieved context. Every claim should be supported by the context.',
  answer_relevancy:
    "Measures how relevant the response is to the user's question. Penalises incomplete or redundant answers.",
  context_precision:
    'Measures how well retrieved contexts are ranked — whether relevant chunks appear before irrelevant ones.',
  context_recall:
    'Measures how much of the reference answer can be attributed to the retrieved context. Catches missing retrieval.',
  context_entities_recall:
    'Measures the proportion of entities in the reference that also appear in the retrieved contexts.',
  noise_sensitivity:
    'Measures how much irrelevant context (noise) degrades the response quality compared to the reference.',
  factual_correctness:
    'Compares the response to a reference answer by decomposing both into claims and checking overlap.',
  summarization_score:
    'Evaluates how well a summary captures the key information from the source context.',
  aspect_critic:
    'Binary LLM judge that evaluates a specific aspect (e.g. harmfulness, correctness) and returns yes/no.',
  rubrics_score:
    'LLM judge that scores the response against user-defined rubric criteria with detailed reasoning.',
  instance_rubrics:
    'Per-instance rubric evaluation using SingleTurnSample. Scores response against rubric criteria on a 1-5 scale, normalised to 0-1.',
  refusal_accuracy:
    'For out-of-scope questions (refusal-tagged): did the agent correctly decline instead of fabricating an answer? Scores refused=1, hedged=0.5, fabricated=0. Other questions are skipped.',
  conversation_retention:
    'For multi-turn questions (with setup turns): does the final answer honor facts established earlier in the conversation? Scores retained=1, partial=0.5, forgot/contradicted=0. Single-turn questions are skipped.',
  // NVIDIA Metrics
  answer_accuracy:
    'Dual LLM-as-a-Judge that measures agreement between the response and a reference answer. Scores from two perspectives then averages.',
  context_relevance:
    'Dual LLM-as-a-Judge that evaluates whether retrieved contexts are pertinent to the query. Two independent ratings averaged.',
  response_groundedness:
    'Dual LLM-as-a-Judge that checks if every claim in the response is supported by the retrieved contexts.',
  // Embedding Metrics
  semantic_similarity:
    'Cosine similarity between embeddings of the response and the reference answer. No LLM needed.',
  // String Metrics
  non_llm_string_similarity:
    'Character-level string distance (Levenshtein) between the response and reference. Fast, no LLM needed.',
  bleu_score:
    'BLEU n-gram precision score comparing response to reference. Common in machine translation evaluation.',
  rouge_score:
    'ROUGE recall-oriented score measuring n-gram overlap between response and reference.',
  chrf_score: 'chrF character n-gram F-score. More robust than BLEU for morphologically rich text.',
  exact_match:
    'Returns 1 if the response exactly matches the reference (after normalisation), 0 otherwise.',
  string_presence:
    'Checks whether the reference string appears anywhere in the response. Simple substring match.',
  // Domain-Specific Metrics
  sql_semantic_equivalence:
    'Compares a generated SQL query against a reference SQL for semantic equivalence, optionally using schema context.',
  datacompy_score:
    'Compares structured/tabular data between response and reference using row-level or column-level matching.',
  // Judge Metrics
  multi_llm_judge:
    'Runs multiple LLMs independently as judges and aggregates their verdicts. Each evaluator produces a reasoning, verdict (positive/mixed/critical), score (1–10), and claim-level quotes linking the response to source chunks. The final score is the mean verdict across all evaluators.',
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

function MetricGroup({
  label,
  labelClass,
  metrics,
  selected,
  onToggle,
  activeClass,
  inactiveClass,
  disabledMetrics,
  disabledReasons,
}: MetricGroupProps) {
  return (
    <div>
      <label className={`mb-2 block text-xs font-medium ${labelClass}`}>{label}</label>
      <div className="flex flex-wrap gap-2">
        {metrics.map((metric) => {
          const checked = selected.has(metric);
          const disabled = disabledMetrics?.has(metric) ?? false;
          const disabledReason = disabled
            ? (disabledReasons?.[metric] ??
              'requires retrieved contexts (not available for this connector)')
            : null;
          return (
            <button
              key={metric}
              type="button"
              onClick={() => !disabled && onToggle(metric)}
              title={
                disabled
                  ? `${metric.replace(/_/g, ' ')} — ${disabledReason}`
                  : METRIC_DESCRIPTIONS[metric]
              }
              disabled={disabled}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                disabled
                  ? 'cursor-not-allowed border-border/50 bg-card/30 text-text-muted/40 line-through'
                  : checked
                    ? activeClass
                    : inactiveClass
              }`}
            >
              {metric.replace(/_/g, ' ')}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface MetricSelectionProps {
  customMetrics: CustomMetric[];
  selectedMetrics: Set<string>;
  setSelectedMetrics: Dispatch<SetStateAction<Set<string>>>;
  disabledMetrics: Set<string>;
  hasContexts: boolean;
}

/** Quick-select preset row plus the grouped metric toggle buttons. */
export default function MetricSelection({
  customMetrics,
  selectedMetrics,
  setSelectedMetrics,
  disabledMetrics,
  hasContexts,
}: MetricSelectionProps) {
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

  return (
    <>
      {/* Quick presets — guided selection before the full option groups */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-text-secondary">Quick select:</span>
        <button
          type="button"
          onClick={() =>
            setSelectedMetrics(new Set(PRESET_RECOMMENDED.filter((m) => !disabledMetrics.has(m))))
          }
          title="The core quality metrics most teams start with"
          className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-1 text-xs font-medium text-accent hover:bg-accent/20"
        >
          Recommended
        </button>
        <button
          type="button"
          onClick={() => setSelectedMetrics(new Set(STRING_METRICS))}
          title="Deterministic reference-comparison metrics — instant, no LLM cost"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-400 hover:bg-amber-500/20"
        >
          Free only
        </button>
        <button
          type="button"
          onClick={() =>
            setSelectedMetrics(
              new Set(
                [
                  ...LLM_METRICS,
                  ...NVIDIA_METRICS,
                  ...EMBEDDING_METRICS,
                  ...STRING_METRICS,
                  ...DOMAIN_METRICS,
                ].filter((m) => !disabledMetrics.has(m)),
              ),
            )
          }
          title="Every applicable metric — slowest and highest LLM cost"
          className="rounded-lg border border-border bg-card px-3 py-1 text-xs font-medium text-text-secondary hover:text-text-primary"
        >
          Everything
        </button>
        <button
          type="button"
          onClick={() => setSelectedMetrics(new Set())}
          className="rounded-lg px-2 py-1 text-xs text-text-muted hover:text-text-secondary"
        >
          Clear
        </button>
        <span className="ml-auto text-xs text-text-muted">{selectedMetrics.size} selected</span>
      </div>

      <div className="space-y-3">
        {/* LLM Metrics */}
        <MetricGroup
          label="LLM Metrics (uses judge LLM — costs API calls)"
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
          label="String Metrics (free — instant, no LLM)"
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
            sql_semantic_equivalence: 'no questions in this test set have reference_sql metadata',
            datacompy_score: 'no questions in this test set have reference_data metadata',
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
                {m.name.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        </div>

        {/* Custom metrics */}
        {customMetrics.length > 0 && (
          <div>
            <label className="mb-2 block text-xs font-medium text-purple-400">Custom Metrics</label>
            <div className="flex flex-wrap gap-2">
              {customMetrics.map((cm) => {
                const checked = selectedMetrics.has(cm.name);
                const needsContexts =
                  cm.metric_type === 'rubrics' || cm.metric_type === 'instance_rubrics';
                const disabled = needsContexts && !hasContexts;
                return (
                  <button
                    key={cm.name}
                    type="button"
                    onClick={() => !disabled && toggleMetric(cm.name)}
                    disabled={disabled}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                      disabled
                        ? 'cursor-not-allowed border-border/50 bg-card/30 text-text-muted/40 line-through'
                        : checked
                          ? 'border-purple-500/50 bg-purple-500/15 text-purple-400'
                          : 'border-border bg-card text-text-muted hover:border-purple-500/30 hover:text-text-secondary'
                    }`}
                    title={
                      disabled
                        ? `${cm.name.replace(/_/g, ' ')} — requires retrieved contexts (not available for this connector)`
                        : `${cm.metric_type.replace(/_/g, ' ')} (${cm.min_score}–${cm.max_score})`
                    }
                  >
                    {cm.name.replace(/_/g, ' ')}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {selectedMetrics.size === 0 && (
          <p className="mt-1.5 text-xs text-red-400">Select at least one metric</p>
        )}
      </div>
    </>
  );
}

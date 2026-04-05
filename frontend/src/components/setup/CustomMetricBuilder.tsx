import { useState, useEffect } from "react";
import {
  fetchCustomMetrics,
  createCustomMetric,
  deleteCustomMetric,
} from "../../lib/api";
import type { CustomMetric } from "../../lib/api";

interface Props {
  projectId: number;
}

const METRIC_TYPES = [
  {
    value: "integer_range",
    label: "Integer Range",
    description: "LLM rates the response on a numeric scale using your custom prompt.",
  },
  {
    value: "similarity",
    label: "Similarity-Based",
    description: "LLM rates how similar the response is to the reference answer.",
  },
  {
    value: "rubrics",
    label: "Rubrics-Based",
    description: "LLM scores against detailed rubric descriptions for each score level.",
  },
  {
    value: "instance_rubrics",
    label: "Instance-Specific Rubrics",
    description: "Each test question gets its own rubric. (Requires per-question rubric data.)",
  },
] as const;

const PROMPT_HINTS: Record<string, string> = {
  integer_range: `Available variables: {response}, {user_input}, {reference}, {retrieved_contexts}

Example:
Rate the helpfulness of the response on a scale of 1 to 5.

1 = Not helpful at all
2 = Slightly helpful
3 = Moderately helpful
4 = Very helpful
5 = Extremely helpful

Question: {user_input}
Response: {response}

Respond with only the number.`,
  similarity: `Available variables: {response}, {reference}

Example:
Rate how closely the response matches the reference answer on a scale of 0 to 5.

0 = Completely different meaning
1 = Vaguely related
2 = Partially overlapping
3 = Mostly similar
4 = Very similar with minor differences
5 = Identical meaning

Reference: {reference}
Response: {response}

Respond with only the number.`,
};

const RUBRIC_HINT = `Define what each score level means. Use the exact field names shown.
Example for a 1-5 scale:
  score1_description: "Completely incorrect or irrelevant"
  score2_description: "Partially correct but major errors"
  score3_description: "Mostly correct but lacks detail"
  score4_description: "Correct and clear with minor issues"
  score5_description: "Excellent, accurate, and comprehensive"`;

export default function CustomMetricBuilder({ projectId }: Props) {
  const [metrics, setMetrics] = useState<CustomMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [metricType, setMetricType] = useState<string>("integer_range");
  const [prompt, setPrompt] = useState("");
  const [minScore, setMinScore] = useState(1);
  const [maxScore, setMaxScore] = useState(5);
  const [rubrics, setRubrics] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMetrics = () => {
    setLoading(true);
    fetchCustomMetrics(projectId)
      .then(setMetrics)
      .catch(() => setMetrics([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadMetrics();
  }, [projectId]);

  // Generate rubric fields when score range or type changes
  useEffect(() => {
    if (metricType === "rubrics") {
      const newRubrics: Record<string, string> = {};
      for (let i = minScore; i <= maxScore; i++) {
        const key = `score${i}_description`;
        newRubrics[key] = rubrics[key] || "";
      }
      setRubrics(newRubrics);
    }
  }, [metricType, minScore, maxScore]);

  const resetForm = () => {
    setName("");
    setMetricType("integer_range");
    setPrompt("");
    setMinScore(1);
    setMaxScore(5);
    setRubrics({});
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await createCustomMetric(projectId, {
        name: name.trim(),
        metric_type: metricType,
        prompt: metricType === "rubrics" || metricType === "instance_rubrics" ? undefined : prompt,
        rubrics: metricType === "rubrics" ? rubrics : undefined,
        min_score: minScore,
        max_score: maxScore,
      });
      resetForm();
      setShowForm(false);
      loadMetrics();
    } catch (err) {
      setError((err as Error).message || "Failed to create metric");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setDeleting(id);
    try {
      await deleteCustomMetric(projectId, id);
      loadMetrics();
    } catch {
      // Silently handle
    } finally {
      setDeleting(null);
    }
  };

  const needsPrompt = metricType === "integer_range" || metricType === "similarity";
  const needsRubrics = metricType === "rubrics";

  const nameValid = /^[a-z][a-z0-9_]*$/.test(name.trim());
  const promptValid = !needsPrompt || prompt.trim().length > 0;
  const rubricsValid =
    !needsRubrics || Object.values(rubrics).every((v) => v.trim().length > 0);
  const canSubmit =
    nameValid && promptValid && rubricsValid && !submitting;

  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/15">
            <svg
              className="h-4 w-4 text-purple-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-1.5 3 1.5"
              />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-text-primary">
            Custom Scoring Metrics
          </h3>
        </div>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-purple-500/50 hover:text-purple-400"
          >
            + New Metric
          </button>
        )}
      </div>

      {/* Existing metrics list */}
      {loading ? (
        <p className="text-xs text-text-muted">Loading...</p>
      ) : metrics.length > 0 ? (
        <div className="mb-4 space-y-2">
          {metrics.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between rounded-lg border border-border/50 bg-elevated/50 px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">
                    {m.name}
                  </span>
                  <span className="rounded bg-purple-500/15 px-1.5 py-0.5 text-[10px] font-medium text-purple-400">
                    {m.metric_type.replace(/_/g, " ")}
                  </span>
                  <span className="text-[10px] text-text-muted">
                    {m.min_score}–{m.max_score}
                  </span>
                </div>
                {m.prompt && (
                  <p className="mt-0.5 truncate text-xs text-text-muted">
                    {m.prompt.slice(0, 80)}...
                  </p>
                )}
              </div>
              <button
                onClick={() => handleDelete(m.id)}
                disabled={deleting === m.id}
                className="ml-2 rounded p-1 text-text-muted transition hover:bg-red-500/10 hover:text-red-400 disabled:opacity-40"
                title="Delete metric"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      ) : !showForm ? (
        <p className="mb-4 text-xs text-text-muted">
          No custom metrics yet. Create one to add your own evaluation criteria.
        </p>
      ) : null}

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="space-y-4 border-t border-border/50 pt-4">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Metric Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, ""))}
              placeholder="e.g. helpfulness, tone_check"
              className={`w-full rounded-lg border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 ${
                name && !nameValid
                  ? "border-red-500/50 focus:ring-red-500/50"
                  : "border-border focus:ring-purple-500/50"
              }`}
            />
            <p className="mt-1 text-[10px] text-text-muted">
              Lowercase with underscores. This becomes the metric key in results.
            </p>
          </div>

          {/* Type selector */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Rating Scale Type
            </label>
            <div className="grid grid-cols-2 gap-2">
              {METRIC_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setMetricType(t.value)}
                  className={`rounded-lg border px-3 py-2 text-left transition ${
                    metricType === t.value
                      ? "border-purple-500/50 bg-purple-500/10"
                      : "border-border bg-elevated/30 hover:border-border-focus"
                  }`}
                >
                  <span
                    className={`block text-xs font-medium ${
                      metricType === t.value ? "text-purple-400" : "text-text-primary"
                    }`}
                  >
                    {t.label}
                  </span>
                  <span className="mt-0.5 block text-[10px] leading-tight text-text-muted">
                    {t.description}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Score range — for integer_range and similarity */}
          {(metricType === "integer_range" || metricType === "similarity" || metricType === "rubrics") && (
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Min Score
                </label>
                <input
                  type="number"
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  min={0}
                  max={9}
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                />
              </div>
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Max Score
                </label>
                <input
                  type="number"
                  value={maxScore}
                  onChange={(e) => setMaxScore(Number(e.target.value))}
                  min={1}
                  max={10}
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                />
              </div>
            </div>
          )}

          {/* Prompt editor — for integer_range and similarity */}
          {needsPrompt && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                Judgement Prompt
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={8}
                placeholder={PROMPT_HINTS[metricType] || "Enter your evaluation prompt..."}
                className="w-full rounded-lg border border-border bg-input px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
              />
              <div className="mt-1.5 rounded-lg bg-purple-500/5 px-3 py-2">
                <p className="text-[10px] font-medium text-purple-400">Hint</p>
                <p className="mt-0.5 whitespace-pre-line text-[10px] leading-relaxed text-text-muted">
                  {metricType === "integer_range"
                    ? "Use {response} for the bot's answer, {user_input} for the question, {reference} for the ground truth, and {retrieved_contexts} for the retrieved context chunks."
                    : "Use {response} for the bot's answer and {reference} for the ground truth answer."}
                </p>
              </div>
            </div>
          )}

          {/* Rubric editor — for rubrics type */}
          {needsRubrics && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                Rubric Definitions
              </label>
              <div className="rounded-lg bg-purple-500/5 px-3 py-2 mb-3">
                <p className="whitespace-pre-line text-[10px] leading-relaxed text-text-muted">
                  {RUBRIC_HINT}
                </p>
              </div>
              <div className="space-y-2">
                {Object.entries(rubrics).map(([key, value]) => {
                  const scoreNum = key.match(/score(\d+)_description/)?.[1] || "?";
                  return (
                    <div key={key} className="flex items-start gap-2">
                      <span className="mt-2 flex h-6 w-6 shrink-0 items-center justify-center rounded bg-purple-500/15 text-xs font-bold text-purple-400">
                        {scoreNum}
                      </span>
                      <input
                        type="text"
                        value={value}
                        onChange={(e) =>
                          setRubrics((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                        placeholder={`Describe what a score of ${scoreNum} means...`}
                        className="flex-1 rounded-lg border border-border bg-input px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Instance rubrics info */}
          {metricType === "instance_rubrics" && (
            <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2">
              <p className="text-xs text-yellow-400">
                Instance-specific rubrics require per-question rubric data in your test set. This metric type is saved for future use when per-question rubrics are supported.
              </p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-lg bg-purple-600 px-4 py-2 text-xs font-medium text-white transition hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? "Creating..." : "Create Metric"}
            </button>
            <button
              type="button"
              onClick={() => {
                resetForm();
                setShowForm(false);
              }}
              className="rounded-lg border border-border px-4 py-2 text-xs font-medium text-text-secondary transition hover:border-border-focus hover:text-text-primary"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

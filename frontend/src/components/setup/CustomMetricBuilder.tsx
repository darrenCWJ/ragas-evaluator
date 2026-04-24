import { useState, useEffect } from "react";
import {
  fetchCustomMetrics,
  createCustomMetric,
  updateCustomMetric,
  deleteCustomMetric,
  refineMetricDescription,
} from "../../lib/api";
import type { CustomMetric, FewShotExample } from "../../lib/api";

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
  {
    value: "criteria_judge",
    label: "Criteria Judge",
    description: "AI evaluators judge responses against your custom criteria (good/mixed/bad).",
  },
  {
    value: "reference_judge",
    label: "Reference Answer Judge",
    description: "AI evaluators compare the bot answer against your suggested/reference answer (good/mixed/bad).",
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
  const [editingId, setEditingId] = useState<number | null>(null);
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

  // Criteria judge state
  const [description, setDescription] = useState("");
  const [refinedPrompt, setRefinedPrompt] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);

  // Few-shot examples state (criteria/reference judge only)
  const EMPTY_EXAMPLE: FewShotExample = { question: "", response: "", verdict: "good", score: undefined, reasoning: "" };
  const [fewShotExamples, setFewShotExamples] = useState<FewShotExample[]>([]);

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
    setDescription("");
    setRefinedPrompt("");
    setRefineError(null);
    setFewShotExamples([]);
    setEditingId(null);
  };

  const handleEdit = (m: CustomMetric) => {
    setEditingId(m.id);
    setName(m.name);
    setMetricType(m.metric_type);
    setPrompt(m.prompt ?? "");
    setMinScore(m.min_score);
    setMaxScore(m.max_score);
    setRubrics(m.rubrics ?? {});
    setDescription("");
    setRefinedPrompt(m.refined_prompt ?? "");
    setRefineError(null);
    setFewShotExamples(m.few_shot_examples ?? []);
    setError(null);
    setShowForm(true);
  };

  const handleRefine = async () => {
    if (!description.trim()) return;
    setIsRefining(true);
    setRefineError(null);
    try {
      const result = await refineMetricDescription(projectId, description.trim());
      setRefinedPrompt(result.refined_prompt);
    } catch (err) {
      setRefineError((err as Error).message || "Failed to refine description");
    } finally {
      setIsRefining(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const validExamples = fewShotExamples.filter(e => e.question.trim() && e.response.trim());
      const payload = isAiJudge
        ? {
            name: name.trim(),
            metric_type: metricType,
            prompt: description.trim() || undefined,
            refined_prompt: refinedPrompt.trim(),
            min_score: 0,
            max_score: 1,
            few_shot_examples: validExamples.length > 0 ? validExamples : null,
          }
        : {
            name: name.trim(),
            metric_type: metricType,
            prompt: metricType === "rubrics" || metricType === "instance_rubrics" ? undefined : prompt,
            rubrics: metricType === "rubrics" ? rubrics : undefined,
            min_score: minScore,
            max_score: maxScore,
          };

      if (editingId !== null) {
        await updateCustomMetric(projectId, editingId, payload);
      } else {
        await createCustomMetric(projectId, payload);
      }
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
  const isCriteriaJudge = metricType === "criteria_judge";
  const isReferenceJudge = metricType === "reference_judge";
  const isAiJudge = isCriteriaJudge || isReferenceJudge;

  const nameValid = /^[a-z][a-z0-9_]*$/.test(name.trim());
  const promptValid = !needsPrompt || prompt.trim().length > 0;
  const rubricsValid =
    !needsRubrics || Object.values(rubrics).every((v) => v.trim().length > 0);
  const criteriaValid = !isAiJudge || refinedPrompt.trim().length > 0;
  const canSubmit =
    nameValid && promptValid && rubricsValid && criteriaValid && !submitting;

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
                  {m.metric_type !== "criteria_judge" && m.metric_type !== "reference_judge" && (
                    <span className="text-[10px] text-text-muted">
                      {m.min_score}–{m.max_score}
                    </span>
                  )}
                  {(m.metric_type === "criteria_judge" || m.metric_type === "reference_judge") && (
                    <span className="text-[10px] text-text-muted">good / mixed / bad</span>
                  )}
                  {(m.metric_type === "criteria_judge" || m.metric_type === "reference_judge") && m.few_shot_examples && m.few_shot_examples.length > 0 && (
                    <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-400">
                      {m.few_shot_examples.length} example{m.few_shot_examples.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                {(m.metric_type === "criteria_judge" || m.metric_type === "reference_judge") && m.refined_prompt && (
                  <p className="mt-0.5 truncate text-xs text-text-muted">
                    {m.refined_prompt.slice(0, 80)}...
                  </p>
                )}
                {m.metric_type !== "criteria_judge" && m.metric_type !== "reference_judge" && m.prompt && (
                  <p className="mt-0.5 truncate text-xs text-text-muted">
                    {m.prompt.slice(0, 80)}...
                  </p>
                )}
              </div>
              <div className="ml-2 flex items-center gap-1 shrink-0">
                <button
                  onClick={() => handleEdit(m)}
                  className="rounded p-1 text-text-muted transition hover:bg-accent/10 hover:text-accent"
                  title="Edit metric"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                  </svg>
                </button>
                <button
                  onClick={() => handleDelete(m.id)}
                  disabled={deleting === m.id}
                  className="rounded p-1 text-text-muted transition hover:bg-red-500/10 hover:text-red-400 disabled:opacity-40"
                  title="Delete metric"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
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
        <form onSubmit={handleSubmit} autoComplete="off" className="space-y-4 border-t border-border/50 pt-4">
          {editingId !== null && (
            <p className="text-xs font-medium text-accent">Editing: {name}</p>
          )}
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Metric Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => !editingId && setName(e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, ""))}
              placeholder="e.g. helpfulness, tone_check"
              readOnly={editingId !== null}
              className={`w-full rounded-lg border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 ${
                editingId !== null
                  ? "cursor-not-allowed opacity-60 border-border"
                  : name && !nameValid
                    ? "border-red-500/50 focus:ring-red-500/50"
                    : "border-border focus:ring-purple-500/50"
              }`}
            />
            <p className="mt-1 text-[10px] text-text-muted">
              {editingId !== null
                ? "Name cannot be changed — existing experiment results reference it."
                : "Lowercase with underscores. This becomes the metric key in results."}
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
          {(metricType === "integer_range" || metricType === "similarity" || metricType === "rubrics") && !isAiJudge && (
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

          {/* Criteria Judge / Reference Judge: description + refine */}
          {isAiJudge && (
            <div className="space-y-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Metric Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  placeholder={
                    isReferenceJudge
                      ? "e.g. Does the bot answer convey the same key facts as the suggested answer?"
                      : "e.g. Does the response avoid harmful or unsafe content?"
                  }
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                />
                <button
                  type="button"
                  onClick={handleRefine}
                  disabled={!description.trim() || isRefining}
                  className="mt-2 rounded-lg border border-purple-500/40 bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-300 transition hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isRefining ? "Refining..." : "Refine with AI"}
                </button>
                {refineError && (
                  <p className="mt-1 text-[10px] text-red-400">{refineError}</p>
                )}
              </div>

              {refinedPrompt && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                    Refined Evaluation Prompt
                    <span className="ml-1.5 text-[10px] text-text-muted font-normal">
                      (editable — this becomes the judge's instructions)
                    </span>
                  </label>
                  <textarea
                    value={refinedPrompt}
                    onChange={(e) => setRefinedPrompt(e.target.value)}
                    rows={10}
                    className="w-full rounded-lg border border-purple-500/30 bg-purple-500/5 px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                  />
                  <p className="mt-1 text-[10px] text-text-muted">
                    Evaluators will judge responses as <span className="text-green-400">good</span> / <span className="text-yellow-400">mixed</span> / <span className="text-red-400">bad</span> based on this prompt.
                    {isReferenceJudge && (
                      <span className="ml-1">The judge will see both the <strong>suggested answer</strong> and the <strong>bot answer</strong> side-by-side.</span>
                    )}
                  </p>
                </div>
              )}

              {/* Few-shot examples */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-xs font-medium text-text-secondary">
                    Few-shot Examples
                    <span className="ml-1.5 text-[10px] text-text-muted font-normal">(optional — max 5)</span>
                  </label>
                  {fewShotExamples.length < 5 && (
                    <button
                      type="button"
                      onClick={() => setFewShotExamples((prev) => [...prev, { ...EMPTY_EXAMPLE }])}
                      className="text-[10px] text-purple-400 hover:text-purple-300 transition"
                    >
                      + Add Example
                    </button>
                  )}
                </div>

                {/* How-it-works hint */}
                <div className="mb-3 rounded-lg border border-border/50 bg-elevated/40 px-3 py-2.5 space-y-1.5">
                  <p className="text-[10px] font-medium text-text-secondary">How the evaluator sees your examples</p>
                  {isCriteriaJudge ? (
                    <pre className="whitespace-pre-wrap font-mono text-[9px] leading-relaxed text-text-muted">{`--- Example 1 ---
QUESTION: What is your refund policy?

BOT RESPONSE: We don't offer refunds.

Expected output:
{ "verdict": "bad", "score": 0.0, "highlights": [],
  "reasoning": "Terse and unhelpful — no policy detail." }`}</pre>
                  ) : (
                    <pre className="whitespace-pre-wrap font-mono text-[9px] leading-relaxed text-text-muted">{`--- Example 1 ---
QUESTION: What is your refund policy?

SUGGESTED ANSWER (reference): Refunds within 30 days with receipt.

BOT RESPONSE: We don't offer refunds.

Expected output:
{ "verdict": "bad", "score": 0.0, "highlights": [],
  "reasoning": "Contradicts the reference — refunds are available." }`}</pre>
                  )}
                  <p className="text-[9px] text-text-muted">
                    {isCriteriaJudge
                      ? "The evaluator sees your criteria prompt, then these examples, then the real question + bot response to judge."
                      : "The evaluator sees your criteria prompt, then these examples (with reference answers), then the real question + reference + bot response to judge."}
                  </p>
                </div>

                {fewShotExamples.length === 0 && (
                  <p className="text-[10px] text-text-muted">
                    No examples yet. Add real question/response pairs you already know the correct verdict for.
                  </p>
                )}

                <div className="space-y-3">
                  {fewShotExamples.map((ex, i) => (
                    <div key={i} className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-medium text-purple-400">Example {i + 1}</span>
                        <button
                          type="button"
                          onClick={() => setFewShotExamples((prev) => prev.filter((_, idx) => idx !== i))}
                          className="text-text-muted hover:text-red-400 transition"
                        >
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>

                      <div>
                        <label className="mb-1 block text-[10px] text-text-muted">
                          Question <span className="text-text-muted/40">— the user's question</span>
                        </label>
                        <textarea
                          value={ex.question}
                          onChange={(e) => setFewShotExamples((prev) => prev.map((item, idx) => idx === i ? { ...item, question: e.target.value } : item))}
                          rows={2}
                          placeholder={isCriteriaJudge ? "e.g. What is your refund policy?" : "e.g. How long is the warranty?"}
                          className="w-full rounded border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                        />
                      </div>

                      {isReferenceJudge && (
                        <div>
                          <label className="mb-1 block text-[10px] text-text-muted">
                            Suggested Answer <span className="text-text-muted/40">— the correct/reference answer</span>
                          </label>
                          <textarea
                            value={ex.reference ?? ""}
                            onChange={(e) => setFewShotExamples((prev) => prev.map((item, idx) => idx === i ? { ...item, reference: e.target.value } : item))}
                            rows={2}
                            placeholder="e.g. Warranty covers 2 years from purchase date including parts and labour."
                            className="w-full rounded border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                          />
                        </div>
                      )}

                      <div>
                        <label className="mb-1 block text-[10px] text-text-muted">
                          Bot Response <span className="text-text-muted/40">— what the bot actually said</span>
                        </label>
                        <textarea
                          value={ex.response}
                          onChange={(e) => setFewShotExamples((prev) => prev.map((item, idx) => idx === i ? { ...item, response: e.target.value } : item))}
                          rows={2}
                          placeholder={isCriteriaJudge ? "e.g. We don't offer refunds." : "e.g. I'm not sure about the warranty details."}
                          className="w-full rounded border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                        />
                      </div>

                      <div className="flex gap-3 items-end">
                        <div className="flex-1">
                          <label className="mb-1 block text-[10px] text-text-muted">
                            Expected Verdict <span className="text-text-muted/40">— what the correct judgment is</span>
                          </label>
                          <select
                            value={ex.verdict}
                            onChange={(e) => setFewShotExamples((prev) => prev.map((item, idx) => idx === i ? { ...item, verdict: e.target.value } : item))}
                            className="w-full rounded border border-border bg-input px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                          >
                            <option value="good">good — clearly meets criteria</option>
                            <option value="mixed">mixed — partially meets criteria</option>
                            <option value="bad">bad — fails criteria</option>
                          </select>
                        </div>
                      </div>

                      <div>
                        <label className="mb-1 block text-[10px] text-text-muted">
                          Reasoning <span className="text-text-muted/40">(optional) — appears in the expected output shown to evaluators</span>
                        </label>
                        <input
                          type="text"
                          value={ex.reasoning ?? ""}
                          onChange={(e) => setFewShotExamples((prev) => prev.map((item, idx) => idx === i ? { ...item, reasoning: e.target.value } : item))}
                          placeholder={
                            ex.verdict === "good" ? "e.g. Directly answers the question with accurate detail."
                            : ex.verdict === "bad" ? "e.g. Ignores the question entirely / contradicts the reference."
                            : "e.g. Partially correct but missing key information."
                          }
                          className="w-full rounded border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-purple-500/50"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
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
              {submitting ? (editingId !== null ? "Saving..." : "Creating...") : (editingId !== null ? "Save Changes" : "Create Metric")}
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

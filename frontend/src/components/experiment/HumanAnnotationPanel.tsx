import { useState, useEffect, useCallback } from "react";
import {
  fetchAnnotationSample,
  submitAnnotations,
  fetchEvaluatorAccuracy,
} from "../../lib/api";
import type {
  AnnotationSampleItem,
  HumanAnnotationCreate,
  EvaluatorAccuracyResult,
} from "../../lib/api";

interface Props {
  projectId: number;
  experimentId: number;
}

type Rating = "accurate" | "partially_accurate" | "inaccurate";

const CORRECTNESS_METRICS = new Set([
  "factual_correctness",
  "faithfulness",
  "answer_relevancy",
  "semantic_similarity",
]);

const RATING_OPTIONS: { value: Rating; label: string; color: string }[] = [
  { value: "accurate", label: "Accurate", color: "text-score-high" },
  { value: "partially_accurate", label: "Partial", color: "text-yellow-400" },
  { value: "inaccurate", label: "Inaccurate", color: "text-score-low" },
];

export default function HumanAnnotationPanel({ projectId, experimentId }: Props) {
  const [sample, setSample] = useState<AnnotationSampleItem[]>([]);
  const [totalResults, setTotalResults] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Local annotation state keyed by experiment_result_id
  const [ratings, setRatings] = useState<Record<number, Rating>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  // Evaluator accuracy state
  const [accuracy, setAccuracy] = useState<EvaluatorAccuracyResult | null>(null);
  const [loadingAccuracy, setLoadingAccuracy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAnnotationSample(projectId, experimentId);
      setSample(data.sample);
      setTotalResults(data.total_results);
      // Pre-populate existing annotations
      const existingRatings: Record<number, Rating> = {};
      const existingNotes: Record<number, string> = {};
      for (const item of data.sample) {
        if (item.annotation) {
          existingRatings[item.experiment_result_id] = item.annotation.rating as Rating;
          existingNotes[item.experiment_result_id] = item.annotation.notes ?? "";
        }
      }
      setRatings(existingRatings);
      setNotes(existingNotes);
    } catch (err) {
      setError((err as Error).message || "Failed to load annotation sample");
    } finally {
      setLoading(false);
    }
  }, [projectId, experimentId]);

  useEffect(() => {
    load();
  }, [load]);

  const annotatedCount = Object.keys(ratings).length;
  const allAnnotated = annotatedCount === sample.length && sample.length > 0;

  async function handleSubmit() {
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const annotations: HumanAnnotationCreate[] = Object.entries(ratings).map(
        ([resultId, rating]) => ({
          experiment_result_id: Number(resultId),
          rating,
          notes: notes[Number(resultId)] || null,
        }),
      );
      const result = await submitAnnotations(projectId, experimentId, annotations);
      setSubmitMsg(`Submitted ${result.submitted} annotation${result.submitted !== 1 ? "s" : ""}.`);
      await load();
    } catch (err) {
      setSubmitMsg((err as Error).message || "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLoadAccuracy() {
    setLoadingAccuracy(true);
    try {
      const data = await fetchEvaluatorAccuracy(projectId, experimentId);
      setAccuracy(data);
    } catch (err) {
      setSubmitMsg((err as Error).message || "Failed to compute accuracy");
    } finally {
      setLoadingAccuracy(false);
    }
  }

  if (loading) {
    return (
      <div className="py-4 text-center text-sm text-text-muted">
        Loading annotation sample...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    );
  }

  if (sample.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-6 text-center text-sm text-text-muted">
        No results to annotate.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Human Annotation
        </h3>
        <span className="text-xs text-text-muted">
          {sample.length} of {totalResults} results (20% sample)
        </span>
      </div>

      {/* Progress bar */}
      <div>
        <div className="mb-1 flex justify-between text-xs text-text-muted">
          <span>{annotatedCount} / {sample.length} annotated</span>
          <span>{sample.length > 0 ? Math.round((annotatedCount / sample.length) * 100) : 0}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-elevated">
          <div
            className="h-full rounded-full bg-accent transition-all duration-300"
            style={{ width: `${sample.length > 0 ? (annotatedCount / sample.length) * 100 : 0}%` }}
          />
        </div>
      </div>

      {/* Annotation cards */}
      <div className="space-y-3">
        {sample.map((item) => (
          <div
            key={item.experiment_result_id}
            className="rounded-lg border border-border bg-elevated/30 p-4 space-y-3"
          >
            {/* Question */}
            <div>
              <span className="text-xs font-medium text-text-secondary">Question</span>
              <p className="text-sm text-text-primary">{item.question}</p>
            </div>

            {/* Bot response & reference side by side */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <span className="text-xs font-medium text-text-secondary">Bot Response</span>
                <p className="mt-0.5 text-xs text-text-muted leading-relaxed max-h-24 overflow-y-auto">
                  {item.response ?? "No response"}
                </p>
              </div>
              <div>
                <span className="text-xs font-medium text-text-secondary">Reference Answer</span>
                <p className="mt-0.5 text-xs text-text-muted leading-relaxed max-h-24 overflow-y-auto">
                  {item.reference_answer}
                </p>
              </div>
            </div>

            {/* Correctness metric scores — only the 4 used for agreement comparison */}
            {(() => {
              const relevant = Object.entries(item.metrics).filter(([name]) => CORRECTNESS_METRICS.has(name));
              if (relevant.length === 0) return null;
              return (
                <div>
                  <p className="mb-1 text-xs text-text-muted">
                    Automated scores used for agreement comparison:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {relevant.map(([name, value]) => (
                      <span
                        key={name}
                        className="rounded bg-elevated px-2 py-0.5 text-xs text-text-muted"
                      >
                        {name.replace(/_/g, " ")}: {(value * 100).toFixed(0)}%
                      </span>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* Rating buttons */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-text-secondary mr-1">Rating:</span>
              {RATING_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() =>
                    setRatings((prev) => ({ ...prev, [item.experiment_result_id]: opt.value }))
                  }
                  className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                    ratings[item.experiment_result_id] === opt.value
                      ? `border-accent bg-accent/15 ${opt.color}`
                      : "border-border text-text-muted hover:border-border-focus hover:text-text-secondary"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Notes */}
            <input
              type="text"
              value={notes[item.experiment_result_id] ?? ""}
              onChange={(e) =>
                setNotes((prev) => ({ ...prev, [item.experiment_result_id]: e.target.value }))
              }
              placeholder="Optional notes..."
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
          </div>
        ))}
      </div>

      {/* Submit */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={annotatedCount === 0 || submitting}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {submitting ? "Submitting..." : `Submit ${annotatedCount} Annotation${annotatedCount !== 1 ? "s" : ""}`}
        </button>

        {allAnnotated && (
          <button
            onClick={handleLoadAccuracy}
            disabled={loadingAccuracy}
            className="rounded-lg border border-accent/40 px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/10 disabled:opacity-40"
          >
            {loadingAccuracy ? "Computing..." : "View Evaluator Accuracy"}
          </button>
        )}
      </div>

      {submitMsg && (
        <p className="text-xs text-text-muted">{submitMsg}</p>
      )}

      {/* Evaluator accuracy results */}
      {accuracy && (
        <div className="rounded-xl border border-border bg-card p-4 space-y-3">
          <h4 className="text-sm font-semibold text-text-primary">
            Evaluator vs Human Agreement
          </h4>

          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {accuracy.agreement_rate !== null
                  ? `${(accuracy.agreement_rate * 100).toFixed(0)}%`
                  : "—"}
              </div>
              <div className="text-xs text-text-muted">Agreement Rate</div>
            </div>
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {accuracy.agreements}/{accuracy.scorable_count}
              </div>
              <div className="text-xs text-text-muted">Agreements</div>
            </div>
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {accuracy.total_annotations}
              </div>
              <div className="text-xs text-text-muted">Total Annotations</div>
            </div>
          </div>

          {/* Per-result comparison */}
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {accuracy.comparisons.map((c) => (
              <div
                key={c.experiment_result_id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-xs ${
                  c.agrees === true
                    ? "bg-score-high/5"
                    : c.agrees === false
                      ? "bg-score-low/5"
                      : "bg-elevated/30"
                }`}
              >
                <span className="w-4 text-center">
                  {c.agrees === true ? "✓" : c.agrees === false ? "✗" : "—"}
                </span>
                <span className="flex-1 truncate text-text-primary">{c.question}</span>
                <span className="shrink-0 text-text-muted">
                  Human: {c.human_rating}
                </span>
                <span className="shrink-0 text-text-muted">
                  Eval: {c.evaluator_rating ?? "n/a"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

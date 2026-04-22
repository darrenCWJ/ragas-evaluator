import { useState, useEffect, useCallback } from "react";
import {
  fetchJudgeEvaluations,
  annotateJudgeClaim,
  type JudgeEvaluation,
  type JudgeClaim,
  type ClaimAnnotation,
} from "../../lib/api";

interface Props {
  projectId: number;
  experimentId: number;
  resultId: number;
  /** Optional: if annotations come from the 20% sample view, pass pre-loaded evaluations */
  preloadedEvaluations?: JudgeEvaluation[];
  excludedIndices?: Set<number>;
  /** For criteria_judge metrics: the metric name to filter evaluations. Omit for built-in judge. */
  metricName?: string;
  /** Called after any annotation is saved so the parent can re-fetch scores. */
  onAnnotationChange?: () => void;
}

type AnnotationMap = Record<number, Record<number, ClaimAnnotation>>;

const VERDICT_STYLES: Record<string, string> = {
  positive: "bg-score-high/10 text-score-high border-score-high/30",
  mixed: "bg-score-mid/10 text-score-mid border-score-mid/30",
  critical: "bg-score-low/10 text-score-low border-score-low/30",
};

const VERDICT_LABELS: Record<string, string> = {
  positive: "Positive",
  mixed: "Mixed",
  critical: "Critical",
};

const CLAIM_BADGE: Record<string, string> = {
  praise: "bg-score-high/15 text-score-high",
  critique: "bg-score-low/15 text-score-low",
};


/** Highlight occurrences of `quote` inside `text` using a mark span. */
function HighlightedText({
  text,
  quote,
  highlightClass,
}: {
  text: string;
  quote: string;
  highlightClass: string;
}) {
  if (!quote || !text.includes(quote)) {
    return <span>{text}</span>;
  }
  const idx = text.indexOf(quote);
  const before = text.slice(0, idx);
  const after = text.slice(idx + quote.length);
  return (
    <span>
      {before}
      <mark className={`rounded px-0.5 not-italic ${highlightClass}`}>{quote}</mark>
      {after}
    </span>
  );
}

function ClaimCard({
  evalId,
  claim,
  claimIndex,
  annotation,
  highlightClass,
  onAnnotate,
  saving,
}: {
  evalId: number;
  claim: JudgeClaim;
  claimIndex: number;
  annotation: ClaimAnnotation | undefined;
  highlightClass: string;
  onAnnotate: (evalId: number, claimIdx: number, status: "accurate" | "inaccurate" | "unsure") => void;
  saving: boolean;
}) {
  const [commentOpen, setCommentOpen] = useState(false);

  return (
    <div className="rounded-lg border border-border/60 bg-elevated/40 p-3 space-y-2">
      {/* Claim type badge */}
      <div className="flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-2xs font-semibold ${CLAIM_BADGE[claim.type] ?? ""}`}>
          {claim.type === "praise" ? "✓ Praise" : "✗ Critique"}
        </span>
        {annotation && (
          <span
            className={`rounded-full px-2 py-0.5 text-2xs font-medium border ${
              annotation.status === "accurate"
                ? "bg-score-high/10 text-score-high border-score-high/30"
                : annotation.status === "inaccurate"
                ? "bg-score-low/10 text-score-low border-score-low/30"
                : "bg-text-muted/10 text-text-muted border-text-muted/30"
            }`}
          >
            {annotation.status === "accurate" ? "Human: Accurate" : annotation.status === "inaccurate" ? "Human: Wrong" : "Human: Unsure"}
          </span>
        )}
      </div>

      {/* Response quote */}
      {claim.response_quote && (
        <div>
          <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-text-muted">Response</p>
          <p className="rounded bg-elevated px-2 py-1.5 text-xs text-text-primary leading-relaxed">
            <HighlightedText
              text={claim.response_quote}
              quote={claim.response_quote}
              highlightClass={highlightClass}
            />
          </p>
        </div>
      )}

      {/* Chunk reference */}
      {claim.chunk_reference && claim.chunk_quote && (
        <div>
          <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Source — {claim.chunk_reference}
          </p>
          <p className="rounded border border-accent/20 bg-accent/5 px-2 py-1.5 text-xs text-text-secondary leading-relaxed italic">
            "{claim.chunk_quote}"
          </p>
        </div>
      )}

      {/* Explanation */}
      <p className="text-xs text-text-secondary leading-relaxed">{claim.explanation}</p>

      {/* Annotation controls */}
      <div className="flex items-center gap-2 pt-1">
        <span className="text-2xs text-text-muted">Rate this claim:</span>
        {(["accurate", "inaccurate", "unsure"] as const).map((s) => (
          <button
            key={s}
            disabled={saving}
            onClick={() => onAnnotate(evalId, claimIndex, s)}
            className={`rounded-full px-2.5 py-0.5 text-2xs font-medium transition border ${
              annotation?.status === s
                ? s === "accurate"
                  ? "bg-score-high text-white border-score-high"
                  : s === "inaccurate"
                  ? "bg-score-low text-white border-score-low"
                  : "bg-text-muted text-white border-text-muted"
                : "border-border text-text-muted hover:border-accent hover:text-accent"
            } ${saving ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          >
            {s === "accurate" ? "✓ Accurate" : s === "inaccurate" ? "✗ Wrong" : "? Unsure"}
          </button>
        ))}
        {annotation && (
          <button
            onClick={() => setCommentOpen((p) => !p)}
            className="ml-auto text-2xs text-accent underline"
          >
            {commentOpen ? "hide note" : annotation.comment ? "edit note" : "+ note"}
          </button>
        )}
      </div>
      {commentOpen && annotation?.comment && (
        <p className="text-2xs text-text-muted italic">{annotation.comment}</p>
      )}
    </div>
  );
}

function EvaluatorCard({
  evaluation,
  annotations,
  excluded,
  onAnnotate,
  savingKey,
}: {
  evaluation: JudgeEvaluation;
  annotations: Record<number, ClaimAnnotation>;
  excluded: boolean;
  onAnnotate: (evalId: number, claimIdx: number, status: "accurate" | "inaccurate" | "unsure") => void;
  savingKey: string | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div
      className={`rounded-xl border transition ${
        excluded
          ? "border-border/40 bg-elevated/30 opacity-50"
          : "border-border bg-card"
      }`}
    >
      {/* Header */}
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <svg
          className={`h-3.5 w-3.5 shrink-0 text-text-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>

        <span className="text-xs font-semibold text-text-secondary">
          Evaluator {evaluation.evaluator_index + 1}
        </span>

        {/* Verdict badge */}
        <span
          className={`rounded-full border px-2 py-0.5 text-2xs font-medium ${
            VERDICT_STYLES[evaluation.verdict] ?? "bg-elevated text-text-muted border-border"
          }`}
        >
          {VERDICT_LABELS[evaluation.verdict] ?? evaluation.verdict}
        </span>

        {excluded && (
          <span className="rounded-full border border-border/40 bg-elevated/60 px-2 py-0.5 text-2xs text-text-muted">
            Low reliability
          </span>
        )}
      </button>

      {/* Claims */}
      <div
        className={`grid transition-[grid-template-rows] duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border/60 px-4 py-3 space-y-3">
            {evaluation.reasoning && (
              <div className="rounded-lg border border-accent/20 bg-accent/5 px-3 py-2">
                <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-accent/70">
                  Reasoning
                </p>
                <p className="text-xs text-text-secondary leading-relaxed">
                  {evaluation.reasoning}
                </p>
              </div>
            )}
            {evaluation.claims.length === 0 ? (
              <p className="text-xs text-text-muted italic">No claims produced by this evaluator.</p>
            ) : (
              evaluation.claims.map((claim, idx) => (
                <ClaimCard
                  key={idx}
                  evalId={evaluation.id}
                  claim={claim}
                  claimIndex={idx}
                  annotation={annotations[idx]}
                  highlightClass={
                    claim.type === "praise"
                      ? "bg-score-high/25 text-score-high"
                      : "bg-score-low/20 text-score-low"
                  }
                  onAnnotate={onAnnotate}
                  saving={savingKey === `${evaluation.id}-${idx}`}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MultiLLMJudgePanel({
  projectId,
  experimentId,
  resultId,
  preloadedEvaluations,
  excludedIndices = new Set(),
  metricName,
  onAnnotationChange,
}: Props) {
  const [evaluations, setEvaluations] = useState<JudgeEvaluation[]>(preloadedEvaluations ?? []);
  const [annotationMap, setAnnotationMap] = useState<AnnotationMap>({});
  const [loading, setLoading] = useState(!preloadedEvaluations);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (preloadedEvaluations) {
      setEvaluations(preloadedEvaluations);
      const map: AnnotationMap = {};
      for (const ev of preloadedEvaluations) {
        map[ev.id] = ev.annotations as Record<number, ClaimAnnotation>;
      }
      setAnnotationMap(map);
      return;
    }

    setLoading(true);
    fetchJudgeEvaluations(projectId, experimentId, resultId, metricName)
      .then((data) => {
        setEvaluations(data.evaluations);
        const map: AnnotationMap = {};
        for (const ev of data.evaluations) {
          map[ev.id] = ev.annotations as Record<number, ClaimAnnotation>;
        }
        setAnnotationMap(map);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [projectId, experimentId, resultId, preloadedEvaluations, metricName]);

  const handleAnnotate = useCallback(
    async (evalId: number, claimIdx: number, status: "accurate" | "inaccurate" | "unsure") => {
      const key = `${evalId}-${claimIdx}`;
      setSavingKey(key);
      try {
        await annotateJudgeClaim(projectId, experimentId, resultId, evalId, claimIdx, status);
        setAnnotationMap((prev) => ({
          ...prev,
          [evalId]: {
            ...prev[evalId],
            [claimIdx]: {
              status,
              comment: prev[evalId]?.[claimIdx]?.comment ?? null,
              annotated_at: new Date().toISOString(),
            },
          },
        }));
        onAnnotationChange?.();
      } catch (e) {
        setError(`Failed to save annotation: ${e}`);
      } finally {
        setSavingKey(null);
      }
    },
    [projectId, experimentId, resultId],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-text-muted">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        Loading evaluator feedback…
      </div>
    );
  }

  if (error) {
    return <p className="rounded bg-score-low/10 px-3 py-2 text-xs text-score-low">{error}</p>;
  }

  if (evaluations.length === 0) {
    return (
      <p className="text-xs text-text-muted italic">
        No evaluator data found for this result.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-2xs font-semibold uppercase tracking-wider text-text-muted">
        LLM Evaluators ({evaluations.length})
      </p>
      {evaluations.map((ev) => (
        <EvaluatorCard
          key={ev.id}
          evaluation={ev}
          annotations={annotationMap[ev.id] ?? {}}
          excluded={excludedIndices.has(ev.evaluator_index)}
          onAnnotate={handleAnnotate}
          savingKey={savingKey}
        />
      ))}
    </div>
  );
}

import { useState, useEffect } from "react";
import {
  fetchJudgeReliability,
  fetchJudgeSummary,
  fetchJudgeAnnotationSample,
  type JudgeReliabilityResult,
  type JudgeSummaryResponse,
  type JudgeAnnotationSampleResult,
  type JudgeAnnotationSampleItem,
} from "../../lib/api";
import MultiLLMJudgePanel from "./MultiLLMJudgePanel";

interface Props {
  projectId: number;
  experimentId: number;
}

const VERDICT_DOT: Record<string, string> = {
  positive: "bg-score-high",
  mixed: "bg-score-mid",
  critical: "bg-score-low",
};

const VERDICT_LABEL: Record<string, string> = {
  positive: "Positive",
  mixed: "Mixed",
  critical: "Critical",
};

function ReliabilityRing({ value }: { value: number | null }) {
  const pct = value !== null ? Math.round(value * 100) : null;
  const color =
    pct === null ? "text-text-muted" : pct >= 70 ? "text-score-high" : pct >= 50 ? "text-score-mid" : "text-score-low";
  return (
    <div className={`text-4xl font-bold tabular-nums ${color}`}>
      {pct !== null ? `${pct}%` : "—"}
    </div>
  );
}

function EvaluatorCard({
  evaluator,
}: {
  evaluator: JudgeReliabilityResult["evaluators"][0];
}) {
  const pct =
    evaluator.reliability !== null
      ? Math.round(evaluator.reliability * 100)
      : null;
  const color =
    pct === null
      ? "text-text-muted"
      : pct >= 70
      ? "text-score-high"
      : pct >= 50
      ? "text-score-mid"
      : "text-score-low";

  return (
    <div
      className={`rounded-xl border p-4 space-y-1 ${
        evaluator.excluded ? "border-border/40 bg-elevated/30 opacity-60" : "border-border bg-card"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-text-primary">
          Evaluator {evaluator.evaluator_index + 1}
        </span>
        {evaluator.excluded && (
          <span className="rounded-full border border-border/40 bg-elevated px-2 py-0.5 text-2xs text-text-muted">
            Excluded
          </span>
        )}
      </div>
      <div className={`text-2xl font-bold tabular-nums ${color}`}>
        {pct !== null ? `${pct}%` : "—"}
      </div>
      <p className="text-2xs text-text-muted">
        {pct !== null
          ? `${evaluator.accurate_claims} accurate / ${evaluator.accurate_claims + evaluator.inaccurate_claims} reviewed`
          : "Not yet annotated"}
      </p>
      {evaluator.total_claims_annotated === 0 && (
        <p className="text-2xs italic text-text-muted">No annotations yet</p>
      )}
    </div>
  );
}

function VerdictDot({ verdict }: { verdict: string }) {
  return (
    <span
      title={VERDICT_LABEL[verdict] ?? verdict}
      className={`inline-block h-2.5 w-2.5 rounded-full ${VERDICT_DOT[verdict] ?? "bg-text-muted"}`}
    />
  );
}

function AnnotationSampleSection({
  projectId,
  experimentId,
  sample,
  excludedIndices,
}: {
  projectId: number;
  experimentId: number;
  sample: JudgeAnnotationSampleItem[];
  excludedIndices: Set<number>;
}) {
  const [openResultId, setOpenResultId] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {sample.map((item) => (
        <div key={item.result_id} className="rounded-xl border border-border bg-card">
          <button
            onClick={() =>
              setOpenResultId((p) => (p === item.result_id ? null : item.result_id))
            }
            className="flex w-full items-center gap-3 px-4 py-3 text-left"
          >
            <svg
              className={`h-3.5 w-3.5 shrink-0 text-text-muted transition-transform duration-150 ${
                openResultId === item.result_id ? "rotate-90" : ""
              }`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
              {item.question}
            </span>
            <div className="flex shrink-0 gap-1.5">
              {item.evaluations.map((ev) => (
                <VerdictDot key={ev.evaluator_index} verdict={ev.verdict} />
              ))}
            </div>
            {item.evaluations.some((ev) => Object.keys(ev.annotations).length > 0) && (
              <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-2xs text-accent">
                Annotated
              </span>
            )}
          </button>

          <div
            className={`grid transition-[grid-template-rows] duration-200 ${
              openResultId === item.result_id ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
            }`}
          >
            <div className="overflow-hidden">
              <div className="border-t border-border/60 px-4 py-4 space-y-4">
                <div>
                  <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-text-muted">
                    Bot Response
                  </p>
                  <p className="rounded-lg bg-elevated/60 px-3 py-2 text-sm text-text-primary whitespace-pre-wrap">
                    {item.response ?? <span className="italic text-text-muted">No response</span>}
                  </p>
                </div>
                <MultiLLMJudgePanel
                  projectId={projectId}
                  experimentId={experimentId}
                  resultId={item.result_id}
                  preloadedEvaluations={item.evaluations}
                  excludedIndices={excludedIndices}
                />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function MultiLLMJudgeDashboard({ projectId, experimentId }: Props) {
  const [reliability, setReliability] = useState<JudgeReliabilityResult | null>(null);
  const [summary, setSummary] = useState<JudgeSummaryResponse | null>(null);
  const [sampleData, setSampleData] = useState<JudgeAnnotationSampleResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "annotate">("overview");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchJudgeReliability(projectId, experimentId),
      fetchJudgeSummary(projectId, experimentId),
      fetchJudgeAnnotationSample(projectId, experimentId),
    ])
      .then(([rel, sum, samp]) => {
        setReliability(rel);
        setSummary(sum);
        setSampleData(samp);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [projectId, experimentId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-text-muted justify-center">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        Loading judge dashboard…
      </div>
    );
  }

  if (error) {
    return (
      <p className="rounded-lg bg-score-low/10 px-4 py-3 text-sm text-score-low">
        {error}
      </p>
    );
  }

  if (!reliability || !summary) return null;

  const excludedSet = new Set(reliability.excluded_indices);
  const { annotated_evaluators, total_evaluators } = reliability.annotation_progress;

  return (
    <div className="space-y-6">
      {/* ── Top stats ── */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Overall reliability */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Overall Reliability
          </p>
          <ReliabilityRing value={reliability.overall_reliability} />
          <p className="mt-1 text-2xs text-text-muted">
            Threshold: {Math.round(reliability.threshold * 100)}%
          </p>
        </div>

        {/* Evaluators active */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Active Evaluators
          </p>
          <div className="text-4xl font-bold text-text-primary tabular-nums">
            {reliability.evaluators.filter((e) => !e.excluded).length}
            <span className="text-xl text-text-muted">
              /{reliability.evaluators.length}
            </span>
          </div>
          {excludedSet.size > 0 && (
            <p className="mt-1 text-2xs text-score-low">
              {excludedSet.size} excluded (low reliability)
            </p>
          )}
        </div>

        {/* Annotation progress */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Annotation Progress
          </p>
          <div className="text-4xl font-bold text-text-primary tabular-nums">
            {sampleData?.annotated_count ?? 0}
            <span className="text-xl text-text-muted">
              /{sampleData?.sample_size ?? 0}
            </span>
          </div>
          <p className="mt-1 text-2xs text-text-muted">
            questions reviewed (20% sample)
          </p>
        </div>

        {/* Questions evaluated */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Questions Evaluated
          </p>
          <div className="text-4xl font-bold text-text-primary tabular-nums">
            {summary.results.length}
          </div>
          <p className="mt-1 text-2xs text-text-muted">with judge feedback</p>
        </div>
      </div>

      {/* ── Evaluator cards ── */}
      <div>
        <p className="mb-3 text-sm font-semibold text-text-primary">Evaluator Reliability</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {reliability.evaluators.map((ev) => (
            <EvaluatorCard key={ev.evaluator_index} evaluator={ev} />
          ))}
        </div>
      </div>

      {/* ── Tabs: Q&A Table / Annotate ── */}
      <div>
        <div className="flex gap-1 border-b border-border mb-4">
          {(["overview", "annotate"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium transition border-b-2 -mb-px ${
                tab === t
                  ? "border-accent text-accent"
                  : "border-transparent text-text-muted hover:text-text-secondary"
              }`}
            >
              {t === "overview" ? "All Results" : `Annotate Sample (${sampleData?.sample_size ?? 0})`}
            </button>
          ))}
        </div>

        {tab === "overview" && (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-elevated/60">
                  <th className="px-4 py-2.5 font-semibold text-text-secondary">Question</th>
                  {reliability.evaluators.map((ev) => (
                    <th
                      key={ev.evaluator_index}
                      className={`px-3 py-2.5 text-center font-semibold ${
                        ev.excluded ? "text-text-muted" : "text-text-secondary"
                      }`}
                    >
                      E{ev.evaluator_index + 1}
                      {ev.excluded && (
                        <span className="ml-1 text-2xs text-score-low">✕</span>
                      )}
                    </th>
                  ))}
                  <th className="px-3 py-2.5 text-right font-semibold text-text-secondary">
                    Score
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {summary.results.map((r) => (
                  <tr key={r.result_id} className="hover:bg-elevated/40 transition">
                    <td className="max-w-xs truncate px-4 py-2.5 text-text-primary">
                      {r.question}
                    </td>
                    {reliability.evaluators.map((ev) => {
                      const verdict = r.evaluator_verdicts[ev.evaluator_index];
                      return (
                        <td
                          key={ev.evaluator_index}
                          className="px-3 py-2.5 text-center"
                        >
                          {verdict ? (
                            <VerdictDot verdict={verdict} />
                          ) : (
                            <span className="text-text-muted">—</span>
                          )}
                        </td>
                      );
                    })}
                    <td className="px-3 py-2.5 text-right font-mono text-xs font-semibold">
                      <span
                        className={
                          r.adjusted_score >= 0.7
                            ? "text-score-high"
                            : r.adjusted_score >= 0.4
                            ? "text-score-mid"
                            : "text-score-low"
                        }
                      >
                        {Math.round(r.adjusted_score * 100)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "annotate" && sampleData && (
          <div className="space-y-4">
            {sampleData.sample.length === 0 ? (
              <p className="text-sm text-text-muted italic">
                No annotation sample available. Run an experiment with multi_llm_judge first.
              </p>
            ) : (
              <>
                <p className="text-sm text-text-secondary">
                  Review the evaluator claims below and mark each as accurate, wrong, or unsure.
                  Evaluators with &lt;{Math.round(reliability.threshold * 100)}% accuracy will be
                  excluded from score calculations.
                </p>
                <AnnotationSampleSection
                  projectId={projectId}
                  experimentId={experimentId}
                  sample={sampleData.sample}
                  excludedIndices={excludedSet}
                />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

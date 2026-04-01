import { useState, useEffect, useCallback } from "react";
import type { TestQuestion, TestSetSummary, TestSet } from "../../lib/api";
import { fetchTestQuestions, fetchTestSetSummary } from "../../lib/api";

const STATUS_FILTERS = ["all", "pending", "approved", "rejected", "edited"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/15 text-yellow-300",
  approved: "bg-green-500/15 text-green-300",
  rejected: "bg-red-500/15 text-red-300",
  edited: "bg-blue-500/15 text-blue-300",
};

interface Props {
  projectId: number;
  testSet: TestSet;
  onBack: () => void;
}

export default function QuestionList({
  projectId,
  testSet,
  onBack,
}: Props) {
  const [questions, setQuestions] = useState<TestQuestion[]>([]);
  const [summary, setSummary] = useState<TestSetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const loadQuestions = useCallback(
    async (status: StatusFilter) => {
      setLoading(true);
      setError(null);
      try {
        const qs = await fetchTestQuestions(
          projectId,
          testSet.id,
          status === "all" ? undefined : status,
        );
        setQuestions(qs);
      } catch (err) {
        setError((err as Error).message || "Failed to load questions");
      } finally {
        setLoading(false);
      }
    },
    [projectId, testSet.id],
  );

  const loadSummary = useCallback(async () => {
    try {
      const s = await fetchTestSetSummary(projectId, testSet.id);
      setSummary(s);
    } catch {
      // summary is supplementary; don't block on failure
    }
  }, [projectId, testSet.id]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadQuestions(filter);
  }, [loadQuestions, filter]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      {/* Header with test set context */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="rounded-lg border border-border p-1.5 text-text-muted transition hover:border-accent hover:text-accent"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"
            />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-medium text-text-primary">
            {testSet.name}
          </h3>
          <p className="text-xs text-text-muted">
            {testSet.generation_config.testset_size} questions requested
            {testSet.generation_config.use_personas &&
              ` · ${testSet.generation_config.num_personas} personas`}
          </p>
        </div>
      </div>

      {/* Summary bar — always shows unfiltered totals */}
      {summary && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-xs">
          <span className="font-medium text-text-primary">
            {summary.total} total
          </span>
          <span className="text-text-muted">|</span>
          <span className="text-yellow-300">{summary.pending} pending</span>
          <span className="text-text-muted">|</span>
          <span className="text-green-300">{summary.approved} approved</span>
          <span className="text-text-muted">|</span>
          <span className="text-red-300">{summary.rejected} rejected</span>
          <span className="text-text-muted">|</span>
          <span className="text-blue-300">{summary.edited} edited</span>
          <span className="ml-auto font-medium text-text-secondary">
            {summary.completion_pct}% reviewed
          </span>
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition ${
              filter === f
                ? "bg-accent/15 text-accent"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="py-8 text-center text-sm text-text-muted">
          Loading questions…
        </div>
      )}

      {/* Question cards */}
      {!loading && questions.length === 0 && (
        <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
          <p className="text-sm text-text-muted">
            {filter === "all"
              ? "No questions in this test set."
              : `No ${filter} questions.`}
          </p>
        </div>
      )}

      {!loading && questions.length > 0 && (
        <div className="space-y-2">
          {questions.map((q) => {
            const isExpanded = expanded.has(q.id);
            const refAnswer = q.reference_answer || "";
            const needsTruncate = refAnswer.length > 150;

            return (
              <div
                key={q.id}
                className="rounded-xl border border-border bg-card px-4 py-3"
              >
                {/* Question text */}
                <p className="text-sm font-medium text-text-primary">
                  {q.question}
                </p>

                {/* Reference answer */}
                <div className="mt-2">
                  <p className="text-xs text-text-muted">Reference answer:</p>
                  <p className="mt-0.5 text-sm text-text-secondary">
                    {isExpanded || !needsTruncate
                      ? refAnswer
                      : refAnswer.slice(0, 150) + "…"}
                  </p>
                  {needsTruncate && (
                    <button
                      onClick={() => toggleExpand(q.id)}
                      className="mt-1 text-xs text-accent hover:underline"
                    >
                      {isExpanded ? "Show less" : "Show more"}
                    </button>
                  )}
                </div>

                {/* Badges */}
                <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs">
                  {/* Status badge */}
                  <span
                    className={`rounded-full px-2 py-0.5 font-medium ${STATUS_COLORS[q.status] || "bg-gray-500/15 text-gray-300"}`}
                  >
                    {q.status}
                  </span>

                  {/* Question type badge */}
                  {q.question_type && (
                    <span className="rounded-full bg-surface px-2 py-0.5 text-text-muted">
                      {q.question_type}
                    </span>
                  )}

                  {/* Persona badge */}
                  {q.persona && (
                    <span className="text-text-muted italic">
                      {q.persona}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

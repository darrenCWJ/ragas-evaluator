import { useState } from "react";
import type { ExperimentResult } from "../../lib/api";
import MultiLLMJudgePanel from "./MultiLLMJudgePanel";

interface Props {
  result: ExperimentResult;
  projectId: number;
  experimentId: number;
  /** Names of custom metrics that are criteria_judge type */
  criteriaMetricNames?: string[];
}

/** Humanize snake_case → Title Case */
function humanize(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function barColor(v: number): string {
  if (v >= 0.8) return "bg-score-high";
  if (v >= 0.5) return "bg-score-mid";
  return "bg-score-low";
}

function textColor(v: number): string {
  if (v >= 0.8) return "text-score-high";
  if (v >= 0.5) return "text-score-mid";
  return "text-score-low";
}

export default function QuestionResultRow({ result, projectId, experimentId, criteriaMetricNames = [] }: Props) {
  const [open, setOpen] = useState(false);
  const [judgeOpen, setJudgeOpen] = useState(false);
  const [openCriteriaPanels, setOpenCriteriaPanels] = useState<Set<string>>(new Set());
  const hasJudge = "multi_llm_judge" in result.metrics;
  const criteriaMetricsInResult = criteriaMetricNames.filter((n) => n in result.metrics);

  const toggleCriteriaPanel = (metricName: string) => {
    setOpenCriteriaPanels((prev) => {
      const next = new Set(prev);
      if (next.has(metricName)) {
        next.delete(metricName);
      } else {
        next.add(metricName);
      }
      return next;
    });
  };

  const metrics = Object.entries(result.metrics).filter(
    (e): e is [string, number] => typeof e[1] === "number",
  );

  const handleToggle = () => setOpen((prev) => !prev);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleToggle();
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card transition hover:border-border-focus">
      {/* ── Collapsed header ── */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        className="flex cursor-pointer items-center gap-3 px-4 py-3 select-none"
      >
        {/* Chevron */}
        <svg
          className={`h-4 w-4 shrink-0 text-text-muted transition-transform duration-200 ${open ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9 5l7 7-7 7"
          />
        </svg>

        {/* Question text */}
        <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
          {result.question}
        </span>

        {/* Question type badge */}
        <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-2xs font-medium text-accent">
          {result.question_type}
        </span>

        {/* Mini metric bars */}
        <div className="hidden shrink-0 items-center gap-1.5 sm:flex">
          {metrics.slice(0, 4).map(([name, value]) => (
            <div
              key={name}
              className="flex items-center gap-1"
              title={`${humanize(name)}: ${(value * 100).toFixed(0)}%`}
            >
              <div className="h-1.5 w-10 overflow-hidden rounded-full bg-elevated">
                <div
                  className={`h-full rounded-full ${barColor(value)}`}
                  style={{ width: `${Math.max(value * 100, 2)}%` }}
                />
              </div>
              <span
                className={`w-7 text-right font-mono text-2xs ${textColor(value)}`}
              >
                {(value * 100).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Expanded detail ── */}
      <div
        className={`grid transition-[grid-template-rows] duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border px-4 py-4 space-y-4">
            {/* Full question */}
            <DetailBlock label="Question">
              <p className="text-sm text-text-primary">{result.question}</p>
            </DetailBlock>

            {/* Reference answer */}
            <DetailBlock label="Reference Answer">
              <p className="text-sm text-text-primary whitespace-pre-wrap">
                {result.reference_answer}
              </p>
            </DetailBlock>

            {/* Model response */}
            <DetailBlock label="Model Response">
              {result.response ? (
                <p className="text-sm text-text-primary whitespace-pre-wrap">
                  {result.response}
                </p>
              ) : (
                <p className="text-sm italic text-text-muted">No response</p>
              )}
            </DetailBlock>

            {/* Retrieved contexts */}
            {result.retrieved_contexts.length > 0 && (
              <DetailBlock label={`Retrieved Contexts (${result.retrieved_contexts.length})`}>
                <div className="space-y-2">
                  {result.retrieved_contexts.map((ctx, i) => (
                    <ContextBlock key={i} index={i + 1} content={ctx.content} />
                  ))}
                </div>
              </DetailBlock>
            )}

            {/* All metrics — full width bars */}
            {metrics.length > 0 && (
              <DetailBlock label="Metrics">
                <div className="space-y-2.5">
                  {metrics
                    .sort((a, b) => b[1] - a[1])
                    .map(([name, value]) => (
                      <div key={name} className="flex items-center gap-3">
                        <span className="w-32 shrink-0 truncate text-xs font-medium text-text-secondary">
                          {humanize(name)}
                        </span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                          <div
                            className={`h-full rounded-full transition-all duration-300 ${barColor(value)}`}
                            style={{
                              width: `${Math.max(value * 100, 1)}%`,
                            }}
                          />
                        </div>
                        <span
                          className={`w-10 text-right font-mono text-xs font-semibold ${textColor(value)}`}
                        >
                          {(value * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                </div>
              </DetailBlock>
            )}

            {/* LLM Judge panel toggle */}
            {hasJudge && (
              <div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setJudgeOpen((p) => !p);
                  }}
                  className="flex items-center gap-1.5 rounded-lg border border-accent/30 bg-accent/5 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/10"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 001.5 2.122V15m-6.75 0h6.75m0 0v1.125A2.25 2.25 0 0113.5 18.375H10.5A2.25 2.25 0 018.25 16.5V15m0 0h6.75" />
                  </svg>
                  {judgeOpen ? "Hide" : "Show"} LLM Evaluator Feedback
                </button>
                {judgeOpen && (
                  <div className="mt-3">
                    <MultiLLMJudgePanel
                      projectId={projectId}
                      experimentId={experimentId}
                      resultId={result.id}
                    />
                  </div>
                )}
              </div>
            )}

            {/* Criteria Judge panels — one per criteria_judge metric */}
            {criteriaMetricsInResult.map((metricName) => (
              <div key={metricName}>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleCriteriaPanel(metricName);
                  }}
                  className="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/5 px-3 py-1.5 text-xs font-medium text-purple-300 transition hover:bg-purple-500/10"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 001.5 2.122V15m-6.75 0h6.75m0 0v1.125A2.25 2.25 0 0113.5 18.375H10.5A2.25 2.25 0 018.25 16.5V15m0 0h6.75" />
                  </svg>
                  {openCriteriaPanels.has(metricName) ? "Hide" : "Show"} {metricName.replace(/_/g, " ")} Evaluations
                </button>
                {openCriteriaPanels.has(metricName) && (
                  <div className="mt-3">
                    <MultiLLMJudgePanel
                      projectId={projectId}
                      experimentId={experimentId}
                      resultId={result.id}
                      metricName={metricName}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Sub-components ── */

function DetailBlock({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      {children}
    </div>
  );
}

function ContextBlock({ index, content }: { index: number; content: string }) {
  const [open, setOpen] = useState(false);
  const preview = content.length > 200 ? content.slice(0, 200) + "..." : content;

  return (
    <div className="rounded-lg border border-border/60 bg-elevated/50 px-3 py-2">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((p) => !p);
        }}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent/10 font-mono text-2xs font-bold text-accent">
          {index}
        </span>
        <span className="min-w-0 flex-1 text-xs text-text-secondary">
          {open ? content : preview}
        </span>
        {content.length > 200 && (
          <svg
            className={`h-3 w-3 shrink-0 text-text-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 5l7 7-7 7"
            />
          </svg>
        )}
      </button>
    </div>
  );
}

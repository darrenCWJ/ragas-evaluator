import { useState } from "react";
import type { ExperimentResult } from "../../lib/api";

interface Props {
  result: ExperimentResult;
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

export default function QuestionResultRow({ result }: Props) {
  const [open, setOpen] = useState(false);

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
        <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
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
                className={`w-7 text-right font-mono text-[10px] ${textColor(value)}`}
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
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
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
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent/10 font-mono text-[10px] font-bold text-accent">
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

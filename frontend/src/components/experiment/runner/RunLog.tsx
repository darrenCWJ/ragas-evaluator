import { useEffect, useRef } from 'react';
import type { InFlightDetail, SSECompletionItem } from '../../../lib/api';

interface RunLogProps {
  inFlightDetails: InFlightDetail[];
  completedLog: SSECompletionItem[];
  connectorType: string | null;
  isBotExperiment: boolean;
}

/** In-flight question pipeline display plus the live completed-items Q&A feed. */
export default function RunLog({
  inFlightDetails,
  completedLog,
  connectorType,
  isBotExperiment,
}: RunLogProps) {
  const logEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll log to bottom when new items arrive
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [completedLog.length]);

  return (
    <>
      {/* In-flight questions with per-question pipeline */}
      {inFlightDetails.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-text-muted">
            Processing ({inFlightDetails.length} in parallel)
          </p>
          <div className="space-y-2">
            {inFlightDetails.map((detail, i) => {
              const totalMetrics =
                detail.metrics_done.length +
                detail.metrics_active.length +
                detail.metrics_pending.length;
              const doneCount = detail.metrics_done.length;
              const scoringPct = totalMetrics > 0 ? (doneCount / totalMetrics) * 100 : 0;

              return (
                <div key={i} className="rounded-lg border border-border/60 bg-card/50 px-3 py-2.5">
                  {/* Question text */}
                  <p className="mb-2 text-xs leading-relaxed text-text-secondary">
                    {detail.question}
                  </p>

                  {/* Pipeline steps */}
                  <div className="space-y-1.5">
                    {/* Step 1: Querying */}
                    <div className="flex items-center gap-2">
                      {detail.phase === 'querying' ? (
                        <svg
                          className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-400"
                          viewBox="0 0 24 24"
                          fill="none"
                        >
                          <circle
                            className="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            strokeWidth="4"
                          />
                          <path
                            className="opacity-75"
                            fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                          />
                        </svg>
                      ) : (
                        <svg
                          className="h-3.5 w-3.5 shrink-0 text-green-400"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                      <span
                        className={`text-xs ${detail.phase === 'querying' ? 'text-blue-300' : 'text-text-muted'}`}
                      >
                        {connectorType === 'csv'
                          ? 'Using pre-loaded data'
                          : isBotExperiment
                            ? 'Querying bot'
                            : 'Running RAG pipeline'}
                      </span>
                    </div>

                    {/* Step 2: Scoring metrics */}
                    <div className="flex items-center gap-2">
                      {detail.phase === 'querying' ? (
                        <div className="h-3.5 w-3.5 shrink-0 rounded-full border border-border" />
                      ) : doneCount < totalMetrics ? (
                        <svg
                          className="h-3.5 w-3.5 shrink-0 animate-spin text-purple-400"
                          viewBox="0 0 24 24"
                          fill="none"
                        >
                          <circle
                            className="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            strokeWidth="4"
                          />
                          <path
                            className="opacity-75"
                            fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                          />
                        </svg>
                      ) : (
                        <svg
                          className="h-3.5 w-3.5 shrink-0 text-green-400"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                      <span
                        className={`text-xs ${detail.phase === 'scoring' ? 'text-purple-300' : 'text-text-muted'}`}
                      >
                        Evaluating metrics{' '}
                        {detail.phase === 'scoring' && totalMetrics > 0
                          ? `(${doneCount}/${totalMetrics})`
                          : ''}
                      </span>
                    </div>

                    {/* Metric progress bar + detail when scoring */}
                    {detail.phase === 'scoring' && totalMetrics > 0 && (
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
                            <span
                              key={m}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-green-500/10 text-green-400"
                            >
                              {m.replace(/_/g, ' ')} ✓
                            </span>
                          ))}
                          {detail.metrics_active.map((m) => (
                            <span
                              key={m}
                              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium bg-purple-500/10 text-purple-300"
                            >
                              <span className="inline-block h-1 w-1 animate-pulse rounded-full bg-purple-400" />
                              {m.replace(/_/g, ' ')}
                            </span>
                          ))}
                          {detail.metrics_pending.map((m) => (
                            <span
                              key={m}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-zinc-500/10 text-text-muted"
                            >
                              {m.replace(/_/g, ' ')}
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
          <p className="text-xs font-medium text-text-muted">Completed ({completedLog.length})</p>
          <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-border bg-elevated/30 p-2">
            {completedLog.map((item, i) => (
              <div
                key={i}
                className={`rounded-lg border px-3 py-2 ${
                  item.error ? 'border-red-500/20 bg-red-500/5' : 'border-border/60 bg-card/50'
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
                            ? 'bg-zinc-500/10 text-text-muted'
                            : value >= 0.7
                              ? 'bg-green-500/10 text-green-400'
                              : value >= 0.4
                                ? 'bg-yellow-500/10 text-yellow-400'
                                : 'bg-red-500/10 text-red-400'
                        }`}
                      >
                        {name.replace(/_/g, ' ')}: {value !== null ? value.toFixed(2) : '—'}
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
    </>
  );
}

import { useState, useEffect, useCallback } from "react";
import { fetchProjectReport } from "../../lib/api";
import type { ProjectReport, BotSummary } from "../../lib/api";
import { humanizeMetric, scoreBarColor, scoreTextColor, scoreBgColor } from "./scoreUtils";

interface Props {
  projectId: number;
}

export default function ProjectReportPanel({ projectId }: Props) {
  const [report, setReport] = useState<ProjectReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchProjectReport(projectId);
      setReport(data);
    } catch (err) {
      setError((err as Error).message || "Failed to load report");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="py-6 text-center text-sm text-text-muted">Loading project report...</div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    );
  }

  if (!report || report.total_experiments === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-6 text-center text-sm text-text-muted">
        No completed experiments yet.
      </div>
    );
  }

  const overallMetricEntries = report.overall_metrics
    ? (Object.entries(report.overall_metrics).filter(
        (e): e is [string, number] => e[1] !== null,
      ) as [string, number][])
    : [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Project Report
        </h3>
        <span className="text-xs text-text-muted">
          {report.total_experiments} experiment{report.total_experiments !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Overall metrics */}
      {overallMetricEntries.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Overall Metrics (All Experiments)
          </h4>
          <div className="space-y-2">
            {overallMetricEntries
              .sort((a, b) => b[1] - a[1])
              .map(([name, value]) => (
                <div key={name} className="flex items-center gap-3">
                  <span className="w-36 shrink-0 truncate text-xs font-medium text-text-secondary">
                    {humanizeMetric(name)}
                  </span>
                  <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(value)}`}
                      style={{ width: `${Math.max(value * 100, 1)}%` }}
                    />
                  </div>
                  <span className={`w-10 text-right font-mono text-xs font-semibold ${scoreTextColor(value)}`}>
                    {(value * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Bot summary */}
      {report.bot_summary.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Per-Bot Performance
          </h4>
          <div className="space-y-3">
            {report.bot_summary.map((bot: BotSummary) => {
              const botMetrics = Object.entries(bot.aggregate_metrics).filter(
                (e): e is [string, number] => e[1] !== null,
              );
              return (
                <div key={bot.bot_config_id} className="rounded-lg border border-border/50 bg-elevated/30 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-text-primary">
                        {bot.bot_config_name ?? `Bot #${bot.bot_config_id}`}
                      </span>
                      <span className="rounded bg-elevated px-1.5 py-0.5 text-xs text-text-muted">
                        {bot.connector_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-text-muted">
                        {bot.experiment_count} exp{bot.experiment_count !== 1 ? "s" : ""}
                      </span>
                      {bot.overall_score !== null && (
                        <span className={`font-mono text-sm font-bold ${scoreTextColor(bot.overall_score)}`}>
                          {(bot.overall_score * 100).toFixed(0)}
                        </span>
                      )}
                    </div>
                  </div>
                  {botMetrics.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {botMetrics.map(([name, value]) => (
                        <span
                          key={name}
                          className={`rounded px-2 py-0.5 text-xs ${scoreBgColor(value)} ${scoreTextColor(value)}`}
                        >
                          {humanizeMetric(name)}: {(value * 100).toFixed(0)}%
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Source verification summary */}
      {report.overall_source_verification && (
        <div className="rounded-xl border border-border bg-card p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Source Verification Summary
          </h4>
          <div className="grid grid-cols-4 gap-2">
            <div className="rounded-lg bg-score-high/10 px-3 py-2 text-center">
              <div className="text-lg font-bold text-score-high">
                {report.overall_source_verification.pct_verified}%
              </div>
              <div className="text-xs text-text-muted">Verified</div>
            </div>
            <div className="rounded-lg bg-score-low/10 px-3 py-2 text-center">
              <div className="text-lg font-bold text-score-low">
                {report.overall_source_verification.pct_hallucinated}%
              </div>
              <div className="text-xs text-text-muted">Hallucinated</div>
            </div>
            <div className="rounded-lg bg-yellow-500/10 px-3 py-2 text-center">
              <div className="text-lg font-bold text-yellow-400">
                {report.overall_source_verification.inaccessible}
              </div>
              <div className="text-xs text-text-muted">Inaccessible</div>
            </div>
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-muted">
                {report.overall_source_verification.total}
              </div>
              <div className="text-xs text-text-muted">Total</div>
            </div>
          </div>
        </div>
      )}

      {/* Evaluator reliability */}
      {report.overall_evaluator_reliability && (
        <div className="rounded-xl border border-border bg-card p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Evaluator Reliability
          </h4>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {(report.overall_evaluator_reliability.agreement_rate * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-text-muted">Agreement Rate</div>
            </div>
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {report.overall_evaluator_reliability.agreements}/{report.overall_evaluator_reliability.scorable_count}
              </div>
              <div className="text-xs text-text-muted">Agreements</div>
            </div>
            <div className="rounded-lg bg-elevated px-3 py-2 text-center">
              <div className="text-lg font-bold text-text-primary">
                {report.overall_evaluator_reliability.total_annotations}
              </div>
              <div className="text-xs text-text-muted">Total Annotations</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

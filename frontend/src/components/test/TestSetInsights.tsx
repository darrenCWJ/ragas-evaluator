import { useState } from 'react';
import { fetchTestSetCoverage, runQualityAudit } from '../../lib/api';
import type { CoverageReport, QualityAuditSummary } from '../../lib/api';
import { useFetch } from '../../hooks/useFetch';
import { Button, ErrorAlert, ScoreBar, Spinner } from '../ui';

/** Human descriptions for audit flags (chip labels). */
export const QUALITY_FLAG_LABELS: Record<string, string> = {
  too_short: 'Question is too short',
  no_reference: 'Missing reference answer',
  no_contexts: 'No reference contexts',
  verbatim_leakage: 'Question copies source text',
  ungrounded: 'Answer not grounded in contexts',
  not_self_contained: 'Question depends on unstated context',
  trivial: 'Question is trivially easy',
};

interface Props {
  projectId: number;
  testSetId: number;
  /** Called after an audit completes so the parent can refresh question data. */
  onAudited?: () => void;
}

/** Quality audit + corpus coverage panel for the selected test set. */
export default function TestSetInsights({ projectId, testSetId, onAudited }: Props) {
  const [auditing, setAuditing] = useState<'quick' | 'deep' | null>(null);
  const [audit, setAudit] = useState<QualityAuditSummary | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [showUncovered, setShowUncovered] = useState(false);

  const coverage = useFetch<CoverageReport>(
    () => fetchTestSetCoverage(projectId, testSetId),
    [projectId, testSetId],
  );

  const handleAudit = async (useLlm: boolean) => {
    setAuditing(useLlm ? 'deep' : 'quick');
    setAuditError(null);
    try {
      const summary = await runQualityAudit(projectId, testSetId, useLlm);
      setAudit(summary);
      onAudited?.();
    } catch (err) {
      setAuditError(err instanceof Error ? err.message : 'Audit failed');
    } finally {
      setAuditing(null);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      {/* ── Quality audit ── */}
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
          Test Set Quality
        </h4>
        <span className="flex-1" />
        <Button
          variant="secondary"
          loading={auditing === 'quick'}
          disabled={auditing !== null}
          onClick={() => handleAudit(false)}
          className="!px-3 !py-1.5 !text-xs"
        >
          Quick audit (free)
        </Button>
        <Button
          variant="secondary"
          loading={auditing === 'deep'}
          disabled={auditing !== null}
          onClick={() => handleAudit(true)}
          className="!px-3 !py-1.5 !text-xs"
        >
          Deep audit (uses LLM)
        </Button>
      </div>
      <p className="mt-1 text-xs text-text-muted">
        Deep audit makes one LLM call per question — slower and costs tokens. Quick audit runs only
        deterministic checks.
      </p>

      <div className="mt-2">
        <ErrorAlert message={auditError} onDismiss={() => setAuditError(null)} />
      </div>

      {audit && (
        <div className="mt-3 space-y-2.5">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="text-text-secondary">
              {audit.audited} question{audit.audited !== 1 ? 's' : ''} audited
              {audit.use_llm ? ' (deep)' : ' (quick)'}
            </span>
            <span className="text-text-muted">·</span>
            <span className="flex items-center gap-2 text-text-secondary">
              Avg quality <ScoreBar value={audit.avg_score} />
            </span>
            <span className="text-text-muted">·</span>
            <span
              className={
                audit.flagged_question_ids.length > 0 ? 'text-yellow-300' : 'text-green-300'
              }
            >
              {audit.flagged_question_ids.length} flagged
            </span>
          </div>

          {Object.keys(audit.flag_counts).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(audit.flag_counts).map(([flag, count]) => (
                <span
                  key={flag}
                  title={flag}
                  className="rounded-full bg-yellow-500/15 px-2 py-0.5 text-xs text-yellow-300"
                >
                  {QUALITY_FLAG_LABELS[flag] ?? flag.replace(/_/g, ' ')}
                  <span className="ml-1 font-semibold">{count}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Coverage ── */}
      <div className="mt-4 border-t border-border pt-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
          Corpus Coverage
        </h4>

        {coverage.loading && (
          <div className="mt-2 flex items-center gap-2 text-xs text-text-muted">
            <Spinner size="sm" /> Computing coverage…
          </div>
        )}
        {coverage.error && (
          <div className="mt-2">
            <ErrorAlert message={coverage.error} />
          </div>
        )}

        {coverage.data && (
          <div className="mt-2 space-y-2 text-xs">
            <div className="flex flex-wrap items-center gap-3">
              <span
                className={
                  coverage.data.covered_documents < coverage.data.total_documents
                    ? 'text-yellow-300'
                    : 'text-green-300'
                }
              >
                {coverage.data.covered_documents} / {coverage.data.total_documents} documents
                covered
              </span>
              <span className="text-text-muted">·</span>
              <span className="flex items-center gap-2 text-text-secondary">
                Chunk coverage <ScoreBar value={coverage.data.chunk_coverage} />
              </span>
              <span className="text-text-muted">·</span>
              <span className="text-text-muted">
                {coverage.data.questions_with_provenance} / {coverage.data.total_questions}{' '}
                questions traceable to sources
              </span>
            </div>

            {coverage.data.uncovered_documents.length > 0 && (
              <div>
                <button
                  onClick={() => setShowUncovered(!showUncovered)}
                  className="flex items-center gap-1 text-yellow-300 transition hover:text-yellow-200"
                >
                  <svg
                    className={`h-3 w-3 transition-transform ${showUncovered ? 'rotate-90' : ''}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                  {coverage.data.uncovered_documents.length} untested document
                  {coverage.data.uncovered_documents.length !== 1 ? 's' : ''}
                </button>
                {showUncovered && (
                  <div className="mt-1.5 rounded-lg bg-deep px-3 py-2">
                    <p className="text-text-muted">No test questions exercise these documents:</p>
                    <ul className="mt-1 space-y-0.5">
                      {coverage.data.uncovered_documents.map((filename) => (
                        <li key={filename} className="truncate font-mono text-text-secondary">
                          {filename}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

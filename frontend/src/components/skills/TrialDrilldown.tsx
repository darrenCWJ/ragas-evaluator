import { useState } from 'react';
import { fetchSkillTrialResults } from '../../api';
import type { DirectiveResult, SkillTrialResult, SkillTrialVariant } from '../../api';
import { useFetch } from '../../hooks/useFetch';
import { Card, EmptyState, ErrorAlert, ScoreBar, Spinner } from '../ui';
import TraceTimeline from './TraceTimeline';

interface TrialDrilldownProps {
  projectId: number;
  trialId: number;
  model: string;
  variant: SkillTrialVariant;
}

const VERDICT_CLASSES: Record<DirectiveResult['verdict'], string> = {
  pass: 'bg-score-high/15 text-score-high',
  fail: 'bg-score-low/15 text-score-low',
  not_applicable: 'bg-elevated text-text-muted',
};

function VerdictChip({ result }: { result: DirectiveResult }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium ${VERDICT_CLASSES[result.verdict]}`}
      title={result.reasoning}
    >
      {result.id}
      <span className="font-normal opacity-80">
        {result.verdict === 'not_applicable' ? 'n/a' : result.verdict}
      </span>
      {result.deterministic && (
        <span className="opacity-70" title="Deterministic format check (not judge-scored)">
          &#9881;
        </span>
      )}
    </span>
  );
}

function ResultRow({ result }: { result: SkillTrialResult }) {
  const [showResponse, setShowResponse] = useState(false);

  return (
    <Card variant="muted" padding="md" className="space-y-2">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 text-sm text-text-primary">{result.question}</p>
        <div className="flex shrink-0 items-center gap-3 text-2xs text-text-muted">
          {result.latency_ms != null && <span>{(result.latency_ms / 1000).toFixed(1)}s</span>}
          {result.tokens_in != null && result.tokens_out != null && (
            <span>
              {result.tokens_in}&rarr;{result.tokens_out} tok
            </span>
          )}
        </div>
      </div>

      {result.error ? (
        <ErrorAlert message={result.error} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <span className="flex items-center gap-2 text-2xs text-text-muted">
              adherence <ScoreBar value={result.scores.skill_adherence ?? null} />
            </span>
            <span className="flex items-center gap-2 text-2xs text-text-muted">
              format <ScoreBar value={result.scores.format_compliance ?? null} />
            </span>
          </div>

          {result.directive_results.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {result.directive_results.map((d) => (
                <VerdictChip key={d.id} result={d} />
              ))}
            </div>
          )}

          <button
            onClick={() => setShowResponse((v) => !v)}
            className="text-xs text-accent hover:underline"
          >
            {showResponse ? 'Hide response' : 'Show response'}
          </button>
          {showResponse && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-input p-3 text-xs text-text-secondary">
              {result.response ?? '(empty response)'}
            </pre>
          )}
        </>
      )}

      <TraceTimeline trace={result.trace} />
    </Card>
  );
}

/** Per-question results for one model + variant cell of the trial matrix. */
export default function TrialDrilldown({
  projectId,
  trialId,
  model,
  variant,
}: TrialDrilldownProps) {
  const {
    data: results,
    loading,
    error,
  } = useFetch(
    () => fetchSkillTrialResults(projectId, trialId, { model, variant }),
    [projectId, trialId, model, variant],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-text-muted">
        <Spinner size="sm" /> Loading results for {model} ({variant})...
      </div>
    );
  }
  if (error) return <ErrorAlert message={error} />;
  if (!results || results.length === 0) {
    return <EmptyState title={`No results yet for ${model} (${variant}).`} />;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-text-muted">
        {model} &middot; {variant} &middot; {results.length} question
        {results.length !== 1 ? 's' : ''}
      </p>
      {results.map((r) => (
        <ResultRow key={r.id} result={r} />
      ))}
    </div>
  );
}

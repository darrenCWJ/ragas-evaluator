import { useState } from 'react';
import { runPromptDoctor } from '../../lib/api';
import type { PromptDoctorResult } from '../../lib/api';
import Button from '../ui/Button';
import ErrorAlert from '../ui/ErrorAlert';
import CopyButton from '../ui/CopyButton';

interface Props {
  projectId: number;
  experimentId: number;
  /** Called after a successful run — the doctor inserts rows into the suggestions list. */
  onSuggestionsCreated: () => void;
}

const ADDITION_TYPE_LABELS: Record<string, string> = {
  persona: 'Persona',
  guardrail: 'Guardrail',
  phase: 'Phase',
};

export default function PromptDoctorPanel({
  projectId,
  experimentId,
  onSuggestionsCreated,
}: Props) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PromptDoctorResult | null>(null);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await runPromptDoctor(projectId, experimentId);
      setResult(res);
      onSuggestionsCreated();
    } catch (err) {
      setError((err as Error).message || 'Prompt doctor failed');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-border bg-base/40 px-4 py-3">
      {/* Action row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-text-primary">Prompt doctor</p>
          <p className="mt-0.5 text-xs text-text-muted">
            Drafts a revised system prompt from your worst results (uses LLM)
          </p>
        </div>
        <Button
          variant="secondary"
          loading={running}
          onClick={handleRun}
          className="shrink-0 !px-3 !py-1.5 !text-xs"
        >
          {running ? 'Diagnosing...' : result ? 'Run again' : 'Run prompt doctor'}
        </Button>
      </div>

      {/* Slow-call hint while running */}
      {running && (
        <p className="text-xs text-text-muted">
          Analyzing your worst results — this can take up to 30 seconds...
        </p>
      )}

      {/* Error */}
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      {/* Result */}
      {result && !running && (
        <div className="space-y-3">
          {/* Diagnosis */}
          {result.diagnosis.length > 0 && (
            <div>
              <h5 className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                Diagnosis
              </h5>
              <ul className="mt-1.5 space-y-1">
                {result.diagnosis.map((item, i) => (
                  <li key={i} className="flex gap-2 text-xs text-text-primary">
                    <span className="shrink-0 text-accent">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Additions */}
          {result.additions.length > 0 && (
            <div>
              <h5 className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                Additions
              </h5>
              <ul className="mt-1.5 space-y-1">
                {result.additions.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5 shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-2xs font-medium text-accent">
                      {ADDITION_TYPE_LABELS[a.type] ?? a.type}
                    </span>
                    <span className="text-text-secondary">{a.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* External agent note */}
          {result.external_agent && (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              This experiment tests an external agent — copy the prompt into your agent's own
              configuration.
            </div>
          )}

          {/* Revised prompt */}
          <div className="rounded-lg border border-border bg-base">
            <div className="flex items-center justify-between gap-3 border-b border-border/60 px-3 py-1.5">
              <span className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                Revised system prompt
              </span>
              <CopyButton text={result.revised_system_prompt} label="Copy prompt" />
            </div>
            <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-xs leading-relaxed text-text-primary">
              {result.revised_system_prompt}
            </pre>
          </div>

          {/* Suggestions created note */}
          {result.suggestions_created > 0 && (
            <p className="text-xs text-text-muted">
              {result.suggestions_created} suggestion
              {result.suggestions_created !== 1 ? 's' : ''} added to the list below.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

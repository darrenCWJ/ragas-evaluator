import { useState } from 'react';
import type { AgentTurn, SkillDryRunResult } from '../../api';
import { Button, Spinner, TextInput } from '../ui';

export interface PlaygroundRun {
  status: 'running' | 'awaiting_input' | 'completed' | 'error';
  result: SkillDryRunResult | null;
  error?: string;
}

/** One round of the transcript: thought + the tool calls it made. */
function TurnView({ turn }: { turn: AgentTurn }) {
  return (
    <div className="space-y-1">
      {turn.thought && (
        <div className="flex gap-2">
          <span className="shrink-0 text-2xs" title="Model reasoning this round">
            💭
          </span>
          <p className="min-w-0 whitespace-pre-wrap text-xs italic text-text-secondary">
            {turn.thought}
          </p>
        </div>
      )}
      {turn.steps.map((step, j) =>
        step.tool === 'ask_user' ? (
          <div key={j} className="space-y-0.5">
            <div className="flex gap-2">
              <span className="shrink-0 text-2xs" title="Model asked the user">
                ❓
              </span>
              <p className="min-w-0 text-xs text-text-primary">
                {String(step.arguments.question ?? '')}
              </p>
            </div>
            <div className="flex gap-2 pl-5">
              <span
                className="shrink-0 text-2xs"
                title={
                  step.simulated
                    ? 'AI-simulated user — answered from your project details brief'
                    : 'User reply (you or your script)'
                }
              >
                {step.simulated ? '🤖' : '🧑'}
              </span>
              <p className="min-w-0 whitespace-pre-wrap text-xs text-accent">{step.result}</p>
            </div>
          </div>
        ) : (
          <div key={j} className="flex gap-2">
            <span className="shrink-0 text-2xs" title="Tool call">
              🔧
            </span>
            <div className="min-w-0 text-xs">
              <span className={`font-mono ${step.error ? 'text-score-low' : 'text-accent'}`}>
                {step.tool}
              </span>
              <span className="ml-1.5 break-all font-mono text-2xs text-text-muted">
                {JSON.stringify(step.arguments)}
              </span>
              {step.error ? (
                <p className="text-2xs text-score-low">{step.error}</p>
              ) : (
                <p className="line-clamp-2 break-all text-2xs text-text-muted">{step.result}</p>
              )}
            </div>
          </div>
        ),
      )}
    </div>
  );
}

interface PlaygroundRunPanelProps {
  model: string;
  modelName: string;
  run: PlaygroundRun;
  onContinue: (model: string, answer: string) => void;
}

/** One model's live playground run: transcript, pause-for-input box, answer. */
export default function PlaygroundRunPanel({
  model,
  modelName,
  run,
  onContinue,
}: PlaygroundRunPanelProps) {
  const [pendingAnswer, setPendingAnswer] = useState('');
  const result = run.result;
  const awaiting = run.status === 'awaiting_input';

  const submitAnswer = () => {
    if (!pendingAnswer.trim()) return;
    onContinue(model, pendingAnswer.trim());
    setPendingAnswer('');
  };

  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs font-medium text-text-primary" title={model}>
          {modelName}
        </span>
        {run.status === 'running' && <Spinner size="sm" />}
        {run.status === 'awaiting_input' && (
          <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-2xs text-accent">
            waiting for you
          </span>
        )}
        {run.status === 'completed' && (
          <span className="shrink-0 rounded-full bg-score-high/10 px-2 py-0.5 text-2xs text-score-high">
            done
          </span>
        )}
        {run.status === 'error' && (
          <span className="shrink-0 rounded-full bg-score-low/10 px-2 py-0.5 text-2xs text-score-low">
            failed
          </span>
        )}
      </div>

      {run.status === 'error' && <p className="text-xs text-score-low">{run.error}</p>}

      {result && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-text-muted">
            <span>{result.turns.length} rounds</span>
            <span>{result.files_read.length} files</span>
            <span>{result.user_exchanges} exchanges</span>
            <span>
              {result.tokens_in}&rarr;{result.tokens_out} tok
            </span>
            {result.cost_usd != null && (
              <span title="Estimated cost from the model registry's per-token prices">
                ${result.cost_usd.toFixed(4)}
              </span>
            )}
            {result.stage_scores && (
              <span
                className="rounded-full bg-accent/10 px-1.5 py-0.5 text-accent"
                title="Stage-plan files read / read in plan order"
              >
                stages {(result.stage_scores.stage_coverage * 100).toFixed(0)}% · order{' '}
                {(result.stage_scores.stage_order * 100).toFixed(0)}%
              </span>
            )}
          </div>

          <div className="max-h-96 space-y-2 overflow-y-auto rounded-lg bg-input p-2.5">
            {result.turns.length === 0 && !awaiting && (
              <p className="text-xs text-text-muted">
                Answered directly without using any tools — likely skipped the process.
              </p>
            )}
            {result.turns.map((turn, i) => (
              <TurnView key={i} turn={turn} />
            ))}

            {awaiting ? (
              <div className="space-y-2 rounded-lg border border-accent/40 bg-accent/5 p-2.5">
                <div className="flex gap-2">
                  <span className="shrink-0 text-2xs" title="The model is asking you">
                    ❓
                  </span>
                  <p className="min-w-0 text-xs font-medium text-text-primary">
                    {result.question || '(the model asked a question)'}
                  </p>
                </div>
                <div className="flex gap-2">
                  <TextInput
                    value={pendingAnswer}
                    onChange={(e) => setPendingAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') submitAnswer();
                    }}
                    placeholder="Your answer..."
                  />
                  <Button onClick={submitAnswer} disabled={!pendingAnswer.trim()}>
                    Send
                  </Button>
                </div>
              </div>
            ) : (
              run.status === 'completed' && (
                <div className="flex gap-2 border-t border-border/50 pt-2">
                  <span className="shrink-0 text-2xs" title="Final answer">
                    ✅
                  </span>
                  <pre className="max-h-48 min-w-0 overflow-auto whitespace-pre-wrap text-xs text-text-primary">
                    {result.answer || '(empty answer)'}
                  </pre>
                </div>
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}

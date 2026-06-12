import { useState } from 'react';
import { continueDryRun, dryRunSkill } from '../../api';
import type { AgentTurn, JudgeModel, Skill, SkillDryRunResult } from '../../api';
import { Button, Card, ErrorAlert, FormField, Select, TextArea, TextInput } from '../ui';

interface SkillPlaygroundProps {
  projectId: number;
  skills: Skill[];
  judgeModels: JudgeModel[];
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
              <span className="shrink-0 text-2xs" title="User reply">
                🧑
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

/**
 * Watch a single model walk a skill on one ad-hoc prompt — no test set, no
 * judging, nothing stored. Made for process-flow skills where the point is
 * HOW the model works through the stages, not the final answer.
 *
 * Interactive mode pauses whenever the model asks the user something and
 * lets YOU type the answer; otherwise a simulated user replies.
 */
export default function SkillPlayground({ projectId, skills, judgeModels }: SkillPlaygroundProps) {
  const [skillId, setSkillId] = useState<number | ''>('');
  const [model, setModel] = useState('');
  const [prompt, setPrompt] = useState('');
  const [userInputs, setUserInputs] = useState('');
  const [interactive, setInteractive] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SkillDryRunResult | null>(null);
  const [pendingAnswer, setPendingAnswer] = useState('');
  const [error, setError] = useState<string | null>(null);

  const usableModels = judgeModels.filter((m) => m.enabled !== false && m.available);
  const selectedSkill = skills.find((s) => s.id === skillId);
  const canRun = skillId !== '' && model && prompt.trim().length >= 3 && !running;
  const awaiting = result?.status === 'awaiting_input';

  const handleRun = async () => {
    if (skillId === '') return;
    setRunning(true);
    setError(null);
    setResult(null);
    setPendingAnswer('');
    try {
      const scripted = userInputs
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 5);
      const res = await dryRunSkill(projectId, skillId, {
        prompt: prompt.trim(),
        model,
        user_inputs: scripted,
        interactive,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dry run failed');
    } finally {
      setRunning(false);
    }
  };

  const handleContinue = async () => {
    if (!result?.run_id || !pendingAnswer.trim()) return;
    setRunning(true);
    setError(null);
    try {
      const res = await continueDryRun(projectId, result.run_id, pendingAnswer.trim());
      setResult(res);
      setPendingAnswer('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to continue the run');
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card padding="lg" className="space-y-4">
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Skill">
          <Select
            value={skillId}
            onChange={(e) => setSkillId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select a skill...</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} v{s.version}
                {(s.stage_count ?? 0) > 0 ? ` — ${s.stage_count} stages` : ''}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Model" hint="Models with an API key configured">
          <Select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">Select a model...</option>
            {usableModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.provider})
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <FormField
        label="Task prompt"
        hint="The user request that kicks off the skill's flow, e.g. 'Build a daily payment reconciliation app'"
      >
        <TextArea
          rows={2}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What should the model work on?"
        />
      </FormField>

      <FormField
        label="Scripted user replies (optional)"
        hint="One per line — used in order when the model asks something, before pausing for you (interactive) or handing off to the simulator"
      >
        <TextArea
          rows={2}
          value={userInputs}
          onChange={(e) => setUserInputs(e.target.value)}
          placeholder={'e.g.\ncall it fraud-alert-daily\ndaily at 02:00'}
        />
      </FormField>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary"
            title="Pause the run whenever the model asks the user a question, and answer it yourself. Off = an LLM simulates the user."
          >
            <input
              type="checkbox"
              className="accent-accent"
              checked={interactive}
              onChange={(e) => setInteractive(e.target.checked)}
            />
            Interactive — I answer the model&apos;s questions myself
          </label>
          <span className="text-xs text-text-muted">
            Nothing is saved, no judge involved.
            {selectedSkill && (selectedSkill.files?.length ?? 0) > 0
              ? ` ${selectedSkill.files?.length} reference files available.`
              : ''}
          </span>
        </div>
        <Button onClick={handleRun} loading={running && !awaiting} disabled={!canRun}>
          {running && !awaiting ? 'Watching the model work...' : 'Run'}
        </Button>
      </div>

      {result && (
        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-text-muted">
            <span>{result.turns.length} rounds</span>
            <span>{result.files_read.length} files read</span>
            <span>{result.user_exchanges} user exchanges</span>
            <span>
              {result.tokens_in}&rarr;{result.tokens_out} tok
            </span>
            <span>{(result.latency_ms / 1000).toFixed(1)}s</span>
            {result.stage_scores && (
              <span
                className="rounded-full bg-accent/10 px-2 py-0.5 text-accent"
                title="Stage-plan files read / read in plan order"
              >
                stages {(result.stage_scores.stage_coverage * 100).toFixed(0)}% · order{' '}
                {(result.stage_scores.stage_order * 100).toFixed(0)}%
              </span>
            )}
          </div>

          <div className="space-y-2 rounded-lg bg-input p-3">
            {result.turns.length === 0 && !awaiting && (
              <p className="text-xs text-text-muted">
                The model answered directly without using any tools — for staged skills that usually
                means it skipped the process.
              </p>
            )}
            {result.turns.map((turn, i) => (
              <TurnView key={i} turn={turn} />
            ))}

            {awaiting ? (
              <div className="space-y-2 rounded-lg border border-accent/40 bg-accent/5 p-3">
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
                      if (e.key === 'Enter') handleContinue();
                    }}
                    placeholder="Type your answer and press Enter..."
                  />
                  <Button
                    onClick={handleContinue}
                    loading={running}
                    disabled={!pendingAnswer.trim() || running}
                  >
                    Continue
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex gap-2 border-t border-border/50 pt-2">
                <span className="shrink-0 text-2xs" title="Final answer">
                  ✅
                </span>
                <pre className="max-h-72 min-w-0 overflow-auto whitespace-pre-wrap text-xs text-text-primary">
                  {result.answer || '(empty answer)'}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

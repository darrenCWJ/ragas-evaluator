import { useState } from 'react';
import { dryRunSkill } from '../../api';
import type { JudgeModel, Skill, SkillDryRunResult } from '../../api';
import { Button, Card, ErrorAlert, FormField, Select, TextArea, TextInput } from '../ui';

interface SkillPlaygroundProps {
  projectId: number;
  skills: Skill[];
  judgeModels: JudgeModel[];
}

/**
 * Watch a single model walk a skill on one ad-hoc prompt — no test set, no
 * judging, nothing stored. Made for process-flow skills where the point is
 * HOW the model works through the stages, not the final answer.
 */
export default function SkillPlayground({ projectId, skills, judgeModels }: SkillPlaygroundProps) {
  const [skillId, setSkillId] = useState<number | ''>('');
  const [model, setModel] = useState('');
  const [prompt, setPrompt] = useState('');
  const [userInputs, setUserInputs] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SkillDryRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const usableModels = judgeModels.filter((m) => m.enabled !== false && m.available);
  const selectedSkill = skills.find((s) => s.id === skillId);
  const canRun = skillId !== '' && model && prompt.trim().length >= 3 && !running;

  const handleRun = async () => {
    if (skillId === '') return;
    setRunning(true);
    setError(null);
    setResult(null);
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
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dry run failed');
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
        hint="One per line — used in order when the model asks the user something; a simulated user answers after they run out"
      >
        <TextInput
          value={userInputs}
          onChange={(e) => setUserInputs(e.target.value)}
          placeholder="e.g. call it fraud-alert-daily"
        />
      </FormField>

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-text-muted">
          Agentic dry run — nothing is saved, no judge is involved.
          {selectedSkill && (selectedSkill.files?.length ?? 0) > 0
            ? ` ${selectedSkill.files?.length} reference files available via read_file.`
            : ''}
        </span>
        <Button onClick={handleRun} loading={running} disabled={!canRun}>
          {running ? 'Watching the model work...' : 'Run'}
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
            {result.turns.length === 0 && (
              <p className="text-xs text-text-muted">
                The model answered directly without using any tools — for staged skills that
                usually means it skipped the process.
              </p>
            )}
            {result.turns.map((turn, i) => (
              <div key={i} className="space-y-1">
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
                {turn.steps.map((step, j) => (
                  <div key={j} className="flex gap-2">
                    <span className="shrink-0 text-2xs" title="Tool call">
                      🔧
                    </span>
                    <div className="min-w-0 text-xs">
                      <span
                        className={`font-mono ${step.error ? 'text-score-low' : 'text-accent'}`}
                      >
                        {step.tool}
                      </span>
                      <span className="ml-1.5 break-all font-mono text-2xs text-text-muted">
                        {JSON.stringify(step.arguments)}
                      </span>
                      {step.error ? (
                        <p className="text-2xs text-score-low">{step.error}</p>
                      ) : (
                        <p className="line-clamp-2 break-all text-2xs text-text-muted">
                          {step.result}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ))}
            <div className="flex gap-2 border-t border-border/50 pt-2">
              <span className="shrink-0 text-2xs" title="Final answer">
                ✅
              </span>
              <pre className="max-h-72 min-w-0 overflow-auto whitespace-pre-wrap text-xs text-text-primary">
                {result.answer || '(empty answer)'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

import { useState } from 'react';
import { continueDryRun, dryRunSkill } from '../../api';
import type { JudgeModel, Skill } from '../../api';
import { Button, Card, ErrorAlert, FormField, Select, TextArea } from '../ui';
import PlaygroundRunPanel, { type PlaygroundRun } from './PlaygroundRunPanel';

interface SkillPlaygroundProps {
  projectId: number;
  skills: Skill[];
  judgeModels: JudgeModel[];
}

const MAX_PARALLEL_MODELS = 6;

/**
 * Watch one or more models walk a skill on a single ad-hoc prompt — no test
 * set, no judging, nothing stored. Runs all selected models in parallel with
 * a side-by-side transcript per model, so you can compare HOW each one works
 * through the stages. Interactive mode pauses each run on its own questions.
 */
export default function SkillPlayground({ projectId, skills, judgeModels }: SkillPlaygroundProps) {
  const [skillId, setSkillId] = useState<number | ''>('');
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [userInputs, setUserInputs] = useState('');
  const [interactive, setInteractive] = useState(true);
  const [runs, setRuns] = useState<Record<string, PlaygroundRun>>({});
  const [error, setError] = useState<string | null>(null);

  const usableModels = judgeModels.filter((m) => m.enabled !== false && m.available);
  const selectedSkill = skills.find((s) => s.id === skillId);
  const anyRunning = Object.values(runs).some((r) => r.status === 'running');
  const canRun =
    skillId !== '' && selectedModels.length > 0 && prompt.trim().length >= 3 && !anyRunning;

  const toggleModel = (id: string) => {
    setSelectedModels((prev) =>
      prev.includes(id)
        ? prev.filter((m) => m !== id)
        : prev.length < MAX_PARALLEL_MODELS
          ? [...prev, id]
          : prev,
    );
  };

  const setRun = (model: string, run: PlaygroundRun) => {
    setRuns((prev) => ({ ...prev, [model]: run }));
  };

  const handleRunAll = () => {
    if (skillId === '') return;
    setError(null);
    const scripted = userInputs
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 5);

    const initial: Record<string, PlaygroundRun> = {};
    for (const model of selectedModels) {
      initial[model] = { status: 'running', result: null };
    }
    setRuns(initial);

    for (const model of selectedModels) {
      dryRunSkill(projectId, skillId, {
        prompt: prompt.trim(),
        model,
        user_inputs: scripted,
        interactive,
      })
        .then((res) => {
          setRun(model, {
            status: res.status === 'awaiting_input' ? 'awaiting_input' : 'completed',
            result: res,
          });
        })
        .catch((err) => {
          setRun(model, {
            status: 'error',
            result: null,
            error: err instanceof Error ? err.message : 'Dry run failed',
          });
        });
    }
  };

  const handleContinue = (model: string, answer: string) => {
    const run = runs[model];
    const runId = run?.result?.run_id;
    if (!runId) return;
    setRun(model, { ...run, status: 'running' });
    continueDryRun(projectId, runId, answer)
      .then((res) => {
        setRun(model, {
          status: res.status === 'awaiting_input' ? 'awaiting_input' : 'completed',
          result: res,
        });
      })
      .catch((err) => {
        setRun(model, {
          ...run,
          status: 'error',
          error: err instanceof Error ? err.message : 'Failed to continue the run',
        });
      });
  };

  const modelName = (id: string) => judgeModels.find((m) => m.id === id)?.name ?? id;
  const orderedRuns = selectedModels
    .map((m) => ({ model: m, run: runs[m] }))
    .filter((entry): entry is { model: string; run: PlaygroundRun } => entry.run != null);

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
        <FormField
          label="Models"
          hint={`Up to ${MAX_PARALLEL_MODELS} run in parallel, one transcript panel each`}
        >
          {usableModels.length === 0 ? (
            <p className="text-xs text-text-muted">
              No models available — configure API keys or manage the model registry above.
            </p>
          ) : (
            <div className="grid max-h-32 gap-1 overflow-y-auto sm:grid-cols-2">
              {usableModels.map((m) => (
                <label
                  key={m.id}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition ${
                    selectedModels.includes(m.id)
                      ? 'border-accent bg-accent/5 text-text-primary'
                      : 'border-border text-text-secondary hover:border-border-focus'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={selectedModels.includes(m.id)}
                    onChange={() => toggleModel(m.id)}
                  />
                  <span className="min-w-0 truncate">{m.name}</span>
                  <span className="ml-auto shrink-0 text-2xs text-text-muted">{m.provider}</span>
                </label>
              ))}
            </div>
          )}
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
        hint="One per line — every model consumes the same script in order before pausing for you (interactive) or handing off to the simulator"
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
            title="Pause each run whenever its model asks the user a question, and answer it yourself. Off = an LLM simulates the user."
          >
            <input
              type="checkbox"
              className="accent-accent"
              checked={interactive}
              onChange={(e) => setInteractive(e.target.checked)}
            />
            Interactive — I answer each model&apos;s questions myself
          </label>
          <span className="text-xs text-text-muted">
            Nothing is saved, no judge involved.
            {selectedSkill && (selectedSkill.files?.length ?? 0) > 0
              ? ` ${selectedSkill.files?.length} reference files available.`
              : ''}
          </span>
        </div>
        <Button onClick={handleRunAll} loading={anyRunning} disabled={!canRun}>
          {anyRunning
            ? 'Models working...'
            : `Run ${selectedModels.length > 1 ? `${selectedModels.length} models` : ''}`}
        </Button>
      </div>

      {orderedRuns.length > 0 && (
        <div
          className={`grid gap-3 border-t border-border pt-4 ${
            orderedRuns.length > 1 ? 'lg:grid-cols-2' : ''
          }`}
        >
          {orderedRuns.map(({ model, run }) => (
            <PlaygroundRunPanel
              key={model}
              model={model}
              modelName={modelName(model)}
              run={run}
              onContinue={handleContinue}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

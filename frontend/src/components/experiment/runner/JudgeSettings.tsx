import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { JudgeModel } from '../../../lib/api';
import { updateProjectJudgeDefaults } from '../../../lib/api';

/** Fallback judge models so dropdowns are usable before the API responds. */
export const FALLBACK_MODELS: JudgeModel[] = [
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', available: true },
  { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'openai', available: true },
  { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'openai', available: true },
  { id: 'gpt-4.1-mini', name: 'GPT-4.1 Mini', provider: 'openai', available: true },
  { id: 'claude-opus-4-5', name: 'Claude Opus 4.5', provider: 'anthropic', available: false },
  { id: 'claude-sonnet-4-5', name: 'Claude Sonnet 4.5', provider: 'anthropic', available: false },
  { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', provider: 'anthropic', available: false },
  { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash', provider: 'gemini', available: false },
  { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro', provider: 'gemini', available: false },
];

interface JudgeSettingsProps {
  projectId: number;
  availableModels: JudgeModel[];
  judgeModelSlots: string[];
  setJudgeModelSlots: Dispatch<SetStateAction<string[]>>;
  judgeTempSlots: number[];
  setJudgeTempSlots: Dispatch<SetStateAction<number[]>>;
}

/** Per-evaluator judge model + temperature slots, shown when a judge metric is selected. */
export default function JudgeSettings({
  projectId,
  availableModels,
  judgeModelSlots,
  setJudgeModelSlots,
  judgeTempSlots,
  setJudgeTempSlots,
}: JudgeSettingsProps) {
  const [savingDefaults, setSavingDefaults] = useState(false);

  return (
    <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-4 py-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-violet-400">LLM Judge Settings</p>
        <button
          type="button"
          onClick={async () => {
            setSavingDefaults(true);
            try {
              await updateProjectJudgeDefaults(projectId, judgeModelSlots);
            } finally {
              setSavingDefaults(false);
            }
          }}
          disabled={savingDefaults}
          className="text-2xs text-violet-400/70 hover:text-violet-400 transition disabled:opacity-40"
        >
          {savingDefaults ? 'Saving...' : 'Save as project default'}
        </button>
      </div>

      {/* Per-slot model selectors */}
      <div className="space-y-2">
        {/* Column headers */}
        <div className="flex items-center gap-2">
          <span className="w-20 shrink-0" />
          <span className="flex-1 text-2xs font-medium text-text-muted">Model</span>
          <span className="w-16 shrink-0 text-center text-2xs font-medium text-text-muted">
            Temp
          </span>
          {judgeModelSlots.length > 1 && <span className="w-5 shrink-0" />}
        </div>
        {judgeModelSlots.map((modelId, i) => {
          const model = availableModels.find((m) => m.id === modelId);
          const unavailable = model ? !model.available : false;
          return (
            <div key={i} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-2xs text-text-muted">Evaluator {i + 1}</span>
              <select
                value={modelId}
                onChange={(e) => {
                  const next = [...judgeModelSlots];
                  next[i] = e.target.value;
                  setJudgeModelSlots(next);
                }}
                className="flex-1 rounded-lg border border-border bg-input px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-violet-500/50"
              >
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {!m.available ? ' ⚠ No API key' : ''}
                  </option>
                ))}
              </select>
              {unavailable && (
                <span className="shrink-0 text-2xs text-yellow-500">⚠ key missing</span>
              )}
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={judgeTempSlots[i] ?? 0.5}
                onChange={(e) => {
                  const next = [...judgeTempSlots];
                  next[i] = Math.min(1, Math.max(0, parseFloat(e.target.value) || 0));
                  setJudgeTempSlots(next);
                }}
                className="w-16 shrink-0 rounded-lg border border-border bg-input px-2 py-1.5 text-center text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-violet-500/50"
                title="Temperature (0–1)"
              />
              {judgeModelSlots.length > 1 && (
                <button
                  type="button"
                  onClick={() => {
                    setJudgeModelSlots((prev) => prev.filter((_, idx) => idx !== i));
                    setJudgeTempSlots((prev) => prev.filter((_, idx) => idx !== i));
                  }}
                  className="shrink-0 rounded p-1 text-text-muted hover:text-red-400 transition"
                >
                  <svg
                    className="h-3 w-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Add evaluator button */}
      <button
        type="button"
        onClick={() => {
          setJudgeModelSlots((prev) => [...prev, 'gpt-4o-mini']);
          setJudgeTempSlots((prev) => [...prev, 0.5]);
        }}
        className="text-2xs text-violet-400 hover:text-violet-300 transition"
      >
        + Add Evaluator
      </button>

      <p className="text-2xs text-text-muted">
        Each evaluator uses a different model and temperature for diverse perspectives. Human
        annotations drive per-evaluator reliability scoring.
      </p>
    </div>
  );
}

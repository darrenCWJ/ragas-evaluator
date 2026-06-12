import { useState } from 'react';
import { addJudgeModel, deleteJudgeModel, setJudgeModelEnabled } from '../../api';
import type { JudgeModel } from '../../api';
import { Button, ErrorAlert, FormField, Select, TextInput } from '../ui';

interface ManageModelsProps {
  judgeModels: JudgeModel[];
  onChanged: () => void;
}

const PROVIDERS = ['openai', 'anthropic', 'gemini', 'gateway'] as const;

/**
 * Editable judge-model registry — hide outdated built-ins and register new
 * model ids without a code change (e.g. when a provider ships a new model).
 */
export default function ManageModels({ judgeModels, onChanged }: ManageModelsProps) {
  const [newId, setNewId] = useState('');
  const [newName, setNewName] = useState('');
  const [newProvider, setNewProvider] = useState<string>('openai');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Model registry update failed');
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = () =>
    run(async () => {
      await addJudgeModel({
        id: newId.trim(),
        name: newName.trim() || undefined,
        provider: newProvider,
      });
      setNewId('');
      setNewName('');
    });

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      <div className="space-y-1.5">
        {judgeModels.map((m) => (
          <div
            key={m.id}
            className={`flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm ${
              m.enabled === false ? 'opacity-50' : ''
            }`}
          >
            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                className="accent-accent"
                disabled={busy}
                checked={m.enabled !== false}
                onChange={(e) => run(() => setJudgeModelEnabled(m.id, e.target.checked))}
              />
              <span className="truncate text-text-primary">{m.name}</span>
              <span className="shrink-0 font-mono text-2xs text-text-muted">{m.id}</span>
            </label>
            <span className="shrink-0 text-2xs text-text-muted">
              {m.provider}
              {!m.available && ' — no API key'}
            </span>
            {m.custom && (
              <button
                type="button"
                className="shrink-0 text-2xs text-red-400 hover:underline disabled:opacity-50"
                disabled={busy}
                onClick={() => run(() => deleteJudgeModel(m.id))}
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {judgeModels.length === 0 && (
          <p className="text-xs text-text-muted">No models registered yet — add one below.</p>
        )}
      </div>

      <div className="grid items-end gap-2 sm:grid-cols-[2fr_2fr_1fr_auto]">
        <FormField label="Model id" hint="Exact API id, e.g. gpt-5.1 or claude-opus-4-8">
          <TextInput
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            placeholder="model-id"
          />
        </FormField>
        <FormField label="Display name (optional)">
          <TextInput
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Friendly name"
          />
        </FormField>
        <FormField label="Provider">
          <Select value={newProvider} onChange={(e) => setNewProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </FormField>
        <Button onClick={handleAdd} loading={busy} disabled={!newId.trim()}>
          Add model
        </Button>
      </div>
    </div>
  );
}

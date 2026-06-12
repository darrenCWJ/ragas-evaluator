import { useState, useEffect, useCallback } from 'react';
import {
  fetchTools,
  fetchBuiltinTools,
  createTool,
  deleteTool,
  type ToolDefinition,
  type BuiltinTool,
} from '../../lib/api';

interface Props {
  projectId: number;
  selectedToolIds: Set<number>;
  onChange: (ids: Set<number>) => void;
}

const MODE_HINTS: Record<string, string> = {
  mock: 'Fixture responses — define what the tool returns per argument pattern. Free.',
  simulated: 'An LLM invents a plausible response each call. Costs API calls.',
  builtin: 'Real implementation shipped with Tribunal (document search, file read, calculator).',
};

/** Tool picker + inline creator for agentic experiments. */
export default function AgentToolsPanel({ projectId, selectedToolIds, onChange }: Props) {
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [builtins, setBuiltins] = useState<BuiltinTool[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newMode, setNewMode] = useState<'mock' | 'simulated' | 'builtin'>('mock');
  const [newBuiltin, setNewBuiltin] = useState('search_documents');
  const [newParams, setNewParams] = useState('{\n  "type": "object",\n  "properties": {}\n}');
  const [newFixtures, setNewFixtures] = useState('{\n  "default": "OK"\n}');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    fetchTools(projectId)
      .then(setTools)
      .catch(() => setTools([]));
  }, [projectId]);

  useEffect(() => {
    load();
    fetchBuiltinTools()
      .then(setBuiltins)
      .catch(() => setBuiltins([]));
  }, [load]);

  const toggle = (id: number) => {
    const next = new Set(selectedToolIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onChange(next);
  };

  async function handleCreate() {
    setCreating(true);
    setError(null);
    try {
      let parameters: Record<string, unknown> | null = null;
      let fixtures: Record<string, unknown> | null = null;
      if (newMode !== 'builtin') {
        parameters = JSON.parse(newParams) as Record<string, unknown>;
      }
      if (newMode === 'mock') {
        fixtures = JSON.parse(newFixtures) as Record<string, unknown>;
      }
      const tool = await createTool(projectId, {
        name: newName.trim(),
        description: newDescription.trim(),
        mode: newMode,
        parameters,
        fixtures,
        builtin_name: newMode === 'builtin' ? newBuiltin : null,
      });
      setShowCreate(false);
      setNewName('');
      setNewDescription('');
      load();
      onChange(new Set([...selectedToolIds, tool.id]));
    } catch (err) {
      setError(
        err instanceof SyntaxError ? `Invalid JSON: ${err.message}` : (err as Error).message,
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteTool(projectId, id);
      const next = new Set(selectedToolIds);
      next.delete(id);
      onChange(next);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-text-secondary">
          Agent tools{' '}
          <span className="text-text-muted">
            — the model can call these during the experiment; every call is traced and scored
          </span>
        </span>
        <button
          type="button"
          onClick={() => setShowCreate((s) => !s)}
          className="rounded-md px-2 py-1 text-xs text-accent hover:bg-accent/10"
        >
          {showCreate ? 'Cancel' : '+ New tool'}
        </button>
      </div>

      {tools.length === 0 && !showCreate && (
        <p className="text-xs text-text-muted">
          No tools defined yet. Create one to turn this experiment into an agent test.
        </p>
      )}

      {tools.map((t) => (
        <label
          key={t.id}
          className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-elevated/50"
        >
          <input
            type="checkbox"
            checked={selectedToolIds.has(t.id)}
            onChange={() => toggle(t.id)}
            className="mt-0.5 accent-[var(--tw-color-accent,#818cf8)]"
          />
          <span className="min-w-0 flex-1">
            <span className="font-mono text-xs text-text-primary">{t.name}</span>
            <span className="ml-2 rounded-full bg-elevated px-1.5 py-0.5 text-2xs text-text-muted">
              {t.mode}
              {t.builtin_name ? `: ${t.builtin_name}` : ''}
            </span>
            <span className="block truncate text-2xs text-text-muted">{t.description}</span>
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              handleDelete(t.id);
            }}
            className="rounded px-1.5 text-xs text-red-400/70 hover:bg-red-400/10 hover:text-red-400"
            title="Delete tool"
          >
            ✕
          </button>
        </label>
      ))}

      {showCreate && (
        <div className="space-y-2 rounded-md border border-border/60 bg-elevated/30 p-3">
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="tool_name (identifier)"
              className="rounded-md border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
            <select
              value={newMode}
              onChange={(e) => setNewMode(e.target.value as 'mock' | 'simulated' | 'builtin')}
              className="rounded-md border border-border bg-input px-2 py-1.5 text-xs text-text-primary focus:outline-none"
            >
              <option value="mock">mock (fixtures)</option>
              <option value="simulated">simulated (LLM plays the tool)</option>
              <option value="builtin">builtin (real implementation)</option>
            </select>
          </div>
          <p className="text-2xs text-text-muted">{MODE_HINTS[newMode]}</p>
          <input
            type="text"
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            placeholder="What this tool does (shown to the model)"
            className="w-full rounded-md border border-border bg-input px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
          {newMode === 'builtin' ? (
            <select
              value={newBuiltin}
              onChange={(e) => setNewBuiltin(e.target.value)}
              className="w-full rounded-md border border-border bg-input px-2 py-1.5 text-xs text-text-primary focus:outline-none"
            >
              {builtins.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name} — {b.description.slice(0, 60)}
                </option>
              ))}
            </select>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              <div>
                <span className="text-2xs text-text-muted">Arguments JSON schema</span>
                <textarea
                  value={newParams}
                  onChange={(e) => setNewParams(e.target.value)}
                  rows={4}
                  className="w-full rounded-md border border-border bg-input px-2 py-1.5 font-mono text-2xs text-text-primary focus:border-border-focus focus:outline-none"
                />
              </div>
              {newMode === 'mock' && (
                <div>
                  <span className="text-2xs text-text-muted">
                    Fixtures: {`{"default": ..., "cases": [{"when": {...}, "response": ...}]}`}
                  </span>
                  <textarea
                    value={newFixtures}
                    onChange={(e) => setNewFixtures(e.target.value)}
                    rows={4}
                    className="w-full rounded-md border border-border bg-input px-2 py-1.5 font-mono text-2xs text-text-primary focus:border-border-focus focus:outline-none"
                  />
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !newName.trim() || !newDescription.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {creating ? 'Creating…' : 'Create tool'}
          </button>
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

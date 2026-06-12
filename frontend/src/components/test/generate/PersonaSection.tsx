import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { KnowledgeGraphInfo, SavedPersona } from '../../../lib/api';
import {
  ApiError,
  deletePersona,
  generatePersonas,
  savePersonasBulk,
  updatePersona,
} from '../../../lib/api';

export interface PersonaDraft {
  name: string;
  role_description: string;
  question_style: string;
}

interface PersonaSectionProps {
  projectId: number;
  generating: boolean;
  usePersonas: boolean;
  setUsePersonas: (value: boolean) => void;
  numPersonas: string;
  setNumPersonas: (value: string) => void;
  personasError: string | null;
  validatePersonas: (value: string) => boolean;
  customPersonas: PersonaDraft[];
  setCustomPersonas: Dispatch<SetStateAction<PersonaDraft[]>>;
  savedPersonas: SavedPersona[];
  setSavedPersonas: Dispatch<SetStateAction<SavedPersona[]>>;
  loadSavedPersonas: () => Promise<void>;
  chunkConfigId: number | '';
  kgInfo: KnowledgeGraphInfo | null;
  chunksRequired: boolean;
  useKgAsSource: boolean;
  onError: (message: string | null) => void;
}

/**
 * Persona controls for test set generation: the "Use Personas" toggle,
 * persona count, custom persona editor, auto-generation, and the
 * saved-personas dropdown (load / edit / delete).
 *
 * Rendered as grid cells inside the parent's two-column grid.
 */
export default function PersonaSection({
  projectId,
  generating,
  usePersonas,
  setUsePersonas,
  numPersonas,
  setNumPersonas,
  personasError,
  validatePersonas,
  customPersonas,
  setCustomPersonas,
  savedPersonas,
  setSavedPersonas,
  loadSavedPersonas,
  chunkConfigId,
  kgInfo,
  chunksRequired,
  useKgAsSource,
  onError,
}: PersonaSectionProps) {
  const [generatingPersonas, setGeneratingPersonas] = useState(false);
  const [personaGenMode, setPersonaGenMode] = useState<'fast' | 'full'>('fast');
  const [savingPersonas, setSavingPersonas] = useState(false);
  const [showSavedPersonas, setShowSavedPersonas] = useState(false);
  const [editingPersonaId, setEditingPersonaId] = useState<number | null>(null);
  const [editingPersona, setEditingPersona] = useState<PersonaDraft>({
    name: '',
    role_description: '',
    question_style: '',
  });

  const handleAutoGeneratePersonas = async () => {
    const effectiveChunkConfigId =
      chunkConfigId !== '' ? (chunkConfigId as number) : kgInfo?.chunk_config_id;
    if (!effectiveChunkConfigId || !validatePersonas(numPersonas)) return;
    setGeneratingPersonas(true);
    onError(null);
    try {
      const personas = await generatePersonas(
        projectId,
        effectiveChunkConfigId,
        Number(numPersonas),
        personaGenMode,
      );
      setCustomPersonas(personas);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : 'Failed to auto-generate personas');
    } finally {
      setGeneratingPersonas(false);
    }
  };

  const handleSavePersonas = async () => {
    const valid = customPersonas.filter((p) => p.name.trim() && p.role_description.trim());
    if (valid.length === 0) return;
    setSavingPersonas(true);
    try {
      await savePersonasBulk(projectId, valid);
      await loadSavedPersonas();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : 'Failed to save personas');
    } finally {
      setSavingPersonas(false);
    }
  };

  const handleLoadSavedPersona = (p: SavedPersona) => {
    const exists = customPersonas.some(
      (c) => c.name === p.name && c.role_description === p.role_description,
    );
    if (!exists) {
      setCustomPersonas((prev) => [
        ...prev,
        {
          name: p.name,
          role_description: p.role_description,
          question_style: p.question_style,
        },
      ]);
    }
    setShowSavedPersonas(false);
  };

  const handleDeleteSavedPersona = async (personaId: number) => {
    try {
      await deletePersona(projectId, personaId);
      setSavedPersonas((prev) => prev.filter((p) => p.id !== personaId));
    } catch {
      // silent
    }
  };

  const handleStartEditPersona = (p: SavedPersona) => {
    setEditingPersonaId(p.id);
    setEditingPersona({
      name: p.name,
      role_description: p.role_description,
      question_style: p.question_style,
    });
  };

  const handleSaveEditPersona = async () => {
    if (editingPersonaId === null) return;
    try {
      await updatePersona(projectId, editingPersonaId, editingPersona);
      setSavedPersonas((prev) =>
        prev.map((p) => (p.id === editingPersonaId ? { ...p, ...editingPersona } : p)),
      );
      setEditingPersonaId(null);
    } catch {
      // silent
    }
  };

  return (
    <>
      {/* Use personas toggle */}
      <div className="flex items-end gap-3 pb-1">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={usePersonas}
            onChange={(e) => setUsePersonas(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
            disabled={generating}
          />
          Use Personas
        </label>
      </div>

      {/* Num personas */}
      {usePersonas && (
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Number of Personas
          </label>
          <input
            type="number"
            min={1}
            max={10}
            value={numPersonas}
            onChange={(e) => {
              setNumPersonas(e.target.value);
              validatePersonas(e.target.value);
            }}
            className={`w-full rounded-lg border px-3 py-2 text-sm text-text-primary focus:outline-none ${
              personasError
                ? 'border-red-500 focus:border-red-500'
                : 'border-border bg-input focus:border-accent'
            }`}
            disabled={generating}
          />
          {personasError && <p className="mt-1 text-xs text-red-400">{personasError}</p>}
        </div>
      )}

      {/* Custom personas editor */}
      {usePersonas && (
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Custom Personas{' '}
            <span className="font-normal text-text-muted">
              (optional — leave empty for auto-generated)
            </span>
          </label>

          {generatingPersonas && (
            <div className="mb-2 space-y-3">
              {Array.from({ length: Number(numPersonas) || 3 }).map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-lg border border-border bg-input/50 p-2.5 space-y-1.5"
                >
                  <div className="flex items-start gap-2">
                    <div className="w-1/3 h-8 rounded-lg bg-border/50" />
                    <div className="flex-1 h-8 rounded-lg bg-border/50" />
                    <div className="shrink-0 h-8 w-8 rounded-md bg-border/50" />
                  </div>
                  <div className="w-full h-8 rounded-lg bg-border/50" />
                </div>
              ))}
              <p className="text-xs text-accent">
                {personaGenMode === 'full'
                  ? 'Building knowledge graph and generating personas (this may take a few minutes)...'
                  : 'Analyzing documents and generating personas...'}
              </p>
            </div>
          )}

          {!generatingPersonas && customPersonas.length > 0 && (
            <div className="mb-2 space-y-3">
              {customPersonas.map((p, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-border bg-input/50 p-2.5 space-y-1.5"
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="text"
                      value={p.name}
                      onChange={(e) => {
                        setCustomPersonas((prev) =>
                          prev.map((item, j) =>
                            j === i ? { ...item, name: e.target.value } : item,
                          ),
                        );
                      }}
                      placeholder="Name"
                      className="w-1/3 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      disabled={generating}
                    />
                    <input
                      type="text"
                      value={p.role_description}
                      onChange={(e) => {
                        setCustomPersonas((prev) =>
                          prev.map((item, j) =>
                            j === i ? { ...item, role_description: e.target.value } : item,
                          ),
                        );
                      }}
                      placeholder="Role description"
                      className="flex-1 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      disabled={generating}
                    />
                    <button
                      type="button"
                      onClick={() => setCustomPersonas(customPersonas.filter((_, j) => j !== i))}
                      disabled={generating}
                      className="shrink-0 rounded-md border border-border p-1.5 text-text-muted transition hover:border-red-500/40 hover:text-red-400 disabled:opacity-40"
                      title="Remove persona"
                    >
                      <svg
                        className="h-3.5 w-3.5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18 18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </div>
                  <input
                    type="text"
                    value={p.question_style}
                    onChange={(e) => {
                      setCustomPersonas((prev) =>
                        prev.map((item, j) =>
                          j === i ? { ...item, question_style: e.target.value } : item,
                        ),
                      );
                    }}
                    placeholder="Question style (e.g. formal technical queries, brief keyword searches, scenario-based questions)"
                    className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                    disabled={generating}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Generation mode toggle */}
          <div className="mb-2 flex items-center gap-3">
            <span className="text-xs text-text-muted">Generation mode:</span>
            <button
              type="button"
              onClick={() => setPersonaGenMode('fast')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                personaGenMode === 'fast'
                  ? 'bg-accent text-white'
                  : 'border border-border text-text-muted hover:border-accent hover:text-accent'
              }`}
              disabled={generating || generatingPersonas}
            >
              Fast
            </button>
            <button
              type="button"
              onClick={() => setPersonaGenMode('full')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                personaGenMode === 'full'
                  ? 'bg-accent text-white'
                  : 'border border-border text-text-muted hover:border-accent hover:text-accent'
              }`}
              disabled={generating || generatingPersonas}
            >
              Full (Knowledge Graph)
            </button>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                setCustomPersonas([
                  ...customPersonas,
                  { name: '', role_description: '', question_style: '' },
                ])
              }
              disabled={
                generating ||
                generatingPersonas ||
                customPersonas.length >= (Number(numPersonas) || 1)
              }
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              + Add Persona
              {customPersonas.length >= (Number(numPersonas) || 1) && (
                <span className="ml-1 text-text-muted">(max {numPersonas})</span>
              )}
            </button>
            <button
              type="button"
              onClick={handleAutoGeneratePersonas}
              disabled={
                generating ||
                generatingPersonas ||
                (chunksRequired && chunkConfigId === '' && !kgInfo?.chunk_config_id) ||
                (useKgAsSource && !(kgInfo?.exists && kgInfo.is_complete))
              }
              className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {generatingPersonas
                ? personaGenMode === 'full'
                  ? 'Building knowledge graph…'
                  : 'Generating…'
                : `Auto Generate (${personaGenMode === 'full' ? 'Full' : 'Fast'})`}
            </button>
            {customPersonas.length > 0 && (
              <button
                type="button"
                onClick={handleSavePersonas}
                disabled={savingPersonas || generating}
                className="rounded-md border border-green-500/40 bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-400 transition hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {savingPersonas ? 'Saving…' : 'Save Personas'}
              </button>
            )}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSavedPersonas(!showSavedPersonas)}
                disabled={generating || generatingPersonas || savedPersonas.length === 0}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                Load Saved{savedPersonas.length > 0 && ` (${savedPersonas.length})`}
              </button>
              {showSavedPersonas && savedPersonas.length > 0 && (
                <div className="absolute left-0 top-full z-10 mt-1 max-h-80 w-96 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg">
                  {savedPersonas.map((p) => (
                    <div key={p.id} className="border-b border-border/50 px-3 py-2 last:border-b-0">
                      {editingPersonaId === p.id ? (
                        <div className="space-y-1.5">
                          <input
                            type="text"
                            value={editingPersona.name}
                            onChange={(e) =>
                              setEditingPersona({ ...editingPersona, name: e.target.value })
                            }
                            className="w-full rounded border border-border bg-input px-2 py-1 text-sm text-text-primary"
                            placeholder="Name"
                          />
                          <textarea
                            value={editingPersona.role_description}
                            onChange={(e) =>
                              setEditingPersona({
                                ...editingPersona,
                                role_description: e.target.value,
                              })
                            }
                            className="w-full rounded border border-border bg-input px-2 py-1 text-xs text-text-primary"
                            placeholder="Role description"
                            rows={2}
                          />
                          <input
                            type="text"
                            value={editingPersona.question_style}
                            onChange={(e) =>
                              setEditingPersona({
                                ...editingPersona,
                                question_style: e.target.value,
                              })
                            }
                            className="w-full rounded border border-border bg-input px-2 py-1 text-xs text-text-primary"
                            placeholder="Question style"
                          />
                          <div className="flex gap-1.5 pt-0.5">
                            <button
                              type="button"
                              onClick={handleSaveEditPersona}
                              className="rounded bg-accent px-2 py-0.5 text-xs font-medium text-deep transition hover:bg-accent/80"
                            >
                              Save
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingPersonaId(null)}
                              className="rounded px-2 py-0.5 text-xs text-text-muted transition hover:text-text-primary"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => handleLoadSavedPersona(p)}
                            className="flex-1 text-left"
                          >
                            <p className="text-sm font-medium text-text-primary">{p.name}</p>
                            <p className="truncate text-xs text-text-muted">{p.role_description}</p>
                            {p.question_style && (
                              <p className="truncate text-xs text-accent/70">{p.question_style}</p>
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleStartEditPersona(p)}
                            className="shrink-0 rounded p-1 text-text-muted transition hover:text-accent"
                            title="Edit persona"
                          >
                            <svg
                              className="h-3.5 w-3.5"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={2}
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Z"
                              />
                            </svg>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteSavedPersona(p.id)}
                            className="shrink-0 rounded p-1 text-text-muted transition hover:text-red-400"
                            title="Delete saved persona"
                          >
                            <svg
                              className="h-3.5 w-3.5"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={2}
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M6 18 18 6M6 6l12 12"
                              />
                            </svg>
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {personaGenMode === 'full' && (
            <p className="mt-1 text-xs text-text-muted">
              Full mode builds a knowledge graph from your documents for more accurate personas.
              This takes longer.
            </p>
          )}
        </div>
      )}
    </>
  );
}

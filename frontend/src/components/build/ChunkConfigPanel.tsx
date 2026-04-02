import { useState, useEffect, useCallback } from "react";
import type { ChunkConfig, Document as Doc } from "../../lib/api";
import {
  fetchChunkConfigs,
  createChunkConfig,
  deleteChunkConfig,
} from "../../lib/api";
import ChunkPreview from "./ChunkPreview";
import ChunkGenerate from "./ChunkGenerate";

const METHODS = ["recursive", "parent_child", "semantic", "fixed_overlap"] as const;
type Method = (typeof METHODS)[number];

const METHOD_DEFAULTS: Record<Method, Record<string, number>> = {
  recursive: { chunk_size: 512, chunk_overlap: 50 },
  parent_child: { parent_chunk_size: 1024, child_chunk_size: 256 },
  semantic: { threshold: 0.5 },
  fixed_overlap: { chunk_size: 500, overlap: 50 },
};

const METHOD_LABELS: Record<string, string> = {
  chunk_size: "Chunk Size",
  chunk_overlap: "Chunk Overlap",
  parent_chunk_size: "Parent Chunk Size",
  child_chunk_size: "Child Chunk Size",
  threshold: "Threshold",
  overlap: "Overlap",
};

const PARAM_HELP: Record<string, string> = {
  chunk_size: "Target size in characters for each chunk (typical: 500-2000)",
  chunk_overlap: "Number of overlapping characters between chunks (typical: 50-200)",
  parent_chunk_size: "Target size in characters for each chunk (typical: 500-2000)",
  child_chunk_size: "Target size in characters for each chunk (typical: 500-2000)",
  threshold: "Similarity threshold for semantic splitting (0.0-1.0, typical: 0.5)",
  overlap: "Number of overlapping characters between chunks (typical: 50-200)",
};

interface Props {
  projectId: number;
  documents: Doc[];
}

function validateParams(
  method: Method,
  params: Record<string, number>,
): string | null {
  if (method === "recursive") {
    if (params.chunk_size! <= 0) return "Chunk size must be > 0";
    if (params.chunk_overlap! < 0) return "Overlap must be >= 0";
    if (params.chunk_overlap! >= params.chunk_size!)
      return "Overlap must be less than chunk size";
  } else if (method === "parent_child") {
    if (params.parent_chunk_size! <= 0) return "Parent size must be > 0";
    if (params.child_chunk_size! <= 0) return "Child size must be > 0";
    if (params.child_chunk_size! >= params.parent_chunk_size!)
      return "Child size must be less than parent size";
  } else if (method === "semantic") {
    if (params.threshold! < 0 || params.threshold! > 1)
      return "Threshold must be between 0 and 1";
  } else if (method === "fixed_overlap") {
    if (params.chunk_size! <= 0) return "Chunk size must be > 0";
    if (params.overlap! < 0) return "Overlap must be >= 0";
    if (params.overlap! >= params.chunk_size!)
      return "Overlap must be less than chunk size";
  }
  return null;
}

export default function ChunkConfigPanel({ projectId, documents }: Props) {
  const [configs, setConfigs] = useState<ChunkConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [method, setMethod] = useState<Method>("recursive");
  const [params, setParams] = useState<Record<string, number>>(
    () => ({ ...METHOD_DEFAULTS.recursive }),
  );
  const [step2Enabled, setStep2Enabled] = useState(false);
  const [step2Method, setStep2Method] = useState<Method>("semantic");
  const [step2Params, setStep2Params] = useState<Record<string, number>>(
    () => ({ ...METHOD_DEFAULTS.semantic }),
  );
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Preview / Generate state
  const [previewConfigId, setPreviewConfigId] = useState<number | null>(null);
  const [generateConfigId, setGenerateConfigId] = useState<number | null>(null);

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchChunkConfigs(projectId);
      setConfigs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load configs");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // Reset params when method changes
  useEffect(() => {
    setParams({ ...METHOD_DEFAULTS[method] });
  }, [method]);

  useEffect(() => {
    setStep2Params({ ...METHOD_DEFAULTS[step2Method] });
  }, [step2Method]);

  function updateParam(key: string, value: string) {
    setParams((prev) => ({ ...prev, [key]: parseFloat(value) || 0 }));
  }

  function updateStep2Param(key: string, value: string) {
    setStep2Params((prev) => ({ ...prev, [key]: parseFloat(value) || 0 }));
  }

  const validationError = validateParams(method, params);
  const step2ValidationError = step2Enabled
    ? validateParams(step2Method, step2Params)
    : null;
  const canSave =
    name.trim().length > 0 && !validationError && !step2ValidationError;

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setFormError(null);
    try {
      await createChunkConfig(projectId, {
        name: name.trim(),
        method,
        params,
        step2_method: step2Enabled ? step2Method : null,
        step2_params: step2Enabled ? step2Params : null,
      });
      setName("");
      setMethod("recursive");
      setParams({ ...METHOD_DEFAULTS.recursive });
      setStep2Enabled(false);
      loadConfigs();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(configId: number) {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteChunkConfig(projectId, configId);
      setConfirmDeleteId(null);
      loadConfigs();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Delete failed");
      setConfirmDeleteId(null);
    } finally {
      setDeleting(false);
    }
  }

  function renderParamInputs(
    p: Record<string, number>,
    m: Method,
    onChange: (key: string, val: string) => void,
  ) {
    return (
      <div className="mt-3 grid grid-cols-2 gap-3">
        {Object.entries(METHOD_DEFAULTS[m]).map(([key]) => (
          <label key={key} className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              {METHOD_LABELS[key] ?? key}
            </span>
            {PARAM_HELP[key] && (
              <p className="mt-0.5 text-xs text-text-muted">{PARAM_HELP[key]}</p>
            )}
            {key === "threshold" ? (
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={p[key] ?? 0.5}
                  onChange={(e) => onChange(key, e.target.value)}
                  className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-accent"
                />
                <span className="w-8 text-right text-xs font-mono text-text-primary">
                  {(p[key] ?? 0.5).toFixed(2)}
                </span>
              </div>
            ) : (
              <input
                type="number"
                value={p[key] ?? 0}
                onChange={(e) => onChange(key, e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              />
            )}
          </label>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* New Config Form */}
      <div className="rounded-xl border border-border bg-card/60 p-5">
        <h4 className="mb-4 text-sm font-semibold text-text-primary">
          New Chunk Config
        </h4>

        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Name</span>
          <p className="mt-0.5 text-xs text-text-muted">A descriptive name for this chunking configuration</p>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. recursive-512"
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </label>

        <label className="mt-3 block">
          <span className="mb-1 block text-xs text-text-secondary">Method</span>
          <p className="mt-0.5 text-xs text-text-muted">recursive: splits by separators recursively | parent_child: creates parent-child chunk pairs | semantic: splits by semantic similarity | fixed_overlap: fixed-size chunks with overlap</p>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as Method)}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
          >
            {METHODS.map((m) => (
              <option key={m} value={m}>
                {m.replace("_", " ")}
              </option>
            ))}
          </select>
        </label>

        {renderParamInputs(params, method, updateParam)}

        {validationError && (
          <p className="mt-2 text-xs text-score-low">{validationError}</p>
        )}

        {/* 2nd pass toggle */}
        <div className="mt-4 border-t border-border pt-4">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={step2Enabled}
              onChange={(e) => setStep2Enabled(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
            />
            <span className="text-xs text-text-secondary">
              Enable 2nd pass chunking
            </span>
          </label>

          {step2Enabled && (
            <div className="mt-3">
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  2nd Pass Method
                </span>
                <p className="mt-0.5 text-xs text-text-muted">Optional second pass to further refine chunks from the first pass</p>
                <select
                  value={step2Method}
                  onChange={(e) => setStep2Method(e.target.value as Method)}
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                >
                  {METHODS.map((m) => (
                    <option key={m} value={m}>
                      {m.replace("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
              {renderParamInputs(step2Params, step2Method, updateStep2Param)}
              {step2ValidationError && (
                <p className="mt-2 text-xs text-score-low">
                  {step2ValidationError}
                </p>
              )}
            </div>
          )}
        </div>

        {formError && (
          <p className="mt-3 text-xs text-score-low">{formError}</p>
        )}

        <button
          onClick={handleSave}
          disabled={!canSave || saving}
          className="mt-4 w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? "Saving..." : "Save Config"}
        </button>
      </div>

      {/* Existing configs list */}
      <div>
        <h4 className="mb-3 text-sm font-semibold text-text-primary">
          Saved Configs
        </h4>

        {loading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-text-muted">
            <svg
              className="h-4 w-4 animate-spin"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Loading configs...
          </div>
        ) : error ? (
          <div className="flex items-center justify-between rounded-lg bg-score-low/10 px-4 py-3 text-sm text-score-low">
            <span>{error}</span>
            <button
              onClick={loadConfigs}
              className="ml-3 rounded-md bg-score-low/20 px-3 py-1 text-xs font-medium hover:bg-score-low/30"
            >
              Retry
            </button>
          </div>
        ) : configs.length === 0 ? (
          <p className="py-4 text-center text-sm text-text-muted">
            No configs yet. Create one above.
          </p>
        ) : (
          <>
          {deleteError && (
            <div className="mb-2 flex items-center justify-between rounded-lg bg-score-low/10 px-4 py-2 text-xs text-score-low">
              <span>{deleteError}</span>
              <button
                onClick={() => setDeleteError(null)}
                className="ml-2 rounded bg-score-low/20 px-2 py-0.5 text-xs hover:bg-score-low/30"
              >
                Dismiss
              </button>
            </div>
          )}
          <ul className="space-y-2">
            {configs.map((cfg) => (
              <li
                key={cfg.id}
                className="rounded-lg bg-card px-4 py-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="truncate text-sm font-medium text-text-primary">
                      {cfg.name}
                    </span>
                    <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent">
                      {cfg.method.replace("_", " ")}
                    </span>
                    {cfg.step2_method && (
                      <span className="shrink-0 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text-muted">
                        + {cfg.step2_method.replace("_", " ")}
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-text-muted">
                      {new Date(cfg.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() =>
                        setPreviewConfigId(
                          previewConfigId === cfg.id ? null : cfg.id,
                        )
                      }
                      className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
                    >
                      Preview
                    </button>
                    <button
                      onClick={() =>
                        setGenerateConfigId(
                          generateConfigId === cfg.id ? null : cfg.id,
                        )
                      }
                      className="rounded px-2 py-1 text-xs text-score-high hover:bg-score-high/10"
                    >
                      Generate
                    </button>
                    {confirmDeleteId === cfg.id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(cfg.id)}
                          disabled={deleting}
                          className="rounded bg-score-low/20 px-2 py-1 text-xs text-score-low hover:bg-score-low/30 disabled:opacity-50"
                        >
                          {deleting ? "..." : "Yes"}
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded bg-elevated px-2 py-1 text-xs text-text-secondary hover:bg-border"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(cfg.id)}
                        className="rounded p-1 text-text-muted hover:bg-elevated hover:text-score-low"
                        title="Delete config"
                      >
                        <svg
                          className="h-3.5 w-3.5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={1.5}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M6 18L18 6M6 6l12 12"
                          />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {/* Inline preview */}
                {previewConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3">
                    <ChunkPreview
                      projectId={projectId}
                      configId={cfg.id}
                      documents={documents}
                    />
                  </div>
                )}

                {/* Inline generate */}
                {generateConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3">
                    <ChunkGenerate
                      projectId={projectId}
                      configId={cfg.id}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
          </>
        )}
      </div>
    </div>
  );
}

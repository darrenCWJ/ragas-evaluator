import { useState, useEffect, useCallback } from "react";
import type { ChunkConfig, Document as Doc } from "../../lib/api";
import {
  fetchChunkConfigs,
  createChunkConfig,
  deleteChunkConfig,
} from "../../lib/api";
import ChunkPreview from "./ChunkPreview";
import ChunkGenerate from "./ChunkGenerate";

const METHODS = ["recursive", "parent_child", "semantic", "fixed_overlap", "markdown", "token"] as const;
type Method = (typeof METHODS)[number];

const METHOD_DEFAULTS: Record<Method, Record<string, number>> = {
  recursive: { chunk_size: 512, chunk_overlap: 50 },
  parent_child: { parent_chunk_size: 1024, child_chunk_size: 256 },
  semantic: { max_chunk_size: 1000, breakpoint_threshold: 0.5 },
  fixed_overlap: { chunk_size: 500, overlap: 50 },
  markdown: { chunk_size: 1000, chunk_overlap: 100 },
  token: { chunk_size: 256, chunk_overlap: 30 },
};

const METHOD_LABELS: Record<string, string> = {
  chunk_size: "Chunk Size",
  chunk_overlap: "Chunk Overlap",
  parent_chunk_size: "Parent Chunk Size",
  child_chunk_size: "Child Chunk Size",
  max_chunk_size: "Max Chunk Size",
  breakpoint_threshold: "Breakpoint Threshold",
  overlap: "Overlap",
};

const PARAM_HELP: Record<Method, Record<string, string>> = {
  recursive: {
    chunk_size: "Size in characters (default: 512). Smaller chunks = more precise retrieval, larger = more context per result.",
    chunk_overlap: "Overlapping characters between chunks (default: 50). Helps preserve context at chunk boundaries.",
  },
  parent_child: {
    parent_chunk_size: "Size in characters for parent chunks (default: 1024). These are split further into child chunks.",
    child_chunk_size: "Size in characters for child chunks (default: 256). Smaller children = more granular retrieval.",
  },
  semantic: {
    max_chunk_size: "Maximum chunk size in characters (default: 1000). Chunks split at structural boundaries (headings, paragraphs) within this limit.",
    breakpoint_threshold: "Sensitivity for structural boundary detection (0.0\u20131.0, default: 0.5).",
  },
  fixed_overlap: {
    chunk_size: "Fixed window size in characters (default: 500). Every chunk is exactly this size (except possibly the last).",
    overlap: "Overlapping characters between chunks (default: 50). Helps preserve context at chunk boundaries.",
  },
  markdown: {
    chunk_size: "Size in characters (default: 1000). Splits at headings and code blocks before falling back to paragraphs.",
    chunk_overlap: "Overlapping characters between chunks (default: 100). Helps preserve context at chunk boundaries.",
  },
  token: {
    chunk_size: "Size in tokens (default: 256). Aligned to embedding model token limits. 1 token \u2248 4 characters in English.",
    chunk_overlap: "Overlapping tokens between chunks (default: 30). Helps preserve context at chunk boundaries.",
  },
};

interface Props {
  projectId: number;
  documents: Doc[];
  onConfigsChanged?: () => void;
}

function validateParams(
  method: Method,
  params: Record<string, number>,
): string | null {
  if (method === "recursive" || method === "markdown" || method === "token") {
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
    if (params.max_chunk_size! <= 0) return "Max chunk size must be > 0";
    if (params.breakpoint_threshold! < 0 || params.breakpoint_threshold! > 1)
      return "Threshold must be between 0 and 1";
  } else if (method === "fixed_overlap") {
    if (params.chunk_size! <= 0) return "Chunk size must be > 0";
    if (params.overlap! < 0) return "Overlap must be >= 0";
    if (params.overlap! >= params.chunk_size!)
      return "Overlap must be less than chunk size";
  }
  return null;
}

export default function ChunkConfigPanel({ projectId, documents, onConfigsChanged }: Props) {
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
  const [filterEnabled, setFilterEnabled] = useState(false);
  const [filterParams, setFilterParams] = useState({
    min_char_length: 20,
    min_word_count: 3,
    max_whitespace_ratio: 0.8,
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Preview / Generate / Expand state
  const [previewConfigId, setPreviewConfigId] = useState<number | null>(null);
  const [generateConfigId, setGenerateConfigId] = useState<number | null>(null);
  const [expandedConfigId, setExpandedConfigId] = useState<number | null>(null);

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

  // Warn when step 2 chunk size >= step 1 output size (step 2 would be a no-op)
  const step2SizeWarning = (() => {
    if (!step2Enabled) return null;

    const getEffectiveSize = (m: Method, p: Record<string, number>): { size: number; unit: "chars" | "tokens" } => {
      if (m === "token") return { size: p.chunk_size ?? 256, unit: "tokens" };
      if (m === "parent_child") return { size: p.child_chunk_size ?? 256, unit: "chars" };
      if (m === "semantic") return { size: p.max_chunk_size ?? 1000, unit: "chars" };
      return { size: p.chunk_size ?? 500, unit: "chars" };
    };

    const step1 = getEffectiveSize(method, params);
    const step2 = getEffectiveSize(step2Method, step2Params);

    if (step2.size >= step1.size) {
      const msg = `2nd pass chunk size (${step2.size}) is >= 1st pass output size (${step1.size}). The 2nd pass will have no effect.`;
      return { msg, sameUnit: step1.unit === step2.unit };
    }
    return null;
  })();

  const canSave =
    name.trim().length > 0 &&
    !validationError &&
    !step2ValidationError &&
    !(step2SizeWarning?.sameUnit);

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
        filter_params: filterEnabled ? filterParams : null,
      });
      setName("");
      setMethod("recursive");
      setParams({ ...METHOD_DEFAULTS.recursive });
      setStep2Enabled(false);
      setFilterEnabled(false);
      setFilterParams({ min_char_length: 20, min_word_count: 3, max_whitespace_ratio: 0.8 });
      loadConfigs();
      onConfigsChanged?.();
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
      onConfigsChanged?.();
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
            {PARAM_HELP[m]?.[key] && (
              <p className="mt-0.5 text-xs text-text-muted">{PARAM_HELP[m][key]}</p>
            )}
            {(key === "threshold" || key === "breakpoint_threshold") ? (
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
          <p className="mt-0.5 text-xs text-text-muted">recursive: splits by separators recursively | parent_child: creates parent-child chunk pairs | semantic: structural boundary splitting | fixed_overlap: fixed-size character windows | markdown: heading/code-block aware | token: splits by token count (aligned to embedding models)</p>
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
              {!step2ValidationError && step2SizeWarning && (
                <p className={`mt-2 text-xs ${step2SizeWarning.sameUnit ? "text-score-low" : "text-yellow-500"}`}>
                  {step2SizeWarning.msg}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Chunk quality filters */}
        <div className="mt-4 border-t border-border pt-4">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={filterEnabled}
              onChange={(e) => setFilterEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
            />
            <span className="text-xs text-text-secondary">
              Enable chunk quality filters
            </span>
          </label>
          <p className="mt-1 text-xs text-text-muted">
            Remove low-quality chunks (too short, mostly whitespace, etc.)
          </p>

          {filterEnabled && (
            <div className="mt-3 grid grid-cols-3 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  Min Characters
                </span>
                <p className="mt-0.5 text-xs text-text-muted">
                  Drop chunks shorter than this (0 = disabled)
                </p>
                <input
                  type="number"
                  min="0"
                  value={filterParams.min_char_length}
                  onChange={(e) =>
                    setFilterParams((prev) => ({
                      ...prev,
                      min_char_length: parseInt(e.target.value) || 0,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  Min Words
                </span>
                <p className="mt-0.5 text-xs text-text-muted">
                  Drop chunks with fewer words (0 = disabled)
                </p>
                <input
                  type="number"
                  min="0"
                  value={filterParams.min_word_count}
                  onChange={(e) =>
                    setFilterParams((prev) => ({
                      ...prev,
                      min_word_count: parseInt(e.target.value) || 0,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  Max Whitespace Ratio
                </span>
                <p className="mt-0.5 text-xs text-text-muted">
                  Drop chunks exceeding this non-alphanumeric ratio (1.0 = disabled)
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                    value={filterParams.max_whitespace_ratio}
                    onChange={(e) =>
                      setFilterParams((prev) => ({
                        ...prev,
                        max_whitespace_ratio: parseFloat(e.target.value),
                      }))
                    }
                    className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-accent"
                  />
                  <span className="w-8 text-right font-mono text-xs text-text-primary">
                    {filterParams.max_whitespace_ratio.toFixed(2)}
                  </span>
                </div>
              </label>
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
                    <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider text-accent">
                      {cfg.method.replace("_", " ")}
                    </span>
                    {cfg.step2_method && (
                      <span className="shrink-0 rounded bg-accent/10 px-1.5 py-0.5 text-2xs uppercase tracking-wider text-text-muted">
                        + {cfg.step2_method.replace("_", " ")}
                      </span>
                    )}
                    {cfg.filter_params && (
                      <span className="shrink-0 rounded bg-yellow-500/15 px-1.5 py-0.5 text-2xs uppercase tracking-wider text-yellow-600">
                        filtered
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-text-muted">
                      {new Date(cfg.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() =>
                        setExpandedConfigId(
                          expandedConfigId === cfg.id ? null : cfg.id,
                        )
                      }
                      className="rounded p-1 text-text-muted hover:bg-elevated hover:text-text-primary"
                      title="Toggle config details"
                    >
                      <svg
                        className={`h-3.5 w-3.5 transition-transform ${expandedConfigId === cfg.id ? "rotate-90" : ""}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
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

                {/* Expanded config details */}
                {expandedConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3 space-y-1 text-xs text-text-muted">
                    <p>
                      <span className="text-text-secondary">Method:</span>{" "}
                      {cfg.method.replace("_", " ")}
                    </p>
                    <p>
                      <span className="text-text-secondary">Params:</span>{" "}
                      {Object.entries(cfg.params).map(([k, v]) => `${METHOD_LABELS[k] ?? k}: ${v}`).join(", ")}
                    </p>
                    {cfg.step2_method && cfg.step2_params && (
                      <>
                        <p>
                          <span className="text-text-secondary">2nd Pass:</span>{" "}
                          {cfg.step2_method.replace("_", " ")}
                        </p>
                        <p>
                          <span className="text-text-secondary">2nd Pass Params:</span>{" "}
                          {Object.entries(cfg.step2_params).map(([k, v]) => `${METHOD_LABELS[k] ?? k}: ${v}`).join(", ")}
                        </p>
                      </>
                    )}
                    {cfg.filter_params && (
                      <p>
                        <span className="text-text-secondary">Filters:</span>{" "}
                        {Object.entries(cfg.filter_params).map(([k, v]) => {
                          const labels: Record<string, string> = {
                            min_char_length: "Min Chars",
                            min_word_count: "Min Words",
                            max_whitespace_ratio: "Max Whitespace Ratio",
                          };
                          return `${labels[k] ?? k}: ${v}`;
                        }).join(", ")}
                      </p>
                    )}
                  </div>
                )}

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

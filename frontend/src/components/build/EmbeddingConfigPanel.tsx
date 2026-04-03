import { useState, useEffect, useCallback } from "react";
import type { EmbeddingConfig, ChunkConfig } from "../../lib/api";
import {
  fetchEmbeddingConfigs,
  createEmbeddingConfig,
  deleteEmbeddingConfig,
} from "../../lib/api";
import EmbedAction from "./EmbedAction";

const EMBEDDING_TYPES = [
  "dense_openai",
  "dense_sentence_transformers",
  "bm25_sparse",
] as const;
type EmbeddingType = (typeof EMBEDDING_TYPES)[number];

const TYPE_DEFAULTS: Record<EmbeddingType, string> = {
  dense_openai: "text-embedding-3-small",
  dense_sentence_transformers: "all-MiniLM-L6-v2",
  bm25_sparse: "",
};

const TYPE_LABELS: Record<EmbeddingType, string> = {
  dense_openai: "Dense (OpenAI)",
  dense_sentence_transformers: "Dense (ST)",
  bm25_sparse: "BM25 Sparse",
};

interface Props {
  projectId: number;
  chunkConfigs: ChunkConfig[];
  onConfigsChanged?: () => void;
}

export default function EmbeddingConfigPanel({
  projectId,
  chunkConfigs,
  onConfigsChanged,
}: Props) {
  const [configs, setConfigs] = useState<EmbeddingConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [embType, setEmbType] = useState<EmbeddingType>("dense_openai");
  const [modelName, setModelName] = useState(TYPE_DEFAULTS.dense_openai);
  const [paramsJson, setParamsJson] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Embed inline
  const [embedConfigId, setEmbedConfigId] = useState<number | null>(null);

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEmbeddingConfigs(projectId);
      setConfigs(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load embedding configs",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // Update model name default when type changes
  useEffect(() => {
    setModelName(TYPE_DEFAULTS[embType]);
  }, [embType]);

  const canSave = name.trim().length > 0;

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setFormError(null);

    let params: Record<string, unknown> = {};
    if (paramsJson.trim()) {
      try {
        params = JSON.parse(paramsJson.trim());
      } catch {
        setFormError("Invalid JSON in params");
        setSaving(false);
        return;
      }
    }

    try {
      await createEmbeddingConfig(projectId, {
        name: name.trim(),
        type: embType,
        model_name: modelName,
        params,
      });
      setName("");
      setEmbType("dense_openai");
      setModelName(TYPE_DEFAULTS.dense_openai);
      setParamsJson("");
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
      await deleteEmbeddingConfig(projectId, configId);
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

  return (
    <div className="space-y-6">
      {/* New Embedding Config Form */}
      <div className="rounded-xl border border-border bg-card/60 p-5">
        <h4 className="mb-4 text-sm font-semibold text-text-primary">
          New Embedding Config
        </h4>

        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Name</span>
          <p className="mt-0.5 text-xs text-text-muted">A descriptive name for this embedding configuration</p>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. openai-small"
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </label>

        <label className="mt-3 block">
          <span className="mb-1 block text-xs text-text-secondary">Type</span>
          <p className="mt-0.5 text-xs text-text-muted">dense_openai: OpenAI API embeddings (best quality) | dense_sentence_transformers: local model embeddings (free, slower) | bm25_sparse: keyword-based sparse embeddings (no ML)</p>
          <select
            value={embType}
            onChange={(e) => setEmbType(e.target.value as EmbeddingType)}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
          >
            {EMBEDDING_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>

        <label className="mt-3 block">
          <span className="mb-1 block text-xs text-text-secondary">
            Model Name
          </span>
          <p className="mt-0.5 text-xs text-text-muted">Model identifier (e.g., text-embedding-3-small for OpenAI, all-MiniLM-L6-v2 for sentence-transformers)</p>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder={TYPE_DEFAULTS[embType] || "model name"}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </label>

        <label className="mt-3 block">
          <span className="mb-1 block text-xs text-text-secondary">
            Params (JSON, optional)
          </span>
          <p className="mt-0.5 text-xs text-text-muted">Optional JSON parameters for the embedding model</p>
          <textarea
            value={paramsJson}
            onChange={(e) => setParamsJson(e.target.value)}
            placeholder='{"dimensions": 1536}'
            rows={2}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </label>

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
          Saved Embedding Configs
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
            No embedding configs yet. Create one above.
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
              <li key={cfg.id} className="rounded-lg bg-card px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="truncate text-sm font-medium text-text-primary">
                      {cfg.name}
                    </span>
                    <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider text-accent">
                      {TYPE_LABELS[cfg.type as EmbeddingType] ?? cfg.type}
                    </span>
                    {cfg.model_name && (
                      <span className="shrink-0 font-mono text-2xs text-text-muted">
                        {cfg.model_name}
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-text-muted">
                      {new Date(cfg.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() =>
                        setEmbedConfigId(
                          embedConfigId === cfg.id ? null : cfg.id,
                        )
                      }
                      className="rounded px-2 py-1 text-xs text-score-high hover:bg-score-high/10"
                    >
                      Embed
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

                {/* Inline embed */}
                {embedConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3">
                    <EmbedAction
                      projectId={projectId}
                      embeddingConfigId={cfg.id}
                      chunkConfigs={chunkConfigs}
                      onEmbedComplete={onConfigsChanged}
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

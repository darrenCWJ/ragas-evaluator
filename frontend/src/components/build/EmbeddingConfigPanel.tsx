import { useState, useEffect, useCallback } from "react";
import type { EmbeddingConfig, ChunkConfig } from "../../lib/api";
import {
  fetchEmbeddingConfigs,
  fetchConfigDefaults,
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

const FALLBACK_TYPE_DEFAULTS: Record<EmbeddingType, string> = {
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
  const [typeDefaults, setTypeDefaults] = useState<Record<EmbeddingType, string>>(FALLBACK_TYPE_DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [embType, setEmbType] = useState<EmbeddingType>("dense_openai");
  const [modelName, setModelName] = useState(FALLBACK_TYPE_DEFAULTS.dense_openai);
  const [paramsJson, setParamsJson] = useState("");
  const [useDimReduction, setUseDimReduction] = useState(false);
  const [dimensions, setDimensions] = useState(256);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Embed inline / Expand
  const [embedConfigId, setEmbedConfigId] = useState<number | null>(null);
  const [expandedConfigId, setExpandedConfigId] = useState<number | null>(null);

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
    // Load embedding default from backend config
    fetchConfigDefaults().then((defaults) => {
      setTypeDefaults((prev) => ({
        ...prev,
        dense_openai: defaults.default_eval_embedding,
      }));
      setModelName(defaults.default_eval_embedding);
    }).catch(() => {
      // keep fallback defaults
    });
  }, [loadConfigs]);

  // Update model name default when type changes
  useEffect(() => {
    setModelName(typeDefaults[embType]);
  }, [embType, typeDefaults]);

  const isOpenAIEmb3 =
    embType === "dense_openai" && modelName.startsWith("text-embedding-3");
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

    // Merge dimension reduction into params for OpenAI models
    if (useDimReduction && isOpenAIEmb3) {
      params.dimensions = dimensions;
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
      setModelName(typeDefaults.dense_openai);
      setParamsJson("");
      setUseDimReduction(false);
      setDimensions(256);
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
          <p className="mt-0.5 text-xs text-text-muted">
            {embType === "dense_openai" ? (
              <>OpenAI models: <code className="rounded bg-elevated px-1">text-embedding-3-small</code> (fast, cheap) | <code className="rounded bg-elevated px-1">text-embedding-3-large</code> (best quality, supports dimension reduction)</>
            ) : embType === "dense_sentence_transformers" ? (
              <>Local models from <a href="https://huggingface.co/models?pipeline_tag=sentence-similarity&sort=downloads" target="_blank" rel="noopener noreferrer" className="underline hover:text-accent">Hugging Face</a>: <code className="rounded bg-elevated px-1">all-MiniLM-L6-v2</code> (fast) | <code className="rounded bg-elevated px-1">all-mpnet-base-v2</code> (better quality) | <code className="rounded bg-elevated px-1">BAAI/bge-small-en-v1.5</code> | <code className="rounded bg-elevated px-1">nomic-ai/nomic-embed-text-v1.5</code></>
            ) : (
              <>BM25 sparse search does not use a model</>
            )}
          </p>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder={typeDefaults[embType] || "model name"}
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

        {/* Dimension reduction — only for OpenAI text-embedding-3 models */}
        {isOpenAIEmb3 && (
          <div className="mt-3 rounded-lg border border-border/50 bg-card/30 p-3">
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={useDimReduction}
                onChange={(e) => setUseDimReduction(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              />
              <div>
                <span className="text-xs font-medium text-text-secondary">
                  Dimension reduction (Matryoshka)
                </span>
                <p className="text-xs text-text-muted">
                  OpenAI text-embedding-3 models support shortening the embedding
                  dimensions. Lower dimensions = faster search and less storage,
                  with minimal quality loss. Default is 3072 for -large and 1536
                  for -small.
                </p>
              </div>
            </label>
            {useDimReduction && (
              <label className="mt-2 block">
                <span className="mb-1 block text-xs text-text-secondary">
                  Dimensions
                </span>
                <select
                  value={dimensions}
                  onChange={(e) => setDimensions(Number(e.target.value))}
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                >
                  {[256, 512, 768, 1024, 1536, 3072].map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}

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

                {/* Expanded config details */}
                {expandedConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3 space-y-1 text-xs text-text-muted">
                    <p>
                      <span className="text-text-secondary">Type:</span>{" "}
                      {TYPE_LABELS[cfg.type as EmbeddingType] ?? cfg.type}
                    </p>
                    {cfg.model_name && (
                      <p>
                        <span className="text-text-secondary">Model:</span>{" "}
                        {cfg.model_name}
                      </p>
                    )}
                    {cfg.params && Object.keys(cfg.params).length > 0 && (
                      <p>
                        <span className="text-text-secondary">Params:</span>{" "}
                        {Object.entries(cfg.params).map(([k, v]) => `${k}: ${v}`).join(", ")}
                      </p>
                    )}
                  </div>
                )}

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

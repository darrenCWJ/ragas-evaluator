import { useState, useEffect, useCallback } from "react";
import type {
  RagConfig,
  RagConfigCreate,
  EmbeddingConfig,
  ChunkConfig,
} from "../../lib/api";
import {
  fetchRagConfigs,
  createRagConfig,
  deleteRagConfig,
} from "../../lib/api";
import RagTestQuery from "./RagTestQuery";

const SEARCH_TYPES = ["dense", "sparse", "hybrid"] as const;
const RESPONSE_MODES = ["single_shot", "multi_step"] as const;

const SEARCH_LABELS: Record<string, string> = {
  dense: "Dense",
  sparse: "Sparse",
  hybrid: "Hybrid",
};

const MODE_LABELS: Record<string, string> = {
  single_shot: "Single Shot",
  multi_step: "Multi Step",
};

interface Props {
  projectId: number;
  embeddingConfigs: EmbeddingConfig[];
  chunkConfigs: ChunkConfig[];
  onConfigsChanged?: () => void;
}

export default function RagConfigPanel({
  projectId,
  embeddingConfigs,
  chunkConfigs,
  onConfigsChanged,
}: Props) {
  const [configs, setConfigs] = useState<RagConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [embConfigId, setEmbConfigId] = useState<number | "">(
    embeddingConfigs.length > 0 ? embeddingConfigs[0]!.id : "",
  );
  const [chunkConfigId, setChunkConfigId] = useState<number | "">(
    chunkConfigs.length > 0 ? chunkConfigs[0]!.id : "",
  );
  const [searchType, setSearchType] = useState<string>("dense");
  const [llmModel, setLlmModel] = useState("gpt-4o-mini");
  const [responseMode, setResponseMode] = useState<string>("single_shot");
  const [topK, setTopK] = useState(5);
  const [maxSteps, setMaxSteps] = useState(3);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  // Hybrid fields
  const [sparseConfigId, setSparseConfigId] = useState<number | "">(
    embeddingConfigs.find((c) => c.type === "bm25_sparse")?.id ?? "",
  );
  const [alpha, setAlpha] = useState(0.5);

  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Test inline
  const [testConfigId, setTestConfigId] = useState<number | null>(null);

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRagConfigs(projectId);
      setConfigs(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load RAG configs",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // Update default selectors when configs change
  useEffect(() => {
    if (embeddingConfigs.length > 0 && embConfigId === "") {
      setEmbConfigId(embeddingConfigs[0]!.id);
    }
  }, [embeddingConfigs, embConfigId]);

  useEffect(() => {
    if (chunkConfigs.length > 0 && chunkConfigId === "") {
      setChunkConfigId(chunkConfigs[0]!.id);
    }
  }, [chunkConfigs, chunkConfigId]);

  const canSave =
    name.trim().length > 0 && embConfigId !== "" && chunkConfigId !== "";

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setFormError(null);
    try {
      const payload: RagConfigCreate = {
        name: name.trim(),
        embedding_config_id: embConfigId as number,
        chunk_config_id: chunkConfigId as number,
        search_type: searchType,
        llm_model: llmModel,
        top_k: topK,
        response_mode: responseMode,
      };
      if (responseMode === "multi_step") payload.max_steps = maxSteps;
      if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim();
      if (searchType === "hybrid") {
        if (sparseConfigId !== "") payload.sparse_config_id = sparseConfigId as number;
        payload.alpha = alpha;
      }
      await createRagConfig(projectId, payload);
      setName("");
      setSearchType("dense");
      setLlmModel("gpt-4o-mini");
      setResponseMode("single_shot");
      setTopK(5);
      setMaxSteps(3);
      setSystemPrompt("");
      setShowAdvanced(false);
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
    try {
      await deleteRagConfig(projectId, configId);
      setConfirmDeleteId(null);
      loadConfigs();
      onConfigsChanged?.();
    } catch {
      // keep inline
    } finally {
      setDeleting(false);
    }
  }

  // If no embedding configs available, show guidance
  if (embeddingConfigs.length === 0) {
    return (
      <div className="space-y-6">
        <div className="rounded-xl border border-border bg-card/60 p-5">
          <p className="text-sm text-text-muted">
            Create an embedding config first before setting up RAG.
          </p>
        </div>
        {/* Still show saved configs list */}
        {renderConfigsList()}
      </div>
    );
  }

  function renderConfigsList() {
    return (
      <div>
        <h4 className="mb-3 text-sm font-semibold text-text-primary">
          Saved RAG Configs
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
            No RAG configs yet. Create one above.
          </p>
        ) : (
          <ul className="space-y-2">
            {configs.map((cfg) => (
              <li key={cfg.id} className="rounded-lg bg-card px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="truncate text-sm font-medium text-text-primary">
                      {cfg.name}
                    </span>
                    <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent">
                      {SEARCH_LABELS[cfg.search_type] ?? cfg.search_type}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-text-muted">
                      {cfg.llm_model}
                    </span>
                    <span className="shrink-0 rounded bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted">
                      {MODE_LABELS[cfg.response_mode] ?? cfg.response_mode}
                    </span>
                    <span className="shrink-0 text-xs text-text-muted">
                      {new Date(cfg.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() =>
                        setTestConfigId(
                          testConfigId === cfg.id ? null : cfg.id,
                        )
                      }
                      className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
                    >
                      Test
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

                {/* Inline test query */}
                {testConfigId === cfg.id && (
                  <div className="mt-3 border-t border-border pt-3">
                    <RagTestQuery
                      projectId={projectId}
                      ragConfigId={cfg.id}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* New RAG Config Form */}
      <div className="rounded-xl border border-border bg-card/60 p-5">
        <h4 className="mb-4 text-sm font-semibold text-text-primary">
          New RAG Config
        </h4>

        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. dense-gpt4o"
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </label>

        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              Embedding Config
            </span>
            <select
              value={embConfigId}
              onChange={(e) => setEmbConfigId(Number(e.target.value))}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            >
              {embeddingConfigs.map((ec) => (
                <option key={ec.id} value={ec.id}>
                  {ec.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              Chunk Config
            </span>
            <select
              value={chunkConfigId}
              onChange={(e) => setChunkConfigId(Number(e.target.value))}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            >
              {chunkConfigs.map((cc) => (
                <option key={cc.id} value={cc.id}>
                  {cc.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              Search Type
            </span>
            <select
              value={searchType}
              onChange={(e) => setSearchType(e.target.value)}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            >
              {SEARCH_TYPES.map((st) => (
                <option key={st} value={st}>
                  {SEARCH_LABELS[st]}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              LLM Model
            </span>
            <input
              type="text"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder="gpt-4o-mini"
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
          </label>
        </div>

        {/* Hybrid-specific fields */}
        {searchType === "hybrid" && (
          <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-border/50 bg-card/30 p-3">
            <label className="block">
              <span className="mb-1 block text-xs text-text-secondary">
                Sparse Config
              </span>
              <select
                value={sparseConfigId}
                onChange={(e) =>
                  setSparseConfigId(
                    e.target.value ? Number(e.target.value) : "",
                  )
                }
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="">None</option>
                {embeddingConfigs.map((ec) => (
                  <option key={ec.id} value={ec.id}>
                    {ec.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-secondary">
                Alpha ({alpha.toFixed(2)})
              </span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={alpha}
                onChange={(e) => setAlpha(parseFloat(e.target.value))}
                className="mt-1 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-border accent-accent"
              />
            </label>
          </div>
        )}

        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              Response Mode
            </span>
            <select
              value={responseMode}
              onChange={(e) => setResponseMode(e.target.value)}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            >
              {RESPONSE_MODES.map((rm) => (
                <option key={rm} value={rm}>
                  {MODE_LABELS[rm]}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              Top K
            </span>
            <input
              type="number"
              value={topK}
              min={1}
              max={50}
              onChange={(e) => setTopK(parseInt(e.target.value) || 5)}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            />
          </label>
        </div>

        {/* Multi-step: max_steps */}
        {responseMode === "multi_step" && (
          <label className="mt-3 block">
            <span className="mb-1 block text-xs text-text-secondary">
              Max Steps
            </span>
            <input
              type="number"
              value={maxSteps}
              min={1}
              max={10}
              onChange={(e) => setMaxSteps(parseInt(e.target.value) || 3)}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
            />
          </label>
        )}

        {/* Advanced: system prompt (collapsible) */}
        <div className="mt-3 border-t border-border pt-3">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary"
          >
            <svg
              className={`h-3 w-3 transition-transform ${showAdvanced ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 5l7 7-7 7"
              />
            </svg>
            Advanced Settings
          </button>

          {showAdvanced && (
            <label className="mt-2 block">
              <span className="mb-1 block text-xs text-text-secondary">
                System Prompt (optional)
              </span>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are a helpful assistant..."
                rows={3}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </label>
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
      {renderConfigsList()}
    </div>
  );
}

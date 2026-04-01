import { useState } from "react";
import type { ChunkConfig, EmbedResult } from "../../lib/api";
import { embedChunks } from "../../lib/api";

interface Props {
  projectId: number;
  embeddingConfigId: number;
  chunkConfigs: ChunkConfig[];
  onEmbedComplete?: () => void;
}

export default function EmbedAction({
  projectId,
  embeddingConfigId,
  chunkConfigs,
  onEmbedComplete,
}: Props) {
  const [selectedChunkConfigId, setSelectedChunkConfigId] = useState<
    number | null
  >(chunkConfigs.length > 0 ? chunkConfigs[0]!.id : null);
  const [embedding, setEmbedding] = useState(false);
  const [result, setResult] = useState<EmbedResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (chunkConfigs.length === 0) {
    return (
      <p className="py-2 text-xs text-text-muted">
        Create and generate chunks first before embedding.
      </p>
    );
  }

  async function handleEmbed() {
    if (!selectedChunkConfigId) return;
    setEmbedding(true);
    setError(null);
    setResult(null);
    try {
      const res = await embedChunks(
        projectId,
        embeddingConfigId,
        selectedChunkConfigId,
      );
      setResult(res);
      onEmbedComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Embedding failed");
    } finally {
      setEmbedding(false);
    }
  }

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1 block text-xs text-text-secondary">
          Chunk Config
        </span>
        <select
          value={selectedChunkConfigId ?? ""}
          onChange={(e) => setSelectedChunkConfigId(Number(e.target.value))}
          disabled={embedding}
          className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none disabled:opacity-50"
        >
          {chunkConfigs.map((cc) => (
            <option key={cc.id} value={cc.id}>
              {cc.name} ({cc.method})
            </option>
          ))}
        </select>
      </label>

      <button
        onClick={handleEmbed}
        disabled={embedding || !selectedChunkConfigId}
        className="rounded-lg bg-score-high/15 px-4 py-1.5 text-xs font-medium text-score-high transition-colors hover:bg-score-high/25 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {embedding ? (
          <span className="flex items-center gap-2">
            <svg
              className="h-3.5 w-3.5 animate-spin"
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
            Embedding...
          </span>
        ) : (
          "Embed Chunks"
        )}
      </button>

      {result && (
        <div className="rounded-lg bg-score-high/10 px-3 py-2 text-xs text-score-high">
          Embedded{" "}
          <span className="font-mono font-bold">{result.total_embedded}</span>{" "}
          chunks
          {result.collection && (
            <span className="text-text-muted">
              {" "}
              &rarr; collection: {result.collection}
            </span>
          )}
          {result.index && (
            <span className="text-text-muted">
              {" "}
              &rarr; index: {result.index}
            </span>
          )}
        </div>
      )}

      {error && (
        <p className="rounded-lg bg-score-low/10 px-3 py-2 text-xs text-score-low">
          {error}
        </p>
      )}
    </div>
  );
}

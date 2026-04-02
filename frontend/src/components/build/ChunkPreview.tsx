import { useState } from "react";
import type { Document as Doc, ChunkPreviewResult } from "../../lib/api";
import { previewChunks } from "../../lib/api";

interface Props {
  projectId: number;
  configId: number;
  documents: Doc[];
}

export default function ChunkPreview({
  projectId,
  configId,
  documents,
}: Props) {
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [result, setResult] = useState<ChunkPreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePreview() {
    if (!selectedDocId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await previewChunks(projectId, configId, selectedDocId);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setLoading(false);
    }
  }

  if (documents.length === 0) {
    return (
      <p className="text-xs text-text-muted">
        Upload documents first to preview chunks.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-2">
        <label className="flex-1">
          <span className="mb-1 block text-xs text-text-secondary">
            Document
          </span>
          <select
            value={selectedDocId ?? ""}
            onChange={(e) => setSelectedDocId(Number(e.target.value) || null)}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
          >
            <option value="">Select a document</option>
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={handlePreview}
          disabled={!selectedDocId || loading}
          className="shrink-0 rounded-lg bg-accent/15 px-4 py-1.5 text-sm font-medium text-accent hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Loading..." : "Preview"}
        </button>
      </div>

      {error && (
        <p className="text-xs text-score-low">{error}</p>
      )}

      {result && (
        <div>
          <p className="mb-2 text-xs text-text-secondary">
            {result.chunk_count} chunk{result.chunk_count !== 1 ? "s" : ""} from{" "}
            <span className="text-text-primary">{result.filename}</span>
          </p>
          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
            {result.chunks.map((chunk, i) => (
              <div
                key={i}
                className="rounded-lg border border-border bg-deep/50 px-3 py-2"
              >
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-text-muted">
                  Chunk {i + 1}
                </span>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">
                  {chunk}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

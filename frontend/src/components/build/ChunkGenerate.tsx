import { useState, useEffect, useRef } from "react";
import type { ChunkGenerateResult } from "../../lib/api";
import { generateChunks } from "../../lib/api";

interface Props {
  projectId: number;
  configId: number;
}

export default function ChunkGenerate({ projectId, configId }: Props) {
  const [confirmed, setConfirmed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<ChunkGenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const triggered = useRef(false);

  useEffect(() => {
    if (!confirmed || triggered.current) return;
    triggered.current = true;

    setGenerating(true);
    setError(null);
    generateChunks(projectId, configId)
      .then((data) => setResult(data))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Generation failed"),
      )
      .finally(() => setGenerating(false));
  }, [confirmed, projectId, configId]);

  if (result) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <svg
            className="h-4 w-4 text-score-high"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span className="text-sm font-medium text-score-high">
            {result.total_chunks} total chunks generated
          </span>
        </div>
        <ul className="space-y-1">
          {result.documents.map((d) => (
            <li
              key={d.document_id}
              className="flex items-center justify-between rounded bg-card px-3 py-1.5 text-xs"
            >
              <span className="truncate text-text-secondary">{d.filename}</span>
              <span className="shrink-0 font-mono text-text-primary">
                {d.chunk_count}
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (error) {
    return <p className="text-xs text-score-low">{error}</p>;
  }

  if (generating) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-text-muted">
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
        Generating chunks...
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-score-mid/30 bg-score-mid/5 p-3">
      <p className="mb-3 text-xs text-score-mid">
        This will replace any existing chunks for this config. Continue?
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => setConfirmed(true)}
          className="rounded-lg bg-score-mid/20 px-3 py-1 text-xs font-medium text-score-mid hover:bg-score-mid/30"
        >
          Yes, generate
        </button>
      </div>
    </div>
  );
}

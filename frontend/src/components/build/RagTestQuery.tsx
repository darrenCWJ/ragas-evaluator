import { useState } from "react";
import type { RagQueryResult } from "../../lib/api";
import { queryRag } from "../../lib/api";

interface Props {
  projectId: number;
  ragConfigId: number;
}

export default function RagTestQuery({ projectId, ragConfigId }: Props) {
  const [query, setQuery] = useState("");
  const [querying, setQuerying] = useState(false);
  const [result, setResult] = useState<RagQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [contextsOpen, setContextsOpen] = useState(false);

  async function handleQuery() {
    if (!query.trim() || querying) return;
    setQuerying(true);
    setError(null);
    setResult(null);
    setContextsOpen(false);
    try {
      const res = await queryRag(projectId, ragConfigId, query.trim());
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setQuerying(false);
    }
  }

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1 block text-xs text-text-secondary">Query</span>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a question..."
          rows={2}
          disabled={querying}
          className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none disabled:opacity-50"
        />
      </label>

      <button
        onClick={handleQuery}
        disabled={querying || !query.trim()}
        className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {querying ? (
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
            Querying...
          </span>
        ) : (
          "Send"
        )}
      </button>

      {error && (
        <p className="rounded-lg bg-score-low/10 px-3 py-2 text-xs text-score-low">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-3">
          {/* Answer */}
          <div className="rounded-lg bg-elevated px-4 py-3">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-primary">
              {result.answer}
            </p>
            <div className="mt-2 flex items-center gap-3 text-2xs text-text-muted">
              <span className="font-mono">{result.model}</span>
              <span>
                {result.usage.prompt_tokens}p / {result.usage.completion_tokens}c
                tokens
              </span>
            </div>
          </div>

          {/* Contexts */}
          {result.contexts.length > 0 && (
            <div>
              <button
                onClick={() => setContextsOpen(!contextsOpen)}
                className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary"
              >
                <svg
                  className={`h-3 w-3 transition-transform ${contextsOpen ? "rotate-90" : ""}`}
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
                {result.contexts.length} retrieved context
                {result.contexts.length !== 1 ? "s" : ""}
              </button>

              {contextsOpen && (
                <ul className="mt-2 space-y-2">
                  {result.contexts.map((ctx, i) => (
                    <li
                      key={i}
                      className="rounded-lg border border-border bg-card/40 px-3 py-2"
                    >
                      <p className="line-clamp-4 text-xs leading-relaxed text-text-secondary">
                        {ctx.content}
                      </p>
                      {ctx.chunk_id != null && (
                        <span className="mt-1 inline-block font-mono text-2xs text-text-muted">
                          chunk #{ctx.chunk_id}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

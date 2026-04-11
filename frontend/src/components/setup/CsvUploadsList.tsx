import { useState, useEffect, useCallback } from "react";
import {
  fetchBotConfigs,
  fetchBotConfigBaselines,
  deleteBotConfig,
  type BotConfig,
  type BotConfigBaselinesResult,
} from "../../lib/api";

interface Props {
  projectId: number;
  refreshKey: number;
}

export default function CsvUploadsList({ projectId, refreshKey }: Props) {
  const [csvConfigs, setCsvConfigs] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [samples, setSamples] = useState<Record<number, BotConfigBaselinesResult>>({});
  const [loadingSample, setLoadingSample] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const configs = await fetchBotConfigs(projectId);
      setCsvConfigs(configs.filter((c) => c.connector_type === "csv"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load CSV uploads");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function handleToggle(configId: number) {
    if (expandedId === configId) {
      setExpandedId(null);
      return;
    }

    setExpandedId(configId);

    if (!samples[configId]) {
      setLoadingSample(configId);
      try {
        const data = await fetchBotConfigBaselines(projectId, configId, 10);
        setSamples((prev) => ({ ...prev, [configId]: data }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load sample");
      } finally {
        setLoadingSample(null);
      }
    }
  }

  async function handleDelete(configId: number) {
    setDeletingId(configId);
    try {
      await deleteBotConfig(projectId, configId);
      setCsvConfigs((prev) => prev.filter((c) => c.id !== configId));
      if (expandedId === configId) setExpandedId(null);
      setSamples((prev) => {
        const next = { ...prev };
        delete next[configId];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-text-primary">
          Uploaded CSVs
        </h3>
        <p className="text-xs text-text-secondary">
          {csvConfigs.length} CSV{csvConfigs.length !== 1 ? "s" : ""} uploaded
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-8 text-sm text-text-muted">
          <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading uploads...
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg bg-score-low/10 px-4 py-3 text-sm text-score-low">
          {error}
          <button onClick={load} className="ml-2 underline hover:no-underline">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && csvConfigs.length === 0 && (
        <div className="rounded-xl border border-dashed border-border bg-surface/50 py-10 text-center">
          <svg className="mx-auto mb-2 h-8 w-8 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <p className="text-sm text-text-muted">No CSVs uploaded yet.</p>
          <p className="mt-1 text-xs text-text-muted">
            Upload a CSV with question, bot answer, reference answer, and sources columns.
          </p>
        </div>
      )}

      {!loading && !error && csvConfigs.length > 0 && (
        <div className="space-y-2">
          {csvConfigs.map((config) => {
            const isExpanded = expandedId === config.id;
            const sample = samples[config.id];
            const isLoadingSample = loadingSample === config.id;
            const sourceFile = (config.config_json as Record<string, unknown>)?.source_file as string | undefined;

            return (
              <div
                key={config.id}
                className="overflow-hidden rounded-lg border border-border"
              >
                {/* CSV row header */}
                <button
                  onClick={() => handleToggle(config.id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface/50"
                >
                  {/* Expand/collapse chevron */}
                  <svg
                    className={`h-4 w-4 shrink-0 text-text-muted transition-transform ${
                      isExpanded ? "rotate-90" : ""
                    }`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>

                  {/* CSV icon */}
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10">
                    <svg className="h-4 w-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>

                  {/* Name + metadata */}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text-primary">
                      {config.name}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-text-muted">
                      {sourceFile && (
                        <span className="truncate">{sourceFile}</span>
                      )}
                      {sample && (
                        <span>{sample.total} row{sample.total !== 1 ? "s" : ""}</span>
                      )}
                      <span>
                        {new Date(config.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(config.id);
                    }}
                    disabled={deletingId === config.id}
                    className="shrink-0 rounded p-1 text-text-muted transition-colors hover:bg-score-low/10 hover:text-score-low disabled:opacity-50"
                    title="Delete CSV upload"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                    </svg>
                  </button>
                </button>

                {/* Expanded sample data */}
                {isExpanded && (
                  <div className="border-t border-border bg-surface/30 px-4 py-3">
                    {isLoadingSample && (
                      <div className="flex items-center gap-2 py-4 text-xs text-text-muted">
                        <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Loading sample...
                      </div>
                    )}

                    {!isLoadingSample && sample && sample.rows.length === 0 && (
                      <p className="py-4 text-center text-xs text-text-muted">
                        No rows in this CSV.
                      </p>
                    )}

                    {!isLoadingSample && sample && sample.rows.length > 0 && (
                      <>
                        <div className="mb-2 text-xs text-text-muted">
                          Showing {sample.rows.length} of {sample.total} rows
                        </div>
                        <div className="overflow-x-auto rounded-lg border border-border">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="bg-surface">
                                <th className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-text-secondary">
                                  Question
                                </th>
                                <th className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-text-secondary">
                                  Bot Answer
                                </th>
                                <th className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-text-secondary">
                                  Reference Answer
                                </th>
                                <th className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-text-secondary">
                                  Sources
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {sample.rows.map((row) => (
                                <tr
                                  key={row.id}
                                  className="border-b border-border/50 last:border-0"
                                >
                                  <td
                                    className="max-w-[180px] truncate px-3 py-1.5 text-text-primary"
                                    title={row.question}
                                  >
                                    {row.question}
                                  </td>
                                  <td
                                    className="max-w-[180px] truncate px-3 py-1.5 text-text-secondary"
                                    title={row.answer}
                                  >
                                    {row.answer}
                                  </td>
                                  <td
                                    className="max-w-[180px] truncate px-3 py-1.5 text-text-secondary"
                                    title={row.reference_answer || "—"}
                                  >
                                    {row.reference_answer || "—"}
                                  </td>
                                  <td
                                    className="max-w-[120px] truncate px-3 py-1.5 text-text-muted"
                                    title={row.sources || "—"}
                                  >
                                    {row.sources || "—"}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

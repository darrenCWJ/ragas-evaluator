import { useState, useEffect, useCallback } from "react";
import { fetchBaselines, deleteBaseline, clearBaselines, type ExternalBaseline } from "../../lib/api";

interface Props {
  projectId: number;
  refreshKey: number;
}

const PAGE_SIZE = 20;

export default function BaselinePreview({ projectId, refreshKey }: Props) {
  const [baselines, setBaselines] = useState<ExternalBaseline[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [confirmClear, setConfirmClear] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBaselines(projectId);
      setBaselines(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load baselines");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function handleDelete(id: number) {
    setDeleting(id);
    try {
      await deleteBaseline(projectId, id);
      setBaselines((prev) => prev.filter((b) => b.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeleting(null);
    }
  }

  async function handleClearAll() {
    try {
      await clearBaselines(projectId);
      setBaselines([]);
      setConfirmClear(false);
      setPage(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear");
    }
  }

  const totalPages = Math.max(1, Math.ceil(baselines.length / PAGE_SIZE));
  const visible = baselines.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            Baseline Data
          </h3>
          <p className="text-xs text-text-secondary">
            {baselines.length} row{baselines.length !== 1 ? "s" : ""} imported
          </p>
        </div>

        {baselines.length > 0 && !confirmClear && (
          <button
            onClick={() => setConfirmClear(true)}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-score-low hover:text-score-low"
          >
            Clear All
          </button>
        )}

        {confirmClear && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">Delete all?</span>
            <button
              onClick={handleClearAll}
              className="rounded-lg bg-score-low/15 px-3 py-1.5 text-xs font-medium text-score-low hover:bg-score-low/25"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirmClear(false)}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-8 text-sm text-text-muted">
          <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading baselines...
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

      {!loading && !error && baselines.length === 0 && (
        <div className="rounded-xl border border-dashed border-border bg-surface/50 py-10 text-center">
          <svg className="mx-auto mb-2 h-8 w-8 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <p className="text-sm text-text-muted">No baselines imported yet.</p>
          <p className="mt-1 text-xs text-text-muted">
            Upload a CSV with question, answer, and sources columns.
          </p>
        </div>
      )}

      {!loading && !error && baselines.length > 0 && (
        <>
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="px-3 py-2 text-xs font-medium text-text-secondary">Question</th>
                  <th className="px-3 py-2 text-xs font-medium text-text-secondary">Answer</th>
                  <th className="px-3 py-2 text-xs font-medium text-text-secondary">Sources</th>
                  <th className="w-10 px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((b) => (
                  <tr key={b.id} className="border-b border-border last:border-0 hover:bg-surface/50">
                    <td className="max-w-[200px] truncate px-3 py-2 text-text-primary" title={b.question}>
                      {b.question}
                    </td>
                    <td className="max-w-[200px] truncate px-3 py-2 text-text-secondary" title={b.answer}>
                      {b.answer}
                    </td>
                    <td className="max-w-[150px] truncate px-3 py-2 text-text-muted" title={b.sources || "—"}>
                      {b.sources || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => handleDelete(b.id)}
                        disabled={deleting === b.id}
                        className="text-text-muted transition-colors hover:text-score-low disabled:opacity-50"
                        title="Delete row"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-text-muted">
                Page {page + 1} of {totalPages}
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40"
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

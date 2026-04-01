import { useState } from "react";
import type { TestSet } from "../../lib/api";
import { deleteTestSet, ApiError } from "../../lib/api";

interface Props {
  projectId: number;
  testSets: TestSet[];
  onTestSetsChanged: () => void;
  onSelectTestSet: (testSet: TestSet) => void;
}

export default function TestSetList({
  projectId,
  testSets,
  onTestSetsChanged,
  onSelectTestSet,
}: Props) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async (id: number) => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteTestSet(projectId, id);
      setConfirmDeleteId(null);
      onTestSetsChanged();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDeleteError("Cannot delete — this test set is used by experiments.");
      } else {
        setDeleteError((err as Error).message || "Delete failed");
      }
    } finally {
      setDeleting(false);
    }
  };

  if (testSets.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-text-muted">
          No test sets yet. Generate one above.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Test Sets
      </h3>

      {deleteError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {deleteError}
        </div>
      )}

      <div className="space-y-2">
        {testSets.map((ts) => (
          <div
            key={ts.id}
            className="rounded-xl border border-border bg-card px-4 py-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-text-primary">
                  {ts.name}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-text-secondary">
                    {ts.total_questions} questions
                  </span>
                  <span className="text-text-muted">·</span>
                  {ts.pending_count > 0 && (
                    <span className="rounded-full bg-yellow-500/15 px-2 py-0.5 text-yellow-300">
                      {ts.pending_count} pending
                    </span>
                  )}
                  {ts.approved_count > 0 && (
                    <span className="rounded-full bg-green-500/15 px-2 py-0.5 text-green-300">
                      {ts.approved_count} approved
                    </span>
                  )}
                  {ts.rejected_count > 0 && (
                    <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-red-300">
                      {ts.rejected_count} rejected
                    </span>
                  )}
                  <span className="text-text-muted">·</span>
                  <span className="text-text-muted">
                    {new Date(ts.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <button
                  onClick={() => onSelectTestSet(ts)}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent"
                >
                  View Questions
                </button>

                {confirmDeleteId === ts.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(ts.id)}
                      disabled={deleting}
                      className="rounded-lg bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/30 disabled:opacity-40"
                    >
                      {deleting ? "…" : "Confirm"}
                    </button>
                    <button
                      onClick={() => {
                        setConfirmDeleteId(null);
                        setDeleteError(null);
                      }}
                      className="rounded-lg px-2 py-1.5 text-xs text-text-muted hover:text-text-secondary"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      setConfirmDeleteId(ts.id);
                      setDeleteError(null);
                    }}
                    className="rounded-lg px-2 py-1.5 text-xs text-text-muted transition hover:text-red-400"
                    title="Delete test set"
                  >
                    <svg
                      className="h-4 w-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={1.5}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                      />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

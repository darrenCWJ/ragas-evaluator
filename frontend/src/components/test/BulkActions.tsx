import { useState } from "react";
import { bulkAnnotateQuestions } from "../../lib/api";

interface Props {
  projectId: number;
  testSetId: number;
  selectedIds: Set<number>;
  pendingCount: number;
  onBulkComplete: () => void;
}

export default function BulkActions({
  projectId,
  testSetId,
  selectedIds,
  pendingCount,
  onBulkComplete,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmRejectAll, setConfirmRejectAll] = useState(false);

  const run = async (
    action: "approve" | "reject" | "approve_all" | "reject_all",
    ids?: number[],
  ) => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    setConfirmRejectAll(false);
    try {
      const result = await bulkAnnotateQuestions(projectId, testSetId, {
        action,
        question_ids: ids,
      });
      setSuccess(`Updated ${result.updated_count} questions`);
      setTimeout(() => setSuccess(null), 2000);
      onBulkComplete();
    } catch (err) {
      setError((err as Error).message || "Bulk action failed");
    } finally {
      setBusy(false);
    }
  };

  const hasSelection = selectedIds.size > 0;
  const hasPending = pendingCount > 0;

  // Don't render if nothing actionable
  if (!hasSelection && !hasPending) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-elevated px-4 py-2.5 text-xs">
      {/* Selection actions */}
      {hasSelection && (
        <>
          <span className="font-medium text-text-primary">
            {selectedIds.size} selected
          </span>
          <span className="text-text-muted">&mdash;</span>
          <button
            onClick={() => run("approve", [...selectedIds])}
            disabled={busy}
            className="rounded-md border border-green-500/30 px-2.5 py-1 font-medium text-green-400 transition hover:bg-green-500/10 disabled:opacity-40"
          >
            Approve Selected
          </button>
          <button
            onClick={() => run("reject", [...selectedIds])}
            disabled={busy}
            className="rounded-md border border-red-500/30 px-2.5 py-1 font-medium text-red-400 transition hover:bg-red-500/10 disabled:opacity-40"
          >
            Reject Selected
          </button>
          {hasPending && (
            <span className="mx-1 text-text-muted">|</span>
          )}
        </>
      )}

      {/* All-pending actions */}
      {hasPending && (
        <>
          <button
            onClick={() => run("approve_all")}
            disabled={busy}
            className="rounded-md border border-green-500/20 px-2.5 py-1 text-green-400/80 transition hover:bg-green-500/10 disabled:opacity-40"
          >
            Approve All Pending ({pendingCount})
          </button>

          {!confirmRejectAll ? (
            <button
              onClick={() => setConfirmRejectAll(true)}
              disabled={busy}
              className="rounded-md border border-red-500/20 px-2.5 py-1 text-red-400/80 transition hover:bg-red-500/10 disabled:opacity-40"
            >
              Reject All Pending ({pendingCount})
            </button>
          ) : (
            <button
              onClick={() => run("reject_all")}
              disabled={busy}
              className="rounded-md border border-red-500/50 bg-red-500/15 px-2.5 py-1 font-medium text-red-300 transition hover:bg-red-500/25 disabled:opacity-40"
            >
              Confirm Reject All?
            </button>
          )}
        </>
      )}

      {/* Feedback */}
      {success && (
        <span className="ml-auto text-green-400">{success}</span>
      )}
      {error && (
        <span className="ml-auto text-red-400">{error}</span>
      )}
    </div>
  );
}

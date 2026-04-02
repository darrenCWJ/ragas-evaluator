import { useState } from "react";
import type { Document } from "../../lib/api";
import { deleteDocument } from "../../lib/api";

interface Props {
  projectId: number;
  documents: Document[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export default function DocumentList({
  projectId,
  documents,
  loading,
  error,
  onRefresh,
}: Props) {
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(docId: number) {
    setDeleting(true);
    try {
      await deleteDocument(projectId, docId);
      setConfirmId(null);
      onRefresh();
    } catch {
      // Error shown inline is sufficient
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-text-muted">
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
        Loading documents...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-between rounded-lg bg-score-low/10 px-4 py-3 text-sm text-score-low">
        <span>{error}</span>
        <button
          onClick={onRefresh}
          className="ml-3 rounded-md bg-score-low/20 px-3 py-1 text-xs font-medium hover:bg-score-low/30"
        >
          Retry
        </button>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-text-muted">
        No documents uploaded yet.
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {documents.map((doc) => (
        <li
          key={doc.id}
          className="flex items-center justify-between rounded-lg bg-card px-4 py-3"
        >
          <div className="flex items-center gap-3 overflow-hidden">
            <span
              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                doc.file_type === ".pdf"
                  ? "bg-score-low/15 text-score-low"
                  : "bg-accent/15 text-accent"
              }`}
            >
              {doc.file_type.replace(".", "")}
            </span>
            <span className="truncate text-sm text-text-primary">
              {doc.filename}
            </span>
            <span className="shrink-0 text-xs text-text-muted">
              {new Date(doc.created_at).toLocaleDateString()}
            </span>
          </div>

          {confirmId === doc.id ? (
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-text-secondary">Delete?</span>
              <button
                onClick={() => handleDelete(doc.id)}
                disabled={deleting}
                className="rounded bg-score-low/20 px-2 py-1 text-xs font-medium text-score-low hover:bg-score-low/30 disabled:opacity-50"
              >
                {deleting ? "..." : "Yes"}
              </button>
              <button
                onClick={() => setConfirmId(null)}
                className="rounded bg-elevated px-2 py-1 text-xs text-text-secondary hover:bg-border"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmId(doc.id)}
              className="shrink-0 rounded p-1.5 text-text-muted hover:bg-elevated hover:text-score-low"
              title="Delete document"
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
                  d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                />
              </svg>
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

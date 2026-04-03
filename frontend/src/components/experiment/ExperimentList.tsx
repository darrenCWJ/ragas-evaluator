import { useState } from "react";
import { deleteExperiment, ApiError } from "../../lib/api";
import type { Experiment } from "../../lib/api";

interface Props {
  projectId: number;
  experiments: Experiment[];
  selectedId: number | null;
  onSelect: (experiment: Experiment) => void;
  onRefresh: () => void;
  /** Set of experiment IDs selected for comparison (multi-select) */
  compareSet?: Set<number>;
  /** Toggle an experiment in/out of the compare set */
  onToggleCompare?: (id: number) => void;
}

const STATUS_STYLES: Record<
  string,
  { bg: string; text: string; label: string; pulse?: boolean }
> = {
  pending: {
    bg: "bg-yellow-500/15",
    text: "text-yellow-300",
    label: "Pending",
  },
  running: {
    bg: "bg-blue-500/15",
    text: "text-blue-300",
    label: "Running",
    pulse: true,
  },
  completed: {
    bg: "bg-green-500/15",
    text: "text-green-300",
    label: "Completed",
  },
  failed: {
    bg: "bg-red-500/15",
    text: "text-red-300",
    label: "Failed",
  },
};

export default function ExperimentList({
  projectId,
  experiments,
  selectedId,
  onSelect,
  onRefresh,
  compareSet,
  onToggleCompare,
}: Props) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async (id: number) => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteExperiment(projectId, id);
      setConfirmDeleteId(null);
      onRefresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(err.message);
      } else {
        setDeleteError((err as Error).message || "Delete failed");
      }
    } finally {
      setDeleting(false);
    }
  };

  if (experiments.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-text-muted">
          No experiments yet. Create one above to get started.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Experiments
      </h3>

      {deleteError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {deleteError}
        </div>
      )}

      <div className="space-y-2">
        {experiments.map((exp) => {
          const style = STATUS_STYLES[exp.status] ?? STATUS_STYLES["pending"]!;
          const isSelected = selectedId === exp.id;

          return (
            <button
              key={exp.id}
              type="button"
              onClick={() => onSelect(exp)}
              className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                isSelected
                  ? "border-accent/50 bg-accent/5 ring-1 ring-accent/30"
                  : "border-border bg-card hover:border-border-focus"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-text-primary">
                    {exp.name}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                    {/* Status badge */}
                    <span
                      className={`rounded-full px-2 py-0.5 ${style.bg} ${style.text} ${
                        style.pulse ? "animate-pulse" : ""
                      }`}
                    >
                      {style.label}
                    </span>
                    <span className="text-text-muted">·</span>
                    <span className="text-text-secondary">{exp.model}</span>
                    {exp.approved_question_count != null && (
                      <>
                        <span className="text-text-muted">·</span>
                        <span className="text-text-secondary">
                          {exp.approved_question_count} questions
                        </span>
                      </>
                    )}
                    <span className="text-text-muted">·</span>
                    <span className="text-text-muted">
                      {new Date(exp.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <div
                  className="flex shrink-0 items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Compare checkbox — completed experiments only */}
                  {exp.status === "completed" && compareSet && onToggleCompare && (
                    <label
                      className="flex items-center gap-1 cursor-pointer"
                      title="Select for comparison"
                    >
                      <input
                        type="checkbox"
                        checked={compareSet.has(exp.id)}
                        onChange={() => onToggleCompare(exp.id)}
                        className="h-3.5 w-3.5 rounded border-border bg-elevated accent-accent cursor-pointer"
                      />
                      <span className="text-2xs text-text-muted">Compare</span>
                    </label>
                  )}
                  {confirmDeleteId === exp.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleDelete(exp.id)}
                        disabled={deleting}
                        className="rounded-lg bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/30 disabled:opacity-40"
                      >
                        {deleting ? "..." : "Confirm"}
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
                        setConfirmDeleteId(exp.id);
                        setDeleteError(null);
                      }}
                      className="rounded-lg px-2 py-1.5 text-xs text-text-muted transition hover:text-red-400"
                      title="Delete experiment"
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
            </button>
          );
        })}
      </div>
    </div>
  );
}

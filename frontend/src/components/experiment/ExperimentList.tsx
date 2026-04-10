import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { deleteExperiment, cancelExperiment, resetExperiment, ApiError } from "../../lib/api";
import type { Experiment } from "../../lib/api";
import ExperimentRunner from "./ExperimentRunner";
import ExperimentResults from "./ExperimentResults";
import SourceVerificationPanel from "./SourceVerificationPanel";
import HumanAnnotationPanel from "./HumanAnnotationPanel";

/** Animated expand/collapse using grid-template-rows trick */
function ExpandablePanel({ open, children }: { open: boolean; children: ReactNode }) {
  const [shouldRender, setShouldRender] = useState(open);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) setShouldRender(true);
  }, [open]);

  const handleTransitionEnd = useCallback(() => {
    if (!open) setShouldRender(false);
  }, [open]);

  return (
    <div
      className="grid transition-[grid-template-rows] duration-300 ease-out"
      style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      onTransitionEnd={handleTransitionEnd}
    >
      <div ref={contentRef} className="overflow-hidden">
        <div
          className={`transition-opacity duration-200 ${
            open ? "opacity-100 delay-100" : "opacity-0"
          }`}
        >
          {shouldRender && children}
        </div>
      </div>
    </div>
  );
}

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

type TabKey = "run" | "results" | "source" | "annotations";

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

function getDefaultTab(exp: Experiment): TabKey {
  if (exp.status === "completed") return "results";
  return "run";
}

function getAvailableTabs(exp: Experiment): { key: TabKey; label: string }[] {
  if (exp.status === "completed") {
    const tabs: { key: TabKey; label: string }[] = [
      { key: "results", label: "Results" },
    ];
    if (exp.bot_config_id != null) {
      tabs.push({ key: "source", label: "Source Verification" });
    }
    tabs.push({ key: "annotations", label: "Annotations" });
    tabs.push({ key: "run", label: "Retest" });
    return tabs;
  }
  // pending, running, failed — only the runner
  return [{ key: "run", label: "Run" }];
}

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
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<Record<number, TabKey>>({});
  const [resetting, setResetting] = useState(false);

  const expandedId = selectedId;

  const handleSelect = (exp: Experiment) => {
    // Toggle: clicking the same experiment collapses it
    if (expandedId === exp.id) {
      onSelect(null as unknown as Experiment); // signal collapse
      return;
    }
    onSelect(exp);
    // Set default tab for this experiment
    setActiveTab((prev) => ({ ...prev, [exp.id]: getDefaultTab(exp) }));
  };

  const handleCancel = async (id: number) => {
    setCancelling(id);
    try {
      await cancelExperiment(projectId, id);
      onRefresh();
    } catch {
      onRefresh();
    } finally {
      setCancelling(null);
    }
  };

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

  const handleReset = async (exp: Experiment) => {
    setResetting(true);
    try {
      await resetExperiment(projectId, exp.id);
      await onRefresh();
    } catch (err) {
      setDeleteError((err as Error).message || "Failed to reset experiment");
    } finally {
      setResetting(false);
    }
  };

  const currentTab = (id: number, exp: Experiment): TabKey =>
    activeTab[id] ?? getDefaultTab(exp);

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
          const isExpanded = expandedId === exp.id;
          const tabs = getAvailableTabs(exp);
          const tab = currentTab(exp.id, exp);

          return (
            <div
              key={exp.id}
              className={`rounded-xl border transition-all duration-200 ${
                isExpanded
                  ? "border-accent/50 bg-accent/5 ring-1 ring-accent/30"
                  : "border-border bg-card hover:border-border-focus"
              }`}
            >
              {/* Row header */}
              <button
                type="button"
                onClick={() => handleSelect(exp)}
                className="w-full px-4 py-3 text-left"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {/* Expand chevron */}
                      <svg
                        className={`h-4 w-4 shrink-0 text-text-muted transition-transform duration-200 ${
                          isExpanded ? "rotate-90" : ""
                        }`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                      <p className="truncate font-medium text-text-primary">
                        {exp.name}
                      </p>
                    </div>
                    <div className="mt-1.5 ml-6 flex flex-wrap items-center gap-2 text-xs">
                      {/* Status badge */}
                      <span
                        className={`rounded-full px-2 py-0.5 ${style.bg} ${style.text} ${
                          style.pulse ? "animate-pulse" : ""
                        }`}
                      >
                        {style.label}
                      </span>
                      <span className="text-text-muted">&middot;</span>
                      <span className="text-text-secondary">{exp.model}</span>
                      {exp.test_set_name && (
                        <>
                          <span className="text-text-muted">&middot;</span>
                          <span className="text-text-secondary">
                            {exp.test_set_name}
                          </span>
                        </>
                      )}
                      {exp.approved_question_count != null && (
                        <>
                          <span className="text-text-muted">&middot;</span>
                          <span className="text-text-secondary">
                            {exp.approved_question_count} questions
                          </span>
                        </>
                      )}
                      <span className="text-text-muted">&middot;</span>
                      <span className="text-text-muted">
                        {new Date(exp.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  <div
                    className="flex shrink-0 items-center gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* Cancel button — running experiments only */}
                    {exp.status === "running" && (
                      <button
                        onClick={() => handleCancel(exp.id)}
                        disabled={cancelling === exp.id}
                        className="rounded-lg border border-red-500/30 px-2.5 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/10 disabled:opacity-40"
                      >
                        {cancelling === exp.id ? "Stopping..." : "Stop"}
                      </button>
                    )}

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

              {/* Expanded content — animated */}
              <ExpandablePanel open={isExpanded}>
                <div className="border-t border-border/40 px-4 pb-4 pt-3">
                  {/* Tab bar */}
                  {tabs.length > 1 && (
                    <div className="mb-4 flex gap-1 rounded-lg bg-elevated/50 p-1">
                      {tabs.map((t) => (
                        <button
                          key={t.key}
                          type="button"
                          onClick={() =>
                            setActiveTab((prev) => ({ ...prev, [exp.id]: t.key }))
                          }
                          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                            tab === t.key
                              ? "bg-accent text-white shadow-sm"
                              : "text-text-secondary hover:text-text-primary hover:bg-card/80"
                          }`}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Tab content */}
                  {tab === "run" && (
                    <div>
                      {/* Reset prompt for failed experiments */}
                      {exp.status === "failed" && (
                        <div className="mb-4 flex items-center justify-between rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-2.5">
                          <span className="text-xs text-red-300">
                            This experiment failed. Reset to re-run with new metrics.
                          </span>
                          <button
                            onClick={() => handleReset(exp)}
                            disabled={resetting}
                            className="rounded-lg bg-red-500/15 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/25 disabled:opacity-40"
                          >
                            {resetting ? "Resetting..." : "Reset & Re-run"}
                          </button>
                        </div>
                      )}

                      {/* Reset prompt for completed experiments (retest) */}
                      {exp.status === "completed" && (
                        <div className="mb-4 flex items-center justify-between rounded-lg border border-border/60 bg-elevated/50 px-4 py-2.5">
                          <span className="text-xs text-text-secondary">
                            Reset this experiment to re-run with different metrics or settings.
                          </span>
                          <button
                            onClick={() => handleReset(exp)}
                            disabled={resetting}
                            className="rounded-lg bg-accent/15 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/25 disabled:opacity-40"
                          >
                            {resetting ? "Resetting..." : "Reset & Re-run"}
                          </button>
                        </div>
                      )}

                      {/* Runner for pending/running experiments */}
                      {(exp.status === "pending" || exp.status === "running") && (
                        <ExperimentRunner
                          projectId={projectId}
                          experiment={exp}
                          onComplete={onRefresh}
                        />
                      )}
                    </div>
                  )}

                  {tab === "results" && exp.status === "completed" && (
                    <ExperimentResults
                      key={exp.id}
                      projectId={projectId}
                      experimentId={exp.id}
                    />
                  )}

                  {tab === "source" && exp.status === "completed" && exp.bot_config_id != null && (
                    <SourceVerificationPanel
                      key={`sv-${exp.id}`}
                      projectId={projectId}
                      experimentId={exp.id}
                    />
                  )}

                  {tab === "annotations" && exp.status === "completed" && (
                    <HumanAnnotationPanel
                      key={`ann-${exp.id}`}
                      projectId={projectId}
                      experimentId={exp.id}
                    />
                  )}
                </div>
              </ExpandablePanel>
            </div>
          );
        })}
      </div>
    </div>
  );
}

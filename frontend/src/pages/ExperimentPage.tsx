import { useState, useEffect, useCallback } from "react";
import { useProject } from "../contexts/ProjectContext";
import { fetchExperiments, resetExperiment } from "../lib/api";
import type { Experiment } from "../lib/api";
import ExperimentCreate from "../components/experiment/ExperimentCreate";
import ExperimentList from "../components/experiment/ExperimentList";
import ExperimentRunner from "../components/experiment/ExperimentRunner";
import ExperimentResults from "../components/experiment/ExperimentResults";
import ExperimentCompare from "../components/experiment/ExperimentCompare";
import ExperimentHistory from "../components/experiment/ExperimentHistory";

const MIN_COMPARE = 2;
const MAX_COMPARE = 5;

export default function ExperimentPage() {
  const { project } = useProject();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Experiment | null>(null);

  // Compare multi-select (independent of single-select)
  const [compareSet, setCompareSet] = useState<Set<number>>(new Set());
  const [comparingIds, setComparingIds] = useState<number[]>([]);

  const loadExperiments = useCallback(async () => {
    if (!project) return;
    try {
      const exps = await fetchExperiments(project.id);
      setExperiments(exps);
      // If we had a selection, refresh it from the new list
      setSelected((prev) => {
        if (!prev) return null;
        return exps.find((e) => e.id === prev.id) ?? null;
      });
    } catch (err) {
      setError((err as Error).message || "Failed to load experiments");
    }
  }, [project]);

  useEffect(() => {
    if (!project) return;
    setLoading(true);
    loadExperiments().finally(() => setLoading(false));
  }, [project, loadExperiments]);

  const handleToggleCompare = (id: number) => {
    setCompareSet((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleStartCompare = () => {
    setComparingIds(Array.from(compareSet));
  };

  const handleCloseCompare = () => {
    setComparingIds([]);
  };

  if (!project) return null;

  const compareCount = compareSet.size;
  const compareDisabled = compareCount < MIN_COMPARE || compareCount > MAX_COMPARE;
  const compareTooltip =
    compareCount < MIN_COMPARE
      ? `Select at least ${MIN_COMPARE} experiments`
      : compareCount > MAX_COMPARE
        ? `Maximum ${MAX_COMPARE} experiments`
        : `Compare ${compareCount} experiments`;

  return (
    <div className="mx-auto max-w-3xl pt-8">
      {/* Header */}
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg
            className="h-5 w-5 text-accent"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">
            Experiment
          </h1>
          <p className="text-sm text-text-secondary">
            Configure experiments and run evaluations.
          </p>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="py-12 text-center text-sm text-text-muted">
          Loading...
        </div>
      ) : (
        <div className="space-y-8">
          {/* Create form */}
          <section className="rounded-xl border border-border bg-card p-5">
            <ExperimentCreate
              projectId={project.id}
              onCreated={loadExperiments}
            />
          </section>

          {/* Compare bar — shown when any completed experiments exist */}
          {experiments.some((e) => e.status === "completed") && comparingIds.length === 0 && (
            <div className="flex items-center justify-between rounded-lg border border-border/60 bg-elevated/50 px-4 py-2.5">
              <span className="text-xs text-text-secondary">
                {compareCount > 0
                  ? `${compareCount} experiment${compareCount !== 1 ? "s" : ""} selected`
                  : "Select experiments to compare"}
              </span>
              <button
                onClick={handleStartCompare}
                disabled={compareDisabled}
                title={compareTooltip}
                className="rounded-lg bg-accent/15 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/25 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Compare Selected
              </button>
            </div>
          )}

          {/* Experiment list */}
          <section>
            <ExperimentList
              projectId={project.id}
              experiments={experiments}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              onRefresh={loadExperiments}
              compareSet={compareSet}
              onToggleCompare={handleToggleCompare}
            />
          </section>

          {/* Comparison view — replaces single results when active */}
          {comparingIds.length > 0 && (
            <section className="rounded-xl border border-accent/20 bg-card p-5">
              <ExperimentCompare
                key={comparingIds.join(",")}
                projectId={project.id}
                experimentIds={comparingIds}
                onClose={handleCloseCompare}
              />
            </section>
          )}

          {/* Runner — for pending or failed experiments, and not during comparison */}
          {comparingIds.length === 0 &&
            selected &&
            (selected.status === "pending" || selected.status === "failed") && (
              <section className="rounded-xl border border-accent/30 bg-accent/5 p-5">
                {selected.status === "failed" && (
                  <div className="mb-4 flex items-center justify-between rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-2.5">
                    <span className="text-xs text-red-300">
                      This experiment failed. Reset to re-run with new metrics.
                    </span>
                    <button
                      onClick={async () => {
                        try {
                          await resetExperiment(project.id, selected.id);
                          await loadExperiments();
                        } catch (err) {
                          setError((err as Error).message || "Failed to reset experiment");
                        }
                      }}
                      className="rounded-lg bg-red-500/15 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/25"
                    >
                      Reset & Re-run
                    </button>
                  </div>
                )}
                {selected.status === "pending" && (
                  <ExperimentRunner
                    projectId={project.id}
                    experiment={selected}
                    onComplete={loadExperiments}
                  />
                )}
              </section>
            )}

          {/* Results — only for completed experiments, and not during comparison */}
          {comparingIds.length === 0 &&
            selected &&
            selected.status === "completed" && (
              <section className="rounded-xl border border-accent/20 bg-card p-5">
                <ExperimentResults
                  key={selected.id}
                  projectId={project.id}
                  experimentId={selected.id}
                />
              </section>
            )}

          {/* History — collapsible section at bottom */}
          <ExperimentHistory projectId={project.id} />
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { useProject } from "../contexts/ProjectContext";
import { fetchExperiments } from "../lib/api";
import type { Experiment } from "../lib/api";
import ExperimentSuggestions from "../components/experiment/ExperimentSuggestions";
import ExperimentDelta from "../components/experiment/ExperimentDelta";
import ExperimentResults from "../components/experiment/ExperimentResults";

export default function AnalyzePage() {
  const { project } = useProject();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const loadExperiments = useCallback(async () => {
    if (!project) return;
    try {
      const exps = await fetchExperiments(project.id);
      setExperiments(exps.filter((e) => e.status === "completed"));
    } catch {
      // Silently handle — empty list shown
    }
  }, [project]);

  useEffect(() => {
    if (!project) return;
    setLoading(true);
    loadExperiments().finally(() => setLoading(false));
  }, [project, loadExperiments]);

  if (!project) return null;

  const selected = experiments.find((e) => e.id === selectedId) ?? null;

  return (
    <div className="mx-auto max-w-3xl pt-8 xl:max-w-5xl">
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
              d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Analyze</h1>
          <p className="text-sm text-text-secondary">
            Review results, get suggestions, and iterate on your pipeline.
          </p>
        </div>
      </div>

      {/* Loading */}
      {loading ? (
        <div className="py-12 text-center text-sm text-text-muted">
          Loading...
        </div>
      ) : experiments.length === 0 ? (
        /* No completed experiments */
        <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
          <p className="text-sm text-text-muted">
            No completed experiments yet. Run an experiment first.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Experiment selector */}
          <section>
            <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-text-secondary">
              Select experiment
            </label>
            <select
              value={selectedId ?? ""}
              onChange={(e) =>
                setSelectedId(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full rounded-xl border border-border bg-card px-4 py-3 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              <option value="">Choose a completed experiment...</option>
              {experiments.map((exp) => (
                <option key={exp.id} value={exp.id}>
                  {exp.name}
                  {exp.rag_config_name ? ` — ${exp.rag_config_name}` : ""}
                  {exp.completed_at
                    ? ` (${new Date(exp.completed_at).toLocaleDateString()})`
                    : ""}
                </option>
              ))}
            </select>
          </section>

          {/* No selection */}
          {!selected && (
            <div className="rounded-xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
              <p className="text-sm text-text-muted">
                Select a completed experiment to analyze.
              </p>
            </div>
          )}

          {/* Selected experiment sections */}
          {selected && (
            <>
              {/* Suggestions */}
              <section className="rounded-xl border border-border bg-card p-5">
                <ExperimentSuggestions
                  key={`suggestions-${selected.id}`}
                  projectId={project.id}
                  experimentId={selected.id}
                  onExperimentCreated={loadExperiments}
                />
              </section>

              {/* Delta comparison */}
              <section className="rounded-xl border border-border bg-card p-5">
                <ExperimentDelta
                  key={`delta-${selected.id}`}
                  projectId={project.id}
                  experimentId={selected.id}
                />
              </section>

              {/* Results with export */}
              <section className="rounded-xl border border-accent/20 bg-card p-5">
                <ExperimentResults
                  key={selected.id}
                  projectId={project.id}
                  experimentId={selected.id}
                />
              </section>
            </>
          )}
        </div>
      )}
    </div>
  );
}

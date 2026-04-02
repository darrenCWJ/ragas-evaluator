import { useState, useEffect } from "react";
import {
  fetchTestSets,
  fetchRagConfigsExpanded,
  fetchRagConfigs,
  createExperiment,
} from "../../lib/api";
import type { TestSet, RagConfigExpanded } from "../../lib/api";

interface Props {
  projectId: number;
  onCreated: () => void;
}

export default function ExperimentCreate({ projectId, onCreated }: Props) {
  const [testSets, setTestSets] = useState<TestSet[]>([]);
  const [ragConfigs, setRagConfigs] = useState<RagConfigExpanded[]>([]);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [testSetId, setTestSetId] = useState<number | "">("");
  const [ragConfigId, setRagConfigId] = useState<number | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    setLoading(true);
    const loadRagConfigs = fetchRagConfigsExpanded(projectId).catch(() =>
      fetchRagConfigs(projectId).then((basics) =>
        basics.map((rc) => ({ ...rc, chunk_config: null, embedding_config: null }))
      )
    );
    Promise.all([fetchTestSets(projectId), loadRagConfigs])
      .then(([ts, rc]) => {
        // Only show test sets with approved questions
        setTestSets(ts.filter((t) => t.approved_count > 0));
        setRagConfigs(rc);
      })
      .catch(() => {
        // Supplementary load — page-level error handles API failures
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  const nameValid = name.trim().length > 0;
  const testSetValid = testSetId !== "";
  const ragConfigValid = ragConfigId !== "";
  const canSubmit = nameValid && testSetValid && ragConfigValid && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!canSubmit) return;

    setSubmitting(true);
    setError(null);
    try {
      await createExperiment(projectId, {
        name: name.trim(),
        test_set_id: testSetId as number,
        rag_config_id: ragConfigId as number,
      });
      setName("");
      setTestSetId("");
      setRagConfigId("");
      setTouched(false);
      onCreated();
    } catch (err) {
      setError((err as Error).message || "Failed to create experiment");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="py-6 text-center text-sm text-text-muted">
        Loading configurations...
      </div>
    );
  }

  const noPrereqs = testSets.length === 0 || ragConfigs.length === 0;

  return (
    <div>
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-text-secondary">
        New Experiment
      </h3>

      {noPrereqs && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
          {testSets.length === 0 && (
            <p>No test sets with approved questions. Complete the Test stage first.</p>
          )}
          {ragConfigs.length === 0 && (
            <p>No RAG configs found. Complete the Build stage first.</p>
          )}
        </div>
      )}

      {!noPrereqs && (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Experiment Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Baseline GPT-4o mini"
              className={`w-full rounded-lg border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 ${
                touched && !nameValid
                  ? "border-red-500/50 focus:ring-red-500/50"
                  : "border-border focus:ring-accent"
              }`}
            />
            {touched && !nameValid && (
              <p className="mt-1 text-xs text-red-400">Name is required</p>
            )}
          </div>

          {/* Test Set */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Test Set
            </label>
            <select
              value={testSetId}
              onChange={(e) =>
                setTestSetId(e.target.value ? Number(e.target.value) : "")
              }
              className={`w-full rounded-lg border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 ${
                touched && !testSetValid
                  ? "border-red-500/50 focus:ring-red-500/50"
                  : "border-border focus:ring-accent"
              }`}
            >
              <option value="">Select test set...</option>
              {testSets.map((ts) => (
                <option key={ts.id} value={ts.id}>
                  {ts.name} ({ts.approved_count} approved)
                </option>
              ))}
            </select>
            {touched && !testSetValid && (
              <p className="mt-1 text-xs text-red-400">Test set is required</p>
            )}
          </div>

          {/* RAG Config */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              RAG Configuration
            </label>
            <select
              value={ragConfigId}
              onChange={(e) =>
                setRagConfigId(e.target.value ? Number(e.target.value) : "")
              }
              className={`w-full rounded-lg border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 ${
                touched && !ragConfigValid
                  ? "border-red-500/50 focus:ring-red-500/50"
                  : "border-border focus:ring-accent"
              }`}
            >
              <option value="">Select RAG config...</option>
              {ragConfigs.map((rc) => (
                <option key={rc.id} value={rc.id}>
                  {rc.name} ({rc.llm_model})
                </option>
              ))}
            </select>
            {touched && !ragConfigValid && (
              <p className="mt-1 text-xs text-red-400">
                RAG configuration is required
              </p>
            )}
            {ragConfigId !== "" && (() => {
              const selected = ragConfigs.find((rc) => rc.id === ragConfigId);
              if (!selected || (!selected.chunk_config && !selected.embedding_config)) return null;
              return (
                <div className="mt-2 rounded-lg border border-border/50 bg-card/40 px-3 py-2 text-xs text-text-muted">
                  {selected.chunk_config && (
                    <p><span className="text-text-secondary">Chunk:</span> {selected.chunk_config.name} ({selected.chunk_config.method})</p>
                  )}
                  {selected.embedding_config && (
                    <p><span className="text-text-secondary">Embedding:</span> {selected.embedding_config.name} ({selected.embedding_config.model_name})</p>
                  )}
                  <p><span className="text-text-secondary">LLM:</span> {selected.llm_model} | Search: {selected.search_type} | Top K: {selected.top_k}</p>
                </div>
              );
            })()}
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Creating..." : "Create Experiment"}
          </button>
        </form>
      )}
    </div>
  );
}

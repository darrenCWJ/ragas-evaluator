import { useState, useEffect, useCallback } from "react";
import { useProject } from "../contexts/ProjectContext";
import { fetchTestSets, fetchChunkConfigs } from "../lib/api";
import type { TestSet, ChunkConfig } from "../lib/api";
import TestSetGenerate from "../components/test/TestSetGenerate";
import TestSetUpload from "../components/test/TestSetUpload";
import TestSetList from "../components/test/TestSetList";
import QuestionList from "../components/test/QuestionList";
import Card from "../components/ui/Card";

export default function TestPage() {
  const { project } = useProject();
  const [testSets, setTestSets] = useState<TestSet[]>([]);
  const [chunkConfigs, setChunkConfigs] = useState<ChunkConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTestSet, setSelectedTestSet] = useState<TestSet | null>(null);

  const loadTestSets = useCallback(async () => {
    if (!project) return;
    try {
      const ts = await fetchTestSets(project.id);
      setTestSets(ts);
    } catch (err) {
      setError((err as Error).message || "Failed to load test sets");
    }
  }, [project]);

  const loadChunkConfigs = useCallback(async () => {
    if (!project) return;
    try {
      const cc = await fetchChunkConfigs(project.id);
      setChunkConfigs(cc);
    } catch {
      // chunk configs are supplementary for the form
    }
  }, [project]);

  useEffect(() => {
    if (!project) return;
    setLoading(true);
    Promise.all([loadTestSets(), loadChunkConfigs()]).finally(() =>
      setLoading(false),
    );
  }, [project, loadTestSets, loadChunkConfigs]);

  if (!project) return null;

  // Question view
  if (selectedTestSet) {
    return (
      <div className="mx-auto max-w-3xl pt-8">
        <QuestionList
          projectId={project.id}
          testSet={selectedTestSet}
          onBack={() => { setSelectedTestSet(null); loadTestSets(); }}
        />
      </div>
    );
  }

  // Default view: generate + list
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
              d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Test</h1>
          <p className="text-sm text-text-secondary">
            Generate test sets and browse questions.
          </p>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Card variant="error" padding="md" className="mb-4">
          {error}
        </Card>
      )}

      {/* Loading */}
      {loading ? (
        <div className="py-12 text-center text-sm text-text-muted">
          Loading…
        </div>
      ) : (
        <div className="space-y-8">
          {/* Upload custom Q&A */}
          <Card padding="lg" className="p-5">
            <TestSetUpload
              projectId={project.id}
              onTestSetCreated={loadTestSets}
            />
          </Card>

          {/* Generation form */}
          <Card padding="lg" className="p-5">
            <TestSetGenerate
              projectId={project.id}
              chunkConfigs={chunkConfigs}
              onTestSetCreated={loadTestSets}
            />
          </Card>

          {/* Test set list */}
          <section>
            <TestSetList
              projectId={project.id}
              testSets={testSets}
              onTestSetsChanged={loadTestSets}
              onSelectTestSet={setSelectedTestSet}
            />
          </section>
        </div>
      )}
    </div>
  );
}

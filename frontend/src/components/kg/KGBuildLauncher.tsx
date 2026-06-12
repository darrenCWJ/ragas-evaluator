import { useEffect, useState } from 'react';
import { buildKnowledgeGraph, fetchChunkConfigs, fetchProjects } from '../../api';
import type { ChunkConfig, Project } from '../../api';
import { Button, ErrorAlert, FormField, Select } from '../ui';

interface KGBuildLauncherProps {
  /** Called after a build is accepted so the list can start polling. */
  onStarted: () => void;
}

type KGSource = 'documents' | 'chunks';

/**
 * Build a knowledge graph straight from the KG Explorer — pick a project and
 * source; the main app runs the build locally or delegates it to a worker.
 */
export default function KGBuildLauncher({ onStarted }: KGBuildLauncherProps) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | ''>('');
  const [source, setSource] = useState<KGSource>('documents');
  const [chunkConfigs, setChunkConfigs] = useState<ChunkConfig[]>([]);
  const [chunkConfigId, setChunkConfigId] = useState<number | ''>('');
  const [fastMode, setFastMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    fetchProjects()
      .then(setProjects)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load projects'));
  }, [open]);

  useEffect(() => {
    setChunkConfigs([]);
    setChunkConfigId('');
    if (projectId === '' || source !== 'chunks') return;
    fetchChunkConfigs(projectId)
      .then(setChunkConfigs)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load chunk configs'),
      );
  }, [projectId, source]);

  const canBuild =
    projectId !== '' && (source === 'documents' || chunkConfigId !== '') && !submitting;

  const handleBuild = async () => {
    if (projectId === '') return;
    setSubmitting(true);
    setError(null);
    try {
      await buildKnowledgeGraph(
        projectId,
        source === 'chunks' && chunkConfigId !== '' ? chunkConfigId : null,
        500,
        source,
        fastMode,
      );
      setOpen(false);
      onStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the build');
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <div className="mb-6 flex justify-end">
        <Button onClick={() => setOpen(true)}>Build knowledge graph</Button>
      </div>
    );
  }

  return (
    <div className="mb-6 space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-text-primary">Build a knowledge graph</h2>
        <button
          type="button"
          className="text-xs text-text-muted hover:text-text-secondary"
          onClick={() => setOpen(false)}
        >
          Close
        </button>
      </div>
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      <div className="grid gap-3 sm:grid-cols-3">
        <FormField label="Project">
          <Select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select a project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField
          label="Source"
          hint={source === 'documents' ? 'Full documents as nodes' : 'Uses a chunking strategy'}
        >
          <Select value={source} onChange={(e) => setSource(e.target.value as KGSource)}>
            <option value="documents">Documents</option>
            <option value="chunks">Chunks</option>
          </Select>
        </FormField>
        {source === 'chunks' && (
          <FormField label="Chunk config">
            <Select
              value={chunkConfigId}
              onChange={(e) => setChunkConfigId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select a chunk config...</option>
              {chunkConfigs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}
      </div>

      <div className="flex items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            className="accent-accent"
            checked={fastMode}
            onChange={(e) => setFastMode(e.target.checked)}
          />
          Fast mode (fewer extraction passes)
        </label>
        <Button onClick={handleBuild} loading={submitting} disabled={!canBuild}>
          Start build
        </Button>
      </div>
    </div>
  );
}

import type { ChunkConfig, KnowledgeGraphInfo } from '../../../lib/api';
import { KgSourceInfoCard } from './KGBuildPanel';

interface SourceFieldsProps {
  chunkConfigs: ChunkConfig[];
  generating: boolean;
  useKgAsSource: boolean;
  setUseKgAsSource: (value: boolean) => void;
  chunkConfigId: number | '';
  setChunkConfigId: (value: number | '') => void;
  useGraphRag: boolean;
  graphRagKgSource: 'chunks' | 'documents';
  kgInfo: KnowledgeGraphInfo | null;
  name: string;
  setName: (value: string) => void;
  testsetSize: string;
  setTestsetSize: (value: string) => void;
  validateSize: (value: string) => boolean;
  sizeError: string | null;
  chunkSampleSize: string;
  setChunkSampleSize: (value: string) => void;
  numWorkers: number;
  setNumWorkers: (value: number) => void;
}

/**
 * Basic generation inputs: source selector, chunk config, name, test set
 * size, chunk/node sample size, and parallel workers.
 *
 * Rendered as grid cells inside the parent's two-column grid.
 */
export default function SourceFields({
  chunkConfigs,
  generating,
  useKgAsSource,
  setUseKgAsSource,
  chunkConfigId,
  setChunkConfigId,
  useGraphRag,
  graphRagKgSource,
  kgInfo,
  name,
  setName,
  testsetSize,
  setTestsetSize,
  validateSize,
  sizeError,
  chunkSampleSize,
  setChunkSampleSize,
  numWorkers,
  setNumWorkers,
}: SourceFieldsProps) {
  return (
    <>
      {/* Source selector */}
      <div className="sm:col-span-2">
        <label className="mb-1.5 block text-xs font-medium text-text-secondary">Source</label>
        <div className="flex overflow-hidden rounded-lg border border-border">
          {(['chunks', 'knowledge_graph'] as const).map((src) => {
            const active = src === (useKgAsSource ? 'knowledge_graph' : 'chunks');
            return (
              <button
                key={src}
                type="button"
                onClick={() => setUseKgAsSource(src === 'knowledge_graph')}
                disabled={generating}
                className={`flex-1 py-1.5 text-xs font-medium transition ${
                  active
                    ? 'bg-accent/15 text-accent'
                    : 'text-text-muted hover:bg-elevated hover:text-text-secondary'
                }`}
              >
                {src === 'chunks' ? 'Chunk Config' : 'Knowledge Graph'}
              </button>
            );
          })}
        </div>
      </div>

      {/* Chunk config selector — hidden when KG is source */}
      {!useKgAsSource && (
        <div className="sm:col-span-2">
          <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
            Chunk Config
            {useGraphRag && graphRagKgSource === 'documents' && (
              <span className="text-[10px] text-text-muted">
                (optional — not needed for Graph RAG Documents only)
              </span>
            )}
          </label>
          <select
            value={chunkConfigId}
            onChange={(e) => setChunkConfigId(e.target.value ? Number(e.target.value) : '')}
            className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            disabled={generating}
          >
            <option value="">Select a chunk config…</option>
            {chunkConfigs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.method})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* KG info card — shown when KG is source */}
      {useKgAsSource && <KgSourceInfoCard kgInfo={kgInfo} />}

      {/* Name */}
      <div className="sm:col-span-2">
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          Name <span className="font-normal text-text-muted">(optional)</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Auto-generated if blank"
          className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          disabled={generating}
        />
      </div>

      {/* Test set size */}
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">Test Set Size</label>
        <input
          type="number"
          min={1}
          max={400}
          value={testsetSize}
          onChange={(e) => {
            setTestsetSize(e.target.value);
            validateSize(e.target.value);
          }}
          className={`w-full rounded-lg border px-3 py-2 text-sm text-text-primary focus:outline-none ${
            sizeError
              ? 'border-red-500 focus:border-red-500'
              : 'border-border bg-input focus:border-accent'
          }`}
          disabled={generating}
        />
        {sizeError && <p className="mt-1 text-xs text-red-400">{sizeError}</p>}
      </div>

      {/* Chunk / node sample size */}
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          {useKgAsSource ? 'Node Sample Size' : 'Chunk Sample Size'}
        </label>
        <input
          type="number"
          min={0}
          value={chunkSampleSize}
          onChange={(e) => setChunkSampleSize(e.target.value)}
          className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
          disabled={generating}
        />
        <p className="mt-1 text-xs text-text-muted">
          {useKgAsSource
            ? 'Random subset of KG nodes to use. 0 = all nodes.'
            : 'Random subset of chunks to use. 0 = all chunks.'}
        </p>
      </div>

      {/* Parallel workers */}
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          Parallel Workers
        </label>
        <select
          value={numWorkers}
          onChange={(e) => setNumWorkers(Number(e.target.value))}
          className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
          disabled={generating}
        >
          {[1, 2, 4, 6, 8].map((n) => (
            <option key={n} value={n}>
              {n} {n === 1 ? 'worker' : 'workers'}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-text-muted">
          More workers = faster generation. Increase for large test sets.
        </p>
      </div>
    </>
  );
}

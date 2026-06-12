import type { Dispatch, SetStateAction } from 'react';
import type { KnowledgeGraphInfo } from '../../../lib/api';
import { GRAPH_RAG_CATEGORIES } from './constants';
import DistributionSliders from './DistributionSliders';
import { DocKgStatusRow } from './KGBuildPanel';

interface GraphRagSectionProps {
  projectId: number;
  generating: boolean;
  useGraphRag: boolean;
  setUseGraphRag: (value: boolean) => void;
  graphRagKgSource: 'chunks' | 'documents';
  setGraphRagKgSource: (value: 'chunks' | 'documents') => void;
  kgInfo: KnowledgeGraphInfo | null;
  docKgInfo: KnowledgeGraphInfo | null;
  docKgBuilding: boolean;
  setDocKgBuilding: (building: boolean) => void;
  loadDocKgInfo: () => void;
  overlapMaxNodes: number | null;
  enabledGraphRag: Record<string, boolean>;
  setEnabledGraphRag: (next: Record<string, boolean>) => void;
  graphRagDistribution: Record<string, number>;
  setGraphRagDistribution: Dispatch<SetStateAction<Record<string, number>>>;
}

/**
 * Graph RAG question-type controls: enable toggle, KG source selector,
 * document KG status, and bridge/comparative/community sliders.
 *
 * Rendered as grid cells inside the parent's two-column grid.
 */
export default function GraphRagSection({
  projectId,
  generating,
  useGraphRag,
  setUseGraphRag,
  graphRagKgSource,
  setGraphRagKgSource,
  kgInfo,
  docKgInfo,
  docKgBuilding,
  setDocKgBuilding,
  loadDocKgInfo,
  overlapMaxNodes,
  enabledGraphRag,
  setEnabledGraphRag,
  graphRagDistribution,
  setGraphRagDistribution,
}: GraphRagSectionProps) {
  return (
    <>
      {/* Graph RAG question types toggle */}
      <div className="sm:col-span-2 flex items-end gap-3 pb-1">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={useGraphRag}
            onChange={(e) => setUseGraphRag(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
            disabled={generating}
          />
          Graph RAG Question Types
        </label>
      </div>

      {/* Graph RAG config */}
      {useGraphRag && (
        <div className="sm:col-span-2 space-y-3 rounded-lg border border-border bg-elevated/50 p-3">
          <p className="text-xs text-text-muted">
            Generate relationship-aware questions using the knowledge graph. All types require a
            built KG.
          </p>

          {/* KG Source selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">KG Source:</span>
            <div className="flex rounded-md border border-border overflow-hidden text-xs">
              {(['chunks', 'documents'] as const).map((src) => (
                <button
                  key={src}
                  type="button"
                  onClick={() => {
                    setGraphRagKgSource(src);
                    if (src === 'documents') loadDocKgInfo();
                  }}
                  disabled={generating}
                  className={`px-3 py-1 capitalize transition ${
                    graphRagKgSource === src
                      ? 'bg-accent text-white'
                      : 'bg-elevated text-text-secondary hover:bg-elevated/80'
                  }`}
                >
                  {src}
                </button>
              ))}
            </div>
          </div>

          {/* Document KG status (shown only when Documents source selected) */}
          {graphRagKgSource === 'documents' && (
            <DocKgStatusRow
              projectId={projectId}
              generating={generating}
              docKgInfo={docKgInfo}
              docKgBuilding={docKgBuilding}
              setDocKgBuilding={setDocKgBuilding}
              loadDocKgInfo={loadDocKgInfo}
              overlapMaxNodes={overlapMaxNodes}
            />
          )}

          {/* Chunk KG warning when chunks source and no KG */}
          {graphRagKgSource === 'chunks' && kgInfo && !kgInfo.exists && (
            <p className="text-xs text-amber-400">
              No knowledge graph found — build one in the KG section above before using Graph RAG
              types.
            </p>
          )}
          <DistributionSliders
            categories={GRAPH_RAG_CATEGORIES}
            distribution={graphRagDistribution}
            setDistribution={setGraphRagDistribution}
            enabled={enabledGraphRag}
            setEnabled={setEnabledGraphRag}
            disabled={generating}
          />
        </div>
      )}
    </>
  );
}

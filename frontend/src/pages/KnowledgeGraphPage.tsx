import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchAllKnowledgeGraphs,
  streamKnowledgeGraphData,
} from "../lib/api";
import type { KGListItem, KGGraphData, KGGraphNode, KGGraphEdge } from "../lib/api";
import KGCard from "../components/kg/KGCard";
import KGGraphView from "../components/kg/KGGraphView";
import Card from "../components/ui/Card";

export default function KnowledgeGraphPage() {
  const [kgs, setKgs] = useState<KGListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Graph view state
  const [selectedKg, setSelectedKg] = useState<KGListItem | null>(null);
  const [graphData, setGraphData] = useState<KGGraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [streamProgress, setStreamProgress] = useState<{
    loadedNodes: number;
    loadedEdges: number;
    totalNodes: number;
    totalEdges: number;
  } | null>(null);

  const cancelStreamRef = useRef<(() => void) | null>(null);

  const loadKgs = useCallback(async () => {
    try {
      setError(null);
      const list = await fetchAllKnowledgeGraphs();
      setKgs(list);
    } catch (err) {
      setError((err as Error).message || "Failed to load knowledge graphs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKgs();
  }, [loadKgs]);

  const handleSelect = useCallback((kg: KGListItem) => {
    setSelectedKg(kg);
    setGraphLoading(true);
    setGraphData(null);
    setStreamProgress(null);

    const nodesAcc: KGGraphNode[] = [];
    const edgesAcc: KGGraphEdge[] = [];
    let isComplete = false;

    const cancel = streamKnowledgeGraphData(kg.project_id, {
      onMeta: (meta) => {
        isComplete = meta.is_complete;
        setStreamProgress({
          loadedNodes: 0,
          loadedEdges: 0,
          totalNodes: meta.total_nodes,
          totalEdges: meta.total_edges,
        });
      },
      onNodes: (batch) => {
        nodesAcc.push(...batch);
        setStreamProgress((prev) =>
          prev ? { ...prev, loadedNodes: nodesAcc.length } : prev,
        );
      },
      onEdges: (batch) => {
        edgesAcc.push(...batch);
        setStreamProgress((prev) =>
          prev ? { ...prev, loadedEdges: edgesAcc.length } : prev,
        );
      },
      onDone: () => {
        setGraphData({
          nodes: nodesAcc,
          edges: edgesAcc,
          is_complete: isComplete,
        });
        setGraphLoading(false);
        setStreamProgress(null);
      },
      onError: (msg) => {
        setError(msg);
        setSelectedKg(null);
        setGraphLoading(false);
        setStreamProgress(null);
      },
    });

    cancelStreamRef.current = cancel;
  }, []);

  const handleBack = useCallback(() => {
    cancelStreamRef.current?.();
    cancelStreamRef.current = null;
    setSelectedKg(null);
    setGraphData(null);
    setStreamProgress(null);
    setGraphLoading(false);
  }, []);

  // Graph view — full screen
  if (selectedKg && graphData) {
    return (
      <div className="fixed inset-0 z-30 flex flex-col bg-deep">
        <KGGraphView
          data={graphData}
          projectName={selectedKg.project_name}
          onBack={handleBack}
        />
      </div>
    );
  }

  // Loading graph with streaming progress
  if (selectedKg && graphLoading) {
    return (
      <div className="fixed inset-0 z-30 flex items-center justify-center bg-deep">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-text-secondary">
            Loading graph for <span className="text-text-primary font-medium">{selectedKg.project_name}</span>
          </p>
          {streamProgress && (
            <div className="flex items-center gap-4 text-micro text-text-muted font-mono">
              <span>
                {streamProgress.loadedNodes.toLocaleString()}/{streamProgress.totalNodes.toLocaleString()} nodes
              </span>
              <span className="text-border">|</span>
              <span>
                {streamProgress.loadedEdges.toLocaleString()}/{streamProgress.totalEdges.toLocaleString()} edges
              </span>
            </div>
          )}
          {streamProgress && streamProgress.totalNodes > 0 && (
            <div className="w-48 h-1 rounded-full bg-elevated overflow-hidden">
              <div
                className="h-full bg-accent transition-all duration-300 rounded-full"
                style={{
                  width: `${Math.round(
                    ((streamProgress.loadedNodes + streamProgress.loadedEdges) /
                      (streamProgress.totalNodes + streamProgress.totalEdges)) *
                      100,
                  )}%`,
                }}
              />
            </div>
          )}
          <button
            onClick={handleBack}
            className="mt-2 text-micro text-text-muted hover:text-text-secondary transition"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // List view
  return (
    <div className="mx-auto max-w-4xl pt-8">
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
              d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">
            Knowledge Graphs
          </h1>
          <p className="text-sm text-text-secondary">
            Browse and explore saved knowledge graphs across projects.
          </p>
        </div>
      </div>

      {/* Error */}
      {error && (
        <Card variant="error" padding="md" className="mb-6">
          {error}
        </Card>
      )}

      {/* Loading */}
      {loading ? (
        <div className="py-16 text-center">
          <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="mt-3 text-sm text-text-muted">Loading knowledge graphs...</p>
        </div>
      ) : kgs.length === 0 ? (
        /* Empty state */
        <Card padding="lg" className="py-16 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-card border border-border mb-4">
            <svg
              className="h-7 w-7 text-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z"
              />
            </svg>
          </div>
          <h3 className="text-sm font-medium text-text-primary mb-1">
            No knowledge graphs yet
          </h3>
          <p className="text-micro text-text-muted max-w-xs mx-auto">
            Build a knowledge graph from the Test page to see it here.
          </p>
        </Card>
      ) : (
        /* KG grid */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {kgs.map((kg) => (
            <KGCard key={kg.id} kg={kg} onSelect={handleSelect} onRefresh={loadKgs} />
          ))}
        </div>
      )}
    </div>
  );
}

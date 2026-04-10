import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Graph from "graphology";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSigma,
  useSetSettings,
} from "@react-sigma/core";
import "@react-sigma/core/lib/style.css";
import louvain from "graphology-communities-louvain";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import type { KGGraphData, KGGraphNode } from "../../lib/api";
import KGNodeDetail from "./KGNodeDetail";

// ── Types ──────────────────────────────────────────────────────────────────

interface KGGraphViewProps {
  data: KGGraphData;
  projectName: string;
  onBack: () => void;
}

interface Filters {
  showDocuments: boolean;
  showChunks: boolean;
  edgeScoreMin: number;
  selectedCommunities: Set<number>;
  search: string;
  clusterView: boolean;
}

// ── Color palette for communities ──────────────────────────────────────────

const COMMUNITY_COLORS = [
  "#818cf8", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7",
  "#ec4899", "#14b8a6", "#f97316", "#8b5cf6", "#10b981", "#3b82f6",
  "#e11d48", "#84cc16", "#6366f1", "#d946ef",
];

function communityColor(community: number): string {
  return COMMUNITY_COLORS[community % COMMUNITY_COLORS.length] ?? "#5a6a84";
}

// Semantic zoom thresholds
const CLUSTER_ZOOM_OUT_RATIO = 1.5; // zoom out past this → cluster view
const CLUSTER_ZOOM_IN_RATIO = 0.8;  // zoom in past this → detail view

// ── Build graph structure only (no Louvain, no layout) ─────────────────────

function buildGraphStructure(data: KGGraphData): Graph {
  const graph = new Graph({ multi: false, type: "undirected" });

  const n = data.nodes.length;
  for (let i = 0; i < n; i++) {
    const node = data.nodes[i]!;
    if (graph.hasNode(node.id)) continue;
    const angle = (2 * Math.PI * i) / n;
    const r = Math.sqrt(n) * 5;
    graph.addNode(node.id, {
      label: node.label,
      nodeType: node.type,
      keyphrases: node.keyphrases,
      size: node.type === "document"
        ? Math.max(6, Math.min(16, (node.keyphrases.length || 1) * 2.5))
        : Math.max(3, Math.min(8, (node.keyphrases.length || 1) * 1.5)),
      color: node.type === "document" ? "#22c55e" : "#818cf8",
      x: Math.cos(angle) * r,
      y: Math.sin(angle) * r,
    });
  }

  for (const edge of data.edges) {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
      const edgeKey = [edge.source, edge.target].sort().join("--");
      if (!graph.hasEdge(edgeKey)) {
        graph.addEdgeWithKey(edgeKey, edge.source, edge.target, {
          weight: edge.score,
          score: edge.score,
          edgeType: edge.type,
          size: Math.max(0.3, edge.score * 1.5),
          color: "#283348",
        });
      }
    }
  }

  return graph;
}

// ── Run Louvain and color nodes by community ───────────────────────────────

function applyCommunities(graph: Graph): {
  communityCount: number;
  communities: Map<number, string[]>;
} {
  let communityCount = 0;
  const communitiesMap = new Map<number, string[]>();

  if (graph.order > 0 && graph.size > 0) {
    louvain.assign(graph, { nodeCommunityAttribute: "community" });

    graph.forEachNode((nodeId, attrs) => {
      const c = attrs.community as number;
      if (c >= communityCount) communityCount = c + 1;
      const list = communitiesMap.get(c) || [];
      list.push(nodeId);
      communitiesMap.set(c, list);
      graph.setNodeAttribute(nodeId, "color", communityColor(c));
    });
  }

  return { communityCount, communities: communitiesMap };
}

// ── Build a cluster-view graph (super-nodes) ───────────────────────────────

function buildClusterGraph(
  sourceGraph: Graph,
  communities: Map<number, string[]>,
): Graph {
  const clusterGraph = new Graph({ multi: false, type: "undirected" });

  for (const [communityId, memberIds] of communities.entries()) {
    const allKeyphrases: Record<string, number> = {};
    let cx = 0;
    let cy = 0;

    for (const nid of memberIds) {
      if (!sourceGraph.hasNode(nid)) continue;
      const attrs = sourceGraph.getNodeAttributes(nid);
      cx += (attrs.x as number) || 0;
      cy += (attrs.y as number) || 0;
      const kps = attrs.keyphrases as string[];
      if (kps) {
        for (const kp of kps) {
          allKeyphrases[kp] = (allKeyphrases[kp] || 0) + 1;
        }
      }
    }

    const topEntry = Object.entries(allKeyphrases)
      .sort((a, b) => b[1] - a[1])[0];
    const label = topEntry
      ? `${topEntry[0]} (${memberIds.length})`
      : `Cluster ${communityId} (${memberIds.length})`;

    clusterGraph.addNode(String(communityId), {
      label,
      nodeType: "cluster",
      size: Math.max(8, Math.min(30, Math.sqrt(memberIds.length) * 5)),
      color: communityColor(communityId),
      x: cx / memberIds.length,
      y: cy / memberIds.length,
      community: communityId,
      memberCount: memberIds.length,
    });
  }

  const interEdges = new Map<string, { weight: number; count: number }>();
  sourceGraph.forEachEdge((_edgeKey, edgeAttrs, source, target) => {
    const sc = sourceGraph.getNodeAttribute(source, "community") as number;
    const tc = sourceGraph.getNodeAttribute(target, "community") as number;
    if (sc === tc) return;
    const key = [Math.min(sc, tc), Math.max(sc, tc)].join("--");
    const existing = interEdges.get(key);
    const w = (edgeAttrs.score as number) || 0.5;
    if (existing) {
      existing.weight += w;
      existing.count += 1;
    } else {
      interEdges.set(key, { weight: w, count: 1 });
    }
  });

  for (const [key, { weight, count }] of interEdges.entries()) {
    const [src, tgt] = key.split("--");
    if (src && tgt && clusterGraph.hasNode(src) && clusterGraph.hasNode(tgt)) {
      clusterGraph.addEdgeWithKey(key, src, tgt, {
        weight: weight / count,
        score: weight / count,
        size: Math.max(1, Math.min(5, count * 0.5)),
        color: "#3a4a66",
        edgeType: "cluster",
      });
    }
  }

  return clusterGraph;
}

// ── Precompute lookup tables for fast rendering ───────────────────────────

interface GraphLookups {
  /** edge key → [source, target] */
  edgeEndpoints: Map<string, [string, string]>;
  /** node id → Set of neighbor node ids */
  adjacency: Map<string, Set<string>>;
  /** Set of all chunk node ids */
  chunkNodes: Set<string>;
  /** node id → Set of edge keys it participates in */
  nodeEdges: Map<string, Set<string>>;
}

function buildGraphLookups(graph: Graph): GraphLookups {
  const edgeEndpoints = new Map<string, [string, string]>();
  const adjacency = new Map<string, Set<string>>();
  const chunkNodes = new Set<string>();
  const nodeEdges = new Map<string, Set<string>>();

  graph.forEachNode((nodeId, attrs) => {
    adjacency.set(nodeId, new Set());
    nodeEdges.set(nodeId, new Set());
    if ((attrs.nodeType as string) === "chunk") {
      chunkNodes.add(nodeId);
    }
  });

  graph.forEachEdge((edge, _attrs, source, target) => {
    edgeEndpoints.set(edge, [source, target]);
    adjacency.get(source)?.add(target);
    adjacency.get(target)?.add(source);
    nodeEdges.get(source)?.add(edge);
    nodeEdges.get(target)?.add(edge);
  });

  return { edgeEndpoints, adjacency, chunkNodes, nodeEdges };
}

// ── Inner graph component (uses sigma hooks) ───────────────────────────────

interface GraphInnerProps {
  data: KGGraphData;
  filters: Filters;
  onNodeClick: (node: KGGraphNode) => void;
  onFilterChange: <K extends keyof Filters>(key: K, value: Filters[K]) => void;
  graphRef: React.MutableRefObject<Graph | null>;
  communitiesRef: React.MutableRefObject<Map<number, string[]>>;
  communityCountRef: React.MutableRefObject<number>;
  expandedNodes: Set<string>;
  onExpandNode: (nodeId: string) => void;
  onReady: () => void;
  onError: (msg: string) => void;
}

function GraphInner({
  data,
  filters,
  onNodeClick,
  onFilterChange,
  graphRef,
  communitiesRef,
  communityCountRef,
  expandedNodes,
  onExpandNode,
  onReady,
  onError,
}: GraphInnerProps) {
  const loadGraph = useLoadGraph();
  const registerEvents = useRegisterEvents();
  const sigma = useSigma();
  const setSettings = useSetSettings();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fa2Ref = useRef<FA2Layout | null>(null);
  const lookupsRef = useRef<GraphLookups>({
    edgeEndpoints: new Map(),
    adjacency: new Map(),
    chunkNodes: new Set(),
    nodeEdges: new Set() as unknown as Map<string, Set<string>>,
  });
  const semanticZoomEnabledRef = useRef(true);
  const lastManualToggleRef = useRef(0);

  // Helper: stop any running FA2 worker
  const stopFA2 = useCallback(() => {
    if (fa2Ref.current) {
      fa2Ref.current.stop();
      fa2Ref.current.kill();
      fa2Ref.current = null;
    }
  }, []);

  // Helper: start FA2 worker layout
  const startFA2 = useCallback(
    (graph: Graph, duration = 5000) => {
      stopFA2();
      if (graph.order === 0) return;

      const layout = new FA2Layout(graph, {
        settings: {
          gravity: 1,
          scalingRatio: 10,
          barnesHutOptimize: true,
          slowDown: 5,
        },
      });
      fa2Ref.current = layout;
      layout.start();

      // Auto-stop after duration
      setTimeout(() => {
        if (fa2Ref.current === layout) {
          layout.stop();
        }
      }, duration);
    },
    [stopFA2],
  );

  // Phase 1: Build graph structure and render immediately
  // Phase 2: Run Louvain + FA2 layout via Web Worker
  useEffect(() => {
    try {
      const graph = buildGraphStructure(data);
      graphRef.current = graph;
      lookupsRef.current = buildGraphLookups(graph);
      loadGraph(graph);
      onReady();

      const deferredTimer = setTimeout(() => {
        try {
          const { communityCount, communities } = applyCommunities(graph);
          communitiesRef.current = communities;
          communityCountRef.current = communityCount;
          sigma.refresh();

          // Start FA2 layout in Web Worker — zero main-thread jank
          startFA2(graph);
        } catch (err) {
          console.warn("KG layout/clustering error:", err);
        }
      }, 50);

      return () => {
        clearTimeout(deferredTimer);
        stopFA2();
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(msg);
    }
  }, [data]);

  // Switch between cluster view and full view
  useEffect(() => {
    const graph = graphRef.current;
    const communities = communitiesRef.current;
    if (!graph) return;

    stopFA2();

    if (filters.clusterView && communities.size > 0) {
      const cg = buildClusterGraph(graph, communities);
      lookupsRef.current = buildGraphLookups(cg);
      loadGraph(cg);
    } else {
      lookupsRef.current = buildGraphLookups(graph);
      loadGraph(graph);
    }

    setTimeout(() => {
      sigma.getCamera().animatedReset({ duration: 300 });
    }, 100);
  }, [filters.clusterView]);

  // Semantic zoom: auto-switch cluster ↔ detail based on camera zoom
  useEffect(() => {
    const camera = sigma.getCamera();

    const handleCameraUpdate = () => {
      // Don't override if user manually toggled recently (2s cooldown)
      if (Date.now() - lastManualToggleRef.current < 2000) return;
      if (!semanticZoomEnabledRef.current) return;
      if (communitiesRef.current.size === 0) return;

      const ratio = camera.ratio;

      if (!filters.clusterView && ratio > CLUSTER_ZOOM_OUT_RATIO) {
        onFilterChange("clusterView", true);
      } else if (filters.clusterView && ratio < CLUSTER_ZOOM_IN_RATIO) {
        onFilterChange("clusterView", false);
      }
    };

    camera.on("updated", handleCameraUpdate);
    return () => {
      camera.off("updated", handleCameraUpdate);
    };
  }, [sigma, filters.clusterView, onFilterChange]);

  // Register click/hover/double-click events
  useEffect(() => {
    registerEvents({
      clickNode: (event) => {
        if (filters.clusterView) {
          // Click cluster super-node → zoom into that community
          const communityId = parseInt(event.node);
          const members = communitiesRef.current.get(communityId);
          if (members && members.length > 0 && graphRef.current) {
            // Switch to detail view
            lastManualToggleRef.current = Date.now();
            onFilterChange("clusterView", false);

            // Animate camera to the community centroid after switching
            setTimeout(() => {
              const graph = graphRef.current;
              if (!graph) return;
              let cx = 0, cy = 0, count = 0;
              for (const nid of members) {
                if (graph.hasNode(nid)) {
                  cx += graph.getNodeAttribute(nid, "x") as number;
                  cy += graph.getNodeAttribute(nid, "y") as number;
                  count++;
                }
              }
              if (count > 0) {
                const pos = sigma.graphToViewport({ x: cx / count, y: cy / count });
                const viewPos = sigma.viewportToFramedGraph(pos);
                sigma.getCamera().animate(
                  { x: viewPos.x, y: viewPos.y, ratio: 0.4 },
                  { duration: 400 },
                );
              }
            }, 200);
          }
          return;
        }

        const raw = data.nodes.find((n) => n.id === event.node);
        if (raw) onNodeClick(raw);

        // Zoom camera into the clicked node and its neighborhood
        const graph = graphRef.current;
        if (!graph || !graph.hasNode(event.node)) return;
        const neighbors = lookupsRef.current.adjacency.get(event.node);
        const nodeIds = [event.node, ...(neighbors ? Array.from(neighbors) : [])];

        let cx = 0, cy = 0, count = 0;
        for (const nid of nodeIds) {
          if (graph.hasNode(nid)) {
            cx += graph.getNodeAttribute(nid, "x") as number;
            cy += graph.getNodeAttribute(nid, "y") as number;
            count++;
          }
        }
        if (count > 0) {
          const pos = sigma.graphToViewport({ x: cx / count, y: cy / count });
          const viewPos = sigma.viewportToFramedGraph(pos);
          const zoomRatio = count <= 5 ? 0.2 : count <= 15 ? 0.35 : 0.5;
          sigma.getCamera().animate(
            { x: viewPos.x, y: viewPos.y, ratio: zoomRatio },
            { duration: 400 },
          );
        }
      },
      doubleClickNode: (event) => {
        if (filters.clusterView) return;
        // Double-click a document node → expand/reveal its chunk neighbors
        const graph = graphRef.current;
        if (!graph || !graph.hasNode(event.node)) return;
        const nodeType = graph.getNodeAttribute(event.node, "nodeType");
        if (nodeType === "document") {
          onExpandNode(event.node);

          // Animate camera to this node
          const x = graph.getNodeAttribute(event.node, "x") as number;
          const y = graph.getNodeAttribute(event.node, "y") as number;
          const pos = sigma.graphToViewport({ x, y });
          const viewPos = sigma.viewportToFramedGraph(pos);
          sigma.getCamera().animate(
            { x: viewPos.x, y: viewPos.y, ratio: 0.3 },
            { duration: 400 },
          );
        }
      },
      doubleClickStage: () => {
        // Prevent default zoom on double-click stage
      },
      enterNode: (event) => {
        if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
        setHoveredNode(event.node);
      },
      leaveNode: () => {
        // Small delay to prevent flicker when moving between adjacent nodes
        hoverTimerRef.current = setTimeout(() => setHoveredNode(null), 50);
      },
    });
  }, [registerEvents, data.nodes, onNodeClick, onExpandNode, filters.clusterView, sigma]);

  // Search match set + camera animation on search
  const searchMatchSet = useMemo(() => {
    const s = filters.search.toLowerCase();
    if (!s) return null;
    const set = new Set<string>();
    for (const n of data.nodes) {
      if (
        n.label.toLowerCase().includes(s) ||
        n.keyphrases.some((kp) => kp.toLowerCase().includes(s))
      ) {
        set.add(n.id);
      }
    }
    return set;
  }, [filters.search, data.nodes]);

  // Animate camera to search results
  useEffect(() => {
    if (!searchMatchSet || searchMatchSet.size === 0) return;
    const graph = graphRef.current;
    if (!graph) return;

    let cx = 0, cy = 0, count = 0;
    for (const nodeId of searchMatchSet) {
      if (graph.hasNode(nodeId)) {
        cx += graph.getNodeAttribute(nodeId, "x") as number;
        cy += graph.getNodeAttribute(nodeId, "y") as number;
        count++;
      }
    }
    if (count === 0) return;

    const pos = sigma.graphToViewport({ x: cx / count, y: cy / count });
    const viewPos = sigma.viewportToFramedGraph(pos);
    const zoomRatio = count <= 3 ? 0.3 : count <= 10 ? 0.5 : 0.7;
    sigma.getCamera().animate(
      { x: viewPos.x, y: viewPos.y, ratio: zoomRatio },
      { duration: 400 },
    );
  }, [searchMatchSet, sigma]);

  // Neighbor set for hover — O(1) adjacency lookup instead of O(E) scan
  const neighborSet = useMemo(() => {
    if (!hoveredNode) return null;
    const neighbors = lookupsRef.current.adjacency.get(hoveredNode);
    if (!neighbors) return new Set([hoveredNode]);
    const set = new Set(neighbors);
    set.add(hoveredNode);
    return set;
  }, [hoveredNode]);

  // Pre-compute set of chunk nodes visible due to expanded document nodes
  // This replaces the O(E) loop that ran per-node inside the reducer
  const expandedChunkNodes = useMemo(() => {
    if (expandedNodes.size === 0) return null;
    const { adjacency, chunkNodes } = lookupsRef.current;
    const visible = new Set<string>();
    for (const docId of expandedNodes) {
      const neighbors = adjacency.get(docId);
      if (!neighbors) continue;
      for (const nid of neighbors) {
        if (chunkNodes.has(nid)) visible.add(nid);
      }
    }
    return visible;
  }, [expandedNodes]);

  // Pre-compute set of edges that connect to expanded chunk neighborhoods
  const expandedEdges = useMemo(() => {
    if (!expandedChunkNodes || expandedChunkNodes.size === 0) return null;
    const { nodeEdges } = lookupsRef.current;
    const edges = new Set<string>();
    for (const docId of expandedNodes) {
      const docEdges = nodeEdges.get(docId);
      if (!docEdges) continue;
      for (const edgeKey of docEdges) {
        const ep = lookupsRef.current.edgeEndpoints.get(edgeKey);
        if (!ep) continue;
        const [src, tgt] = ep;
        const other = src === docId ? tgt : src;
        if (expandedChunkNodes.has(other)) edges.add(edgeKey);
      }
    }
    return edges;
  }, [expandedChunkNodes, expandedNodes]);

  // Reusable dimmed/hidden/highlighted attr objects to avoid GC pressure
  // We create these once per settings update, not per node/edge
  const DIMMED = useMemo(() => ({ color: "#1a2236", label: "" }), []);
  const HIDDEN = useMemo(() => ({ hidden: true as const }), []);
  const HIGHLIGHT_EDGE = useMemo(() => ({ color: "#818cf8", size: 1.5 }), []);

  // Apply filters via nodeReducer / edgeReducer
  useEffect(() => {
    const chunksHidden = !filters.showChunks;
    const hasCommunityFilter = filters.selectedCommunities.size > 0;
    const hasEdgeFilter = filters.edgeScoreMin > 0;
    const { edgeEndpoints, chunkNodes } = lookupsRef.current;

    setSettings({
      nodeReducer: (node, attrs) => {
        if (filters.clusterView) {
          if (!neighborSet) return attrs;
          if (!neighborSet.has(node))
            return { ...attrs, ...DIMMED };
          return { ...attrs, highlighted: true };
        }

        const nodeType = attrs.nodeType as string;

        // Document visibility
        if (nodeType === "document" && !filters.showDocuments)
          return { ...attrs, ...HIDDEN };

        // Chunk visibility: hidden unless expanded or hovered neighbor
        if (nodeType === "chunk" && chunksHidden) {
          if (expandedChunkNodes?.has(node))
            return { ...attrs, highlighted: true };
          if (neighborSet?.has(node))
            return { ...attrs, highlighted: true };
          return { ...attrs, ...HIDDEN };
        }

        // Community filter
        if (
          hasCommunityFilter &&
          !filters.selectedCommunities.has(attrs.community as number)
        )
          return { ...attrs, ...HIDDEN };

        // Search highlighting
        if (searchMatchSet) {
          if (!searchMatchSet.has(node))
            return { ...attrs, ...DIMMED };
          return { ...attrs, highlighted: true };
        }

        // Hover dimming
        if (neighborSet) {
          if (!neighborSet.has(node))
            return { ...attrs, ...DIMMED };
          return { ...attrs, highlighted: true };
        }

        return attrs;
      },
      edgeReducer: (edge, attrs) => {
        // Score threshold
        if (hasEdgeFilter && ((attrs.score as number) ?? 0) < filters.edgeScoreMin)
          return { ...attrs, ...HIDDEN };

        const endpoints = edgeEndpoints.get(edge);

        // When chunks are hidden, hide edges to chunk nodes (pre-computed set, no getNodeAttribute)
        if (chunksHidden && !filters.clusterView && endpoints) {
          const [src, tgt] = endpoints;
          const srcIsChunk = chunkNodes.has(src);
          const tgtIsChunk = chunkNodes.has(tgt);

          if (srcIsChunk || tgtIsChunk) {
            // Show if edge is in the expanded neighborhood
            if (expandedEdges?.has(edge))
              return { ...attrs, ...HIGHLIGHT_EDGE };
            if (neighborSet && neighborSet.has(src) && neighborSet.has(tgt))
              return { ...attrs, ...HIGHLIGHT_EDGE };
            return { ...attrs, ...HIDDEN };
          }
        }

        // Normal hover behavior
        if (neighborSet && endpoints) {
          const [src, tgt] = endpoints;
          if (!neighborSet.has(src) && !neighborSet.has(tgt))
            return { ...attrs, ...HIDDEN };
          return { ...attrs, ...HIGHLIGHT_EDGE };
        }

        return attrs;
      },
      labelRenderedSizeThreshold: 12,
      labelColor: { color: "#8896b0" },
      labelFont: '"DM Sans", sans-serif',
      labelSize: 12,
      labelDensity: 0.5,
    });
  }, [filters, searchMatchSet, neighborSet, expandedChunkNodes, expandedEdges, expandedNodes, setSettings, DIMMED, HIDDEN, HIGHLIGHT_EDGE]);

  return null;
}

// ── Main component ─────────────────────────────────────────────────────────

export default function KGGraphView({
  data,
  projectName,
  onBack,
}: KGGraphViewProps) {
  const [selectedNode, setSelectedNode] = useState<KGGraphNode | null>(null);
  const [filters, setFilters] = useState<Filters>({
    showDocuments: true,
    showChunks: false,
    edgeScoreMin: 0.3,
    selectedCommunities: new Set(),
    search: "",
    clusterView: false,
  });
  const [showFilters, setShowFilters] = useState(false);
  const [ready, setReady] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const graphRef = useRef<Graph | null>(null);
  const communitiesRef = useRef<Map<number, string[]>>(new Map());
  const communityCountRef = useRef<number>(0);

  const handleNodeClick = useCallback((node: KGGraphNode) => {
    setSelectedNode(node);
  }, []);

  const handleReady = useCallback(() => {
    setReady(true);
  }, []);

  const handleGraphError = useCallback((msg: string) => {
    setGraphError(msg);
  }, []);

  const updateFilter = useCallback(
    <K extends keyof Filters>(key: K, value: Filters[K]) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleExpandNode = useCallback((nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  const toggleCommunity = useCallback((community: number) => {
    setFilters((prev) => {
      const next = new Set(prev.selectedCommunities);
      if (next.has(community)) {
        next.delete(community);
      } else {
        next.add(community);
      }
      return { ...prev, selectedCommunities: next };
    });
  }, []);

  const clearCommunityFilter = useCallback(() => {
    setFilters((prev) => ({ ...prev, selectedCommunities: new Set() }));
  }, []);

  const visibleStats = useMemo(() => {
    if (filters.clusterView) {
      return { nodes: communityCountRef.current, edges: "~" as const };
    }
    let nodeCount = data.nodes.length;
    if (!filters.showDocuments) {
      nodeCount -= data.nodes.filter((n) => n.type === "document").length;
    }
    if (!filters.showChunks) {
      nodeCount -= data.nodes.filter((n) => n.type === "chunk").length;
    }
    const edgeCount = data.edges.filter(
      (e) => e.score >= filters.edgeScoreMin,
    ).length;
    return { nodes: nodeCount, edges: edgeCount };
  }, [data, filters]);

  // Empty data guard
  if (data.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <span className="text-sm text-text-muted">No nodes in this knowledge graph.</span>
        <button
          onClick={onBack}
          className="text-sm text-accent hover:text-accent/80 transition"
        >
          Go back
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b border-border bg-card/80 backdrop-blur-sm px-5 py-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-text-secondary transition hover:bg-elevated hover:text-text-primary"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          Back
        </button>

        <div className="h-5 w-px bg-border" />

        <h2 className="text-sm font-semibold text-text-primary truncate">
          {projectName}
        </h2>

        <div className="ml-auto flex items-center gap-3">
          {/* Cluster view toggle */}
          <button
            onClick={() => updateFilter("clusterView", !filters.clusterView)}
            className={`rounded-lg border px-3 py-1.5 text-micro font-medium transition ${
              filters.clusterView
                ? "border-accent/40 bg-accent/15 text-accent"
                : "border-border text-text-muted hover:bg-elevated hover:text-text-secondary"
            }`}
          >
            {filters.clusterView ? "Cluster view" : "Full view"}
          </button>

          {/* Expanded nodes indicator */}
          {expandedNodes.size > 0 && (
            <button
              onClick={() => setExpandedNodes(new Set())}
              className="flex items-center gap-1.5 rounded-lg border border-accent/30 bg-accent/10 px-3 py-1.5 text-micro font-medium text-accent transition hover:bg-accent/20"
            >
              {expandedNodes.size} expanded
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}

          {/* Search */}
          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              value={filters.search}
              onChange={(e) => updateFilter("search", e.target.value)}
              placeholder="Search nodes..."
              className="w-48 rounded-lg border border-border bg-input pl-8 pr-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
          </div>

          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-micro font-medium transition ${
              showFilters
                ? "border-accent/40 bg-accent/15 text-accent"
                : "border-border text-text-muted hover:bg-elevated hover:text-text-secondary"
            }`}
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" />
            </svg>
            Filters
          </button>

          {/* Stats */}
          <div className="flex items-center gap-3 text-micro text-text-muted font-mono">
            <span>
              {typeof visibleStats.nodes === "number"
                ? visibleStats.nodes.toLocaleString()
                : visibleStats.nodes}{" "}
              nodes
            </span>
            <span className="text-border">|</span>
            <span>
              {typeof visibleStats.edges === "number"
                ? visibleStats.edges.toLocaleString()
                : visibleStats.edges}{" "}
              edges
            </span>
          </div>
        </div>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="border-b border-border bg-card/60 backdrop-blur-sm px-5 py-3">
          <div className="flex flex-wrap items-center gap-5">
            {/* Node type toggles */}
            <div className="flex items-center gap-3">
              <span className="text-micro text-text-muted font-medium">Node types</span>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.showDocuments}
                  onChange={(e) => updateFilter("showDocuments", e.target.checked)}
                  className="rounded border-border bg-input text-emerald-500 focus:ring-0 focus:ring-offset-0 h-3.5 w-3.5"
                />
                <span className="flex items-center gap-1 text-micro text-text-secondary">
                  <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                  Document
                </span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.showChunks}
                  onChange={(e) => updateFilter("showChunks", e.target.checked)}
                  className="rounded border-border bg-input text-accent focus:ring-0 focus:ring-offset-0 h-3.5 w-3.5"
                />
                <span className="flex items-center gap-1 text-micro text-text-secondary">
                  <span className="inline-block h-2 w-2 rounded-full bg-accent" />
                  Chunk
                </span>
              </label>
            </div>

            <div className="h-5 w-px bg-border" />

            {/* Edge score slider */}
            <div className="flex items-center gap-2">
              <span className="text-micro text-text-muted font-medium">Min edge score</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={filters.edgeScoreMin}
                onChange={(e) => updateFilter("edgeScoreMin", parseFloat(e.target.value))}
                className="w-24 accent-accent h-1"
              />
              <span className="text-micro text-text-secondary font-mono w-8">
                {filters.edgeScoreMin.toFixed(2)}
              </span>
            </div>

            <div className="h-5 w-px bg-border" />

            {/* Community chips */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-micro text-text-muted font-medium">Communities</span>
              {filters.selectedCommunities.size > 0 && (
                <button
                  onClick={clearCommunityFilter}
                  className="text-micro text-accent hover:text-accent/80 transition"
                >
                  Clear
                </button>
              )}
              <div className="flex items-center gap-1 flex-wrap">
                {Array.from(
                  { length: Math.min(communityCountRef.current, 16) },
                  (_, i) => i,
                ).map((c) => {
                  const active =
                    filters.selectedCommunities.size === 0 ||
                    filters.selectedCommunities.has(c);
                  const members = communitiesRef.current.get(c)?.length || 0;
                  return (
                    <button
                      key={c}
                      onClick={() => toggleCommunity(c)}
                      className={`rounded-md px-2 py-0.5 text-2xs font-mono transition border ${
                        active ? "border-transparent" : "border-border opacity-30"
                      }`}
                      style={{
                        backgroundColor: active ? communityColor(c) + "26" : "#1a2236",
                        color: communityColor(c),
                      }}
                      title={`Community ${c}: ${members} nodes`}
                    >
                      {members}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Graph canvas */}
      <div className="flex-1 relative min-h-0 overflow-hidden">
        {!ready && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-deep">
            <div className="flex flex-col items-center gap-3">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-sm text-text-muted">Initializing graph...</span>
            </div>
          </div>
        )}
        {graphError && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-deep">
            <div className="flex flex-col items-center gap-3 max-w-md text-center">
              <span className="text-sm text-red-400">Failed to initialize graph</span>
              <span className="text-micro text-text-muted">{graphError}</span>
              <button
                onClick={onBack}
                className="mt-2 text-sm text-accent hover:text-accent/80 transition"
              >
                Go back
              </button>
            </div>
          </div>
        )}

        {/* Interaction hints */}
        {ready && !graphError && (
          <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2 rounded-lg bg-card/80 backdrop-blur-sm border border-border px-3 py-2">
            <span className="text-2xs text-text-muted">
              Click node to zoom &amp; details
            </span>
            <span className="text-border">|</span>
            <span className="text-2xs text-text-muted">
              Double-click document to expand chunks
            </span>
            <span className="text-border">|</span>
            <span className="text-2xs text-text-muted">
              Zoom out for cluster view
            </span>
          </div>
        )}

        <SigmaContainer
          style={{ width: "100%", height: "100%", background: "#080c14" }}
          settings={{
            defaultNodeColor: "#5a6a84",
            defaultEdgeColor: "#283348",
            renderEdgeLabels: false,
            labelRenderedSizeThreshold: 12,
            labelColor: { color: "#8896b0" },
            labelFont: '"DM Sans", sans-serif',
            labelSize: 12,
            labelDensity: 0.5,
            enableEdgeEvents: false,
            hideEdgesOnMove: true,
            hideLabelsOnMove: true,
            zoomDuration: 200,
            minEdgeThickness: 0.3,
            zIndex: true,
          }}
        >
          <GraphInner
            data={data}
            filters={filters}
            onNodeClick={handleNodeClick}
            onFilterChange={updateFilter}
            graphRef={graphRef}
            communitiesRef={communitiesRef}
            communityCountRef={communityCountRef}
            expandedNodes={expandedNodes}
            onExpandNode={handleExpandNode}
            onReady={handleReady}
            onError={handleGraphError}
          />
        </SigmaContainer>
      </div>

      {/* Detail panel */}
      {selectedNode && (
        <KGNodeDetail
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import type { ChunkConfig, TestSetCreate, SavedPersona, GenerationProgress, KnowledgeGraphInfo, KGBuildProgress } from "../../lib/api";
import {
  createTestSet,
  generatePersonas,
  fetchPersonas,
  savePersonasBulk,
  deletePersona,
  fetchGenerationProgress,
  fetchKnowledgeGraphInfo,
  buildKnowledgeGraph,
  fetchKGBuildProgress,
  deleteKnowledgeGraph,
  resetKnowledgeGraph,
  ApiError,
} from "../../lib/api";

const QUERY_TYPES = [
  { key: "single_hop_specific", label: "Single-hop Specific", description: "Direct factual questions answerable from a single chunk (e.g. \"What is the default timeout?\")" },
  { key: "multi_hop_abstract", label: "Multi-hop Abstract", description: "High-level questions requiring synthesis across multiple chunks (e.g. \"How does the system handle errors?\")" },
  { key: "multi_hop_specific", label: "Multi-hop Specific", description: "Precise questions needing details from multiple chunks (e.g. \"Which config options affect both caching and logging?\")" },
] as const;

const QUESTION_CATEGORIES = [
  { key: "typical", label: "Typical", description: "Common, expected queries users would ask in normal scenarios" },
  { key: "in_knowledge_base", label: "In Knowledge Base", description: "Questions about content within the knowledge base" },
  { key: "edge", label: "Edge", description: "Questions in unusual or challenging scenarios" },
  { key: "out_of_knowledge_base", label: "Out of Knowledge Base", description: "Questions about content outside the knowledge base" },
] as const;

const DEFAULT_CATEGORIES: Record<string, number> = {
  typical: 30,
  in_knowledge_base: 30,
  edge: 20,
  out_of_knowledge_base: 20,
};

const GRAPH_RAG_CATEGORIES = [
  { key: "bridge", label: "Bridge", description: "Questions connecting distant concepts through multi-hop reasoning (requires KG)" },
  { key: "comparative", label: "Comparative", description: "Compare and contrast related entities or concepts (requires KG)" },
  { key: "community", label: "Community", description: "High-level thematic questions about topic clusters (requires KG)" },
] as const;

const DEFAULT_GRAPH_RAG_DIST: Record<string, number> = {
  bridge: 34,
  comparative: 33,
  community: 33,
};

/**
 * Redistribute percentages when one slider changes.
 * Spreads the delta evenly across the other keys, round-robin,
 * so a small change (e.g. 1%) rotates across all others instead
 * of always landing on the same key.
 */
function redistributeEvenly(
  keys: string[],
  total: number,
  prev: Record<string, number>,
): Record<string, number> {
  if (keys.length === 0) return {};

  const prevTotal = keys.reduce((s, k) => s + (prev[k] ?? 0), 0);

  // If all others are zero, split evenly
  if (prevTotal === 0) {
    const base = Math.floor(total / keys.length);
    let rem = total - base * keys.length;
    const result: Record<string, number> = {};
    for (const k of keys) {
      result[k] = base + (rem > 0 ? 1 : 0);
      if (rem > 0) rem--;
    }
    return result;
  }

  const delta = total - prevTotal; // positive = others need more, negative = others need less
  const result: Record<string, number> = {};

  // Start with current values
  for (const k of keys) {
    result[k] = prev[k] ?? 0;
  }

  // Distribute delta one unit at a time, cycling through keys
  // sorted by current value descending (shrink the biggest first when negative,
  // grow the smallest first when positive)
  const sorted = delta >= 0
    ? [...keys].sort((a, b) => (result[a] ?? 0) - (result[b] ?? 0))   // smallest first for growth
    : [...keys].sort((a, b) => (result[b] ?? 0) - (result[a] ?? 0));  // biggest first for shrink

  let remaining = Math.abs(delta);
  let idx = 0;
  if (sorted.length === 0) return result;
  while (remaining > 0) {
    const k = sorted[idx % sorted.length] as string;
    if (delta >= 0) {
      result[k] = (result[k] ?? 0) + 1;
    } else if ((result[k] ?? 0) > 0) {
      result[k] = (result[k] ?? 0) - 1;
    } else {
      // skip keys already at 0 when shrinking
      idx++;
      continue;
    }
    remaining--;
    idx++;
  }

  return result;
}

const DEFAULT_DISTRIBUTION: Record<string, number> = {
  single_hop_specific: 50,
  multi_hop_abstract: 25,
  multi_hop_specific: 25,
};

interface Props {
  projectId: number;
  chunkConfigs: ChunkConfig[];
  onTestSetCreated: () => void;
}

export default function TestSetGenerate({
  projectId,
  chunkConfigs,
  onTestSetCreated,
}: Props) {
  const [chunkConfigId, setChunkConfigId] = useState<number | "">("");
  const [name, setName] = useState("");
  const [testsetSize, setTestsetSize] = useState<string>("10");
  const [numPersonas, setNumPersonas] = useState<string>("3");
  const [usePersonas, setUsePersonas] = useState(true);
  const [customPersonas, setCustomPersonas] = useState<
    { name: string; role_description: string; question_style: string }[]
  >([]);
  const [chunkSampleSize, setChunkSampleSize] = useState<string>("100");
  const [numWorkers, setNumWorkers] = useState(4);
  const [queryDistribution, setQueryDistribution] = useState<Record<string, number>>({ ...DEFAULT_DISTRIBUTION });
  const [useCustomDistribution, setUseCustomDistribution] = useState(false);
  const [useCategories, setUseCategories] = useState(false);
  const [enabledCategories, setEnabledCategories] = useState<Record<string, boolean>>({
    typical: true,
    in_knowledge_base: true,
    edge: true,
    out_of_knowledge_base: true,
  });
  const [categoryDistribution, setCategoryDistribution] = useState<Record<string, number>>({ ...DEFAULT_CATEGORIES });
  const [useGraphRag, setUseGraphRag] = useState(false);
  const [graphRagKgSource, setGraphRagKgSource] = useState<"chunks" | "documents">("chunks");
  const [docKgInfo, setDocKgInfo] = useState<KnowledgeGraphInfo | null>(null);
  const [docKgBuilding, setDocKgBuilding] = useState(false);
  const [enabledGraphRag, setEnabledGraphRag] = useState<Record<string, boolean>>({
    bridge: true,
    comparative: true,
    community: true,
  });
  const [graphRagDistribution, setGraphRagDistribution] = useState<Record<string, number>>({ ...DEFAULT_GRAPH_RAG_DIST });
  const [generating, setGenerating] = useState(false);
  const [generatingPersonas, setGeneratingPersonas] = useState(false);
  const [personaGenMode, setPersonaGenMode] = useState<"fast" | "full">("fast");
  const [savedPersonas, setSavedPersonas] = useState<SavedPersona[]>([]);
  const [savingPersonas, setSavingPersonas] = useState(false);
  const [showSavedPersonas, setShowSavedPersonas] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sizeError, setSizeError] = useState<string | null>(null);
  const [personasError, setPersonasError] = useState<string | null>(null);
  const [kgInfo, setKgInfo] = useState<KnowledgeGraphInfo | null>(null);
  const [kgBuilding, setKgBuilding] = useState(false);
  const [kgProgress, setKgProgress] = useState<KGBuildProgress | null>(null);
  const [overlapMaxNodes, setOverlapMaxNodes] = useState<number | null>(500);

  const loadSavedPersonas = useCallback(async () => {
    try {
      const personas = await fetchPersonas(projectId);
      setSavedPersonas(personas);
    } catch {
      // silent — not critical
    }
  }, [projectId]);

  const loadDocKgInfo = useCallback(async () => {
    try {
      const info = await fetchKnowledgeGraphInfo(projectId, "documents");
      setDocKgInfo(info);
    } catch {
      // silent
    }
  }, [projectId]);

  const loadKgInfo = useCallback(async () => {
    try {
      const info = await fetchKnowledgeGraphInfo(projectId);
      setKgInfo(info);
      // Check if a build is actively running (e.g. page refresh mid-build)
      const progress = await fetchKGBuildProgress(projectId);
      if (progress.active) {
        setKgBuilding(true);
        setKgProgress(progress);
      }
    } catch {
      // silent
    }
  }, [projectId]);

  useEffect(() => {
    loadSavedPersonas();
    loadKgInfo();
    loadDocKgInfo();
  }, [loadSavedPersonas, loadKgInfo, loadDocKgInfo]);

  // Poll KG build progress
  useEffect(() => {
    if (!kgBuilding) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const p = await fetchKGBuildProgress(projectId);
          if (cancelled) break;
          setKgProgress(p);
          if (!p.active) {
            setKgBuilding(false);
            setKgProgress(null);
            loadKgInfo();
            break;
          }
        } catch {
          // ignore
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [kgBuilding, projectId, loadKgInfo]);

  useEffect(() => {
    if (!generating) {
      setElapsed(0);
      setProgress(null);
      return;
    }
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [generating]);

  // Poll generation progress while generating
  useEffect(() => {
    if (!generating) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const p = await fetchGenerationProgress(projectId);
          if (cancelled) break;
          setProgress(p);

          // Generation completed or failed — stop polling
          if (p.status === "completed") {
            setGenerating(false);
            onTestSetCreated();
            break;
          }
          if (p.status === "failed") {
            setError(p.error_message || "Test generation failed");
            setGenerating(false);
            break;
          }
        } catch {
          // ignore polling errors
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [generating, projectId, onTestSetCreated]);

  const validateSize = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 400) {
      setSizeError("Must be between 1 and 400");
      return false;
    }
    setSizeError(null);
    return true;
  };

  const validatePersonas = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 10) {
      setPersonasError("Must be between 1 and 10");
      return false;
    }
    setPersonasError(null);
    return true;
  };

  const handleAutoGeneratePersonas = async () => {
    if (chunkConfigId === "" || !validatePersonas(numPersonas)) return;
    setGeneratingPersonas(true);
    setError(null);
    try {
      const personas = await generatePersonas(
        projectId,
        chunkConfigId as number,
        Number(numPersonas),
        personaGenMode,
      );
      setCustomPersonas(personas);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to auto-generate personas",
      );
    } finally {
      setGeneratingPersonas(false);
    }
  };

  const handleSavePersonas = async () => {
    const valid = customPersonas.filter(
      (p) => p.name.trim() && p.role_description.trim(),
    );
    if (valid.length === 0) return;
    setSavingPersonas(true);
    try {
      await savePersonasBulk(projectId, valid);
      await loadSavedPersonas();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to save personas",
      );
    } finally {
      setSavingPersonas(false);
    }
  };

  const handleLoadSavedPersona = (p: SavedPersona) => {
    const exists = customPersonas.some(
      (c) => c.name === p.name && c.role_description === p.role_description,
    );
    if (!exists) {
      setCustomPersonas((prev) => [
        ...prev,
        {
          name: p.name,
          role_description: p.role_description,
          question_style: p.question_style,
        },
      ]);
    }
    setShowSavedPersonas(false);
  };

  const handleDeleteSavedPersona = async (personaId: number) => {
    try {
      await deletePersona(projectId, personaId);
      setSavedPersonas((prev) => prev.filter((p) => p.id !== personaId));
    } catch {
      // silent
    }
  };

  // Chunk config is optional when ONLY Graph RAG categories are selected with Documents source
  const chunksRequired = !(
    useGraphRag &&
    graphRagKgSource === "documents" &&
    !useCategories
  );

  const handleGenerate = async () => {
    setError(null);
    const sizeOk = validateSize(testsetSize);
    const personasOk = !usePersonas || validatePersonas(numPersonas);
    if (!sizeOk || !personasOk || (chunksRequired && chunkConfigId === "")) return;

    const parsedSize = Number(testsetSize);
    const parsedPersonas = Number(numPersonas);
    const parsedChunkSample = Number(chunkSampleSize) || 0;

    try {
      const config: TestSetCreate = {
        chunk_config_id: chunksRequired ? (chunkConfigId as number) : undefined,
        testset_size: parsedSize,
        num_personas: usePersonas ? parsedPersonas : undefined,
        use_personas: usePersonas,
        query_distribution: useCustomDistribution
          ? Object.fromEntries(
              Object.entries(queryDistribution).map(([k, v]) => [k, v / 100]),
            )
          : undefined,
        chunk_sample_size: parsedChunkSample,
        num_workers: numWorkers,
      };
      if (name.trim()) config.name = name.trim();

      // Include question categories if enabled
      const activeCats: Record<string, number> = {};
      if (useCategories) {
        for (const cat of QUESTION_CATEGORIES) {
          if (enabledCategories[cat.key]) {
            activeCats[cat.key] = categoryDistribution[cat.key] ?? 0;
          }
        }
      }
      // Merge Graph RAG categories if enabled
      if (useGraphRag) {
        for (const cat of GRAPH_RAG_CATEGORIES) {
          if (enabledGraphRag[cat.key]) {
            activeCats[cat.key] = graphRagDistribution[cat.key] ?? 0;
          }
        }
      }
      if (Object.keys(activeCats).length > 0) {
        config.question_categories = activeCats;
      }
      if (useGraphRag) {
        config.graph_rag_kg_source = graphRagKgSource;
      }

      // Include custom personas only if valid entries exist (both name and role_description required)
      if (usePersonas && customPersonas.length > 0) {
        const valid = customPersonas.filter(
          (p) => p.name.trim() && p.role_description.trim(),
        );
        if (valid.length > 0) {
          config.custom_personas = valid.map((p) => ({
            name: p.name.trim(),
            role_description: p.role_description.trim(),
            question_style: p.question_style.trim(),
          }));
        }
      }

      // POST returns immediately — generation runs in background
      await createTestSet(projectId, config);

      // Reset form
      setName("");
      setChunkConfigId("");
      setTestsetSize("10");
      setNumPersonas("3");
      setUsePersonas(true);
      setCustomPersonas([]);
      setChunkSampleSize("100");
      setNumWorkers(4);
      setUseCustomDistribution(false);
      setQueryDistribution({ ...DEFAULT_DISTRIBUTION });
      setUseCategories(false);
      setEnabledCategories({ typical: true, in_knowledge_base: true, edge: true, out_of_knowledge_base: true });
      setCategoryDistribution({ ...DEFAULT_CATEGORIES });
      setUseGraphRag(false);
      setGraphRagKgSource("chunks");
      setDocKgInfo(null);
      setEnabledGraphRag({ bridge: true, comparative: true, community: true });
      setGraphRagDistribution({ ...DEFAULT_GRAPH_RAG_DIST });

      // Enter generating state — polling effect will detect completion
      setGenerating(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError("A test set is already being generated for this project.");
        } else if (err.status === 422) {
          setError(err.message || "No chunks found for this config. Generate chunks in the Build stage first.");
        } else if (err.status === 429) {
          setError("Rate limit exceeded — wait a moment and try again.");
        } else {
          setError(err.message);
        }
      } else {
        setError((err as Error).message || "Generation failed");
      }
    }
  };

  if (chunkConfigs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-text-muted">
          Create and generate chunks in the{" "}
          <span className="font-medium text-text-secondary">Build</span> stage
          first.
        </p>
      </div>
    );
  }

  if (generating) {
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

    const STAGE_LABELS: Record<string, string> = {
      building_knowledge_graph: "Building knowledge graph",
      kg_resuming_from_checkpoint: "Resuming from checkpoint",
      kg_loaded_from_cache: "Loaded knowledge graph from cache",
      kg_extracting_headlines: "Extracting headlines from chunks",
      kg_splitting_headlines: "Splitting chunks by headlines",
      kg_extracting_keyphrases: "Extracting keyphrases (slowest step)",
      kg_building_overlap: "Building overlap scores between nodes",
      kg_filtering_nodes: "Filtering low-quality nodes",
      kg_extracting_themes: "Extracting themes from chunks",
      kg_extracting_entities: "Extracting named entities",
      kg_building_summary_similarity: "Building summary similarity links",
      kg_building_entity_overlap: "Building entity overlap scores",
      generating_personas: "Generating personas",
      generating_questions: "Synthesizing questions",
      generating_special_categories: "Generating edge & out-of-KB questions",
      generating_bridge_questions: "Generating bridge questions",
      generating_comparative_questions: "Generating comparative questions",
      generating_community_questions: "Generating community questions",
    };
    // When KG is loaded from cache, show a single "loaded from cache" step
    // instead of the individual KG build sub-steps.
    const currentStage = progress?.stage ?? "building_knowledge_graph";
    const kgCached = currentStage === "kg_loaded_from_cache"
      || (!currentStage.startsWith("kg_") && currentStage !== "building_knowledge_graph");

    const STAGE_ORDER = kgCached
      ? [
          "kg_loaded_from_cache",
          "generating_personas",
          "generating_questions",
          "generating_special_categories",
          "generating_bridge_questions",
          "generating_comparative_questions",
          "generating_community_questions",
        ]
      : [
          "building_knowledge_graph",
          "kg_extracting_headlines",
          "kg_splitting_headlines",
          "kg_extracting_keyphrases",
          "kg_building_overlap",
          "kg_extracting_summaries",
          "kg_filtering_nodes",
          "kg_embedding_summaries",
          "kg_extracting_themes",
          "kg_extracting_entities",
          "kg_building_summary_similarity",
          "kg_building_entity_overlap",
          "generating_personas",
          "generating_questions",
          "generating_special_categories",
          "generating_bridge_questions",
          "generating_comparative_questions",
          "generating_community_questions",
        ];

    const currentStageIdx = STAGE_ORDER.indexOf(currentStage);
    const questionsGenerated = progress?.questions_generated ?? 0;
    const targetSize = progress?.target_size ?? (Number(testsetSize) || 10);
    const pct = Math.min(100, Math.round((questionsGenerated / targetSize) * 100));

    return (
      <div className="space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Generate Test Set
        </h3>
        <div className="flex flex-col items-center gap-5 rounded-lg border border-border bg-elevated/50 py-10 px-6">
          {/* Spinner */}
          <svg className="h-10 w-10 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>

          <div className="text-center">
            <p className="text-sm font-medium text-text-primary">Generating test set…</p>
            <p className="mt-1 text-xs tabular-nums text-text-muted">Elapsed: {timeStr}</p>
          </div>

          {/* Question counter */}
          {progress?.active && (
            <div className="w-full max-w-xs space-y-2">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium tabular-nums text-text-primary">
                  {questionsGenerated} / {targetSize} questions
                </span>
                <span className="text-xs tabular-nums text-text-muted">{pct}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-border/50">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500 ease-out"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )}

          {/* Stage steps */}
          <div className="w-full max-w-xs space-y-2">
            {STAGE_ORDER.map((stage, i) => {
              const label = STAGE_LABELS[stage] ?? stage;
              const isDone = i < currentStageIdx;
              const isActive = i === currentStageIdx;
              return (
                <div key={stage} className="flex items-center gap-2">
                  {isDone ? (
                    <svg className="h-4 w-4 shrink-0 text-score-high" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : isActive ? (
                    <svg className="h-4 w-4 shrink-0 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <div className="h-4 w-4 shrink-0 rounded-full border border-border" />
                  )}
                  <span className={`text-xs ${i <= currentStageIdx ? "text-text-secondary" : "text-text-muted"}`}>
                    {label}
                  </span>
                </div>
              );
            })}
          </div>

          <p className="text-xs text-text-muted">This may take a few minutes depending on chunk count.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Generate Test Set
      </h3>

      <div className="grid gap-3 sm:grid-cols-2">
        {/* Chunk config selector */}
        <div className="sm:col-span-2">
          <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
            Chunk Config
            {useGraphRag && graphRagKgSource === "documents" && (
              <span className="text-[10px] text-text-muted">(optional — not needed for Graph RAG Documents only)</span>
            )}
          </label>
          <select
            value={chunkConfigId}
            onChange={(e) =>
              setChunkConfigId(e.target.value ? Number(e.target.value) : "")
            }
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

        {/* Name */}
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Name{" "}
            <span className="font-normal text-text-muted">(optional)</span>
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
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Test Set Size
          </label>
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
                ? "border-red-500 focus:border-red-500"
                : "border-border bg-input focus:border-accent"
            }`}
            disabled={generating}
          />
          {sizeError && (
            <p className="mt-1 text-xs text-red-400">{sizeError}</p>
          )}
        </div>

        {/* Chunk sample size */}
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Chunk Sample Size
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
            Random subset of chunks to use. 0 = all chunks.
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
                {n} {n === 1 ? "worker" : "workers"}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-text-muted">
            More workers = faster generation. Increase for large test sets.
          </p>
        </div>

        {/* Knowledge Graph */}
        {chunkConfigId !== "" && (
          <div className="sm:col-span-2 rounded-lg border border-border bg-elevated/50 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                Knowledge Graph
              </h4>
              {kgInfo?.exists && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await deleteKnowledgeGraph(projectId);
                      setKgInfo({ exists: false });
                    } catch {
                      setError("Failed to delete knowledge graph");
                    }
                  }}
                  disabled={generating || kgBuilding}
                  className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40"
                >
                  Delete
                </button>
              )}
            </div>

            {kgBuilding ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <svg className="h-4 w-4 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span className="text-sm text-text-primary">
                    {kgProgress?.stage === "kg_resuming_from_checkpoint" ? "Resuming from checkpoint..." :
                     kgProgress?.stage === "kg_extracting_headlines" ? "Extracting headlines..." :
                     kgProgress?.stage === "kg_splitting_headlines" ? "Splitting headlines..." :
                     kgProgress?.stage === "kg_extracting_keyphrases" ? "Extracting keyphrases..." :
                     kgProgress?.stage === "kg_building_overlap" ? "Building overlap scores..." :
                     kgProgress?.stage === "kg_filtering_nodes" ? "Filtering nodes..." :
                     kgProgress?.stage === "kg_extracting_themes" ? "Extracting themes..." :
                     kgProgress?.stage === "kg_extracting_entities" ? "Extracting entities..." :
                     kgProgress?.stage === "kg_building_summary_similarity" ? "Building similarity..." :
                     kgProgress?.stage === "kg_building_entity_overlap" ? "Building entity overlap..." :
                     "Building knowledge graph..."}
                  </span>
                </div>
                {kgProgress?.batch_total && kgProgress.batch_total > 1 && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-text-muted">
                      <span>Batch {kgProgress.batch_current ?? 0}/{kgProgress.batch_total}</span>
                      <span>{kgProgress.nodes_processed ?? 0}/{kgProgress.nodes_total ?? 0} nodes</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-bg-tertiary overflow-hidden">
                      <div
                        className="h-full rounded-full bg-accent transition-all duration-500"
                        style={{ width: `${((kgProgress.nodes_processed ?? 0) / (kgProgress.nodes_total || 1)) * 100}%` }}
                      />
                    </div>
                  </div>
                )}
                <p className="text-xs text-text-muted">
                  This may take 30-60 minutes for large document sets.
                </p>
              </div>
            ) : kgInfo?.exists ? (
              <div className="text-sm text-text-secondary space-y-1">
                <p>{kgInfo.num_nodes} nodes from {kgInfo.num_chunks} chunks</p>
                <p className="text-xs text-text-muted">
                  Built {kgInfo.created_at ? new Date(kgInfo.created_at).toLocaleString() : ""}
                  {kgInfo.is_complete === false && ` (partial — step ${kgInfo.completed_steps ?? 0}/11)`}
                </p>
                {kgInfo.is_complete === false && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          setKgBuilding(true);
                          await buildKnowledgeGraph(
                            projectId,
                            kgInfo.chunk_config_id ?? (chunkConfigId as number) ?? null,
                            overlapMaxNodes,
                          );
                        } catch (err) {
                          setKgBuilding(false);
                          setError(
                            err instanceof ApiError ? err.message : "Failed to resume KG build",
                          );
                        }
                      }}
                      className="px-3 py-1 text-xs rounded bg-accent text-white hover:bg-accent/90"
                    >
                      Resume Build
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await resetKnowledgeGraph(projectId);
                          setKgInfo({ exists: false });
                        } catch (err) {
                          setError(
                            err instanceof ApiError ? err.message : "Failed to reset KG",
                          );
                        }
                      }}
                      className="px-3 py-1 text-xs rounded border border-red-300 text-red-600 hover:bg-red-50"
                    >
                      Reset
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-text-muted">
                  Pre-build a knowledge graph for faster "Full" persona generation and richer test sets.
                </p>
                <div className="flex items-center gap-3">
                  <label className="text-xs text-text-secondary whitespace-nowrap">
                    Overlap node cap
                  </label>
                  <select
                    value={overlapMaxNodes === null ? "none" : String(overlapMaxNodes)}
                    onChange={(e) => setOverlapMaxNodes(e.target.value === "none" ? null : Number(e.target.value))}
                    className="rounded border border-border bg-bg-secondary px-2 py-1 text-xs"
                  >
                    <option value="250">250 (~1 min)</option>
                    <option value="500">500 (~3-5 min)</option>
                    <option value="750">750 (~8-12 min)</option>
                    <option value="1000">1000 (~15-20 min)</option>
                    <option value="1500">1500 (~35-45 min)</option>
                    <option value="none">No limit (can be very slow)</option>
                  </select>
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      setKgBuilding(true);
                      await buildKnowledgeGraph(projectId, chunkConfigId as number, overlapMaxNodes);
                    } catch (err) {
                      setKgBuilding(false);
                      setError(
                        err instanceof ApiError ? err.message : "Failed to start KG build",
                      );
                    }
                  }}
                  disabled={generating}
                  className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/20 disabled:opacity-40"
                >
                  Generate Knowledge Graph
                </button>
              </div>
            )}
          </div>
        )}

        {/* Use personas toggle */}
        <div className="flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={usePersonas}
              onChange={(e) => setUsePersonas(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Use Personas
          </label>
        </div>

        {/* Num personas */}
        {usePersonas && (
          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Number of Personas
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={numPersonas}
              onChange={(e) => {
                setNumPersonas(e.target.value);
                validatePersonas(e.target.value);
              }}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-text-primary focus:outline-none ${
                personasError
                  ? "border-red-500 focus:border-red-500"
                  : "border-border bg-input focus:border-accent"
              }`}
              disabled={generating}
            />
            {personasError && (
              <p className="mt-1 text-xs text-red-400">{personasError}</p>
            )}
          </div>
        )}

        {/* Custom personas editor */}
        {usePersonas && (
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Custom Personas{" "}
              <span className="font-normal text-text-muted">
                (optional — leave empty for auto-generated)
              </span>
            </label>

            {generatingPersonas && (
              <div className="mb-2 space-y-3">
                {Array.from({ length: Number(numPersonas) || 3 }).map((_, i) => (
                  <div key={i} className="animate-pulse rounded-lg border border-border bg-input/50 p-2.5 space-y-1.5">
                    <div className="flex items-start gap-2">
                      <div className="w-1/3 h-8 rounded-lg bg-border/50" />
                      <div className="flex-1 h-8 rounded-lg bg-border/50" />
                      <div className="shrink-0 h-8 w-8 rounded-md bg-border/50" />
                    </div>
                    <div className="w-full h-8 rounded-lg bg-border/50" />
                  </div>
                ))}
                <p className="text-xs text-accent">
                  {personaGenMode === "full"
                    ? "Building knowledge graph and generating personas (this may take a few minutes)..."
                    : "Analyzing documents and generating personas..."}
                </p>
              </div>
            )}

            {!generatingPersonas && customPersonas.length > 0 && (
              <div className="mb-2 space-y-3">
                {customPersonas.map((p, i) => (
                  <div key={i} className="rounded-lg border border-border bg-input/50 p-2.5 space-y-1.5">
                    <div className="flex items-start gap-2">
                      <input
                        type="text"
                        value={p.name}
                        onChange={(e) => {
                          setCustomPersonas((prev) =>
                            prev.map((item, j) =>
                              j === i ? { ...item, name: e.target.value } : item,
                            ),
                          );
                        }}
                        placeholder="Name"
                        className="w-1/3 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                        disabled={generating}
                      />
                      <input
                        type="text"
                        value={p.role_description}
                        onChange={(e) => {
                          setCustomPersonas((prev) =>
                            prev.map((item, j) =>
                              j === i ? { ...item, role_description: e.target.value } : item,
                            ),
                          );
                        }}
                        placeholder="Role description"
                        className="flex-1 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                        disabled={generating}
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setCustomPersonas(customPersonas.filter((_, j) => j !== i))
                        }
                        disabled={generating}
                        className="shrink-0 rounded-md border border-border p-1.5 text-text-muted transition hover:border-red-500/40 hover:text-red-400 disabled:opacity-40"
                        title="Remove persona"
                      >
                        <svg
                          className="h-3.5 w-3.5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M6 18 18 6M6 6l12 12"
                          />
                        </svg>
                      </button>
                    </div>
                    <input
                      type="text"
                      value={p.question_style}
                      onChange={(e) => {
                        setCustomPersonas((prev) =>
                          prev.map((item, j) =>
                            j === i ? { ...item, question_style: e.target.value } : item,
                          ),
                        );
                      }}
                      placeholder="Question style (e.g. formal technical queries, brief keyword searches, scenario-based questions)"
                      className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      disabled={generating}
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Generation mode toggle */}
            <div className="mb-2 flex items-center gap-3">
              <span className="text-xs text-text-muted">Generation mode:</span>
              <button
                type="button"
                onClick={() => setPersonaGenMode("fast")}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  personaGenMode === "fast"
                    ? "bg-accent text-white"
                    : "border border-border text-text-muted hover:border-accent hover:text-accent"
                }`}
                disabled={generating || generatingPersonas}
              >
                Fast
              </button>
              <button
                type="button"
                onClick={() => setPersonaGenMode("full")}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  personaGenMode === "full"
                    ? "bg-accent text-white"
                    : "border border-border text-text-muted hover:border-accent hover:text-accent"
                }`}
                disabled={generating || generatingPersonas}
              >
                Full (Knowledge Graph)
              </button>
            </div>

            {/* Action buttons */}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() =>
                  setCustomPersonas([
                    ...customPersonas,
                    { name: "", role_description: "", question_style: "" },
                  ])
                }
                disabled={generating || generatingPersonas || customPersonas.length >= (Number(numPersonas) || 1)}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                + Add Persona
                {customPersonas.length >= (Number(numPersonas) || 1) && (
                  <span className="ml-1 text-text-muted">
                    (max {numPersonas})
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={handleAutoGeneratePersonas}
                disabled={generating || generatingPersonas || (chunksRequired && chunkConfigId === "")}
                className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {generatingPersonas
                  ? personaGenMode === "full"
                    ? "Building knowledge graph…"
                    : "Generating…"
                  : `Auto Generate (${personaGenMode === "full" ? "Full" : "Fast"})`}
              </button>
              {customPersonas.length > 0 && (
                <button
                  type="button"
                  onClick={handleSavePersonas}
                  disabled={savingPersonas || generating}
                  className="rounded-md border border-green-500/40 bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-400 transition hover:bg-green-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {savingPersonas ? "Saving…" : "Save Personas"}
                </button>
              )}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowSavedPersonas(!showSavedPersonas)}
                  disabled={generating || generatingPersonas || savedPersonas.length === 0}
                  className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Load Saved{savedPersonas.length > 0 && ` (${savedPersonas.length})`}
                </button>
                {showSavedPersonas && savedPersonas.length > 0 && (
                  <div className="absolute left-0 top-full z-10 mt-1 max-h-60 w-80 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg">
                    {savedPersonas.map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center gap-2 border-b border-border/50 px-3 py-2 last:border-b-0"
                      >
                        <button
                          type="button"
                          onClick={() => handleLoadSavedPersona(p)}
                          className="flex-1 text-left"
                        >
                          <p className="text-sm font-medium text-text-primary">{p.name}</p>
                          <p className="truncate text-xs text-text-muted">{p.role_description}</p>
                          {p.question_style && (
                            <p className="truncate text-xs text-accent/70">{p.question_style}</p>
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteSavedPersona(p.id)}
                          className="shrink-0 rounded p-1 text-text-muted transition hover:text-red-400"
                          title="Delete saved persona"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {personaGenMode === "full" && (
              <p className="mt-1 text-xs text-text-muted">
                Full mode builds a knowledge graph from your documents for more accurate personas. This takes longer.
              </p>
            )}
          </div>
        )}
        {/* Question categories toggle */}
        <div className="sm:col-span-2 flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={useCategories}
              onChange={(e) => setUseCategories(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Question Categories
          </label>
        </div>

        {/* Question categories config */}
        {useCategories && (
          <div className="sm:col-span-2 space-y-3 rounded-lg border border-border bg-elevated/50 p-3">
            <p className="text-xs text-text-muted">
              Select which question categories to include and adjust their proportions.
            </p>
            {QUESTION_CATEGORIES.map((cat) => {
              const enabled = enabledCategories[cat.key] ?? false;
              const pct = categoryDistribution[cat.key] ?? 0;
              return (
                <div key={cat.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => {
                          const next = { ...enabledCategories, [cat.key]: e.target.checked };
                          setEnabledCategories(next);
                          // Redistribute percentages among enabled categories
                          const enabledKeys = QUESTION_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => next[k]);
                          if (enabledKeys.length > 0) {
                            const share = Math.round(100 / enabledKeys.length);
                            const newDist: Record<string, number> = {};
                            enabledKeys.forEach((k, i) => {
                              newDist[k] = i === enabledKeys.length - 1
                                ? 100 - share * (enabledKeys.length - 1)
                                : share;
                            });
                            QUESTION_CATEGORIES.forEach((c) => {
                              if (!next[c.key]) newDist[c.key] = 0;
                            });
                            setCategoryDistribution(newDist);
                          }
                        }}
                        className="h-3.5 w-3.5 rounded border-border bg-input text-accent accent-accent"
                        disabled={generating}
                      />
                      <div>
                        <label className="text-xs font-medium text-text-secondary">
                          {cat.label}
                        </label>
                        <p className="text-[11px] leading-tight text-text-muted">{cat.description}</p>
                      </div>
                    </div>
                    {enabled && (
                      <div className="flex shrink-0 items-baseline gap-0.5">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={pct}
                          onFocus={(e) => e.target.select()}
                          onChange={(e) => {
                            const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                            setCategoryDistribution((prev) => {
                              const enabledKeys = QUESTION_CATEGORIES
                                .map((c) => c.key)
                                .filter((k) => enabledCategories[k] && k !== cat.key);
                              const remaining = 100 - raw;
                              const distributed = redistributeEvenly(enabledKeys, remaining, prev);
                              return { ...prev, [cat.key]: raw, ...distributed };
                            });
                          }}
                          disabled={generating}
                          className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                        />
                        <span className="text-xs text-text-muted">%</span>
                      </div>
                    )}
                  </div>
                  {enabled && (
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={pct}
                      onChange={(e) => {
                        const raw = Number(e.target.value);
                        setCategoryDistribution((prev) => {
                          const enabledKeys = QUESTION_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => enabledCategories[k] && k !== cat.key);
                          const remaining = 100 - raw;
                          const distributed = redistributeEvenly(enabledKeys, remaining, prev);
                          return { ...prev, [cat.key]: raw, ...distributed };
                        });
                      }}
                      className="w-full accent-accent"
                      disabled={generating}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Query distribution toggle */}
        <div className="sm:col-span-2 flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={useCustomDistribution}
              onChange={(e) => setUseCustomDistribution(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Custom Query Distribution
          </label>
        </div>

        {/* Query distribution sliders */}
        {useCustomDistribution && (
          <div className="sm:col-span-2 space-y-3 rounded-lg border border-border bg-elevated/50 p-3">
            <p className="text-xs text-text-muted">
              Adjust the proportion of each question type. Values always sum to 100%.
            </p>
            {QUERY_TYPES.map((qt) => {
              const pct = queryDistribution[qt.key] ?? 0;
              return (
                <div key={qt.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div>
                      <label className="text-xs font-medium text-text-secondary">
                        {qt.label}
                      </label>
                      <p className="text-[11px] leading-tight text-text-muted">{qt.description}</p>
                    </div>
                    <div className="flex shrink-0 items-baseline gap-0.5">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={pct}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => {
                          const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                          setQueryDistribution((prev) => {
                            const otherKeys = QUERY_TYPES
                              .map((q) => q.key)
                              .filter((k) => k !== qt.key);
                            const remaining = 100 - raw;
                            const distributed = redistributeEvenly(otherKeys, remaining, prev);
                            return { [qt.key]: raw, ...distributed };
                          });
                        }}
                        disabled={generating}
                        className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                      />
                      <span className="text-xs text-text-muted">%</span>
                    </div>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={pct}
                    onChange={(e) => {
                      const raw = Number(e.target.value);
                      setQueryDistribution((prev) => {
                        const otherKeys = QUERY_TYPES
                          .map((q) => q.key)
                          .filter((k) => k !== qt.key);
                        const remaining = 100 - raw;
                        const distributed = redistributeEvenly(otherKeys, remaining, prev);
                        return { [qt.key]: raw, ...distributed };
                      });
                    }}
                    className="w-full accent-accent"
                    disabled={generating}
                  />
                </div>
              );
            })}
          </div>
        )}

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
              Generate relationship-aware questions using the knowledge graph. All types require a built KG.
            </p>

            {/* KG Source selector */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">KG Source:</span>
              <div className="flex rounded-md border border-border overflow-hidden text-xs">
                {(["chunks", "documents"] as const).map((src) => (
                  <button
                    key={src}
                    type="button"
                    onClick={() => {
                      setGraphRagKgSource(src);
                      if (src === "documents") loadDocKgInfo();
                    }}
                    disabled={generating}
                    className={`px-3 py-1 capitalize transition ${
                      graphRagKgSource === src
                        ? "bg-accent text-white"
                        : "bg-elevated text-text-secondary hover:bg-elevated/80"
                    }`}
                  >
                    {src}
                  </button>
                ))}
              </div>
            </div>

            {/* Document KG status (shown only when Documents source selected) */}
            {graphRagKgSource === "documents" && (
              <div className="flex items-center justify-between rounded-md border border-border/60 bg-deep px-3 py-2 text-xs">
                {docKgBuilding ? (
                  <span className="flex items-center gap-1.5 text-text-muted">
                    <svg className="h-3 w-3 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Building document KG…
                  </span>
                ) : docKgInfo?.exists ? (
                  <span className={docKgInfo.chunks_stale ? "text-amber-400" : "text-green-400"}>
                    {docKgInfo.chunks_stale
                      ? `Document KG stale (${docKgInfo.num_nodes ?? 0} nodes)`
                      : `Document KG ready (${docKgInfo.num_nodes ?? 0} nodes)`}
                  </span>
                ) : (
                  <span className="text-text-muted">Document KG not built</span>
                )}
                <button
                  type="button"
                  disabled={generating || docKgBuilding}
                  onClick={async () => {
                    setDocKgBuilding(true);
                    try {
                      await buildKnowledgeGraph(projectId, null, overlapMaxNodes, "documents");
                      // Poll until complete
                      const poll = setInterval(async () => {
                        try {
                          const prog = await fetchKGBuildProgress(projectId, "documents");
                          if (!prog.active) {
                            clearInterval(poll);
                            setDocKgBuilding(false);
                            loadDocKgInfo();
                          }
                        } catch {
                          clearInterval(poll);
                          setDocKgBuilding(false);
                        }
                      }, 3000);
                    } catch {
                      setDocKgBuilding(false);
                    }
                  }}
                  className="ml-3 rounded border border-accent/40 px-2 py-0.5 text-accent transition hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {docKgInfo?.exists ? (docKgInfo.chunks_stale ? "Rebuild" : "Rebuild") : "Build"}
                </button>
              </div>
            )}

            {/* Chunk KG warning when chunks source and no KG */}
            {graphRagKgSource === "chunks" && kgInfo && !kgInfo.exists && (
              <p className="text-xs text-amber-400">
                No knowledge graph found — build one in the KG section above before using Graph RAG types.
              </p>
            )}
            {GRAPH_RAG_CATEGORIES.map((cat) => {
              const enabled = enabledGraphRag[cat.key] ?? false;
              const pct = graphRagDistribution[cat.key] ?? 0;
              return (
                <div key={cat.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => {
                          const next = { ...enabledGraphRag, [cat.key]: e.target.checked };
                          setEnabledGraphRag(next);
                          const enabledKeys = GRAPH_RAG_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => next[k]);
                          if (enabledKeys.length > 0) {
                            const share = Math.round(100 / enabledKeys.length);
                            const newDist: Record<string, number> = {};
                            enabledKeys.forEach((k, i) => {
                              newDist[k] = i === enabledKeys.length - 1
                                ? 100 - share * (enabledKeys.length - 1)
                                : share;
                            });
                            GRAPH_RAG_CATEGORIES.forEach((c) => {
                              if (!next[c.key]) newDist[c.key] = 0;
                            });
                            setGraphRagDistribution(newDist);
                          }
                        }}
                        className="h-3.5 w-3.5 rounded border-border bg-input text-accent accent-accent"
                        disabled={generating}
                      />
                      <div>
                        <label className="text-xs font-medium text-text-secondary">
                          {cat.label}
                        </label>
                        <p className="text-[11px] leading-tight text-text-muted">{cat.description}</p>
                      </div>
                    </div>
                    {enabled && (
                      <div className="flex shrink-0 items-baseline gap-0.5">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={pct}
                          onFocus={(e) => e.target.select()}
                          onChange={(e) => {
                            const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                            setGraphRagDistribution((prev) => {
                              const enabledKeys = GRAPH_RAG_CATEGORIES
                                .map((c) => c.key)
                                .filter((k) => enabledGraphRag[k] && k !== cat.key);
                              const remaining = 100 - raw;
                              const distributed = redistributeEvenly(enabledKeys, remaining, prev);
                              return { ...prev, [cat.key]: raw, ...distributed };
                            });
                          }}
                          disabled={generating}
                          className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                        />
                        <span className="text-xs text-text-muted">%</span>
                      </div>
                    )}
                  </div>
                  {enabled && (
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={pct}
                      onChange={(e) => {
                        const raw = Number(e.target.value);
                        setGraphRagDistribution((prev) => {
                          const enabledKeys = GRAPH_RAG_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => enabledGraphRag[k] && k !== cat.key);
                          const remaining = 100 - raw;
                          const distributed = redistributeEvenly(enabledKeys, remaining, prev);
                          return { ...prev, [cat.key]: raw, ...distributed };
                        });
                      }}
                      className="w-full accent-accent"
                      disabled={generating}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={generating || (chunksRequired && chunkConfigId === "")}
        className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generating ? (
          <span className="flex items-center gap-2">
            <svg
              className="h-4 w-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Generating… this may take a few minutes
          </span>
        ) : (
          "Generate Test Set"
        )}
      </button>
    </div>
  );
}

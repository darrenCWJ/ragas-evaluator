import { useState, useEffect, useCallback } from 'react';
import type {
  ChunkConfig,
  TestSetCreate,
  SavedPersona,
  GenerationProgress,
  KnowledgeGraphInfo,
  KGBuildProgress,
} from '../../lib/api';
import {
  createTestSet,
  fetchPersonas,
  fetchGenerationProgress,
  fetchKnowledgeGraphInfo,
  fetchKGBuildProgress,
  ApiError,
} from '../../lib/api';
import { usePolling } from '../../hooks/usePolling';
import {
  QUERY_TYPES,
  QUESTION_CATEGORIES,
  DEFAULT_CATEGORIES,
  GRAPH_RAG_CATEGORIES,
  DEFAULT_GRAPH_RAG_DIST,
  DEFAULT_DISTRIBUTION,
} from './generate/constants';
import DistributionSliders from './generate/DistributionSliders';
import GenerateProgress from './generate/GenerateProgress';
import GraphRagSection from './generate/GraphRagSection';
import KGBuildPanel from './generate/KGBuildPanel';
import PersonaSection from './generate/PersonaSection';
import type { PersonaDraft } from './generate/PersonaSection';
import SourceFields from './generate/SourceFields';

interface Props {
  projectId: number;
  chunkConfigs: ChunkConfig[];
  onTestSetCreated: () => void;
}

export default function TestSetGenerate({ projectId, chunkConfigs, onTestSetCreated }: Props) {
  const [chunkConfigId, setChunkConfigId] = useState<number | ''>('');
  const [name, setName] = useState('');
  const [testsetSize, setTestsetSize] = useState<string>('10');
  const [numPersonas, setNumPersonas] = useState<string>('3');
  const [usePersonas, setUsePersonas] = useState(true);
  const [customPersonas, setCustomPersonas] = useState<PersonaDraft[]>([]);
  const [chunkSampleSize, setChunkSampleSize] = useState<string>('100');
  const [numWorkers, setNumWorkers] = useState(4);
  const [queryDistribution, setQueryDistribution] = useState<Record<string, number>>({
    ...DEFAULT_DISTRIBUTION,
  });
  const [useCustomDistribution, setUseCustomDistribution] = useState(false);
  const [useCategories, setUseCategories] = useState(false);
  const [enabledCategories, setEnabledCategories] = useState<Record<string, boolean>>({
    typical: true,
    in_knowledge_base: true,
    edge: true,
    out_of_knowledge_base: true,
  });
  const [categoryDistribution, setCategoryDistribution] = useState<Record<string, number>>({
    ...DEFAULT_CATEGORIES,
  });
  const [useGraphRag, setUseGraphRag] = useState(false);
  const [graphRagKgSource, setGraphRagKgSource] = useState<'chunks' | 'documents'>('chunks');
  const [docKgInfo, setDocKgInfo] = useState<KnowledgeGraphInfo | null>(null);
  const [docKgBuilding, setDocKgBuilding] = useState(false);
  const [enabledGraphRag, setEnabledGraphRag] = useState<Record<string, boolean>>({
    bridge: true,
    comparative: true,
    community: true,
  });
  const [graphRagDistribution, setGraphRagDistribution] = useState<Record<string, number>>({
    ...DEFAULT_GRAPH_RAG_DIST,
  });
  const [useKgAsSource, setUseKgAsSource] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [activeTestSetId, setActiveTestSetId] = useState<number | null>(null);
  const [savedPersonas, setSavedPersonas] = useState<SavedPersona[]>([]);
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sizeError, setSizeError] = useState<string | null>(null);
  const [personasError, setPersonasError] = useState<string | null>(null);
  const [kgInfo, setKgInfo] = useState<KnowledgeGraphInfo | null>(null);
  const [kgBuilding, setKgBuilding] = useState(false);
  const [kgProgress, setKgProgress] = useState<KGBuildProgress | null>(null);
  const [overlapMaxNodes, setOverlapMaxNodes] = useState<number | null>(500);
  const [fastKgMode, setFastKgMode] = useState(false);

  const loadSavedPersonas = useCallback(
    () =>
      fetchPersonas(projectId)
        .then(setSavedPersonas)
        .catch(() => {
          // silent — not critical
        }),
    [projectId],
  );

  const loadDocKgInfo = useCallback(
    () =>
      fetchKnowledgeGraphInfo(projectId, 'documents')
        .then(setDocKgInfo)
        .catch(() => {
          // silent
        }),
    [projectId],
  );

  const loadKgInfo = useCallback(
    () =>
      fetchKnowledgeGraphInfo(projectId)
        .then(async (info) => {
          setKgInfo(info);
          // Check if a build is actively running (e.g. page refresh mid-build)
          const progress = await fetchKGBuildProgress(projectId);
          if (progress.active) {
            setKgBuilding(true);
            setKgProgress(progress);
          }
        })
        .catch(() => {
          // silent
        }),
    [projectId],
  );

  useEffect(() => {
    void loadSavedPersonas();
    void loadKgInfo();
    void loadDocKgInfo();
  }, [loadSavedPersonas, loadKgInfo, loadDocKgInfo]);

  // On mount: check if a generation is already running and reconnect to it
  useEffect(() => {
    fetchGenerationProgress(projectId)
      .then((p) => {
        if (p.active || p.status === 'generating') {
          setGenerating(true);
          setProgress(p);
          if (p.test_set_id) setActiveTestSetId(p.test_set_id);
        }
      })
      .catch(() => {});
  }, [projectId]);

  // Poll KG build progress
  usePolling(
    async () => {
      const p = await fetchKGBuildProgress(projectId);
      setKgProgress(p);
      if (!p.active) {
        setKgBuilding(false);
        setKgProgress(null);
        loadKgInfo();
        return 'stop';
      }
      return 'continue';
    },
    3000,
    kgBuilding,
    () => {
      setError(
        'Lost connection while checking KG build progress. The build may still be running — refresh to reconnect.',
      );
      setKgBuilding(false);
    },
  );

  // Poll generation progress while generating
  usePolling(
    async () => {
      const p = await fetchGenerationProgress(projectId);
      setProgress(p);
      // Sync activeTestSetId from progress if not already set
      if (p.test_set_id) setActiveTestSetId(p.test_set_id);

      if (p.status === 'completed') {
        setGenerating(false);
        onTestSetCreated();
        return 'stop';
      }
      if (p.status === 'cancelled') {
        setGenerating(false);
        return 'stop';
      }
      if (p.status === 'failed') {
        setError(p.error_message || 'Test generation failed');
        setGenerating(false);
        return 'stop';
      }
      return 'continue';
    },
    2000,
    generating,
    () => {
      setError(
        'Lost connection while checking generation progress. Generation may still be running — refresh to reconnect.',
      );
      setGenerating(false);
    },
  );

  const validateSize = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 400) {
      setSizeError('Must be between 1 and 400');
      return false;
    }
    setSizeError(null);
    return true;
  };

  const validatePersonas = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 10) {
      setPersonasError('Must be between 1 and 10');
      return false;
    }
    setPersonasError(null);
    return true;
  };

  // Chunk config not required when using KG as source, or when only Graph RAG (Documents) categories
  const chunksRequired = !(
    useKgAsSource ||
    (useGraphRag && graphRagKgSource === 'documents' && !useCategories)
  );

  const handleGenerate = async () => {
    setError(null);
    const sizeOk = validateSize(testsetSize);
    const personasOk = !usePersonas || validatePersonas(numPersonas);
    if (!sizeOk || !personasOk || (chunksRequired && chunkConfigId === '')) return;

    const parsedSize = Number(testsetSize);
    const parsedPersonas = Number(numPersonas);
    const parsedChunkSample = Number(chunkSampleSize) || 0;

    try {
      const config: TestSetCreate = {
        use_kg_as_source: useKgAsSource || undefined,
        fast_kg_mode: fastKgMode || undefined,
        chunk_config_id: !useKgAsSource && chunksRequired ? (chunkConfigId as number) : undefined,
        testset_size: parsedSize,
        num_personas: usePersonas ? parsedPersonas : undefined,
        use_personas: usePersonas,
        query_distribution: useCustomDistribution
          ? Object.fromEntries(Object.entries(queryDistribution).map(([k, v]) => [k, v / 100]))
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
        const valid = customPersonas.filter((p) => p.name.trim() && p.role_description.trim());
        if (valid.length > 0) {
          config.custom_personas = valid.map((p) => ({
            name: p.name.trim(),
            role_description: p.role_description.trim(),
            question_style: p.question_style.trim(),
          }));
        }
      }

      // POST returns immediately — generation runs in background
      const created = await createTestSet(projectId, config);
      setActiveTestSetId(created.id);

      // Reset form
      setName('');
      setChunkConfigId('');
      setTestsetSize('10');
      setNumPersonas('3');
      setUsePersonas(true);
      setCustomPersonas([]);
      setChunkSampleSize('100');
      setNumWorkers(4);
      setUseCustomDistribution(false);
      setQueryDistribution({ ...DEFAULT_DISTRIBUTION });
      setUseCategories(false);
      setEnabledCategories({
        typical: true,
        in_knowledge_base: true,
        edge: true,
        out_of_knowledge_base: true,
      });
      setCategoryDistribution({ ...DEFAULT_CATEGORIES });
      setUseGraphRag(false);
      setGraphRagKgSource('chunks');
      setDocKgInfo(null);
      setEnabledGraphRag({ bridge: true, comparative: true, community: true });
      setGraphRagDistribution({ ...DEFAULT_GRAPH_RAG_DIST });

      // Enter generating state — polling will detect completion
      setProgress(null);
      setGenerating(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError('A test set is already being generated for this project.');
        } else if (err.status === 422) {
          setError(
            err.message ||
              'No chunks found for this config. Generate chunks in the Build stage first.',
          );
        } else if (err.status === 429) {
          setError('Rate limit exceeded — wait a moment and try again.');
        } else {
          setError(err.message);
        }
      } else {
        setError((err as Error).message || 'Generation failed');
      }
    }
  };

  if (chunkConfigs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-text-muted">
          Create and generate chunks in the{' '}
          <span className="font-medium text-text-secondary">Build</span> stage first.
        </p>
      </div>
    );
  }

  if (generating) {
    return (
      <GenerateProgress
        projectId={projectId}
        activeTestSetId={activeTestSetId}
        progress={progress}
        testsetSize={testsetSize}
      />
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Generate Test Set
      </h3>

      <div className="grid gap-3 sm:grid-cols-2">
        {/* Source, chunk config, name, size, sample size, workers */}
        <SourceFields
          chunkConfigs={chunkConfigs}
          generating={generating}
          useKgAsSource={useKgAsSource}
          setUseKgAsSource={setUseKgAsSource}
          chunkConfigId={chunkConfigId}
          setChunkConfigId={setChunkConfigId}
          useGraphRag={useGraphRag}
          graphRagKgSource={graphRagKgSource}
          kgInfo={kgInfo}
          name={name}
          setName={setName}
          testsetSize={testsetSize}
          setTestsetSize={setTestsetSize}
          validateSize={validateSize}
          sizeError={sizeError}
          chunkSampleSize={chunkSampleSize}
          setChunkSampleSize={setChunkSampleSize}
          numWorkers={numWorkers}
          setNumWorkers={setNumWorkers}
        />

        {/* Knowledge Graph */}
        {chunkConfigId !== '' && (
          <KGBuildPanel
            projectId={projectId}
            chunkConfigId={chunkConfigId as number}
            generating={generating}
            kgInfo={kgInfo}
            setKgInfo={setKgInfo}
            kgBuilding={kgBuilding}
            setKgBuilding={setKgBuilding}
            kgProgress={kgProgress}
            overlapMaxNodes={overlapMaxNodes}
            setOverlapMaxNodes={setOverlapMaxNodes}
            fastKgMode={fastKgMode}
            setFastKgMode={setFastKgMode}
            onError={setError}
          />
        )}

        {/* Personas: toggle, count, custom editor, saved personas */}
        <PersonaSection
          projectId={projectId}
          generating={generating}
          usePersonas={usePersonas}
          setUsePersonas={setUsePersonas}
          numPersonas={numPersonas}
          setNumPersonas={setNumPersonas}
          personasError={personasError}
          validatePersonas={validatePersonas}
          customPersonas={customPersonas}
          setCustomPersonas={setCustomPersonas}
          savedPersonas={savedPersonas}
          setSavedPersonas={setSavedPersonas}
          loadSavedPersonas={loadSavedPersonas}
          chunkConfigId={chunkConfigId}
          kgInfo={kgInfo}
          chunksRequired={chunksRequired}
          useKgAsSource={useKgAsSource}
          onError={setError}
        />

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
            <DistributionSliders
              categories={QUESTION_CATEGORIES}
              distribution={categoryDistribution}
              setDistribution={setCategoryDistribution}
              enabled={enabledCategories}
              setEnabled={setEnabledCategories}
              disabled={generating}
            />
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
            <DistributionSliders
              categories={QUERY_TYPES}
              distribution={queryDistribution}
              setDistribution={setQueryDistribution}
              disabled={generating}
            />
          </div>
        )}

        {/* Graph RAG question types: toggle, KG source, doc KG status, sliders */}
        <GraphRagSection
          projectId={projectId}
          generating={generating}
          useGraphRag={useGraphRag}
          setUseGraphRag={setUseGraphRag}
          graphRagKgSource={graphRagKgSource}
          setGraphRagKgSource={setGraphRagKgSource}
          kgInfo={kgInfo}
          docKgInfo={docKgInfo}
          docKgBuilding={docKgBuilding}
          setDocKgBuilding={setDocKgBuilding}
          loadDocKgInfo={loadDocKgInfo}
          overlapMaxNodes={overlapMaxNodes}
          enabledGraphRag={enabledGraphRag}
          setEnabledGraphRag={setEnabledGraphRag}
          graphRagDistribution={graphRagDistribution}
          setGraphRagDistribution={setGraphRagDistribution}
        />
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
        disabled={
          generating ||
          (chunksRequired && chunkConfigId === '') ||
          (useKgAsSource && !(kgInfo?.exists && kgInfo.is_complete))
        }
        className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generating ? (
          <span className="flex items-center gap-2">
            <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
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
          'Generate Test Set'
        )}
      </button>
    </div>
  );
}

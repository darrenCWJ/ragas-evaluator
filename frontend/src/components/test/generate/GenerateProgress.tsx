import { useState, useEffect } from 'react';
import type { GenerationProgress } from '../../../lib/api';
import { cancelTestSetGeneration } from '../../../lib/api';

const STAGE_LABELS: Record<string, string> = {
  initializing: 'Initializing',
  building_knowledge_graph: 'Building knowledge graph',
  kg_resuming_from_checkpoint: 'Resuming from checkpoint',
  kg_loaded_from_cache: 'Loaded knowledge graph from cache',
  kg_extracting_headlines: 'Extracting headlines from chunks',
  kg_splitting_headlines: 'Splitting chunks by headlines',
  kg_extracting_keyphrases: 'Extracting keyphrases (slowest step)',
  kg_building_overlap: 'Building overlap scores between nodes',
  kg_filtering_nodes: 'Filtering low-quality nodes',
  kg_extracting_themes: 'Extracting themes from chunks',
  kg_extracting_entities: 'Extracting named entities',
  kg_building_summary_similarity: 'Building summary similarity links',
  kg_building_entity_overlap: 'Building entity overlap scores',
  generating_personas: 'Generating personas',
  generating_questions: 'Synthesizing questions',
  generating_special_categories: 'Generating edge & out-of-KB questions',
  generating_bridge_questions: 'Generating bridge questions',
  generating_comparative_questions: 'Generating comparative questions',
  generating_community_questions: 'Generating community questions',
};

interface GenerateProgressProps {
  projectId: number;
  activeTestSetId: number | null;
  progress: GenerationProgress | null;
  testsetSize: string;
}

/** Full-panel progress display shown while a test set is being generated. */
export default function GenerateProgress({
  projectId,
  activeTestSetId,
  progress,
  testsetSize,
}: GenerateProgressProps) {
  const [elapsed, setElapsed] = useState(0);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  // When KG is loaded from cache, show a single "loaded from cache" step
  // instead of the individual KG build sub-steps.
  const currentStage = progress?.stage ?? 'initializing';
  const kgCached =
    currentStage === 'kg_loaded_from_cache' ||
    (!currentStage.startsWith('kg_') &&
      currentStage !== 'building_knowledge_graph' &&
      currentStage !== 'initializing');

  const STAGE_ORDER = kgCached
    ? [
        'kg_loaded_from_cache',
        'generating_personas',
        'generating_questions',
        'generating_special_categories',
        'generating_bridge_questions',
        'generating_comparative_questions',
        'generating_community_questions',
      ]
    : [
        'building_knowledge_graph',
        'kg_extracting_headlines',
        'kg_splitting_headlines',
        'kg_extracting_keyphrases',
        'kg_building_overlap',
        'kg_extracting_summaries',
        'kg_filtering_nodes',
        'kg_embedding_summaries',
        'kg_extracting_themes',
        'kg_extracting_entities',
        'kg_building_summary_similarity',
        'kg_building_entity_overlap',
        'generating_personas',
        'generating_questions',
        'generating_special_categories',
        'generating_bridge_questions',
        'generating_comparative_questions',
        'generating_community_questions',
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
                  <svg
                    className="h-4 w-4 shrink-0 text-score-high"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : isActive ? (
                  <svg
                    className="h-4 w-4 shrink-0 animate-spin text-accent"
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
                ) : (
                  <div className="h-4 w-4 shrink-0 rounded-full border border-border" />
                )}
                <span
                  className={`text-xs ${i <= currentStageIdx ? 'text-text-secondary' : 'text-text-muted'}`}
                >
                  {label}
                </span>
              </div>
            );
          })}
        </div>

        <p className="text-xs text-text-muted">
          This may take a few minutes depending on chunk count.
        </p>

        {/* Cancel button */}
        <button
          onClick={async () => {
            if (!activeTestSetId || cancelling) return;
            setCancelling(true);
            try {
              await cancelTestSetGeneration(projectId, activeTestSetId);
            } catch {
              setCancelling(false);
            }
          }}
          disabled={cancelling || !activeTestSetId}
          className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-1.5 text-xs font-medium text-red-400 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {cancelling ? 'Cancelling…' : 'Cancel generation'}
        </button>
      </div>
    </div>
  );
}

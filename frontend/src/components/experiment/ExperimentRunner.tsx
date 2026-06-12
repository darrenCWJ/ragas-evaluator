import { useState, useEffect } from 'react';
import { fetchCustomMetrics, fetchJudgeModels, fetchProject } from '../../lib/api';
import type { Experiment, CustomMetric, JudgeModel, JudgeModelsResponse } from '../../lib/api';
import { useExperimentStream } from '../../hooks/useExperimentStream';
import MetricSelection, { CONTEXT_REQUIRED_METRICS } from './runner/MetricSelection';
import RubricsForm, { DEFAULT_RUBRICS } from './runner/RubricsForm';
import JudgeSettings, { FALLBACK_MODELS } from './runner/JudgeSettings';
import RunLog from './runner/RunLog';

interface Props {
  projectId: number;
  experiment: Experiment;
  onComplete: () => void;
}

export default function ExperimentRunner({ projectId, experiment, onComplete }: Props) {
  const isBotExperiment = experiment.bot_config_id != null;
  const connectorType = experiment.connector_type ?? null;
  const botReturnsContexts = experiment.bot_returns_contexts ?? false;
  const hasContexts =
    !isBotExperiment || botReturnsContexts || (experiment.has_reference_contexts ?? false);
  const hasRefSql = experiment.has_reference_sql ?? false;
  const hasRefData = experiment.has_reference_data ?? false;

  const disabledMetrics = (() => {
    const disabled = hasContexts ? new Set<string>() : new Set(CONTEXT_REQUIRED_METRICS);
    if (!hasRefSql) disabled.add('sql_semantic_equivalence');
    if (!hasRefData) disabled.add('datacompy_score');
    return disabled;
  })();

  const [customMetrics, setCustomMetrics] = useState<CustomMetric[]>([]);
  const [selectedMetrics, setSelectedMetrics] = useState<Set<string>>(new Set());

  const isCsvExperiment = connectorType === 'csv';
  const [concurrency, setConcurrency] = useState(isCsvExperiment ? 10 : isBotExperiment ? 2 : 5);
  const [rubrics, setRubrics] = useState<Record<string, string>>({ ...DEFAULT_RUBRICS });
  // Multi-model judge state — seeded with fallback list so dropdowns are usable immediately
  const [availableModels, setAvailableModels] = useState<JudgeModel[]>(FALLBACK_MODELS);
  const [judgeModelSlots, setJudgeModelSlots] = useState<string[]>([
    'gpt-4o-mini',
    'gpt-4o-mini',
    'gpt-4o-mini',
  ]);
  const [judgeTempSlots, setJudgeTempSlots] = useState<number[]>([0.3, 0.525, 0.75]);

  const {
    runState,
    setRunState,
    errorCount,
    elapsed,
    completedLog,
    experimentMeta,
    refreshing,
    startRun,
    abort,
    refreshStatus,
  } = useExperimentStream({ projectId, experiment, onComplete });

  // Derived: judge selected + missing key check
  const judgeSelected =
    selectedMetrics.has('multi_llm_judge') ||
    customMetrics.some(
      (cm) =>
        (cm.metric_type === 'criteria_judge' || cm.metric_type === 'reference_judge') &&
        selectedMetrics.has(cm.name),
    );
  const missingKeyModels = judgeSelected
    ? judgeModelSlots.filter((id) => {
        const m = availableModels.find((am) => am.id === id);
        return m ? !m.available : false;
      })
    : [];
  const hasMissingKeys = missingKeyModels.length > 0;

  // Load custom metrics, available judge models, and project judge defaults
  useEffect(() => {
    fetchCustomMetrics(projectId)
      .then(setCustomMetrics)
      .catch(() => setCustomMetrics([]));

    // Load judge models + env-var defaults, then overlay project-level saved defaults
    Promise.all([
      fetchJudgeModels().catch(
        (): JudgeModelsResponse => ({
          models: [],
          default_model_assignments: null,
          temp_min: 0.3,
          temp_max: 0.75,
        }),
      ),
      fetchProject(projectId).catch(() => null),
    ]).then(([judgeData, proj]) => {
      setAvailableModels(judgeData.models.length > 0 ? judgeData.models : FALLBACK_MODELS);

      // Priority: project saved > env-var defaults > hardcoded fallback
      const savedAssignments = proj?.judge_model_assignments;
      const assignments =
        savedAssignments && savedAssignments.length > 0
          ? savedAssignments
          : (judgeData.default_model_assignments ?? null);

      if (assignments && assignments.length > 0) {
        setJudgeModelSlots(assignments);
        const tMin = judgeData.temp_min;
        const tMax = judgeData.temp_max;
        const n = assignments.length;
        setJudgeTempSlots(
          n === 1
            ? [tMin]
            : Array.from(
                { length: n },
                (_, i) => Math.round((tMin + ((tMax - tMin) / (n - 1)) * i) * 1000) / 1000,
              ),
        );
      }
    });
  }, [projectId]);

  const handleRun = () => {
    if (selectedMetrics.size === 0) return;
    startRun({
      metrics: Array.from(selectedMetrics),
      rubrics: selectedMetrics.has('rubrics_score') ? rubrics : null,
      concurrency,
      judgeModelSlots,
      judgeTempSlots,
    });
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div>
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-accent">
        Run Experiment
      </h3>

      {/* Idle — metric selection + run button */}
      {runState.phase === 'idle' && (
        <div className="space-y-4">
          {!hasContexts && (
            <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-300/80">
              {connectorType
                ? `The ${connectorType} connector does not return retrieved contexts — context-dependent metrics are disabled.`
                : 'No retrieved contexts available — context-dependent metrics are disabled.'}
            </div>
          )}

          <MetricSelection
            customMetrics={customMetrics}
            selectedMetrics={selectedMetrics}
            setSelectedMetrics={setSelectedMetrics}
            disabledMetrics={disabledMetrics}
            hasContexts={hasContexts}
          />

          {/* Rubric editor — shown when rubrics_score is selected */}
          {selectedMetrics.has('rubrics_score') && (
            <RubricsForm rubrics={rubrics} setRubrics={setRubrics} />
          )}

          {/* LLM Judge Settings — shown when multi_llm_judge, criteria_judge, or reference_judge is selected */}
          {judgeSelected && (
            <JudgeSettings
              projectId={projectId}
              availableModels={availableModels}
              judgeModelSlots={judgeModelSlots}
              setJudgeModelSlots={setJudgeModelSlots}
              judgeTempSlots={judgeTempSlots}
              setJudgeTempSlots={setJudgeTempSlots}
            />
          )}

          {/* Concurrency control */}
          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-text-secondary">Parallel questions</label>
            <input
              type="range"
              min={1}
              max={20}
              value={concurrency}
              onChange={(e) => setConcurrency(Number(e.target.value))}
              className="h-1.5 w-32 cursor-pointer accent-accent"
            />
            <span className="w-6 text-center text-xs font-mono text-text-primary">
              {concurrency}
            </span>
            <span className="text-xs text-text-muted">
              {concurrency === 1 ? '(sequential)' : concurrency >= 15 ? '(aggressive)' : ''}
            </span>
          </div>

          <div className="flex flex-col items-start gap-1">
            <button
              onClick={handleRun}
              disabled={selectedMetrics.size === 0 || hasMissingKeys}
              className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Run Experiment
            </button>
            {hasMissingKeys && (
              <p className="text-2xs text-yellow-500">
                Missing API key for: {[...new Set(missingKeyModels)].join(', ')}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Running — progress + live Q&A feed */}
      {runState.phase === 'running' && (
        <div className="space-y-4">
          {/* Experiment info banner */}
          {experimentMeta && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-card/50 px-3 py-2">
              <span className="text-xs font-medium text-text-primary">{experimentMeta.name}</span>
              <span className="text-xs text-text-muted">{experimentMeta.model}</span>
              <span className="text-xs text-text-muted">{experimentMeta.testSet}</span>
            </div>
          )}

          {/* Progress bar */}
          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="font-medium text-text-primary">
                {runState.total > 0
                  ? `${runState.current} / ${runState.total} questions`
                  : 'Starting...'}
              </span>
              <span className="font-mono text-text-muted">{formatTime(elapsed)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-elevated">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{
                  width:
                    runState.total > 0 ? `${(runState.current / runState.total) * 100}%` : '0%',
                }}
              />
            </div>
            {runState.total > 0 && (
              <p className="mt-1 text-right text-xs text-text-muted">
                {Math.round((runState.current / runState.total) * 100)}%
              </p>
            )}
          </div>

          {/* Initializing status — shown before any question completes */}
          {runState.current === 0 && runState.inFlightDetails.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
              {runState.currentQuestion || 'Initializing...'}
            </div>
          )}

          {/* In-flight pipeline + live Q&A feed */}
          <RunLog
            inFlightDetails={runState.inFlightDetails}
            completedLog={completedLog}
            connectorType={connectorType}
            isBotExperiment={isBotExperiment}
          />

          {/* Abort */}
          <button
            onClick={abort}
            className="rounded-lg border border-red-500/30 px-4 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/10"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Completed */}
      {runState.phase === 'completed' && errorCount === 0 && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3">
          <p className="text-sm font-medium text-green-300">Experiment completed</p>
          <p className="mt-0.5 text-xs text-green-300/70">
            {runState.resultCount} results recorded in {formatTime(elapsed)}
          </p>
        </div>
      )}

      {/* Completed with partial failures */}
      {runState.phase === 'completed' && errorCount > 0 && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3">
          <p className="text-sm font-medium text-yellow-300">Experiment completed with errors</p>
          <p className="mt-0.5 text-xs text-yellow-300/70">
            {runState.resultCount - errorCount} of {runState.resultCount} questions succeeded,{' '}
            {errorCount} failed &middot; {formatTime(elapsed)}
          </p>
        </div>
      )}

      {/* Error */}
      {runState.phase === 'error' && (
        <div className="space-y-3">
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
            <p className="text-sm font-medium text-red-300">Experiment failed</p>
            <p className="mt-0.5 text-xs text-red-300/70">{runState.message}</p>
          </div>
          <button
            onClick={() => setRunState({ phase: 'idle' })}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent"
          >
            Back to metrics
          </button>
        </div>
      )}

      {/* Connection lost */}
      {runState.phase === 'connection_lost' && (
        <div className="space-y-3">
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3">
            <p className="text-sm font-medium text-yellow-300">Connection lost</p>
            <p className="mt-0.5 text-xs text-yellow-300/70">
              Last progress: {runState.lastCurrent} / {runState.lastTotal} questions completed
              before disconnect
            </p>
          </div>
          <button
            onClick={refreshStatus}
            disabled={refreshing}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent disabled:opacity-40"
          >
            {refreshing ? 'Checking...' : 'Refresh Status'}
          </button>
        </div>
      )}
    </div>
  );
}

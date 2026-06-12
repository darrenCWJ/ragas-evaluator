import { useState, useEffect, useRef, useCallback } from 'react';
import {
  runExperimentSSE,
  observeExperimentProgress,
  fetchExperiment,
  fetchProgressSnapshot,
  cancelExperiment,
} from '../lib/api';
import type {
  Experiment,
  ExperimentSSEHandle,
  SSEStartedEvent,
  SSEProgressEvent,
  SSECompletedEvent,
  SSEErrorEvent,
  SSECompletionItem,
  InFlightDetail,
} from '../lib/api';

export type RunState =
  | { phase: 'idle' }
  | {
      phase: 'running';
      current: number;
      total: number;
      currentQuestion: string;
      lastError?: string;
      inFlight: string[];
      scoringMetrics: string[];
      inFlightDetails: InFlightDetail[];
    }
  | { phase: 'completed'; resultCount: number }
  | { phase: 'error'; message: string }
  | { phase: 'connection_lost'; lastCurrent: number; lastTotal: number };

export interface ExperimentMeta {
  name: string;
  model: string;
  testSet: string;
}

export interface StartRunOptions {
  metrics: string[];
  rubrics: Record<string, string> | null;
  concurrency: number;
  judgeModelSlots: string[];
  judgeTempSlots: number[];
}

interface UseExperimentStreamArgs {
  projectId: number;
  experiment: Experiment;
  onComplete: () => void;
}

const FRESH_RUNNING: RunState = {
  phase: 'running',
  current: 0,
  total: 0,
  currentQuestion: '',
  inFlight: [],
  scoringMetrics: [],
  inFlightDetails: [],
};

/**
 * Owns the SSE lifecycle for running an experiment: live progress state,
 * the completed-items log, the elapsed timer, auto-reconnect to an
 * already-running experiment, and abort/refresh actions.
 *
 * The same event handling is shared between a fresh run (`startRun`) and
 * the auto-reconnect observer.
 */
export function useExperimentStream({
  projectId,
  experiment,
  onComplete,
}: UseExperimentStreamArgs) {
  const [runState, setRunState] = useState<RunState>(() =>
    experiment.status === 'running'
      ? { ...FRESH_RUNNING, currentQuestion: 'Reconnecting...' }
      : { phase: 'idle' },
  );
  const [errorCount, setErrorCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [completedLog, setCompletedLog] = useState<SSECompletionItem[]>([]);
  const [experimentMeta, setExperimentMeta] = useState<ExperimentMeta | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const handleRef = useRef<ExperimentSSEHandle | null>(null);

  // Elapsed timer — runs while the experiment is in the running phase
  useEffect(() => {
    if (runState.phase !== 'running') return;
    const id = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(id);
  }, [runState.phase]);

  // Cleanup on unmount — only abort the SSE observer, NOT the background task
  useEffect(() => {
    return () => {
      handleRef.current?.abort();
    };
  }, []);

  // The single set of SSE callbacks shared by startRun and auto-reconnect
  const makeCallbacks = useCallback(
    () => ({
      onStarted: (data: SSEStartedEvent) => {
        if (data.experiment_name) {
          setExperimentMeta({
            name: data.experiment_name,
            model: data.model ?? '',
            testSet: data.test_set_name ?? '',
          });
        }
        // Update total from the started event, but preserve any progress already shown
        setRunState((prev) =>
          prev.phase === 'running'
            ? { ...prev, total: data.total_questions }
            : { ...FRESH_RUNNING, total: data.total_questions },
        );
      },
      onProgress: (data: SSEProgressEvent) => {
        if (data.error) setErrorCount((prev) => prev + 1);
        if (data.new_completions?.length) {
          setCompletedLog((prev) => [...prev, ...data.new_completions!]);
        }
        setRunState({
          phase: 'running',
          current: data.current,
          total: data.total,
          currentQuestion: data.question,
          lastError: data.error || undefined,
          inFlight: data.in_flight ?? [],
          scoringMetrics: data.scoring_metrics ?? [],
          inFlightDetails: data.in_flight_details ?? [],
        });
      },
      onCompleted: (data: SSECompletedEvent) => {
        setRunState({ phase: 'completed', resultCount: data.result_count });
        onComplete();
      },
      onError: (data: SSEErrorEvent) => {
        setRunState({ phase: 'error', message: data.message });
        onComplete();
      },
      onConnectionError: (_err: Error, lastProgress: SSEProgressEvent | null) => {
        setRunState({
          phase: 'connection_lost',
          lastCurrent: lastProgress?.current ?? 0,
          lastTotal: lastProgress?.total ?? 0,
        });
      },
    }),
    [onComplete],
  );

  // Auto-reconnect to a running experiment on mount
  useEffect(() => {
    if (experiment.status !== 'running') return;
    // Already observing
    if (handleRef.current) return;

    // Pre-populate state from snapshot so the UI shows real progress immediately
    // instead of "Initializing..." until the first SSE event arrives.
    fetchProgressSnapshot(projectId, experiment.id)
      .then((snapshot) => {
        if (!snapshot || snapshot.total === 0) return;
        setRunState((prev) => {
          if (prev.phase !== 'running' || prev.total > 0) return prev;
          return {
            phase: 'running',
            current: snapshot.current,
            total: snapshot.total,
            currentQuestion: snapshot.question,
            inFlight: snapshot.in_flight,
            scoringMetrics: snapshot.scoring_metrics,
            inFlightDetails: snapshot.in_flight_details,
          };
        });
      })
      .catch(() => {});

    handleRef.current = observeExperimentProgress(projectId, experiment.id, makeCallbacks());
  }, [experiment.status, experiment.id, projectId, makeCallbacks]);

  const startRun = ({
    metrics,
    rubrics,
    concurrency,
    judgeModelSlots,
    judgeTempSlots,
  }: StartRunOptions) => {
    setRunState({ ...FRESH_RUNNING });
    setErrorCount(0);
    setElapsed(0);
    setCompletedLog([]);
    setExperimentMeta(null);

    handleRef.current = runExperimentSSE(
      projectId,
      experiment.id,
      metrics,
      makeCallbacks(),
      rubrics,
      concurrency,
      judgeModelSlots.length,
      judgeModelSlots,
      judgeTempSlots,
    );
  };

  const abort = () => {
    // Signal the server to stop processing remaining questions
    cancelExperiment(projectId, experiment.id).catch(() => {});
    handleRef.current?.abort();
    handleRef.current = null;
    setRunState({ phase: 'idle' });
  };

  const refreshStatus = async () => {
    setRefreshing(true);
    try {
      const exp = await fetchExperiment(projectId, experiment.id);
      if (exp.status === 'completed' || exp.status === 'failed') {
        setRunState({ phase: 'idle' });
        onComplete();
      }
    } catch {
      // Stay in current state
    } finally {
      setRefreshing(false);
    }
  };

  return {
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
  };
}

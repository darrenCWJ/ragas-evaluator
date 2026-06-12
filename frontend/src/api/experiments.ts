// Experiments domain — experiment CRUD, run/progress SSE, comparison, history, delta, export, suggestions, source verification

import { request, ApiError } from './client';
import type {
  Experiment,
  ExperimentCreate,
  ExperimentResult,
  ProgressSnapshot,
  SSEStartedEvent,
  SSEProgressEvent,
  SSECompletedEvent,
  SSEErrorEvent,
  ExperimentSSECallbacks,
  ExperimentSSEHandle,
  Suggestion,
  BatchApplyResult,
  DeltaResult,
  CompareResult,
  HistoryExperiment,
  SourceVerificationResult,
} from './types';

// --- Experiment API ---

export async function fetchExperiments(projectId: number): Promise<Experiment[]> {
  return request<Experiment[]>(`/api/projects/${projectId}/experiments`);
}

export async function createExperiment(
  projectId: number,
  data: ExperimentCreate,
): Promise<Experiment> {
  return request<Experiment>(`/api/projects/${projectId}/experiments`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function fetchExperiment(
  projectId: number,
  experimentId: number,
): Promise<Experiment> {
  return request<Experiment>(`/api/projects/${projectId}/experiments/${experimentId}`);
}

export async function deleteExperiment(projectId: number, experimentId: number): Promise<void> {
  await request<void>(`/api/projects/${projectId}/experiments/${experimentId}`, {
    method: 'DELETE',
  });
}

export async function resetExperiment(
  projectId: number,
  experimentId: number,
): Promise<Experiment> {
  return request<Experiment>(`/api/projects/${projectId}/experiments/${experimentId}/reset`, {
    method: 'POST',
  });
}

export async function cancelExperiment(
  projectId: number,
  experimentId: number,
): Promise<{ status: string; experiment_id: number }> {
  return request<{ status: string; experiment_id: number }>(
    `/api/projects/${projectId}/experiments/${experimentId}/cancel`,
    { method: 'POST' },
  );
}

export async function fetchProgressSnapshot(
  projectId: number,
  experimentId: number,
): Promise<ProgressSnapshot | null> {
  try {
    return await request<ProgressSnapshot>(
      `/api/projects/${projectId}/experiments/${experimentId}/progress-snapshot`,
    );
  } catch {
    return null;
  }
}

export async function fetchExperimentResults(
  projectId: number,
  experimentId: number,
): Promise<ExperimentResult[]> {
  return request<ExperimentResult[]>(
    `/api/projects/${projectId}/experiments/${experimentId}/results`,
  );
}

// --- SSE Experiment Runner ---

export function runExperimentSSE(
  projectId: number,
  experimentId: number,
  metrics: string[] | null,
  callbacks: ExperimentSSECallbacks,
  rubrics?: Record<string, string> | null,
  concurrency?: number,
  multiLlmJudgeEvaluators?: number,
  judgeModelAssignments?: string[],
  judgeTemperatureAssignments?: number[],
): ExperimentSSEHandle {
  const controller = new AbortController();

  (async () => {
    try {
      // Fire the run endpoint (returns JSON immediately, starts background task)
      const runRes = await fetch(`/api/projects/${projectId}/experiments/${experimentId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metrics,
          rubrics: rubrics ?? null,
          concurrency: concurrency ?? 5,
          multi_llm_judge_evaluators: multiLlmJudgeEvaluators ?? 5,
          judge_model_assignments: judgeModelAssignments ?? null,
          judge_temperature_assignments: judgeTemperatureAssignments ?? null,
        }),
        signal: controller.signal,
      });

      if (!runRes.ok) {
        const body = await runRes.text().catch(() => '');
        let message = `HTTP ${runRes.status}`;
        try {
          const parsed = JSON.parse(body);
          message = parsed.detail ?? parsed.message ?? (body || message);
        } catch {
          if (body) message = body;
        }
        callbacks.onError?.({ message });
        return;
      }

      const runData = await runRes.json();

      // Emit a synthetic "started" event from the run response
      callbacks.onStarted?.({
        experiment_id: runData.experiment_id,
        total_questions: 0,
        metrics: runData.metrics ?? [],
        experiment_name: '',
        model: '',
        test_set_name: '',
      });

      // Now observe progress via the SSE progress endpoint
      const handle = observeExperimentProgress(projectId, experimentId, callbacks);
      // Wire abort through to the progress observer
      controller.signal.addEventListener('abort', () => handle.abort());
    } catch (err) {
      if ((err as DOMException).name === 'AbortError') return;
      callbacks.onConnectionError?.(err as Error, null);
    }
  })();

  return { abort: () => controller.abort() };
}

/**
 * Reconnect to a running experiment's progress stream.
 * Unlike runExperimentSSE, this uses GET /progress and does not start the experiment.
 */
export function observeExperimentProgress(
  projectId: number,
  experimentId: number,
  callbacks: ExperimentSSECallbacks,
): ExperimentSSEHandle {
  const controller = new AbortController();
  let lastProgress: SSEProgressEvent | null = null;

  (async () => {
    try {
      // Retry connection for up to 5s — the background task may not have
      // registered in the progress dict yet when called right after /run
      let res: Response | null = null;
      for (let attempt = 0; attempt < 10; attempt++) {
        res = await fetch(`/api/projects/${projectId}/experiments/${experimentId}/progress`, {
          signal: controller.signal,
        });
        if (res.ok || res.status !== 409) break;
        await new Promise((r) => setTimeout(r, 500));
      }

      if (!res || !res.ok) {
        const body = (await res?.text().catch(() => 'Unknown error')) ?? 'No response';
        callbacks.onError?.({ message: `${res?.status}: ${body}` });
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError?.({ message: 'No response stream' });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const part of parts) {
          if (!part.trim()) continue;

          let eventType = 'message';
          let dataStr = '';

          for (const line of part.split('\n')) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              dataStr = line.slice(5).trim();
            }
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);

            switch (eventType) {
              case 'started':
                callbacks.onStarted?.(data as SSEStartedEvent);
                break;
              case 'progress':
                lastProgress = data as SSEProgressEvent;
                callbacks.onProgress?.(lastProgress);
                break;
              case 'completed':
                callbacks.onCompleted?.(data as SSECompletedEvent);
                break;
              case 'error':
                callbacks.onError?.(data as SSEErrorEvent);
                break;
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (err) {
      if ((err as DOMException).name === 'AbortError') return;
      callbacks.onConnectionError?.(err as Error, lastProgress);
    }
  })();

  return { abort: () => controller.abort() };
}

// --- Suggestion API ---

export async function generateSuggestions(
  projectId: number,
  experimentId: number,
): Promise<{ suggestions: Suggestion[]; count: number }> {
  return request<{ suggestions: Suggestion[]; count: number }>(
    `/api/projects/${projectId}/experiments/${experimentId}/suggestions/generate`,
    { method: 'POST' },
  );
}

export async function fetchSuggestions(
  projectId: number,
  experimentId: number,
): Promise<Suggestion[]> {
  const data = await request<{ suggestions: Suggestion[] }>(
    `/api/projects/${projectId}/experiments/${experimentId}/suggestions`,
  );
  return data.suggestions;
}

export async function applySuggestionsBatch(
  projectId: number,
  experimentId: number,
  items: { suggestion_id: number; override_value?: string }[],
  experimentName?: string,
): Promise<BatchApplyResult> {
  return request<BatchApplyResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/suggestions/apply-batch`,
    {
      method: 'POST',
      body: JSON.stringify({
        items,
        experiment_name: experimentName || undefined,
      }),
    },
  );
}

// --- Delta API ---

export async function fetchExperimentDelta(
  projectId: number,
  experimentId: number,
): Promise<DeltaResult> {
  return request<DeltaResult>(`/api/projects/${projectId}/experiments/${experimentId}/delta`);
}

// --- Export API ---

export async function exportExperiment(
  projectId: number,
  experimentId: number,
  format: 'csv' | 'json',
): Promise<void> {
  const res = await fetch(
    `/api/projects/${projectId}/experiments/${experimentId}/export?format=${format}`,
  );

  if (!res.ok) {
    const body = await res.text().catch(() => 'Unknown error');
    throw new ApiError(res.status, body);
  }

  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] ?? `export.${format}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- Comparison API ---

export async function compareExperiments(
  projectId: number,
  experimentIds: number[],
): Promise<CompareResult> {
  const ids = experimentIds.join(',');
  return request<CompareResult>(`/api/projects/${projectId}/experiments/compare?ids=${ids}`);
}

// --- History API ---

export async function fetchExperimentHistory(projectId: number): Promise<HistoryExperiment[]> {
  const data = await request<{ experiments: HistoryExperiment[] }>(
    `/api/projects/${projectId}/experiments/history`,
  );
  return data.experiments;
}

// --- Source Verification API ---

export async function fetchSourceVerifications(
  projectId: number,
  experimentId: number,
): Promise<SourceVerificationResult> {
  return request<SourceVerificationResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/source-verifications`,
  );
}

// Metrics domain — custom metric CRUD/refinement and multi-LLM judge evaluations

import { request } from './client';
import type {
  CustomMetric,
  CustomMetricCreate,
  JudgeEvaluationsResponse,
  JudgeAnnotationSampleResult,
  JudgeReliabilityResult,
  JudgeSummaryResponse,
} from './types';

// --- Custom Metrics API ---

export async function fetchCustomMetrics(projectId: number): Promise<CustomMetric[]> {
  return request<CustomMetric[]>(`/api/projects/${projectId}/custom-metrics`);
}

export async function createCustomMetric(
  projectId: number,
  data: CustomMetricCreate,
): Promise<CustomMetric> {
  return request<CustomMetric>(`/api/projects/${projectId}/custom-metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function updateCustomMetric(
  projectId: number,
  metricId: number,
  data: CustomMetricCreate,
): Promise<CustomMetric> {
  return request<CustomMetric>(`/api/projects/${projectId}/custom-metrics/${metricId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function refineMetricDescription(
  projectId: number,
  description: string,
): Promise<{ refined_prompt: string }> {
  return request<{ refined_prompt: string }>(
    `/api/projects/${projectId}/custom-metrics/refine-description`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    },
  );
}

export async function deleteCustomMetric(projectId: number, metricId: number): Promise<void> {
  await request<{ deleted: boolean }>(`/api/projects/${projectId}/custom-metrics/${metricId}`, {
    method: 'DELETE',
  });
}

// --- Multi-LLM Judge API ---

export async function fetchJudgeEvaluations(
  projectId: number,
  experimentId: number,
  resultId: number,
  metricName?: string,
): Promise<JudgeEvaluationsResponse> {
  const url = metricName
    ? `/api/projects/${projectId}/experiments/${experimentId}/results/${resultId}/judge-evaluations?metric_name=${encodeURIComponent(metricName)}`
    : `/api/projects/${projectId}/experiments/${experimentId}/results/${resultId}/judge-evaluations`;
  return request<JudgeEvaluationsResponse>(url);
}

export async function fetchJudgeAnnotationSample(
  projectId: number,
  experimentId: number,
  metricName?: string,
): Promise<JudgeAnnotationSampleResult> {
  const url = metricName
    ? `/api/projects/${projectId}/experiments/${experimentId}/judge-annotation-sample?metric_name=${encodeURIComponent(metricName)}`
    : `/api/projects/${projectId}/experiments/${experimentId}/judge-annotation-sample`;
  return request<JudgeAnnotationSampleResult>(url);
}

export async function annotateJudgeClaim(
  projectId: number,
  experimentId: number,
  resultId: number,
  evaluationId: number,
  claimIndex: number,
  status: 'accurate' | 'inaccurate' | 'unsure',
  comment?: string,
): Promise<{ evaluation_id: number; claim_index: number; status: string }> {
  return request(
    `/api/projects/${projectId}/experiments/${experimentId}/results/${resultId}/judge-evaluations/${evaluationId}/claims/${claimIndex}/annotate`,
    { method: 'POST', body: JSON.stringify({ status, comment: comment ?? null }) },
  );
}

export async function fetchJudgeReliability(
  projectId: number,
  experimentId: number,
  metricName?: string,
): Promise<JudgeReliabilityResult> {
  const url = metricName
    ? `/api/projects/${projectId}/experiments/${experimentId}/judge-reliability?metric_name=${encodeURIComponent(metricName)}`
    : `/api/projects/${projectId}/experiments/${experimentId}/judge-reliability`;
  return request<JudgeReliabilityResult>(url);
}

export async function fetchJudgeSummary(
  projectId: number,
  experimentId: number,
  metricName?: string,
): Promise<JudgeSummaryResponse> {
  const url = metricName
    ? `/api/projects/${projectId}/experiments/${experimentId}/judge-summary?metric_name=${encodeURIComponent(metricName)}`
    : `/api/projects/${projectId}/experiments/${experimentId}/judge-summary`;
  return request<JudgeSummaryResponse>(url);
}

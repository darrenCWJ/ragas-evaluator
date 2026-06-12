// Insights domain — test set quality audits, corpus coverage, and
// per-category experiment breakdowns (the "what went wrong" endpoints)

import { request } from './client';
import type { CoverageReport, ExperimentBreakdown, QualityAuditSummary } from './types';

/**
 * Audit every question in a test set and persist per-question results to
 * `metadata.quality`. With `useLlm: true` this makes one LLM call per
 * question; `useLlm: false` runs only the free deterministic checks.
 */
export async function runQualityAudit(
  projectId: number,
  testSetId: number,
  useLlm: boolean,
): Promise<QualityAuditSummary> {
  return request<QualityAuditSummary>(
    `/api/projects/${projectId}/test-sets/${testSetId}/quality-audit`,
    {
      method: 'POST',
      body: JSON.stringify({ use_llm: useLlm }),
    },
  );
}

/** How much of the project corpus the test set actually exercises. */
export async function fetchTestSetCoverage(
  projectId: number,
  testSetId: number,
): Promise<CoverageReport> {
  return request<CoverageReport>(`/api/projects/${projectId}/test-sets/${testSetId}/coverage`);
}

/** Per-category score breakdown for an experiment, sorted weakest first. */
export async function fetchExperimentBreakdown(
  projectId: number,
  experimentId: number,
): Promise<ExperimentBreakdown> {
  return request<ExperimentBreakdown>(
    `/api/projects/${projectId}/experiments/${experimentId}/breakdown`,
  );
}

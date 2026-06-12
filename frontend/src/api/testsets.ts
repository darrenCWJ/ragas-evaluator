// Test sets domain — test sets, questions, generation lifecycle, and CSV/file upload

import { request, formRequest } from './client';
import type {
  TestSet,
  TestSetCreate,
  TestQuestion,
  TestSetSummary,
  UploadPreviewResult,
  UploadConfirmResult,
  GenerationProgress,
  CreateTestSetResponse,
} from './types';

// --- Test Set Upload API ---

export async function previewTestSetUpload(
  projectId: number,
  file: File,
): Promise<UploadPreviewResult> {
  const form = new FormData();
  form.append('file', file);
  return formRequest<UploadPreviewResult>(
    `/api/projects/${projectId}/test-sets/upload/preview`,
    form,
  );
}

export async function confirmTestSetUpload(
  projectId: number,
  file: File,
  questionColumn: string,
  answerColumn: string,
  opts?: {
    contextsColumn?: string;
    name?: string;
    referenceSqlColumn?: string;
    schemaContextsColumn?: string;
    referenceDataColumn?: string;
    categoryColumn?: string;
    turnsColumn?: string;
  },
): Promise<UploadConfirmResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('question_column', questionColumn);
  form.append('answer_column', answerColumn);
  if (opts?.contextsColumn) form.append('contexts_column', opts.contextsColumn);
  if (opts?.categoryColumn) form.append('category_column', opts.categoryColumn);
  if (opts?.turnsColumn) form.append('turns_column', opts.turnsColumn);
  if (opts?.referenceSqlColumn) form.append('reference_sql_column', opts.referenceSqlColumn);
  if (opts?.schemaContextsColumn) form.append('schema_contexts_column', opts.schemaContextsColumn);
  if (opts?.referenceDataColumn) form.append('reference_data_column', opts.referenceDataColumn);
  if (opts?.name) form.append('name', opts.name);
  return formRequest<UploadConfirmResult>(`/api/projects/${projectId}/test-sets/upload`, form);
}

// --- Test Set API ---

export async function fetchTestSets(projectId: number): Promise<TestSet[]> {
  const data = await request<{ test_sets: TestSet[] }>(`/api/projects/${projectId}/test-sets`);
  return data.test_sets;
}

export async function fetchGenerationProgress(projectId: number): Promise<GenerationProgress> {
  return request<GenerationProgress>(`/api/projects/${projectId}/test-sets/generation-progress`);
}

export async function cancelTestSetGeneration(
  projectId: number,
  testSetId: number,
): Promise<{ status: string; test_set_id: number }> {
  return request(`/api/projects/${projectId}/test-sets/${testSetId}/cancel`, {
    method: 'POST',
  });
}

export async function createTestSet(
  projectId: number,
  config: TestSetCreate,
  signal?: AbortSignal,
): Promise<CreateTestSetResponse> {
  return request<CreateTestSetResponse>(`/api/projects/${projectId}/test-sets`, {
    method: 'POST',
    body: JSON.stringify(config),
    signal,
  });
}

export async function deleteTestSet(projectId: number, testSetId: number): Promise<void> {
  await request<void>(`/api/projects/${projectId}/test-sets/${testSetId}`, {
    method: 'DELETE',
  });
}

export async function resumeTestSet(
  projectId: number,
  testSetId: number,
): Promise<{ status: string; existing_questions: number; remaining: number }> {
  return request(`/api/projects/${projectId}/test-sets/${testSetId}/resume`, {
    method: 'POST',
  });
}

export async function fetchTestQuestions(
  projectId: number,
  testSetId: number,
  status?: string,
): Promise<TestQuestion[]> {
  const qs = status ? `?status=${status}` : '';
  const data = await request<{ questions: TestQuestion[] }>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions${qs}`,
  );
  return data.questions;
}

export async function fetchTestSetSummary(
  projectId: number,
  testSetId: number,
): Promise<TestSetSummary> {
  return request<TestSetSummary>(`/api/projects/${projectId}/test-sets/${testSetId}/summary`);
}

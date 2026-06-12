// Real-user log import (reference-free test sets) and hard-case mining.

import { formRequest, request } from './client';

export interface LogImportResult {
  test_set_id: number;
  name: string;
  imported: number;
  skipped: { trivial: number; duplicate: number };
}

export interface HardCaseMineResult {
  test_set_id: number | null;
  hard_cases: number;
  variants_created: number;
  failures: number;
}

export async function importLogs(
  projectId: number,
  file: File,
  options?: { questionColumn?: string; name?: string },
): Promise<LogImportResult> {
  const form = new FormData();
  form.set('file', file);
  if (options?.questionColumn) form.set('question_column', options.questionColumn);
  if (options?.name) form.set('name', options.name);
  return formRequest(`/api/projects/${projectId}/test-sets/import-logs`, form);
}

export async function mineHardCases(
  projectId: number,
  experimentId: number,
  options?: { threshold?: number; variantsPerQuestion?: number; maxQuestions?: number },
): Promise<HardCaseMineResult> {
  return request(`/api/projects/${projectId}/experiments/${experimentId}/mine-hard-cases`, {
    method: 'POST',
    body: JSON.stringify({
      threshold: options?.threshold ?? 0.5,
      variants_per_question: options?.variantsPerQuestion ?? 2,
      max_questions: options?.maxQuestions ?? 20,
    }),
  });
}

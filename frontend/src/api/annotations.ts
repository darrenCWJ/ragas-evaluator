// Annotations domain — test-set question review and human annotation of experiment results

import { request } from './client';
import type {
  TestQuestion,
  QuestionAnnotation,
  BulkAnnotation,
  BulkAnnotationResult,
  AnnotationSampleResult,
  HumanAnnotationCreate,
  EvaluatorAccuracyResult,
} from './types';

// --- Question Annotation API ---

export async function annotateQuestion(
  projectId: number,
  testSetId: number,
  questionId: number,
  annotation: QuestionAnnotation,
): Promise<TestQuestion> {
  return request<TestQuestion>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions/${questionId}`,
    { method: 'PATCH', body: JSON.stringify(annotation) },
  );
}

export async function bulkAnnotateQuestions(
  projectId: number,
  testSetId: number,
  bulk: BulkAnnotation,
): Promise<BulkAnnotationResult> {
  return request<BulkAnnotationResult>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions/bulk`,
    { method: 'POST', body: JSON.stringify(bulk) },
  );
}

// --- Human Annotation API ---

export async function fetchAnnotationSample(
  projectId: number,
  experimentId: number,
): Promise<AnnotationSampleResult> {
  return request<AnnotationSampleResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/annotation-sample`,
  );
}

export async function submitAnnotations(
  projectId: number,
  experimentId: number,
  annotations: HumanAnnotationCreate[],
): Promise<{ experiment_id: number; submitted: number }> {
  return request<{ experiment_id: number; submitted: number }>(
    `/api/projects/${projectId}/experiments/${experimentId}/annotations`,
    { method: 'POST', body: JSON.stringify({ annotations }) },
  );
}

export async function fetchEvaluatorAccuracy(
  projectId: number,
  experimentId: number,
): Promise<EvaluatorAccuracyResult> {
  return request<EvaluatorAccuracyResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/evaluator-accuracy`,
  );
}

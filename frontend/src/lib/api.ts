// API client — typed fetch wrapper for Ragas Platform backend

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Document {
  id: number;
  filename: string;
  file_type: string;
  created_at: string;
}

export interface ChunkConfig {
  id: number;
  project_id: number;
  name: string;
  method: string;
  params: Record<string, number | string>;
  step2_method: string | null;
  step2_params: Record<string, number | string> | null;
  created_at: string;
}

export interface ChunkConfigCreate {
  name: string;
  method: string;
  params: Record<string, number | string>;
  step2_method?: string | null;
  step2_params?: Record<string, number | string> | null;
}

export interface ChunkPreviewResult {
  document_id: number;
  filename: string;
  chunks: string[];
  chunk_count: number;
}

export interface ChunkGenerateResult {
  total_chunks: number;
  documents: { document_id: number; filename: string; chunk_count: number }[];
}

// --- Embedding Config Types ---

export interface EmbeddingConfig {
  id: number;
  project_id: number;
  name: string;
  type: string;
  model_name: string;
  params: Record<string, unknown> | null;
  created_at: string;
}

export interface EmbeddingConfigCreate {
  name: string;
  type: string;
  model_name: string;
  params?: Record<string, unknown> | null;
}

export interface EmbedResult {
  total_embedded: number;
  collection?: string;
  index?: string;
}

// --- RAG Config Types ---

export interface RagConfig {
  id: number;
  project_id: number;
  name: string;
  embedding_config_id: number;
  chunk_config_id: number;
  search_type: string;
  llm_model: string;
  top_k: number;
  system_prompt: string | null;
  llm_params: Record<string, unknown> | null;
  sparse_config_id: number | null;
  alpha: number | null;
  response_mode: string;
  max_steps: number | null;
  created_at: string;
}

export interface RagConfigCreate {
  name: string;
  embedding_config_id: number;
  chunk_config_id: number;
  search_type: string;
  llm_model: string;
  top_k?: number;
  system_prompt?: string | null;
  llm_params?: Record<string, unknown> | null;
  sparse_config_id?: number | null;
  alpha?: number | null;
  response_mode?: string;
  max_steps?: number | null;
}

export interface RagQueryResult {
  answer: string;
  contexts: { content: string; chunk_id?: number; [key: string]: unknown }[];
  model: string;
  usage: { prompt_tokens: number; completion_tokens: number };
}

interface CreateProjectPayload {
  name: string;
  description: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, `${res.status}: ${body}`);
  }

  return res.json() as Promise<T>;
}

export async function fetchProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export async function createProject(
  payload: CreateProjectPayload,
): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Document API ---

export async function fetchDocuments(projectId: number): Promise<Document[]> {
  return request<Document[]>(`/api/projects/${projectId}/documents`);
}

export async function uploadDocument(
  projectId: number,
  file: File,
): Promise<Document> {
  const form = new FormData();
  form.append("file", file);
  // Do NOT set Content-Type — let browser set multipart boundary
  const res = await fetch(`/api/projects/${projectId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, `${res.status}: ${body}`);
  }
  return res.json() as Promise<Document>;
}

export async function deleteDocument(
  projectId: number,
  docId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/documents/${docId}`,
    { method: "DELETE" },
  );
}

// --- Chunk Config API ---

export async function fetchChunkConfigs(
  projectId: number,
): Promise<ChunkConfig[]> {
  return request<ChunkConfig[]>(`/api/projects/${projectId}/chunk-configs`);
}

export async function createChunkConfig(
  projectId: number,
  config: ChunkConfigCreate,
): Promise<ChunkConfig> {
  return request<ChunkConfig>(`/api/projects/${projectId}/chunk-configs`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteChunkConfig(
  projectId: number,
  configId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/chunk-configs/${configId}`,
    { method: "DELETE" },
  );
}

export async function previewChunks(
  projectId: number,
  configId: number,
  documentId: number,
): Promise<ChunkPreviewResult> {
  return request<ChunkPreviewResult>(
    `/api/projects/${projectId}/chunk-configs/${configId}/preview?document_id=${documentId}`,
    { method: "POST" },
  );
}

export async function generateChunks(
  projectId: number,
  configId: number,
): Promise<ChunkGenerateResult> {
  return request<ChunkGenerateResult>(
    `/api/projects/${projectId}/chunk-configs/${configId}/generate`,
    { method: "POST" },
  );
}

// --- Embedding Config API ---

export async function fetchEmbeddingConfigs(
  projectId: number,
): Promise<EmbeddingConfig[]> {
  return request<EmbeddingConfig[]>(
    `/api/projects/${projectId}/embedding-configs`,
  );
}

export async function createEmbeddingConfig(
  projectId: number,
  config: EmbeddingConfigCreate,
): Promise<EmbeddingConfig> {
  return request<EmbeddingConfig>(
    `/api/projects/${projectId}/embedding-configs`,
    { method: "POST", body: JSON.stringify(config) },
  );
}

export async function deleteEmbeddingConfig(
  projectId: number,
  configId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/embedding-configs/${configId}`,
    { method: "DELETE" },
  );
}

export async function embedChunks(
  projectId: number,
  configId: number,
  chunkConfigId: number,
): Promise<EmbedResult> {
  return request<EmbedResult>(
    `/api/projects/${projectId}/embedding-configs/${configId}/embed`,
    { method: "POST", body: JSON.stringify({ chunk_config_id: chunkConfigId }) },
  );
}

// --- RAG Config API ---

export async function fetchRagConfigs(
  projectId: number,
): Promise<RagConfig[]> {
  return request<RagConfig[]>(`/api/projects/${projectId}/rag-configs`);
}

export async function createRagConfig(
  projectId: number,
  config: RagConfigCreate,
): Promise<RagConfig> {
  return request<RagConfig>(`/api/projects/${projectId}/rag-configs`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteRagConfig(
  projectId: number,
  configId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/rag-configs/${configId}`,
    { method: "DELETE" },
  );
}

export async function queryRag(
  projectId: number,
  configId: number,
  query: string,
): Promise<RagQueryResult> {
  return request<RagQueryResult>(
    `/api/projects/${projectId}/rag-configs/${configId}/query`,
    { method: "POST", body: JSON.stringify({ query }) },
  );
}

// --- Test Set Types ---

export interface TestSet {
  id: number;
  name: string;
  project_id?: number;
  generation_config: {
    chunk_config_id: number;
    testset_size: number;
    num_personas: number;
    custom_personas: Record<string, unknown>[] | null;
    use_personas: boolean;
  };
  created_at: string;
  total_questions: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
}

export interface TestSetCreate {
  chunk_config_id: number;
  name?: string;
  testset_size?: number;
  num_personas?: number;
  use_personas?: boolean;
}

export interface TestQuestion {
  id: number;
  test_set_id: number;
  question: string;
  reference_answer: string;
  reference_contexts: string[];
  question_type: string;
  persona: string | null;
  status: string;
  user_edited_answer: string | null;
  user_notes: string | null;
  reviewed_at: string | null;
}

export interface TestSetSummary {
  test_set_id: number;
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  edited: number;
  completion_pct: number;
}

// --- Test Set API ---

export async function fetchTestSets(projectId: number): Promise<TestSet[]> {
  const data = await request<{ test_sets: TestSet[] }>(
    `/api/projects/${projectId}/test-sets`,
  );
  return data.test_sets;
}

export async function createTestSet(
  projectId: number,
  config: TestSetCreate,
  signal?: AbortSignal,
): Promise<TestSet> {
  return request<TestSet>(`/api/projects/${projectId}/test-sets`, {
    method: "POST",
    body: JSON.stringify(config),
    signal,
  });
}

export async function deleteTestSet(
  projectId: number,
  testSetId: number,
): Promise<void> {
  await request<void>(`/api/projects/${projectId}/test-sets/${testSetId}`, {
    method: "DELETE",
  });
}

export async function fetchTestQuestions(
  projectId: number,
  testSetId: number,
  status?: string,
): Promise<TestQuestion[]> {
  const qs = status ? `?status=${status}` : "";
  const data = await request<{ questions: TestQuestion[] }>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions${qs}`,
  );
  return data.questions;
}

export async function fetchTestSetSummary(
  projectId: number,
  testSetId: number,
): Promise<TestSetSummary> {
  return request<TestSetSummary>(
    `/api/projects/${projectId}/test-sets/${testSetId}/summary`,
  );
}

// --- Annotation Types ---

export interface QuestionAnnotation {
  status: "approved" | "rejected" | "edited";
  user_edited_answer?: string;
  user_notes?: string;
}

export interface BulkAnnotation {
  action: "approve" | "reject" | "approve_all" | "reject_all";
  question_ids?: number[];
}

export interface BulkAnnotationResult {
  updated_count: number;
}

// --- Annotation API ---

export async function annotateQuestion(
  projectId: number,
  testSetId: number,
  questionId: number,
  annotation: QuestionAnnotation,
): Promise<TestQuestion> {
  return request<TestQuestion>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions/${questionId}`,
    { method: "PATCH", body: JSON.stringify(annotation) },
  );
}

export async function bulkAnnotateQuestions(
  projectId: number,
  testSetId: number,
  bulk: BulkAnnotation,
): Promise<BulkAnnotationResult> {
  return request<BulkAnnotationResult>(
    `/api/projects/${projectId}/test-sets/${testSetId}/questions/bulk`,
    { method: "POST", body: JSON.stringify(bulk) },
  );
}

// --- Experiment Types ---

export interface Experiment {
  id: number;
  project_id: number;
  test_set_id: number;
  name: string;
  model: string;
  model_params: Record<string, unknown> | null;
  retrieval_config: Record<string, unknown> | null;
  chunk_config_id: number;
  embedding_config_id: number;
  rag_config_id: number;
  baseline_experiment_id: number | null;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  // Optional aggregate fields (present on GET single / list)
  test_set_name?: string;
  rag_config_name?: string;
  approved_question_count?: number;
  result_count?: number;
  aggregate_metrics?: Record<string, number | null> | null;
}

export interface ExperimentCreate {
  test_set_id: number;
  rag_config_id: number;
  name: string;
}

export interface ExperimentResult {
  id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  question_type: string;
  persona: string | null;
  response: string | null;
  retrieved_contexts: { content: string; chunk_id?: number }[];
  metrics: Record<string, number>;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

// --- Experiment API ---

export async function fetchExperiments(
  projectId: number,
): Promise<Experiment[]> {
  return request<Experiment[]>(`/api/projects/${projectId}/experiments`);
}

export async function createExperiment(
  projectId: number,
  data: ExperimentCreate,
): Promise<Experiment> {
  return request<Experiment>(`/api/projects/${projectId}/experiments`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function fetchExperiment(
  projectId: number,
  experimentId: number,
): Promise<Experiment> {
  return request<Experiment>(
    `/api/projects/${projectId}/experiments/${experimentId}`,
  );
}

export async function deleteExperiment(
  projectId: number,
  experimentId: number,
): Promise<void> {
  await request<void>(
    `/api/projects/${projectId}/experiments/${experimentId}`,
    { method: "DELETE" },
  );
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

export interface SSEStartedEvent {
  experiment_id: number;
  total_questions: number;
  metrics: string[];
}

export interface SSEProgressEvent {
  current: number;
  total: number;
  question_id: number;
  question: string;
}

export interface SSECompletedEvent {
  experiment_id: number;
  result_count: number;
}

export interface SSEErrorEvent {
  message: string;
}

export interface ExperimentSSECallbacks {
  onStarted?: (data: SSEStartedEvent) => void;
  onProgress?: (data: SSEProgressEvent) => void;
  onCompleted?: (data: SSECompletedEvent) => void;
  onError?: (data: SSEErrorEvent) => void;
  onConnectionError?: (error: Error, lastProgress: SSEProgressEvent | null) => void;
}

export interface ExperimentSSEHandle {
  abort: () => void;
}

export function runExperimentSSE(
  projectId: number,
  experimentId: number,
  metrics: string[] | null,
  callbacks: ExperimentSSECallbacks,
): ExperimentSSEHandle {
  const controller = new AbortController();
  let lastProgress: SSEProgressEvent | null = null;

  (async () => {
    try {
      const res = await fetch(
        `/api/projects/${projectId}/experiments/${experimentId}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ metrics }),
          signal: controller.signal,
        },
      );

      if (!res.ok) {
        const body = await res.text().catch(() => "Unknown error");
        callbacks.onError?.({ message: `${res.status}: ${body}` });
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError?.({ message: "No response stream" });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split on double newline (SSE event boundary)
        const parts = buffer.split("\n\n");
        // Keep the last part (may be incomplete)
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.trim()) continue;

          let eventType = "message";
          let dataStr = "";

          for (const line of part.split("\n")) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataStr = line.slice(5).trim();
            }
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);

            switch (eventType) {
              case "started":
                callbacks.onStarted?.(data as SSEStartedEvent);
                break;
              case "progress":
                lastProgress = data as SSEProgressEvent;
                callbacks.onProgress?.(lastProgress);
                break;
              case "completed":
                callbacks.onCompleted?.(data as SSECompletedEvent);
                break;
              case "error":
                callbacks.onError?.(data as SSEErrorEvent);
                break;
            }
          } catch {
            // Skip malformed JSON chunks
          }
        }
      }
    } catch (err) {
      if ((err as DOMException).name === "AbortError") return;
      callbacks.onConnectionError?.(err as Error, lastProgress);
    }
  })();

  return { abort: () => controller.abort() };
}

// --- Suggestion Types ---

export interface Suggestion {
  id: number;
  experiment_id: number;
  category: string;
  signal: string;
  suggestion: string;
  priority: "high" | "medium" | "low";
  config_field: string | null;
  suggested_value: string | null;
  implemented: boolean;
  created_at: string;
}

export interface ApplySuggestionResult {
  suggestion: Suggestion;
  new_experiment: Experiment;
  new_rag_config: { id: number; name: string };
  changes: Record<string, { old: unknown; new: unknown }>;
}

// --- Delta Types ---

export interface ConfigChange {
  field: string;
  old_value: unknown;
  new_value: unknown;
}

export interface MetricDelta {
  baseline: number | null;
  iteration: number | null;
  delta: number | null;
  improved: boolean | null;
}

export interface QuestionDelta {
  test_question_id: number;
  question: string | null;
  metrics: Record<
    string,
    { baseline: number | null; iteration: number | null; delta: number | null }
  >;
}

export interface DeltaResult {
  experiment_id: number;
  experiment_name: string;
  baseline_experiment_id: number;
  baseline_experiment_name: string;
  config_changes: ConfigChange[];
  metric_deltas: Record<string, MetricDelta>;
  per_question_deltas: QuestionDelta[];
}

// --- Suggestion API ---

export async function generateSuggestions(
  projectId: number,
  experimentId: number,
): Promise<{ suggestions: Suggestion[]; count: number }> {
  return request<{ suggestions: Suggestion[]; count: number }>(
    `/api/projects/${projectId}/experiments/${experimentId}/suggestions/generate`,
    { method: "POST" },
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

export async function applySuggestion(
  projectId: number,
  suggestionId: number,
  body?: { override_value?: string; experiment_name?: string },
): Promise<ApplySuggestionResult> {
  return request<ApplySuggestionResult>(
    `/api/projects/${projectId}/suggestions/${suggestionId}/apply`,
    {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    },
  );
}

// --- Delta API ---

export async function fetchExperimentDelta(
  projectId: number,
  experimentId: number,
): Promise<DeltaResult> {
  return request<DeltaResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/delta`,
  );
}

// --- Export API ---

export async function exportExperiment(
  projectId: number,
  experimentId: number,
  format: "csv" | "json",
): Promise<void> {
  const res = await fetch(
    `/api/projects/${projectId}/experiments/${experimentId}/export?format=${format}`,
  );

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] ?? `export.${format}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- Comparison Types ---

export interface CompareQuestionExperimentData {
  response: string | null;
  metrics: Record<string, number>;
  retrieved_contexts: { content: string; chunk_id?: number }[];
  metadata: Record<string, unknown> | null;
}

export interface CompareQuestionData {
  test_question_id: number;
  question: string;
  reference_answer: string;
  question_type: string;
  persona: string | null;
  experiments: Record<number, CompareQuestionExperimentData>;
}

export interface CompareResult {
  experiments: Experiment[];
  questions: CompareQuestionData[];
}

// --- History Types ---

export interface HistoryExperiment extends Experiment {
  overall_score: number | null;
}

// --- Comparison API ---

export async function compareExperiments(
  projectId: number,
  experimentIds: number[],
): Promise<CompareResult> {
  const ids = experimentIds.join(",");
  return request<CompareResult>(
    `/api/projects/${projectId}/experiments/compare?ids=${ids}`,
  );
}

// --- History API ---

export async function fetchExperimentHistory(
  projectId: number,
): Promise<HistoryExperiment[]> {
  const data = await request<{ experiments: HistoryExperiment[] }>(
    `/api/projects/${projectId}/experiments/history`,
  );
  return data.experiments;
}

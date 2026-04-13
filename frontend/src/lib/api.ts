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
  context_label: string | null;
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
  filter_params: Record<string, number> | null;
  created_at: string;
}

export interface ChunkConfigCreate {
  name: string;
  method: string;
  params: Record<string, number | string>;
  step2_method?: string | null;
  step2_params?: Record<string, number | string> | null;
  filter_params?: Record<string, number> | null;
}

export interface ChunkPreviewResult {
  document_id: number;
  filename: string;
  chunks: string[];
  chunk_count: number;
}

export interface ChunkGenerateResult {
  total_chunks: number;
  skipped_documents: number;
  documents: { document_id: number; filename: string; chunk_count: number; skipped: boolean }[];
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
  reranker_model: string | null;
  reranker_top_k: number | null;
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
  reranker_model?: string | null;
  reranker_top_k?: number | null;
}

export interface RagConfigExpanded extends RagConfig {
  chunk_config: { name: string; method: string; params: Record<string, number | string> } | null;
  embedding_config: { name: string; type: string; model_name: string } | null;
}

export interface RagQueryResult {
  answer: string;
  contexts: { content: string; chunk_id?: number; [key: string]: unknown }[];
  model: string;
  usage: { prompt_tokens: number; completion_tokens: number };
}

// --- External Baseline Types ---

export interface ExternalBaseline {
  id: number;
  project_id: number;
  question: string;
  answer: string;
  reference_answer: string;
  sources: string;
  source_type: string;
  created_at: string;
}

export interface CsvUploadResult {
  imported: number;
  bot_config_id: number;
  preview: { question: string; answer: string; sources: string }[];
}

export interface CsvPreviewResult {
  headers: string[];
  rows: Record<string, string>[];
}

// --- API Config Types ---

export interface ApiConfig {
  id: number;
  project_id: number;
  endpoint_url: string;
  api_key: string | null;
  headers_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiConfigCreate {
  endpoint_url: string;
  api_key?: string | null;
  headers_json?: string | null;
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

/**
 * Send a FormData request and parse the response, extracting error detail on failure.
 */
async function formRequest<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      if (parsed.detail) detail = parsed.detail;
    } catch { /* use raw body */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
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
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      if (parsed.detail) detail = parsed.detail;
    } catch {
      // use raw body
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// --- Config Defaults API ---

export interface ConfigDefaults {
  connector_types: string[];
  default_models: Record<string, string>;
  default_eval_model: string;
  default_eval_embedding: string;
}

let _configCache: ConfigDefaults | null = null;

export async function fetchConfigDefaults(): Promise<ConfigDefaults> {
  if (_configCache) return _configCache;
  _configCache = await request<ConfigDefaults>("/api/config/defaults");
  return _configCache;
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

// --- External Baseline API ---

export async function previewBaselineCsv(
  projectId: number,
  file: File,
): Promise<CsvPreviewResult> {
  const form = new FormData();
  form.append("file", file);
  return formRequest<CsvPreviewResult>(`/api/projects/${projectId}/baselines/preview-csv`, form);
}

export async function uploadBaselineCsv(
  projectId: number,
  file: File,
  columnMapping: {
    questionCol: string;
    answerCol: string;
    referenceAnswerCol?: string;
    contextCol?: string;
    configName?: string;
  },
): Promise<CsvUploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("question_col", columnMapping.questionCol);
  form.append("answer_col", columnMapping.answerCol);
  if (columnMapping.referenceAnswerCol) form.append("reference_answer_col", columnMapping.referenceAnswerCol);
  if (columnMapping.contextCol) form.append("context_col", columnMapping.contextCol);
  if (columnMapping.configName) form.append("config_name", columnMapping.configName);
  return formRequest<CsvUploadResult>(`/api/projects/${projectId}/baselines/upload-csv`, form);
}

export async function fetchBaselines(
  projectId: number,
): Promise<ExternalBaseline[]> {
  return request<ExternalBaseline[]>(`/api/projects/${projectId}/baselines`);
}

export async function deleteBaseline(
  projectId: number,
  baselineId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/baselines/${baselineId}`,
    { method: "DELETE" },
  );
}

export async function clearBaselines(
  projectId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/baselines`,
    { method: "DELETE" },
  );
}

// --- API Config API ---

export async function saveApiConfig(
  projectId: number,
  payload: ApiConfigCreate,
): Promise<ApiConfig> {
  return request<ApiConfig>(`/api/projects/${projectId}/api-config`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchApiConfig(
  projectId: number,
): Promise<ApiConfig> {
  return request<ApiConfig>(`/api/projects/${projectId}/api-config`);
}

export async function deleteApiConfig(
  projectId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/api-config`,
    { method: "DELETE" },
  );
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
  return formRequest<Document>(`/api/projects/${projectId}/documents`, form);
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

export async function deleteAllDocuments(
  projectId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/documents`,
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
  force: boolean = false,
): Promise<ChunkGenerateResult> {
  const query = force ? "?force=true" : "";
  return request<ChunkGenerateResult>(
    `/api/projects/${projectId}/chunk-configs/${configId}/generate${query}`,
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
  useContextualPrefix: boolean = false,
): Promise<EmbedResult> {
  return request<EmbedResult>(
    `/api/projects/${projectId}/embedding-configs/${configId}/embed`,
    {
      method: "POST",
      body: JSON.stringify({
        chunk_config_id: chunkConfigId,
        use_contextual_prefix: useContextualPrefix,
      }),
    },
  );
}

export async function updateDocumentContextLabel(
  projectId: number,
  documentId: number,
  contextLabel: string,
): Promise<{ detail: string; context_label: string }> {
  return request<{ detail: string; context_label: string }>(
    `/api/projects/${projectId}/documents/${documentId}/context-label`,
    {
      method: "PATCH",
      body: JSON.stringify({ context_label: contextLabel }),
    },
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

export async function fetchRagConfigsExpanded(
  projectId: number,
): Promise<RagConfigExpanded[]> {
  return request<RagConfigExpanded[]>(`/api/projects/${projectId}/rag-configs/expanded`);
}

export async function fetchRagConfigExpanded(
  projectId: number,
  configId: number,
): Promise<RagConfigExpanded> {
  return request<RagConfigExpanded>(`/api/projects/${projectId}/rag-configs/${configId}/expanded`);
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
  custom_personas?: { name: string; role_description: string; question_style?: string }[];
  use_personas?: boolean;
  query_distribution?: Record<string, number>;
  chunk_sample_size?: number;
  num_workers?: number;
  question_categories?: Record<string, number>;
}

export interface TestQuestion {
  id: number;
  test_set_id: number;
  question: string;
  reference_answer: string;
  reference_contexts: string[];
  question_type: string;
  persona: string | null;
  category: string | null;
  status: string;
  user_edited_answer: string | null;
  user_edited_contexts: string[] | null;
  user_notes: string | null;
  metadata: Record<string, unknown> | null;
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

// --- Test Set Upload Types ---

export interface UploadPreviewResult {
  filename: string;
  total_rows: number;
  columns: string[];
  preview: Record<string, string>[];
}

export interface UploadConfirmResult {
  id: number;
  name: string;
  project_id: number;
  question_count: number;
}

// --- Test Set Upload API ---

export async function previewTestSetUpload(
  projectId: number,
  file: File,
): Promise<UploadPreviewResult> {
  const form = new FormData();
  form.append("file", file);
  return formRequest<UploadPreviewResult>(`/api/projects/${projectId}/test-sets/upload/preview`, form);
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
  },
): Promise<UploadConfirmResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("question_column", questionColumn);
  form.append("answer_column", answerColumn);
  if (opts?.contextsColumn) form.append("contexts_column", opts.contextsColumn);
  if (opts?.referenceSqlColumn) form.append("reference_sql_column", opts.referenceSqlColumn);
  if (opts?.schemaContextsColumn) form.append("schema_contexts_column", opts.schemaContextsColumn);
  if (opts?.referenceDataColumn) form.append("reference_data_column", opts.referenceDataColumn);
  if (opts?.name) form.append("name", opts.name);
  return formRequest<UploadConfirmResult>(`/api/projects/${projectId}/test-sets/upload`, form);
}

// --- Test Set API ---

export async function fetchTestSets(projectId: number): Promise<TestSet[]> {
  const data = await request<{ test_sets: TestSet[] }>(
    `/api/projects/${projectId}/test-sets`,
  );
  return data.test_sets;
}

// --- Persona Types ---

export interface SavedPersona {
  id: number;
  name: string;
  role_description: string;
  question_style: string;
  created_at: string;
}

// --- Persona API ---

export async function fetchPersonas(
  projectId: number,
): Promise<SavedPersona[]> {
  const data = await request<{ personas: SavedPersona[] }>(
    `/api/projects/${projectId}/personas`,
  );
  return data.personas;
}

export async function savePersonasBulk(
  projectId: number,
  personas: { name: string; role_description: string; question_style: string }[],
): Promise<SavedPersona[]> {
  const data = await request<{ personas: SavedPersona[] }>(
    `/api/projects/${projectId}/personas/bulk`,
    {
      method: "POST",
      body: JSON.stringify(personas),
    },
  );
  return data.personas;
}

export async function deletePersona(
  projectId: number,
  personaId: number,
): Promise<void> {
  await request<{ detail: string }>(
    `/api/projects/${projectId}/personas/${personaId}`,
    { method: "DELETE" },
  );
}

export async function generatePersonas(
  projectId: number,
  chunkConfigId: number,
  numPersonas: number = 3,
  mode: "fast" | "full" = "fast",
  signal?: AbortSignal,
): Promise<{ name: string; role_description: string; question_style: string }[]> {
  const data = await request<{
    personas: { name: string; role_description: string; question_style: string }[];
  }>(`/api/projects/${projectId}/generate-personas`, {
    method: "POST",
    body: JSON.stringify({
      chunk_config_id: chunkConfigId,
      num_personas: numPersonas,
      mode,
    }),
    signal,
  });
  return data.personas;
}

export interface GenerationProgress {
  active: boolean;
  stage?: string;
  questions_generated?: number;
  target_size?: number;
  status?: "generating" | "completed" | "failed";
  test_set_id?: number;
  error_message?: string;
}

export interface CreateTestSetResponse {
  id: number;
  name: string;
  project_id: number;
  status: "generating";
}

export async function fetchGenerationProgress(
  projectId: number,
): Promise<GenerationProgress> {
  return request<GenerationProgress>(
    `/api/projects/${projectId}/test-sets/generation-progress`,
  );
}

export async function createTestSet(
  projectId: number,
  config: TestSetCreate,
  signal?: AbortSignal,
): Promise<CreateTestSetResponse> {
  return request<CreateTestSetResponse>(`/api/projects/${projectId}/test-sets`, {
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
  user_edited_contexts?: string[];
  user_notes?: string;
  metadata?: Record<string, unknown>;
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
  bot_config_id: number | null;
  baseline_experiment_id: number | null;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  // Optional aggregate fields (present on GET single / list)
  test_set_name?: string;
  rag_config_name?: string;
  has_reference_contexts?: boolean;
  has_reference_sql?: boolean;
  has_reference_data?: boolean;
  connector_type?: string | null;
  bot_returns_contexts?: boolean;
  approved_question_count?: number;
  result_count?: number;
  aggregate_metrics?: Record<string, number | null> | null;
}

export interface ExperimentCreate {
  test_set_id?: number | null;
  rag_config_id?: number | null;
  bot_config_id?: number | null;
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

export async function resetExperiment(
  projectId: number,
  experimentId: number,
): Promise<Experiment> {
  return request<Experiment>(
    `/api/projects/${projectId}/experiments/${experimentId}/reset`,
    { method: "POST" },
  );
}

export async function cancelExperiment(
  projectId: number,
  experimentId: number,
): Promise<{ status: string; experiment_id: number }> {
  return request<{ status: string; experiment_id: number }>(
    `/api/projects/${projectId}/experiments/${experimentId}/cancel`,
    { method: "POST" },
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
  experiment_name?: string;
  model?: string;
  test_set_name?: string;
}

export interface SSECompletionItem {
  question: string;
  response: string | null;
  error: string | null;
  metrics?: Record<string, number | null>;
}

export interface InFlightDetail {
  question: string;
  phase: "querying" | "scoring";
  metrics_done: string[];
  metrics_active: string[];
  metrics_pending: string[];
}

export interface SSEProgressEvent {
  current: number;
  total: number;
  question_id: number;
  question: string;
  error?: string;
  in_flight?: string[];
  new_completions?: SSECompletionItem[];
  scoring_metrics?: string[];
  in_flight_details?: InFlightDetail[];
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
  rubrics?: Record<string, string> | null,
  concurrency?: number,
  multiLlmJudgeEvaluators?: number,
): ExperimentSSEHandle {
  const controller = new AbortController();

  (async () => {
    try {
      // Fire the run endpoint (returns JSON immediately, starts background task)
      const runRes = await fetch(
        `/api/projects/${projectId}/experiments/${experimentId}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            metrics,
            rubrics: rubrics ?? null,
            concurrency: concurrency ?? 5,
            multi_llm_judge_evaluators: multiLlmJudgeEvaluators ?? 5,
          }),
          signal: controller.signal,
        },
      );

      if (!runRes.ok) {
        const body = await runRes.text().catch(() => "Unknown error");
        callbacks.onError?.({ message: `${runRes.status}: ${body}` });
        return;
      }

      const runData = await runRes.json();

      // Emit a synthetic "started" event from the run response
      callbacks.onStarted?.({
        experiment_id: runData.experiment_id,
        total_questions: 0,
        metrics: runData.metrics ?? [],
        experiment_name: "",
        model: "",
        test_set_name: "",
      });

      // Now observe progress via the SSE progress endpoint
      const handle = observeExperimentProgress(projectId, experimentId, callbacks);
      // Wire abort through to the progress observer
      controller.signal.addEventListener("abort", () => handle.abort());
    } catch (err) {
      if ((err as DOMException).name === "AbortError") return;
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
        res = await fetch(
          `/api/projects/${projectId}/experiments/${experimentId}/progress`,
          { signal: controller.signal },
        );
        if (res.ok || res.status !== 409) break;
        await new Promise((r) => setTimeout(r, 500));
      }

      if (!res || !res.ok) {
        const body = await res?.text().catch(() => "Unknown error") ?? "No response";
        callbacks.onError?.({ message: `${res?.status}: ${body}` });
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
        const parts = buffer.split("\n\n");
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
            // Skip malformed JSON
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

export interface BatchApplyResult {
  suggestions: Suggestion[];
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

export async function applySuggestionsBatch(
  projectId: number,
  experimentId: number,
  items: { suggestion_id: number; override_value?: string }[],
  experimentName?: string,
): Promise<BatchApplyResult> {
  return request<BatchApplyResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/suggestions/apply-batch`,
    {
      method: "POST",
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

// --- Bot Config API ---

export type ConnectorType = "glean" | "openai" | "claude" | "deepseek" | "gemini" | "custom" | "csv";

export interface BotConfig {
  id: number;
  project_id: number;
  name: string;
  connector_type: ConnectorType;
  config_json: Record<string, unknown>;
  prompt_for_sources: boolean;
  returns_contexts: boolean;
  created_at: string;
  updated_at: string;
}

export interface BotConfigCreatePayload {
  name: string;
  connector_type: ConnectorType;
  config_json: Record<string, unknown>;
  prompt_for_sources?: boolean;
}

export async function fetchBotConfigs(projectId: number): Promise<BotConfig[]> {
  return request<BotConfig[]>(`/api/projects/${projectId}/bot-configs`);
}

export async function createBotConfig(
  projectId: number,
  payload: BotConfigCreatePayload,
): Promise<BotConfig> {
  return request<BotConfig>(`/api/projects/${projectId}/bot-configs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateBotConfig(
  projectId: number,
  configId: number,
  payload: Partial<BotConfigCreatePayload>,
): Promise<BotConfig> {
  return request<BotConfig>(`/api/projects/${projectId}/bot-configs/${configId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteBotConfig(
  projectId: number,
  configId: number,
): Promise<void> {
  return request<void>(`/api/projects/${projectId}/bot-configs/${configId}`, {
    method: "DELETE",
  });
}

export interface BotConfigBaselinesResult {
  total: number;
  rows: {
    id: number;
    question: string;
    answer: string;
    reference_answer: string;
    sources: string;
    created_at: string;
  }[];
}

export async function fetchBotConfigBaselines(
  projectId: number,
  configId: number,
  limit = 5,
): Promise<BotConfigBaselinesResult> {
  return request<BotConfigBaselinesResult>(
    `/api/projects/${projectId}/bot-configs/${configId}/baselines?limit=${limit}`,
  );
}

// --- Source Verification Types ---

export interface SourceVerification {
  id: number;
  citation_index: number;
  title: string | null;
  url: string | null;
  status: "verified" | "hallucinated" | "inaccessible" | "unverifiable";
  details: string | null;
  created_at: string;
}

export interface SourceVerificationGroup {
  experiment_result_id: number;
  test_question_id: number;
  question: string;
  verifications: SourceVerification[];
}

export interface SourceVerificationResult {
  experiment_id: number;
  results: SourceVerificationGroup[];
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

// --- Human Annotation Types ---

export interface AnnotationSampleItem {
  experiment_result_id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  response: string | null;
  metrics: Record<string, number>;
  annotation: {
    rating: string;
    notes: string | null;
    annotated_at: string;
  } | null;
}

export interface AnnotationSampleResult {
  experiment_id: number;
  total_results: number;
  sample_size: number;
  annotated_count: number;
  sample: AnnotationSampleItem[];
}

export interface HumanAnnotationCreate {
  experiment_result_id: number;
  rating: "accurate" | "partially_accurate" | "inaccurate";
  notes?: string | null;
}

export interface EvaluatorAccuracyComparison {
  experiment_result_id: number;
  question: string;
  response: string | null;
  reference_answer: string;
  human_rating: string;
  human_score: number;
  evaluator_score: number | null;
  evaluator_rating: string | null;
  agrees: boolean | null;
  notes: string | null;
}

export interface EvaluatorAccuracyResult {
  experiment_id: number;
  total_annotations: number;
  scorable_count: number;
  agreements: number;
  agreement_rate: number | null;
  comparisons: EvaluatorAccuracyComparison[];
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
    { method: "POST", body: JSON.stringify({ annotations }) },
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

// --- Project Report Types ---

export interface ExperimentReportEntry {
  id: number;
  name: string;
  bot_config_id: number | null;
  bot_config_name: string | null;
  rag_config_id: number | null;
  rag_config_name: string | null;
  result_count: number;
  completed_at: string | null;
  aggregate_metrics: Record<string, number | null>;
  overall_score: number | null;
  source_verification: {
    verified: number;
    hallucinated: number;
    inaccessible: number;
    unverifiable: number;
    total: number;
    pct_verified: number;
    pct_hallucinated: number;
  } | null;
  evaluator_reliability: {
    total_annotations: number;
    scorable_count: number;
    agreements: number;
    agreement_rate: number;
  } | null;
}

export interface BotSummary {
  bot_config_id: number;
  bot_config_name: string | null;
  connector_type: string;
  experiment_count: number;
  total_results: number;
  aggregate_metrics: Record<string, number | null>;
  overall_score: number | null;
}

export interface ProjectReport {
  project_id: number;
  project_name: string;
  total_experiments: number;
  experiments: ExperimentReportEntry[];
  bot_summary: BotSummary[];
  overall_metrics: Record<string, number | null> | null;
  overall_source_verification: {
    verified: number;
    hallucinated: number;
    inaccessible: number;
    unverifiable: number;
    total: number;
    pct_verified: number;
    pct_hallucinated: number;
  } | null;
  overall_evaluator_reliability: {
    total_annotations: number;
    scorable_count: number;
    agreements: number;
    agreement_rate: number;
  } | null;
}

// --- Project Report API ---

export async function fetchProjectReport(
  projectId: number,
): Promise<ProjectReport> {
  return request<ProjectReport>(`/api/projects/${projectId}/report`);
}

// --- Custom Metrics API ---

export interface CustomMetric {
  id: number;
  project_id: number;
  name: string;
  metric_type: "integer_range" | "similarity" | "rubrics" | "instance_rubrics";
  prompt: string | null;
  rubrics: Record<string, string> | null;
  min_score: number;
  max_score: number;
  created_at: string;
}

export interface CustomMetricCreate {
  name: string;
  metric_type: string;
  prompt?: string | null;
  rubrics?: Record<string, string> | null;
  min_score?: number;
  max_score?: number;
}

export async function fetchCustomMetrics(
  projectId: number,
): Promise<CustomMetric[]> {
  return request<CustomMetric[]>(`/api/projects/${projectId}/custom-metrics`);
}

export async function createCustomMetric(
  projectId: number,
  data: CustomMetricCreate,
): Promise<CustomMetric> {
  return request<CustomMetric>(`/api/projects/${projectId}/custom-metrics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteCustomMetric(
  projectId: number,
  metricId: number,
): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/projects/${projectId}/custom-metrics/${metricId}`,
    { method: "DELETE" },
  );
}

// --- Knowledge Graph ---

export interface KnowledgeGraphInfo {
  exists: boolean;
  id?: number;
  project_id?: number;
  num_nodes?: number;
  num_chunks?: number;
  is_complete?: boolean;
  completed_steps?: number;
  total_steps?: number;
  heartbeat_stale?: boolean;
  chunks_stale?: boolean;
  chunk_config_id?: number;
  last_heartbeat?: string;
  created_at?: string;
}

export interface KGBuildProgress {
  active: boolean;
  stage?: string;
  status?: string;
  stale?: boolean;
  num_nodes?: number;
  num_chunks?: number;
  batch_current?: number;
  batch_total?: number;
  nodes_processed?: number;
  nodes_total?: number;
  is_complete?: boolean;
  completed_steps?: number;
  total_steps?: number;
}

// --- Multi-LLM Judge Types ---

export interface JudgeClaim {
  type: "praise" | "critique";
  response_quote: string;
  chunk_reference: string | null;
  chunk_quote: string | null;
  explanation: string;
}

export interface ClaimAnnotation {
  status: "accurate" | "inaccurate" | "unsure";
  comment: string | null;
  annotated_at: string;
}

export interface JudgeEvaluation {
  id: number;
  evaluator_index: number;
  verdict: "positive" | "mixed" | "critical";
  score: number;
  claims: JudgeClaim[];
  annotations: Record<number, ClaimAnnotation>;
  created_at: string;
}

export interface JudgeEvaluationsResponse {
  result_id: number;
  evaluations: JudgeEvaluation[];
}

export interface JudgeAnnotationSampleItem {
  result_id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  response: string | null;
  evaluations: JudgeEvaluation[];
}

export interface JudgeAnnotationSampleResult {
  experiment_id: number;
  total_results: number;
  sample_size: number;
  annotated_count: number;
  sample: JudgeAnnotationSampleItem[];
}

export interface JudgeEvaluatorStats {
  evaluator_index: number;
  reliability: number | null;
  accurate_claims: number;
  inaccurate_claims: number;
  unsure_claims: number;
  total_claims_annotated: number;
  verdict_counts: Record<string, number>;
  excluded: boolean;
}

export interface JudgeReliabilityResult {
  experiment_id: number;
  evaluators: JudgeEvaluatorStats[];
  excluded_indices: number[];
  overall_reliability: number | null;
  threshold: number;
  annotation_progress: { annotated_evaluators: number; total_evaluators: number };
}

export interface JudgeSummaryResult {
  result_id: number;
  question: string;
  response: string | null;
  reference_answer: string;
  evaluator_verdicts: Record<number, string>;
  adjusted_score: number;
}

export interface JudgeSummaryResponse {
  experiment_id: number;
  excluded_indices: number[];
  results: JudgeSummaryResult[];
}

// --- Multi-LLM Judge API ---

export async function fetchJudgeEvaluations(
  projectId: number,
  experimentId: number,
  resultId: number,
): Promise<JudgeEvaluationsResponse> {
  return request<JudgeEvaluationsResponse>(
    `/api/projects/${projectId}/experiments/${experimentId}/results/${resultId}/judge-evaluations`,
  );
}

export async function fetchJudgeAnnotationSample(
  projectId: number,
  experimentId: number,
): Promise<JudgeAnnotationSampleResult> {
  return request<JudgeAnnotationSampleResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/judge-annotation-sample`,
  );
}

export async function annotateJudgeClaim(
  projectId: number,
  experimentId: number,
  resultId: number,
  evaluationId: number,
  claimIndex: number,
  status: "accurate" | "inaccurate" | "unsure",
  comment?: string,
): Promise<{ evaluation_id: number; claim_index: number; status: string }> {
  return request(
    `/api/projects/${projectId}/experiments/${experimentId}/results/${resultId}/judge-evaluations/${evaluationId}/claims/${claimIndex}/annotate`,
    { method: "POST", body: JSON.stringify({ status, comment: comment ?? null }) },
  );
}

export async function fetchJudgeReliability(
  projectId: number,
  experimentId: number,
): Promise<JudgeReliabilityResult> {
  return request<JudgeReliabilityResult>(
    `/api/projects/${projectId}/experiments/${experimentId}/judge-reliability`,
  );
}

export async function fetchJudgeSummary(
  projectId: number,
  experimentId: number,
): Promise<JudgeSummaryResponse> {
  return request<JudgeSummaryResponse>(
    `/api/projects/${projectId}/experiments/${experimentId}/judge-summary`,
  );
}

export async function fetchKnowledgeGraphInfo(
  projectId: number,
): Promise<KnowledgeGraphInfo> {
  return request<KnowledgeGraphInfo>(
    `/api/projects/${projectId}/knowledge-graph`,
  );
}

export async function buildKnowledgeGraph(
  projectId: number,
  chunkConfigId: number,
  overlapMaxNodes: number | null = 500,
): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/projects/${projectId}/build-knowledge-graph`,
    {
      method: "POST",
      body: JSON.stringify({
        chunk_config_id: chunkConfigId,
        overlap_max_nodes: overlapMaxNodes,
      }),
    },
  );
}

export async function fetchKGBuildProgress(
  projectId: number,
): Promise<KGBuildProgress> {
  return request<KGBuildProgress>(
    `/api/projects/${projectId}/knowledge-graph/progress`,
  );
}

export async function deleteKnowledgeGraph(
  projectId: number,
): Promise<void> {
  await request<void>(
    `/api/projects/${projectId}/knowledge-graph`,
    { method: "DELETE" },
  );
}

export async function resetKnowledgeGraph(
  projectId: number,
): Promise<{ deleted: boolean; was_complete?: boolean }> {
  return request<{ deleted: boolean; was_complete?: boolean }>(
    `/api/projects/${projectId}/knowledge-graph/reset`,
    { method: "POST" },
  );
}

export async function rebuildKGLinks(
  projectId: number,
  overlapMaxNodes: number | null = 500,
): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/projects/${projectId}/knowledge-graph/rebuild-links`,
    {
      method: "POST",
      body: JSON.stringify({ overlap_max_nodes: overlapMaxNodes }),
    },
  );
}

export async function updateKnowledgeGraph(
  projectId: number,
  chunkConfigId: number,
  overlapMaxNodes: number | null = 500,
): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/projects/${projectId}/knowledge-graph/update`,
    {
      method: "POST",
      body: JSON.stringify({
        chunk_config_id: chunkConfigId,
        overlap_max_nodes: overlapMaxNodes,
      }),
    },
  );
}

// --- Knowledge Graph Explorer ---

export interface KGListItem {
  id: number;
  project_id: number;
  project_name: string;
  num_nodes: number;
  num_chunks: number;
  is_complete: boolean;
  completed_steps: number;
  total_steps: number;
  chunk_config_id: number | null;
  chunks_stale: boolean;
  created_at: string;
}

export interface KGGraphNode {
  id: string;
  type: string;
  label: string;
  keyphrases: string[];
}

export interface KGGraphEdge {
  source: string;
  target: string;
  type: string;
  score: number;
}

export interface KGGraphData {
  nodes: KGGraphNode[];
  edges: KGGraphEdge[];
  is_complete: boolean;
}

export async function fetchAllKnowledgeGraphs(): Promise<KGListItem[]> {
  return request<KGListItem[]>("/api/knowledge-graphs");
}

export async function fetchKnowledgeGraphData(
  projectId: number,
): Promise<KGGraphData> {
  return request<KGGraphData>(
    `/api/projects/${projectId}/knowledge-graph/data`,
  );
}

export interface KGStreamCallbacks {
  onMeta: (meta: { total_nodes: number; total_edges: number; is_complete: boolean }) => void;
  onNodes: (nodes: KGGraphNode[]) => void;
  onEdges: (edges: KGGraphEdge[]) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

export function streamKnowledgeGraphData(
  projectId: number,
  callbacks: KGStreamCallbacks,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(
        `/api/projects/${projectId}/knowledge-graph/stream`,
        { signal: controller.signal },
      );
      if (!res.ok) {
        const body = await res.text().catch(() => "Unknown error");
        callbacks.onError(body);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError("No response body");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const json = line.slice(6);
          try {
            const event = JSON.parse(json);
            switch (event.type) {
              case "meta":
                callbacks.onMeta(event);
                break;
              case "nodes":
                callbacks.onNodes(event.batch);
                break;
              case "edges":
                callbacks.onEdges(event.batch);
                break;
              case "done":
                callbacks.onDone();
                break;
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        callbacks.onError((err as Error).message || "Stream failed");
      }
    }
  })();

  return () => controller.abort();
}

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

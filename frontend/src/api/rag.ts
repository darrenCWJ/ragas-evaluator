// RAG domain — RAG config CRUD, expanded views, and test query

import { request } from './client';
import type { RagConfig, RagConfigCreate, RagConfigExpanded, RagQueryResult } from './types';

export async function fetchRagConfigs(projectId: number): Promise<RagConfig[]> {
  return request<RagConfig[]>(`/api/projects/${projectId}/rag-configs`);
}

export async function createRagConfig(
  projectId: number,
  config: RagConfigCreate,
): Promise<RagConfig> {
  return request<RagConfig>(`/api/projects/${projectId}/rag-configs`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function fetchRagConfigsExpanded(projectId: number): Promise<RagConfigExpanded[]> {
  return request<RagConfigExpanded[]>(`/api/projects/${projectId}/rag-configs/expanded`);
}

export async function fetchRagConfigExpanded(
  projectId: number,
  configId: number,
): Promise<RagConfigExpanded> {
  return request<RagConfigExpanded>(`/api/projects/${projectId}/rag-configs/${configId}/expanded`);
}

export async function deleteRagConfig(projectId: number, configId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/rag-configs/${configId}`, {
    method: 'DELETE',
  });
}

export async function queryRag(
  projectId: number,
  configId: number,
  query: string,
): Promise<RagQueryResult> {
  return request<RagQueryResult>(`/api/projects/${projectId}/rag-configs/${configId}/query`, {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
}

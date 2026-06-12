// Embeddings domain — embedding config CRUD and chunk embedding

import { request } from './client';
import type { EmbeddingConfig, EmbeddingConfigCreate, EmbedResult } from './types';

export async function fetchEmbeddingConfigs(projectId: number): Promise<EmbeddingConfig[]> {
  return request<EmbeddingConfig[]>(`/api/projects/${projectId}/embedding-configs`);
}

export async function createEmbeddingConfig(
  projectId: number,
  config: EmbeddingConfigCreate,
): Promise<EmbeddingConfig> {
  return request<EmbeddingConfig>(`/api/projects/${projectId}/embedding-configs`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function deleteEmbeddingConfig(projectId: number, configId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/embedding-configs/${configId}`, {
    method: 'DELETE',
  });
}

export async function embedChunks(
  projectId: number,
  configId: number,
  chunkConfigId: number,
  useContextualPrefix: boolean = false,
): Promise<EmbedResult> {
  return request<EmbedResult>(`/api/projects/${projectId}/embedding-configs/${configId}/embed`, {
    method: 'POST',
    body: JSON.stringify({
      chunk_config_id: chunkConfigId,
      use_contextual_prefix: useContextualPrefix,
    }),
  });
}

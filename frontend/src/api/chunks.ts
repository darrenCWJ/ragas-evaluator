// Chunks domain — chunk config CRUD, preview, and generation

import { request } from './client';
import type {
  ChunkConfig,
  ChunkConfigCreate,
  ChunkPreviewResult,
  ChunkGenerateResult,
} from './types';

export async function fetchChunkConfigs(projectId: number): Promise<ChunkConfig[]> {
  return request<ChunkConfig[]>(`/api/projects/${projectId}/chunk-configs`);
}

export async function createChunkConfig(
  projectId: number,
  config: ChunkConfigCreate,
): Promise<ChunkConfig> {
  return request<ChunkConfig>(`/api/projects/${projectId}/chunk-configs`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function deleteChunkConfig(projectId: number, configId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/chunk-configs/${configId}`, {
    method: 'DELETE',
  });
}

export async function previewChunks(
  projectId: number,
  configId: number,
  documentId: number,
): Promise<ChunkPreviewResult> {
  return request<ChunkPreviewResult>(
    `/api/projects/${projectId}/chunk-configs/${configId}/preview?document_id=${documentId}`,
    { method: 'POST' },
  );
}

export async function generateChunks(
  projectId: number,
  configId: number,
  force: boolean = false,
): Promise<ChunkGenerateResult> {
  const query = force ? '?force=true' : '';
  return request<ChunkGenerateResult>(
    `/api/projects/${projectId}/chunk-configs/${configId}/generate${query}`,
    { method: 'POST' },
  );
}

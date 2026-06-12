// Workers domain — worker pool status and stale task clearing

import { request } from './client';
import type { WorkersStatusResponse } from './types';

export async function fetchWorkersStatus(): Promise<WorkersStatusResponse> {
  return request<WorkersStatusResponse>('/api/workers/status');
}

export async function clearWorkerPersonaTask(projectId: number): Promise<{ cleared: boolean }> {
  return request<{ cleared: boolean }>(`/api/workers/clear-personas/${projectId}`, {
    method: 'POST',
  });
}

export async function clearWorkerBuildTask(
  projectId: number,
  kgSource: string = 'chunks',
): Promise<{ cleared: boolean }> {
  return request<{ cleared: boolean }>(
    `/api/workers/clear-build/${projectId}?kg_source=${kgSource}`,
    { method: 'POST' },
  );
}

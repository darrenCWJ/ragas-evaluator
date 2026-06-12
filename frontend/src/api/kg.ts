// Knowledge graph domain — KG build/reset/update, build progress, explorer data, and SSE graph stream

import { request } from './client';
import type {
  KnowledgeGraphInfo,
  KGBuildProgress,
  KGListItem,
  KGGraphData,
  KGStreamCallbacks,
} from './types';

export async function fetchKnowledgeGraphInfo(
  projectId: number,
  kgSource: string = 'chunks',
): Promise<KnowledgeGraphInfo> {
  return request<KnowledgeGraphInfo>(
    `/api/projects/${projectId}/knowledge-graph?kg_source=${encodeURIComponent(kgSource)}`,
  );
}

export async function buildKnowledgeGraph(
  projectId: number,
  chunkConfigId: number | null,
  overlapMaxNodes: number | null = 500,
  kgSource: string = 'chunks',
  fastMode: boolean = false,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/projects/${projectId}/build-knowledge-graph`, {
    method: 'POST',
    body: JSON.stringify({
      chunk_config_id: chunkConfigId,
      overlap_max_nodes: overlapMaxNodes,
      fast_mode: fastMode || undefined,
      kg_source: kgSource,
    }),
  });
}

export async function fetchKGBuildProgress(
  projectId: number,
  kgSource: string = 'chunks',
): Promise<KGBuildProgress> {
  return request<KGBuildProgress>(
    `/api/projects/${projectId}/knowledge-graph/progress?kg_source=${encodeURIComponent(kgSource)}`,
  );
}

export async function deleteKnowledgeGraph(
  projectId: number,
  kgSource: string = 'chunks',
): Promise<void> {
  await request<void>(
    `/api/projects/${projectId}/knowledge-graph?kg_source=${encodeURIComponent(kgSource)}`,
    { method: 'DELETE' },
  );
}

export async function resetKnowledgeGraph(
  projectId: number,
  kgSource: string = 'chunks',
): Promise<{ deleted: boolean; was_complete?: boolean }> {
  return request<{ deleted: boolean; was_complete?: boolean }>(
    `/api/projects/${projectId}/knowledge-graph/reset?kg_source=${encodeURIComponent(kgSource)}`,
    { method: 'POST' },
  );
}

export async function rebuildKGLinks(
  projectId: number,
  overlapMaxNodes: number | null = 500,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/projects/${projectId}/knowledge-graph/rebuild-links`, {
    method: 'POST',
    body: JSON.stringify({ overlap_max_nodes: overlapMaxNodes }),
  });
}

export async function updateKnowledgeGraph(
  projectId: number,
  chunkConfigId: number,
  overlapMaxNodes: number | null = 500,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/projects/${projectId}/knowledge-graph/update`, {
    method: 'POST',
    body: JSON.stringify({
      chunk_config_id: chunkConfigId,
      overlap_max_nodes: overlapMaxNodes,
    }),
  });
}

// --- Knowledge Graph Explorer ---

export async function fetchAllKnowledgeGraphs(): Promise<KGListItem[]> {
  return request<KGListItem[]>('/api/knowledge-graphs');
}

export async function fetchKnowledgeGraphData(projectId: number): Promise<KGGraphData> {
  return request<KGGraphData>(`/api/projects/${projectId}/knowledge-graph/data`);
}

export function streamKnowledgeGraphData(
  projectId: number,
  callbacks: KGStreamCallbacks,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`/api/projects/${projectId}/knowledge-graph/stream`, {
        signal: controller.signal,
      });
      if (!res.ok) {
        const body = await res.text().catch(() => 'Unknown error');
        callbacks.onError(body);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const json = line.slice(6);
          try {
            const event = JSON.parse(json);
            switch (event.type) {
              case 'meta':
                callbacks.onMeta(event);
                break;
              case 'nodes':
                callbacks.onNodes(event.batch);
                break;
              case 'edges':
                callbacks.onEdges(event.batch);
                break;
              case 'done':
                callbacks.onDone();
                break;
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        callbacks.onError((err as Error).message || 'Stream failed');
      }
    }
  })();

  return () => controller.abort();
}

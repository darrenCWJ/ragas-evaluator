// Personas domain — saved persona CRUD and persona generation

import { request } from './client';
import type { SavedPersona } from './types';

export async function fetchPersonas(projectId: number): Promise<SavedPersona[]> {
  const data = await request<{ personas: SavedPersona[] }>(`/api/projects/${projectId}/personas`);
  return data.personas;
}

export async function savePersonasBulk(
  projectId: number,
  personas: { name: string; role_description: string; question_style: string }[],
): Promise<SavedPersona[]> {
  const data = await request<{ personas: SavedPersona[] }>(
    `/api/projects/${projectId}/personas/bulk`,
    {
      method: 'POST',
      body: JSON.stringify(personas),
    },
  );
  return data.personas;
}

export async function updatePersona(
  projectId: number,
  personaId: number,
  updates: { name?: string; role_description?: string; question_style?: string },
): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/personas/${personaId}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
}

export async function deletePersona(projectId: number, personaId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/personas/${personaId}`, {
    method: 'DELETE',
  });
}

export async function generatePersonas(
  projectId: number,
  chunkConfigId: number,
  numPersonas: number = 3,
  mode: 'fast' | 'full' = 'fast',
  signal?: AbortSignal,
): Promise<{ name: string; role_description: string; question_style: string }[]> {
  type PersonaResult = { name: string; role_description: string; question_style: string };
  type StartResponse = { status: string; personas?: PersonaResult[] };

  const start = await request<StartResponse>(`/api/projects/${projectId}/generate-personas`, {
    method: 'POST',
    body: JSON.stringify({ chunk_config_id: chunkConfigId, num_personas: numPersonas, mode }),
    signal,
  });

  // Fast mode returns personas immediately
  if (start.personas) return start.personas;

  // Full mode: poll until completed or error
  const sleep = (ms: number) =>
    new Promise<void>((res, rej) => {
      const t = setTimeout(res, ms);
      signal?.addEventListener('abort', () => {
        clearTimeout(t);
        rej(new DOMException('Aborted', 'AbortError'));
      });
    });

  while (true) {
    await sleep(4000);
    const poll = await request<{ status: string; personas?: PersonaResult[]; detail?: string }>(
      `/api/projects/${projectId}/generate-personas/status`,
      { signal },
    );
    if (poll.status === 'completed' && poll.personas) return poll.personas;
    if (poll.status === 'error') throw new Error(poll.detail ?? 'Persona generation failed');
  }
}

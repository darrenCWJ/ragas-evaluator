// Skill Arena domain — skill file CRUD, cross-model trials, results, and model apply

import { request } from './client';
import type {
  ApplyModelResponse,
  Skill,
  SkillTrial,
  SkillTrialCreatePayload,
  SkillTrialCreateResponse,
  SkillTrialDetail,
  SkillTrialProgress,
  SkillTrialResult,
  SkillTrialVariant,
} from './types';

// --- Skill CRUD ---

export async function createSkill(
  projectId: number,
  payload: { content: string; name?: string },
): Promise<Skill> {
  return request<Skill>(`/api/projects/${projectId}/skills`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchSkills(projectId: number): Promise<Skill[]> {
  return request<Skill[]>(`/api/projects/${projectId}/skills`);
}

export async function fetchSkill(projectId: number, skillId: number): Promise<Skill> {
  return request<Skill>(`/api/projects/${projectId}/skills/${skillId}`);
}

export async function deleteSkill(projectId: number, skillId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/skills/${skillId}`, {
    method: 'DELETE',
  });
}

// --- Trial lifecycle ---

export async function createSkillTrial(
  projectId: number,
  payload: SkillTrialCreatePayload,
): Promise<SkillTrialCreateResponse> {
  return request<SkillTrialCreateResponse>(`/api/projects/${projectId}/skill-trials`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchSkillTrials(projectId: number): Promise<SkillTrial[]> {
  return request<SkillTrial[]>(`/api/projects/${projectId}/skill-trials`);
}

export async function fetchSkillTrial(
  projectId: number,
  trialId: number,
): Promise<SkillTrialDetail> {
  return request<SkillTrialDetail>(`/api/projects/${projectId}/skill-trials/${trialId}`);
}

export async function fetchSkillTrialProgress(
  projectId: number,
  trialId: number,
): Promise<SkillTrialProgress> {
  return request<SkillTrialProgress>(`/api/projects/${projectId}/skill-trials/${trialId}/progress`);
}

export async function cancelSkillTrial(
  projectId: number,
  trialId: number,
): Promise<{ detail: string }> {
  return request<{ detail: string }>(`/api/projects/${projectId}/skill-trials/${trialId}/cancel`, {
    method: 'POST',
  });
}

export async function fetchSkillTrialResults(
  projectId: number,
  trialId: number,
  opts?: { model?: string; variant?: SkillTrialVariant; limit?: number },
): Promise<SkillTrialResult[]> {
  const params = new URLSearchParams();
  if (opts?.model) params.set('model', opts.model);
  if (opts?.variant) params.set('variant', opts.variant);
  if (opts?.limit) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return request<SkillTrialResult[]>(
    `/api/projects/${projectId}/skill-trials/${trialId}/results${qs ? `?${qs}` : ''}`,
  );
}

// --- Apply winning model ---

export async function applyPreferredModel(
  projectId: number,
  model: string,
): Promise<ApplyModelResponse> {
  return request<ApplyModelResponse>(`/api/projects/${projectId}/apply-model`, {
    method: 'POST',
    body: JSON.stringify({ model }),
  });
}

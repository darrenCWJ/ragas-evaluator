// Projects domain — projects, judge models, config defaults, external baselines, API configs, bot configs, project report

import { request, formRequest } from './client';
import type {
  Project,
  JudgeModelsResponse,
  ConfigDefaults,
  ExternalBaseline,
  CsvUploadResult,
  CsvPreviewResult,
  ApiConfig,
  ApiConfigCreate,
  BotConfig,
  BotConfigCreatePayload,
  BotConfigBaselinesResult,
  ProjectReport,
} from './types';

interface CreateProjectPayload {
  name: string;
  description: string;
}

// --- Config Defaults API ---

let _configCache: ConfigDefaults | null = null;

export async function fetchConfigDefaults(): Promise<ConfigDefaults> {
  if (_configCache) return _configCache;
  _configCache = await request<ConfigDefaults>('/api/config/defaults');
  return _configCache;
}

export async function fetchProjects(): Promise<Project[]> {
  return request<Project[]>('/api/projects');
}

export async function fetchProject(projectId: number): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`);
}

export async function createProject(payload: CreateProjectPayload): Promise<Project> {
  return request<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchJudgeModels(): Promise<JudgeModelsResponse> {
  return request<JudgeModelsResponse>('/api/judge-models');
}

export async function deleteProject(projectId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}`, {
    method: 'DELETE',
  });
}

export async function updateProjectJudgeDefaults(
  projectId: number,
  assignments: string[] | null,
): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ judge_model_assignments: assignments }),
  });
}

// --- External Baseline API ---

export async function previewBaselineCsv(projectId: number, file: File): Promise<CsvPreviewResult> {
  const form = new FormData();
  form.append('file', file);
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
  form.append('file', file);
  form.append('question_col', columnMapping.questionCol);
  form.append('answer_col', columnMapping.answerCol);
  if (columnMapping.referenceAnswerCol)
    form.append('reference_answer_col', columnMapping.referenceAnswerCol);
  if (columnMapping.contextCol) form.append('context_col', columnMapping.contextCol);
  if (columnMapping.configName) form.append('config_name', columnMapping.configName);
  return formRequest<CsvUploadResult>(`/api/projects/${projectId}/baselines/upload-csv`, form);
}

export async function fetchBaselines(projectId: number): Promise<ExternalBaseline[]> {
  return request<ExternalBaseline[]>(`/api/projects/${projectId}/baselines`);
}

export async function deleteBaseline(projectId: number, baselineId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/baselines/${baselineId}`, {
    method: 'DELETE',
  });
}

export async function clearBaselines(projectId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/baselines`, { method: 'DELETE' });
}

// --- API Config API ---

export async function saveApiConfig(
  projectId: number,
  payload: ApiConfigCreate,
): Promise<ApiConfig> {
  return request<ApiConfig>(`/api/projects/${projectId}/api-config`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchApiConfig(projectId: number): Promise<ApiConfig> {
  return request<ApiConfig>(`/api/projects/${projectId}/api-config`);
}

export async function deleteApiConfig(projectId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/api-config`, { method: 'DELETE' });
}

// --- Bot Config API ---

export async function fetchBotConfigs(projectId: number): Promise<BotConfig[]> {
  return request<BotConfig[]>(`/api/projects/${projectId}/bot-configs`);
}

export async function createBotConfig(
  projectId: number,
  payload: BotConfigCreatePayload,
): Promise<BotConfig> {
  return request<BotConfig>(`/api/projects/${projectId}/bot-configs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateBotConfig(
  projectId: number,
  configId: number,
  payload: Partial<BotConfigCreatePayload>,
): Promise<BotConfig> {
  return request<BotConfig>(`/api/projects/${projectId}/bot-configs/${configId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteBotConfig(projectId: number, configId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/bot-configs/${configId}`, {
    method: 'DELETE',
  });
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

// --- Project Report API ---

export async function fetchProjectReport(projectId: number): Promise<ProjectReport> {
  return request<ProjectReport>(`/api/projects/${projectId}/report`);
}

// Tool definitions for agentic experiments
import { request } from './client';

export interface ToolDefinition {
  id: number;
  project_id: number;
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  mode: 'mock' | 'simulated' | 'builtin';
  fixtures: Record<string, unknown> | null;
  builtin_name: string | null;
  created_at: string;
}

export interface BuiltinTool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ToolDefinitionCreate {
  name: string;
  description: string;
  parameters?: Record<string, unknown> | null;
  mode: 'mock' | 'simulated' | 'builtin';
  fixtures?: Record<string, unknown> | null;
  builtin_name?: string | null;
}

export async function fetchTools(projectId: number): Promise<ToolDefinition[]> {
  const data = await request<{ tools: ToolDefinition[] }>(`/api/projects/${projectId}/tools`);
  return data.tools;
}

export async function fetchBuiltinTools(): Promise<BuiltinTool[]> {
  const data = await request<{ builtins: BuiltinTool[] }>('/api/tools/builtins');
  return data.builtins;
}

export async function createTool(
  projectId: number,
  tool: ToolDefinitionCreate,
): Promise<ToolDefinition> {
  return request<ToolDefinition>(`/api/projects/${projectId}/tools`, {
    method: 'POST',
    body: JSON.stringify(tool),
  });
}

export async function deleteTool(projectId: number, toolId: number): Promise<void> {
  await request<void>(`/api/projects/${projectId}/tools/${toolId}`, { method: 'DELETE' });
}

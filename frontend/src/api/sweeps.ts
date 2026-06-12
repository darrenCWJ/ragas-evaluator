// Parameter sweeps — grid over retrieval params, one experiment per combo,
// ranked by a judge-free leaderboard (retrieval_hit_rate, then overall).

import { request } from './client';

export interface SweepRun {
  id: number;
  experiment_id: number | null;
  params: Record<string, unknown>;
  status: string;
}

export interface Sweep {
  id: number;
  project_id: number;
  name: string;
  test_set_id: number;
  base_rag_config_id: number;
  grid: Record<string, unknown[]>;
  metrics: string[];
  status: string;
  error_message: string | null;
  created_at: string;
}

export interface SweepListItem extends Sweep {
  run_counts: Record<string, number>;
}

export interface SweepDetail extends Sweep {
  runs: SweepRun[];
}

export interface SweepCreatePayload {
  name: string;
  test_set_id: number;
  rag_config_id: number;
  grid: Record<string, unknown[]>;
  metrics?: string[];
  concurrency?: number;
}

export interface SweepLeaderboardEntry {
  run_id: number;
  experiment_id: number | null;
  params: Record<string, unknown>;
  status: string;
  aggregate_metrics: Record<string, number | null> | null;
  overall_score: number | null;
  result_count: number;
}

export interface SweepLeaderboard {
  sweep_id: number;
  status: string;
  leaderboard: SweepLeaderboardEntry[];
}

export async function createSweep(
  projectId: number,
  payload: SweepCreatePayload,
): Promise<Sweep & { num_runs: number }> {
  return request(`/api/projects/${projectId}/sweeps`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchSweeps(projectId: number): Promise<SweepListItem[]> {
  return request(`/api/projects/${projectId}/sweeps`);
}

export async function fetchSweep(projectId: number, sweepId: number): Promise<SweepDetail> {
  return request(`/api/projects/${projectId}/sweeps/${sweepId}`);
}

export async function fetchSweepLeaderboard(
  projectId: number,
  sweepId: number,
): Promise<SweepLeaderboard> {
  return request(`/api/projects/${projectId}/sweeps/${sweepId}/leaderboard`);
}

export async function cancelSweep(projectId: number, sweepId: number): Promise<{ detail: string }> {
  return request(`/api/projects/${projectId}/sweeps/${sweepId}/cancel`, { method: 'POST' });
}

export async function deleteSweep(projectId: number, sweepId: number): Promise<void> {
  return request(`/api/projects/${projectId}/sweeps/${sweepId}`, { method: 'DELETE' });
}

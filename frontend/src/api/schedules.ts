// Scheduled regression runs against external agents, with metric-drop alerts.

import { request } from './client';

export interface ScheduleAlertDrop {
  metric: string;
  baseline: number;
  current: number;
  drop: number;
}

export interface ScheduleAlert {
  id: number;
  experiment_id: number | null;
  baseline_experiment_id: number | null;
  drops: ScheduleAlertDrop[];
  acknowledged: boolean;
  created_at: string;
}

export interface Schedule {
  id: number;
  project_id: number;
  name: string;
  bot_config_id: number;
  test_set_id: number;
  metrics: string[];
  interval_minutes: number;
  alert_drop_threshold: number;
  webhook_url: string | null;
  enabled: boolean;
  last_run_at: string | null;
  last_experiment_id: number | null;
  created_at: string;
}

export interface ScheduleListItem extends Schedule {
  open_alerts: number;
}

export interface ScheduleDetail extends Schedule {
  alerts: ScheduleAlert[];
}

export interface ScheduleCreatePayload {
  name: string;
  bot_config_id: number;
  test_set_id: number;
  interval_minutes: number;
  metrics?: string[];
  alert_drop_threshold?: number;
  webhook_url?: string | null;
}

export interface ScheduleUpdatePayload {
  name?: string;
  interval_minutes?: number;
  metrics?: string[];
  alert_drop_threshold?: number;
  webhook_url?: string | null;
  enabled?: boolean;
}

export async function createSchedule(
  projectId: number,
  payload: ScheduleCreatePayload,
): Promise<Schedule> {
  return request(`/api/projects/${projectId}/schedules`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchSchedules(projectId: number): Promise<ScheduleListItem[]> {
  return request(`/api/projects/${projectId}/schedules`);
}

export async function fetchSchedule(
  projectId: number,
  scheduleId: number,
): Promise<ScheduleDetail> {
  return request(`/api/projects/${projectId}/schedules/${scheduleId}`);
}

export async function updateSchedule(
  projectId: number,
  scheduleId: number,
  payload: ScheduleUpdatePayload,
): Promise<Schedule> {
  return request(`/api/projects/${projectId}/schedules/${scheduleId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteSchedule(projectId: number, scheduleId: number): Promise<void> {
  return request(`/api/projects/${projectId}/schedules/${scheduleId}`, { method: 'DELETE' });
}

export async function runScheduleNow(
  projectId: number,
  scheduleId: number,
): Promise<{ detail: string }> {
  return request(`/api/projects/${projectId}/schedules/${scheduleId}/run-now`, {
    method: 'POST',
  });
}

export async function acknowledgeScheduleAlert(
  projectId: number,
  scheduleId: number,
  alertId: number,
): Promise<{ detail: string }> {
  return request(`/api/projects/${projectId}/schedules/${scheduleId}/alerts/${alertId}/ack`, {
    method: 'POST',
  });
}

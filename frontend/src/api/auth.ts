// Auth domain — session status, register/login/logout, current user, admin
// user management, and project membership.

import { request } from './client';
import type { AdminUserRow, AuthStatus, AuthUser, ProjectMembers, UserRole } from './types';

export interface RegisterPayload {
  email: string;
  name: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>('/api/auth/status');
}

export async function registerUser(payload: RegisterPayload): Promise<AuthUser> {
  return request<AuthUser>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function loginUser(payload: LoginPayload): Promise<AuthUser> {
  return request<AuthUser>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function logoutUser(): Promise<void> {
  await request<{ detail: string }>('/api/auth/logout', { method: 'POST' });
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  return request<AuthUser>('/api/auth/me');
}

// --- Admin: user management ---

export async function fetchUsers(): Promise<AdminUserRow[]> {
  return request<AdminUserRow[]>('/api/auth/users');
}

export async function updateUserRole(userId: number, role: UserRole): Promise<AuthUser> {
  return request<AuthUser>(`/api/auth/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

// --- Project membership ---

export async function fetchProjectMembers(projectId: number): Promise<ProjectMembers> {
  return request<ProjectMembers>(`/api/projects/${projectId}/members`);
}

export async function addProjectMember(
  projectId: number,
  email: string,
): Promise<{ detail: string; user_id: number }> {
  return request<{ detail: string; user_id: number }>(`/api/projects/${projectId}/members`, {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function removeProjectMember(projectId: number, userId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/members/${userId}`, {
    method: 'DELETE',
  });
}

// Documents domain — upload, list, delete documents and context labels

import { request, formRequest } from './client';
import type { Document } from './types';

export async function fetchDocuments(projectId: number): Promise<Document[]> {
  return request<Document[]>(`/api/projects/${projectId}/documents`);
}

export async function uploadDocument(projectId: number, file: File): Promise<Document> {
  const form = new FormData();
  form.append('file', file);
  return formRequest<Document>(`/api/projects/${projectId}/documents`, form);
}

export async function deleteDocument(projectId: number, docId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/documents/${docId}`, {
    method: 'DELETE',
  });
}

export async function deleteAllDocuments(projectId: number): Promise<void> {
  await request<{ detail: string }>(`/api/projects/${projectId}/documents`, { method: 'DELETE' });
}

export async function updateDocumentContextLabel(
  projectId: number,
  documentId: number,
  contextLabel: string,
): Promise<{ detail: string; context_label: string }> {
  return request<{ detail: string; context_label: string }>(
    `/api/projects/${projectId}/documents/${documentId}/context-label`,
    {
      method: 'PATCH',
      body: JSON.stringify({ context_label: contextLabel }),
    },
  );
}

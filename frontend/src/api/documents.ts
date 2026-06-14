// Documents domain — upload, list, delete documents and context labels

import { request, formRequest } from './client';
import type { Document } from './types';

export async function fetchDocuments(projectId: number): Promise<Document[]> {
  return request<Document[]>(`/api/projects/${projectId}/documents`);
}

export interface DocumentProcessingOptions {
  /** Render DOCX/PPTX tables as markdown rows in the extracted text (default true). */
  extractTables?: boolean;
  /** Describe embedded images (PPTX/DOCX/PDF) with the vision LLM (default false). */
  describeImages?: boolean;
}

export async function uploadDocument(
  projectId: number,
  file: File,
  options?: DocumentProcessingOptions,
): Promise<Document> {
  const form = new FormData();
  form.append('file', file);
  if (options?.extractTables !== undefined) {
    form.append('extract_tables', String(options.extractTables));
  }
  if (options?.describeImages !== undefined) {
    form.append('describe_images', String(options.describeImages));
  }
  return formRequest<Document>(`/api/projects/${projectId}/documents`, form);
}

export interface ReprocessResult {
  id: number;
  filename: string;
  images_described: number;
  content_chars: number;
  note: string;
}

export async function reprocessDocument(
  projectId: number,
  docId: number,
  options: DocumentProcessingOptions,
): Promise<ReprocessResult> {
  return request<ReprocessResult>(`/api/projects/${projectId}/documents/${docId}/reprocess`, {
    method: 'POST',
    body: JSON.stringify({
      extract_tables: options.extractTables ?? true,
      describe_images: options.describeImages ?? false,
    }),
  });
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

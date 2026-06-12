// Shared API core — ApiError, error extraction, and typed fetch helpers used by all domain modules

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Extract a human-readable error detail from a failed response body.
 * Handles FastAPI-style `detail` payloads (string or validation-error array),
 * falling back to the raw body text.
 */
async function extractError(res: Response): Promise<string> {
  const body = await res.text().catch(() => 'Unknown error');
  let detail = body;
  try {
    const parsed = JSON.parse(body);
    if (parsed.detail) {
      detail = Array.isArray(parsed.detail)
        ? parsed.detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join('; ')
        : String(parsed.detail);
    }
  } catch {
    // use raw body
  }
  return detail;
}

/**
 * Send a FormData request and parse the response, extracting error detail on failure.
 */
export async function formRequest<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: 'POST', body: form });
  if (!res.ok) {
    throw new ApiError(res.status, await extractError(res));
  }
  return res.json() as Promise<T>;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!res.ok) {
    throw new ApiError(res.status, await extractError(res));
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

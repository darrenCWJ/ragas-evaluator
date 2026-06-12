import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, UNAUTHORIZED_EVENT, formRequest, request } from './client';

interface FakeResponseOptions {
  ok?: boolean;
  status?: number;
  body?: string;
  textRejects?: boolean;
}

function fakeResponse({
  ok = true,
  status = 200,
  body = '{}',
  textRejects = false,
}: FakeResponseOptions): Response {
  return {
    ok,
    status,
    json: async () => JSON.parse(body),
    text: textRejects ? async () => Promise.reject(new Error('stream broken')) : async () => body,
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('request', () => {
  it('returns parsed JSON on success and sends a JSON content type', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ body: '{"id": 7}' }));

    const result = await request<{ id: number }>('/api/projects/7');

    expect(result).toEqual({ id: 7 });
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/projects/7');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('returns undefined for 204 responses without reading the body', async () => {
    const res = fakeResponse({ status: 204, body: '' });
    res.json = async () => {
      throw new Error('json() must not be called on 204');
    };
    fetchMock.mockResolvedValue(res);

    await expect(request('/api/projects/7')).resolves.toBeUndefined();
  });

  it('throws ApiError with the FastAPI detail string', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 400, body: '{"detail": "name already exists"}' }),
    );

    const err = await request('/api/projects').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
    expect((err as ApiError).message).toBe('name already exists');
  });

  it('joins FastAPI validation-error arrays into one message', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({
        ok: false,
        status: 422,
        body: '{"detail": [{"msg": "field required"}, {"loc": ["body", "x"]}]}',
      }),
    );

    const err = await request('/api/projects').catch((e: unknown) => e);

    expect((err as ApiError).message).toBe('field required; {"loc":["body","x"]}');
  });

  it('falls back to the raw body when it is not JSON', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 502, body: 'Bad Gateway from nginx' }),
    );

    const err = await request('/api/projects').catch((e: unknown) => e);

    expect((err as ApiError).message).toBe('Bad Gateway from nginx');
  });

  it('uses "Unknown error" when the body cannot be read', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ ok: false, status: 500, textRejects: true }));

    const err = await request('/api/projects').catch((e: unknown) => e);

    expect((err as ApiError).message).toBe('Unknown error');
  });

  it('dispatches the unauthorized event on 401 from a non-auth path', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 401, body: '{"detail": "Not authenticated"}' }),
    );
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(request('/api/projects')).rejects.toBeInstanceOf(ApiError);

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it('does NOT dispatch the unauthorized event for /api/auth/ paths', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 401, body: '{"detail": "bad credentials"}' }),
    );
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(request('/api/auth/login')).rejects.toBeInstanceOf(ApiError);

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it('does not dispatch the unauthorized event for non-401 errors', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ ok: false, status: 403, body: '"forbidden"' }));
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(request('/api/projects')).rejects.toBeInstanceOf(ApiError);

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });
});

describe('formRequest', () => {
  it('POSTs the FormData without forcing a JSON content type', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ body: '{"uploaded": true}' }));
    const form = new FormData();
    form.set('name', 'doc.pdf');

    const result = await formRequest<{ uploaded: boolean }>('/api/documents', form);

    expect(result).toEqual({ uploaded: true });
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/documents');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(form);
    expect(init.headers).toBeUndefined();
  });

  it('throws ApiError with extracted detail on failure', async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 413, body: '{"detail": "file too large"}' }),
    );

    const err = await formRequest('/api/documents', new FormData()).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(413);
    expect((err as ApiError).message).toBe('file too large');
  });

  it('dispatches the unauthorized event on 401', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ ok: false, status: 401, body: '"expired"' }));
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(formRequest('/api/documents', new FormData())).rejects.toBeInstanceOf(ApiError);

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });
});

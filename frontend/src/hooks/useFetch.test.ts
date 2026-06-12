import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useFetch } from './useFetch';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useFetch', () => {
  it('starts loading, then exposes the resolved data', async () => {
    const { result } = renderHook(() => useFetch(() => Promise.resolve('payload'), []));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe('payload');
    expect(result.current.error).toBeNull();
  });

  it('surfaces the error message when the fetch rejects', async () => {
    const { result } = renderHook(() =>
      useFetch(() => Promise.reject(new Error('server exploded')), []),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('server exploded');
    expect(result.current.data).toBeNull();
  });

  it('uses a generic message for non-Error rejections', async () => {
    const { result } = renderHook(() => useFetch(() => Promise.reject('string reason'), []));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('Request failed');
  });

  it('reload() re-runs the fetch function', async () => {
    let calls = 0;
    const { result } = renderHook(() =>
      useFetch(() => {
        calls += 1;
        return Promise.resolve(calls);
      }, []),
    );

    await waitFor(() => expect(result.current.data).toBe(1));

    await result.current.reload();

    await waitFor(() => expect(result.current.data).toBe(2));
    expect(result.current.error).toBeNull();
  });

  it('ignores stale resolutions when deps change mid-flight', async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const fns = [() => first.promise, () => second.promise];

    const { result, rerender } = renderHook(
      ({ dep }: { dep: number }) => useFetch(fns[dep]!, [dep]),
      {
        initialProps: { dep: 0 },
      },
    );

    // Switch deps while the first request is still pending, then resolve
    // the second request first and the (now stale) first request afterwards.
    rerender({ dep: 1 });
    second.resolve('fresh');
    await waitFor(() => expect(result.current.data).toBe('fresh'));

    first.resolve('stale');
    await new Promise((r) => setTimeout(r, 0));

    expect(result.current.data).toBe('fresh');
    expect(result.current.loading).toBe(false);
  });

  it('ignores resolutions that land after unmount', async () => {
    const pending = deferred<string>();
    const { result, unmount } = renderHook(() => useFetch(() => pending.promise, []));

    unmount();
    pending.resolve('too late');
    await new Promise((r) => setTimeout(r, 0));

    // No state update after unmount — data stays at its initial value.
    expect(result.current.data).toBeNull();
  });
});

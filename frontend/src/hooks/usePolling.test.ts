import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePolling } from './usePolling';

const INTERVAL = 1_000;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Flush microtasks so the polling loop's awaits settle under fake timers. */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('usePolling', () => {
  it('does nothing while inactive', async () => {
    const fn = vi.fn().mockResolvedValue('continue');
    renderHook(() => usePolling(fn, INTERVAL, false));

    await flush();
    await tick(INTERVAL * 3);

    expect(fn).not.toHaveBeenCalled();
  });

  it('polls on the interval until fn returns "stop"', async () => {
    const fn = vi
      .fn()
      .mockResolvedValueOnce('continue')
      .mockResolvedValueOnce('continue')
      .mockResolvedValue('stop');
    const { result } = renderHook(() => usePolling(fn, INTERVAL, true));

    await flush();
    expect(fn).toHaveBeenCalledTimes(1);

    await tick(INTERVAL);
    expect(fn).toHaveBeenCalledTimes(2);

    await tick(INTERVAL);
    expect(fn).toHaveBeenCalledTimes(3);

    // Loop ended on 'stop' — no further calls.
    await tick(INTERVAL * 3);
    expect(fn).toHaveBeenCalledTimes(3);
    expect(result.current.error).toBeNull();
  });

  it('tolerates transient failures and resets the failure counter on success', async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValueOnce('continue')
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValue('stop');
    const { result } = renderHook(() => usePolling(fn, INTERVAL, true));

    await flush();
    await tick(INTERVAL);
    await tick(INTERVAL);
    await tick(INTERVAL);

    expect(fn).toHaveBeenCalledTimes(4);
    expect(result.current.error).toBeNull();
  });

  it('gives up after 5 consecutive failures, sets error, and notifies once', async () => {
    const failure = new Error('connection refused');
    const fn = vi.fn().mockRejectedValue(failure);
    const onPersistentFailure = vi.fn();
    const { result } = renderHook(() => usePolling(fn, INTERVAL, true, onPersistentFailure));

    await flush();
    for (let i = 0; i < 4; i++) {
      await tick(INTERVAL);
    }

    expect(fn).toHaveBeenCalledTimes(5);
    expect(result.current.error).toBe('Lost connection: connection refused');
    expect(onPersistentFailure).toHaveBeenCalledTimes(1);
    expect(onPersistentFailure).toHaveBeenCalledWith(failure);

    // Loop has stopped for good.
    await tick(INTERVAL * 3);
    expect(fn).toHaveBeenCalledTimes(5);
  });

  it('stops polling when unmounted', async () => {
    const fn = vi.fn().mockResolvedValue('continue');
    const { unmount } = renderHook(() => usePolling(fn, INTERVAL, true));

    await flush();
    expect(fn).toHaveBeenCalledTimes(1);

    unmount();
    await tick(INTERVAL * 3);

    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('stops polling when active flips to false', async () => {
    const fn = vi.fn().mockResolvedValue('continue');
    const { rerender } = renderHook(
      ({ active }: { active: boolean }) => usePolling(fn, INTERVAL, active),
      {
        initialProps: { active: true },
      },
    );

    await flush();
    expect(fn).toHaveBeenCalledTimes(1);

    rerender({ active: false });
    await tick(INTERVAL * 3);

    expect(fn).toHaveBeenCalledTimes(1);
  });
});

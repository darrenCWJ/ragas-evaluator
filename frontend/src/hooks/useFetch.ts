import { useCallback, useEffect, useRef, useState } from 'react';

interface FetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Load data with loading/error state and stale-resolution protection.
 * `reload()` re-runs the fetch (e.g. after a mutation).
 */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<FetchState<T>>({ data: null, loading: true, error: null });
  const generation = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    const gen = ++generation.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fnRef.current();
      if (gen === generation.current) setState({ data, loading: false, error: null });
    } catch (err) {
      if (gen === generation.current) {
        setState({
          data: null,
          loading: false,
          error: err instanceof Error ? err.message : 'Request failed',
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    load();
    return () => {
      // Invalidate in-flight resolutions on unmount/dep change
      generation.current++;
    };
  }, [load]);

  return { ...state, reload: load };
}

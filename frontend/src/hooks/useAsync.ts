import { useState, useCallback } from "react";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useAsync<T>(fn: (...args: never[]) => Promise<T>) {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const execute = useCallback(
    async (...args: Parameters<typeof fn>) => {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const data = await fn(...args);
        setState({ data, loading: false, error: null });
        return data;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "An error occurred";
        setState((prev) => ({ ...prev, loading: false, error: message }));
        throw err;
      }
    },
    [fn],
  );

  return { ...state, execute };
}

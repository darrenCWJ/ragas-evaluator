import { useEffect, useRef, useState } from 'react';

const MAX_CONSECUTIVE_FAILURES = 5;

/**
 * Poll `fn` every `intervalMs` while `active` is true.
 *
 * `fn` returns 'continue' to keep polling or 'stop' to end the loop.
 * Transient failures are tolerated; after 5 consecutive failures the loop
 * stops and `error` is set — never spin forever against a dead server.
 */
export function usePolling(
  fn: () => Promise<'continue' | 'stop'>,
  intervalMs: number,
  active: boolean,
) {
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let failures = 0;
    setError(null);

    const loop = async () => {
      while (!cancelled) {
        try {
          const verdict = await fnRef.current();
          if (cancelled || verdict === 'stop') break;
          failures = 0;
        } catch (err) {
          failures += 1;
          if (failures >= MAX_CONSECUTIVE_FAILURES) {
            if (!cancelled) {
              setError(
                err instanceof Error
                  ? `Lost connection: ${err.message}`
                  : 'Lost connection while polling for progress.',
              );
            }
            break;
          }
        }
        await new Promise((r) => setTimeout(r, intervalMs));
      }
    };
    loop();
    return () => {
      cancelled = true;
    };
  }, [active, intervalMs]);

  return { error };
}

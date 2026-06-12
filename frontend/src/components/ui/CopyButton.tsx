import { useEffect, useRef, useState } from 'react';

const FEEDBACK_DURATION_MS = 1500;

type CopyState = 'idle' | 'copied' | 'failed';

interface CopyButtonProps {
  text: string;
  label?: string;
}

/** Small copy-to-clipboard button with brief "Copied" feedback. */
export default function CopyButton({ text, label = 'Copy' }: CopyButtonProps) {
  const [copyState, setCopyState] = useState<CopyState>('idle');
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setCopyState('idle'), FEEDBACK_DURATION_MS);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`shrink-0 rounded-md border border-border px-2 py-0.5 text-2xs font-medium transition hover:bg-elevated ${
        copyState === 'copied'
          ? 'text-emerald-400'
          : copyState === 'failed'
            ? 'text-red-400'
            : 'text-text-secondary'
      }`}
    >
      {copyState === 'copied' ? 'Copied' : copyState === 'failed' ? 'Copy failed' : label}
    </button>
  );
}

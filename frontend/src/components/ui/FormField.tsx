import { type ReactNode } from 'react';

interface FormFieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}

/** Label + control + optional hint/error, matching the existing form layout. */
export default function FormField({ label, hint, error, children }: FormFieldProps) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-text-secondary">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-text-muted">{hint}</p>}
      {error && <p className="mt-1 text-xs text-score-low">{error}</p>}
    </div>
  );
}

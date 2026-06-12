interface EmptyStateProps {
  title: string;
  hint?: string;
}

/** Muted centered placeholder for empty lists/sections. */
export default function EmptyState({ title, hint }: EmptyStateProps) {
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <p className="text-sm text-text-secondary">{title}</p>
      {hint && <p className="mt-1 text-xs text-text-muted">{hint}</p>}
    </div>
  );
}

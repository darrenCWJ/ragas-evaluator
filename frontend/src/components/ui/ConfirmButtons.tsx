interface ConfirmButtonsProps {
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
}

/** Inline confirm/cancel pair for destructive actions (no modal). */
export default function ConfirmButtons({
  onConfirm,
  onCancel,
  confirmLabel = 'Yes, delete',
}: ConfirmButtonsProps) {
  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={onConfirm}
        className="rounded-lg bg-score-low/15 px-3 py-1 text-xs font-medium text-score-low hover:bg-score-low/25"
      >
        {confirmLabel}
      </button>
      <button
        onClick={onCancel}
        className="rounded-lg border border-border px-3 py-1 text-xs text-text-secondary hover:text-text-primary"
      >
        Cancel
      </button>
    </span>
  );
}

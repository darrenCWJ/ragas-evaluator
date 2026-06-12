interface ErrorAlertProps {
  message: string | null;
  onDismiss?: () => void;
}

/** Standard inline error banner. Renders nothing when message is null. */
export default function ErrorAlert({ message, onDismiss }: ErrorAlertProps) {
  if (!message) return null;
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg bg-score-low/10 px-4 py-3 text-sm text-score-low">
      <span className="break-words">{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 text-xs underline hover:no-underline"
          aria-label="Dismiss error"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

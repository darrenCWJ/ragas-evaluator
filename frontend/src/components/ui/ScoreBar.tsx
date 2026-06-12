import { scoreBarColor, scoreTextColor } from '../experiment/scoreUtils';

interface ScoreBarProps {
  value: number | null;
  /** Show the numeric value next to the bar (default true) */
  showValue?: boolean;
}

/** Horizontal 0–1 score bar using the shared score color thresholds. */
export default function ScoreBar({ value, showValue = true }: ScoreBarProps) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className="text-xs text-text-muted">—</span>;
  }
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-input">
        <div
          className={`h-full rounded-full ${scoreBarColor(value)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showValue && (
        <span className={`text-xs font-medium tabular-nums ${scoreTextColor(value)}`}>
          {value.toFixed(2)}
        </span>
      )}
    </div>
  );
}

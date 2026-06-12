/** Shared score display utilities for experiment components */

/** Acronym words that should stay fully uppercase when humanizing metric names */
const METRIC_WORD_OVERRIDES: Record<string, string> = {
  mrr: 'MRR',
};

/** Humanize snake_case metric name → Title Case (acronyms like MRR kept uppercase) */
export function humanizeMetric(name: string): string {
  return name
    .split('_')
    .map((w) => METRIC_WORD_OVERRIDES[w] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/** Bar fill color class for a 0-1 score */
export function scoreBarColor(v: number): string {
  if (v >= 0.8) return 'bg-score-high';
  if (v >= 0.5) return 'bg-score-mid';
  return 'bg-score-low';
}

/** Background color with opacity for badges */
export function scoreBgColor(v: number): string {
  if (v >= 0.8) return 'bg-score-high/15';
  if (v >= 0.5) return 'bg-score-mid/15';
  return 'bg-score-low/15';
}

/** Text color for score values */
export function scoreTextColor(v: number): string {
  if (v >= 0.8) return 'text-score-high';
  if (v >= 0.5) return 'text-score-mid';
  return 'text-score-low';
}

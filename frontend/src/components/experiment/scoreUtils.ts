/** Shared score display utilities for experiment components */

/** Humanize snake_case metric name → Title Case */
export function humanizeMetric(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Bar fill color class for a 0-1 score */
export function scoreBarColor(v: number): string {
  if (v >= 0.8) return "bg-score-high";
  if (v >= 0.5) return "bg-score-mid";
  return "bg-score-low";
}

/** Background color with opacity for badges */
export function scoreBgColor(v: number): string {
  if (v >= 0.8) return "bg-score-high/15";
  if (v >= 0.5) return "bg-score-mid/15";
  return "bg-score-low/15";
}

/** Text color for score values */
export function scoreTextColor(v: number): string {
  if (v >= 0.8) return "text-score-high";
  if (v >= 0.5) return "text-score-mid";
  return "text-score-low";
}

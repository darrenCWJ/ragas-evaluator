import type { Dispatch, SetStateAction } from 'react';
import type { SliderCategory } from './constants';

/**
 * Redistribute percentages when one slider changes.
 * Spreads the delta evenly across the other keys, round-robin,
 * so a small change (e.g. 1%) rotates across all others instead
 * of always landing on the same key.
 */
function redistributeEvenly(
  keys: string[],
  total: number,
  prev: Record<string, number>,
): Record<string, number> {
  if (keys.length === 0) return {};

  const prevTotal = keys.reduce((s, k) => s + (prev[k] ?? 0), 0);

  // If all others are zero, split evenly
  if (prevTotal === 0) {
    const base = Math.floor(total / keys.length);
    let rem = total - base * keys.length;
    const result: Record<string, number> = {};
    for (const k of keys) {
      result[k] = base + (rem > 0 ? 1 : 0);
      if (rem > 0) rem--;
    }
    return result;
  }

  const delta = total - prevTotal; // positive = others need more, negative = others need less
  const result: Record<string, number> = {};

  // Start with current values
  for (const k of keys) {
    result[k] = prev[k] ?? 0;
  }

  // Distribute delta one unit at a time, cycling through keys
  // sorted by current value descending (shrink the biggest first when negative,
  // grow the smallest first when positive)
  const sorted =
    delta >= 0
      ? [...keys].sort((a, b) => (result[a] ?? 0) - (result[b] ?? 0)) // smallest first for growth
      : [...keys].sort((a, b) => (result[b] ?? 0) - (result[a] ?? 0)); // biggest first for shrink

  let remaining = Math.abs(delta);
  let idx = 0;
  if (sorted.length === 0) return result;
  while (remaining > 0) {
    const k = sorted[idx % sorted.length] as string;
    if (delta >= 0) {
      result[k] = (result[k] ?? 0) + 1;
    } else if ((result[k] ?? 0) > 0) {
      result[k] = (result[k] ?? 0) - 1;
    } else {
      // skip keys already at 0 when shrinking
      idx++;
      continue;
    }
    remaining--;
    idx++;
  }

  return result;
}

interface DistributionSlidersProps {
  categories: ReadonlyArray<SliderCategory>;
  distribution: Record<string, number>;
  setDistribution: Dispatch<SetStateAction<Record<string, number>>>;
  /** When provided (with `setEnabled`), each category gets an enable checkbox. */
  enabled?: Record<string, boolean>;
  setEnabled?: (next: Record<string, boolean>) => void;
  disabled: boolean;
}

/**
 * Percentage sliders for a set of categories that always sum to 100%.
 * Changing one slider redistributes the remainder across the others.
 */
export default function DistributionSliders({
  categories,
  distribution,
  setDistribution,
  enabled,
  setEnabled,
  disabled,
}: DistributionSlidersProps) {
  const hasToggles = enabled !== undefined && setEnabled !== undefined;

  const applyValue = (key: string, raw: number) => {
    setDistribution((prev) => {
      const otherKeys = categories
        .map((c) => c.key)
        .filter((k) => (enabled ? enabled[k] : true) && k !== key);
      const remaining = 100 - raw;
      const distributed = redistributeEvenly(otherKeys, remaining, prev);
      return hasToggles ? { ...prev, [key]: raw, ...distributed } : { [key]: raw, ...distributed };
    });
  };

  const handleToggle = (key: string, checked: boolean) => {
    if (!enabled || !setEnabled) return;
    const next = { ...enabled, [key]: checked };
    setEnabled(next);
    // Redistribute percentages among enabled categories
    const enabledKeys = categories.map((c) => c.key).filter((k) => next[k]);
    if (enabledKeys.length > 0) {
      const share = Math.round(100 / enabledKeys.length);
      const newDist: Record<string, number> = {};
      enabledKeys.forEach((k, i) => {
        newDist[k] = i === enabledKeys.length - 1 ? 100 - share * (enabledKeys.length - 1) : share;
      });
      categories.forEach((c) => {
        if (!next[c.key]) newDist[c.key] = 0;
      });
      setDistribution(newDist);
    }
  };

  return (
    <>
      {categories.map((cat) => {
        const isEnabled = hasToggles ? (enabled[cat.key] ?? false) : true;
        const pct = distribution[cat.key] ?? 0;
        return (
          <div key={cat.key} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              {hasToggles ? (
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={isEnabled}
                    onChange={(e) => handleToggle(cat.key, e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-border bg-input text-accent accent-accent"
                    disabled={disabled}
                  />
                  <div>
                    <label className="text-xs font-medium text-text-secondary">{cat.label}</label>
                    <p className="text-[11px] leading-tight text-text-muted">{cat.description}</p>
                  </div>
                </div>
              ) : (
                <div>
                  <label className="text-xs font-medium text-text-secondary">{cat.label}</label>
                  <p className="text-[11px] leading-tight text-text-muted">{cat.description}</p>
                </div>
              )}
              {isEnabled && (
                <div className="flex shrink-0 items-baseline gap-0.5">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={pct}
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => {
                      const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                      applyValue(cat.key, raw);
                    }}
                    disabled={disabled}
                    className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                  />
                  <span className="text-xs text-text-muted">%</span>
                </div>
              )}
            </div>
            {isEnabled && (
              <input
                type="range"
                min={0}
                max={100}
                value={pct}
                onChange={(e) => {
                  const raw = Number(e.target.value);
                  applyValue(cat.key, raw);
                }}
                className="w-full accent-accent"
                disabled={disabled}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

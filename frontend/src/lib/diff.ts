// Minimal line diff (LCS-based) for comparing skill versions.
// Good enough for instruction documents; not built for huge files — inputs
// beyond MAX_DIFF_LINES fall back to a "too large" marker.

export type DiffOp = 'same' | 'add' | 'del';

export interface DiffLine {
  op: DiffOp;
  text: string;
}

export const MAX_DIFF_LINES = 3000;

export function diffLines(oldText: string, newText: string): DiffLine[] | null {
  const a = oldText.split('\n');
  const b = newText.split('\n');
  if (a.length > MAX_DIFF_LINES || b.length > MAX_DIFF_LINES) return null;

  // Trim common prefix/suffix to keep the LCS table small
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }

  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);

  // LCS table on the changed middle section
  const n = midA.length;
  const m = midB.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i]![j] =
        midA[i] === midB[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }

  const out: DiffLine[] = a.slice(0, start).map((text) => ({ op: 'same' as const, text }));
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (midA[i] === midB[j]) {
      out.push({ op: 'same', text: midA[i]! });
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      out.push({ op: 'del', text: midA[i]! });
      i++;
    } else {
      out.push({ op: 'add', text: midB[j]! });
      j++;
    }
  }
  while (i < n) out.push({ op: 'del', text: midA[i++]! });
  while (j < m) out.push({ op: 'add', text: midB[j++]! });
  out.push(...a.slice(endA).map((text) => ({ op: 'same' as const, text })));
  return out;
}

/** Collapse long unchanged runs for display: keep `context` lines around changes. */
export function collapseUnchanged(
  lines: DiffLine[],
  context = 2,
): Array<DiffLine | { op: 'skip'; count: number }> {
  const keep = new Array<boolean>(lines.length).fill(false);
  lines.forEach((line, idx) => {
    if (line.op !== 'same') {
      for (
        let k = Math.max(0, idx - context);
        k <= Math.min(lines.length - 1, idx + context);
        k++
      ) {
        keep[k] = true;
      }
    }
  });
  const out: Array<DiffLine | { op: 'skip'; count: number }> = [];
  let skipped = 0;
  lines.forEach((line, idx) => {
    if (keep[idx]) {
      if (skipped > 0) {
        out.push({ op: 'skip', count: skipped });
        skipped = 0;
      }
      out.push(line);
    } else {
      skipped++;
    }
  });
  if (skipped > 0) out.push({ op: 'skip', count: skipped });
  return out;
}

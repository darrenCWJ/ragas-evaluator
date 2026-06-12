import type { TraceSpan } from '../../api';

interface TraceTimelineProps {
  trace: TraceSpan[];
}

const SPAN_COLORS: Record<string, string> = {
  prepare: 'bg-purple-400/70',
  query: 'bg-accent/70',
  judge: 'bg-score-mid/70',
};

function spanColor(span: TraceSpan): string {
  if (span.status === 'error') return 'bg-score-low/80';
  return SPAN_COLORS[span.name] ?? 'bg-elevated';
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/** Horizontal step-trace timeline: spans positioned by offset, sized by duration. */
export default function TraceTimeline({ trace }: TraceTimelineProps) {
  if (trace.length === 0) {
    return <p className="text-2xs text-text-muted">No trace recorded.</p>;
  }

  const totalMs = Math.max(...trace.map((s) => s.offset_ms + (s.duration_ms ?? 0)), 1);

  return (
    <div className="space-y-1">
      <div className="relative h-5 w-full overflow-hidden rounded bg-input">
        {trace.map((span, i) => {
          const left = (span.offset_ms / totalMs) * 100;
          const width = Math.max(((span.duration_ms ?? 0) / totalMs) * 100, 1);
          return (
            <div
              key={`${span.name}-${i}`}
              className={`absolute top-0 h-full ${spanColor(span)}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`${span.name}: ${formatMs(span.duration_ms ?? 0)} (at +${formatMs(span.offset_ms)})${
                span.error ? ` — ${span.error}` : ''
              }`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {trace.map((span, i) => (
          <span
            key={`${span.name}-label-${i}`}
            className={`inline-flex items-center gap-1 text-2xs ${
              span.status === 'error' ? 'text-score-low' : 'text-text-muted'
            }`}
            title={span.error}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${spanColor(span)}`} />
            {span.name} {formatMs(span.duration_ms ?? 0)}
          </span>
        ))}
        <span className="text-2xs text-text-muted">total {formatMs(totalMs)}</span>
      </div>
    </div>
  );
}

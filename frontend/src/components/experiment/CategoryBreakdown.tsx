import { useState } from 'react';
import { fetchExperimentBreakdown } from '../../lib/api';
import type { CategoryBreakdown as CategoryRow, ExperimentBreakdown } from '../../lib/api';
import { useFetch } from '../../hooks/useFetch';
import { EmptyState, ErrorAlert, ScoreBar, Spinner } from '../ui';
import { humanizeMetric, scoreTextColor } from './scoreUtils';

const CATEGORY_LABELS: Record<string, string> = {
  typical: 'Typical',
  in_knowledge_base: 'In Knowledge Base',
  edge: 'Edge Cases',
  out_of_knowledge_base: 'Out of Knowledge Base',
  bridge: 'Bridge',
  comparative: 'Comparative',
  community: 'Community',
  uncategorized: 'Uncategorized',
};

interface Props {
  projectId: number;
  experimentId: number;
}

/** Collapsible per-category score breakdown; fetches lazily on first expand. */
export default function CategoryBreakdown({ projectId, experimentId }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-5 py-3 text-left text-sm font-medium text-text-primary transition hover:text-accent"
      >
        <svg
          className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        Breakdown by category
        <span className="text-xs font-normal text-text-muted">— weakest categories first</span>
      </button>

      {expanded && (
        <div className="border-t border-border px-5 py-4">
          <BreakdownContent projectId={projectId} experimentId={experimentId} />
        </div>
      )}
    </div>
  );
}

/** Mounted only while expanded, so the fetch happens lazily. */
function BreakdownContent({ projectId, experimentId }: Props) {
  const { data, loading, error } = useFetch<ExperimentBreakdown>(
    () => fetchExperimentBreakdown(projectId, experimentId),
    [projectId, experimentId],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-xs text-text-muted">
        <Spinner size="sm" /> Computing breakdown…
      </div>
    );
  }
  if (error) return <ErrorAlert message={error} />;
  if (!data || data.categories.length === 0) {
    return (
      <EmptyState
        title="No category breakdown available"
        hint="Run the experiment to completion to see per-category scores."
      />
    );
  }

  return (
    <div className="space-y-3">
      {data.categories.map((cat) => (
        <CategoryRowView key={cat.category} category={cat} />
      ))}
    </div>
  );
}

function CategoryRowView({ category }: { category: CategoryRow }) {
  const metricEntries = Object.entries(category.metrics);

  return (
    <div className="rounded-lg border border-border bg-elevated/50 px-4 py-3">
      {/* Header: name, count, overall */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-text-primary">
          {CATEGORY_LABELS[category.category] ?? humanizeMetric(category.category)}
        </span>
        <span className="text-xs text-text-muted">
          {category.question_count} question{category.question_count !== 1 ? 's' : ''}
        </span>
        <span className="ml-auto flex items-center gap-2 text-xs text-text-secondary">
          Overall <ScoreBar value={category.overall} />
        </span>
      </div>

      {/* Per-metric mini scores */}
      {metricEntries.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {metricEntries.map(([name, avg]) => (
            <span key={name} className="text-xs text-text-muted">
              {humanizeMetric(name)}:{' '}
              <span className={`font-mono font-medium ${scoreTextColor(avg)}`}>
                {avg.toFixed(2)}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Weakest questions */}
      {category.weakest_questions.length > 0 && (
        <div className="mt-2.5 space-y-1 border-t border-border/60 pt-2">
          <p className="text-xs font-medium text-text-muted">Weakest questions</p>
          {category.weakest_questions.map((wq) => (
            <div key={wq.question_id} className="flex items-baseline gap-2 text-xs">
              <span
                className={`shrink-0 font-mono font-semibold ${
                  wq.mean_score !== null ? scoreTextColor(wq.mean_score) : 'text-text-muted'
                }`}
              >
                {wq.mean_score !== null ? wq.mean_score.toFixed(2) : '—'}
              </span>
              <span className="truncate text-text-secondary" title={wq.question}>
                {wq.question}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

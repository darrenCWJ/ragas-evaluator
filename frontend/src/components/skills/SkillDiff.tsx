import { useEffect, useState } from 'react';
import { fetchSkill } from '../../api';
import type { Skill } from '../../api';
import { collapseUnchanged, diffLines } from '../../lib/diff';
import { ErrorAlert, Spinner } from '../ui';

interface SkillDiffProps {
  projectId: number;
  /** Newer version (the row the user clicked). */
  current: Skill;
  /** Older version of the same skill to compare against. */
  previous: Skill;
  onClose: () => void;
}

/** Inline line diff between two versions of the same skill. */
export default function SkillDiff({ projectId, current, previous, onClose }: SkillDiffProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ReturnType<typeof collapseUnchanged> | null>(null);
  const [stats, setStats] = useState<{ added: number; removed: number }>({
    added: 0,
    removed: 0,
  });

  // Parent keys this component by version pair, so initial state covers each
  // mount — no synchronous setState in the effect body.
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchSkill(projectId, previous.id), fetchSkill(projectId, current.id)])
      .then(([oldSkill, newSkill]) => {
        if (cancelled) return;
        const diff = diffLines(oldSkill.content ?? '', newSkill.content ?? '');
        if (diff === null) {
          setError('Skill is too large to diff in the browser');
          return;
        }
        setStats({
          added: diff.filter((l) => l.op === 'add').length,
          removed: diff.filter((l) => l.op === 'del').length,
        });
        setRows(collapseUnchanged(diff));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load versions');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, current.id, previous.id]);

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border bg-deep p-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{current.name}</span>{' '}
          <span className="font-mono">
            v{previous.version} → v{current.version}
          </span>
          {!loading && !error && (
            <span className="ml-2">
              <span className="text-score-high">+{stats.added}</span>{' '}
              <span className="text-score-low">−{stats.removed}</span>
            </span>
          )}
        </p>
        <button onClick={onClose} className="text-xs text-text-muted hover:text-text-primary">
          Close
        </button>
      </div>
      <ErrorAlert message={error} />
      {loading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-text-muted">
          <Spinner size="sm" /> Loading versions...
        </div>
      ) : (
        rows && (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-2xs leading-relaxed">
            {rows.map((row, i) =>
              row.op === 'skip' ? (
                <div key={i} className="select-none py-0.5 text-center text-text-muted">
                  ⋯ {row.count} unchanged line{row.count !== 1 ? 's' : ''} ⋯
                </div>
              ) : (
                <div
                  key={i}
                  className={
                    row.op === 'add'
                      ? 'bg-score-high/10 text-score-high'
                      : row.op === 'del'
                        ? 'bg-score-low/10 text-score-low line-through decoration-score-low/40'
                        : 'text-text-secondary'
                  }
                >
                  {row.op === 'add' ? '+ ' : row.op === 'del' ? '− ' : '  '}
                  {row.text || ' '}
                </div>
              ),
            )}
          </pre>
        )
      )}
    </div>
  );
}

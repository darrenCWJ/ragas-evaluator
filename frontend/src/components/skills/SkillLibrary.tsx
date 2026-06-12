import { useState } from 'react';
import { deleteSkill } from '../../api';
import type { Skill } from '../../api';
import { useConfirm } from '../../hooks/useConfirm';
import { ConfirmButtons, EmptyState, ErrorAlert, Spinner } from '../ui';
import SkillDiff from './SkillDiff';
import SkillUpload from './SkillUpload';

interface SkillLibraryProps {
  projectId: number;
  skills: Skill[];
  loading: boolean;
  loadError: string | null;
  onChanged: () => void;
}

/** Skill library — uploaded skills with version/directive counts, plus the upload form. */
export default function SkillLibrary({
  projectId,
  skills,
  loading,
  loadError,
  onChanged,
}: SkillLibraryProps) {
  const confirm = useConfirm<number>();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [diffForId, setDiffForId] = useState<number | null>(null);

  /** Highest older version of the same skill name, if any. */
  const previousVersionOf = (skill: Skill): Skill | undefined =>
    skills
      .filter((s) => s.name === skill.name && s.version < skill.version)
      .sort((a, b) => b.version - a.version)[0];

  const handleDelete = async (skillId: number) => {
    setDeletingId(skillId);
    setActionError(null);
    try {
      await deleteSkill(projectId, skillId);
      confirm.clear();
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete skill');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <ErrorAlert message={loadError ?? actionError} onDismiss={() => setActionError(null)} />

      {loading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-text-muted">
          <Spinner size="sm" /> Loading skills...
        </div>
      ) : skills.length === 0 ? (
        <EmptyState
          title="No skills uploaded yet"
          hint="Upload a SKILL.md-style instruction file below to start comparing models."
        />
      ) : (
        <ul className="space-y-2">
          {skills.map((skill) => (
            <li key={skill.id} className="rounded-xl border border-border bg-card px-4 py-3">
              <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-text-primary">
                  {skill.name}
                  <span className="ml-2 rounded bg-elevated px-1.5 py-0.5 text-2xs font-mono text-text-muted">
                    v{skill.version}
                  </span>
                  <span className="ml-2 text-xs text-text-muted">
                    {skill.directive_count} directive{skill.directive_count !== 1 ? 's' : ''}
                  </span>
                  {(skill.stage_count ?? 0) > 0 && (
                    <span
                      className="ml-2 rounded-full bg-accent/10 px-1.5 py-0.5 text-2xs text-accent"
                      title={(skill.stages ?? [])
                        .map((s) => s.title + (s.files.length ? ` (${s.files.join(', ')})` : ''))
                        .join('\n')}
                    >
                      {skill.stage_count} stages
                    </span>
                  )}
                  {(skill.files?.length ?? 0) > 0 && (
                    <span className="ml-2 text-2xs text-text-muted">
                      {skill.files?.length} files
                    </span>
                  )}
                </p>
                {skill.summary && (
                  <p className="mt-1 truncate text-xs text-text-secondary" title={skill.summary}>
                    {skill.summary}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {previousVersionOf(skill) && (
                  <button
                    onClick={() => setDiffForId(diffForId === skill.id ? null : skill.id)}
                    className="rounded-lg px-2 py-1 text-xs text-text-muted transition hover:text-accent"
                    title={`Compare against v${previousVersionOf(skill)?.version}`}
                  >
                    {diffForId === skill.id ? 'Hide diff' : 'Diff'}
                  </button>
                )}
                {confirm.isConfirming(skill.id) ? (
                  deletingId === skill.id ? (
                    <Spinner size="sm" />
                  ) : (
                    <ConfirmButtons
                      onConfirm={() => handleDelete(skill.id)}
                      onCancel={confirm.clear}
                    />
                  )
                ) : (
                  <button
                    onClick={() => confirm.requestConfirm(skill.id)}
                    className="rounded-lg px-2 py-1 text-xs text-text-muted transition hover:text-score-low"
                  >
                    Delete
                  </button>
                )}
              </div>
              </div>
              {diffForId === skill.id && previousVersionOf(skill) && (
                <SkillDiff
                  key={`${skill.id}-${previousVersionOf(skill)!.id}`}
                  projectId={projectId}
                  current={skill}
                  previous={previousVersionOf(skill)!}
                  onClose={() => setDiffForId(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <SkillUpload projectId={projectId} onUploaded={onChanged} />
    </div>
  );
}

import { useState } from 'react';
import {
  applyPreferredModel,
  cancelSkillTrial,
  fetchProject,
  fetchSkillTrial,
  fetchSkillTrialProgress,
} from '../../api';
import type { SkillTrial, SkillTrialProgress, SkillTrialStatus } from '../../api';
import { useProject } from '../../contexts/ProjectContext';
import { useFetch } from '../../hooks/useFetch';
import { usePolling } from '../../hooks/usePolling';
import { Button, Card, EmptyState, ErrorAlert, Spinner } from '../ui';
import TrialDrilldown from './TrialDrilldown';
import TrialMatrix, { type MatrixCellRef } from './TrialMatrix';

const PROGRESS_POLL_MS = 2000;

interface TrialListProps {
  projectId: number;
  trials: SkillTrial[];
  loading: boolean;
  loadError: string | null;
  onChanged: () => void;
}

const STATUS_CLASSES: Record<SkillTrialStatus, string> = {
  pending: 'bg-elevated text-text-muted',
  running: 'bg-accent/15 text-accent',
  completed: 'bg-score-high/15 text-score-high',
  failed: 'bg-score-low/15 text-score-low',
  cancelled: 'bg-score-mid/15 text-score-mid',
};

function StatusBadge({ status }: { status: SkillTrialStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
        STATUS_CLASSES[status] ?? STATUS_CLASSES.pending
      }`}
    >
      {status}
    </span>
  );
}

/** Expanded trial body: matrix + apply-model + cell drilldown. */
function TrialDetail({ projectId, trial }: { projectId: number; trial: SkillTrial }) {
  const { project, setProject } = useProject();
  const [selectedCell, setSelectedCell] = useState<MatrixCellRef | null>(null);
  const [applyingModel, setApplyingModel] = useState<string | null>(null);
  const [appliedNote, setAppliedNote] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const {
    data: detail,
    loading,
    error,
  } = useFetch(() => fetchSkillTrial(projectId, trial.id), [projectId, trial.id, trial.status]);

  const handleApply = async (model: string) => {
    setApplyingModel(model);
    setApplyError(null);
    setAppliedNote(null);
    try {
      const res = await applyPreferredModel(projectId, model);
      setAppliedNote(`Preferred model set to ${res.preferred_model}.`);
      try {
        setProject(await fetchProject(projectId));
      } catch {
        // Non-critical: context refresh failed; the backend change still applied.
      }
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : 'Failed to apply model');
    } finally {
      setApplyingModel(null);
    }
  };

  if (loading && !detail) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-text-muted">
        <Spinner size="sm" /> Loading trial detail...
      </div>
    );
  }
  if (error) return <ErrorAlert message={error} />;
  if (!detail) return null;

  return (
    <div className="space-y-3 border-t border-border/50 pt-3">
      {detail.skill && (
        <p className="text-xs text-text-muted">
          Skill: <span className="text-text-secondary">{detail.skill.name}</span> v
          {detail.skill.version} &middot; {detail.skill.directive_count} directives
        </p>
      )}
      <ErrorAlert message={applyError} onDismiss={() => setApplyError(null)} />
      {appliedNote && (
        <Card variant="info" padding="sm" className="flex items-center justify-between text-xs">
          <span>{appliedNote}</span>
          <button onClick={() => setAppliedNote(null)} className="underline hover:no-underline">
            Dismiss
          </button>
        </Card>
      )}
      <TrialMatrix
        matrix={detail.matrix}
        includeBaseline={detail.include_baseline}
        preferredModel={project?.preferred_model ?? null}
        applyingModel={applyingModel}
        onApply={handleApply}
        selectedCell={selectedCell}
        onCellClick={(cell) =>
          setSelectedCell((prev) =>
            prev?.model === cell.model && prev?.variant === cell.variant ? null : cell,
          )
        }
      />
      {selectedCell && (
        <TrialDrilldown
          projectId={projectId}
          trialId={trial.id}
          model={selectedCell.model}
          variant={selectedCell.variant}
        />
      )}
    </div>
  );
}

function TrialRow({
  projectId,
  trial,
  onChanged,
}: {
  projectId: number;
  trial: SkillTrial;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [progress, setProgress] = useState<SkillTrialProgress | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const isActive = trial.status === 'running' || trial.status === 'pending';

  const { error: pollError } = usePolling(
    async () => {
      const p = await fetchSkillTrialProgress(projectId, trial.id);
      setProgress(p);
      if (p.phase === 'running' || p.phase === 'pending') return 'continue';
      onChanged();
      return 'stop';
    },
    PROGRESS_POLL_MS,
    isActive,
  );

  const handleCancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelSkillTrial(projectId, trial.id);
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : 'Failed to cancel trial');
    } finally {
      setCancelling(false);
    }
  };

  const pct =
    progress?.total && progress.total > 0
      ? Math.min(100, Math.round(((progress.current ?? 0) / progress.total) * 100))
      : null;

  return (
    <Card padding="md" className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={expanded}
        >
          <span className={`text-text-muted transition-transform ${expanded ? 'rotate-90' : ''}`}>
            &#9656;
          </span>
          <span className="truncate text-sm font-medium text-text-primary">{trial.name}</span>
          <span className="shrink-0 text-2xs text-text-muted">
            {trial.models.length} model{trial.models.length !== 1 ? 's' : ''} &middot;{' '}
            {new Date(trial.created_at).toLocaleString()}
          </span>
        </button>
        <StatusBadge status={trial.status} />
        {isActive && (
          <Button
            variant="danger"
            className="px-3 py-1 text-xs"
            loading={cancelling}
            onClick={handleCancel}
          >
            Cancel
          </Button>
        )}
      </div>

      {isActive && (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-input">
            <div
              className={`h-full rounded-full bg-accent transition-all ${pct === null ? 'w-1/4 animate-pulse' : ''}`}
              style={pct !== null ? { width: `${pct}%` } : undefined}
            />
          </div>
          <p className="text-2xs text-text-muted">
            {progress?.total
              ? `${progress.current ?? 0}/${progress.total} cells`
              : 'Starting trial...'}
          </p>
        </div>
      )}

      <ErrorAlert message={cancelError ?? pollError} onDismiss={() => setCancelError(null)} />
      {trial.status === 'failed' && trial.error_message && (
        <ErrorAlert message={trial.error_message} />
      )}

      {expanded && <TrialDetail projectId={projectId} trial={trial} />}
    </Card>
  );
}

/** Trial history list with live progress for running trials and expandable detail. */
export default function TrialList({
  projectId,
  trials,
  loading,
  loadError,
  onChanged,
}: TrialListProps) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-text-muted">
        <Spinner size="sm" /> Loading trials...
      </div>
    );
  }
  if (loadError) return <ErrorAlert message={loadError} />;
  if (trials.length === 0) {
    return (
      <EmptyState
        title="No trials yet"
        hint="Start a trial above to compare how models follow your skill."
      />
    );
  }

  return (
    <div className="space-y-3">
      {trials.map((trial) => (
        <TrialRow key={trial.id} projectId={projectId} trial={trial} onChanged={onChanged} />
      ))}
    </div>
  );
}

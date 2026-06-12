import type { SkillTrialCell, SkillTrialMatrix, SkillTrialVariant } from '../../api';
import { Button, ScoreBar } from '../ui';

export interface MatrixCellRef {
  model: string;
  variant: SkillTrialVariant;
}

interface TrialMatrixProps {
  matrix: SkillTrialMatrix;
  includeBaseline: boolean;
  preferredModel: string | null;
  applyingModel: string | null;
  onApply: (model: string) => void;
  selectedCell: MatrixCellRef | null;
  onCellClick: (cell: MatrixCellRef) => void;
}

function cellByVariant(
  cells: SkillTrialCell[],
  model: string,
): Partial<Record<SkillTrialVariant, SkillTrialCell>> {
  const out: Partial<Record<SkillTrialVariant, SkillTrialCell>> = {};
  for (const c of cells) {
    if (c.model === model) out[c.variant] = c;
  }
  return out;
}

function CellButton({
  cell,
  isSelected,
  onClick,
}: {
  cell: SkillTrialCell | undefined;
  isSelected: boolean;
  onClick: () => void;
}) {
  if (!cell) {
    return <span className="text-xs text-text-muted">&mdash;</span>;
  }
  return (
    <button
      onClick={onClick}
      title="Click to drill into per-question results"
      className={`w-full rounded-lg border px-2.5 py-2 text-left transition ${
        isSelected
          ? 'border-accent bg-accent/5'
          : 'border-transparent hover:border-border-focus hover:bg-elevated'
      }`}
    >
      <ScoreBar value={cell.adherence} />
      <div className="mt-1.5 space-y-0.5 text-2xs text-text-muted">
        <div>fmt {cell.format_compliance != null ? cell.format_compliance.toFixed(2) : '—'}</div>
        <div>
          {cell.avg_latency_ms != null ? `${(cell.avg_latency_ms / 1000).toFixed(1)}s avg` : '—'}
          {' · '}
          {cell.tokens_in + cell.tokens_out} tok
        </div>
        <div className={cell.errors > 0 ? 'text-score-low' : ''}>
          {cell.count} runs{cell.errors > 0 ? ` · ${cell.errors} errors` : ''}
        </div>
      </div>
    </button>
  );
}

/** Model × (skill / baseline / lift) adherence matrix with per-row model apply. */
export default function TrialMatrix({
  matrix,
  includeBaseline,
  preferredModel,
  applyingModel,
  onApply,
  selectedCell,
  onCellClick,
}: TrialMatrixProps) {
  const models = [...new Set(matrix.cells.map((c) => c.model))];

  if (models.length === 0) {
    return <p className="py-3 text-sm text-text-muted">No matrix data yet.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-text-muted">
            <th className="px-3 py-2 font-medium">Model</th>
            <th className="px-3 py-2 font-medium">Skill</th>
            {includeBaseline && (
              <>
                <th className="px-3 py-2 font-medium">Baseline</th>
                <th className="px-3 py-2 font-medium">Lift</th>
              </>
            )}
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const byVariant = cellByVariant(matrix.cells, model);
            const lift = matrix.lift[model];
            const isPreferred = preferredModel === model;
            return (
              <tr key={model} className="border-b border-border/50 align-top last:border-0">
                <td className="px-3 py-3">
                  <span className="font-mono text-xs text-text-primary">{model}</span>
                  {isPreferred && (
                    <span className="ml-2 rounded-md bg-score-high/15 px-1.5 py-0.5 text-2xs font-medium text-score-high">
                      project default
                    </span>
                  )}
                </td>
                <td className="px-1 py-2">
                  <CellButton
                    cell={byVariant.skill}
                    isSelected={selectedCell?.model === model && selectedCell?.variant === 'skill'}
                    onClick={() => onCellClick({ model, variant: 'skill' })}
                  />
                </td>
                {includeBaseline && (
                  <>
                    <td className="px-1 py-2">
                      <CellButton
                        cell={byVariant.baseline}
                        isSelected={
                          selectedCell?.model === model && selectedCell?.variant === 'baseline'
                        }
                        onClick={() => onCellClick({ model, variant: 'baseline' })}
                      />
                    </td>
                    <td className="px-3 py-3">
                      {lift != null ? (
                        <span
                          className={`text-sm font-semibold tabular-nums ${
                            lift > 0
                              ? 'text-score-high'
                              : lift < 0
                                ? 'text-score-low'
                                : 'text-text-muted'
                          }`}
                        >
                          {lift > 0 ? '+' : ''}
                          {lift.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-xs text-text-muted">&mdash;</span>
                      )}
                    </td>
                  </>
                )}
                <td className="px-3 py-2 text-right">
                  <Button
                    variant="secondary"
                    className="px-3 py-1 text-xs"
                    loading={applyingModel === model}
                    disabled={applyingModel !== null || isPreferred}
                    onClick={() => onApply(model)}
                  >
                    {isPreferred ? 'Current default' : 'Use this model'}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

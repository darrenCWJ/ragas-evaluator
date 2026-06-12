import { useState } from 'react';
import { applyJudgeCalibration, fetchJudgeCalibration } from '../../api';
import { Button, ErrorAlert } from '../ui';
import { useFetch } from '../../hooks/useFetch';

interface Props {
  projectId: number;
}

/** Ranks judge models by agreement with human annotations; applies the best
 *  ones as the project's default judge panel. */
export default function JudgeCalibrationPanel({ projectId }: Props) {
  const report = useFetch(() => fetchJudgeCalibration(projectId), [projectId]);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<string[] | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  async function handleApply() {
    setApplying(true);
    setApplyError(null);
    try {
      const result = await applyJudgeCalibration(projectId);
      setApplied(result.judge_model_assignments);
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : 'Apply failed');
    } finally {
      setApplying(false);
    }
  }

  const data = report.data;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Judge Calibration</h3>
          <p className="text-xs text-text-muted">
            Which judge model agrees with your human annotations most? Annotate judged results
            (below) to build up calibration pairs.
          </p>
        </div>
        {data?.recommended_assignments && (
          <Button onClick={handleApply} loading={applying}>
            Apply Recommendation
          </Button>
        )}
      </div>

      {report.loading ? (
        <p className="py-2 text-xs text-text-muted">Loading calibration…</p>
      ) : report.error ? (
        <ErrorAlert message={report.error} />
      ) : !data || data.models.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-3 text-xs text-text-muted">
          No calibration data yet. Run experiments with the multi-LLM judge, then annotate the 20%
          human sample — each judge model needs {data?.min_pairs_required ?? 5}+ rated evaluations.
        </p>
      ) : (
        <>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-2xs uppercase tracking-wider text-text-muted">
                <th className="py-1 pr-3">Judge Model</th>
                <th className="py-1 pr-3">Pairs</th>
                <th className="py-1 pr-3">Human Agreement</th>
                <th className="py-1 pr-3">Mean Abs Error</th>
                <th className="py-1">Calibrated</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((model) => (
                <tr key={model.model} className="border-t border-border/50">
                  <td className="py-1.5 pr-3 font-mono text-text-primary">{model.model}</td>
                  <td className="py-1.5 pr-3">{model.pairs}</td>
                  <td className="py-1.5 pr-3">{(model.agreement_rate * 100).toFixed(1)}%</td>
                  <td className="py-1.5 pr-3">{model.mean_abs_error}</td>
                  <td className="py-1.5">
                    {model.calibrated ? (
                      <span className="text-score-high">yes</span>
                    ) : (
                      <span className="text-text-muted">
                        needs {data.min_pairs_required - model.pairs} more
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.recommended_assignments ? (
            <p className="mt-2 text-xs text-text-secondary">
              Recommended panel:{' '}
              <span className="font-mono">{data.recommended_assignments.join(', ')}</span>
            </p>
          ) : (
            <p className="mt-2 text-xs text-text-muted">
              No recommendation yet — models need {data.min_pairs_required}+ pairs and ≥50%
              agreement.
            </p>
          )}
        </>
      )}

      {applied && (
        <p className="mt-2 rounded-lg bg-score-high/10 px-4 py-2 text-xs text-score-high">
          Project default judges set to: {applied.join(', ')}
        </p>
      )}
      <ErrorAlert message={applyError} onDismiss={() => setApplyError(null)} />
    </div>
  );
}

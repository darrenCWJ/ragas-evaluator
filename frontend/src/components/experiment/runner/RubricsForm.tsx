import type { Dispatch, SetStateAction } from 'react';

export const DEFAULT_RUBRICS: Record<string, string> = {
  score1_description: 'The response is completely incorrect or irrelevant.',
  score2_description: 'The response is partially correct but has significant errors.',
  score3_description: 'The response is mostly correct but could be improved.',
  score4_description: 'The response is correct and well-structured.',
  score5_description: 'The response is excellent, accurate, and comprehensive.',
};

interface RubricsFormProps {
  rubrics: Record<string, string>;
  setRubrics: Dispatch<SetStateAction<Record<string, string>>>;
}

/** Rubric criteria editor — shown when rubrics_score is selected. */
export default function RubricsForm({ rubrics, setRubrics }: RubricsFormProps) {
  const updateRubric = (key: string, value: string) => {
    setRubrics((prev) => ({ ...prev, [key]: value }));
  };

  const resetRubrics = () => {
    setRubrics({ ...DEFAULT_RUBRICS });
  };

  return (
    <div className="rounded-lg border border-accent/20 bg-accent/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <label className="text-xs font-medium text-accent">Rubric Criteria (1–5 scale)</label>
        <button
          type="button"
          onClick={resetRubrics}
          className="text-xs text-text-muted transition hover:text-accent"
        >
          Reset to defaults
        </button>
      </div>
      <div className="space-y-2">
        {([1, 2, 3, 4, 5] as const).map((n) => {
          const key = `score${n}_description`;
          return (
            <div key={key} className="flex items-start gap-2">
              <span className="mt-1.5 w-5 shrink-0 text-center text-xs font-bold text-text-muted">
                {n}
              </span>
              <input
                type="text"
                value={rubrics[key] ?? ''}
                onChange={(e) => updateRubric(key, e.target.value)}
                className="flex-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                placeholder={`Describe what a score of ${n} means...`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

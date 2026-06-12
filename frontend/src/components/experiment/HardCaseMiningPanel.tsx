import { useState } from 'react';
import { mineHardCases } from '../../api';
import type { HardCaseMineResult } from '../../api';
import { Button, ErrorAlert, FormField } from '../ui';

interface Props {
  projectId: number;
  experimentId: number;
}

/** Generate harder variants of the experiment's worst-scoring questions. */
export default function HardCaseMiningPanel({ projectId, experimentId }: Props) {
  const [threshold, setThreshold] = useState(0.5);
  const [variants, setVariants] = useState(2);
  const [mining, setMining] = useState(false);
  const [result, setResult] = useState<HardCaseMineResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleMine() {
    setMining(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await mineHardCases(projectId, experimentId, {
          threshold,
          variantsPerQuestion: variants,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Mining failed');
    } finally {
      setMining(false);
    }
  }

  return (
    <div>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-text-primary">Hard-Case Mining</h3>
        <p className="text-xs text-text-muted">
          Take this experiment's worst-scoring questions and generate harder variants of them as a
          new test set (reference answers and provenance are inherited).
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <FormField
          label={`Score threshold (${threshold.toFixed(2)})`}
          hint="Questions with a mean metric score below this are mined"
        >
          <input
            type="range"
            min="0.1"
            max="0.9"
            step="0.05"
            value={threshold}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            className="mt-2 h-1.5 w-44 cursor-pointer appearance-none rounded-full bg-border accent-accent"
          />
        </FormField>
        <FormField label="Variants per question">
          <input
            type="number"
            min={1}
            max={5}
            value={variants}
            onChange={(e) => setVariants(parseInt(e.target.value) || 2)}
            className="w-24 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
          />
        </FormField>
        <Button onClick={handleMine} loading={mining}>
          Mine Hard Cases
        </Button>
      </div>

      {result && (
        <p className="mt-3 rounded-lg bg-score-high/10 px-4 py-2 text-xs text-score-high">
          Created test set #{result.test_set_id}: {result.variants_created} variants from{' '}
          {result.hard_cases} hard case{result.hard_cases !== 1 ? 's' : ''}
          {result.failures > 0 ? ` (${result.failures} generation failures)` : ''}. Find it on the
          Test page.
        </p>
      )}
      <div className="mt-2">
        <ErrorAlert message={error} onDismiss={() => setError(null)} />
      </div>
    </div>
  );
}

import { useRef, useState } from 'react';
import { importLogs } from '../../api';
import type { LogImportResult } from '../../api';
import { Button, ErrorAlert, FormField, TextInput } from '../ui';

interface Props {
  projectId: number;
  onTestSetCreated: () => void;
}

/** Import real user query logs as a reference-free test set. */
export default function LogImportPanel({ projectId, onTestSetCreated }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [questionColumn, setQuestionColumn] = useState('');
  const [name, setName] = useState('');
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<LogImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleImport() {
    if (!file) return;
    setImporting(true);
    setError(null);
    setResult(null);
    try {
      const imported = await importLogs(projectId, file, {
        questionColumn: questionColumn.trim() || undefined,
        name: name.trim() || undefined,
      });
      setResult(imported);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onTestSetCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImporting(false);
    }
  }

  return (
    <div>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-text-primary">Import User Logs</h3>
        <p className="text-xs text-text-muted">
          Turn real user queries (.txt one-per-line, .csv, or .jsonl exports) into a reference-free
          test set. Trivial and duplicate queries are dropped automatically — score these sets with
          reference-free metrics like faithfulness and answer relevancy.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField label="Log file">
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.csv,.tsv,.json,.jsonl,.ndjson"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full text-xs text-text-secondary file:mr-3 file:rounded-lg file:border-0 file:bg-accent/15 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-accent hover:file:bg-accent/25"
          />
        </FormField>
        <FormField label="Query column (optional)" hint="Auto-detected for csv/json">
          <TextInput
            value={questionColumn}
            onChange={(e) => setQuestionColumn(e.target.value)}
            placeholder="e.g. user_message"
          />
        </FormField>
        <FormField label="Test set name (optional)">
          <TextInput
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. prod queries June"
          />
        </FormField>
      </div>

      <div className="mt-3 flex justify-end">
        <Button onClick={handleImport} loading={importing} disabled={!file}>
          Import Logs
        </Button>
      </div>

      {result && (
        <p className="mt-3 rounded-lg bg-score-high/10 px-4 py-2 text-xs text-score-high">
          Imported {result.imported} queries into “{result.name}” (skipped {result.skipped.trivial}{' '}
          trivial, {result.skipped.duplicate} duplicate).
        </p>
      )}
      <div className="mt-2">
        <ErrorAlert message={error} onDismiss={() => setError(null)} />
      </div>
    </div>
  );
}

import { useState, useRef } from "react";
import {
  previewTestSetUpload,
  confirmTestSetUpload,
  ApiError,
} from "../../lib/api";
import type { UploadPreviewResult } from "../../lib/api";

interface Props {
  projectId: number;
  onTestSetCreated: () => void;
}

export default function TestSetUpload({ projectId, onTestSetCreated }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<UploadPreviewResult | null>(null);
  const [questionCol, setQuestionCol] = useState("");
  const [answerCol, setAnswerCol] = useState("");
  const [contextsCol, setContextsCol] = useState("");
  const [refSqlCol, setRefSqlCol] = useState("");
  const [schemaCtxCol, setSchemaCtxCol] = useState("");
  const [refDataCol, setRefDataCol] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleFileSelect = async (f: File) => {
    setFile(f);
    setPreview(null);
    setQuestionCol("");
    setAnswerCol("");
    setContextsCol("");
    setRefSqlCol("");
    setSchemaCtxCol("");
    setRefDataCol("");
    setError(null);
    setSuccess(null);
    setLoading(true);

    try {
      const result = await previewTestSetUpload(projectId, f);
      setPreview(result);
      // Auto-select columns if obvious names exist
      const qNames = new Set(["question", "query", "user_input", "input"]);
      const aNames = new Set(["reference_answer", "answer", "expected_answer", "reference", "ground_truth", "output"]);
      const cNames = new Set(["reference_contexts", "contexts", "context", "sources"]);
      const sqlNames = new Set(["reference_sql", "ref_sql", "expected_sql", "sql"]);
      const schemaNames = new Set(["schema_contexts", "schema", "ddl"]);
      const dataNames = new Set(["reference_data", "ref_data", "expected_data"]);
      for (const col of result.columns) {
        const lower = col.toLowerCase();
        if (qNames.has(lower)) setQuestionCol(col);
        else if (aNames.has(lower)) setAnswerCol(col);
        else if (cNames.has(lower)) setContextsCol(col);
        else if (sqlNames.has(lower)) setRefSqlCol(col);
        else if (schemaNames.has(lower)) setSchemaCtxCol(col);
        else if (dataNames.has(lower)) setRefDataCol(col);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError((err as Error).message || "Failed to preview file");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!file || !questionCol || !answerCol) return;
    setError(null);
    setSuccess(null);
    setUploading(true);

    try {
      const result = await confirmTestSetUpload(
        projectId,
        file,
        questionCol,
        answerCol,
        {
          contextsColumn: contextsCol || undefined,
          name: name.trim() || undefined,
          referenceSqlColumn: refSqlCol || undefined,
          schemaContextsColumn: schemaCtxCol || undefined,
          referenceDataColumn: refDataCol || undefined,
        },
      );
      setSuccess(
        `Created test set "${result.name}" with ${result.question_count} questions.`,
      );
      // Reset
      setFile(null);
      setPreview(null);
      setQuestionCol("");
      setAnswerCol("");
      setContextsCol("");
      setRefSqlCol("");
      setSchemaCtxCol("");
      setRefDataCol("");
      setName("");
      if (fileRef.current) fileRef.current.value = "";
      onTestSetCreated();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError((err as Error).message || "Upload failed");
      }
    } finally {
      setUploading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setQuestionCol("");
    setAnswerCol("");
    setContextsCol("");
    setRefSqlCol("");
    setSchemaCtxCol("");
    setRefDataCol("");
    setName("");
    setError(null);
    setSuccess(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Upload Test Questions
      </h3>

      {/* File picker */}
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          CSV or JSON file
        </label>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.json"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFileSelect(f);
          }}
          disabled={loading || uploading}
          className="w-full text-sm text-text-secondary file:mr-3 file:rounded-lg file:border file:border-border file:bg-elevated file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-text-primary file:transition hover:file:border-accent hover:file:text-accent disabled:opacity-40"
        />
        <p className="mt-1 text-xs text-text-muted">
          Must contain columns for questions and reference answers.
        </p>
      </div>

      {/* Column guide */}
      <details className="group rounded-lg border border-border bg-elevated/30 px-4 py-3">
        <summary className="cursor-pointer text-xs font-medium text-text-secondary hover:text-text-primary transition select-none">
          Column guide
        </summary>
        <div className="mt-3 space-y-3 text-xs text-text-secondary">
          <div>
            <p className="font-semibold text-text-primary">
              Required columns
            </p>
            <dl className="mt-1.5 space-y-1">
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-text-primary">question</dt>
                <dd className="text-text-muted">
                  — The test question or user query.
                  <span className="ml-1 italic">Auto-detected names: question, query, user_input, input</span>
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-text-primary">reference_answer</dt>
                <dd className="text-text-muted">
                  — The expected/ground-truth answer.
                  <span className="ml-1 italic">Auto-detected: reference_answer, answer, expected_answer, reference, ground_truth, output</span>
                </dd>
              </div>
            </dl>
          </div>

          <div>
            <p className="font-semibold text-text-primary">
              Optional columns
            </p>
            <dl className="mt-1.5 space-y-1">
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-text-primary">reference_contexts</dt>
                <dd className="text-text-muted">
                  — Retrieved context passages used to generate the answer. Can be a JSON array of strings or a single text value.
                  <span className="ml-1 italic">Auto-detected: reference_contexts, contexts, context, sources</span>
                </dd>
              </div>
            </dl>
          </div>

          <div>
            <p className="font-semibold text-teal-400">
              Domain-specific columns
              <span className="ml-1 font-normal text-text-muted">(select via dropdowns below)</span>
            </p>
            <dl className="mt-1.5 space-y-1">
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-teal-300">Reference SQL</dt>
                <dd className="text-text-muted">
                  — The ground-truth SQL query, used by the <span className="font-medium text-text-secondary">sql_semantic_equivalence</span> metric to compare against the generated SQL.
                  <span className="ml-1 italic">Auto-detected: reference_sql, ref_sql, expected_sql, sql</span>
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-teal-300">Schema Contexts</dt>
                <dd className="text-text-muted">
                  — Database schema definitions (CREATE TABLE statements) that provide context for SQL comparison. JSON array of strings or a single DDL string.
                  <span className="ml-1 italic">Auto-detected: schema_contexts, schema, ddl</span>
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="shrink-0 font-medium text-teal-300">Reference Data</dt>
                <dd className="text-text-muted">
                  — Expected tabular/structured output (CSV format), used by the <span className="font-medium text-text-secondary">datacompy_score</span> metric to compare against the generated data.
                  <span className="ml-1 italic">Auto-detected: reference_data, ref_data, expected_data</span>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </details>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <svg
            className="h-4 w-4 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          Parsing file...
        </div>
      )}

      {/* Preview table */}
      {preview && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-text-secondary">
              <span className="font-medium text-text-primary">
                {preview.filename}
              </span>{" "}
              — {preview.total_rows} rows, {preview.columns.length} columns
            </p>
            <button
              onClick={handleReset}
              className="text-xs text-text-muted hover:text-text-secondary"
            >
              Clear
            </button>
          </div>

          {/* Table preview */}
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="min-w-full text-left text-xs">
              <thead>
                <tr className="border-b border-border bg-elevated/50">
                  {preview.columns.map((col) => (
                    <th
                      key={col}
                      className="whitespace-nowrap px-3 py-2 font-semibold text-text-secondary"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.preview.map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-border/50 last:border-0"
                  >
                    {preview.columns.map((col) => (
                      <td
                        key={col}
                        className="max-w-[250px] truncate whitespace-nowrap px-3 py-2 text-text-primary"
                        title={row[col] ?? ""}
                      >
                        {row[col] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-text-muted">
            Showing first {preview.preview.length} of {preview.total_rows} rows.
          </p>

          {/* Column mapping */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Question Column{" "}
                <span className="text-red-400">*</span>
              </label>
              <select
                value={questionCol}
                onChange={(e) => setQuestionCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
              >
                <option value="">Select column...</option>
                {preview.columns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Reference Answer Column{" "}
                <span className="text-red-400">*</span>
              </label>
              <select
                value={answerCol}
                onChange={(e) => setAnswerCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
              >
                <option value="">Select column...</option>
                {preview.columns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Reference Contexts Column{" "}
                <span className="font-normal text-text-muted">(optional)</span>
              </label>
              <select
                value={contextsCol}
                onChange={(e) => setContextsCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
              >
                <option value="">None</option>
                {preview.columns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Test Set Name{" "}
                <span className="font-normal text-text-muted">(optional)</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Auto-generated if blank"
                className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          {/* Domain-specific column mapping */}
          <details className="group rounded-lg border border-teal-500/20 px-4 py-3">
            <summary className="cursor-pointer text-xs font-medium text-teal-400 hover:text-teal-300 transition select-none">
              Domain-specific columns
              <span className="ml-1 font-normal text-text-muted">(optional — for SQL / tabular metrics)</span>
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-text-secondary">
                  Reference SQL Column
                </label>
                <select
                  value={refSqlCol}
                  onChange={(e) => setRefSqlCol(e.target.value)}
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-teal-500 focus:outline-none"
                >
                  <option value="">None</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
                <p className="mt-0.5 text-xs text-text-muted">
                  Ground-truth SQL for the sql_semantic_equivalence metric
                </p>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-text-secondary">
                  Schema Contexts Column
                </label>
                <select
                  value={schemaCtxCol}
                  onChange={(e) => setSchemaCtxCol(e.target.value)}
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-teal-500 focus:outline-none"
                >
                  <option value="">None</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
                <p className="mt-0.5 text-xs text-text-muted">
                  DDL / CREATE TABLE statements for SQL comparison context
                </p>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-text-secondary">
                  Reference Data Column
                </label>
                <select
                  value={refDataCol}
                  onChange={(e) => setRefDataCol(e.target.value)}
                  className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-teal-500 focus:outline-none"
                >
                  <option value="">None</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
                <p className="mt-0.5 text-xs text-text-muted">
                  Expected tabular output (CSV) for the datacompy_score metric
                </p>
              </div>
            </div>
          </details>

          {/* Upload button */}
          <button
            onClick={handleConfirm}
            disabled={!questionCol || !answerCol || uploading}
            className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {uploading ? (
              <span className="flex items-center gap-2">
                <svg
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Uploading...
              </span>
            ) : (
              `Upload ${preview.total_rows} Questions`
            )}
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Success */}
      {success && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-300">
          {success}
        </div>
      )}
    </div>
  );
}

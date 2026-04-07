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
      for (const col of result.columns) {
        const lower = col.toLowerCase();
        if (qNames.has(lower)) setQuestionCol(col);
        else if (aNames.has(lower)) setAnswerCol(col);
        else if (cNames.has(lower)) setContextsCol(col);
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
        contextsCol || undefined,
        name.trim() || undefined,
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

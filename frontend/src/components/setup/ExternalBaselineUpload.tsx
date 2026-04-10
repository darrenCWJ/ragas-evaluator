import { useState, useRef, type DragEvent } from "react";
import {
  previewBaselineCsv,
  uploadBaselineCsv,
  type CsvPreviewResult,
} from "../../lib/api";

const MAX_SIZE = 10 * 1024 * 1024; // 10MB

interface Props {
  projectId: number;
  onUploaded: () => void;
}

type Step = "pick" | "map";

export default function ExternalBaselineUpload({ projectId, onUploaded }: Props) {
  const [step, setStep] = useState<Step>("pick");
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported: number; botConfigId: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Preview state
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CsvPreviewResult | null>(null);

  // Column mapping state
  const [questionCol, setQuestionCol] = useState("");
  const [answerCol, setAnswerCol] = useState("");
  const [contextCol, setContextCol] = useState("");
  const [configName, setConfigName] = useState("");

  function validate(f: File): string | null {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (ext !== ".csv") return `Unsupported file type "${ext}". Only .csv files are accepted.`;
    if (f.size > MAX_SIZE) return `File exceeds 10 MB limit (${(f.size / 1024 / 1024).toFixed(1)} MB).`;
    return null;
  }

  function resetAll() {
    setStep("pick");
    setFile(null);
    setPreview(null);
    setQuestionCol("");
    setAnswerCol("");
    setContextCol("");
    setConfigName("");
    setError(null);
    setResult(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleFileSelected(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setResult(null);

    const f = files[0]!;
    const validationError = validate(f);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      const previewData = await previewBaselineCsv(projectId, f);
      setFile(f);
      setPreview(previewData);
      setStep("map");

      // Auto-detect columns by common names
      const headers = previewData.headers.map((h) => h.toLowerCase());
      const qMatch = previewData.headers.find((_, i) =>
        ["question", "query", "q", "input", "prompt"].includes(headers[i]!)
      );
      const aMatch = previewData.headers.find((_, i) =>
        ["answer", "response", "reply", "output", "a"].includes(headers[i]!)
      );
      const cMatch = previewData.headers.find((_, i) =>
        ["context", "contexts", "sources", "source", "references", "reference"].includes(headers[i]!)
      );
      if (qMatch) setQuestionCol(qMatch);
      if (aMatch) setAnswerCol(aMatch);
      if (cMatch) setContextCol(cMatch);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to preview CSV");
    } finally {
      setLoading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleConfirm() {
    if (!file || !questionCol || !answerCol) return;

    setLoading(true);
    setError(null);
    try {
      const res = await uploadBaselineCsv(projectId, file, {
        questionCol,
        answerCol,
        contextCol: contextCol || undefined,
        configName: configName.trim() || undefined,
      });
      setResult({ imported: res.imported, botConfigId: res.bot_config_id });
      setStep("pick");
      setFile(null);
      setPreview(null);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    setDragging(true);
  }
  function onDragLeave(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    handleFileSelected(e.dataTransfer.files);
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-1 text-sm font-semibold text-text-primary">
        Import Bot Responses (CSV)
      </h3>
      <p className="mb-4 text-xs text-text-secondary">
        Upload a CSV with pre-collected bot responses. This creates a virtual bot connector
        for evaluation — no live API needed.
      </p>

      {/* Step 1: File picker */}
      {step === "pick" && (
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
            dragging
              ? "border-accent bg-accent-glow"
              : "border-border hover:border-text-muted"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => handleFileSelected(e.target.files)}
          />

          {loading ? (
            <div className="flex flex-col items-center gap-2">
              <svg className="h-6 w-6 animate-spin text-accent" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm text-text-secondary">Reading CSV headers...</span>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <svg className="h-7 w-7 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <p className="text-sm text-text-secondary">
                Drag & drop CSV here, or{" "}
                <span className="text-accent underline">browse</span>
              </p>
              <p className="text-xs text-text-muted">.csv — max 10 MB, up to 1000 rows</p>
            </div>
          )}
        </div>
      )}

      {/* Step 2: Column mapping */}
      {step === "map" && preview && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-secondary">
              {file?.name} — {preview.headers.length} columns detected
            </span>
            <button
              onClick={resetAll}
              className="text-xs text-text-muted hover:text-text-secondary"
            >
              Change file
            </button>
          </div>

          {/* Config name */}
          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Bot Config Name <span className="text-text-muted">(optional)</span>
            </label>
            <input
              type="text"
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
              placeholder={file?.name ?? "CSV Upload"}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
          </div>

          {/* Column mapping dropdowns */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Question Column <span className="text-score-low">*</span>
              </label>
              <select
                value={questionCol}
                onChange={(e) => setQuestionCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="">Select...</option>
                {preview.headers.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Answer Column <span className="text-score-low">*</span>
              </label>
              <select
                value={answerCol}
                onChange={(e) => setAnswerCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="">Select...</option>
                {preview.headers.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Context Column <span className="text-text-muted">(optional)</span>
              </label>
              <select
                value={contextCol}
                onChange={(e) => setContextCol(e.target.value)}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="">None</option>
                {preview.headers.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Preview table */}
          {preview.rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-surface">
                    {preview.headers.map((h) => {
                      const isSelected = h === questionCol || h === answerCol || h === contextCol;
                      return (
                        <th
                          key={h}
                          className={`whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium ${
                            isSelected ? "text-accent" : "text-text-muted"
                          }`}
                        >
                          {h}
                          {h === questionCol && (
                            <span className="ml-1 rounded bg-accent/15 px-1 py-0.5 text-[10px] text-accent">Q</span>
                          )}
                          {h === answerCol && (
                            <span className="ml-1 rounded bg-accent/15 px-1 py-0.5 text-[10px] text-accent">A</span>
                          )}
                          {h === contextCol && (
                            <span className="ml-1 rounded bg-accent/15 px-1 py-0.5 text-[10px] text-accent">C</span>
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, i) => (
                    <tr key={i} className="border-b border-border/50 last:border-0">
                      {preview.headers.map((h) => {
                        const isSelected = h === questionCol || h === answerCol || h === contextCol;
                        const val = row[h] ?? "";
                        return (
                          <td
                            key={h}
                            className={`max-w-[200px] truncate px-3 py-1.5 ${
                              isSelected ? "text-text-primary" : "text-text-muted"
                            }`}
                            title={val}
                          >
                            {val}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleConfirm}
              disabled={loading || !questionCol || !answerCol}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/80 disabled:opacity-50"
            >
              {loading ? "Importing..." : "Import as Bot Connector"}
            </button>
            <button
              onClick={resetAll}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-3 rounded-lg bg-score-high/10 px-4 py-2 text-sm text-score-high">
          Imported {result.imported} row{result.imported !== 1 ? "s" : ""} as bot connector.
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-lg bg-score-low/10 px-4 py-2 text-sm text-score-low">
          {error}
        </div>
      )}
    </div>
  );
}

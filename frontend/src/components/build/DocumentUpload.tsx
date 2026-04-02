import { useState, useRef, type DragEvent } from "react";
import { uploadDocument } from "../../lib/api";

const ALLOWED_EXTENSIONS = [".pdf", ".txt"];
const MAX_SIZE = 50 * 1024 * 1024; // 50MB

interface Props {
  projectId: number;
  onUploaded: () => void;
}

export default function DocumentUpload({ projectId, onUploaded }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function validate(file: File): string | null {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Unsupported file type "${ext}". Only .pdf and .txt allowed.`;
    }
    if (file.size > MAX_SIZE) {
      return `File exceeds 50 MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB).`;
    }
    return null;
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);

    const file = files[0]!;
    const validationError = validate(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setUploading(true);
    try {
      await uploadDocument(projectId, file);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
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
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div>
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragging
            ? "border-accent bg-accent-glow"
            : "border-border hover:border-text-muted"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />

        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <svg
              className="h-6 w-6 animate-spin text-accent"
              fill="none"
              viewBox="0 0 24 24"
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
            <span className="text-sm text-text-secondary">Uploading...</span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <svg
              className="h-8 w-8 text-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
              />
            </svg>
            <p className="text-sm text-text-secondary">
              Drag & drop a file here, or{" "}
              <span className="text-accent underline">browse</span>
            </p>
            <p className="text-xs text-text-muted">.pdf, .txt — max 50 MB</p>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-score-low/10 px-4 py-2 text-sm text-score-low">
          {error}
        </div>
      )}
    </div>
  );
}

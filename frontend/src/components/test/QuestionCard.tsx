import { useState } from "react";
import type { TestQuestion } from "../../lib/api";
import { annotateQuestion } from "../../lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/15 text-yellow-300",
  approved: "bg-green-500/15 text-green-300",
  rejected: "bg-red-500/15 text-red-300",
  edited: "bg-blue-500/15 text-blue-300",
};

const FLASH_COLORS: Record<string, string> = {
  approved: "border-green-400/60",
  rejected: "border-red-400/60",
  edited: "border-blue-400/60",
};

interface Props {
  question: TestQuestion;
  projectId: number;
  testSetId: number;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  onAnnotated: () => void;
}

export default function QuestionCard({
  question,
  projectId,
  testSetId,
  selected,
  onToggleSelect,
  onAnnotated,
}: Props) {
  const [q, setQ] = useState<TestQuestion>(question);
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editAnswer, setEditAnswer] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  // Sync if parent re-fetches
  if (question.id === q.id && question.status !== q.status) {
    setQ(question);
  }

  const refAnswer = q.reference_answer || "";
  const needsTruncate = refAnswer.length > 150;

  const doAnnotate = async (status: "approved" | "rejected") => {
    setSaving(true);
    setError(null);
    try {
      const updated = await annotateQuestion(projectId, testSetId, q.id, {
        status,
      });
      setQ(updated);
      triggerFlash(status);
      onAnnotated();
    } catch (err) {
      setError((err as Error).message || "Annotation failed");
    } finally {
      setSaving(false);
    }
  };

  const doSaveEdit = async () => {
    if (!editAnswer.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await annotateQuestion(projectId, testSetId, q.id, {
        status: "edited",
        user_edited_answer: editAnswer,
        user_notes: editNotes || undefined,
      });
      setQ(updated);
      setEditing(false);
      triggerFlash("edited");
      onAnnotated();
    } catch (err) {
      setError((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const openEdit = () => {
    setEditAnswer(q.user_edited_answer || q.reference_answer || "");
    setEditNotes(q.user_notes || "");
    setEditing(true);
    setError(null);
  };

  const cancelEdit = () => {
    setEditing(false);
    setError(null);
  };

  const triggerFlash = (status: string) => {
    setFlash(status);
    setTimeout(() => setFlash(null), 800);
  };

  const borderClass = flash
    ? `${FLASH_COLORS[flash] || "border-border"} transition-colors duration-300`
    : "border-border";

  return (
    <div className={`rounded-xl border ${borderClass} bg-card px-4 py-3`}>
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <label className="mt-0.5 flex-shrink-0">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(q.id)}
            className="h-3.5 w-3.5 cursor-pointer appearance-none rounded border border-border bg-input transition checked:border-accent checked:bg-accent"
          />
        </label>

        <div className="min-w-0 flex-1">
          {/* Question text */}
          <p className="text-sm font-medium text-text-primary">{q.question}</p>

          {/* Reference answer */}
          {!editing && (
            <div className="mt-2">
              <p className="text-xs text-text-muted">Reference answer:</p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {expanded || !needsTruncate
                  ? refAnswer
                  : refAnswer.slice(0, 150) + "\u2026"}
              </p>
              {needsTruncate && (
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="mt-1 text-xs text-accent hover:underline"
                >
                  {expanded ? "Show less" : "Show more"}
                </button>
              )}
            </div>
          )}

          {/* Edit mode */}
          {editing && (
            <div className="mt-3 space-y-3">
              {/* Original answer — read-only context */}
              <div>
                <p className="text-xs font-medium text-text-muted">
                  Original reference answer
                </p>
                <p className="mt-1 rounded-lg bg-deep px-3 py-2 text-xs text-text-muted">
                  {refAnswer}
                </p>
              </div>

              {/* Editable answer */}
              <div>
                <label className="text-xs font-medium text-text-secondary">
                  Edited answer
                  <span className="ml-1 text-red-400">*</span>
                </label>
                <textarea
                  value={editAnswer}
                  onChange={(e) => setEditAnswer(e.target.value)}
                  rows={4}
                  className="mt-1 w-full resize-y rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                  placeholder="Enter edited answer..."
                />
              </div>

              {/* Notes */}
              <div>
                <label className="text-xs font-medium text-text-secondary">
                  Notes{" "}
                  <span className="font-normal text-text-muted">(optional)</span>
                </label>
                <textarea
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  rows={2}
                  className="mt-1 w-full resize-y rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                  placeholder="Reason for edit..."
                />
              </div>

              {/* Save / Cancel */}
              <div className="flex gap-2">
                <button
                  onClick={doSaveEdit}
                  disabled={saving || !editAnswer.trim()}
                  className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-500 disabled:opacity-40"
                >
                  {saving ? "Saving\u2026" : "Save"}
                </button>
                <button
                  onClick={cancelEdit}
                  disabled={saving}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-text-muted hover:text-text-secondary disabled:opacity-40"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <p className="mt-2 text-xs text-red-400">{error}</p>
          )}

          {/* Badges + action buttons */}
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs">
            {/* Status badge */}
            <span
              className={`rounded-full px-2 py-0.5 font-medium ${STATUS_COLORS[q.status] || "bg-gray-500/15 text-gray-300"}`}
            >
              {q.status}
            </span>

            {/* Question type badge */}
            {q.question_type && (
              <span className="rounded-full bg-elevated px-2 py-0.5 text-text-muted">
                {q.question_type}
              </span>
            )}

            {/* Persona badge */}
            {q.persona && (
              <span className="text-text-muted italic">{q.persona}</span>
            )}

            {/* Spacer */}
            <span className="flex-1" />

            {/* Annotation actions */}
            {!editing && (
              <div className="flex gap-1.5">
                {q.status !== "approved" && (
                  <button
                    onClick={() => doAnnotate("approved")}
                    disabled={saving}
                    className="rounded-md border border-green-500/30 px-2 py-1 text-green-400 transition hover:bg-green-500/10 disabled:opacity-40"
                  >
                    Approve
                  </button>
                )}
                {q.status !== "rejected" && (
                  <button
                    onClick={() => doAnnotate("rejected")}
                    disabled={saving}
                    className="rounded-md border border-red-500/30 px-2 py-1 text-red-400 transition hover:bg-red-500/10 disabled:opacity-40"
                  >
                    Reject
                  </button>
                )}
                <button
                  onClick={openEdit}
                  disabled={saving}
                  className="rounded-md border border-blue-500/30 px-2 py-1 text-blue-400 transition hover:bg-blue-500/10 disabled:opacity-40"
                >
                  Edit
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

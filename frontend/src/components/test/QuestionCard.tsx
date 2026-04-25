import { useState } from "react";
import type { TestQuestion } from "../../lib/api";
import { annotateQuestion } from "../../lib/api";

const CATEGORY_COLORS: Record<string, string> = {
  typical: "bg-indigo-500/15 text-indigo-300",
  in_knowledge_base: "bg-teal-500/15 text-teal-300",
  edge: "bg-orange-500/15 text-orange-300",
  out_of_knowledge_base: "bg-purple-500/15 text-purple-300",
  bridge: "bg-red-500/15 text-red-300",
  comparative: "bg-cyan-500/15 text-cyan-300",
  community: "bg-lime-500/15 text-lime-300",
};

const CATEGORY_LABELS: Record<string, string> = {
  typical: "Typical",
  in_knowledge_base: "In KB",
  edge: "Edge",
  out_of_knowledge_base: "Out of KB",
  bridge: "Bridge",
  comparative: "Comparative",
  community: "Community",
};

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: "bg-green-500/15 text-green-300",
  medium: "bg-yellow-500/15 text-yellow-300",
  hard: "bg-red-500/15 text-red-300",
};

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
  const [editContexts, setEditContexts] = useState<string[]>([]);
  const [editNotes, setEditNotes] = useState("");
  const [editReferenceSql, setEditReferenceSql] = useState("");
  const [editSchemaContexts, setEditSchemaContexts] = useState<string[]>([]);
  const [editReferenceData, setEditReferenceData] = useState("");
  const [showDomainFields, setShowDomainFields] = useState(false);
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
      // Build metadata from domain-specific fields
      const metadata: Record<string, unknown> = {};
      if (editReferenceSql.trim()) metadata.reference_sql = editReferenceSql.trim();
      const filteredSchemaCtx = editSchemaContexts.filter((s) => s.trim());
      if (filteredSchemaCtx.length > 0) metadata.schema_contexts = filteredSchemaCtx;
      if (editReferenceData.trim()) metadata.reference_data = editReferenceData.trim();

      const updated = await annotateQuestion(projectId, testSetId, q.id, {
        status: "edited",
        user_edited_answer: editAnswer,
        user_edited_contexts: editContexts.some((c) => c.trim()) ? editContexts.filter((c) => c.trim()) : undefined,
        user_notes: editNotes || undefined,
        ...(Object.keys(metadata).length > 0 ? { metadata } : {}),
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
    setEditContexts(q.user_edited_contexts || q.reference_contexts || []);
    setEditNotes(q.user_notes || "");
    const meta = q.metadata || {};
    setEditReferenceSql((meta.reference_sql as string) || "");
    setEditSchemaContexts(
      Array.isArray(meta.schema_contexts)
        ? (meta.schema_contexts as string[])
        : [],
    );
    setEditReferenceData((meta.reference_data as string) || "");
    setShowDomainFields(
      !!(meta.reference_sql || meta.schema_contexts || meta.reference_data),
    );
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

          {/* Reference contexts */}
          {!editing && (q.user_edited_contexts || q.reference_contexts).length > 0 && (
            <details className="mt-2 group">
              <summary className="cursor-pointer text-xs text-text-muted hover:text-text-secondary transition select-none">
                <span className="ml-0.5">
                  Reference contexts ({(q.user_edited_contexts || q.reference_contexts).length})
                  {q.user_edited_contexts && (
                    <span className="ml-1 text-blue-400">(edited)</span>
                  )}
                </span>
              </summary>
              <div className="mt-2 space-y-2">
                {(q.user_edited_contexts || q.reference_contexts).map((ctx, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-deep px-3 py-2 text-xs text-text-secondary leading-relaxed"
                  >
                    <span className="mr-1.5 font-medium text-text-muted">
                      [{i + 1}]
                    </span>
                    {String(ctx)}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Domain-specific metadata (read-only) */}
          {!editing && q.metadata && !!(q.metadata.reference_sql || q.metadata.reference_data || q.metadata.schema_contexts) && (
            <details className="mt-2 group">
              <summary className="cursor-pointer text-xs text-text-muted hover:text-text-secondary transition select-none">
                <span className="ml-0.5">Domain-specific data</span>
              </summary>
              <div className="mt-2 space-y-2">
                {!!q.metadata.reference_sql && (
                  <div className="rounded-lg bg-deep px-3 py-2 text-xs text-text-secondary leading-relaxed">
                    <span className="font-medium text-teal-400">Reference SQL:</span>
                    <pre className="mt-1 whitespace-pre-wrap font-mono">{String(q.metadata.reference_sql)}</pre>
                  </div>
                )}
                {Array.isArray(q.metadata.schema_contexts) && (q.metadata.schema_contexts as string[]).length > 0 && (
                  <div className="rounded-lg bg-deep px-3 py-2 text-xs text-text-secondary leading-relaxed">
                    <span className="font-medium text-teal-400">Schema contexts:</span>
                    {(q.metadata.schema_contexts as string[]).map((sc, i) => (
                      <pre key={i} className="mt-1 whitespace-pre-wrap font-mono">{String(sc)}</pre>
                    ))}
                  </div>
                )}
                {!!q.metadata.reference_data && (
                  <div className="rounded-lg bg-deep px-3 py-2 text-xs text-text-secondary leading-relaxed">
                    <span className="font-medium text-teal-400">Reference data:</span>
                    <pre className="mt-1 whitespace-pre-wrap font-mono">{String(q.metadata.reference_data)}</pre>
                  </div>
                )}
              </div>
            </details>
          )}

          {/* Graph path (bridge / comparative / community questions) */}
          {!editing && !!q.metadata?.graph_path && Array.isArray(q.metadata.graph_path) && (q.metadata.graph_path as string[]).length > 0 && (
            <details className="mt-2 group">
              <summary className="cursor-pointer text-xs text-text-muted hover:text-text-secondary transition select-none">
                <span className="ml-0.5">Graph path</span>
              </summary>
              <div className="mt-1.5 rounded-lg bg-deep px-3 py-2 text-xs text-text-secondary font-mono leading-relaxed">
                {(q.metadata.graph_path as string[]).join(" → ")}
              </div>
            </details>
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

              {/* Reference contexts */}
              <div>
                <label className="text-xs font-medium text-text-secondary">
                  Reference contexts
                </label>
                <div className="mt-1 space-y-2">
                  {editContexts.map((ctx, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="mt-2 text-xs font-medium text-text-muted shrink-0">[{i + 1}]</span>
                      <textarea
                        value={ctx}
                        onChange={(e) => {
                          const updated = [...editContexts];
                          updated[i] = e.target.value;
                          setEditContexts(updated);
                        }}
                        rows={2}
                        className="flex-1 resize-y rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                      />
                      <button
                        onClick={() => setEditContexts(editContexts.filter((_, j) => j !== i))}
                        className="mt-1 shrink-0 text-xs text-red-400 hover:text-red-300"
                        title="Remove context"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                  <button
                    onClick={() => setEditContexts([...editContexts, ""])}
                    className="text-xs text-accent hover:text-accent/80 transition"
                  >
                    + Add context
                  </button>
                </div>
              </div>

              {/* Domain-specific data */}
              <div className="rounded-lg border border-teal-500/20 p-3">
                <button
                  type="button"
                  onClick={() => setShowDomainFields(!showDomainFields)}
                  className="flex w-full items-center gap-1.5 text-xs font-medium text-teal-400 hover:text-teal-300 transition"
                >
                  <svg
                    className={`h-3 w-3 transition-transform ${showDomainFields ? "rotate-90" : ""}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                  Domain-specific data
                  <span className="font-normal text-text-muted">(for SQL / tabular metrics)</span>
                </button>

                {showDomainFields && (
                  <div className="mt-3 space-y-3">
                    {/* Reference SQL */}
                    <div>
                      <label className="text-xs font-medium text-text-secondary">
                        Reference SQL
                      </label>
                      <textarea
                        value={editReferenceSql}
                        onChange={(e) => setEditReferenceSql(e.target.value)}
                        rows={3}
                        className="mt-1 w-full resize-y rounded-lg border border-border bg-input px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                        placeholder="SELECT id, name FROM users WHERE ..."
                      />
                    </div>

                    {/* Schema contexts */}
                    <div>
                      <label className="text-xs font-medium text-text-secondary">
                        Schema contexts
                      </label>
                      <div className="mt-1 space-y-2">
                        {editSchemaContexts.map((sc, i) => (
                          <div key={i} className="flex gap-2">
                            <textarea
                              value={sc}
                              onChange={(e) => {
                                const updated = [...editSchemaContexts];
                                updated[i] = e.target.value;
                                setEditSchemaContexts(updated);
                              }}
                              rows={2}
                              className="flex-1 resize-y rounded-lg border border-border bg-input px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                              placeholder="CREATE TABLE users (id INT, name TEXT, ...);"
                            />
                            <button
                              onClick={() => setEditSchemaContexts(editSchemaContexts.filter((_, j) => j !== i))}
                              className="mt-1 shrink-0 text-xs text-red-400 hover:text-red-300"
                              title="Remove"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        ))}
                        <button
                          onClick={() => setEditSchemaContexts([...editSchemaContexts, ""])}
                          className="text-xs text-teal-400 hover:text-teal-300 transition"
                        >
                          + Add schema context
                        </button>
                      </div>
                    </div>

                    {/* Reference data */}
                    <div>
                      <label className="text-xs font-medium text-text-secondary">
                        Reference data{" "}
                        <span className="font-normal text-text-muted">(CSV/tabular)</span>
                      </label>
                      <textarea
                        value={editReferenceData}
                        onChange={(e) => setEditReferenceData(e.target.value)}
                        rows={4}
                        className="mt-1 w-full resize-y rounded-lg border border-border bg-input px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
                        placeholder={"col1,col2,col3\nval1,val2,val3\n..."}
                      />
                    </div>
                  </div>
                )}
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

            {/* Category badge */}
            {q.category && (
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${CATEGORY_COLORS[q.category] || "bg-gray-500/15 text-gray-300"}`}
              >
                {CATEGORY_LABELS[q.category] || q.category}
              </span>
            )}

            {/* Difficulty badge */}
            {(q.metadata?.difficulty as string | undefined) && (
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${DIFFICULTY_COLORS[q.metadata!.difficulty as string] ?? "bg-gray-500/15 text-gray-300"}`}
              >
                {(q.metadata!.difficulty as string).charAt(0).toUpperCase() + (q.metadata!.difficulty as string).slice(1)}
              </span>
            )}

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

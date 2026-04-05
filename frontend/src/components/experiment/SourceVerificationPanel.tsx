import { useState, useEffect, useCallback } from "react";
import { fetchSourceVerifications } from "../../lib/api";
import type { SourceVerificationGroup } from "../../lib/api";

interface Props {
  projectId: number;
  experimentId: number;
}

interface StatusStyle {
  bg: string;
  text: string;
  label: string;
}

const STATUS_STYLES: Record<string, StatusStyle> = {
  verified: { bg: "bg-score-high/15", text: "text-score-high", label: "Verified" },
  hallucinated: { bg: "bg-score-low/15", text: "text-score-low", label: "Hallucinated" },
  inaccessible: { bg: "bg-yellow-500/15", text: "text-yellow-400", label: "Inaccessible" },
  unverifiable: { bg: "bg-text-muted/15", text: "text-text-muted", label: "Unverifiable" },
};

const FALLBACK_STYLE: StatusStyle = STATUS_STYLES.unverifiable!;

function getStatusStyle(status: string): StatusStyle {
  return STATUS_STYLES[status] ?? FALLBACK_STYLE;
}

export default function SourceVerificationPanel({ projectId, experimentId }: Props) {
  const [groups, setGroups] = useState<SourceVerificationGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSourceVerifications(projectId, experimentId);
      setGroups(data.results ?? []);
    } catch (err) {
      const msg = (err as Error).message || "Failed to load";
      if (msg.includes("409")) {
        setError("Source verification is only available for bot-connector experiments.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [projectId, experimentId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="py-4 text-center text-sm text-text-muted">
        Loading source verifications...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-border/60 bg-elevated/30 px-4 py-3 text-sm text-text-muted">
        {error}
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-6 text-center text-sm text-text-muted">
        No source verifications available for this experiment.
      </div>
    );
  }

  // Summary counts
  const allVerifications = groups.flatMap((g) => g.verifications);
  const total = allVerifications.length;
  const counts = {
    verified: allVerifications.filter((v) => v.status === "verified").length,
    hallucinated: allVerifications.filter((v) => v.status === "hallucinated").length,
    inaccessible: allVerifications.filter((v) => v.status === "inaccessible").length,
    unverifiable: allVerifications.filter((v) => v.status === "unverifiable").length,
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Source Verification
      </h3>

      {/* Summary bar */}
      <div className="grid grid-cols-4 gap-2">
        {(Object.entries(counts) as [string, number][]).map(([status, count]) => {
          const style = getStatusStyle(status);
          return (
            <div key={status} className={`rounded-lg ${style.bg} px-3 py-2 text-center`}>
              <div className={`text-lg font-bold ${style.text}`}>{count}</div>
              <div className="text-xs text-text-muted">{style.label}</div>
              <div className="text-xs text-text-muted">
                {total > 0 ? `${Math.round((count / total) * 100)}%` : "—"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Per-question groups */}
      <div className="space-y-2">
        {groups.map((g) => (
          <details
            key={g.experiment_result_id}
            className="group rounded-lg border border-border bg-elevated/30"
          >
            <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 text-sm">
              <span className="font-medium text-text-primary truncate mr-2">
                {g.question}
              </span>
              <span className="shrink-0 text-xs text-text-muted">
                {g.verifications.length} citation{g.verifications.length !== 1 ? "s" : ""}
              </span>
            </summary>
            <div className="border-t border-border px-4 py-3 space-y-2">
              {g.verifications.map((v) => {
                const vStyle = getStatusStyle(v.status);
                return (
                  <div
                    key={v.id}
                    className="flex items-start gap-3 rounded-lg bg-card/60 px-3 py-2"
                  >
                    <span
                      className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${vStyle.bg} ${vStyle.text}`}
                    >
                      {vStyle.label}
                    </span>
                    <div className="min-w-0 flex-1">
                      {v.title && (
                        <p className="text-sm font-medium text-text-primary truncate">
                          {v.title}
                        </p>
                      )}
                      {v.url && (
                        <p className="text-xs text-accent truncate">{v.url}</p>
                      )}
                      {v.details && (
                        <p className="mt-1 text-xs text-text-muted">{v.details}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

import type { KGGraphNode } from "../../lib/api";

interface KGNodeDetailProps {
  node: KGGraphNode | null;
  onClose: () => void;
}

export default function KGNodeDetail({ node, onClose }: KGNodeDetailProps) {
  if (!node) return null;

  const typeLabel = node.type === "document" ? "Document" : node.type === "chunk" ? "Chunk" : node.type || "Unknown";
  const typeColor = node.type === "document"
    ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
    : "bg-accent/15 text-accent border-accent/30";

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="absolute inset-0 -left-[100vw] bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative ml-auto w-[380px] max-w-[90vw] border-l border-border bg-card/95 backdrop-blur-xl shadow-2xl overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card/90 backdrop-blur-md px-5 py-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className={`shrink-0 rounded-md border px-2 py-0.5 text-2xs font-medium ${typeColor}`}>
              {typeLabel}
            </span>
            <span className="text-micro text-text-muted font-mono truncate">
              {node.id.slice(0, 8)}...
            </span>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-md p-1 text-text-muted transition hover:bg-elevated hover:text-text-primary"
            aria-label="Close detail panel"
          >
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Label / headline */}
          <section>
            <h4 className="text-micro font-medium uppercase tracking-wider text-text-muted mb-2">
              Headline
            </h4>
            <p className="text-sm text-text-primary leading-relaxed">
              {node.label || "No headline available"}
            </p>
          </section>

          {/* Keyphrases */}
          {node.keyphrases.length > 0 && (
            <section>
              <h4 className="text-micro font-medium uppercase tracking-wider text-text-muted mb-2">
                Keyphrases
                <span className="ml-1.5 text-2xs text-text-muted font-normal">
                  ({node.keyphrases.length})
                </span>
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {node.keyphrases.map((kp, i) => (
                  <span
                    key={i}
                    className="inline-block rounded-md border border-border bg-deep/60 px-2 py-0.5 text-2xs text-text-secondary font-mono"
                  >
                    {kp}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Node ID */}
          <section>
            <h4 className="text-micro font-medium uppercase tracking-wider text-text-muted mb-2">
              Node ID
            </h4>
            <code className="block text-2xs text-text-muted font-mono bg-deep/60 rounded-md px-3 py-2 break-all">
              {node.id}
            </code>
          </section>
        </div>
      </div>
    </div>
  );
}

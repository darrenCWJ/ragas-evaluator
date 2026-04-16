interface PipelineStep {
  label: string;
  count: number;
  configured: boolean;
}

interface Props {
  documentCount: number;
  chunkConfigCount: number;
  embeddingConfigCount: number;
  ragConfigCount: number;
}

export default function PipelineStatus({
  documentCount,
  chunkConfigCount,
  embeddingConfigCount,
  ragConfigCount,
}: Props) {
  const steps: PipelineStep[] = [
    {
      label: "Documents",
      count: documentCount,
      configured: documentCount > 0,
    },
    {
      label: "Chunks",
      count: chunkConfigCount,
      configured: chunkConfigCount > 0,
    },
    {
      label: "Embeddings",
      count: embeddingConfigCount,
      configured: embeddingConfigCount > 0,
    },
    {
      label: "RAG",
      count: ragConfigCount,
      configured: ragConfigCount > 0,
    },
  ];

  return (
    <div className="mb-8 flex items-center gap-1">
      {steps.map((step, i) => (
        <div key={step.label} className="flex items-center">
          <div
            className={`flex items-center gap-2 rounded-lg px-3 py-2 ${
              step.configured
                ? "bg-accent/10 text-accent"
                : "bg-card text-text-muted"
            }`}
          >
            {/* Icon */}
            {step.configured ? (
              <svg
                className="h-3.5 w-3.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            ) : (
              <svg
                className="h-3.5 w-3.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <circle cx="12" cy="12" r="9" />
              </svg>
            )}

            <span className="text-xs font-medium">{step.label}</span>
            <span
              className={`font-mono text-2xs ${
                step.configured ? "text-accent/70" : "text-text-muted"
              }`}
            >
              {step.count}
            </span>
          </div>

          {/* Arrow connector */}
          {i < steps.length - 1 && (
            <svg
              className="mx-0.5 h-3 w-3 text-border"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 5l7 7-7 7"
              />
            </svg>
          )}
        </div>
      ))}
    </div>
  );
}

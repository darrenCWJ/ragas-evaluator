export default function AnalyzePage() {
  return (
    <div className="mx-auto max-w-2xl pt-12">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg className="h-5 w-5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Analyze</h1>
          <p className="text-sm text-text-secondary">Review results and iterate on your pipeline.</p>
        </div>
      </div>
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
        <p className="text-sm text-text-muted">Stage content coming in the next phase.</p>
      </div>
    </div>
  );
}

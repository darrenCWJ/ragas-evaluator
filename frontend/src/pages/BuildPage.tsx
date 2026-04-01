export default function BuildPage() {
  return (
    <div className="mx-auto max-w-2xl pt-12">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg className="h-5 w-5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Build</h1>
          <p className="text-sm text-text-secondary">Chunking, embedding, and RAG pipeline configuration.</p>
        </div>
      </div>
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
        <p className="text-sm text-text-muted">Stage content coming in the next phase.</p>
      </div>
    </div>
  );
}

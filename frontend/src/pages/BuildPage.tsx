import { useState, useEffect, useCallback } from "react";
import { useProject } from "../contexts/ProjectContext";
import {
  fetchDocuments,
  fetchChunkConfigs,
  fetchEmbeddingConfigs,
  fetchRagConfigs,
} from "../lib/api";
import type {
  Document as Doc,
  ChunkConfig,
  EmbeddingConfig,
  RagConfig,
} from "../lib/api";
import DocumentUpload from "../components/build/DocumentUpload";
import DocumentList from "../components/build/DocumentList";
import ChunkConfigPanel from "../components/build/ChunkConfigPanel";
import EmbeddingConfigPanel from "../components/build/EmbeddingConfigPanel";
import RagConfigPanel from "../components/build/RagConfigPanel";
import PipelineStatus from "../components/build/PipelineStatus";

export default function BuildPage() {
  const { project } = useProject();
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);

  const [chunkConfigs, setChunkConfigs] = useState<ChunkConfig[]>([]);
  const [embeddingConfigs, setEmbeddingConfigs] = useState<EmbeddingConfig[]>(
    [],
  );
  const [ragConfigs, setRagConfigs] = useState<RagConfig[]>([]);

  const loadDocuments = useCallback(async () => {
    if (!project) return;
    setDocsLoading(true);
    setDocsError(null);
    try {
      const data = await fetchDocuments(project.id);
      setDocuments(data);
    } catch (err) {
      setDocsError(
        err instanceof Error ? err.message : "Failed to load documents",
      );
    } finally {
      setDocsLoading(false);
    }
  }, [project]);

  const loadChunkConfigs = useCallback(async () => {
    if (!project) return;
    try {
      const data = await fetchChunkConfigs(project.id);
      setChunkConfigs(data);
    } catch {
      // silent — ChunkConfigPanel handles its own loading
    }
  }, [project]);

  const loadEmbeddingConfigs = useCallback(async () => {
    if (!project) return;
    try {
      const data = await fetchEmbeddingConfigs(project.id);
      setEmbeddingConfigs(data);
    } catch {
      // silent — EmbeddingConfigPanel handles its own loading
    }
  }, [project]);

  const loadRagConfigs = useCallback(async () => {
    if (!project) return;
    try {
      const data = await fetchRagConfigs(project.id);
      setRagConfigs(data);
    } catch {
      // silent — RagConfigPanel handles its own loading
    }
  }, [project]);

  useEffect(() => {
    loadDocuments();
    loadChunkConfigs();
    loadEmbeddingConfigs();
    loadRagConfigs();
  }, [loadDocuments, loadChunkConfigs, loadEmbeddingConfigs, loadRagConfigs]);

  if (!project) return null;

  return (
    <div className="mx-auto max-w-6xl px-4 pt-8">
      {/* Header */}
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg
            className="h-5 w-5 text-accent"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Build</h1>
          <p className="text-sm text-text-secondary">
            Upload documents, configure chunking, embeddings, and RAG pipelines.
          </p>
        </div>
      </div>

      {/* Pipeline Status */}
      <PipelineStatus
        documentCount={documents.length}
        chunkConfigCount={chunkConfigs.length}
        embeddingConfigCount={embeddingConfigs.length}
        ragConfigCount={ragConfigs.length}
      />

      {/* Row 1: Documents + Chunking */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_0.82fr]">
        {/* Left column — Documents */}
        <div className="space-y-6">
          <div>
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-text-muted">
              Documents
            </h3>
            <p className="mb-4 text-xs text-text-muted">
              Upload PDF or TXT files for your project.
            </p>
            <DocumentUpload
              projectId={project.id}
              onUploaded={loadDocuments}
            />
          </div>

          <DocumentList
            projectId={project.id}
            documents={documents}
            loading={docsLoading}
            error={docsError}
            onRefresh={loadDocuments}
          />
        </div>

        {/* Right column — Chunking */}
        <div>
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-text-muted">
            Chunking Configuration
          </h3>
          <p className="mb-4 text-xs text-text-muted">
            Define how documents are split into chunks for retrieval.
          </p>
          <ChunkConfigPanel
            projectId={project.id}
            documents={documents}
          />
        </div>
      </div>

      {/* Row 2: Embeddings + RAG */}
      <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[1fr_0.82fr]">
        {/* Left column — Embeddings */}
        <div>
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-text-muted">
            Embedding Configuration
          </h3>
          <p className="mb-4 text-xs text-text-muted">
            Configure how chunks are embedded into vector space.
          </p>
          <EmbeddingConfigPanel
            projectId={project.id}
            chunkConfigs={chunkConfigs}
            onConfigsChanged={() => {
              loadEmbeddingConfigs();
              loadRagConfigs();
            }}
          />
        </div>

        {/* Right column — RAG */}
        <div>
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-text-muted">
            RAG Configuration
          </h3>
          <p className="mb-4 text-xs text-text-muted">
            Set up retrieval-augmented generation pipelines.
          </p>
          <RagConfigPanel
            projectId={project.id}
            embeddingConfigs={embeddingConfigs}
            chunkConfigs={chunkConfigs}
            onConfigsChanged={loadRagConfigs}
          />
        </div>
      </div>
    </div>
  );
}

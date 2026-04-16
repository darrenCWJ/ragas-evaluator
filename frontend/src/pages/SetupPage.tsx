import { useState } from "react";
import { useProject } from "../contexts/ProjectContext";
import ProjectSelector from "../components/ProjectSelector";
import ExternalBaselineUpload from "../components/setup/ExternalBaselineUpload";
import BotConnectorConfig from "../components/setup/BotConnectorConfig";
import CustomMetricBuilder from "../components/setup/CustomMetricBuilder";
import CsvUploadsList from "../components/setup/CsvUploadsList";

export default function SetupPage() {
  const { project } = useProject();
  const [refreshKey, setRefreshKey] = useState(0);

  if (!project) {
    return (
      <div className="mx-auto max-w-lg pt-16">
        <div className="rounded-2xl border border-border bg-card p-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-accent/15">
            <svg className="h-7 w-7 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
          </div>
          <h2 className="mb-2 text-lg font-semibold text-text-primary">
            Select a Project
          </h2>
          <p className="mb-6 text-sm text-text-secondary">
            Choose an existing project or create a new one to start your RAG evaluation pipeline.
          </p>
          <div className="flex justify-center">
            <ProjectSelector />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl">
      {/* Header */}
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg className="h-5 w-5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z" />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Setup</h1>
          <p className="text-sm text-text-secondary">
            Import external Q&A baselines and configure API connections for evaluation.
          </p>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Left column: Upload + API Config */}
        <div className="space-y-6 lg:col-span-2">
          <ExternalBaselineUpload
            projectId={project.id}
            onUploaded={() => setRefreshKey((k) => k + 1)}
          />
          <BotConnectorConfig projectId={project.id} />
          <CustomMetricBuilder projectId={project.id} />
        </div>

        {/* Right column: Uploaded CSVs */}
        <div className="lg:col-span-3">
          <CsvUploadsList projectId={project.id} refreshKey={refreshKey} />
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useProject } from "../contexts/ProjectContext";
import {
  fetchDocuments,
  fetchChunkConfigs,
  fetchEmbeddingConfigs,
  fetchRagConfigs,
  fetchTestSets,
  fetchExperiments,
} from "../lib/api";

const stages = [
  {
    path: "setup",
    label: "Setup",
    desc: "Project & documents",
    icon: "01",
  },
  {
    path: "build",
    label: "Build",
    desc: "Chunking, embedding, RAG",
    icon: "02",
  },
  {
    path: "test",
    label: "Test",
    desc: "Generate & annotate",
    icon: "03",
  },
  {
    path: "experiment",
    label: "Experiment",
    desc: "Configure & run",
    icon: "04",
  },
  {
    path: "analyze",
    label: "Analyze",
    desc: "Results & iterate",
    icon: "05",
  },
] as const;

/** Lightweight hook: fetches stage completion from existing API endpoints. */
function useStageCompletion(projectId: number | null) {
  const [completed, setCompleted] = useState<Record<string, boolean>>({});
  const location = useLocation();

  useEffect(() => {
    if (!projectId) {
      setCompleted({});
      return;
    }

    let cancelled = false;

    async function check() {
      try {
        const [docs, chunks, embeddings, rags, testSets, experiments] =
          await Promise.all([
            fetchDocuments(projectId!),
            fetchChunkConfigs(projectId!),
            fetchEmbeddingConfigs(projectId!),
            fetchRagConfigs(projectId!),
            fetchTestSets(projectId!),
            fetchExperiments(projectId!),
          ]);

        if (cancelled) return;

        const hasCompletedExperiment = experiments.some(
          (e) => e.status === "completed",
        );

        setCompleted({
          setup: true, // always true when project exists
          build:
            docs.length > 0 &&
            chunks.length > 0 &&
            embeddings.length > 0 &&
            rags.length > 0,
          test:
            testSets.length > 0 &&
            testSets.some((ts) => ts.approved_count > 0),
          experiment: hasCompletedExperiment,
          analyze: hasCompletedExperiment,
        });
      } catch {
        // Non-critical UI — silently default to all-false
        if (!cancelled) setCompleted({});
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, [projectId, location.pathname]);

  return completed;
}

export default function Stepper() {
  const { project } = useProject();
  const location = useLocation();
  const completed = useStageCompletion(project?.id ?? null);

  const currentPath = location.pathname.split("/").pop() ?? "";

  return (
    <nav
      role="navigation"
      aria-label="Pipeline stages"
      className="flex flex-col gap-1 px-3 py-4"
    >
      {stages.map((stage) => {
        const isActive = currentPath === stage.path;
        const isLocked = !project && stage.path !== "setup";
        const isComplete = !!completed[stage.path] && !isActive;

        return (
          <NavLink
            key={stage.path}
            to={isLocked ? "#" : `/${stage.path}`}
            aria-current={isActive ? "step" : undefined}
            aria-disabled={isLocked}
            onClick={(e) => {
              if (isLocked) e.preventDefault();
            }}
            className={`
              group relative flex items-center gap-3 rounded-lg px-3 py-2.5
              transition-all duration-200 outline-none
              focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base
              ${
                isActive
                  ? "bg-accent-glow text-text-primary"
                  : isLocked
                    ? "cursor-not-allowed opacity-40"
                    : "text-text-secondary hover:bg-elevated hover:text-text-primary"
              }
            `}
          >
            {/* Step number / completion indicator */}
            <span
              className={`
                flex h-8 w-8 shrink-0 items-center justify-center rounded-md
                font-mono text-xs font-semibold tracking-wider
                transition-colors duration-200
                ${
                  isActive
                    ? "bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]"
                    : isComplete
                      ? "bg-emerald-500/15 text-emerald-400"
                      : "bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary"
                }
              `}
            >
              {isComplete ? (
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3.5 8.5L6.5 11.5L12.5 4.5" />
                </svg>
              ) : (
                stage.icon
              )}
            </span>

            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium leading-tight truncate">
                {stage.label}
              </span>
              <span className="text-micro text-text-muted leading-tight truncate">
                {stage.desc}
              </span>
            </div>

            {/* Active indicator bar */}
            {isActive && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-[0_0_8px_rgba(129,140,248,0.5)]" />
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}

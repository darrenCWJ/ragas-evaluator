import { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useProject } from '../contexts/ProjectContext';
import {
  fetchDocuments,
  fetchChunkConfigs,
  fetchEmbeddingConfigs,
  fetchRagConfigs,
  fetchTestSets,
  fetchExperiments,
} from '../lib/api';

const stages = [
  {
    path: 'setup',
    label: 'Setup',
    desc: 'Project & documents',
    icon: '01',
  },
  {
    path: 'build',
    label: 'Build',
    desc: 'Chunking, embedding, RAG',
    icon: '02',
  },
  {
    path: 'test',
    label: 'Test',
    desc: 'Generate & annotate',
    icon: '03',
  },
  {
    path: 'experiment',
    label: 'Experiment',
    desc: 'Configure & run',
    icon: '04',
  },
  {
    path: 'analyze',
    label: 'Analyze',
    desc: 'Results & iterate',
    icon: '05',
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
        const [docs, chunks, embeddings, rags, testSets, experiments] = await Promise.all([
          fetchDocuments(projectId!),
          fetchChunkConfigs(projectId!),
          fetchEmbeddingConfigs(projectId!),
          fetchRagConfigs(projectId!),
          fetchTestSets(projectId!),
          fetchExperiments(projectId!),
        ]);

        if (cancelled) return;

        const hasCompletedExperiment = experiments.some((e) => e.status === 'completed');

        setCompleted({
          setup: true, // always true when project exists
          build: docs.length > 0 && chunks.length > 0 && embeddings.length > 0 && rags.length > 0,
          test: testSets.length > 0 && testSets.some((ts) => ts.approved_count > 0),
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

  const currentPath = location.pathname.split('/').pop() ?? '';

  const isKgActive = currentPath === 'knowledge-graph';
  const isPersonasActive = currentPath === 'personas';
  const isSkillsActive = currentPath === 'skills';
  const isWorkersActive = currentPath === 'workers';

  return (
    <nav role="navigation" aria-label="Pipeline stages" className="flex flex-col gap-1 px-3 py-4">
      {stages.map((stage) => {
        const isActive = currentPath === stage.path;
        const isLocked = !project && stage.path !== 'setup';
        const isComplete = !!completed[stage.path] && !isActive;

        return (
          <NavLink
            key={stage.path}
            to={isLocked ? '#' : `/${stage.path}`}
            aria-current={isActive ? 'step' : undefined}
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
                  ? 'bg-accent-glow text-text-primary'
                  : isLocked
                    ? 'cursor-not-allowed opacity-40'
                    : 'text-text-secondary hover:bg-elevated hover:text-text-primary'
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
                    ? 'bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]'
                    : isComplete
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : 'bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary'
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
              <span className="text-sm font-medium leading-tight truncate">{stage.label}</span>
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

      {/* Utility links separator */}
      <div className="mx-3 my-2 border-t border-border" />

      {/* Knowledge Graph explorer link */}
      <NavLink
        to="/knowledge-graph"
        className={`
          group relative flex items-center gap-3 rounded-lg px-3 py-2.5
          transition-all duration-200 outline-none
          focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base
          ${
            isKgActive
              ? 'bg-accent-glow text-text-primary'
              : 'text-text-secondary hover:bg-elevated hover:text-text-primary'
          }
        `}
      >
        <span
          className={`
            flex h-8 w-8 shrink-0 items-center justify-center rounded-md
            transition-colors duration-200
            ${
              isKgActive
                ? 'bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]'
                : 'bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary'
            }
          `}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z"
            />
          </svg>
        </span>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium leading-tight truncate">Knowledge Graphs</span>
          <span className="text-micro text-text-muted leading-tight truncate">
            Explore & visualize
          </span>
        </div>
        {isKgActive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-[0_0_8px_rgba(129,140,248,0.5)]" />
        )}
      </NavLink>

      {/* Personas link */}
      <NavLink
        to="/personas"
        className={`
          group relative flex items-center gap-3 rounded-lg px-3 py-2.5
          transition-all duration-200 outline-none
          focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base
          ${
            isPersonasActive
              ? 'bg-accent-glow text-text-primary'
              : 'text-text-secondary hover:bg-elevated hover:text-text-primary'
          }
        `}
      >
        <span
          className={`
            flex h-8 w-8 shrink-0 items-center justify-center rounded-md
            transition-colors duration-200
            ${
              isPersonasActive
                ? 'bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]'
                : 'bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary'
            }
          `}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
            />
          </svg>
        </span>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium leading-tight truncate">Personas</span>
          <span className="text-micro text-text-muted leading-tight truncate">Edit & manage</span>
        </div>
        {isPersonasActive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-[0_0_8px_rgba(129,140,248,0.5)]" />
        )}
      </NavLink>

      {/* Skill Arena link */}
      <NavLink
        to="/skills"
        className={`
          group relative flex items-center gap-3 rounded-lg px-3 py-2.5
          transition-all duration-200 outline-none
          focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base
          ${
            isSkillsActive
              ? 'bg-accent-glow text-text-primary'
              : 'text-text-secondary hover:bg-elevated hover:text-text-primary'
          }
        `}
      >
        <span
          className={`
            flex h-8 w-8 shrink-0 items-center justify-center rounded-md
            transition-colors duration-200
            ${
              isSkillsActive
                ? 'bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]'
                : 'bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary'
            }
          `}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M16.5 18.75h-9m9 0a3 3 0 013 3h-15a3 3 0 013-3m9 0v-3.375c0-.621-.503-1.125-1.125-1.125h-.871M7.5 18.75v-3.375c0-.621.504-1.125 1.125-1.125h.872m5.007 0H9.497m5.007 0a7.454 7.454 0 01-.982-3.172M9.497 14.25a7.454 7.454 0 00.981-3.172M5.25 4.236c-.982.143-1.954.317-2.916.52A6.003 6.003 0 007.73 9.728M5.25 4.236V4.5c0 2.108.966 3.99 2.48 5.228M5.25 4.236V2.721C7.456 2.41 9.71 2.25 12 2.25c2.291 0 4.545.16 6.75.47v1.516M7.73 9.728a6.726 6.726 0 002.748 1.35m8.272-6.842V4.5c0 2.108-.966 3.99-2.48 5.228m2.48-5.492a46.32 46.32 0 012.916.52 6.003 6.003 0 01-5.395 4.972m0 0a6.726 6.726 0 01-2.749 1.35m0 0a6.772 6.772 0 01-3.044 0"
            />
          </svg>
        </span>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium leading-tight truncate">Skill Arena</span>
          <span className="text-micro text-text-muted leading-tight truncate">
            Compare model adherence
          </span>
        </div>
        {isSkillsActive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-[0_0_8px_rgba(129,140,248,0.5)]" />
        )}
      </NavLink>

      {/* Workers dashboard link */}
      <NavLink
        to="/workers"
        className={`
          group relative flex items-center gap-3 rounded-lg px-3 py-2.5
          transition-all duration-200 outline-none
          focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base
          ${
            isWorkersActive
              ? 'bg-accent-glow text-text-primary'
              : 'text-text-secondary hover:bg-elevated hover:text-text-primary'
          }
        `}
      >
        <span
          className={`
            flex h-8 w-8 shrink-0 items-center justify-center rounded-md
            transition-colors duration-200
            ${
              isWorkersActive
                ? 'bg-accent text-deep shadow-[0_0_12px_rgba(129,140,248,0.3)]'
                : 'bg-card text-text-muted group-hover:bg-elevated group-hover:text-text-secondary'
            }
          `}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z"
            />
          </svg>
        </span>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium leading-tight truncate">Workers</span>
          <span className="text-micro text-text-muted leading-tight truncate">
            Monitor & manage
          </span>
        </div>
        {isWorkersActive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-[0_0_8px_rgba(129,140,248,0.5)]" />
        )}
      </NavLink>
    </nav>
  );
}

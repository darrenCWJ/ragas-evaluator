import {
  fetchBotConfigs,
  fetchJudgeModels,
  fetchSkills,
  fetchSkillTrials,
  fetchTestSets,
} from '../api';
import type { BotConfig, JudgeModel } from '../api';
import SkillLibrary from '../components/skills/SkillLibrary';
import TrialCreate from '../components/skills/TrialCreate';
import TrialList from '../components/skills/TrialList';
import { Card } from '../components/ui';
import { useProject } from '../contexts/ProjectContext';
import { useFetch } from '../hooks/useFetch';

interface ModelSources {
  judgeModels: JudgeModel[];
  botConfigs: BotConfig[];
}

function SectionHeading({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-medium text-text-primary">{title}</h2>
      <p className="text-xs text-text-muted">{desc}</p>
    </div>
  );
}

/** Skill Arena — upload instruction skills, race models against a test set, apply the winner. */
export default function SkillsPage() {
  const { project } = useProject();
  const projectId = project?.id ?? null;

  const skillsFetch = useFetch(
    () => (projectId ? fetchSkills(projectId) : Promise.resolve([])),
    [projectId],
  );
  const testSetsFetch = useFetch(
    () => (projectId ? fetchTestSets(projectId) : Promise.resolve([])),
    [projectId],
  );
  const trialsFetch = useFetch(
    () => (projectId ? fetchSkillTrials(projectId) : Promise.resolve([])),
    [projectId],
  );
  const modelsFetch = useFetch<ModelSources>(async () => {
    if (!projectId) return { judgeModels: [], botConfigs: [] };
    const [judge, bots] = await Promise.all([
      fetchJudgeModels(),
      fetchBotConfigs(projectId).catch(() => [] as BotConfig[]),
    ]);
    return { judgeModels: judge.models, botConfigs: bots };
  }, [projectId]);

  if (!projectId) {
    return (
      <div className="mx-auto max-w-4xl pt-8">
        <Card padding="lg" className="py-16 text-center">
          <p className="text-sm text-text-muted">Select a project to use the Skill Arena.</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8 pt-8">
      <div className="flex items-center gap-3">
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
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Skill Arena</h1>
          <p className="text-sm text-text-secondary">
            Run a skill file across multiple AI models, compare directive adherence, and apply the
            winner as the project default.
          </p>
        </div>
      </div>

      <section>
        <SectionHeading
          title="Skill library"
          desc="SKILL.md-style instruction files, parsed into testable directive checklists."
        />
        <SkillLibrary
          projectId={projectId}
          skills={skillsFetch.data ?? []}
          loading={skillsFetch.loading}
          loadError={skillsFetch.error}
          onChanged={skillsFetch.reload}
        />
      </section>

      <section>
        <SectionHeading
          title="New trial"
          desc="Each model answers every approved question with the skill applied (and optionally without, as a baseline)."
        />
        <TrialCreate
          projectId={projectId}
          skills={skillsFetch.data ?? []}
          testSets={testSetsFetch.data ?? []}
          judgeModels={modelsFetch.data?.judgeModels ?? []}
          botConfigs={modelsFetch.data?.botConfigs ?? []}
          onCreated={trialsFetch.reload}
        />
      </section>

      <section>
        <SectionHeading
          title="Trials"
          desc="Click a trial to open its adherence matrix; click a cell to drill into per-question verdicts and traces."
        />
        <TrialList
          projectId={projectId}
          trials={trialsFetch.data ?? []}
          loading={trialsFetch.loading}
          loadError={trialsFetch.error}
          onChanged={trialsFetch.reload}
        />
      </section>
    </div>
  );
}

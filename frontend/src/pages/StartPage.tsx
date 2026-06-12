import { Link } from 'react-router-dom';
import { useProject } from '../contexts/ProjectContext';
import { useFetch } from '../hooks/useFetch';
import { fetchDocuments, fetchBotConfigs, fetchTestSets, fetchExperiments } from '../lib/api';
import { Card, Spinner } from '../components/ui';

interface Step {
  label: string;
  to: string;
  done: boolean;
}

function StepRow({ step, index }: { step: Step; index: number }) {
  return (
    <Link
      to={`/${step.to}`}
      className="group flex items-center gap-3 rounded-lg px-2 py-1.5 transition-colors hover:bg-elevated"
    >
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
          step.done ? 'bg-emerald-500/15 text-emerald-400' : 'bg-input text-text-muted'
        }`}
      >
        {step.done ? '✓' : index + 1}
      </span>
      <span
        className={`text-sm ${step.done ? 'text-text-muted line-through decoration-text-muted/40' : 'text-text-secondary group-hover:text-text-primary'}`}
      >
        {step.label}
      </span>
    </Link>
  );
}

function PathCard({ title, blurb, steps }: { title: string; blurb: string; steps: Step[] }) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div>
        <h2 className="text-base font-semibold text-text-primary">{title}</h2>
        <p className="mt-1 text-xs text-text-muted">{blurb}</p>
      </div>
      <div className="flex flex-col gap-1">
        {steps.map((s, i) => (
          <StepRow key={s.to + s.label} step={s} index={i} />
        ))}
      </div>
    </Card>
  );
}

export default function StartPage() {
  const { project } = useProject();
  const projectId = project?.id ?? null;

  const docs = useFetch(
    () => (projectId ? fetchDocuments(projectId) : Promise.resolve([])),
    [projectId],
  );
  const bots = useFetch(
    () => (projectId ? fetchBotConfigs(projectId) : Promise.resolve([])),
    [projectId],
  );
  const testSets = useFetch(
    () => (projectId ? fetchTestSets(projectId) : Promise.resolve([])),
    [projectId],
  );
  const experiments = useFetch(
    () => (projectId ? fetchExperiments(projectId) : Promise.resolve([])),
    [projectId],
  );

  if (!project) {
    return (
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-2 text-xl font-semibold text-text-primary">Welcome to Tribunal</h1>
        <p className="mb-6 text-sm text-text-secondary">
          Test your AI agent, see exactly what went wrong, and verify your fixes actually work.
        </p>
        <Card className="p-6 text-center text-sm text-text-muted">
          Create or select a project in the sidebar to begin.
        </Card>
      </div>
    );
  }

  const loading = docs.loading || bots.loading || testSets.loading || experiments.loading;
  const hasBot = (bots.data?.length ?? 0) > 0;
  const hasDocs = (docs.data?.length ?? 0) > 0;
  const hasApprovedSet = (testSets.data ?? []).some((ts) => ts.approved_count > 0);
  const hasExperiment = (experiments.data?.length ?? 0) > 0;
  const hasCompleted = (experiments.data ?? []).some((e) => e.status === 'completed');

  const externalSteps: Step[] = [
    { label: 'Connect your agent (API endpoint or provider key)', to: 'setup', done: hasBot },
    {
      label: 'Upload your test set — or generate one from documents',
      to: 'test',
      done: hasApprovedSet,
    },
    { label: 'Run an experiment against your agent', to: 'experiment', done: hasExperiment },
    { label: 'See what went wrong & get prompt fixes', to: 'analyze', done: hasCompleted },
  ];

  const ragSteps: Step[] = [
    { label: 'Upload documents & configure the pipeline', to: 'build', done: hasDocs },
    { label: 'Generate a test set from your documents', to: 'test', done: hasApprovedSet },
    { label: 'Run experiments across configurations', to: 'experiment', done: hasExperiment },
    { label: 'Analyze, apply suggestions & iterate', to: 'analyze', done: hasCompleted },
  ];

  // "What's next": first incomplete step on the path with more progress
  const progress = (steps: Step[]) => steps.filter((s) => s.done).length;
  const activePath = progress(externalSteps) >= progress(ragSteps) ? externalSteps : ragSteps;
  const nextStep = activePath.find((s) => !s.done);

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-2 text-xl font-semibold text-text-primary">Welcome to Tribunal</h1>
      <p className="mb-6 text-sm text-text-secondary">
        Test your AI agent, see exactly what went wrong, and verify your fixes actually work. Pick
        the path that matches your setup — both end at the same answer.
      </p>

      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner size="lg" />
        </div>
      ) : (
        <>
          {nextStep && (
            <Card className="mb-5 flex items-center justify-between gap-4 border-accent/30 bg-accent/5 p-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-accent">
                  What&apos;s next
                </p>
                <p className="mt-0.5 text-sm text-text-primary">{nextStep.label}</p>
              </div>
              <Link
                to={`/${nextStep.to}`}
                className="shrink-0 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Go →
              </Link>
            </Card>
          )}
          {!nextStep && (
            <Card className="mb-5 border-emerald-500/30 bg-emerald-500/5 p-4 text-sm text-emerald-400">
              Full loop complete — review your results in Analyze, apply a suggestion, and re-run to
              verify the fix.
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <PathCard
              title="Test an external AI agent"
              blurb="Your agent already exists and is reachable via API (custom endpoint, OpenAI, Claude, Gemini, DeepSeek…). Tribunal sends it your test questions and judges the answers."
              steps={externalSteps}
            />
            <PathCard
              title="Build & evaluate a RAG pipeline"
              blurb="Build the retrieval pipeline here — upload documents, configure chunking/embedding/retrieval — then measure and iterate on it."
              steps={ragSteps}
            />
          </div>

          <p className="mt-5 text-xs text-text-muted">
            Tip: run a <span className="text-text-secondary">quality audit</span> on your test set
            (Test page) before the first experiment — a flawed test set produces flawed verdicts.
          </p>
        </>
      )}
    </div>
  );
}

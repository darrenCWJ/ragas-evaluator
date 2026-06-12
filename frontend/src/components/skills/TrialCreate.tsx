import { useMemo, useState } from 'react';
import { createSkillTrial } from '../../api';
import type { BotConfig, JudgeModel, Skill, SkillTrialModelSpec, TestSet } from '../../api';
import { Button, Card, ErrorAlert, FormField, Select, TextInput } from '../ui';

interface TrialCreateProps {
  projectId: number;
  skills: Skill[];
  testSets: TestSet[];
  judgeModels: JudgeModel[];
  botConfigs: BotConfig[];
  onCreated: () => void;
}

interface ModelOption {
  key: string;
  label: string;
  detail: string;
  disabled: boolean;
}

/** Bot connectors that cannot carry a skill as system context. */
const INELIGIBLE_CONNECTORS = new Set(['csv', 'glean']);

function buildModelSpecs(selectedKeys: string[], botConfigs: BotConfig[]): SkillTrialModelSpec[] {
  return selectedKeys.map((key) => {
    if (key.startsWith('llm:')) {
      return { kind: 'llm' as const, model: key.slice(4) };
    }
    const botId = Number(key.slice(4));
    const bot = botConfigs.find((b) => b.id === botId);
    return { kind: 'bot' as const, bot_config_id: botId, label: bot?.name };
  });
}

/** New trial form — skill × test set × model multi-select with a cell-count estimate. */
export default function TrialCreate({
  projectId,
  skills,
  testSets,
  judgeModels,
  botConfigs,
  onCreated,
}: TrialCreateProps) {
  const [name, setName] = useState('');
  const [skillId, setSkillId] = useState<number | ''>('');
  const [testSetId, setTestSetId] = useState<number | ''>('');
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [includeBaseline, setIncludeBaseline] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligibleBots = useMemo(
    () => botConfigs.filter((b) => !INELIGIBLE_CONNECTORS.has(b.connector_type)),
    [botConfigs],
  );

  const options: ModelOption[] = useMemo(
    () => [
      ...judgeModels.map((m) => ({
        key: `llm:${m.id}`,
        label: m.name,
        detail: m.available ? m.provider : `${m.provider} — no API key`,
        disabled: !m.available,
      })),
      ...eligibleBots.map((b) => ({
        key: `bot:${b.id}`,
        label: b.name,
        detail: `bot · ${b.connector_type}`,
        disabled: false,
      })),
    ],
    [judgeModels, eligibleBots],
  );

  const toggleKey = (key: string) => {
    setSelectedKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const selectedTestSet = testSets.find((ts) => ts.id === testSetId);
  const variants = includeBaseline ? 2 : 1;
  const estimatedCells = selectedTestSet
    ? selectedTestSet.approved_count * selectedKeys.length * variants
    : null;

  const canRun =
    name.trim().length > 0 && skillId !== '' && testSetId !== '' && selectedKeys.length > 0;

  const handleRun = async () => {
    if (skillId === '' || testSetId === '' || !name.trim() || selectedKeys.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      await createSkillTrial(projectId, {
        name: name.trim(),
        skill_id: skillId,
        test_set_id: testSetId,
        models: buildModelSpecs(selectedKeys, botConfigs),
        include_baseline: includeBaseline,
      });
      setName('');
      setSelectedKeys([]);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start trial');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card padding="lg" className="space-y-4">
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      <div className="grid gap-3 sm:grid-cols-3">
        <FormField label="Trial name">
          <TextInput
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. tone-skill shootout"
          />
        </FormField>
        <FormField label="Skill">
          <Select
            value={skillId}
            onChange={(e) => setSkillId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select a skill...</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} v{s.version} ({s.directive_count} directives)
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Test set" hint="Only approved questions are used">
          <Select
            value={testSetId}
            onChange={(e) => setTestSetId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select a test set...</option>
            {testSets.map((ts) => (
              <option key={ts.id} value={ts.id}>
                {ts.name} ({ts.approved_count} approved)
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <FormField label="Models" hint="Each selected model runs every question per variant">
        {options.length === 0 ? (
          <p className="text-xs text-text-muted">
            No models available. Configure judge model API keys or add a bot connector.
          </p>
        ) : (
          <div className="grid gap-1.5 sm:grid-cols-2">
            {options.map((opt) => (
              <label
                key={opt.key}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
                  opt.disabled
                    ? 'cursor-not-allowed border-border opacity-40'
                    : selectedKeys.includes(opt.key)
                      ? 'cursor-pointer border-accent bg-accent/5 text-text-primary'
                      : 'cursor-pointer border-border text-text-secondary hover:border-border-focus'
                }`}
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  disabled={opt.disabled}
                  checked={selectedKeys.includes(opt.key)}
                  onChange={() => toggleKey(opt.key)}
                />
                <span className="min-w-0 truncate">{opt.label}</span>
                <span className="ml-auto shrink-0 text-2xs text-text-muted">{opt.detail}</span>
              </label>
            ))}
          </div>
        )}
      </FormField>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            className="accent-accent"
            checked={includeBaseline}
            onChange={(e) => setIncludeBaseline(e.target.checked)}
          />
          Include baseline (run each model without the skill to measure lift)
        </label>
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-muted">
            {estimatedCells !== null
              ? `~${estimatedCells} cells (${selectedTestSet?.approved_count ?? 0} questions × ${selectedKeys.length} models × ${variants} variant${variants > 1 ? 's' : ''})`
              : 'cells = questions × models × variants'}
          </span>
          <Button onClick={handleRun} loading={submitting} disabled={!canRun}>
            Run trial
          </Button>
        </div>
      </div>
    </Card>
  );
}

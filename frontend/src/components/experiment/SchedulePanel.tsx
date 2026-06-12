import { useState } from 'react';
import {
  acknowledgeScheduleAlert,
  createSchedule,
  deleteSchedule,
  fetchSchedule,
  fetchSchedules,
  runScheduleNow,
  updateSchedule,
} from '../../api';
import type { BotConfig, ScheduleDetail, TestSet } from '../../api';
import { Button, ErrorAlert, FormField, TextInput } from '../ui';
import { useFetch } from '../../hooks/useFetch';

interface Props {
  projectId: number;
  testSets: TestSet[];
  botConfigs: BotConfig[];
}

/** Scheduled regression runs against external agents, with drop alerts. */
export default function SchedulePanel({ projectId, testSets, botConfigs }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [botConfigId, setBotConfigId] = useState<number | ''>(botConfigs[0]?.id ?? '');
  const [testSetId, setTestSetId] = useState<number | ''>(testSets[0]?.id ?? '');
  const [intervalMinutes, setIntervalMinutes] = useState(1440);
  const [threshold, setThreshold] = useState(0.1);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ScheduleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const schedulesFetch = useFetch(() => fetchSchedules(projectId), [projectId]);
  const schedules = schedulesFetch.data ?? [];

  async function handleCreate() {
    if (!name.trim() || botConfigId === '' || testSetId === '') return;
    setCreating(true);
    setFormError(null);
    try {
      await createSchedule(projectId, {
        name: name.trim(),
        bot_config_id: botConfigId as number,
        test_set_id: testSetId as number,
        interval_minutes: intervalMinutes,
        alert_drop_threshold: threshold,
        webhook_url: webhookUrl.trim() || null,
      });
      setName('');
      setWebhookUrl('');
      setShowForm(false);
      await schedulesFetch.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to create schedule');
    } finally {
      setCreating(false);
    }
  }

  async function refreshDetail(scheduleId: number) {
    setDetailLoading(true);
    try {
      setDetail(await fetchSchedule(projectId, scheduleId));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to load schedule');
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleToggleExpand(scheduleId: number) {
    if (expandedId === scheduleId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(scheduleId);
    setDetail(null);
    await refreshDetail(scheduleId);
  }

  async function handleToggleEnabled(scheduleId: number, enabled: boolean) {
    setActionError(null);
    try {
      await updateSchedule(projectId, scheduleId, { enabled: !enabled });
      await schedulesFetch.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Update failed');
    }
  }

  async function handleRunNow(scheduleId: number) {
    setActionError(null);
    setNotice(null);
    try {
      await runScheduleNow(projectId, scheduleId);
      setNotice('Regression run started — results appear in the experiment list.');
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Run failed');
    }
  }

  async function handleDelete(scheduleId: number) {
    setActionError(null);
    try {
      await deleteSchedule(projectId, scheduleId);
      setConfirmDeleteId(null);
      if (expandedId === scheduleId) setExpandedId(null);
      await schedulesFetch.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Delete failed');
      setConfirmDeleteId(null);
    }
  }

  async function handleAck(scheduleId: number, alertId: number) {
    setActionError(null);
    try {
      await acknowledgeScheduleAlert(projectId, scheduleId, alertId);
      await Promise.all([refreshDetail(scheduleId), schedulesFetch.reload()]);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Acknowledge failed');
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Scheduled Regression Runs</h3>
          <p className="text-xs text-text-muted">
            Re-run a bot test set on an interval and get alerted when metrics drop.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Close' : 'New Schedule'}
        </Button>
      </div>

      {showForm &&
        (botConfigs.length === 0 ? (
          <p className="mb-4 rounded-lg border border-border/60 bg-card/40 p-4 text-xs text-text-muted">
            Schedules monitor external agents — create a bot connector in Setup first.
          </p>
        ) : (
          <div className="mb-4 space-y-3 rounded-lg border border-border/60 bg-card/40 p-4">
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Name">
                <TextInput
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. nightly prod check"
                />
              </FormField>
              <FormField label="Bot Connector">
                <select
                  value={botConfigId}
                  onChange={(e) => setBotConfigId(e.target.value ? Number(e.target.value) : '')}
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                >
                  {botConfigs.map((bc) => (
                    <option key={bc.id} value={bc.id}>
                      {bc.name}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label="Test Set">
                <select
                  value={testSetId}
                  onChange={(e) => setTestSetId(e.target.value ? Number(e.target.value) : '')}
                  className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none"
                >
                  {testSets.map((ts) => (
                    <option key={ts.id} value={ts.id}>
                      {ts.name}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label="Interval (minutes)" hint="15 minutes to 7 days; 1440 = daily">
                <TextInput
                  type="number"
                  min={15}
                  max={10080}
                  value={intervalMinutes}
                  onChange={(e) => setIntervalMinutes(parseInt(e.target.value) || 1440)}
                />
              </FormField>
              <FormField
                label={`Alert threshold (${threshold.toFixed(2)})`}
                hint="Alert when any metric drops more than this vs the previous run"
              >
                <input
                  type="range"
                  min="0.02"
                  max="0.5"
                  step="0.01"
                  value={threshold}
                  onChange={(e) => setThreshold(parseFloat(e.target.value))}
                  className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-border accent-accent"
                />
              </FormField>
              <FormField label="Webhook URL (optional)" hint="POSTed alert payloads (https)">
                <TextInput
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://hooks.example.com/..."
                />
              </FormField>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={handleCreate}
                loading={creating}
                disabled={!name.trim() || botConfigId === '' || testSetId === ''}
              >
                Create Schedule
              </Button>
            </div>
            <ErrorAlert message={formError} onDismiss={() => setFormError(null)} />
          </div>
        ))}

      <ErrorAlert message={actionError} onDismiss={() => setActionError(null)} />
      {notice && (
        <p className="mb-2 rounded-lg bg-accent/10 px-4 py-2 text-xs text-accent">{notice}</p>
      )}
      {schedulesFetch.error && <ErrorAlert message={schedulesFetch.error} />}

      {schedules.length === 0 ? (
        <p className="py-3 text-center text-xs text-text-muted">No schedules yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {schedules.map((schedule) => (
            <li key={schedule.id} className="rounded-lg bg-card px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-text-primary">
                    {schedule.name}
                  </span>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wider ${schedule.enabled ? 'bg-score-high/15 text-score-high' : 'bg-elevated text-text-muted'}`}
                  >
                    {schedule.enabled ? 'On' : 'Off'}
                  </span>
                  <span className="shrink-0 text-2xs text-text-muted">
                    every {schedule.interval_minutes}m
                  </span>
                  {schedule.open_alerts > 0 && (
                    <span className="shrink-0 rounded bg-score-low/15 px-1.5 py-0.5 text-2xs font-bold text-score-low">
                      {schedule.open_alerts} alert{schedule.open_alerts !== 1 ? 's' : ''}
                    </span>
                  )}
                  {schedule.last_run_at && (
                    <span className="hidden shrink-0 text-2xs text-text-muted sm:inline">
                      last: {new Date(schedule.last_run_at).toLocaleString()}
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => handleToggleExpand(schedule.id)}
                    className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
                  >
                    {expandedId === schedule.id ? 'Hide' : 'Alerts'}
                  </button>
                  <button
                    onClick={() => handleRunNow(schedule.id)}
                    className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
                  >
                    Run now
                  </button>
                  <button
                    onClick={() => handleToggleEnabled(schedule.id, schedule.enabled)}
                    className="rounded px-2 py-1 text-xs text-text-secondary hover:bg-elevated"
                  >
                    {schedule.enabled ? 'Disable' : 'Enable'}
                  </button>
                  {confirmDeleteId === schedule.id ? (
                    <span className="flex items-center gap-1">
                      <button
                        onClick={() => handleDelete(schedule.id)}
                        className="rounded bg-score-low/20 px-2 py-1 text-xs text-score-low hover:bg-score-low/30"
                      >
                        Yes
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded bg-elevated px-2 py-1 text-xs text-text-secondary hover:bg-border"
                      >
                        No
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(schedule.id)}
                      className="rounded px-2 py-1 text-xs text-text-muted hover:text-score-low"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {expandedId === schedule.id && (
                <div className="mt-3 border-t border-border pt-3">
                  {detailLoading && !detail ? (
                    <p className="text-xs text-text-muted">Loading alerts…</p>
                  ) : detail && detail.alerts.length > 0 ? (
                    <ul className="space-y-2">
                      {detail.alerts.map((alert) => (
                        <li
                          key={alert.id}
                          className={`rounded-lg px-3 py-2 text-xs ${alert.acknowledged ? 'bg-elevated/50 text-text-muted' : 'bg-score-low/10'}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">
                              {new Date(alert.created_at).toLocaleString()} — experiment #
                              {alert.experiment_id} vs #{alert.baseline_experiment_id}
                            </span>
                            {!alert.acknowledged && (
                              <button
                                onClick={() => handleAck(schedule.id, alert.id)}
                                className="rounded bg-elevated px-2 py-0.5 text-2xs text-text-secondary hover:bg-border"
                              >
                                Acknowledge
                              </button>
                            )}
                          </div>
                          <ul className="mt-1 space-y-0.5">
                            {alert.drops.map((drop) => (
                              <li key={drop.metric} className="font-mono">
                                {drop.metric}: {drop.baseline} → {drop.current}{' '}
                                <span className="text-score-low">(-{drop.drop})</span>
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-text-muted">No alerts — metrics are holding.</p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

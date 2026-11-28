'use client';

/**
 * **Verification settings** — the **Verification** tab of `/ade/dashboard/pacts/settings?tab=verification`
 * (PFX-6.2, #6954; a tab of Contracts settings since PFX-8.14, #7311).
 *
 * * **Workspace defaults** — the verification cadence (when Apiome's hosted verifier runs a pair on
 *   its own), the stale threshold (a pact not verified for longer opens a re-publish request to its
 *   consumer), how many scheduled verifications may run at once, how long a re-publish request stays
 *   open before it expires and escalates, and whether stale pacts open requests at all. **Save**
 *   replaces them.
 * * **Overrides** — a different cadence, threshold or verification target for one provider (every
 *   consumer) or one consumer ↔ provider pair; the pair's wins over the provider's, which wins over
 *   the workspace's. A scheduled run needs a target, which only an override can name. **Add
 *   override** / **Edit** open the override dialog; **Remove** deletes one.
 *
 * Each section reads, fails and retries on its own.
 */

import * as React from 'react';
import Link from 'next/link';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, LoadingState } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { formatWhen, type Pacticipant } from '@lib/pact-pacticipants';
import {
  CADENCES,
  CADENCE_TEXT,
  REQUESTS_ROUTE,
  SETTINGS_RANGES,
  cadenceLabel,
  formatHours,
  type Cadence,
  type OverrideBody,
  type OverrideRecord,
  type SettingsBody,
  type VerificationSettings,
} from '@lib/pact-remediation';
import type { TargetOption } from '@lib/pact-verification';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchPacticipants } from '../pactPacticipants/pacticipantsApi';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { fetchTargetOptions } from '../pactVerification/pactVerificationApi';
import { fetchOverrides, fetchSettings, removeOverride, saveOverride, saveSettings } from './remediationApi';
import { SETTINGS_DESCRIPTION, SETTINGS_TITLE } from '@lib/pact-retention';
import { SettingsTabs } from '../pactSettings/SettingsTabs';
import { VERIFY_RUN_ROUTE } from '@lib/pact-verify-run';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** A section's read. */
type Read<T> = { data: T | null; error: string | null };

/** The settings form's values, as typed. */
type SettingsForm = {
  cadence: Cadence;
  stale_threshold_hours: string;
  max_concurrent_runs: string;
  request_window_hours: string;
  republish_requests_enabled: boolean;
};

/**
 * The form's values from stored settings.
 *
 * @param settings - The stored settings.
 * @returns The form.
 */
function formOf(settings: VerificationSettings): SettingsForm {
  return {
    cadence: settings.cadence,
    stale_threshold_hours: String(settings.stale_threshold_hours),
    max_concurrent_runs: String(settings.max_concurrent_runs),
    request_window_hours: String(settings.request_window_hours),
    republish_requests_enabled: settings.republish_requests_enabled,
  };
}

/**
 * The body to save, or why the form cannot be saved.
 *
 * @param form - The form's values.
 * @returns The body, or the problem.
 */
export function settingsBodyOf(form: SettingsForm): { body: SettingsBody } | { error: string } {
  const numbers: Partial<Record<keyof typeof SETTINGS_RANGES, number>> = {};
  const labels: Record<keyof typeof SETTINGS_RANGES, string> = {
    stale_threshold_hours: 'Stale threshold',
    max_concurrent_runs: 'Concurrent scheduled runs',
    request_window_hours: 'Request window',
  };
  for (const key of Object.keys(SETTINGS_RANGES) as Array<keyof typeof SETTINGS_RANGES>) {
    const [min, max] = SETTINGS_RANGES[key];
    const value = Number(form[key]);
    if (!/^\d+$/.test(form[key].trim()) || value < min || value > max) {
      return { error: `${labels[key]} must be a whole number from ${min} to ${max}.` };
    }
    numbers[key] = value;
  }
  return {
    body: {
      cadence: form.cadence,
      stale_threshold_hours: numbers.stale_threshold_hours as number,
      max_concurrent_runs: numbers.max_concurrent_runs as number,
      request_window_hours: numbers.request_window_hours as number,
      republish_requests_enabled: form.republish_requests_enabled,
    },
  };
}

/**
 * The workspace defaults form.
 *
 * @param props - The stored settings and what saving them does.
 * @returns The form.
 */
function SettingsPanel({
  settings,
  onSave,
}: {
  settings: VerificationSettings;
  onSave: (body: SettingsBody) => Promise<VerificationSettings>;
}) {
  const [form, setForm] = React.useState<SettingsForm>(() => formOf(settings));
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const set = <K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setMessage(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const checked = settingsBodyOf(form);
    if ('error' in checked) {
      setMessage({ tone: 'error', text: checked.error });
      return;
    }
    setBusy(true);
    try {
      const saved = await onSave(checked.body);
      setForm(formOf(saved));
      setMessage({ tone: 'ok', text: 'Saved.' });
    } catch (caught) {
      setMessage({ tone: 'error', text: describeFailure(caught, 'Could not save the settings') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="prx-form" onSubmit={(event) => void submit(event)} data-testid="prx-settings-form">
      {!settings.customised ? (
        <p className="ppx__muted" data-testid="prx-defaults-note">
          This workspace uses the defaults. Saving stores them as its own.
        </p>
      ) : settings.updated_at ? (
        <p className="ppx__muted">Last saved {formatWhen(settings.updated_at)}.</p>
      ) : null}
      <div className="pmx-field">
        <label className="ppx__field-label" htmlFor="prx-cadence">
          Verification cadence
        </label>
        <select
          id="prx-cadence"
          className="pmx-input"
          value={form.cadence}
          onChange={(event) => set('cadence', event.target.value as Cadence)}
          disabled={busy}
          aria-describedby="prx-cadence-help"
        >
          {CADENCES.map((cadence) => (
            <option key={cadence} value={cadence}>
              {CADENCE_TEXT[cadence].label}
            </option>
          ))}
        </select>
        <span id="prx-cadence-help" className="ppx__muted">
          {CADENCE_TEXT[form.cadence].description}
          {form.cadence !== 'manual-only' ? ' A pair runs only where an override names its verification target.' : ''}
        </span>
      </div>
      <div className="prx-form__row">
        <div className="pmx-field">
          <label className="ppx__field-label" htmlFor="prx-threshold">
            Stale threshold (hours)
          </label>
          <input
            id="prx-threshold"
            className="pmx-input"
            inputMode="numeric"
            value={form.stale_threshold_hours}
            onChange={(event) => set('stale_threshold_hours', event.target.value)}
            disabled={busy}
            aria-describedby="prx-threshold-help"
          />
          <span id="prx-threshold-help" className="ppx__muted">
            A pact not verified for longer is stale (1 to 2160).
          </span>
        </div>
        <div className="pmx-field">
          <label className="ppx__field-label" htmlFor="prx-window">
            Request window (hours)
          </label>
          <input
            id="prx-window"
            className="pmx-input"
            inputMode="numeric"
            value={form.request_window_hours}
            onChange={(event) => set('request_window_hours', event.target.value)}
            disabled={busy}
            aria-describedby="prx-window-help"
          />
          <span id="prx-window-help" className="ppx__muted">
            How long a re-publish request waits before it expires and escalates (1 to 720).
          </span>
        </div>
        <div className="pmx-field">
          <label className="ppx__field-label" htmlFor="prx-concurrency">
            Concurrent scheduled runs
          </label>
          <input
            id="prx-concurrency"
            className="pmx-input"
            inputMode="numeric"
            value={form.max_concurrent_runs}
            onChange={(event) => set('max_concurrent_runs', event.target.value)}
            disabled={busy}
            aria-describedby="prx-concurrency-help"
          />
          <span id="prx-concurrency-help" className="ppx__muted">
            How many scheduled verifications may run at once (1 to 10).
          </span>
        </div>
      </div>
      <label className="prx-check" htmlFor="prx-requests">
        <input
          id="prx-requests"
          type="checkbox"
          checked={form.republish_requests_enabled}
          onChange={(event) => set('republish_requests_enabled', event.target.checked)}
          disabled={busy}
        />
        <span>Ask the consumer to re-publish a pact when it goes stale</span>
      </label>
      <div className="prx-form__actions">
        <Button type="submit" disabled={busy} data-testid="prx-settings-save">
          {busy ? 'Saving…' : 'Save'}
        </Button>
        {message ? (
          <span
            className={message.tone === 'ok' ? 'prx-saved' : 'ppx__error'}
            role={message.tone === 'error' ? 'alert' : 'status'}
            data-testid="prx-settings-message"
          >
            {message.text}
          </span>
        ) : null}
      </div>
    </form>
  );
}

/** What the override dialog edits: a new override, or an existing one. */
type OverrideDraft = { existing: OverrideRecord | null };

/**
 * The body to save from the override dialog's values, or why it cannot be saved.
 *
 * @param values - Provider, consumer, cadence, threshold and target as typed (empty inherits).
 * @returns The body, or the problem.
 */
export function overrideBodyOf(values: {
  provider: string;
  consumer: string;
  cadence: string;
  threshold: string;
  target: string;
}): { body: OverrideBody } | { error: string } {
  const provider = values.provider.trim();
  if (!provider) return { error: 'Choose the provider.' };
  const body: OverrideBody = { provider };
  if (values.consumer.trim()) {
    if (values.consumer.trim() === provider) return { error: 'A pacticipant cannot be its own consumer.' };
    body.consumer = values.consumer.trim();
  }
  if (values.cadence) body.cadence = values.cadence as Cadence;
  if (values.threshold.trim()) {
    const hours = Number(values.threshold);
    if (!/^\d+$/.test(values.threshold.trim()) || hours < 1 || hours > 2160) {
      return { error: 'Stale threshold must be a whole number from 1 to 2160, or empty to inherit.' };
    }
    body.stale_threshold_hours = hours;
  }
  if (values.target) body.target_ref = values.target;
  if (!body.cadence && !body.stale_threshold_hours && !body.target_ref) {
    return { error: 'Set at least one of cadence, stale threshold and verification target.' };
  }
  return { body };
}

/**
 * The override dialog: provider, optional consumer, and what it overrides.
 *
 * @param props - What is edited, the pacticipants and targets to choose from, and the callbacks.
 * @returns The dialog.
 */
function OverrideDialog({
  draft,
  pacticipants,
  targets,
  targetsError,
  onSave,
  onClose,
}: {
  draft: OverrideDraft;
  pacticipants: Pacticipant[];
  targets: TargetOption[] | null;
  targetsError: string | null;
  onSave: (body: OverrideBody) => Promise<void>;
  onClose: () => void;
}) {
  const existing = draft.existing;
  const [provider, setProvider] = React.useState(existing?.provider ?? '');
  const [consumer, setConsumer] = React.useState(existing?.consumer ?? '');
  const [cadence, setCadence] = React.useState<string>(existing?.cadence ?? '');
  const [threshold, setThreshold] = React.useState(
    existing?.stale_threshold_hours ? String(existing.stale_threshold_hours) : '',
  );
  const [target, setTarget] = React.useState(existing?.target ?? '');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const checked = overrideBodyOf({ provider, consumer, cadence, threshold, target });
    if ('error' in checked) {
      setError(checked.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(checked.body);
    } catch (caught) {
      setError(describeFailure(caught, 'Could not save the override'));
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent data-testid="prx-override-dialog">
        <DialogHeader>
          <DialogTitle>{existing ? 'Edit override' : 'Add override'}</DialogTitle>
          <DialogDescription>
            Set a cadence, stale threshold or verification target for one provider, or for one consumer of it. Leave a
            field empty to inherit it.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <DialogBody>
            <div className="prx-form">
              <datalist id="prx-pacticipants">
                {pacticipants.map((item) => (
                  <option key={item.slug} value={item.slug}>
                    {item.name}
                  </option>
                ))}
              </datalist>
              <label className="pmx-field" htmlFor="prx-override-provider">
                <span className="ppx__field-label">Provider</span>
                <input
                  id="prx-override-provider"
                  className="pmx-input"
                  list="prx-pacticipants"
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                  placeholder="ledger-api"
                  disabled={busy || existing !== null}
                />
              </label>
              <label className="pmx-field" htmlFor="prx-override-consumer">
                <span className="ppx__field-label">Consumer (empty for every consumer)</span>
                <input
                  id="prx-override-consumer"
                  className="pmx-input"
                  list="prx-pacticipants"
                  value={consumer}
                  onChange={(event) => setConsumer(event.target.value)}
                  placeholder="billing-service"
                  disabled={busy || existing !== null}
                />
              </label>
              <label className="pmx-field" htmlFor="prx-override-cadence">
                <span className="ppx__field-label">Cadence</span>
                <select
                  id="prx-override-cadence"
                  className="pmx-input"
                  value={cadence}
                  onChange={(event) => setCadence(event.target.value)}
                  disabled={busy}
                >
                  <option value="">Inherit</option>
                  {CADENCES.map((option) => (
                    <option key={option} value={option}>
                      {CADENCE_TEXT[option].label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="pmx-field" htmlFor="prx-override-threshold">
                <span className="ppx__field-label">Stale threshold (hours)</span>
                <input
                  id="prx-override-threshold"
                  className="pmx-input"
                  inputMode="numeric"
                  value={threshold}
                  onChange={(event) => setThreshold(event.target.value)}
                  placeholder="Inherit"
                  disabled={busy}
                />
              </label>
              <label className="pmx-field" htmlFor="prx-override-target">
                <span className="ppx__field-label">Verification target for scheduled runs</span>
                {targets === null && !targetsError ? (
                  <span className="ppx__muted">Reading the targets…</span>
                ) : (
                  <select
                    id="prx-override-target"
                    className="pmx-input"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    disabled={busy}
                  >
                    <option value="">Inherit</option>
                    {(targets ?? []).map((option) => (
                      <option key={option.slug} value={option.slug} disabled={!option.enabled}>
                        {option.name} ({option.environment}){option.enabled ? '' : ' — disabled'}
                      </option>
                    ))}
                  </select>
                )}
                {targetsError ? <span className="ppx__error">{targetsError}</span> : null}
              </label>
              {error ? (
                <p className="ppx__error" role="alert" data-testid="prx-override-error">
                  {error}
                </p>
              ) : null}
            </div>
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="prx-override-save">
              {busy ? 'Saving…' : 'Save override'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The overrides table.
 *
 * @param props - The overrides and what Edit and Remove do.
 * @returns The table.
 */
function OverridesTable({
  overrides,
  onEdit,
  onRemove,
}: {
  overrides: OverrideRecord[];
  onEdit: (override: OverrideRecord) => void;
  onRemove: (override: OverrideRecord) => void;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="prx-overrides-table">
        <caption className="sr-only">Verification overrides, by provider and consumer</caption>
        <thead>
          <tr>
            <th scope="col">Provider</th>
            <th scope="col">Consumer</th>
            <th scope="col">Cadence</th>
            <th scope="col">Stale threshold</th>
            <th scope="col">Verification target</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {overrides.map((override) => {
            const pair = override.consumer
              ? `${override.provider_name} ← ${override.consumer_name}`
              : override.provider_name;
            return (
              <tr key={override.id} data-testid={`prx-override-${override.id}`}>
                <th scope="row">{override.provider_name}</th>
                <td>{override.consumer_name ?? <span className="ppx__muted">Every consumer</span>}</td>
                <td>
                  {override.cadence ? cadenceLabel(override.cadence) : <span className="ppx__muted">Inherited</span>}
                </td>
                <td>
                  {override.stale_threshold_hours ? (
                    formatHours(override.stale_threshold_hours)
                  ) : (
                    <span className="ppx__muted">Inherited</span>
                  )}
                </td>
                <td>
                  {override.target ? (
                    <span className="ppx__chips">
                      <span className="ppx__mono">{override.target_name ?? override.target}</span>
                      {override.target_deleted ? <Badge variant="danger">Deleted</Badge> : null}
                    </span>
                  ) : (
                    <span className="ppx__muted">Inherited</span>
                  )}
                </td>
                <td>
                  <span className="ppx__actions">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onEdit(override)}
                      aria-label={`Edit the override of ${pair}`}
                    >
                      <Pencil aria-hidden />
                      Edit
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onRemove(override)}
                      aria-label={`Remove the override of ${pair}`}
                      data-testid={`prx-remove-${override.id}`}
                    >
                      <Trash2 aria-hidden />
                      Remove
                    </Button>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * **When Apiome verifies on its own** (PFX-8.15, #7312): every provider or pair whose override names a
 * verification target — only those run on a schedule — with its cadence (the override's, else the
 * workspace's), and **Edit** opening the override. The settings below say how each is decided.
 *
 * @param props - The overrides, the workspace cadence, and what Edit does.
 * @returns The panel.
 */
export function ScheduleList({
  overrides,
  defaultCadence,
  onEdit,
}: {
  overrides: OverrideRecord[];
  defaultCadence: Cadence | null;
  onEdit: (override: OverrideRecord) => void;
}) {
  const scheduled = overrides.filter((override) => override.target && !override.target_deleted);
  return (
    <Panel
      id="prx-schedule"
      title="When Apiome verifies on its own"
      aside={
        <Button size="sm" variant="outline" asChild>
          <Link href={VERIFY_RUN_ROUTE}>Run a verification</Link>
        </Button>
      }
    >
      {scheduled.length === 0 ? (
        <p className="ppx__statement" data-testid="prx-schedule-empty">
          Nothing runs on a schedule yet: a provider needs a verification target. Add an override below and pick its
          target.
        </p>
      ) : (
        <div className="ppx__table-wrap">
          <table className="ppx__table" data-testid="prx-schedule-table">
            <caption className="sr-only">Scheduled verifications</caption>
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">Pacts of</th>
                <th scope="col">Target</th>
                <th scope="col">When</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {scheduled.map((override) => (
                <tr key={override.id} data-testid={`prx-schedule-${override.id}`}>
                  <td>{override.provider_name}</td>
                  <td>{override.consumer_name ?? 'Every consumer'}</td>
                  <td>{override.target_name ?? override.target}</td>
                  <td>
                    {cadenceLabel(override.cadence ?? defaultCadence)}
                    {override.cadence ? null : <span className="ppx__muted"> (workspace default)</span>}
                  </td>
                  <td className="pcx-table__actions">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onEdit(override)}
                      aria-label={`Edit the schedule of ${override.provider_name}`}
                    >
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/**
 * The Verification settings page.
 *
 * @returns The page.
 */
export default function VerificationSettingsClient() {
  const [settings, setSettings] = React.useState<Read<VerificationSettings>>({ data: null, error: null });
  const [overrides, setOverrides] = React.useState<Read<OverrideRecord[]>>({ data: null, error: null });
  const [draft, setDraft] = React.useState<OverrideDraft | null>(null);
  const [pacticipants, setPacticipants] = React.useState<Pacticipant[]>([]);
  const [targets, setTargets] = React.useState<TargetOption[] | null>(null);
  const [targetsError, setTargetsError] = React.useState<string | null>(null);
  const [removeError, setRemoveError] = React.useState<string | null>(null);

  const loadSettings = React.useCallback(async () => {
    setSettings({ data: null, error: null });
    try {
      setSettings({ data: await fetchSettings(), error: null });
    } catch (caught) {
      setSettings({ data: null, error: describeFailure(caught, 'Could not load the settings') });
    }
  }, []);

  const loadOverrides = React.useCallback(async () => {
    setOverrides({ data: null, error: null });
    try {
      setOverrides({ data: await fetchOverrides(), error: null });
    } catch (caught) {
      setOverrides({ data: null, error: describeFailure(caught, 'Could not load the overrides') });
    }
  }, []);

  React.useEffect(() => {
    void loadSettings();
    void loadOverrides();
  }, [loadSettings, loadOverrides]);

  const openDraft = (existing: OverrideRecord | null) => {
    setDraft({ existing });
    if (targets === null) {
      fetchTargetOptions()
        .then(setTargets)
        .catch((caught) => setTargetsError(describeFailure(caught, 'Could not load the verification targets')));
    }
    if (pacticipants.length === 0) {
      fetchPacticipants()
        .then((page) => setPacticipants(page.pacticipants))
        .catch(() => setPacticipants([]));
    }
  };

  const save = async (body: OverrideBody) => {
    await saveOverride(body);
    setDraft(null);
    void loadOverrides();
  };

  const remove = async (override: OverrideRecord) => {
    setRemoveError(null);
    try {
      await removeOverride(override.id);
      void loadOverrides();
    } catch (caught) {
      setRemoveError(describeFailure(caught, 'Could not remove the override'));
    }
  };

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="settings" />}
        title={SETTINGS_TITLE}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Settings' },
        ]}
        description={SETTINGS_DESCRIPTION}
        actions={
          <div className="ppx__actions">
            <Button variant="outline" asChild>
              <Link href={REQUESTS_ROUTE}>Re-publish requests</Link>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                void loadSettings();
                void loadOverrides();
              }}
            >
              <RefreshCw aria-hidden />
              Refresh
            </Button>
          </div>
        }
      />
      <PageBody>
        <SettingsTabs active="verification" />
        <p className="ppx__muted prx-intro">
          When Apiome verifies pacts on its own, when a pact counts as stale, and how its consumer is asked to
          re-publish it.
        </p>
        <div className="ppx prx" data-testid="pact-verification-settings">
          {overrides.data ? (
            <ScheduleList
              overrides={overrides.data}
              defaultCadence={settings.data?.cadence ?? null}
              onEdit={(override) => openDraft(override)}
            />
          ) : null}
          <Panel id="prx-defaults" title="Workspace defaults">
            {settings.error ? (
              <SectionError
                title="The settings could not be read"
                error={settings.error}
                onRetry={() => void loadSettings()}
              />
            ) : settings.data === null ? (
              <LoadingState message="Reading the settings…" minHeightClassName="min-h-[4rem]" />
            ) : (
              <SettingsPanel
                key={settings.data.updated_at ?? 'defaults'}
                settings={settings.data}
                onSave={async (body) => {
                  const saved = await saveSettings(body);
                  return saved;
                }}
              />
            )}
          </Panel>
          <Panel
            id="prx-overrides"
            title="Overrides"
            aside={
              <Button size="sm" onClick={() => openDraft(null)} data-testid="prx-add-override">
                <Plus aria-hidden />
                Add override
              </Button>
            }
          >
            {overrides.error ? (
              <SectionError
                title="The overrides could not be read"
                error={overrides.error}
                onRetry={() => void loadOverrides()}
              />
            ) : overrides.data === null ? (
              <LoadingState message="Reading the overrides…" minHeightClassName="min-h-[4rem]" />
            ) : overrides.data.length === 0 ? (
              <p className="ppx__statement" data-testid="prx-overrides-empty">
                No overrides: every pair uses the workspace defaults and has no verification target, so nothing runs on
                a schedule. Add an override to give a provider a target, or a pair its own cadence or threshold.
              </p>
            ) : (
              <>
                <OverridesTable
                  overrides={overrides.data}
                  onEdit={(override) => openDraft(override)}
                  onRemove={(override) => void remove(override)}
                />
                {removeError ? (
                  <p className="ppx__error" role="alert">
                    {removeError}
                  </p>
                ) : null}
              </>
            )}
          </Panel>
        </div>
        {draft ? (
          <OverrideDialog
            draft={draft}
            pacticipants={pacticipants}
            targets={targets}
            targetsError={targetsError}
            onSave={save}
            onClose={() => setDraft(null)}
          />
        ) : null}
      </PageBody>
    </Page>
  );
}

'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, ArrowRight, Check, Play } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { Stepper } from '@/app/components/ui/Stepper';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { ConnectorFields } from '@/app/components/ade/connectors/ConnectorFields';
import { ConflictPolicyOption } from '@/app/components/ade/dashboard/repositories/RepositoryConflictPolicy';
import {
  CONFLICT_POLICIES,
  DEFAULT_CONFLICT_POLICY,
  type ConflictPolicy,
} from '@/app/components/ade/dashboard/repositories/repositoryConflictPolicy';
import {
  CADENCE_OPTIONS,
  CONNECTOR_KINDS,
  buildCredentials,
  buildScope,
  cadenceSeconds,
  connectorKind,
  missingFields,
  type FieldValues,
} from '@lib/connector-kinds';
import { createConnector, dryRunConnector, listConnectors, type DryRunResult } from '@lib/connectors-api';

/**
 * Bring in → Connectors → Add — `/ade/dashboard/connectors/new` (CDG-1.7, #5958).
 *
 * Five steps: **Kind** → **Credentials** → **Scope** → **Dry run** → **Schedule**. The dry run asks the
 * provider once, with the credentials entered here, how many APIs the connector would sync — before
 * anything is stored. Saving is only possible after a dry run of the *current* inputs succeeded; a
 * failing dry run shows the provider's reason and blocks the save. Saving registers the connector,
 * stores its credential, and opens the connector page without a reload.
 */

/** The wizard's steps, in order. */
export const ADD_CONNECTOR_STEPS = [
  { id: 'kind', label: 'Kind' },
  { id: 'credentials', label: 'Credentials' },
  { id: 'scope', label: 'Scope' },
  { id: 'dry-run', label: 'Dry run' },
  { id: 'schedule', label: 'Schedule' },
] as const;

type StepId = (typeof ADD_CONNECTOR_STEPS)[number]['id'];

/** Where the breadcrumb goes. */
const CONNECTORS_ROUTE = '/ade/dashboard/connectors';

/**
 * The add-connector wizard.
 *
 * @returns The page.
 */
export default function AddConnectorClient() {
  const router = useRouter();
  const [step, setStep] = React.useState<StepId>('kind');
  const [kind, setKind] = React.useState<string | null>(null);
  const [syncable, setSyncable] = React.useState<string[] | null>(null);
  const [credentials, setCredentials] = React.useState<FieldValues>({});
  const [scope, setScope] = React.useState<FieldValues>({});
  const [baseUrl, setBaseUrl] = React.useState('');
  const [name, setName] = React.useState('');
  const [cadence, setCadence] = React.useState('default');
  const [policy, setPolicy] = React.useState<ConflictPolicy>(DEFAULT_CONFLICT_POLICY);
  const [dryRun, setDryRun] = React.useState<DryRunResult | null>(null);
  const [dryRunError, setDryRunError] = React.useState<string | null>(null);
  const [running, setRunning] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  const entry = connectorKind(kind);

  React.useEffect(() => {
    listConnectors()
      .then((list) => setSyncable(list.syncableKinds))
      .catch(() => setSyncable([]));
  }, []);

  /** Any change to what the connector *is* invalidates an earlier dry run. */
  const invalidate = React.useCallback(() => {
    setDryRun(null);
    setDryRunError(null);
  }, []);

  const runDryRun = async () => {
    if (!entry) return;
    setRunning(true);
    setDryRun(null);
    setDryRunError(null);
    try {
      setDryRun(
        await dryRunConnector(
          { kind: entry.kind, baseUrl, scope: buildScope(entry, scope) },
          buildCredentials(entry, credentials)
        )
      );
    } catch (e) {
      setDryRunError(e instanceof Error ? e.message : 'The dry run failed. Check the credentials and scope.');
    } finally {
      setRunning(false);
    }
  };

  const save = async () => {
    if (!entry || !dryRun) return;
    setSaving(true);
    setSaveError(null);
    try {
      const created = await createConnector(
        {
          kind: entry.kind,
          name: name.trim(),
          baseUrl,
          scope: buildScope(entry, scope),
          refreshIntervalSeconds: cadenceSeconds(cadence),
          conflictPolicy: policy,
        },
        buildCredentials(entry, credentials)
      );
      router.push(`${CONNECTORS_ROUTE}/${encodeURIComponent(created.id)}`);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'The connector was not saved. Try again.');
      setSaving(false);
    }
  };

  const index = ADD_CONNECTOR_STEPS.findIndex((candidate) => candidate.id === step);
  const go = (offset: number) => setStep(ADD_CONNECTOR_STEPS[index + offset].id);
  const missing = entry && (step === 'credentials' || step === 'scope') ? missingFields(entry, step, step === 'scope' ? scope : credentials, baseUrl) : [];
  const canContinue =
    (step === 'kind' && Boolean(entry)) ||
    ((step === 'credentials' || step === 'scope') && missing.length === 0) ||
    (step === 'dry-run' && dryRun !== null);

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: '/ade/dashboard' },
          { label: 'Connectors', href: CONNECTORS_ROUTE },
          { label: 'Add' },
        ]}
        title="Add a connector"
        description="Point Apiome at a gateway; check what it serves before you save."
      />
      <PageBody>
        <Stepper steps={ADD_CONNECTOR_STEPS} current={step} aria-label="Add a connector" />

        <section className="cnx-step" aria-labelledby="cnx-step-title" data-testid={`connector-step-${step}`}>
          <h2 id="cnx-step-title" className="cnx-section-title">
            {ADD_CONNECTOR_STEPS[index].label}
          </h2>

          {step === 'kind' ? (
            <div className="cnx-kinds" role="radiogroup" aria-label="Connector kind">
              {CONNECTOR_KINDS.map((candidate) => {
                const available = syncable === null || syncable.includes(candidate.kind);
                return (
                  <label
                    key={candidate.kind}
                    className="cnx-kind"
                    data-selected={kind === candidate.kind ? 'true' : 'false'}
                    data-disabled={available ? 'false' : 'true'}
                  >
                    <input
                      type="radio"
                      name="connector-kind"
                      value={candidate.kind}
                      checked={kind === candidate.kind}
                      disabled={!available}
                      onChange={() => {
                        setKind(candidate.kind);
                        setCredentials({});
                        setScope({});
                        setBaseUrl('');
                        invalidate();
                      }}
                      data-testid={`connector-kind-${candidate.kind}`}
                    />
                    <span className="cnx-kind__body">
                      <span className="cnx-name">{candidate.label}</span>
                      <span className="cnx-meta">{candidate.description}</span>
                      {available ? null : <Badge variant="outline">Not available on this deployment</Badge>}
                    </span>
                  </label>
                );
              })}
            </div>
          ) : null}

          {step === 'credentials' && entry ? (
            <>
              {entry.credentialNote ? <p className="cnx-note">{entry.credentialNote}</p> : null}
              {entry.credentials.length > 0 ? (
                <ConnectorFields
                  fields={entry.credentials}
                  values={credentials}
                  idPrefix="connector-credential"
                  onChange={(key, value) => {
                    setCredentials((current) => ({ ...current, [key]: value }));
                    invalidate();
                  }}
                />
              ) : null}
              <p className="cnx-note">
                Credentials are sealed as soon as they are saved and are never shown again. The dry run uses them once and
                stores nothing.
              </p>
            </>
          ) : null}

          {step === 'scope' && entry ? (
            <>
              {entry.baseUrl !== 'none' ? (
                <FormField
                  label="Base URL"
                  htmlFor="connector-base-url"
                  required={entry.baseUrl === 'required'}
                  helperText={entry.baseUrlHelp}
                >
                  <Input
                    id="connector-base-url"
                    value={baseUrl}
                    onChange={(event) => {
                      setBaseUrl(event.target.value);
                      invalidate();
                    }}
                    data-testid="connector-base-url"
                  />
                </FormField>
              ) : null}
              <ConnectorFields
                fields={entry.scope}
                values={scope}
                idPrefix="connector-scope"
                onChange={(key, value) => {
                  setScope((current) => ({ ...current, [key]: value }));
                  invalidate();
                }}
              />
            </>
          ) : null}

          {(step === 'credentials' || step === 'scope') && missing.length > 0 ? (
            <p className="cnx-note" data-testid="connector-missing">
              Still needed: {missing.join(', ')}.
            </p>
          ) : null}

          {step === 'dry-run' && entry ? (
            <>
              <p className="cnx-note">
                Apiome asks {entry.label} once what this connector would sync. Nothing is stored until you save.
              </p>
              <div className="cnx-step__actions">
                <Button variant="soft" onClick={() => void runDryRun()} disabled={running} data-testid="connector-dry-run">
                  <Play aria-hidden />
                  {running ? 'Asking the provider…' : dryRun ? 'Run the dry run again' : 'Run the dry run'}
                </Button>
              </div>
              {dryRunError ? (
                <Alert variant="error" data-testid="connector-dry-run-error">
                  {dryRunError}
                </Alert>
              ) : null}
              {dryRun ? (
                <div className="cnx-dry-run" data-testid="connector-dry-run-result">
                  <p className="cnx-dry-run__count">
                    <Check aria-hidden className="cnx-glyph" />
                    {dryRun.itemCount === 1 ? '1 API found' : `${dryRun.itemCount} APIs found`}
                  </p>
                  {dryRun.items.length > 0 ? (
                    <ul className="cnx-sample">
                      {dryRun.items.map((item) => (
                        <li key={item.remoteId}>
                          <span className="cnx-name">{item.name ?? item.remoteId}</span>
                          <span className="cnx-meta">
                            {[item.environment, item.revision ? `revision ${item.revision}` : null].filter(Boolean).join(' · ')}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {dryRun.truncated ? <p className="cnx-note">The first {dryRun.items.length} are listed.</p> : null}
                  {dryRun.findings.length > 0 ? (
                    <p className="cnx-note">
                      {dryRun.findings.length === 1 ? '1 finding' : `${dryRun.findings.length} findings`} about the inventory;
                      they are listed on each run.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}

          {step === 'schedule' && entry ? (
            <>
              <FormField label="Name" htmlFor="connector-name" required>
                <Input
                  id="connector-name"
                  value={name}
                  placeholder={`${entry.label} production`}
                  onChange={(event) => setName(event.target.value)}
                  data-testid="connector-name"
                />
              </FormField>
              <FormField label="Refresh" htmlFor="connector-cadence">
                <Select value={cadence} onValueChange={setCadence}>
                  <SelectTrigger id="connector-cadence" data-testid="connector-cadence">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CADENCE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <fieldset className="cnx-policies">
                <legend className="cnx-legend">When a synced API was edited in Apiome</legend>
                {CONFLICT_POLICIES.map((candidate) => (
                  <ConflictPolicyOption
                    key={candidate}
                    policy={candidate}
                    name="connector-conflict-policy"
                    selected={policy === candidate}
                    disabled={false}
                    onSelect={setPolicy}
                  />
                ))}
              </fieldset>
              {saveError ? (
                <Alert variant="error" data-testid="connector-save-error">
                  {saveError}
                </Alert>
              ) : null}
            </>
          ) : null}
        </section>

        <div className="cnx-wizard-nav">
          {index > 0 ? (
            <Button variant="ghost" onClick={() => go(-1)} data-testid="connector-back">
              <ArrowLeft aria-hidden />
              Back
            </Button>
          ) : (
            <span />
          )}
          {step === 'schedule' ? (
            <Button onClick={() => void save()} disabled={saving || !dryRun || !name.trim()} data-testid="connector-save">
              {saving ? 'Saving…' : 'Save connector'}
            </Button>
          ) : (
            <Button onClick={() => go(1)} disabled={!canContinue} data-testid="connector-next">
              Continue
              <ArrowRight aria-hidden />
            </Button>
          )}
        </div>
      </PageBody>
    </Page>
  );
}

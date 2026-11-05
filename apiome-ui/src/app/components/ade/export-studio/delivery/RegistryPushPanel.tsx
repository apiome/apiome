'use client';

import { useCallback, useEffect, useState } from 'react';
import { Database } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';

import { DeliveryProfilesError } from './deliveryProfilesApi';
import { fetchRegistryConnectors, pushToRegistry } from './registryPushApi';
import {
  EMPTY_REGISTRY_DRAFT,
  SUBJECT_NAMING_LABELS,
  registryDraftProblem,
  registryPushBody,
  subjectStatus,
  subjectWhere,
  type RegistryConnector,
  type RegistryPushDraft,
  type RegistryPushResult,
  type RegistryPushSource,
  type SubjectNaming,
} from './registryPushModel';

/** Props for {@link RegistryPushPanel}. */
export interface RegistryPushPanelProps {
  /** The export to push: its registry format, source, version and options. */
  source: RegistryPushSource;
  /** Where schema-registry connectors are managed (the Connectors page). */
  connectorsHref: string;
}

/**
 * The Review step's **Registry** destination (MFX-46.3, #4381).
 *
 * For an Avro, JSON Schema or Protobuf export: pick one of the workspace's `schema-registry` connectors
 * (managed on Connectors — the connector holds the registry URL and its credentials, which never reach
 * the browser), how subjects are named, and whether to dry-run; **Push to registry** registers each
 * schema and lists each subject with its status, version and schema id. With no connector it says where
 * to add one.
 *
 * @param props See {@link RegistryPushPanelProps}.
 * @returns The panel, or null while the connectors load.
 */
export function RegistryPushPanel({ source, connectorsHref }: RegistryPushPanelProps) {
  const [connectors, setConnectors] = useState<RegistryConnector[] | null>(null);
  const [draft, setDraft] = useState<RegistryPushDraft>(EMPTY_REGISTRY_DRAFT);
  const [pushing, setPushing] = useState(false);
  const [result, setResult] = useState<RegistryPushResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchRegistryConnectors()
      .then((rows) => {
        if (!live) return;
        setConnectors(rows);
        if (rows.length === 1) setDraft((current) => ({ ...current, connectorId: rows[0].id }));
      })
      .catch(() => live && setConnectors([]));
    return () => {
      live = false;
    };
  }, []);

  const update = (patch: Partial<RegistryPushDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const problem = registryDraftProblem(draft);

  const push = useCallback(async () => {
    setPushing(true);
    setError(null);
    try {
      setResult(await pushToRegistry(registryPushBody(source, draft)));
    } catch (cause) {
      const extra = cause instanceof DeliveryProfilesError && cause.errors.length ? ` ${cause.errors.join(' ')}` : '';
      setError(`${cause instanceof Error ? cause.message : 'The push could not run.'}${extra}`);
    } finally {
      setPushing(false);
    }
  }, [source, draft]);

  if (connectors === null) return null;

  return (
    <div className="xdlv-dest" data-testid="registry-destination">
      <div className="xdlv-dest__head">
        <Database aria-hidden />
        <span className="xdlv-dest__name">Schema registry</span>
      </div>
      {connectors.length === 0 ? (
        <p className="xdlv-quiet" data-testid="registry-empty">
          No schema registry connected. Add a <strong>Schema registry</strong> connector on{' '}
          <a href={connectorsHref}>Connectors</a> to register this export&rsquo;s schemas there.
        </p>
      ) : (
        <>
          <div className="xdlv-registry__form">
            <label className="xdlv-field">
              <span className="xdlv-field__label">Connector</span>
              <select
                className="hive-control xdlv-select"
                data-testid="registry-connector"
                value={draft.connectorId}
                onChange={(event) => update({ connectorId: event.target.value })}
              >
                <option value="">Choose a connector…</option>
                {connectors.map((connector) => (
                  <option key={connector.id} value={connector.id}>
                    {connector.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="xdlv-field">
              <span className="xdlv-field__label">Subjects</span>
              <select
                className="hive-control xdlv-select"
                data-testid="registry-naming"
                value={draft.subjectNaming}
                onChange={(event) => update({ subjectNaming: event.target.value as SubjectNaming })}
              >
                {(Object.keys(SUBJECT_NAMING_LABELS) as SubjectNaming[]).map((naming) => (
                  <option key={naming} value={naming}>
                    {SUBJECT_NAMING_LABELS[naming]}
                  </option>
                ))}
              </select>
            </label>
            {draft.subjectNaming !== 'record_name' ? (
              <label className="xdlv-field">
                <span className="xdlv-field__label">Topic</span>
                <input
                  className="hive-control xdlv-select"
                  data-testid="registry-topic"
                  value={draft.topic}
                  onChange={(event) => update({ topic: event.target.value })}
                />
              </label>
            ) : null}
            <label className="xdlv-field">
              <span className="xdlv-field__label">Role</span>
              <select
                className="hive-control xdlv-select"
                data-testid="registry-role"
                value={draft.subjectRole}
                onChange={(event) => update({ subjectRole: event.target.value as 'value' | 'key' })}
              >
                <option value="value">Value (-value)</option>
                <option value="key">Key (-key)</option>
              </select>
            </label>
            <label className="xdlv-choice">
              <input
                type="checkbox"
                data-testid="registry-dry-run"
                checked={draft.dryRun}
                onChange={(event) => update({ dryRun: event.target.checked })}
              />
              <span className="xdlv-choice__name">Dry run</span>
              <span className="xdlv-choice__meta">check every subject, register nothing</span>
            </label>
          </div>
          <div className="xdlv-job__now">
            <Button
              size="sm"
              variant="outline"
              data-testid="registry-push"
              disabled={problem !== null || pushing}
              title={problem ?? undefined}
              onClick={() => void push()}
            >
              {pushing ? 'Pushing…' : draft.dryRun ? 'Check against registry' : 'Push to registry'}
            </Button>
          </div>
        </>
      )}

      {error ? (
        <p className="xdlv-job__error" role="alert">
          {error}
        </p>
      ) : null}

      {result ? (
        <div data-testid="registry-result">
          <p className="xdlv-quiet">
            {result.dry_run ? 'Checked against' : 'Pushed to'} <span className="mono">{result.registry_url}</span>
          </p>
          <ul className="xdlv-attempts" aria-label="Registry subjects">
            {result.subjects.map((subject) => {
              const status = subjectStatus(subject.status);
              const where = subjectWhere(subject);
              return (
                <li key={subject.subject} className="xdlv-attempt" data-testid="registry-subject">
                  <div className="xdlv-attempt__head">
                    <Badge variant={status.tone}>{status.label}</Badge>
                    <span className="xdlv-attempt__channel mono">{subject.subject}</span>
                    {where ? <span className="xdlv-attempt__status mono">{where}</span> : null}
                  </div>
                  <div className="xdlv-attempt__meta">
                    <span className="mono">{subject.file}</span>
                  </div>
                  {subject.messages && subject.messages.length > 0 ? (
                    <p className="xdlv-attempt__error">{subject.messages.join(' ')}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

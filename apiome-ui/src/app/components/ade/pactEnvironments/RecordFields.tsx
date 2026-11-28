'use client';

/**
 * The **Service**, **Version** and **Environment** fields that Record a deployment and Record a
 * release share — PFX-8.12 (#7309).
 *
 * **Service** lists the workspace's pacticipants (the first page of 50; a note says when there are
 * more). **Version** is typed, with the chosen service's latest recorded versions offered as you
 * type — REST records only a version it already knows. **Environment** lists the topology's
 * environments.
 */

import * as React from 'react';
import { FormField, Input } from '@/app/components/ui';
import type { Pacticipant, PacticipantVersion } from '@lib/pact-pacticipants';
import type { RecordForm } from '@lib/pact-environment-writes';
import type { TopologyEnvironment } from '@lib/pact-environments';
import { fetchPacticipants, fetchVersions } from '../pactPacticipants/pacticipantsApi';

/** A list being read, read, or refused. */
export type Loadable<T> = { state: 'loading' } | { state: 'ready'; items: T[]; more: boolean } | { state: 'error'; error: string };

/**
 * The pacticipants, read once the dialog opens.
 *
 * @param open - Whether the dialog is open.
 * @param initial - Pacticipants to use without reading them (fixture renders).
 * @returns The list.
 */
export function usePacticipantChoices(open: boolean, initial?: Pacticipant[]): Loadable<Pacticipant> {
  const [list, setList] = React.useState<Loadable<Pacticipant>>(
    initial ? { state: 'ready', items: initial, more: false } : { state: 'loading' },
  );
  React.useEffect(() => {
    if (!open || initial) return;
    let live = true;
    fetchPacticipants()
      .then((page) => live && setList({ state: 'ready', items: page.pacticipants, more: Boolean(page.next_cursor) }))
      .catch((caught: unknown) =>
        live && setList({ state: 'error', error: caught instanceof Error ? caught.message : 'Could not load the services' }),
      );
    return () => {
      live = false;
    };
  }, [initial, open]);
  return list;
}

/**
 * The latest recorded versions of one service.
 *
 * @param slug - The service's handle, or empty for none chosen.
 * @param initial - Versions to use without reading them (fixture renders).
 * @returns The list (empty and ready while no service is chosen).
 */
export function useVersionChoices(slug: string, initial?: PacticipantVersion[]): Loadable<PacticipantVersion> {
  const [list, setList] = React.useState<Loadable<PacticipantVersion>>({ state: 'ready', items: initial ?? [], more: false });
  React.useEffect(() => {
    if (initial) return;
    if (!slug) {
      setList({ state: 'ready', items: [], more: false });
      return;
    }
    let live = true;
    setList({ state: 'loading' });
    fetchVersions(slug)
      .then((page) => live && setList({ state: 'ready', items: page.versions, more: Boolean(page.next_cursor) }))
      .catch((caught: unknown) =>
        live && setList({ state: 'error', error: caught instanceof Error ? caught.message : 'Could not load the versions' }),
      );
    return () => {
      live = false;
    };
  }, [initial, slug]);
  return list;
}

/** Props for {@link RecordFields}. */
export interface RecordFieldsProps {
  form: RecordForm;
  onChange: (patch: Partial<RecordForm>) => void;
  pacticipants: Loadable<Pacticipant>;
  versions: Loadable<PacticipantVersion>;
  environments: TopologyEnvironment[];
  /** Ids start with it, so two dialogs never share one. */
  idPrefix: string;
  disabled?: boolean;
}

/**
 * The three fields.
 *
 * @param props - See {@link RecordFieldsProps}.
 * @returns The fields.
 */
export function RecordFields({ form, onChange, pacticipants, versions, environments, idPrefix, disabled }: RecordFieldsProps) {
  const listId = `${idPrefix}-versions`;
  const serviceHint =
    pacticipants.state === 'error'
      ? pacticipants.error
      : pacticipants.state === 'ready' && pacticipants.more
        ? 'The first 50 services are listed.'
        : undefined;
  const versionHint =
    versions.state === 'error'
      ? versions.error
      : versions.state === 'loading'
        ? 'Reading the versions…'
        : versions.state === 'ready' && form.pacticipant && versions.items.length === 0
          ? 'No version of this service is recorded yet: publish a pact or a verification result first.'
          : 'A version already recorded: publishing a pact or a result records it.';
  return (
    <>
      <FormField label="Service" htmlFor={`${idPrefix}-service`} helperText={serviceHint}>
        <select
          id={`${idPrefix}-service`}
          className="ppx__select"
          value={form.pacticipant}
          disabled={disabled || pacticipants.state !== 'ready'}
          onChange={(event) => onChange({ pacticipant: event.target.value, version: '' })}
          data-testid={`${idPrefix}-service`}
        >
          <option value="">{pacticipants.state === 'loading' ? 'Reading the services…' : 'Choose a service'}</option>
          {pacticipants.state === 'ready'
            ? pacticipants.items.map((pacticipant) => (
                <option key={pacticipant.slug} value={pacticipant.slug}>
                  {pacticipant.name}
                </option>
              ))
            : null}
        </select>
      </FormField>
      <FormField label="Version" htmlFor={`${idPrefix}-version`} helperText={versionHint}>
        <Input
          id={`${idPrefix}-version`}
          className="ppx__mono"
          value={form.version}
          list={listId}
          autoComplete="off"
          disabled={disabled}
          onChange={(event) => onChange({ version: event.target.value })}
          data-testid={`${idPrefix}-version`}
        />
      </FormField>
      <datalist id={listId}>
        {versions.state === 'ready' ? versions.items.map((version) => <option key={version.id} value={version.number} />) : null}
      </datalist>
      <FormField label="Environment" htmlFor={`${idPrefix}-environment`}>
        <select
          id={`${idPrefix}-environment`}
          className="ppx__select"
          value={form.environment}
          disabled={disabled}
          onChange={(event) => onChange({ environment: event.target.value })}
          data-testid={`${idPrefix}-environment`}
        >
          <option value="">Choose an environment</option>
          {environments.map((environment) => (
            <option key={environment.uuid} value={environment.name}>
              {environment.displayName}
            </option>
          ))}
        </select>
      </FormField>
    </>
  );
}

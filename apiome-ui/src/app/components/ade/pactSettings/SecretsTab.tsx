'use client';

/**
 * **Settings → Secrets** — PFX-8.15 (#7312), built to `docs/mockups/contracts/settings.html`.
 *
 * Values that webhooks and verification targets need, write-only: a value is never shown again, and
 * no route returns one. The table lists each secret with what uses it and when its value was set; a
 * secret `apiome pact migrate` created for a value the source redacted reads **No value** — its
 * webhooks are off until **Set value**, which turns them on. **New secret** is the tab's one primary;
 * **Replace value** rotates a value; **Delete** is blocked while anything uses the secret, with the
 * list of what does.
 *
 * Without the Contracts admin permission the tab is read-only and says so once.
 */

import * as React from 'react';
import { KeyRound, Plus, Trash2 } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, CommandBlock, EmptyState, LoadingState } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { pactCommandSurfaces, tenantPath, unsupportedLines } from '@lib/pact-commands';
import {
  SECRETS_PROXY_PATH,
  SECRET_NAME,
  blockers,
  checkValue,
  inUse,
  usedByText,
  type SecretRecord,
} from '@lib/pact-contract-settings';
import { formatWhen } from '@lib/pact-pacticipants';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { createSecret, deleteSecret, fetchContractSettings, fetchSecrets, setSecretValue } from './contractSettingsApi';
import { ReadOnlyNote } from './ReadOnlyNote';

/** Why the block shows only REST: no `apiome pact` command manages secrets. */
export const SECRETS_HAVE_NO_COMMAND =
  'No apiome pact command manages workspace secrets (Pact CLI has none either); use this tab or the REST request.';

/** What the open dialog is for. */
type Draft = { kind: 'new' } | { kind: 'value'; secret: SecretRecord } | { kind: 'delete'; secret: SecretRecord };

/**
 * **New secret** / **Replace value** / **Set value**.
 *
 * @param props - The secret whose value is replaced (none for a new one), and what saving does.
 * @returns The dialog.
 */
function SecretDialog({
  secret,
  onSaved,
  onClose,
}: {
  secret: SecretRecord | null;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [name, setName] = React.useState('');
  const [value, setValue] = React.useState('');
  const [description, setDescription] = React.useState(secret?.description ?? '');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const title = secret ? (secret.has_value ? `Replace the value of ${secret.name}` : `Set the value of ${secret.name}`) : 'New secret';

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!secret && !SECRET_NAME.test(name.trim())) {
      setError('A name starts with a letter, then letters, digits or _ (64 at most).');
      return;
    }
    const problem = checkValue(value);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (secret) await setSecretValue(secret.id, value, secret.description);
      else await createSecret({ name: name.trim(), value, ...(description.trim() ? { description: description.trim() } : {}) });
      onSaved();
    } catch (caught) {
      setError(describeFailure(caught, 'Could not save the secret'));
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent data-testid="psx-secret-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {secret
              ? secret.has_value
                ? 'Every webhook and verification target that uses it sends the new value from its next run.'
                : 'Its webhooks are turned on once every secret they use has a value.'
              : 'Reference it from a webhook as ${user.<name>}, or pick it as a verification target’s sign-in.'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <DialogBody>
            <div className="prx-form">
              {!secret ? (
                <>
                  <div className="pmx-field">
                    <label className="ppx__field-label" htmlFor="psx-name">
                      Name
                    </label>
                    <input
                      id="psx-name"
                      className="pmx-input pcx-mono"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      placeholder="billing_staging_token"
                      autoComplete="off"
                      disabled={busy}
                    />
                  </div>
                  <div className="pmx-field">
                    <label className="ppx__field-label" htmlFor="psx-description">
                      Description (optional)
                    </label>
                    <input
                      id="psx-description"
                      className="pmx-input"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      disabled={busy}
                    />
                  </div>
                </>
              ) : null}
              <div className="pmx-field">
                <label className="ppx__field-label" htmlFor="psx-value">
                  Value
                </label>
                <input
                  id="psx-value"
                  className="pmx-input"
                  type="password"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  autoComplete="new-password"
                  aria-describedby="psx-value-hint"
                  disabled={busy}
                />
                <span id="psx-value-hint" className="ppx__muted">
                  Stored encrypted. You will not be able to read it back.
                </span>
              </div>
              {error ? (
                <p className="ppx__error" role="alert" data-testid="psx-secret-error">
                  {error}
                </p>
              ) : null}
            </div>
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="psx-secret-save">
              {busy ? 'Saving…' : secret ? (secret.has_value ? 'Replace value' : 'Set value') : 'Save secret'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * **Delete** — or why it cannot be deleted yet.
 *
 * @param props - The secret, and what deleting does.
 * @returns The dialog.
 */
function DeleteDialog({ secret, onDeleted, onClose }: { secret: SecretRecord; onDeleted: () => void; onClose: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const using = blockers(secret);
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteSecret(secret.id);
      onDeleted();
    } catch (caught) {
      setError(describeFailure(caught, 'Could not delete the secret'));
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent data-testid="psx-delete-dialog">
        <DialogHeader>
          <DialogTitle>{using.length ? `${secret.name} is in use` : `Delete ${secret.name}?`}</DialogTitle>
          <DialogDescription>
            {using.length
              ? 'A secret cannot be deleted while anything uses it. Change these first:'
              : 'Nothing uses it. Its value is gone for good once deleted.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {using.length ? (
            <ul className="psx-blockers" data-testid="psx-blockers">
              {using.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
          {error ? (
            <p className="ppx__error" role="alert" data-testid="psx-delete-error">
              {error}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            {using.length ? 'Close' : 'Cancel'}
          </Button>
          {!using.length ? (
            <Button variant="danger" onClick={() => void remove()} disabled={busy} data-testid="psx-delete-confirm">
              {busy ? 'Deleting…' : 'Delete secret'}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The Secrets tab.
 *
 * @returns The tab's content.
 */
export default function SecretsTab() {
  const [secrets, setSecrets] = React.useState<SecretRecord[] | null>(null);
  const [limit, setLimit] = React.useState<number | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [canEdit, setCanEdit] = React.useState<boolean | null>(null);
  const [draft, setDraft] = React.useState<Draft | null>(null);

  const load = React.useCallback(async () => {
    setSecrets(null);
    setError(null);
    try {
      const list = await fetchSecrets();
      setSecrets(list.secrets);
      setLimit(list.limit);
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the secrets'));
    }
  }, []);

  React.useEffect(() => {
    void load();
    fetchContractSettings()
      .then((settings) => setCanEdit(settings.can_edit))
      .catch(() => setCanEdit(false));
  }, [load]);

  const readOnly = canEdit !== true;
  const waiting = (secrets ?? []).filter((secret) => !secret.has_value);
  const action = {
    verb: null,
    noCommandReason: SECRETS_HAVE_NO_COMMAND,
    rest: {
      method: 'POST',
      path: tenantPath('', `/${SECRETS_PROXY_PATH}`),
      body: { name: 'billing_staging_token', value: '$SECRET_VALUE', description: 'Staging sign-in' },
    },
  };

  return (
    <div className="pcx" data-testid="pact-settings-secrets">
      {canEdit === false ? <ReadOnlyNote /> : null}
      {waiting.length ? (
        <div className="pcx-callout pcx-callout--warn" role="status" data-testid="psx-waiting">
          {waiting.length === 1
            ? `${waiting[0].name} has no value yet: a migrated webhook waits for it, turned off. Set its value to turn the webhook on.`
            : `${waiting.length} secrets have no value yet: migrated webhooks wait for them, turned off. Set their values to turn the webhooks on.`}
        </div>
      ) : null}
      <div className="pcx-split">
        <div className="pcx-split__main">
          <Panel
            id="psx-secrets"
            title="Secrets"
            aside={
              !readOnly ? (
                <Button
                  size="sm"
                  onClick={() => setDraft({ kind: 'new' })}
                  disabled={limit !== null && secrets !== null && secrets.length >= limit}
                  data-testid="psx-new"
                >
                  <Plus aria-hidden />
                  New secret
                </Button>
              ) : undefined
            }
          >
            <p className="ppx__muted">
              Values that webhooks and verification targets need. Write-only: a value is never shown again.
            </p>
            {error ? (
              <SectionError title="The secrets could not be read" error={error} onRetry={() => void load()} />
            ) : secrets === null ? (
              <LoadingState message="Reading the secrets…" minHeightClassName="min-h-[4rem]" />
            ) : secrets.length === 0 ? (
              <EmptyState
                icon={<KeyRound aria-hidden />}
                title="No secrets yet"
                description="Keep a token once; refer to it from webhooks and verification targets."
                data-testid="psx-empty"
              />
            ) : (
              <div className="ppx__table-wrap">
                <table className="ppx__table" data-testid="psx-table">
                  <caption className="sr-only">Workspace secrets</caption>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Used by</th>
                      <th scope="col">Updated</th>
                      {!readOnly ? (
                        <th scope="col">
                          <span className="sr-only">Actions</span>
                        </th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {secrets.map((secret) => (
                      <tr key={secret.id} data-testid={`psx-secret-${secret.name}`}>
                        <td>
                          <span className="pcx-mono">{secret.name}</span>{' '}
                          {!secret.has_value ? <Badge variant="warning">No value</Badge> : null}
                          {secret.description ? <div className="ppx__muted">{secret.description}</div> : null}
                        </td>
                        <td>{usedByText(secret)}</td>
                        <td className="ppx__muted">
                          {secret.has_value
                            ? formatWhen(secret.value_updated_at ?? secret.updated_at ?? null)
                            : secret.origin === 'migration'
                              ? 'From migration'
                              : '—'}
                        </td>
                        {!readOnly ? (
                          <td className="pcx-table__actions">
                            <span className="psx-actions">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setDraft({ kind: 'value', secret })}
                                data-testid={`psx-value-${secret.name}`}
                              >
                                {secret.has_value ? 'Replace value' : 'Set value'}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setDraft({ kind: 'delete', secret })}
                                aria-label={`Delete ${secret.name}`}
                                title={inUse(secret) ? 'In use: see what uses it' : undefined}
                                data-testid={`psx-delete-${secret.name}`}
                              >
                                <Trash2 aria-hidden />
                              </Button>
                            </span>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
        <aside className="pcx-split__aside" aria-label="Secrets from anywhere">
          <section className="ppx__panel" aria-labelledby="psx-command-title">
            <h2 id="psx-command-title" className="pcx-caps">
              The same, from anywhere
            </h2>
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              defaultSurface="rest"
              unsupported={unsupportedLines(action)}
              footnote="Replace {tenant} with your workspace’s handle. Send the value from a variable, never in a script."
              data-testid="psx-command-block"
            />
          </section>
        </aside>
      </div>
      {draft?.kind === 'new' || draft?.kind === 'value' ? (
        <SecretDialog
          secret={draft.kind === 'value' ? draft.secret : null}
          onClose={() => setDraft(null)}
          onSaved={() => {
            setDraft(null);
            void load();
          }}
        />
      ) : null}
      {draft?.kind === 'delete' ? (
        <DeleteDialog
          secret={draft.secret}
          onClose={() => setDraft(null)}
          onDeleted={() => {
            setDraft(null);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

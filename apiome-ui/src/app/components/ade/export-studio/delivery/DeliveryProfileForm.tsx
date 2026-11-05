'use client';

import { useMemo, useState, type FormEvent } from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';

import type { ReferenceOption } from './deliveryProfilesApi';
import {
  CHANNEL_LABELS,
  DELIVERY_CHANNELS,
  PARTITIONS,
  SECRET_MIN_CHARS,
  validateDraft,
  type DeliveryChannel,
  type DeliveryProfileDraft,
  type Partition,
} from './deliveryProfilesModel';

/** Props for {@link DeliveryProfileForm}. */
export interface DeliveryProfileFormProps {
  /** The draft to start from: blank for a new profile, the profile's for an edit. */
  initial: DeliveryProfileDraft;
  /** Whether this creates a profile (the channel can be chosen and a webhook needs its secret). */
  creating: boolean;
  /** The workspace's registered repositories, for a git profile. */
  repositories: ReferenceOption[];
  /** The workspace's bucket credentials, for an object-storage profile. */
  credentials: ReferenceOption[];
  /** Whether a save is in flight. */
  saving: boolean;
  /** The server's refusal, with every problem it listed. */
  serverError: { message: string; errors: string[] } | null;
  /** Save the draft. */
  onSubmit: (draft: DeliveryProfileDraft) => void;
  /** Close the form without saving. */
  onCancel: () => void;
}

/**
 * The create / edit form for one delivery profile (MFX-38.4, #4331).
 *
 * A new profile picks its channel; an edit cannot change it (the REST layer refuses). Each channel
 * shows only its own fields. A webhook's signing secret is a password field: required on create,
 * and on an edit left blank to keep the stored secret, which is never shown. Problems are checked
 * here first (the same rules the API applies) so every bad field is listed before a round trip.
 *
 * @param props See {@link DeliveryProfileFormProps}.
 * @returns The form.
 */
export function DeliveryProfileForm({
  initial,
  creating,
  repositories,
  credentials,
  saving,
  serverError,
  onSubmit,
  onCancel,
}: DeliveryProfileFormProps) {
  const [draft, setDraft] = useState<DeliveryProfileDraft>(initial);
  const [attempted, setAttempted] = useState(false);
  const problems = useMemo(() => validateDraft(draft, creating, creating ? undefined : initial), [draft, creating, initial]);

  const set = <K extends 'git' | 'webhook' | 'objectStorage'>(
    block: K,
    patch: Partial<DeliveryProfileDraft[K]>,
  ) => setDraft((current) => ({ ...current, [block]: { ...current[block], ...patch } }));

  const togglePartition = (part: Partition, on: boolean) =>
    set('objectStorage', {
      partitioning: on
        ? PARTITIONS.filter((p) => p === part || draft.objectStorage.partitioning.includes(p))
        : draft.objectStorage.partitioning.filter((p) => p !== part),
    });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setAttempted(true);
    if (problems.length === 0) onSubmit(draft);
  };

  const shownProblems = serverError ? serverError.errors : attempted ? problems : [];

  return (
    <form className="xdlv-form" onSubmit={submit} aria-label={creating ? 'New delivery profile' : 'Edit delivery profile'} noValidate>
      {serverError || (attempted && problems.length > 0) ? (
        <Alert variant="danger">
          {serverError?.message ?? 'Fix these before saving:'}
          {shownProblems.length > 0 ? (
            <ul className="xdlv-problems">
              {shownProblems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}

      <div className="xdlv-field">
        <Label htmlFor="xdlv-name">Name</Label>
        <Input
          id="xdlv-name"
          value={draft.name}
          maxLength={120}
          placeholder="orders-to-data-lake"
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
        />
      </div>
      <div className="xdlv-field">
        <Label htmlFor="xdlv-description">Description</Label>
        <Input
          id="xdlv-description"
          value={draft.description}
          placeholder="What this destination is for"
          onChange={(event) => setDraft({ ...draft, description: event.target.value })}
        />
      </div>

      <fieldset className="xdlv-field" disabled={!creating}>
        <legend className="xdlv-legend">Channel</legend>
        <div className="xdlv-channels" role="radiogroup" aria-label="Channel">
          {DELIVERY_CHANNELS.map((channel: DeliveryChannel) => (
            <label key={channel} className="xdlv-channel" data-selected={draft.channel === channel}>
              <input
                type="radio"
                name="xdlv-channel"
                value={channel}
                checked={draft.channel === channel}
                onChange={() => setDraft({ ...draft, channel })}
              />
              {CHANNEL_LABELS[channel]}
            </label>
          ))}
        </div>
        {!creating ? <p className="xdlv-hint">A profile&apos;s channel can&apos;t change.</p> : null}
      </fieldset>

      {draft.channel === 'git' ? (
        <div className="xdlv-group" data-testid="xdlv-git-fields">
          <div className="xdlv-field">
            <Label htmlFor="xdlv-repository">Repository</Label>
            <select
              id="xdlv-repository"
              className="hive-control xdlv-select"
              value={draft.git.repositoryId}
              onChange={(event) => set('git', { repositoryId: event.target.value })}
            >
              <option value="">Choose a repository…</option>
              {repositories.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.label}
                </option>
              ))}
            </select>
            {repositories.length === 0 ? (
              <p className="xdlv-hint">No repositories are registered yet. Add one under Repositories first.</p>
            ) : null}
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-path">Path</Label>
            <Input id="xdlv-path" value={draft.git.targetPath} placeholder="specs/orders"
              onChange={(event) => set('git', { targetPath: event.target.value })} />
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-base-branch">Base branch</Label>
            <Input id="xdlv-base-branch" value={draft.git.baseBranch} placeholder="The repository's default branch"
              onChange={(event) => set('git', { baseBranch: event.target.value })} />
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-mode">Mode</Label>
            <select id="xdlv-mode" className="hive-control xdlv-select" value={draft.git.mode}
              onChange={(event) => set('git', { mode: event.target.value === 'commit' ? 'commit' : 'pr' })}>
              <option value="pr">Pull request</option>
              <option value="commit">Direct commit</option>
            </select>
          </div>
        </div>
      ) : null}

      {draft.channel === 'webhook' ? (
        <div className="xdlv-group" data-testid="xdlv-webhook-fields">
          <div className="xdlv-field">
            <Label htmlFor="xdlv-url">Receiver URL</Label>
            <Input id="xdlv-url" type="url" value={draft.webhook.url} placeholder="https://ci.example.com/hooks/apiome"
              onChange={(event) => set('webhook', { url: event.target.value })} />
            {!creating ? (
              <p className="xdlv-hint">Leave it blank to keep the stored URL; enter it again to change it.</p>
            ) : null}
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-secret">Signing secret</Label>
            <Input id="xdlv-secret" type="password" autoComplete="new-password" value={draft.webhook.secret}
              placeholder={creating ? `At least ${SECRET_MIN_CHARS} characters` : 'Leave blank to keep the stored secret'}
              onChange={(event) => set('webhook', { secret: event.target.value })} />
            <p className="xdlv-hint">Sealed when saved and never shown again.</p>
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-artifact">Bundle</Label>
            <select id="xdlv-artifact" className="hive-control xdlv-select" value={draft.webhook.artifact}
              onChange={(event) => set('webhook', { artifact: event.target.value === 'fetch' ? 'fetch' : 'auto' })}>
              <option value="auto">Inline when small, else a signed link</option>
              <option value="fetch">Always a signed link</option>
            </select>
          </div>
        </div>
      ) : null}

      {draft.channel === 'object_storage' ? (
        <div className="xdlv-group" data-testid="xdlv-storage-fields">
          <div className="xdlv-field">
            <Label htmlFor="xdlv-credential">Storage credential</Label>
            <select id="xdlv-credential" className="hive-control xdlv-select" value={draft.objectStorage.credentialId}
              onChange={(event) => set('objectStorage', { credentialId: event.target.value })}>
              <option value="">Choose a credential…</option>
              {credentials.map((credential) => (
                <option key={credential.id} value={credential.id}>
                  {credential.label}
                </option>
              ))}
            </select>
            {credentials.length === 0 ? (
              <p className="xdlv-hint">No bucket credentials are stored yet. Store one with the REST API first.</p>
            ) : null}
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-bucket">Bucket</Label>
            <Input id="xdlv-bucket" value={draft.objectStorage.bucket} placeholder="data-lake"
              onChange={(event) => set('objectStorage', { bucket: event.target.value })} />
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xdlv-prefix">Prefix</Label>
            <Input id="xdlv-prefix" value={draft.objectStorage.prefix} placeholder="exports/apis"
              onChange={(event) => set('objectStorage', { prefix: event.target.value })} />
          </div>
          <fieldset className="xdlv-field">
            <legend className="xdlv-legend">Partitions</legend>
            <div className="xdlv-channels">
              {PARTITIONS.map((part) => (
                <label key={part} className="xdlv-channel" data-selected={draft.objectStorage.partitioning.includes(part)}>
                  <input type="checkbox" checked={draft.objectStorage.partitioning.includes(part)}
                    onChange={(event) => togglePartition(part, event.target.checked)} />
                  {part}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      ) : null}

      <div className="xdlv-form__actions">
        <Button title={saving ? 'Wait for the save to finish' : undefined} type="button" variant="outline" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button title={saving ? 'Saving the delivery profile' : undefined} type="submit" disabled={saving} data-testid="xdlv-save">
          {creating ? 'Create profile' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}

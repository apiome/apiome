'use client';

/**
 * The manage drawer's **Document storage** section — COA-5.15 (#7092).
 *
 * Where the workspace's originals and rendered documents are kept:
 *
 * - **Platform storage** — the install's own store (the default).
 * - **Your own bucket** — an S3-compatible bucket the workspace owns, reached with a storage
 *   credential. The form names the bucket and, when needed, its folder, region, endpoint,
 *   addressing style and server-side encryption.
 *
 * **Test bucket** writes, reads back and deletes one probe object with the values on screen, saved
 * or not. Saving a different choice starts a move of the existing documents; the section shows its
 * progress and keeps polling while it runs. After a move, the copies left in the old place are
 * deleted only from the **Delete old copies** confirmation.
 *
 * A key is typed once, in **Add a credential**, and sent straight to REST, which seals it. Nothing
 * this section reads back contains one. Everything needs `document_store:manage` (REST enforces
 * it), and the section reads the session's current tenant, like the Security and MCP sections.
 */

import * as React from 'react';
import { Lock } from 'lucide-react';
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Label,
  LoadingState,
  RadioGroup,
  RadioGroupItem,
} from '@/app/components/ui';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/app/components/ui/AlertDialog';
import { Progress } from '@/app/components/ui/metrics';
import {
  DOCUMENT_STORE_MODE_LABELS,
  draftFromStore,
  isDraftDirty,
  movePercent,
  moveSummary,
  validateDraft,
  type DocumentStoreAddressing,
  type DocumentStoreMode,
  type DocumentStoreSse,
  type StorageCredentialInput,
  type StorageCredentialOption,
  type TenantDocumentStore,
  type TenantDocumentStoreDraft,
  type TenantDocumentStoreProbe,
} from '@lib/tenant-document-store';
import { cn } from '@lib/utils';
import {
  cleanupTenantDocumentStore,
  createStorageCredential,
  fetchStorageCredentials,
  fetchTenantDocumentStore,
  saveTenantDocumentStore,
  testTenantDocumentStore,
} from './tenantDocumentStoreApi';

/** How often the section re-reads the settings while a move runs. */
const POLL_MS = 3000;

/** The empty **Add a credential** form. */
const EMPTY_CREDENTIAL: StorageCredentialInput = {
  name: '',
  accessKeyId: '',
  secretAccessKey: '',
  endpointUrl: '',
  region: 'us-east-1',
  forcePathStyle: false,
};

/** The names of the three test steps, as the result list reads. */
const STEP_LABELS = { write: 'Write a test object', read: 'Read it back', delete: 'Delete it' } as const;

/** Props for {@link TenantDocumentStorageSection}. */
export interface TenantDocumentStorageSectionProps {
  /** Whether the reader administers the tenant; others see the settings read-only. */
  isAdmin: boolean;
  /** Reports unsaved changes, so the drawer can mark the tab. */
  onDirtyChange?: (dirty: boolean) => void;
}

/** @returns The message of a caught error, or `fallback`. */
function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

/**
 * The Document storage section.
 *
 * @param props - See {@link TenantDocumentStorageSectionProps}.
 * @returns The choice, the bucket form, the test, the move and the cleanup.
 */
export default function TenantDocumentStorageSection({ isAdmin, onDirtyChange }: TenantDocumentStorageSectionProps) {
  const [store, setStore] = React.useState<TenantDocumentStore | null>(null);
  const [draft, setDraft] = React.useState<TenantDocumentStoreDraft | null>(null);
  const [credentials, setCredentials] = React.useState<StorageCredentialOption[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [probe, setProbe] = React.useState<TenantDocumentStoreProbe | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [credential, setCredential] = React.useState<StorageCredentialInput>(EMPTY_CREDENTIAL);
  const [credentialError, setCredentialError] = React.useState<string | null>(null);
  const [storingCredential, setStoringCredential] = React.useState(false);
  const [confirmingCleanup, setConfirmingCleanup] = React.useState(false);
  const [cleaning, setCleaning] = React.useState(false);
  const [cleaned, setCleaned] = React.useState<number | null>(null);

  const adopt = React.useCallback((next: TenantDocumentStore) => {
    setStore(next);
    setDraft(draftFromStore(next));
  }, []);

  React.useEffect(() => {
    let live = true;
    fetchTenantDocumentStore()
      .then((next) => live && adopt(next))
      .catch((caught: unknown) => live && setError(messageOf(caught, 'Could not load document storage')));
    fetchStorageCredentials()
      .then((next) => live && setCredentials(next))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [adopt]);

  // While a move runs, keep its progress current without touching what the reader is editing.
  const moving = store?.move.state === 'running';
  React.useEffect(() => {
    if (!moving) return undefined;
    const timer = window.setInterval(() => {
      fetchTenantDocumentStore()
        .then((next) => (next.move.state === 'running' ? setStore(next) : adopt(next)))
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [moving, adopt]);

  const dirty = store !== null && draft !== null && isDraftDirty(draft, store);
  React.useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const change = <K extends keyof TenantDocumentStoreDraft>(key: K, value: TenantDocumentStoreDraft[K]) => {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
    setProbe(null);
  };

  const errors = draft ? validateDraft(draft) : {};
  const valid = Object.keys(errors).length === 0;
  const readOnly = !isAdmin || saving || moving;
  // Documents are in the saved bucket: where it is cannot change until they are moved back.
  const locationLocked = store !== null && (store.mode === 'tenant' || store.cleanupPending);
  const modeChanges = store !== null && draft !== null && draft.mode !== store.mode;

  const save = async () => {
    if (!draft || !valid) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    setCleaned(null);
    try {
      adopt(await saveTenantDocumentStore(draft));
      setSaved(true);
    } catch (caught) {
      setError(messageOf(caught, 'Could not save document storage'));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!draft) return;
    setTesting(true);
    setProbe(null);
    setError(null);
    try {
      setProbe(await testTenantDocumentStore(draft));
    } catch (caught) {
      setError(messageOf(caught, 'Could not test the bucket'));
    } finally {
      setTesting(false);
    }
  };

  const storeCredential = async () => {
    setStoringCredential(true);
    setCredentialError(null);
    try {
      const created = await createStorageCredential(credential);
      setCredentials((current) => [...current.filter((item) => item.id !== created.id), created]);
      change('credentialId', created.id);
      setCredential(EMPTY_CREDENTIAL);
      setAdding(false);
    } catch (caught) {
      setCredentialError(messageOf(caught, 'Could not store the credential'));
    } finally {
      setStoringCredential(false);
    }
  };

  const cleanup = async () => {
    setCleaning(true);
    setError(null);
    try {
      const result = await cleanupTenantDocumentStore();
      setCleaned(result.deleted);
      adopt(await fetchTenantDocumentStore());
    } catch (caught) {
      setError(messageOf(caught, 'Could not delete the old copies'));
    } finally {
      setCleaning(false);
      setConfirmingCleanup(false);
    }
  };

  const credentialReady =
    credential.name.trim() !== '' && credential.accessKeyId.trim() !== '' && credential.secretAccessKey !== '';
  const summary = store ? moveSummary(store.move) : null;
  const offered = store !== null && (store.allowed || store.bucket !== null);

  return (
    <section aria-labelledby="tnt-storage-heading" className="space-y-4" data-testid="tenant-document-storage">
      <div className="min-w-0">
        <h3 id="tnt-storage-heading" className="tnt-section-title">
          Document storage
        </h3>
        <p className="tnt-section-desc">
          Where this workspace&apos;s imported originals and rendered documents are kept.
        </p>
      </div>

      {!isAdmin ? (
        <p className="tnt-lock-note">
          <Lock className="size-[var(--icon-dense)] shrink-0" aria-hidden />
          Only administrators can change document storage.
        </p>
      ) : null}
      {error ? <Alert variant="error">{error}</Alert> : null}

      {!store && !error ? (
        <LoadingState message="Loading document storage…" minHeightClassName="min-h-[8rem]" />
      ) : null}

      {store && !offered ? (
        <Alert variant="info" role="note" data-testid="tenant-storage-not-offered">
          This workspace&apos;s documents are kept in platform storage. Keeping them in your own bucket is not turned on
          for this installation; a platform administrator can turn it on.
        </Alert>
      ) : null}

      {store && draft && offered ? (
        <>
          {!store.allowed ? (
            <Alert variant="warn" role="note" data-testid="tenant-storage-frozen">
              Your own bucket is no longer offered on this installation. Documents already in your bucket keep working,
              but these settings cannot be changed.
            </Alert>
          ) : null}

          {!store.health.available ? (
            <Alert variant="error" data-testid="tenant-storage-unavailable">
              Your bucket is not answering. Documents kept there cannot be opened until it does; specs and diffs are
              still shown, rendered on demand. {store.health.error}
            </Alert>
          ) : null}

          <fieldset className="tnt-storage-field" disabled={readOnly || !store.allowed}>
            <legend className="hive-label">Keep documents in</legend>
            <RadioGroup
              value={draft.mode}
              onValueChange={(next) => change('mode', next as DocumentStoreMode)}
              className="tnt-storage-modes"
              aria-label="Keep documents in"
            >
              <RadioGroupItem
                value="platform"
                id="tnt-storage-mode-platform"
                data-testid="tenant-storage-mode-platform"
                className={cn('ver-radio-card', draft.mode === 'platform' && 'is-selected')}
                label={
                  <>
                    <span className="ver-radio-card__title">{DOCUMENT_STORE_MODE_LABELS.platform}</span>
                    <span className="ver-radio-card__desc">The storage this installation provides. Nothing to set up.</span>
                  </>
                }
              />
              <RadioGroupItem
                value="tenant"
                id="tnt-storage-mode-tenant"
                data-testid="tenant-storage-mode-tenant"
                className={cn('ver-radio-card', draft.mode === 'tenant' && 'is-selected')}
                label={
                  <>
                    <span className="ver-radio-card__title">{DOCUMENT_STORE_MODE_LABELS.tenant}</span>
                    <span className="ver-radio-card__desc">
                      An S3-compatible bucket you own, for your region, encryption keys and retention rules.
                    </span>
                  </>
                }
              />
            </RadioGroup>
          </fieldset>

          {draft.mode === 'tenant' ? (
            <fieldset className="tnt-storage-form" disabled={readOnly || !store.allowed} data-testid="tenant-storage-form">
              <legend className="sr-only">Your bucket</legend>

              <div className="tnt-storage-field tnt-storage-field--wide">
                <Label htmlFor="tnt-storage-credential" className="hive-label">
                  Storage credential
                </Label>
                <div className="tnt-storage-inline">
                  <select
                    id="tnt-storage-credential"
                    className="hive-control xdlv-select"
                    value={draft.credentialId}
                    aria-invalid={Boolean(errors.credentialId)}
                    onChange={(event) => change('credentialId', event.target.value)}
                    data-testid="tenant-storage-credential"
                  >
                    <option value="">Choose a credential…</option>
                    {credentials.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name} (…{option.accessKeyHint})
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setAdding((open) => !open)}
                    aria-expanded={adding}
                    data-testid="tenant-storage-add-credential"
                  >
                    Add a credential
                  </Button>
                </div>
                <p className="tnt-section-desc">The access key Apiome uses to read and write your bucket.</p>
              </div>

              {adding ? (
                <div className="tnt-card tnt-card--pad tnt-storage-form tnt-storage-field--wide" data-testid="tenant-storage-credential-form">
                  {credentialError ? (
                    <Alert variant="error" className="tnt-storage-field--wide">
                      {credentialError}
                    </Alert>
                  ) : null}
                  <div className="tnt-storage-field">
                    <Label htmlFor="tnt-credential-name" className="hive-label">
                      Name
                    </Label>
                    <Input
                      id="tnt-credential-name"
                      value={credential.name}
                      placeholder="documents-bucket"
                      onChange={(event) => setCredential({ ...credential, name: event.target.value })}
                      data-testid="tenant-credential-name"
                    />
                  </div>
                  <div className="tnt-storage-field">
                    <Label htmlFor="tnt-credential-region" className="hive-label">
                      Region
                    </Label>
                    <Input
                      id="tnt-credential-region"
                      value={credential.region}
                      onChange={(event) => setCredential({ ...credential, region: event.target.value })}
                    />
                  </div>
                  <div className="tnt-storage-field">
                    <Label htmlFor="tnt-credential-access-key" className="hive-label">
                      Access key ID
                    </Label>
                    <Input
                      id="tnt-credential-access-key"
                      autoComplete="off"
                      value={credential.accessKeyId}
                      onChange={(event) => setCredential({ ...credential, accessKeyId: event.target.value })}
                      data-testid="tenant-credential-access-key"
                    />
                  </div>
                  <div className="tnt-storage-field">
                    <Label htmlFor="tnt-credential-secret" className="hive-label">
                      Secret access key
                    </Label>
                    <Input
                      id="tnt-credential-secret"
                      type="password"
                      autoComplete="new-password"
                      value={credential.secretAccessKey}
                      onChange={(event) => setCredential({ ...credential, secretAccessKey: event.target.value })}
                      data-testid="tenant-credential-secret"
                    />
                  </div>
                  <div className="tnt-storage-field tnt-storage-field--wide">
                    <Label htmlFor="tnt-credential-endpoint" className="hive-label">
                      Endpoint URL
                    </Label>
                    <Input
                      id="tnt-credential-endpoint"
                      value={credential.endpointUrl}
                      placeholder="Leave empty for AWS S3"
                      onChange={(event) => setCredential({ ...credential, endpointUrl: event.target.value })}
                    />
                  </div>
                  <div className="tnt-storage-inline tnt-storage-field--wide">
                    <Checkbox
                      id="tnt-credential-path-style"
                      checked={credential.forcePathStyle}
                      onCheckedChange={(next) => setCredential({ ...credential, forcePathStyle: next === true })}
                    />
                    <Label htmlFor="tnt-credential-path-style">Use path-style addressing (MinIO, Garage)</Label>
                  </div>
                  <p className="tnt-section-desc tnt-storage-field--wide">
                    The secret is stored encrypted and is never shown again.
                  </p>
                  <div className="tnt-storage-inline tnt-storage-field--wide">
                    <Button
                      type="button"
                      onClick={() => void storeCredential()}
                      disabled={!credentialReady || storingCredential}
                      title={credentialReady ? undefined : 'Enter a name, the access key ID and the secret access key first'}
                      data-testid="tenant-credential-store"
                    >
                      {storingCredential ? 'Storing…' : 'Store credential'}
                    </Button>
                    <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : null}

              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-bucket" className="hive-label">
                  Bucket
                </Label>
                <Input
                  id="tnt-storage-bucket"
                  value={draft.bucket}
                  disabled={locationLocked}
                  aria-invalid={Boolean(errors.bucket)}
                  aria-describedby="tnt-storage-bucket-hint"
                  onChange={(event) => change('bucket', event.target.value)}
                  data-testid="tenant-storage-bucket"
                />
                <p id="tnt-storage-bucket-hint" className="tnt-section-desc">
                  {errors.bucket ?? 'It must already exist.'}
                </p>
              </div>
              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-prefix" className="hive-label">
                  Folder
                </Label>
                <Input
                  id="tnt-storage-prefix"
                  value={draft.prefix}
                  disabled={locationLocked}
                  onChange={(event) => change('prefix', event.target.value)}
                  data-testid="tenant-storage-prefix"
                />
                <p className="tnt-section-desc">Apiome only writes under this folder. Empty writes at the root.</p>
              </div>
              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-region" className="hive-label">
                  Region
                </Label>
                <Input
                  id="tnt-storage-region"
                  value={draft.region}
                  placeholder="From the credential"
                  onChange={(event) => change('region', event.target.value)}
                />
              </div>
              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-endpoint" className="hive-label">
                  Endpoint URL
                </Label>
                <Input
                  id="tnt-storage-endpoint"
                  value={draft.endpointUrl}
                  disabled={locationLocked}
                  placeholder="From the credential"
                  aria-invalid={Boolean(errors.endpointUrl)}
                  onChange={(event) => change('endpointUrl', event.target.value)}
                />
                {errors.endpointUrl ? <p className="tnt-section-desc">{errors.endpointUrl}</p> : null}
              </div>
              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-addressing" className="hive-label">
                  Addressing style
                </Label>
                <select
                  id="tnt-storage-addressing"
                  className="hive-control xdlv-select"
                  value={draft.addressingStyle}
                  onChange={(event) => change('addressingStyle', event.target.value as DocumentStoreAddressing)}
                >
                  <option value="auto">Automatic</option>
                  <option value="path">Path-style</option>
                  <option value="virtual">Virtual-hosted</option>
                </select>
              </div>
              <div className="tnt-storage-field">
                <Label htmlFor="tnt-storage-sse" className="hive-label">
                  Encryption
                </Label>
                <select
                  id="tnt-storage-sse"
                  className="hive-control xdlv-select"
                  value={draft.sse}
                  onChange={(event) => change('sse', event.target.value as DocumentStoreSse)}
                  data-testid="tenant-storage-sse"
                >
                  <option value="">Bucket default</option>
                  <option value="s3">SSE-S3</option>
                  <option value="kms">SSE-KMS</option>
                </select>
              </div>
              {draft.sse === 'kms' ? (
                <div className="tnt-storage-field tnt-storage-field--wide">
                  <Label htmlFor="tnt-storage-kms" className="hive-label">
                    KMS key ID
                  </Label>
                  <Input
                    id="tnt-storage-kms"
                    value={draft.kmsKeyId}
                    placeholder="Empty uses the bucket's default key"
                    onChange={(event) => change('kmsKeyId', event.target.value)}
                    data-testid="tenant-storage-kms"
                  />
                </div>
              ) : null}

              {locationLocked ? (
                <p className="tnt-lock-note tnt-storage-field--wide" data-testid="tenant-storage-location-locked">
                  <Lock className="size-[var(--icon-dense)] shrink-0" aria-hidden />
                  Documents are stored in this bucket. To use a different bucket, folder or endpoint, move back to
                  platform storage and delete the old copies first.
                </p>
              ) : null}

              <div className="tnt-storage-inline tnt-storage-field--wide">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void test()}
                  disabled={!valid || testing}
                  title={valid ? undefined : 'Choose a credential and enter the bucket first'}
                  data-testid="tenant-storage-test"
                >
                  {testing ? 'Testing…' : 'Test bucket'}
                </Button>
                {probe ? (
                  <span className="tnt-section-desc" role="status" data-testid="tenant-storage-test-result">
                    {probe.ok ? 'The bucket passed: write, read and delete all worked.' : 'The bucket did not pass.'}
                  </span>
                ) : null}
              </div>
              {probe && !probe.ok ? (
                <ul className="tnt-storage-steps tnt-storage-field--wide" data-testid="tenant-storage-test-steps">
                  {probe.error ? <li data-ok="false">{probe.error}</li> : null}
                  {probe.steps.map((step) => (
                    <li key={step.name} data-ok={step.ok ? 'true' : 'false'}>
                      <span className="tnt-storage-steps__name">{STEP_LABELS[step.name]}</span>
                      <span>{step.ok ? 'Worked' : step.skipped ? 'Not run' : (step.error ?? 'Failed')}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </fieldset>
          ) : null}

          {summary ? (
            <div className="tnt-card tnt-card--pad space-y-2" data-testid="tenant-storage-move">
              <Progress
                value={movePercent(store.move)}
                label="Documents moved"
                tone={store.move.state === 'failed' ? 'warn' : store.move.state === 'completed' ? 'ok' : 'accent'}
                striped={store.move.state === 'running'}
              />
              <p className="tnt-section-desc" role="status">
                {summary}
              </p>
              {store.move.state === 'failed' && store.move.error ? (
                <p className="tnt-section-desc" data-testid="tenant-storage-move-error">
                  {store.move.error} Save again to retry.
                </p>
              ) : null}
            </div>
          ) : null}

          {store.cleanupPending && !moving ? (
            <Alert variant="info" role="note" data-testid="tenant-storage-cleanup">
              <span className="tnt-storage-cleanup">
                <span>
                  The moved documents still have a copy in {store.mode === 'tenant' ? 'platform storage' : 'your bucket'}.
                  They are no longer read from there.
                </span>
                {isAdmin && store.allowed ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setConfirmingCleanup(true)}
                    disabled={cleaning}
                    title={cleaning ? 'The old copies are being deleted' : undefined}
                    data-testid="tenant-storage-cleanup-open"
                  >
                    Delete old copies…
                  </Button>
                ) : null}
              </span>
            </Alert>
          ) : null}
          {cleaned !== null ? (
            <p className="tnt-section-desc" role="status" data-testid="tenant-storage-cleaned">
              Deleted {cleaned} old {cleaned === 1 ? 'copy' : 'copies'}.
            </p>
          ) : null}

          {isAdmin && store.allowed ? (
            <div className="flex items-center gap-3">
              <Button
                onClick={() => void save()}
                disabled={!dirty || !valid || saving || moving}
                title={
                  moving
                    ? 'Wait for the move to finish'
                    : !valid
                      ? 'Choose a credential and enter the bucket first'
                      : !dirty
                        ? 'Nothing has changed'
                        : undefined
                }
                data-testid="tenant-storage-save"
              >
                {saving ? 'Saving…' : modeChanges ? 'Save and move documents' : 'Save changes'}
              </Button>
              {saved ? (
                <span className="tnt-section-desc" role="status">
                  Saved.
                </span>
              ) : null}
              {modeChanges && !saving ? (
                <span className="tnt-section-desc">
                  New documents go to {draft.mode === 'tenant' ? 'your bucket' : 'platform storage'} at once; existing
                  ones are moved in the background.
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      <AlertDialog open={confirmingCleanup} onOpenChange={(open) => !cleaning && setConfirmingCleanup(open)}>
        <AlertDialogContent data-testid="tenant-storage-cleanup-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete old copies?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the copies of the moved documents from{' '}
              {store?.mode === 'tenant' ? 'platform storage' : 'your bucket'}. Documents that could not be moved are
              not touched. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              onClick={(event) => {
                event.preventDefault();
                void cleanup();
              }}
              data-testid="tenant-storage-cleanup-confirm-action"
            >
              {cleaning ? 'Deleting…' : 'Delete old copies'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

/**
 * A workspace's own bucket for the document store — COA-5.15 (#7092).
 *
 * The shapes `GET` / `PUT /v1/tenants/{slug}/document-store` answer with, and the pure helpers the
 * **Document storage** section draws from. No key or secret is ever part of these: a workspace's
 * bucket is reached with a storage credential that is named here by id only.
 */

/** Where new documents go: the install's store, or the workspace's own bucket. */
export type DocumentStoreMode = 'platform' | 'tenant';

/** How bucket names appear in request URLs. */
export type DocumentStoreAddressing = 'auto' | 'path' | 'virtual';

/** Server-side encryption: none, SSE-S3 or SSE-KMS. */
export type DocumentStoreSse = '' | 's3' | 'kms';

/** The move of existing documents to where they are kept now. */
export interface TenantDocumentStoreMove {
  state: 'idle' | 'running' | 'completed' | 'failed';
  target: DocumentStoreMode | null;
  total: number;
  moved: number;
  failed: number;
  error: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

/** A workspace's document storage settings, health and move progress. */
export interface TenantDocumentStore {
  /** Whether the install lets workspaces use their own bucket. */
  allowed: boolean;
  mode: DocumentStoreMode;
  credentialId: string | null;
  credentialName: string | null;
  bucket: string | null;
  prefix: string;
  region: string;
  endpointUrl: string;
  addressingStyle: DocumentStoreAddressing;
  sse: DocumentStoreSse;
  kmsKeyId: string;
  health: { available: boolean; unavailableSince: string | null; error: string | null };
  move: TenantDocumentStoreMove;
  /** A finished move left old copies that await an explicit confirm. */
  cleanupPending: boolean;
}

/** What the form edits and `PUT` / `test` receive. */
export interface TenantDocumentStoreDraft {
  mode: DocumentStoreMode;
  credentialId: string;
  bucket: string;
  prefix: string;
  region: string;
  endpointUrl: string;
  addressingStyle: DocumentStoreAddressing;
  sse: DocumentStoreSse;
  kmsKeyId: string;
}

/** One step of the bucket test. */
export interface TenantDocumentStoreProbeStep {
  name: 'write' | 'read' | 'delete';
  ok: boolean;
  skipped: boolean;
  durationMs: number;
  error: string | null;
}

/** The outcome of the bucket test. */
export interface TenantDocumentStoreProbe {
  ok: boolean;
  bucket: string | null;
  /** Why the test could not run at all (for example, the credential cannot be opened). */
  error: string | null;
  steps: TenantDocumentStoreProbeStep[];
}

/** A storage credential the workspace can choose. */
export interface StorageCredentialOption {
  id: string;
  name: string;
  accessKeyHint: string;
  endpointUrl: string | null;
  region: string;
}

/** What a new storage credential needs. The keys go to REST once and are never read back. */
export interface StorageCredentialInput {
  name: string;
  accessKeyId: string;
  secretAccessKey: string;
  endpointUrl: string;
  region: string;
  forcePathStyle: boolean;
}

/** S3 bucket naming: 3–63 lower-case letters, digits, dots or hyphens. */
const BUCKET_RE = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;

/** The labels of the two modes, as the section's radio cards read. */
export const DOCUMENT_STORE_MODE_LABELS: Readonly<Record<DocumentStoreMode, string>> = {
  platform: 'Platform storage',
  tenant: 'Your own bucket',
};

/**
 * The form's starting values for stored settings.
 *
 * @param store - The stored settings.
 * @returns The draft the form edits.
 */
export function draftFromStore(store: TenantDocumentStore): TenantDocumentStoreDraft {
  return {
    mode: store.mode,
    credentialId: store.credentialId ?? '',
    bucket: store.bucket ?? '',
    prefix: store.prefix,
    region: store.region,
    endpointUrl: store.endpointUrl,
    addressingStyle: store.addressingStyle,
    sse: store.sse,
    kmsKeyId: store.kmsKeyId,
  };
}

/**
 * Whether the draft differs from the stored settings.
 *
 * @param draft - The form's values.
 * @param store - The stored settings.
 * @returns True when saving would change something.
 */
export function isDraftDirty(draft: TenantDocumentStoreDraft, store: TenantDocumentStore): boolean {
  const saved = draftFromStore(store);
  return (Object.keys(saved) as Array<keyof TenantDocumentStoreDraft>).some((key) => saved[key] !== draft[key]);
}

/**
 * What is wrong with a draft, field by field. Only `tenant` mode needs a bucket.
 *
 * @param draft - The form's values.
 * @returns A message per invalid field; empty when the draft can be sent.
 */
export function validateDraft(draft: TenantDocumentStoreDraft): Partial<Record<keyof TenantDocumentStoreDraft, string>> {
  const errors: Partial<Record<keyof TenantDocumentStoreDraft, string>> = {};
  if (draft.mode !== 'tenant') return errors;
  if (!draft.credentialId) errors.credentialId = 'Choose a storage credential.';
  const bucket = draft.bucket.trim();
  if (!bucket) errors.bucket = 'Enter the bucket name.';
  else if (!BUCKET_RE.test(bucket) || bucket.includes('..')) {
    errors.bucket = 'Use 3 to 63 lower-case letters, digits, dots or hyphens.';
  }
  if (draft.kmsKeyId.trim() && draft.sse !== 'kms') errors.kmsKeyId = 'A KMS key is only used with SSE-KMS.';
  const endpoint = draft.endpointUrl.trim();
  if (endpoint && !/^https?:\/\/[^\s/]+/i.test(endpoint)) errors.endpointUrl = 'Enter a URL that starts with https://.';
  return errors;
}

/**
 * The request body for a draft. `platform` sends only the mode, so the saved bucket is kept for
 * the move back and the cleanup.
 *
 * @param draft - The form's values.
 * @returns The JSON body.
 */
export function draftBody(draft: TenantDocumentStoreDraft): Record<string, unknown> {
  if (draft.mode === 'platform') return { mode: 'platform' };
  return {
    mode: 'tenant',
    credentialId: draft.credentialId,
    bucket: draft.bucket.trim(),
    prefix: draft.prefix.trim(),
    region: draft.region.trim(),
    endpointUrl: draft.endpointUrl.trim(),
    addressingStyle: draft.addressingStyle,
    sse: draft.sse,
    kmsKeyId: draft.sse === 'kms' ? draft.kmsKeyId.trim() : '',
  };
}

/**
 * How far a move is, as a whole percentage.
 *
 * @param move - The move.
 * @returns 0–100; 100 for a move with nothing to move.
 */
export function movePercent(move: TenantDocumentStoreMove): number {
  if (move.total <= 0) return move.state === 'running' ? 0 : 100;
  return Math.max(0, Math.min(100, Math.round(((move.moved + move.failed) / move.total) * 100)));
}

/**
 * The sentence under the progress bar.
 *
 * @param move - The move.
 * @returns What the move is doing or did, or null when there has been none.
 */
export function moveSummary(move: TenantDocumentStoreMove): string | null {
  const place = move.target === 'tenant' ? 'your bucket' : 'platform storage';
  const number = (n: number) => n.toLocaleString('en-US');
  const count = (n: number) => `${number(n)} document${n === 1 ? '' : 's'}`;
  switch (move.state) {
    case 'running':
      return `Moving documents to ${place}: ${number(move.moved)} of ${number(move.total)} done. Everything stays readable while this runs.`;
    case 'completed':
      return move.moved > 0 ? `Moved ${count(move.moved)} to ${place}.` : `Nothing needed moving to ${place}.`;
    case 'failed':
      return `Moved ${count(move.moved)} to ${place}; ${count(move.failed)} could not be moved and ${
        move.failed === 1 ? 'is' : 'are'
      } still read from where ${move.failed === 1 ? 'it was' : 'they were'}.`;
    default:
      return null;
  }
}

/**
 * Browser calls for the workspace's document storage (COA-5.15, #7092), through
 * `/api/tenant-document-store` and `/api/export/storage-credentials`.
 */

import type {
  StorageCredentialInput,
  StorageCredentialOption,
  TenantDocumentStore,
  TenantDocumentStoreDraft,
  TenantDocumentStoreProbe,
} from '@lib/tenant-document-store';
import { draftBody } from '@lib/tenant-document-store';

/**
 * Parse a proxy answer, throwing REST's message (or `fallback`) on failure.
 *
 * @param response - The proxy's answer.
 * @param fallback - The message when REST gave none.
 * @returns The JSON body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/** @returns The current workspace's document storage settings, health and move progress. */
export async function fetchTenantDocumentStore(): Promise<TenantDocumentStore> {
  return readJson<TenantDocumentStore>(
    await fetch('/api/tenant-document-store', { cache: 'no-store' }),
    'Could not load document storage'
  );
}

/**
 * Save where documents are kept. Changing the mode starts the move.
 *
 * @param draft - The form's values.
 * @returns The settings after the change.
 */
export async function saveTenantDocumentStore(draft: TenantDocumentStoreDraft): Promise<TenantDocumentStore> {
  const response = await fetch('/api/tenant-document-store', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(draftBody(draft)),
  });
  return readJson<TenantDocumentStore>(response, 'Could not save document storage');
}

/**
 * Write, read back and delete a probe object in the bucket the draft describes.
 *
 * @param draft - The form's values (they need not be saved).
 * @returns Each step's outcome.
 */
export async function testTenantDocumentStore(draft: TenantDocumentStoreDraft): Promise<TenantDocumentStoreProbe> {
  const response = await fetch('/api/tenant-document-store/test', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(draftBody({ ...draft, mode: 'tenant' })),
  });
  return readJson<TenantDocumentStoreProbe>(response, 'Could not test the bucket');
}

/**
 * Delete the copies a finished move left in the old place. The caller has confirmed.
 *
 * @returns How many objects were checked and how many copies were deleted.
 */
export async function cleanupTenantDocumentStore(): Promise<{ checked: number; deleted: number }> {
  const response = await fetch('/api/tenant-document-store/cleanup', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ confirm: true }),
  });
  return readJson<{ checked: number; deleted: number }>(response, 'Could not delete the old copies');
}

/** One credential row as REST describes it (never a key). */
function toOption(row: Record<string, unknown>): StorageCredentialOption {
  return {
    id: String(row.id),
    name: String(row.name ?? row.id),
    accessKeyHint: String(row.accessKeyHint ?? ''),
    endpointUrl: typeof row.endpointUrl === 'string' && row.endpointUrl ? row.endpointUrl : null,
    region: String(row.region ?? ''),
  };
}

/** @returns The workspace's storage credentials, without their keys. */
export async function fetchStorageCredentials(): Promise<StorageCredentialOption[]> {
  const body = await readJson<{ data?: { credentials?: Array<Record<string, unknown>> } }>(
    await fetch('/api/export/storage-credentials', { cache: 'no-store' }),
    'Could not load storage credentials'
  );
  return (body.data?.credentials ?? []).filter((row) => typeof row.id === 'string').map(toOption);
}

/**
 * Store a new storage credential. The key pair is sent once and never read back.
 *
 * @param input - The credential's name, key pair and endpoint.
 * @returns The stored credential, without its keys.
 */
export async function createStorageCredential(input: StorageCredentialInput): Promise<StorageCredentialOption> {
  const response = await fetch('/api/export/storage-credentials', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
  const body = await readJson<{ data?: Record<string, unknown> }>(response, 'Could not store the credential');
  return toOption(body.data ?? {});
}

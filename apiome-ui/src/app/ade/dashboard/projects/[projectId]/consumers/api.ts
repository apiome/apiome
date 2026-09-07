/**
 * Client helpers for the Consumers screen — CTG-4.1 (#4479).
 *
 * Everything here talks to the `/api/consumers` proxy, which forwards to the REST layer's
 * tenant-scoped `/v1/tenants/{slug}/projects/{projectRef}/...` endpoints. The proxy answers
 * `{success, data}` or `{success: false, error, code?}`; these wrappers throw the message so a
 * caller can `try`/`catch` one way for every write.
 */

import type {
  AvailableSurface,
  Consumer,
  ConsumerContract,
  ConsumerSummary,
  SelectionPayloadOperation,
  UnresolvedInteraction,
} from '@/app/components/ade/consumers';

/** The list read. */
export interface ConsumerListResponse {
  consumers: ConsumerSummary[];
  count: number;
}

/** What a write that stores a revision answers with. */
export interface ContractWriteResponse {
  consumer: Consumer;
  contract: ConsumerContract;
  unresolved: UnresolvedInteraction[];
}

/** The consumer's editable identity, as the dialogs submit it. */
export interface ConsumerPayload {
  name: string;
  slug?: string;
  description?: string | null;
  owner?: string | null;
  contact?: string | null;
}

/** The marker segment addressing the picker's catalogue rather than a consumer. */
const SURFACE_MARKER = ':surface';

/** The marker segment addressing the Pact import rather than a consumer. */
const PACT_IMPORT_MARKER = ':pact-imports';

/**
 * Call the proxy and unwrap its envelope.
 *
 * @param path The path under `/api/consumers`.
 * @param init Fetch options.
 * @returns The `data` payload.
 * @throws Error carrying the proxy's message when the call failed.
 */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/consumers${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  // The proxy answers `{success, data}` or `{success: false, error}` on every status, so the
  // envelope is the authority — a refusal that arrived as a 409 and one that arrived as a 400
  // are told apart by their `code`, not by a status check here.
  if (!body?.success) {
    throw new Error(body?.error || 'Request failed');
  }
  return body.data as T;
}

/**
 * The project's consumers with their current contracts.
 *
 * @param projectRef Project slug or id.
 * @returns The list.
 */
export function fetchConsumers(projectRef: string): Promise<ConsumerListResponse> {
  return call<ConsumerListResponse>(`/${encodeURIComponent(projectRef)}`);
}

/**
 * Register a consumer.
 *
 * @param projectRef Project slug or id.
 * @param payload The consumer's identity.
 * @returns The stored consumer.
 */
export function createConsumer(
  projectRef: string,
  payload: ConsumerPayload,
): Promise<Consumer> {
  return call<Consumer>(`/${encodeURIComponent(projectRef)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Update a consumer's identity.
 *
 * @param projectRef Project slug or id.
 * @param consumerRef Consumer slug or id.
 * @param payload The fields to change; the handle is not among them.
 * @returns The updated consumer.
 */
export function updateConsumer(
  projectRef: string,
  consumerRef: string,
  payload: Omit<ConsumerPayload, 'slug'>,
): Promise<Consumer> {
  return call<Consumer>(
    `/${encodeURIComponent(projectRef)}/${encodeURIComponent(consumerRef)}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
}

/**
 * Retire a consumer, keeping its contract history.
 *
 * @param projectRef Project slug or id.
 * @param consumerRef Consumer slug or id.
 */
export async function retireConsumer(
  projectRef: string,
  consumerRef: string,
): Promise<void> {
  await call<void>(
    `/${encodeURIComponent(projectRef)}/${encodeURIComponent(consumerRef)}`,
    { method: 'DELETE' },
  );
}

/**
 * The operations and fields a consumer could declare.
 *
 * @param projectRef Project slug or id.
 * @param version Version label, revision id, or `latest`.
 * @returns The catalogue.
 */
export function fetchAvailableSurface(
  projectRef: string,
  version = 'latest',
): Promise<AvailableSurface> {
  return call<AvailableSurface>(
    `/${encodeURIComponent(projectRef)}/${SURFACE_MARKER}?version=${encodeURIComponent(version)}`,
  );
}

/**
 * Store a contract revision from a picked surface.
 *
 * @param projectRef Project slug or id.
 * @param consumerRef Consumer slug or id.
 * @param operations The picked operations and fields.
 * @param note Free text explaining the revision.
 * @returns The consumer, the stored revision, and everything that did not resolve.
 */
export function declareContract(
  projectRef: string,
  consumerRef: string,
  operations: SelectionPayloadOperation[],
  note?: string,
): Promise<ContractWriteResponse> {
  return call<ContractWriteResponse>(
    `/${encodeURIComponent(projectRef)}/${encodeURIComponent(consumerRef)}/contract`,
    { method: 'PUT', body: JSON.stringify({ operations, ...(note ? { note } : {}) }) },
  );
}

/**
 * Import a Pact document as a contract revision.
 *
 * @param projectRef Project slug or id.
 * @param pact The Pact document as text.
 * @param consumerSlug The handle to file it under; empty to use the document's own name.
 * @returns The consumer, the stored revision, and everything that did not resolve.
 */
export function importPact(
  projectRef: string,
  pact: string,
  consumerSlug: string,
): Promise<ContractWriteResponse> {
  return call<ContractWriteResponse>(
    `/${encodeURIComponent(projectRef)}/${PACT_IMPORT_MARKER}`,
    {
      method: 'POST',
      body: JSON.stringify({ pact, ...(consumerSlug ? { consumer_slug: consumerSlug } : {}) }),
    },
  );
}

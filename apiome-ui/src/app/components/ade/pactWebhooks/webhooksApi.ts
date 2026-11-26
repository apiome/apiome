/**
 * Browser calls for the **Webhooks** pages (PFX-5.6, #6950), through `/api/pact/webhooks/*`.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 422 names the field, a 409 says why a delivery cannot be sent again, a 429 asks to
 * wait before testing again).
 */

import type {
  DeliveryDetail,
  DeliveryPage,
  DeliveryStatus,
  ExecutionResult,
  WebhookDelivery,
  WebhookDocument,
  WebhooksOverview,
} from '@lib/pact-webhooks';
import { readJson } from '../pactPacticipants/pacticipantsApi';

const BASE = '/api/pact/webhooks';

/** JSON `POST` / `PUT` / `DELETE` options. */
function write(method: 'POST' | 'PUT' | 'DELETE', body?: unknown): RequestInit {
  return {
    method,
    cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  };
}

/**
 * Every webhook and the newest firing of each.
 *
 * @returns The overview.
 */
export async function fetchWebhooks(): Promise<WebhooksOverview> {
  return readJson<WebhooksOverview>(await fetch(BASE, { cache: 'no-store' }), 'Could not load the webhooks');
}

/**
 * One webhook.
 *
 * @param id - Its `uuid`.
 * @returns The webhook.
 */
export async function fetchWebhook(id: string): Promise<WebhookDocument> {
  return readJson<WebhookDocument>(
    await fetch(`${BASE}/${encodeURIComponent(id)}`, { cache: 'no-store' }),
    'Could not load the webhook',
  );
}

/**
 * Create a webhook.
 *
 * @param body - The webhook body.
 * @returns The stored webhook.
 */
export async function createWebhook(body: Record<string, unknown>): Promise<WebhookDocument> {
  return readJson<WebhookDocument>(await fetch(BASE, write('POST', body)), 'Could not create the webhook');
}

/**
 * Replace a webhook.
 *
 * @param id - Its `uuid`.
 * @param body - The whole webhook body (`**********` keeps a stored secret).
 * @returns The stored webhook.
 */
export async function replaceWebhook(id: string, body: Record<string, unknown>): Promise<WebhookDocument> {
  return readJson<WebhookDocument>(
    await fetch(`${BASE}/${encodeURIComponent(id)}`, write('PUT', body)),
    'Could not save the webhook',
  );
}

/**
 * Delete a webhook (its deliveries and their logs go with it).
 *
 * @param id - Its `uuid`.
 */
export async function deleteWebhook(id: string): Promise<void> {
  await readJson<unknown>(await fetch(`${BASE}/${encodeURIComponent(id)}`, write('DELETE')), 'Could not delete the webhook');
}

/**
 * Send a saved webhook once, now.
 *
 * @param id - Its `uuid`.
 * @returns What was sent and what came back.
 */
export async function testWebhook(id: string): Promise<ExecutionResult> {
  return readJson<ExecutionResult>(
    await fetch(`${BASE}/${encodeURIComponent(id)}/execute`, write('POST')),
    'Could not test the webhook',
  );
}

/**
 * Send an unsaved webhook once, now.
 *
 * @param body - The webhook body.
 * @returns What was sent and what came back.
 */
export async function testUnsavedWebhook(body: Record<string, unknown>): Promise<ExecutionResult> {
  return readJson<ExecutionResult>(await fetch(`${BASE}/execute`, write('POST', body)), 'Could not test the webhook');
}

/**
 * One page of the delivery log.
 *
 * @param options - `webhook` and `status` narrow; `cursor` is the previous page's `nextCursor`.
 * @returns The page.
 */
export async function fetchDeliveries(
  options: { webhook?: string | null; status?: DeliveryStatus | null; cursor?: string | null } = {},
): Promise<DeliveryPage> {
  const query = new URLSearchParams();
  if (options.webhook) query.set('webhook', options.webhook);
  if (options.status) query.set('status', options.status);
  if (options.cursor) query.set('cursor', options.cursor);
  const rendered = query.toString();
  return readJson<DeliveryPage>(
    await fetch(`${BASE}/deliveries${rendered ? `?${rendered}` : ''}`, { cache: 'no-store' }),
    'Could not load the deliveries',
  );
}

/**
 * One delivery and its attempts.
 *
 * @param id - The firing's `uuid`.
 * @returns The delivery.
 */
export async function fetchDelivery(id: string): Promise<DeliveryDetail> {
  return readJson<DeliveryDetail>(
    await fetch(`${BASE}/deliveries/${encodeURIComponent(id)}`, { cache: 'no-store' }),
    'Could not load the delivery',
  );
}

/**
 * Send a finished delivery again.
 *
 * @param id - The firing's `uuid`.
 * @returns The new delivery.
 */
export async function redeliverDelivery(id: string): Promise<WebhookDelivery> {
  return readJson<WebhookDelivery>(
    await fetch(`${BASE}/deliveries/${encodeURIComponent(id)}/redeliver`, write('POST')),
    'Could not redeliver',
  );
}

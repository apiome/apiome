/**
 * Browser calls for **Settings → Clean-up** (PFX-8.14, #7311), through the `/api/pact/retention/*`
 * proxies. Restoring reuses the pacticipant and version restore calls of the Pacticipants pages.
 *
 * Each throws REST's message on a failure, so the tab can show it (a 403 reads "Permission
 * denied", a 422 names the rule).
 */

import type { DeletedPage, RetentionPolicy, RetentionPreview, RetentionRules } from '@lib/pact-retention';
import { readJson } from '../pactPacticipants/pacticipantsApi';

const BASE = '/api/pact/retention';

/** JSON request options for a write. */
function send(method: 'PUT' | 'POST', body: unknown): RequestInit {
  return { method, cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

/**
 * The workspace's clean-up rules.
 *
 * @returns The policy (the defaults when never saved), with `can_edit`.
 */
export async function fetchPolicy(): Promise<RetentionPolicy> {
  return readJson<RetentionPolicy>(await fetch(`${BASE}/policy`, { cache: 'no-store' }), 'Could not load the clean-up rules');
}

/**
 * Save the clean-up rules (every field: a save replaces them).
 *
 * @param rules - The rules.
 * @returns The saved policy.
 */
export async function savePolicy(rules: RetentionRules): Promise<RetentionPolicy> {
  return readJson<RetentionPolicy>(await fetch(`${BASE}/policy`, send('PUT', rules)), 'Could not save the clean-up rules');
}

/**
 * What the rules would remove if the clean-up ran now.
 *
 * @param draft - Rules not saved yet, or `null` for the saved ones.
 * @returns The preview.
 */
export async function previewPolicy(draft: RetentionRules | null): Promise<RetentionPreview> {
  return readJson<RetentionPreview>(
    await fetch(`${BASE}/policy/preview`, send('POST', draft ? { rules: draft } : {})),
    'Could not preview the clean-up',
  );
}

/**
 * One page of Recently deleted, newest first.
 *
 * @param cursor - The previous page's `next_cursor`.
 * @returns The page.
 */
export async function fetchDeleted(cursor?: string | null): Promise<DeletedPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  const page = await readJson<DeletedPage>(
    await fetch(`${BASE}/deleted${query}`, { cache: 'no-store' }),
    'Could not load what was deleted',
  );
  return { ...page, items: Array.isArray(page.items) ? page.items : [] };
}

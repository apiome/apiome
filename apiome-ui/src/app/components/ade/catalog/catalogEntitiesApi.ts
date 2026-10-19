/**
 * Browser calls for the catalog's entity kinds (CDG-5.1, #5979), through `/api/catalog/entities*`.
 */

import type { CatalogEntityPage, CatalogEntitySummary } from '@lib/catalog-entities';

/**
 * Read a proxy answer, or throw its message.
 *
 * @param response - The proxy response.
 * @param fallback - The message when the answer carries none.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/**
 * Every kind with its count, and the home callouts.
 *
 * @param team - Count only entities this team owns.
 * @returns The summary.
 */
export async function fetchEntitySummary(team?: string | null): Promise<CatalogEntitySummary> {
  const query = team ? `?${new URLSearchParams({ team }).toString()}` : '';
  const body = await readJson<CatalogEntitySummary>(
    await fetch(`/api/catalog/entities/summary${query}`, { cache: 'no-store' }),
    'Could not load the catalog kinds',
  );
  if (!Array.isArray(body.kinds)) throw new Error('Could not load the catalog kinds');
  return body;
}

/** What one entity-list page asks for. */
export interface EntityPageRequest {
  /** One kind, or `null` for every kind. */
  kind: string | null;
  team?: string | null;
  q?: string;
  cursor?: string | null;
  limit?: number;
}

/**
 * One page of entities.
 *
 * @param request - Kind, filters and the cursor.
 * @returns The page.
 */
export async function fetchEntityPage(request: EntityPageRequest): Promise<CatalogEntityPage> {
  const params = new URLSearchParams();
  if (request.kind) params.set('kind', request.kind);
  if (request.team) params.set('team', request.team);
  if (request.q?.trim()) params.set('q', request.q.trim());
  if (request.cursor) params.set('cursor', request.cursor);
  params.set('limit', String(request.limit ?? 50));
  const body = await readJson<CatalogEntityPage>(
    await fetch(`/api/catalog/entities?${params.toString()}`, { cache: 'no-store' }),
    'Could not load the catalog',
  );
  return { items: Array.isArray(body.items) ? body.items : [], pagination: body.pagination ?? { nextCursor: null } };
}

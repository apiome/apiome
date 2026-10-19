/**
 * Browser call for an entity's facts (CDG-5.4, #5982), through `/api/catalog/entities/{kind}/{id}/facts`.
 */

import type { CatalogFactsResponse } from '@lib/catalog-facts';

/**
 * One entity's facts.
 *
 * @param kind - The registry kind.
 * @param id - The entity id.
 * @returns The facts (`score` is always `null`).
 */
export async function fetchCatalogFacts(kind: string, id: string): Promise<CatalogFactsResponse> {
  const response = await fetch(`/api/catalog/entities/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/facts`, {
    cache: 'no-store',
  });
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : 'Could not load the facts');
  }
  return { ...(body as unknown as CatalogFactsResponse), facts: Array.isArray(body.facts) ? (body.facts as CatalogFactsResponse['facts']) : [] };
}

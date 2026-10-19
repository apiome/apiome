/**
 * Browser calls for the dependency-graph screens (CDG-3.4, #5969), through the `/api/graph/*` BFF.
 */

import type {
  BlastRadiusAnswer,
  GraphEdgePage,
  GraphEntityPage,
  GraphNodeKind,
  GraphProvenance,
  SuggestedConsumer,
} from '@lib/graph';
import { EDGE_PAGE_LIMIT } from '@lib/graph';

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : 'The dependency graph could not be read.');
  }
  return body as T;
}

/**
 * One direction of an entity's edges, with both ends' labels.
 *
 * @param kind - The entity's kind.
 * @param id - The entity's id.
 * @param direction - `in` or `out`.
 */
export async function fetchEdges(kind: GraphNodeKind, id: string, direction: 'in' | 'out'): Promise<GraphEdgePage> {
  const query = new URLSearchParams({ direction, limit: String(EDGE_PAGE_LIMIT) });
  const response = await fetch(`/api/graph/edges/${kind}/${encodeURIComponent(id)}?${query.toString()}`, {
    cache: 'no-store',
  });
  return readJson<GraphEdgePage>(response);
}

/** The search the tenant graph page runs. */
export interface EntitySearch {
  q?: string;
  kinds?: readonly GraphNodeKind[];
  team?: string | null;
  provenances?: readonly GraphProvenance[];
  limit?: number;
}

/** Search the entities in the graph. */
export async function fetchGraphEntities(search: EntitySearch): Promise<GraphEntityPage> {
  const query = new URLSearchParams();
  if (search.q?.trim()) query.set('q', search.q.trim());
  for (const kind of search.kinds ?? []) query.append('kind', kind);
  if (search.team) query.set('team', search.team);
  for (const provenance of search.provenances ?? []) query.append('provenance', provenance);
  query.set('limit', String(search.limit ?? 2000));
  const response = await fetch(`/api/graph/entities?${query.toString()}`, { cache: 'no-store' });
  return readJson<GraphEntityPage>(response);
}

/** A blast-radius question. */
export interface BlastRadiusQuestion {
  entity: { kind: GraphNodeKind; id: string };
  pointers: string[];
  depth: number;
  provenance: GraphProvenance[];
  version?: string;
}

/** Ask what a change affects. */
export async function runBlastRadius(question: BlastRadiusQuestion): Promise<BlastRadiusAnswer> {
  const response = await fetch('/api/graph/blast-radius', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(question),
  });
  return readJson<BlastRadiusAnswer>(response);
}

/**
 * Call the consumer-registry proxy (`/api/consumers`) and unwrap its `{success, data}` envelope.
 *
 * @param path - The path under `/api/consumers`.
 * @param init - Fetch options.
 * @returns The `data` payload.
 */
async function consumerCall<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/consumers${path}`, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = (await response.json().catch(() => null)) as {
    success?: boolean;
    data?: T;
    error?: string;
  } | null;
  if (!body?.success) throw new Error(body?.error || 'The request could not be completed.');
  return body.data as T;
}

/**
 * A project's suggested consumers (CDG-3.5): clients in its traffic that no binding attributes.
 *
 * @param projectId - The project (or catalog item) id.
 */
export async function fetchSuggestedConsumers(projectId: string): Promise<SuggestedConsumer[]> {
  const data = await consumerCall<{ suggestions: SuggestedConsumer[] }>(
    `/${encodeURIComponent(projectId)}/:suggestions`
  );
  return data.suggestions;
}

/** What registering a suggestion takes. */
export interface RegisterSuggestionBody {
  name?: string;
  slug?: string;
  binding_name?: string;
}

/**
 * Register a suggested consumer and the binding that recognises it.
 *
 * @param projectId - The project id.
 * @param suggestionId - The suggestion's id.
 * @param body - Name, slug and, for a hashed client, the header or claim name.
 * @returns The new consumer's slug.
 */
export async function registerSuggestedConsumer(
  projectId: string,
  suggestionId: string,
  body: RegisterSuggestionBody
): Promise<{ consumer: { id: string; slug: string; name: string } }> {
  return consumerCall(`/${encodeURIComponent(projectId)}/:suggestions/${encodeURIComponent(suggestionId)}/register`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * The Publish page's calls (PFX-8.3, #7300). Each goes through an `/api/*` proxy as the signed-in
 * user; tenant scoping and the `pacts` permission are REST's. None of them throws: the page shows
 * every answer beside the row or section it belongs to.
 */

import {
  checkUrl,
  classifyCheck,
  readDeriveOutcome,
  readPublishOutcome,
  type CheckVerdict,
  type DeriveOutcome,
  type PactFileRow,
  type PublishBatch,
  type PublishOutcome,
} from '@lib/pact-publish-page';
import type { Pacticipant } from '@lib/pact-pacticipants';

/** A refusal: REST's message and status. */
export interface CallFailure {
  error: string;
  status: number;
}

/** What the network said when it could not be reached. */
const UNREACHABLE = 'The Pact Broker could not be reached. Try again shortly.';

/**
 * Send one request and read its JSON.
 *
 * @param url - The proxy URL.
 * @param init - Fetch options.
 * @returns The status and the parsed body (`null` when it was not JSON), or `null` offline.
 */
async function send(url: string, init?: RequestInit): Promise<{ status: number; body: unknown } | null> {
  try {
    const response = await fetch(url, init);
    return { status: response.status, body: await response.json().catch(() => null) };
  } catch {
    return null;
  }
}

/** The proxy's `error`, or a sentence with the status. */
function errorOf(body: unknown, status: number, fallback: string): string {
  const message = (body as { error?: unknown } | null)?.error;
  return typeof message === 'string' && message ? message : `${fallback} (${status}).`;
}

/**
 * Publish one batch (one consumer, at most 100 pacts).
 *
 * @param batch - The request.
 * @returns What REST stored, or its refusal.
 */
export async function publishBatch(batch: PublishBatch): Promise<PublishOutcome | CallFailure> {
  const answer = await send('/api/pact/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(batch.body),
  });
  if (!answer) return { error: UNREACHABLE, status: 503 };
  if (answer.status >= 400) return { error: errorOf(answer.body, answer.status, 'The Pact Broker refused it'), status: answer.status };
  return readPublishOutcome(batch.consumer, answer.body);
}

/**
 * Generate a consumer's pact from its project and publish it.
 *
 * @param body - The derive proxy's body (`deriveRequest`).
 * @returns The findings and what REST stored, or its refusal.
 */
export async function publishDerived(body: Record<string, unknown>): Promise<DeriveOutcome | CallFailure> {
  const answer = await send('/api/pact/publish/consumer-contract', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!answer) return { error: UNREACHABLE, status: 503 };
  if (answer.status >= 400) return { error: errorOf(answer.body, answer.status, 'The Pact Broker refused it'), status: answer.status };
  return readDeriveOutcome(answer.body);
}

/**
 * Check one row against what its version already published. Writes nothing.
 *
 * @param row - A publishable row.
 * @param version - The consumer version.
 * @returns The verdict.
 */
export async function checkRow(row: PactFileRow, version: string): Promise<CheckVerdict> {
  const answer = await send(checkUrl(row.consumer as string, row.provider as string, version));
  if (!answer) return { kind: 'error', message: UNREACHABLE };
  return classifyCheck(row, answer.status, answer.body);
}

/**
 * The consumer's pacticipant, for **Fill from the linked repository**.
 *
 * @param handle - The pacticipant's handle.
 * @returns The pacticipant, `null` when the workspace has none by that handle, or the failure.
 */
export async function fetchPacticipant(handle: string): Promise<Pacticipant | null | CallFailure> {
  const answer = await send(`/api/pact/pacticipants/${encodeURIComponent(handle)}`);
  if (!answer) return { error: UNREACHABLE, status: 503 };
  if (answer.status === 404) return null;
  if (answer.status >= 400) return { error: errorOf(answer.body, answer.status, 'Could not read the pacticipant'), status: answer.status };
  return answer.body as Pacticipant;
}

/** One project the Derive tab offers. */
export interface ProjectChoice {
  id: string;
  slug: string;
  name: string;
}

/** One consumer of a project the Derive tab offers. */
export interface ConsumerChoice {
  slug: string;
  name: string;
  /** Why it cannot be derived (no revision yet, or one imported from a Pact file), or `null`. */
  unavailable: string | null;
}

/**
 * The workspace's projects.
 *
 * @returns The projects by name, or the failure.
 */
export async function fetchProjects(): Promise<ProjectChoice[] | CallFailure> {
  const answer = await send('/api/projects');
  if (!answer) return { error: 'The projects could not be read. Try again shortly.', status: 503 };
  const body = answer.body as { success?: boolean; projects?: unknown; error?: unknown } | null;
  if (answer.status >= 400 || !body?.success || !Array.isArray(body.projects)) {
    return { error: errorOf(body, answer.status, 'Could not read the projects'), status: answer.status };
  }
  return body.projects
    .flatMap((raw) => {
      const project = raw as Record<string, unknown>;
      const id = typeof project.id === 'string' ? project.id : '';
      if (!id) return [];
      const name = typeof project.name === 'string' && project.name.trim() ? project.name.trim() : 'Untitled';
      return [{ id, name, slug: typeof project.slug === 'string' && project.slug ? project.slug : id }];
    })
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

/**
 * A project's consumers, each with whether it can be derived (a picker-declared revision only).
 *
 * @param project - The project's handle or id.
 * @returns The consumers, or the failure.
 */
export async function fetchProjectConsumers(project: string): Promise<ConsumerChoice[] | CallFailure> {
  const answer = await send(`/api/consumers/${encodeURIComponent(project)}`);
  if (!answer) return { error: 'The consumers could not be read. Try again shortly.', status: 503 };
  const body = answer.body as { success?: boolean; data?: { consumers?: unknown }; error?: unknown } | null;
  if (answer.status >= 400 || !body?.success || !Array.isArray(body.data?.consumers)) {
    return { error: errorOf(body, answer.status, 'Could not read the consumers'), status: answer.status };
  }
  return body.data.consumers.flatMap((raw) => {
    const summary = raw as { consumer?: { slug?: unknown; name?: unknown }; contract?: { source?: unknown } | null };
    const slug = typeof summary.consumer?.slug === 'string' ? summary.consumer.slug : '';
    if (!slug) return [];
    const name = typeof summary.consumer?.name === 'string' ? summary.consumer.name : slug;
    const source = summary.contract?.source;
    const unavailable = !summary.contract
      ? 'has no contract revision yet'
      : source === 'manual'
        ? null
        : 'was imported from a Pact file: publish that file instead';
    return [{ slug, name, unavailable }];
  });
}

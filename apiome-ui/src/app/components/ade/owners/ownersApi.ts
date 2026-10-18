/**
 * Browser calls for ownership — CDG-2.4 (#5963).
 *
 * Every call goes through the `/api/teams` and `/api/owners` BFF routes; nothing here talks to
 * apiome-rest directly. A failure is thrown as an `Error` carrying REST's message, so a caller can
 * show it next to the control that failed.
 */

import {
  parseEntityOwner,
  type EntityOwner,
  type OwnerEntityKind,
  type Team,
  type TeamActivity,
} from '@lib/owners';

/**
 * Read a BFF response, throwing its message on failure.
 *
 * @param response - The fetch response.
 * @param fallback - What to say when the body carries no message.
 * @returns The parsed JSON body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/**
 * The tenant's teams, by name.
 *
 * @returns The teams.
 */
export async function fetchTeams(): Promise<Team[]> {
  const body = await readJson<{ teams?: Team[] }>(await fetch('/api/teams'), 'Could not load teams');
  return Array.isArray(body.teams) ? body.teams : [];
}

/**
 * One team with its members.
 *
 * @param slug - The team's slug.
 * @returns The team.
 */
export async function fetchTeam(slug: string): Promise<Team> {
  return readJson<Team>(await fetch(`/api/teams/${encodeURIComponent(slug)}`), 'Could not load the team');
}

/**
 * A team's owned entities, open findings and routed events.
 *
 * @param slug - The team's slug.
 * @returns The activity.
 */
export async function fetchTeamActivity(slug: string): Promise<TeamActivity> {
  return readJson<TeamActivity>(
    await fetch(`/api/teams/${encodeURIComponent(slug)}/activity`),
    'Could not load the team’s activity'
  );
}

/** The owner half of an `OwnersResponse`, as the envelope `owner` shape. */
function ownerFromResponse(body: { owner?: unknown; suggestions?: unknown }): EntityOwner | null {
  const confirmed = parseEntityOwner(body.owner);
  if (confirmed) return confirmed;
  const suggestions = Array.isArray(body.suggestions) ? body.suggestions : [];
  return parseEntityOwner(suggestions[0]);
}

/**
 * Confirm the suggested owner of an entity.
 *
 * @param kind - The entity kind.
 * @param id - The entity id.
 * @param team - The suggested team to confirm.
 * @returns The entity's owner after the change.
 */
export async function confirmOwner(kind: OwnerEntityKind, id: string, team: string): Promise<EntityOwner | null> {
  const response = await fetch(`/api/owners/${kind}/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ team }),
  });
  return ownerFromResponse(await readJson(response, 'Could not confirm the owner'));
}

/**
 * Make one team the confirmed owner of several entities, all or nothing.
 *
 * @param team - The team's slug.
 * @param entities - The entities.
 * @returns How many entities were assigned.
 */
export async function assignOwner(
  team: string,
  entities: ReadonlyArray<{ kind: OwnerEntityKind; id: string }>
): Promise<number> {
  const response = await fetch('/api/owners/assign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ team, entities }),
  });
  const body = await readJson<{ count?: number }>(response, 'Could not assign the owner');
  return typeof body.count === 'number' ? body.count : entities.length;
}

/**
 * Ownership in the lists — CDG-2.4 (#5963).
 *
 * apiome-rest embeds `owner: {team, status, source}` in the catalog, projects, MCP browse and
 * consumers list envelopes (CDG-2.2), filters each of them by `?team=<slug>` in SQL, and serves
 * the owners and teams APIs. This module is everything the browser decides about that, with no
 * React and no `window`: the wire shapes, what an owner cell says, and the one rule for the
 * `team` query parameter that every BFF route forwards.
 *
 * Writes go through two BFF routes: `/api/owners/…` (confirm, assign, bulk assign) and
 * `/api/teams/…` (list, read, activity).
 */

/** The query parameter every owner-filtered list reads and forwards. */
export const TEAM_PARAM = 'team';

/** A team slug, as apiome-rest constrains it (lowercase, hyphenated, 1–128 characters). */
const TEAM_SLUG = /^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$/;

/** The kinds of entity that can have an owner. */
export const OWNER_ENTITY_KINDS = [
  'project',
  'catalog_item',
  'mcp_endpoint',
  'consumer',
  'connector',
  // CDG-5.2: agents (consumers in their own right) and the models they run on.
  'agent',
  'model',
  // CDG-5.3: a gateway's environment.
  'gateway_config',
  // CDG-5.5: an accepted Backstage or Compass component.
  'component',
] as const;

/** One of {@link OWNER_ENTITY_KINDS}. */
export type OwnerEntityKind = (typeof OWNER_ENTITY_KINDS)[number];

/** What each kind is called on a team page. */
export const OWNER_ENTITY_KIND_LABELS: Readonly<Record<OwnerEntityKind, string>> = {
  project: 'Projects',
  catalog_item: 'Catalog items',
  mcp_endpoint: 'MCP servers',
  consumer: 'Consumers',
  connector: 'Connectors',
  agent: 'Agents',
  model: 'Models',
  gateway_config: 'Gateway configs',
  component: 'Components',
};

/** The team an owner names. */
export interface OwnerTeam {
  /** The team's id. */
  id: string;
  /** The team's handle. */
  slug: string;
  /** The team's display name. */
  name: string;
}

/** The `owner` a list envelope carries: the confirmed owner, else the first suggestion. */
export interface EntityOwner {
  /** The team. */
  team: OwnerTeam;
  /** `confirmed` (findings route to it) or `suggested` (shown with its source, routes nothing). */
  status: 'confirmed' | 'suggested';
  /** Where it came from: `manual`, `gateway_tag`, `codeowners`, `spec_extension`, … */
  source: string;
}

/** What each suggestion source is called next to a "Suggested" badge. */
const SOURCE_LABELS: Readonly<Record<string, string>> = {
  manual: 'Assigned',
  gateway_tag: 'Gateway tag',
  codeowners: 'CODEOWNERS',
  spec_extension: 'Spec',
  backstage: 'Backstage',
  compass: 'Compass',
  hub: 'API hub',
};

/**
 * Read an `owner` field off a wire row.
 *
 * @param value - The row's `owner`, whatever it is.
 * @returns The owner, or `null` when the row has none or it is malformed.
 */
export function parseEntityOwner(value: unknown): EntityOwner | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const team = raw.team as Record<string, unknown> | undefined;
  if (!team || typeof team.slug !== 'string' || typeof team.name !== 'string') return null;
  const status = raw.status === 'confirmed' ? 'confirmed' : raw.status === 'suggested' ? 'suggested' : null;
  if (!status) return null;
  return {
    team: { id: String(team.id ?? ''), slug: team.slug, name: team.name },
    status,
    source: typeof raw.source === 'string' ? raw.source : 'manual',
  };
}

/**
 * The label for where a suggestion came from.
 *
 * @param source - The owner's `source`.
 * @returns A short label, e.g. `Gateway tag`; the raw value when unknown.
 */
export function ownerSourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * The accessible description of an owner cell.
 *
 * @param owner - The owner, or `null`.
 * @returns e.g. `Owned by Payments`, `Suggested owner: Payments (Gateway tag)`, `No owner`.
 */
export function ownerDescription(owner: EntityOwner | null): string {
  if (!owner) return 'No owner';
  if (owner.status === 'confirmed') return `Owned by ${owner.team.name}`;
  return `Suggested owner: ${owner.team.name} (${ownerSourceLabel(owner.source)})`;
}

/**
 * The `team` value a BFF route may forward upstream.
 *
 * @param value - The raw query parameter.
 * @returns The lowercased slug, or `null` when absent or not slug-shaped (never forwarded).
 */
export function sanitizeTeamParam(value: string | null | undefined): string | null {
  const slug = (value ?? '').trim().toLowerCase();
  return slug && TEAM_SLUG.test(slug) ? slug : null;
}

/**
 * Add the `team` filter to a query string being built for apiome-rest or a BFF route.
 *
 * @param params - The parameters being built (mutated).
 * @param team - The selected team slug, or `null`.
 * @returns The same parameters, for chaining.
 */
export function withTeamParam(params: URLSearchParams, team: string | null): URLSearchParams {
  const slug = sanitizeTeamParam(team);
  if (slug) params.set(TEAM_PARAM, slug);
  else params.delete(TEAM_PARAM);
  return params;
}

/* -------------------------------------------------------------------------
   Teams
   ------------------------------------------------------------------------- */

/** A team member, as `GET …/teams/{slug}` returns one. */
export interface TeamMember {
  user_id: string;
  role: 'lead' | 'member';
  email?: string | null;
  name?: string | null;
  added_at?: string | null;
}

/** A team, as `GET …/teams` (no members) and `GET …/teams/{slug}` (members) return it. */
export interface Team {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  contact_email?: string | null;
  chat_url?: string | null;
  oncall_url?: string | null;
  docs_url?: string | null;
  member_count: number;
  members?: TeamMember[] | null;
}

/** An entity a team is the confirmed owner of. */
export interface OwnedEntity {
  kind: OwnerEntityKind;
  id: string;
  name: string;
  source: string;
}

/** One routed finding on a team page. */
export interface RoutedEvent {
  type: string;
  entity_kind?: string | null;
  entity_id?: string | null;
  entity_name?: string | null;
  summary?: string | null;
  link?: string | null;
  created_at?: string | null;
  recipients: number;
}

/** `GET …/teams/{slug}/activity`. */
export interface TeamActivity {
  team_id: string;
  owned: OwnedEntity[];
  owned_counts: Partial<Record<OwnerEntityKind, number>>;
  suggested_count: number;
  open_findings: number;
  events: RoutedEvent[];
}

/**
 * Where an owned entity lives in the app.
 *
 * @param entity - The owned entity.
 * @returns The page, or `null` for a kind with no page of its own (a consumer).
 */
export function ownedEntityHref(entity: Pick<OwnedEntity, 'kind' | 'id'>): string | null {
  const id = encodeURIComponent(entity.id);
  switch (entity.kind) {
    case 'project':
      return `/ade/dashboard/versions?projectId=${id}`;
    case 'catalog_item':
      return `/ade/dashboard/catalog/${id}`;
    case 'mcp_endpoint':
      return `/ade/dashboard/mcp/${id}`;
    case 'connector':
      return `/ade/dashboard/connectors/${id}`;
    case 'agent':
      return `/ade/dashboard/catalog/agents/${id}`;
    case 'model':
      return `/ade/dashboard/catalog/models/${id}`;
    case 'gateway_config':
      return `/ade/dashboard/connectors/environments/${id}`;
    case 'component':
      return `/ade/dashboard/catalog/components/${id}`;
    default:
      return null;
  }
}

/**
 * Group owned entities by kind, in {@link OWNER_ENTITY_KINDS} order, dropping empty kinds.
 *
 * @param owned - The team's owned entities.
 * @returns `[kind, entities]` pairs.
 */
export function groupOwnedByKind(owned: readonly OwnedEntity[]): Array<[OwnerEntityKind, OwnedEntity[]]> {
  return OWNER_ENTITY_KINDS.map(
    (kind) => [kind, owned.filter((entity) => entity.kind === kind)] as [OwnerEntityKind, OwnedEntity[]]
  ).filter(([, entities]) => entities.length > 0);
}

/**
 * The links a team carries, labelled, in a fixed order, absent ones dropped.
 *
 * @param team - The team.
 * @returns `[label, href]` pairs: contact (as `mailto:`), chat, on-call, docs.
 */
export function teamLinks(team: Pick<Team, 'contact_email' | 'chat_url' | 'oncall_url' | 'docs_url'>): Array<[string, string]> {
  const links: Array<[string, string]> = [];
  if (team.contact_email) links.push(['Contact', `mailto:${team.contact_email}`]);
  if (team.chat_url) links.push(['Chat', team.chat_url]);
  if (team.oncall_url) links.push(['On-call', team.oncall_url]);
  if (team.docs_url) links.push(['Docs', team.docs_url]);
  return links;
}

/* -------------------------------------------------------------------------
   Policy, gate and drift (CDG-2.5)
   ------------------------------------------------------------------------- */

/** The tenant's ownership policy, as `GET …/ownership-policy` returns it. */
export interface OwnershipPolicy {
  /** The catch-all team for findings on entities with no confirmed owner, or null. */
  unowned_findings_team: (OwnerTeam & { deleted?: boolean; member_count?: number }) | null;
  /** Whether a project needs a confirmed owner to publish. */
  require_owner_to_publish: boolean;
}

/** The owner gate's verdict for one project. */
export interface OwnerGate {
  status: 'disabled' | 'satisfied' | 'blocked';
  message: string;
  reason?: string | null;
  team?: { slug?: string | null; name?: string | null } | null;
}

/** One row of the ownership drift report. */
export interface DriftItem {
  reason: 'deleted_team' | 'empty_team' | 'stale_suggestion';
  entity_kind: OwnerEntityKind;
  entity_id: string;
  entity_name?: string | null;
  team: { slug?: string | null; name?: string | null };
  since?: string | null;
}

/** The ownership drift report. */
export interface OwnershipDrift {
  items: DriftItem[];
  counts: Partial<Record<DriftItem['reason'], number>>;
  stale_after_days: number;
}

/** How each drift reason is named on the Teams page. */
export const DRIFT_REASON_LABELS: Readonly<Record<DriftItem['reason'], string>> = {
  deleted_team: 'Owner team deleted',
  empty_team: 'Owner team has no members',
  stale_suggestion: 'Suggestion never confirmed',
};

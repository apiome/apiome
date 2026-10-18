/**
 * The shadow-API report's client model (CDG-1.6, #5957).
 *
 * Mirrors `GET /v1/tenants/{t}/shadow-report` and holds the page's pure decisions — which sections
 * exist and what they are called, how a match tier reads, which environments a filter can offer,
 * and what an empty section says — so `ShadowApisClient` only renders and the rules are testable
 * on their own.
 */

/** The catalog item or Project a gateway API may be. */
export interface ShadowMatchTarget {
  projectId: string;
  name: string | null;
  kind: 'catalog-item' | 'project' | string;
  versionId: string | null;
  versionLabel: string | null;
}

/** A possible match — a suggestion; nothing is linked until a person links it. */
export interface ShadowMatch {
  tier: 'remote-id' | 'host' | 'title' | string;
  confidence: number;
  reason: string;
  target: ShadowMatchTarget;
}

/** Why a row was ignored. */
export interface ShadowIgnored {
  reason: string | null;
  at: string | null;
  by: string | null;
  hosts: string[];
  basePath: string | null;
  reappeared: boolean;
}

/** One gateway API in a report section. */
export interface ShadowItem {
  itemId: string;
  connectorId: string;
  connectorName: string | null;
  connectorKind: string | null;
  remoteId: string | null;
  name: string | null;
  environment: string | null;
  hosts: string[];
  basePath: string | null;
  status: string | null;
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  stale: boolean;
  ignored?: ShadowIgnored | null;
  match?: ShadowMatch | null;
  alternatives?: ShadowMatch[];
  catalogItemId?: string | null;
  deployedRevision?: string | null;
  catalogRevision?: string | null;
  catalogVersionLabel?: string | null;
}

/** A described API no connected gateway serves. */
export interface ShadowUndeployed {
  projectId: string;
  name: string | null;
  kind: string;
  versionId: string | null;
  versionLabel: string | null;
  servers: string[];
}

/** A connector in the report's scope. */
export interface ShadowConnector {
  id: string;
  name: string | null;
  kind: string | null;
  status: string | null;
  itemCount: number;
  stale: boolean;
  staleSince: string | null;
}

/** The whole report. */
export interface ShadowReport {
  generatedAt: string;
  filters: { connector: string | null; environment: string | null };
  connectors: ShadowConnector[];
  stale: { connectorId: string; connectorName: string | null; since: string | null; message: string }[];
  summary: Record<ShadowSectionKey, number>;
  shadow: ShadowItem[];
  possibleMatches: ShadowItem[];
  undeployed: ShadowUndeployed[];
  drift: ShadowItem[];
  ignored: ShadowItem[];
}

/** The report's sections, as the page's chips name them. */
export type ShadowSectionKey = 'shadow' | 'possibleMatches' | 'drift' | 'undeployed' | 'ignored';

/** A section: its chip label and the one sentence under it. */
export interface ShadowSection {
  key: ShadowSectionKey;
  label: string;
  description: string;
}

/** Every section, in the order the chips show them. */
export const SHADOW_SECTIONS: readonly ShadowSection[] = [
  {
    key: 'shadow',
    label: 'Shadow',
    description: 'Served by a connected gateway and described nowhere in the catalog.',
  },
  {
    key: 'possibleMatches',
    label: 'Possible matches',
    description: 'Served APIs that look like a catalog item. Link one only after you confirm it.',
  },
  {
    key: 'drift',
    label: 'Drift',
    description: 'Linked APIs whose deployed revision the catalog does not have.',
  },
  {
    key: 'undeployed',
    label: 'Undeployed',
    description: 'Described APIs with servers that no connected gateway serves.',
  },
  {
    key: 'ignored',
    label: 'Ignored',
    description: 'APIs someone ignored, with their reason. They return if their host changes.',
  },
];

/**
 * How a match tier reads to a person.
 *
 * @param tier - The REST tier (`remote-id`, `host`, `title`).
 */
export function tierLabel(tier: string): string {
  switch (tier) {
    case 'remote-id':
      return 'Same remote id';
    case 'host':
      return 'Same host';
    case 'title':
      return 'Similar name';
    default:
      return tier;
  }
}

/**
 * A 0–1 confidence as a whole percentage.
 *
 * @param confidence - The REST confidence.
 */
export function confidencePercent(confidence: number): string {
  return `${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%`;
}

/**
 * The query string of the report request for the current filters (empty when unfiltered).
 *
 * @param filters - The selected connector id and environment, either may be empty.
 */
export function reportQuery(filters: { connector?: string | null; environment?: string | null }): string {
  const query = new URLSearchParams();
  if (filters.connector) query.set('connector', filters.connector);
  if (filters.environment) query.set('environment', filters.environment);
  const text = query.toString();
  return text ? `?${text}` : '';
}

/**
 * The environments a report's gateway rows were found in, sorted, for the environment filter.
 *
 * @param report - The report.
 */
export function environmentsOf(report: ShadowReport | null): string[] {
  if (!report) return [];
  const found = new Set<string>();
  for (const section of [report.shadow, report.possibleMatches, report.drift, report.ignored]) {
    for (const item of section) if (item.environment) found.add(item.environment);
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

/**
 * What an empty section says. A stale inventory is never presented as a clean result.
 *
 * @param section - The section that is empty.
 * @param staleCount - How many connectors in scope have a stale inventory.
 */
export function emptySectionCopy(section: ShadowSectionKey, staleCount: number): string {
  if (staleCount > 0 && section !== 'undeployed' && section !== 'ignored') {
    return 'Nothing here in the last inventory we have, but it is stale. Fix the failing connector, then refresh.';
  }
  switch (section) {
    case 'shadow':
      return 'Every API your gateways serve is in the catalog or waiting for a decision.';
    case 'possibleMatches':
      return 'No served API needs a link decision.';
    case 'drift':
      return 'Every linked API serves the revision the catalog has.';
    case 'undeployed':
      return 'Every described API with a server is served by a connected gateway.';
    case 'ignored':
      return 'No API is ignored.';
  }
}

/**
 * The text a row shows for where it is served: its hosts, with the base path on a bare host.
 *
 * @param item - The gateway row.
 */
export function servedAt(item: Pick<ShadowItem, 'hosts' | 'basePath'>): string {
  if (item.hosts.length === 0) return item.basePath ?? '—';
  return item.hosts
    .map((host) => (host.includes('://') || !item.basePath ? host : `${host}${item.basePath}`))
    .join(', ');
}

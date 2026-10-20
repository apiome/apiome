/**
 * The catalog dependency graph in the UI — CDG-3.4 (#5969).
 *
 * Types for the REST graph reads (CDG-3.1 edges, CDG-3.3 blast radius, the CDG-3.4 entity search)
 * and the pure rules the Dependencies tab, the tenant graph page and the blast-radius drawer share:
 * kind labels, where a node links to, how a list of edges groups, how an operation or schema
 * becomes a JSON pointer, and how each evidence section reads.
 *
 * Every node is a link: to its own page when it has one, else to the graph page centred on it.
 */

import { ownedEntityHref } from '@lib/owners';

/** Every node kind an edge end can be (apiome-db V288, V298). */
export const GRAPH_NODE_KINDS = [
  'project',
  'catalog_item',
  'consumer',
  'connector',
  'mcp_endpoint',
  'mcp_source',
  'repository',
  'identity_group',
  // CDG-5.3 (V298): one (connector, environment) — what `deployed_on` edges point at.
  'gateway_config',
  // CDG-5.5 (V299): an accepted Backstage or Compass component; declares its own edges.
  'component',
] as const;
export type GraphNodeKind = (typeof GRAPH_NODE_KINDS)[number];

/** Every edge kind. */
export const GRAPH_EDGE_KINDS = [
  'consumes',
  'depends_on',
  'runtime_calls',
  'served_by',
  'deployed_on',
  'built_from',
  'converted_from',
  'identity_of',
] as const;
export type GraphEdgeKind = (typeof GRAPH_EDGE_KINDS)[number];

export const GRAPH_PROVENANCES = ['declared', 'derived', 'runtime'] as const;
export type GraphProvenance = (typeof GRAPH_PROVENANCES)[number];

/** A node kind's singular name. */
export const NODE_KIND_LABELS: Readonly<Record<GraphNodeKind, string>> = {
  project: 'Project',
  catalog_item: 'Catalog item',
  consumer: 'Consumer',
  connector: 'Connector',
  mcp_endpoint: 'MCP server',
  mcp_source: 'MCP source',
  repository: 'Repository',
  identity_group: 'Identity group',
  gateway_config: 'Gateway config',
  component: 'Component',
};

/** A short, text-only kind marker drawn inside a graph node (colour is never the only signal). */
export const NODE_KIND_ABBREVIATIONS: Readonly<Record<GraphNodeKind, string>> = {
  project: 'P',
  catalog_item: 'C',
  consumer: 'U',
  connector: 'G',
  mcp_endpoint: 'M',
  mcp_source: 'S',
  repository: 'R',
  identity_group: 'I',
  gateway_config: 'E',
  component: 'K',
};

/** How an edge reads from its source's side (`out`) and from its target's side (`in`). */
export const EDGE_KIND_LABELS: Readonly<Record<GraphEdgeKind, { out: string; in: string }>> = {
  consumes: { out: 'Consumes', in: 'Consumed by' },
  depends_on: { out: 'Depends on', in: 'Depended on by' },
  runtime_calls: { out: 'Calls at runtime', in: 'Called at runtime by' },
  served_by: { out: 'Served by', in: 'Serves' },
  deployed_on: { out: 'Deployed on', in: 'Deploys' },
  built_from: { out: 'Built from', in: 'Builds' },
  converted_from: { out: 'Converted from', in: 'Converted into' },
  identity_of: { out: 'Same API as', in: 'Groups' },
};

export const PROVENANCE_LABELS: Readonly<Record<GraphProvenance, string>> = {
  declared: 'Declared',
  derived: 'Derived',
  runtime: 'Runtime',
};

/** The most a single graph read returns (REST's `limit` bound for edges). */
export const EDGE_PAGE_LIMIT = 500;

/** The blast radius never reports more than this many entities. */
export const BLAST_RADIUS_MAX_NODES = 2000;

/** An owner team as the graph reads return it. */
export interface GraphOwner {
  slug: string;
  name: string;
  status: 'confirmed' | 'suggested' | string;
}

/** One end's label (`labels=true`). */
export interface GraphNodeLabel {
  name: string | null;
  slug: string | null;
  owner: GraphOwner | null;
}

/** One edge, as `GET …/edges?labels=true` returns it. */
export interface GraphEdge {
  id: string;
  from_kind: GraphNodeKind;
  from_id: string;
  to_kind: GraphNodeKind;
  to_id: string;
  edge_kind: GraphEdgeKind;
  pointer: string | null;
  provenance: GraphProvenance;
  source_ref: string;
  evidence: Record<string, unknown>;
  first_seen_at: string | null;
  last_seen_at: string | null;
  stale_since: string | null;
  stale: boolean;
  from_label?: GraphNodeLabel | null;
  to_label?: GraphNodeLabel | null;
}

export interface GraphEdgePage {
  edges: GraphEdge[];
  total: number;
  truncated: boolean;
  limit: number;
  offset: number;
}

/** One entity of the tenant-wide search. */
export interface GraphEntity {
  kind: GraphNodeKind;
  id: string;
  name: string | null;
  slug: string | null;
  owner: GraphOwner | null;
  in_count: number;
  out_count: number;
  stale_count: number;
}

export interface GraphEntityPage {
  entities: GraphEntity[];
  total: number;
  truncated: boolean;
  limit: number;
  offset: number;
}

/** One step of an affected entity's path back to the change. */
export interface BlastRadiusStep {
  from_kind: GraphNodeKind;
  from_id: string;
  to_kind: GraphNodeKind;
  to_id: string;
  edge_kind: GraphEdgeKind;
  provenance: GraphProvenance;
  pointer: string | null;
}

export interface AffectedEntity {
  kind: GraphNodeKind;
  id: string;
  name: string | null;
  slug: string | null;
  depth: number;
  edge_kind: GraphEdgeKind;
  provenance: GraphProvenance;
  pointers: string[];
  path: BlastRadiusStep[];
  owner: GraphOwner | null;
}

export const EVIDENCE_SECTIONS = [
  'verification_runs',
  'consumer_contracts',
  'deploy_gate_evaluations',
  'sdk_regen_targets',
  'agent_toolset_tools',
  'mock_fixture_packs',
  'sunset_consumers',
] as const;
export type EvidenceSection = (typeof EVIDENCE_SECTIONS)[number];

/** What each evidence section is called. */
export const EVIDENCE_LABELS: Readonly<Record<EvidenceSection, string>> = {
  verification_runs: 'Verification runs',
  consumer_contracts: 'Consumer contracts',
  deploy_gate_evaluations: 'Deploy-gate evaluations',
  sdk_regen_targets: 'SDK regeneration targets',
  agent_toolset_tools: 'Agent toolset tools',
  mock_fixture_packs: 'Mock fixture packs and scenarios',
  sunset_consumers: 'Consumers on deprecated versions',
};

export interface BlastRadiusAnswer {
  entity: { kind: GraphNodeKind; id: string; name: string | null; slug: string | null; owner: GraphOwner | null };
  version: { id: string; label: string | null; published: boolean } | null;
  pointers: string[];
  operations: string[] | null;
  depth: number;
  provenance: GraphProvenance[];
  direct: AffectedEntity[];
  transitive: AffectedEntity[];
  invalidated_evidence: Record<EvidenceSection, Array<Record<string, unknown>>>;
  evidence_checked: boolean;
  truncated: boolean;
  node_count: number;
  /** Entities found, including those past the 2,000 cap (a lower bound when truncated). */
  total_found: number;
  warnings: string[];
}

/** Whether a string is a graph node kind. */
export function isGraphNodeKind(value: unknown): value is GraphNodeKind {
  return typeof value === 'string' && (GRAPH_NODE_KINDS as readonly string[]).includes(value);
}

/** Whether a string is an edge kind. */
export function isGraphEdgeKind(value: unknown): value is GraphEdgeKind {
  return typeof value === 'string' && (GRAPH_EDGE_KINDS as readonly string[]).includes(value);
}

/** Whether a string is a provenance. */
export function isGraphProvenance(value: unknown): value is GraphProvenance {
  return typeof value === 'string' && (GRAPH_PROVENANCES as readonly string[]).includes(value);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether a string is a UUID (BFF path-segment guard). */
export function isGraphId(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}

/** The graph page centred on a node. */
export function graphPageHref(kind: GraphNodeKind, id: string): string {
  return `/ade/dashboard/graph?entity=${encodeURIComponent(`${kind}:${id}`)}`;
}

/**
 * Where a node links to: its own page when it has one, else the graph page centred on it.
 *
 * @param kind - The node kind.
 * @param id - The node id.
 */
export function graphNodeHref(kind: GraphNodeKind, id: string): string {
  if (kind === 'repository') return `/ade/dashboard/repositories/${encodeURIComponent(id)}`;
  if (
    kind === 'project' ||
    kind === 'catalog_item' ||
    kind === 'mcp_endpoint' ||
    kind === 'connector' ||
    kind === 'gateway_config' ||
    kind === 'component'
  ) {
    return ownedEntityHref({ kind, id }) ?? graphPageHref(kind, id);
  }
  return graphPageHref(kind, id);
}

/** Parse the graph page's `?entity=kind:id`. */
export function parseEntityParam(value: string | null | undefined): { kind: GraphNodeKind; id: string } | null {
  const [kind, id] = String(value ?? '').split(':', 2);
  return isGraphNodeKind(kind) && isGraphId(id) ? { kind, id } : null;
}

/** A node's display name: its name, else its slug, else its kind and a short id. */
export function nodeDisplayName(
  kind: GraphNodeKind,
  id: string,
  label?: Pick<GraphNodeLabel, 'name' | 'slug'> | null
): string {
  return label?.name || label?.slug || `${NODE_KIND_LABELS[kind]} ${id.slice(0, 8)}`;
}

/** The other end of an edge, seen from `entityId`. */
export interface EdgeNeighbour {
  edge: GraphEdge;
  direction: 'in' | 'out';
  kind: GraphNodeKind;
  id: string;
  label: GraphNodeLabel | null;
}

/** The neighbour an edge leads to from `entityId` (an edge to itself reads as outgoing). */
export function neighbourOf(edge: GraphEdge, entityId: string): EdgeNeighbour {
  const outgoing = edge.from_id === entityId;
  return outgoing
    ? { edge, direction: 'out', kind: edge.to_kind, id: edge.to_id, label: edge.to_label ?? null }
    : { edge, direction: 'in', kind: edge.from_kind, id: edge.from_id, label: edge.from_label ?? null };
}

/** One group of the Dependencies list: one direction and edge kind. */
export interface EdgeGroup {
  key: string;
  direction: 'in' | 'out';
  edgeKind: GraphEdgeKind;
  title: string;
  neighbours: EdgeNeighbour[];
  staleCount: number;
}

/**
 * Group an entity's edges by direction and edge kind — outgoing first, in {@link GRAPH_EDGE_KINDS}
 * order — with current edges before stale ones and, within each, by name.
 *
 * @param edges - The entity's in and out edges.
 * @param entityId - The entity.
 */
export function groupEdges(edges: readonly GraphEdge[], entityId: string): EdgeGroup[] {
  const groups: EdgeGroup[] = [];
  for (const direction of ['out', 'in'] as const) {
    for (const edgeKind of GRAPH_EDGE_KINDS) {
      const neighbours = edges
        .map((edge) => neighbourOf(edge, entityId))
        .filter((n) => n.direction === direction && n.edge.edge_kind === edgeKind)
        .sort(
          (a, b) =>
            Number(a.edge.stale) - Number(b.edge.stale) ||
            nodeDisplayName(a.kind, a.id, a.label).localeCompare(nodeDisplayName(b.kind, b.id, b.label)) ||
            String(a.edge.pointer ?? '').localeCompare(String(b.edge.pointer ?? ''))
        );
      if (neighbours.length) {
        groups.push({
          key: `${direction}:${edgeKind}`,
          direction,
          edgeKind,
          title: EDGE_KIND_LABELS[edgeKind][direction],
          neighbours,
          staleCount: neighbours.filter((n) => n.edge.stale).length,
        });
      }
    }
  }
  return groups;
}

/** Merge pages of edges, dropping duplicates by id (an entity's in and out reads can overlap). */
export function mergeEdges(...pages: ReadonlyArray<readonly GraphEdge[]>): GraphEdge[] {
  const seen = new Set<string>();
  const merged: GraphEdge[] = [];
  for (const page of pages) {
    for (const edge of page) {
      if (seen.has(edge.id)) continue;
      seen.add(edge.id);
      merged.push(edge);
    }
  }
  return merged;
}

/** "Last seen 3 Oct 2026" for a stale edge. */
export function lastSeenLabel(iso: string | null | undefined): string {
  if (!iso) return 'Last seen: unknown';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'Last seen: unknown';
  return `Last seen ${date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
}

const METHODS = ['GET', 'PUT', 'POST', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH', 'TRACE'];

function escapePointerToken(token: string): string {
  return token.replace(/~/g, '~0').replace(/\//g, '~1');
}

/**
 * `GET /pets/{id}` → `/paths/~1pets~1{id}/get`, or `null` when it isn't `METHOD /path`.
 *
 * @param operation - The operation as typed.
 */
export function operationPointer(operation: string): string | null {
  const [method, ...rest] = String(operation ?? '').trim().split(/\s+/);
  const path = rest.join(' ').trim();
  if (!METHODS.includes((method ?? '').toUpperCase()) || !path.startsWith('/')) return null;
  return `/paths/${escapePointerToken(path)}/${method.toLowerCase()}`;
}

/** `Pet` → `/components/schemas/Pet`, or `null` when empty. */
export function schemaPointer(name: string): string | null {
  const trimmed = String(name ?? '').trim();
  return trimmed ? `/components/schemas/${escapePointerToken(trimmed)}` : null;
}

/**
 * "Showing 2,000 of 2,431" when a result was cut short, else `null`.
 *
 * @param shown - How many are shown.
 * @param total - How many there are, when known.
 * @param truncated - Whether the result was cut short.
 * @param options - `atLeast`: the total is a lower bound (the blast radius stops counting at its
 *   walk's edge).
 */
export function truncationNotice(
  shown: number,
  total: number | null,
  truncated: boolean,
  options: { atLeast?: boolean } = {}
): string | null {
  if (!truncated) return null;
  const n = new Intl.NumberFormat('en-US');
  if (total && total > shown) {
    return `Showing ${n.format(shown)} of ${options.atLeast ? 'at least ' : ''}${n.format(total)}. Narrow it down to see the rest.`;
  }
  return `Showing the first ${n.format(shown)}. Narrow the change or raise the depth to see the rest.`;
}

/** One evidence row as the drawer lists it: a title, a detail line, and a link when one exists. */
export interface EvidenceItem {
  key: string;
  title: string;
  detail: string | null;
  href: string | null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : typeof value === 'number' ? String(value) : null;
}

/**
 * How one evidence row reads, with a link to where it lives in the app.
 *
 * @param section - The evidence section.
 * @param row - The row as REST returned it.
 * @param projectId - The changed project (for links into its pages).
 */
export function evidenceItem(
  section: EvidenceSection,
  row: Record<string, unknown>,
  projectId: string | null
): EvidenceItem {
  const project = projectId ? encodeURIComponent(projectId) : null;
  const versions = project ? `/ade/dashboard/versions?projectId=${project}` : null;
  switch (section) {
    case 'verification_runs':
      return {
        key: String(row.run_id),
        title: `${text(row.target) ?? 'Run'} · ${text(row.outcome) ?? 'unknown'}`,
        detail: Array.isArray(row.operations) ? (row.operations as string[]).join(', ') : null,
        href: versions,
      };
    case 'consumer_contracts':
      return {
        key: String(row.contract_id),
        title: `Contract revision ${text(row.revision) ?? '?'}`,
        detail: Array.isArray(row.matched_pointers) ? (row.matched_pointers as string[]).join(', ') : null,
        href: isGraphId(row.consumer_id) ? graphPageHref('consumer', row.consumer_id) : null,
      };
    case 'deploy_gate_evaluations':
      return {
        key: String(row.id),
        title: `${text(row.purpose) === 'deploy' ? 'Deploy gate' : 'Publish gate'} · ${row.passed ? 'passed' : 'failed'}`,
        detail: text(row.evaluated_at),
        href: versions,
      };
    case 'sdk_regen_targets':
      return {
        key: String(row.id),
        title: `${text(row.ecosystem) ?? 'SDK'} · ${text(row.delivery_mode) ?? ''}`.trim(),
        detail: null,
        href: '/ade/dashboard/sdk-settings',
      };
    case 'agent_toolset_tools':
      return {
        key: String(row.id),
        title: text(row.tool_name) ?? 'Tool',
        detail: text(row.operation_key),
        href: versions,
      };
    case 'mock_fixture_packs':
      return {
        key: `${text(row.kind)}:${text(row.name)}`,
        title: `${text(row.kind) === 'scenario' ? 'Scenario' : 'Fixture pack'} ${text(row.name) ?? ''}`.trim(),
        detail: Array.isArray(row.collections)
          ? (row.collections as string[]).join(', ')
          : Array.isArray(row.operations)
            ? (row.operations as string[]).join(', ')
            : null,
        href: versions,
      };
    case 'sunset_consumers':
      return {
        key: String(row.contract_id),
        title: `${text(row.consumer_name) ?? text(row.consumer_slug) ?? 'Consumer'} on ${text(row.version_label) ?? '?'}`,
        detail: text(row.sunset_date) ? `Sunset ${text(row.sunset_date)}` : 'Deprecated',
        href: '/ade/dashboard/versions/sunset-timeline',
      };
  }
}

// ---------------------------------------------------------------------------------------------
// Runtime edges and suggested consumers (CDG-3.5, #5970)
// ---------------------------------------------------------------------------------------------

/**
 * The evidence line of a `runtime_calls` edge: request count and the newest day with a call.
 *
 * @param edge - The edge.
 * @returns `"1,025 calls · last 2026-10-18"`, or `null` for an edge with no runtime evidence.
 */
export function runtimeEvidenceLine(edge: GraphEdge): string | null {
  if (edge.provenance !== 'runtime') return null;
  const calls = typeof edge.evidence.calls === 'number' ? edge.evidence.calls : null;
  const last = typeof edge.evidence.last_seen_day === 'string' ? edge.evidence.last_seen_day : null;
  if (calls === null && !last) return null;
  const parts: string[] = [];
  if (calls !== null) parts.push(calls === 1 ? '1 call' : `${calls.toLocaleString('en-US')} calls`);
  if (last) parts.push(`last ${last}`);
  return parts.join(' · ');
}

/**
 * Split edge groups into what was declared or derived and what was observed at runtime, so the two
 * are shown side by side and never merged.
 *
 * @param groups - The groups {@link groupEdges} built.
 * @returns `{declared, runtime}`; `runtime` holds the `runtime_calls` groups.
 */
export function splitRuntimeGroups(groups: readonly EdgeGroup[]): {
  declared: EdgeGroup[];
  runtime: EdgeGroup[];
} {
  return {
    declared: groups.filter((group) => group.edgeKind !== 'runtime_calls'),
    runtime: groups.filter((group) => group.edgeKind === 'runtime_calls'),
  };
}

/** A client seen in a project's traffic that no binding attributes (REST `consumer-suggestions`). */
export interface SuggestedConsumer {
  id: string;
  client_kind: 'user_agent' | 'header' | 'api_key' | 'jwt_claim';
  label: string;
  suggested_name: string;
  suggested_slug: string | null;
  needs_binding_name: boolean;
  calls: number;
  days_seen: number;
  first_seen_at: string;
  last_seen_at: string;
}

/** How each client kind reads in a suggestion row. */
export const SUGGESTION_KIND_LABELS: Readonly<Record<SuggestedConsumer['client_kind'], string>> = {
  user_agent: 'User agent',
  header: 'Header',
  api_key: 'API key',
  jwt_claim: 'JWT claim',
};

/**
 * The line under a suggestion's label.
 *
 * @param suggestion - The suggestion.
 * @returns `"240 calls on 3 days · last seen 18 Oct 2026"`.
 */
export function suggestionMetaLine(suggestion: SuggestedConsumer): string {
  const calls = suggestion.calls === 1 ? '1 call' : `${suggestion.calls.toLocaleString('en-US')} calls`;
  const days = suggestion.days_seen === 1 ? '1 day' : `${suggestion.days_seen} days`;
  return `${calls} on ${days} · ${lastSeenLabel(suggestion.last_seen_at).replace('Last seen', 'last seen')}`;
}

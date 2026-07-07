/**
 * MCP "changed since last view" digest — shared types & pure presentation helpers
 * (V2-MCP-30.5 / MCAT-16.5, #4640).
 *
 * The Insight tab greets a returning user with a per-user summary of what changed on the endpoint's
 * surface since they last looked — and how breaking that change is — served by apiome-rest through
 * the Next.js proxy at `/api/mcp/endpoints/{id}/insight/digest`. The digest diffs the version the
 * user last saw (their server-side seen-marker) against the endpoint's current version. This module
 * is the *pure, React-free* client layer over that payload: the typed wire shape, a defensive parser,
 * and the small projections the {@link ChangedSinceDigestPanel} renders (its display state and
 * breaking-change flag). Keeping it free of React/JSX lets it be unit-tested directly and keeps the
 * panel free of payload-shaping branches — mirroring {@link mcpEvolutionSeriesFromPayload}.
 */

import type {
  McpEvolutionChangeCounts,
  McpEvolutionSeverityCounts,
  McpEvolutionTypeCounts,
} from './mcpEvolutionUi';

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpEndpointDigestResponse` envelope.

/** One add / remove / modify entry since the user's last view, with its breaking severity. */
export interface McpDigestChange {
  /** `added` | `removed` | `modified` (tolerant of unknown values). */
  change_type: string;
  /** `tool` | `resource` | `resource_template` | `prompt` | `server`. */
  item_type: string;
  item_name: string;
  /** `breaking` | `additive` | `review` (tolerant of unknown values). */
  severity: string;
}

/** The "changed since last view" digest for one user + endpoint. */
export interface McpEndpointDigest {
  endpoint_id: string;
  /** No recorded marker (first visit) or the last-seen snapshot was pruned — the surface is new. */
  new_to_you: boolean;
  /** A marker exists pointing at an older snapshot than the current one, so there is a delta. */
  has_changes: boolean;
  last_seen_version_id: string | null;
  last_seen_version_seq: number | null;
  /** When the user last viewed the endpoint (ISO 8601), or null on a first visit. */
  last_seen_at: string | null;
  current_version_id: string | null;
  current_version_seq: number | null;
  current_version_tag: string | null;
  /** Per-kind counts of the *current* surface — for the "new to you — N tools" summary. */
  current_type_counts: McpEvolutionTypeCounts;
  /** Per-direction tally of the delta since last seen (empty unless `has_changes`). */
  change_counts: McpEvolutionChangeCounts;
  /** Per-severity tally of that same delta (drives the breaking-change callout). */
  severity_counts: McpEvolutionSeverityCounts;
  /** The individual changes since last seen (empty unless `has_changes`). */
  changes: McpDigestChange[];
}

// --- Defensive coercion ----------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asIntOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : null;
}

/** Parse a `{ tools, resources, resource_templates, prompts, total }` block, deriving `total`. */
function typeCountsFromPayload(raw: unknown): McpEvolutionTypeCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const tools = asInt(r.tools);
  const resources = asInt(r.resources);
  const resource_templates = asInt(r.resource_templates);
  const prompts = asInt(r.prompts);
  return {
    tools,
    resources,
    resource_templates,
    prompts,
    // Derive from the parts so the total can never disagree with the kinds it sums.
    total: tools + resources + resource_templates + prompts,
  };
}

/** Parse a `{ added, removed, modified, total }` churn block, deriving `total` from the parts. */
function changeCountsFromPayload(raw: unknown): McpEvolutionChangeCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const added = asInt(r.added);
  const removed = asInt(r.removed);
  const modified = asInt(r.modified);
  return { added, removed, modified, total: added + removed + modified };
}

/** Parse a `{ breaking, additive, review, total }` severity block, deriving `total` from the parts. */
function severityCountsFromPayload(raw: unknown): McpEvolutionSeverityCounts {
  const r = (raw ?? {}) as Record<string, unknown>;
  const breaking = asInt(r.breaking);
  const additive = asInt(r.additive);
  const review = asInt(r.review);
  return { breaking, additive, review, total: breaking + additive + review };
}

/** Parse the `changes` array, dropping entries that carry no item identity. */
function changesFromPayload(raw: unknown): McpDigestChange[] {
  if (!Array.isArray(raw)) return [];
  const out: McpDigestChange[] = [];
  for (const entry of raw) {
    const e = (entry ?? {}) as Record<string, unknown>;
    const item_name = asString(e.item_name);
    if (!item_name) continue;
    out.push({
      change_type: asString(e.change_type) ?? 'modified',
      item_type: asString(e.item_type) ?? 'tool',
      item_name,
      severity: asString(e.severity) ?? 'review',
    });
  }
  return out;
}

/**
 * Parse the digest payload into the typed {@link McpEndpointDigest}, or `null` when the payload is
 * malformed (no `endpoint_id`). Every tally is re-derived from its parts so it can never disagree
 * with them, and unknown/missing fields degrade to safe defaults (an all-zero, up-to-date digest).
 */
export function mcpDigestFromPayload(data: unknown): McpEndpointDigest | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  const endpoint_id = asString(d.endpoint_id);
  if (!endpoint_id) return null;
  return {
    endpoint_id,
    new_to_you: d.new_to_you === true,
    has_changes: d.has_changes === true,
    last_seen_version_id: asString(d.last_seen_version_id),
    last_seen_version_seq: asIntOrNull(d.last_seen_version_seq),
    last_seen_at: asString(d.last_seen_at),
    current_version_id: asString(d.current_version_id),
    current_version_seq: asIntOrNull(d.current_version_seq),
    current_version_tag: asString(d.current_version_tag),
    current_type_counts: typeCountsFromPayload(d.current_type_counts),
    change_counts: changeCountsFromPayload(d.change_counts),
    severity_counts: severityCountsFromPayload(d.severity_counts),
    changes: changesFromPayload(d.changes),
  };
}

// --- Projections -----------------------------------------------------------------------------

/** The digest's display state: the surface is `new` to the user, has `changed`, or is `current`. */
export type McpDigestState = 'new' | 'changed' | 'current';

/**
 * Reduce a digest to its display state. `changed` takes priority (there is a concrete delta to
 * show), then `new` (first visit / pruned marker), otherwise `current` (already up to date).
 */
export function mcpDigestState(digest: McpEndpointDigest): McpDigestState {
  if (digest.has_changes) return 'changed';
  if (digest.new_to_you) return 'new';
  return 'current';
}

/** True when the delta since last view includes at least one breaking change. */
export function mcpDigestHasBreaking(digest: McpEndpointDigest): boolean {
  return digest.severity_counts.breaking > 0;
}

/** The ISO date (YYYY-MM-DD) of the last view, or null — a locale-free, test-stable label. */
export function mcpDigestSeenDate(digest: McpEndpointDigest): string | null {
  return digest.last_seen_at ? digest.last_seen_at.slice(0, 10) : null;
}

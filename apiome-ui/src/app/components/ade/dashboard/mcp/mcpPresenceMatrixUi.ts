/**
 * MCP capability lifespan / presence matrix — shared types & pure projection helpers
 * (V2-MCP-30.2 / MCAT-16.2, #4637).
 *
 * The version history answers "what changed *this* release"; it cannot answer "is this tool stable,
 * or was it added last week and might vanish?". This module projects an endpoint's per-version
 * capability surfaces into a **presence matrix** — rows = every distinct capability name ever seen,
 * columns = discovery snapshots oldest→newest — shading each cell **added / present / modified /
 * absent**. It is the "gantt of the surface" that reveals volatile vs long-lived capabilities.
 *
 * There is no server-side matrix endpoint: the projection is reconstructed entirely on the client
 * from the same per-version {@link McpVersionDetail} snapshots the browse/insight views already load
 * (`mcp_capability_items` per version). Presence is exact (a capability is present in a snapshot iff
 * that snapshot lists it), and the added/modified classification is **adjacency-based** — each cell is
 * compared only to the *immediately preceding* snapshot, exactly as the server's diff engine
 * (`diff_surfaces`) does. That keeps the matrix consistent with `mcp_version_changes`: a renamed
 * capability reads as its old name going **absent** (removed) and its new name **added**, because the
 * diff engine records a rename the same way (there is no dedicated "renamed" change type). "Modified"
 * uses each item's fingerprint projection — the same allow-listed fields the server fingerprints —
 * over the fields the UI capability model carries (fully authoritative for tools; resources/prompts
 * omit only the `mimeType`/`arguments` wire fields the browse model does not promote).
 *
 * Kept pure and React-free — mirroring {@link mcpEvolutionUi} and {@link mcpSafetyPostureUi} — so the
 * presence reconstruction and lifespan classification are unit-tested directly and the panel stays
 * free of projection branches.
 */

import type { McpCapabilityItem, McpVersionDetail } from './mcpBrowseUi';
import { mcpVersionSeqLabel } from './mcpVersionsUi';

// --- Cell / row / column model ---------------------------------------------------------------

/**
 * One cell's state in the matrix, relative to the immediately preceding snapshot:
 * - `added` — present here and absent (or non-existent) in the prior column (a fresh appearance);
 * - `present` — present here and in the prior column with an identical fingerprint (carried, unchanged);
 * - `modified` — present here and in the prior column but with a changed fingerprint;
 * - `absent` — not present in this snapshot.
 */
export type McpMatrixCellState = 'added' | 'present' | 'modified' | 'absent';

/** Lifespan category for a whole row, summarizing its presence across the timeline. */
export type McpMatrixLifespan = 'stable' | 'new' | 'volatile' | 'removed';

/** One column of the matrix — a discovery snapshot the presence is charted against. */
export interface McpMatrixColumn {
  version_id: string;
  version_seq: number;
  version_tag: string | null;
  discovered_at: string | null;
  /** True when the endpoint's `current_version_id` points at this snapshot. */
  is_current: boolean;
}

/** One row of the matrix — a distinct capability (identified by kind + name) tracked across versions. */
export interface McpMatrixRow {
  /** Stable identity key (`item_type` + name), unique per row. */
  key: string;
  item_type: string;
  name: string;
  /** Per-column state, parallel to {@link McpPresenceMatrix.columns}. */
  cells: McpMatrixCellState[];
  /** Index of the first column the capability appears in. */
  firstIndex: number;
  /** Index of the last column the capability appears in. */
  lastIndex: number;
  /** Number of columns the capability is present in (added + present + modified cells). */
  presentCount: number;
  /** Number of columns whose cell is `modified`. */
  modifiedCount: number;
  /** True when the capability disappears and later reappears (an absent gap between two presences). */
  hasGap: boolean;
  /** True when the capability is present in the timeline's "current" column (see {@link McpPresenceMatrix.currentIndex}). */
  currentlyPresent: boolean;
  /** The row's lifespan category, derived from its presence pattern. */
  lifespan: McpMatrixLifespan;
}

/** The full presence matrix plus the headline metrics the panel summarizes. */
export interface McpPresenceMatrix {
  columns: McpMatrixColumn[];
  rows: McpMatrixRow[];
  /** Index of the "current" column (the `is_current` snapshot), else the newest column, else `-1`. */
  currentIndex: number;
  /** Distinct capabilities ever seen (== `rows.length`). */
  totalCapabilities: number;
  /** Capabilities present in the current column. */
  currentCount: number;
  /** Capabilities that were present at some point but are absent in the current column. */
  removedCount: number;
  /** Capabilities that disappeared and reappeared (a presence gap) — a volatility signal. */
  volatileCount: number;
  /** Capabilities that first appeared in the current column ("added last week"). */
  newCount: number;
}

// --- Fingerprint projection (for the added-vs-modified distinction) ---------------------------

/**
 * The fingerprint-relevant fields of a capability item, per kind — the UI-model subset of the
 * server's `fingerprint_projection` allow-list. Tools carry every field the server fingerprints, so
 * their modified detection is exact; resources/resource-templates/prompts omit only the `mimeType` /
 * `arguments` wire fields the browse model does not promote (a change to those alone reads as
 * unchanged here — a conservative false-negative that never mislabels presence).
 */
const FINGERPRINT_FIELDS: Record<string, readonly (keyof McpCapabilityItem)[]> = {
  tool: ['name', 'title', 'description', 'input_schema', 'output_schema', 'annotations'],
  resource: ['name', 'title', 'description', 'uri'],
  resource_template: ['name', 'title', 'description', 'uri_template'],
  prompt: ['name', 'title', 'description'],
};

/** The fallback field set for an unrecognized `item_type`: every fingerprint-relevant field the model carries. */
const FINGERPRINT_FIELDS_FALLBACK: readonly (keyof McpCapabilityItem)[] = [
  'name',
  'title',
  'description',
  'uri',
  'uri_template',
  'input_schema',
  'output_schema',
  'annotations',
];

/**
 * A key-order-independent JSON serialization of a value: object keys are sorted recursively so two
 * semantically equal projections that differ only in key order produce the same string. Mirrors the
 * canonical serialization the server fingerprints with, so the client's "modified" test agrees with
 * the diff engine regardless of how a snapshot's JSON happened to be ordered on the wire.
 */
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const entries = Object.keys(value as Record<string, unknown>)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify((value as Record<string, unknown>)[key])}`);
  return `{${entries.join(',')}}`;
}

/**
 * A capability's fingerprint signature — the stable serialization of its kind's fingerprint-relevant
 * fields. Two snapshots of the same capability are "modified" between them exactly when their
 * signatures differ.
 */
export function mcpCapabilitySignature(item: McpCapabilityItem): string {
  const fields = FINGERPRINT_FIELDS[item.item_type] ?? FINGERPRINT_FIELDS_FALLBACK;
  const projection: Record<string, unknown> = {};
  for (const field of fields) projection[field] = item[field];
  return stableStringify(projection);
}

/** The stable row-identity key for a capability: its kind and name (a rename yields a new key). */
export function mcpCapabilityKey(itemType: string, name: string): string {
  return `${itemType}\u0000${name}`;
}

// --- Matrix projection -----------------------------------------------------------------------

/** Canonical display order of capability kinds so rows group predictably (tools first). */
const KIND_ORDER: Record<string, number> = {
  tool: 0,
  resource: 1,
  resource_template: 2,
  prompt: 3,
};

function kindRank(itemType: string): number {
  return itemType in KIND_ORDER ? KIND_ORDER[itemType] : 99;
}

/** One snapshot's per-capability signatures, indexed by {@link mcpCapabilityKey}. */
interface SnapshotIndex {
  /** key → signature for every capability the snapshot lists. */
  signatures: Map<string, string>;
  /** key → its kind/name, so the row set can be assembled without re-parsing. */
  identities: Map<string, { item_type: string; name: string }>;
}

/** Index one snapshot's capability items by identity, capturing each one's fingerprint signature. */
function indexSnapshot(items: readonly McpCapabilityItem[]): SnapshotIndex {
  const signatures = new Map<string, string>();
  const identities = new Map<string, { item_type: string; name: string }>();
  for (const item of items) {
    // A capability with no name has no stable identity to track across versions — skip it rather
    // than collapse every unnamed item onto one row.
    if (!item.name) continue;
    const key = mcpCapabilityKey(item.item_type, item.name);
    signatures.set(key, mcpCapabilitySignature(item));
    if (!identities.has(key)) identities.set(key, { item_type: item.item_type, name: item.name });
  }
  return { signatures, identities };
}

/** Derive a row's lifespan category from its per-column states and the current column. */
function classifyLifespan(
  cells: readonly McpMatrixCellState[],
  firstIndex: number,
  currentIndex: number,
  hasGap: boolean,
  currentlyPresent: boolean,
): McpMatrixLifespan {
  // Present at some point but gone from the current snapshot — it "vanished".
  if (!currentlyPresent) return 'removed';
  // Reappeared after a gap — unstable presence.
  if (hasGap) return 'volatile';
  // First seen only in the current column — brand new.
  if (firstIndex === currentIndex) return 'new';
  return 'stable';
}

/**
 * Project a set of per-version snapshots into the capability presence matrix. Snapshots are sorted
 * oldest→newest by `version_seq` (defensively, regardless of input order) so the axis is stable, then
 * every distinct capability becomes a row whose cells are classified against the immediately preceding
 * column — the same adjacency the server's diff engine uses, so the matrix agrees with the recorded
 * change history (renames included; see the module doc).
 *
 * @param versions The endpoint's version snapshots (any order); each carries its capability `items`.
 * @returns The presence matrix and its headline metrics. An empty input yields an empty matrix.
 */
export function mcpPresenceMatrix(versions: readonly McpVersionDetail[]): McpPresenceMatrix {
  const ordered = [...versions].sort((a, b) => a.version_seq - b.version_seq);

  const columns: McpMatrixColumn[] = ordered.map((v) => ({
    version_id: v.id,
    version_seq: v.version_seq,
    version_tag: v.version_tag,
    discovered_at: v.discovered_at,
    is_current: v.is_current,
  }));
  const indexed = ordered.map((v) => indexSnapshot(v.items));

  // The "current" column anchors lifespan (currently-present, brand-new). Prefer the flagged current
  // snapshot; fall back to the newest column so the matrix still reads for a history with no current.
  let currentIndex = columns.findIndex((c) => c.is_current);
  if (currentIndex === -1 && columns.length > 0) currentIndex = columns.length - 1;

  // Assemble the full row-identity set (every capability seen in any snapshot), keeping one
  // canonical kind/name per key.
  const identities = new Map<string, { item_type: string; name: string }>();
  for (const snapshot of indexed) {
    for (const [key, identity] of snapshot.identities) {
      if (!identities.has(key)) identities.set(key, identity);
    }
  }

  const rows: McpMatrixRow[] = [];
  for (const [key, identity] of identities) {
    const cells: McpMatrixCellState[] = [];
    let firstIndex = -1;
    let lastIndex = -1;
    let presentCount = 0;
    let modifiedCount = 0;

    indexed.forEach((snapshot, index) => {
      const sig = snapshot.signatures.get(key);
      if (sig === undefined) {
        cells.push('absent');
        return;
      }
      presentCount += 1;
      if (firstIndex === -1) firstIndex = index;
      lastIndex = index;

      const prevSig = index > 0 ? indexed[index - 1].signatures.get(key) : undefined;
      if (prevSig === undefined) {
        cells.push('added');
      } else if (prevSig !== sig) {
        cells.push('modified');
        modifiedCount += 1;
      } else {
        cells.push('present');
      }
    });

    // A gap is an absent cell strictly between the first and last presence — the capability
    // disappeared and later came back.
    let hasGap = false;
    for (let i = firstIndex + 1; i < lastIndex; i += 1) {
      if (cells[i] === 'absent') {
        hasGap = true;
        break;
      }
    }
    const currentlyPresent = currentIndex >= 0 && cells[currentIndex] !== 'absent';

    rows.push({
      key,
      item_type: identity.item_type,
      name: identity.name,
      cells,
      firstIndex,
      lastIndex,
      presentCount,
      modifiedCount,
      hasGap,
      currentlyPresent,
      lifespan: classifyLifespan(cells, firstIndex, currentIndex, hasGap, currentlyPresent),
    });
  }

  // Group by kind (tools first), then oldest-first appearance (the gantt reads top-down by age),
  // then name for a stable order within a cohort.
  rows.sort((a, b) => {
    const kind = kindRank(a.item_type) - kindRank(b.item_type);
    if (kind !== 0) return kind;
    if (a.firstIndex !== b.firstIndex) return a.firstIndex - b.firstIndex;
    return a.name.localeCompare(b.name);
  });

  return {
    columns,
    rows,
    currentIndex,
    totalCapabilities: rows.length,
    currentCount: rows.filter((r) => r.currentlyPresent).length,
    removedCount: rows.filter((r) => !r.currentlyPresent).length,
    volatileCount: rows.filter((r) => r.hasGap).length,
    newCount: rows.filter((r) => r.lifespan === 'new').length,
  };
}

// --- Labels ----------------------------------------------------------------------------------

/** The compact axis label for a column: its sequence label (`v3`). */
export function mcpMatrixColumnLabel(column: McpMatrixColumn): string {
  return mcpVersionSeqLabel(column.version_seq);
}

/**
 * A human date/time tag for a column: its server-supplied `version_tag` when present, else the
 * formatted `discovered_at` timestamp, else the bare sequence label — mirroring {@link mcpVersionDateTag}.
 */
export function mcpMatrixColumnDateLabel(column: McpMatrixColumn): string {
  if (column.version_tag) return column.version_tag;
  if (column.discovered_at) {
    const ms = Date.parse(column.discovered_at);
    if (!Number.isNaN(ms)) return new Date(ms).toLocaleString();
  }
  return mcpVersionSeqLabel(column.version_seq);
}

/** Human label for a capability kind (mirrors the change-row wording). */
export function mcpMatrixKindLabel(itemType: string): string {
  switch (itemType) {
    case 'tool':
      return 'Tool';
    case 'resource':
      return 'Resource';
    case 'resource_template':
      return 'Resource template';
    case 'prompt':
      return 'Prompt';
    default:
      return itemType || 'Item';
  }
}

/** Human phrasing for a cell state, used in each cell's accessible label. */
export function mcpMatrixCellStateLabel(state: McpMatrixCellState): string {
  switch (state) {
    case 'added':
      return 'added';
    case 'present':
      return 'present';
    case 'modified':
      return 'modified';
    default:
      return 'absent';
  }
}

/** Human phrasing for a row's lifespan category, used in its badge. */
export function mcpMatrixLifespanLabel(lifespan: McpMatrixLifespan): string {
  switch (lifespan) {
    case 'stable':
      return 'Stable';
    case 'new':
      return 'New';
    case 'volatile':
      return 'Volatile';
    default:
      return 'Removed';
  }
}

/** The accessible label for one matrix cell: capability, snapshot, and state. */
export function mcpMatrixCellLabel(row: McpMatrixRow, column: McpMatrixColumn, state: McpMatrixCellState): string {
  return `${row.name} in ${mcpVersionSeqLabel(column.version_seq)}: ${mcpMatrixCellStateLabel(state)}`;
}

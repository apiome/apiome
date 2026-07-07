/**
 * Safety & annotation posture presentation helpers (V2-MCP-29.4 / MCAT-15.4, #4634).
 *
 * Whether a server's tools are read-only or destructive is the single most important safety signal,
 * and in the raw surface it is buried per-item in each tool's `annotations`. This module is the
 * *pure*, React-free layer that hoists that signal into a legible posture the 15.4 panel renders:
 *
 * - a per-tool **matrix** of the four behavioural hints (`readOnlyHint`, `destructiveHint`,
 *   `idempotentHint`, `openWorldHint`), each cell a tri-state (asserted / denied / unset) so a tool
 *   that says `destructiveHint: false` reads differently from one that says nothing;
 * - a headline **posture summary** (e.g. "3 destructive, 1 open-world, 8 read-only") over the tools;
 * - the endpoint's **auth posture** cross-referenced with the matrix, so *destructive tools reachable
 *   with no auth* — the combination that most warrants caution — are surfaced explicitly;
 * - a server-wide **"unannotated — treat with caution"** flag when no tool declares any hint.
 *
 * Keeping this free of React/JSX lets it be unit-tested directly and keeps the panel free of
 * counting/cross-referencing branches. Colors/spacing never appear here — each hint carries a *tone
 * token* (a {@link McpBadgeTone}) the consumer maps to classes, never a hex/Tailwind literal. The
 * hint extraction reuses {@link mcpAnnotationHints} and the auth resolution reuses {@link mcpAuthBadge}
 * so this stays the single source of truth for those mappings.
 */

import { mcpAnnotationHints, type McpCapabilityItem } from './mcpBrowseUi';
import { mcpAuthBadge, type McpBadgeTone } from './mcpUiPrimitives';

// --- Hint columns ----------------------------------------------------------------------------

/** The four MCP tool behavioural-annotation hints that form the matrix columns, in display order. */
export type McpSafetyHintKey =
  | 'readOnlyHint'
  | 'destructiveHint'
  | 'idempotentHint'
  | 'openWorldHint';

/** One matrix column: the hint it maps, its short header label, its asserted-true tone, and whether
 *  asserting it is a *risk* signal (a destructive or open-world tool warrants more caution). */
export interface McpSafetyHintColumn {
  key: McpSafetyHintKey;
  label: string;
  /** Tone token painted when the hint is asserted (mirrors {@link mcpCapabilityAnnotationBadge}). */
  tone: McpBadgeTone;
  /** True when an asserted hint raises the tool's risk posture (destructive / open-world). */
  risk: boolean;
}

/**
 * The matrix columns in display order (read-only → destructive → idempotent → open-world), matching
 * the roadmap's "read-only/destructive/idempotent/open-world hints × tools". The tones mirror the
 * shared {@link mcpCapabilityAnnotationBadge} palette (readOnly green, destructive red, idempotent
 * blue, openWorld amber) so a hint reads the same here as it does on the capability cards.
 */
export const SAFETY_HINT_COLUMNS: readonly McpSafetyHintColumn[] = [
  { key: 'readOnlyHint', label: 'Read-only', tone: 'green', risk: false },
  { key: 'destructiveHint', label: 'Destructive', tone: 'red', risk: true },
  { key: 'idempotentHint', label: 'Idempotent', tone: 'blue', risk: false },
  { key: 'openWorldHint', label: 'Open-world', tone: 'amber', risk: true },
];

/**
 * Order the headline posture summary lists its hint chips in — risk signals first (destructive,
 * open-world), then the reassuring ones (read-only, idempotent) — so "3 destructive, 1 open-world,
 * 8 read-only" leads with what a reader most needs to see.
 */
export const SAFETY_HEADLINE_ORDER: readonly McpSafetyHintKey[] = [
  'destructiveHint',
  'openWorldHint',
  'readOnlyHint',
  'idempotentHint',
];

// --- Per-tool matrix rows --------------------------------------------------------------------

/**
 * One matrix cell's tri-state for a (tool, hint) pair:
 * - `asserted` — the server set the hint to `true` (the behaviour applies);
 * - `denied`   — the server set the hint to `false` (an explicit "not this behaviour");
 * - `unset`    — the server declared nothing for this hint (absent / non-boolean).
 */
export type McpSafetyCellState = 'asserted' | 'denied' | 'unset';

/** The fallback label for a tool whose server omitted its programmatic name. */
export const UNNAMED_TOOL_LABEL = '(unnamed tool)';

/** A presentation-ready safety row for one tool: its name, per-hint cells, and derived flags. */
export interface McpToolSafetyRow {
  /** The tool's programmatic name (may be empty when the server omitted it). */
  name: string;
  /** The name to show — {@link UNNAMED_TOOL_LABEL} when the tool is unnamed. */
  displayName: string;
  /** The tool's original ordinal among the surface's tools, used as a stable key/tie-break. */
  index: number;
  /** The tri-state for each of the four hint columns. */
  cells: Record<McpSafetyHintKey, McpSafetyCellState>;
  /** True when the tool declared *no* behavioural hint at all (every cell is `unset`). */
  unannotated: boolean;
  /** True when `destructiveHint` is asserted (`true`) — the tool can make destructive changes. */
  destructive: boolean;
}

/** The set of keys {@link SAFETY_HINT_COLUMNS} covers, for fast membership tests. */
const HINT_KEYS: readonly McpSafetyHintKey[] = SAFETY_HINT_COLUMNS.map((c) => c.key);

/** Build the per-hint tri-state cells for one capability item from its declared annotation hints. */
function cellsForItem(item: McpCapabilityItem): Record<McpSafetyHintKey, McpSafetyCellState> {
  // `mcpAnnotationHints` returns only the *declared* boolean hints (true and false alike), skipping
  // absent or non-boolean ones — exactly the distinction the tri-state needs.
  const declared = new Map<string, boolean>();
  for (const hint of mcpAnnotationHints(item)) {
    declared.set(hint.key, hint.value);
  }
  const cells = {} as Record<McpSafetyHintKey, McpSafetyCellState>;
  for (const key of HINT_KEYS) {
    if (!declared.has(key)) {
      cells[key] = 'unset';
    } else {
      cells[key] = declared.get(key) ? 'asserted' : 'denied';
    }
  }
  return cells;
}

/**
 * Build the {@link McpToolSafetyRow} matrix for a version's capability items, in surface order.
 *
 * Only `tool` items are included — the behavioural hints are a tool concept, so resources, resource
 * templates, and prompts never form matrix rows. Each row's `index` is its ordinal *among the tools*
 * (0-based), so it is a stable React key even when non-tool items are interleaved in the input.
 *
 * @param items The version snapshot's capability items (all kinds), or `null` before it has loaded.
 * @returns One row per tool item, in input order; an empty array when there are no tools.
 */
export function mcpToolSafetyRows(
  items: readonly McpCapabilityItem[] | null | undefined,
): McpToolSafetyRow[] {
  if (!items) return [];
  const rows: McpToolSafetyRow[] = [];
  let toolIndex = 0;
  for (const item of items) {
    if (item.item_type !== 'tool') continue;
    const cells = cellsForItem(item);
    const name = typeof item.name === 'string' ? item.name : '';
    rows.push({
      name,
      displayName: name.trim().length > 0 ? name : UNNAMED_TOOL_LABEL,
      index: toolIndex,
      cells,
      unannotated: HINT_KEYS.every((key) => cells[key] === 'unset'),
      destructive: cells.destructiveHint === 'asserted',
    });
    toolIndex += 1;
  }
  return rows;
}

// --- Auth posture ----------------------------------------------------------------------------

/**
 * The endpoint's authentication posture, distilled from its configured `auth_type`:
 * - `anonymous`     — `auth_type` is `none`: the server is reachable with no credential;
 * - `authenticated` — a secret-bearing scheme (bearer / header / OAuth2) gates access;
 * - `unknown`       — the credential status is absent/unloaded, so we cannot assert either way.
 *
 * The `unknown` state is deliberately conservative: an unresolved auth type never triggers the
 * destructive-without-auth flag, so a failed credential fetch cannot raise a false alarm.
 */
export type McpSafetyAuthPosture = 'anonymous' | 'authenticated' | 'unknown';

/** A resolved auth posture: its state plus the badge tone + label to render it with. */
export interface McpSafetyAuth {
  authType: string | null;
  posture: McpSafetyAuthPosture;
  /** Human label for the auth badge (e.g. "No auth", "bearer", "OAuth 2.1", "Auth unknown"). */
  label: string;
  tone: McpBadgeTone;
}

/**
 * Resolve an endpoint's `auth_type` to a {@link McpSafetyAuth}. An absent/blank type is `unknown`
 * (slate "Auth unknown"); an explicit `none` is `anonymous`; any other scheme is `authenticated`,
 * with its label/tone taken from the shared {@link mcpAuthBadge} so it matches the rest of the MCP
 * surface. `unknown` is kept distinct from `anonymous` so the panel never conflates "we did not load
 * the credential" with "the server needs no auth".
 */
export function mcpSafetyAuth(authType: string | null | undefined): McpSafetyAuth {
  const value = (authType ?? '').trim().toLowerCase();
  if (value === '') {
    return { authType: null, posture: 'unknown', label: 'Auth unknown', tone: 'slate' };
  }
  if (value === 'none') {
    const badge = mcpAuthBadge('none');
    return { authType: 'none', posture: 'anonymous', label: badge.label, tone: badge.tone };
  }
  const badge = mcpAuthBadge(authType);
  return {
    authType: authType ?? null,
    posture: 'authenticated',
    label: badge.label,
    tone: badge.tone,
  };
}

// --- Posture summary ---------------------------------------------------------------------------

/** Per-hint count of tools asserting that hint (`true`). */
export type McpSafetyHintCounts = Record<McpSafetyHintKey, number>;

/** The full safety posture for a surface: matrix roll-up, auth cross-reference, and caution flags. */
export interface McpSafetyPosture {
  /** Number of tools in the surface (matrix rows). */
  totalTools: number;
  /** Tools that declared at least one hint (true *or* false). */
  annotatedTools: number;
  /** Tools that declared no hint at all. */
  unannotatedTools: number;
  /** True when there are tools but *none* declares any hint — the "treat with caution" state. */
  fullyUnannotated: boolean;
  /** Count of tools asserting each hint (`true`). */
  counts: McpSafetyHintCounts;
  /** The endpoint's resolved auth posture. */
  auth: McpSafetyAuth;
  /** Destructive tools reachable with no auth (only populated when auth is `anonymous`). */
  destructiveWithoutAuth: McpToolSafetyRow[];
}

/** Build the zeroed per-hint count map. */
function zeroCounts(): McpSafetyHintCounts {
  return { readOnlyHint: 0, destructiveHint: 0, idempotentHint: 0, openWorldHint: 0 };
}

/**
 * Roll a surface's tool safety rows and the endpoint's `auth_type` up into a {@link McpSafetyPosture}.
 *
 * Counts each hint over the tools that assert it, tallies annotated vs unannotated tools, and — when
 * the endpoint is `anonymous` (`auth_type: none`) — collects the destructive tools that are therefore
 * reachable with no auth. When the auth posture is `authenticated` or `unknown`, that list is empty,
 * so the panel only ever raises the destructive-without-auth alarm on a concrete no-auth surface.
 *
 * @param items    The version snapshot's capability items (all kinds), or `null` before load.
 * @param authType The endpoint's configured `auth_type` (`none` / `bearer` / `header` / `oauth2`),
 *                 or `null` when the credential status is unavailable.
 * @returns The rolled-up posture; safe on an empty surface (all zeroes, `fullyUnannotated: false`).
 */
export function mcpSafetyPosture(
  items: readonly McpCapabilityItem[] | null | undefined,
  authType: string | null | undefined,
): McpSafetyPosture {
  const rows = mcpToolSafetyRows(items);
  const counts = zeroCounts();
  let annotatedTools = 0;
  for (const row of rows) {
    if (!row.unannotated) annotatedTools += 1;
    for (const key of HINT_KEYS) {
      if (row.cells[key] === 'asserted') counts[key] += 1;
    }
  }
  const auth = mcpSafetyAuth(authType);
  const destructiveWithoutAuth =
    auth.posture === 'anonymous' ? rows.filter((row) => row.destructive) : [];
  const totalTools = rows.length;
  const unannotatedTools = totalTools - annotatedTools;
  return {
    totalTools,
    annotatedTools,
    unannotatedTools,
    fullyUnannotated: totalTools > 0 && annotatedTools === 0,
    counts,
    auth,
    destructiveWithoutAuth,
  };
}

// --- Headline chips ----------------------------------------------------------------------------

/** One headline summary chip: a hint, its label, the asserting-tool count, and its tone. */
export interface McpSafetyHeadlineChip {
  key: McpSafetyHintKey;
  label: string;
  count: number;
  tone: McpBadgeTone;
  risk: boolean;
}

/**
 * The non-zero headline chips for a posture, in {@link SAFETY_HEADLINE_ORDER} (risk signals first).
 * A hint with no asserting tool is omitted, so the headline reads "3 destructive, 1 open-world,
 * 8 read-only" rather than padding with zeroes. Returns an empty array when no hint is asserted.
 */
export function mcpSafetyHeadlineChips(posture: McpSafetyPosture): McpSafetyHeadlineChip[] {
  const columnByKey = new Map(SAFETY_HINT_COLUMNS.map((c) => [c.key, c]));
  const chips: McpSafetyHeadlineChip[] = [];
  for (const key of SAFETY_HEADLINE_ORDER) {
    const count = posture.counts[key];
    if (count <= 0) continue;
    const column = columnByKey.get(key);
    if (!column) continue;
    chips.push({ key, label: column.label, count, tone: column.tone, risk: column.risk });
  }
  return chips;
}

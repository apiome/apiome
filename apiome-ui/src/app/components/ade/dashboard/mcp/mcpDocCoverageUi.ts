/**
 * Documentation & schema coverage presentation helpers (V2-MCP-29.5 / MCAT-15.5, #4635).
 *
 * Poorly documented tools are hard for both humans and agents to use well, yet a server's coverage is
 * invisible today. This module is the *pure*, React-free layer that turns a snapshot's capability
 * `items` into the four coverage meters the 15.5 gauge row renders, each with the concrete
 * **drill-down** list of the items it counts against:
 *
 * - **Items described** — capability items carrying a non-empty `description`;
 * - **Items titled** — capability items carrying a non-empty `title`;
 * - **Tool params documented** — tool `input_schema` parameters carrying a `description`;
 * - **Tools with output schema** — tools declaring an `output_schema`.
 *
 * Everything is computed from the same `items` fetch the safety panel already uses (rather than the
 * rolled-up surface metrics) so a meter's percentage and its drill-down list can never disagree: the
 * offenders a meter links to are exactly the items missing from its numerator. Keeping this free of
 * React/JSX lets it be unit-tested directly and keeps the panel free of counting/coercion branches.
 * Colors/spacing never appear here — the consumer maps a percentage to a gauge/chip class.
 */

import type { McpCapabilityItem } from './mcpBrowseUi';

/** The capability `item_type` that carries parameters and an output schema. */
const TOOL_ITEM_TYPE = 'tool';

/** The fallback label for a capability item whose server omitted its programmatic name. */
export const UNNAMED_ITEM_LABEL = '(unnamed)';

// --- Defensive helpers -----------------------------------------------------------------------

/** True when `value` is a string with at least one non-whitespace character. */
function hasText(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}

/** The display label for an item: its `name`, else its `title`, else the unnamed fallback. */
function itemDisplayName(item: McpCapabilityItem): string {
  if (hasText(item.name)) return item.name;
  if (hasText(item.title)) return item.title as string;
  return UNNAMED_ITEM_LABEL;
}

/** A tool's top-level parameter tally: total declared params and how many carry a `description`. */
interface ToolParamStats {
  total: number;
  documented: number;
}

/**
 * Count a tool's top-level `input_schema.properties` and how many declare a non-empty `description`.
 * A missing/malformed schema (or one with no `properties`) yields `{ total: 0, documented: 0 }`, so a
 * parameter-less tool never inflates a denominator. A property whose value is not an object still
 * counts as a parameter (it simply cannot be documented), so a malformed schema reads as *undocumented*
 * rather than silently vanishing from the total.
 */
function toolParamStats(item: McpCapabilityItem): ToolParamStats {
  const schema = item.input_schema;
  const rawProps = schema && typeof schema === 'object' ? (schema as Record<string, unknown>).properties : null;
  if (!rawProps || typeof rawProps !== 'object') return { total: 0, documented: 0 };
  const values = Object.values(rawProps as Record<string, unknown>);
  let documented = 0;
  for (const value of values) {
    if (value && typeof value === 'object' && hasText((value as Record<string, unknown>).description)) {
      documented += 1;
    }
  }
  return { total: values.length, documented };
}

/** True when a tool declares a non-empty `output_schema` object. */
function hasOutputSchema(item: McpCapabilityItem): boolean {
  const schema = item.output_schema;
  return !!schema && typeof schema === 'object' && Object.keys(schema).length > 0;
}

// --- Drill-down offender -----------------------------------------------------------------------

/** One under-documented capability a meter links to in its drill-down. */
export interface McpDocOffender {
  /** The offending item's `item_type` (tool / resource / resource_template / prompt). */
  itemType: string;
  /** The item's programmatic name (may be empty when the server omitted it). */
  name: string;
  /** The name to show — {@link UNNAMED_ITEM_LABEL} when the item is unnamed. */
  displayName: string;
  /** Original surface ordinal, used to keep the drill-down order stable and deterministic. */
  index: number;
  /** For the *params* meter only: how many of this tool's parameters lack a `description`. */
  undocumentedParams?: number;
  /** For the *params* meter only: the tool's total parameter count. */
  totalParams?: number;
}

// --- Coverage meter ----------------------------------------------------------------------------

/** The four documentation/schema coverage meters, in display order. */
export type McpDocCoverageKey = 'described' | 'titled' | 'params' | 'output-schema';

/** A presentation-ready documentation-coverage meter: its percentage, raw counts, and drill-down. */
export interface McpDocCoverageMeter {
  key: McpDocCoverageKey;
  /** Short meter label (e.g. "Items described"). */
  label: string;
  /** One-line explanation of what the meter measures, for the gauge's caption. */
  hint: string;
  /** The plural noun the denominator counts ("items" / "parameters" / "tools"), for phrasing. */
  unit: string;
  /**
   * False when there is nothing to measure (denominator `0` — e.g. a server with no tools has no
   * parameters and no output schemas to score). The consumer renders an explicit "N/A" rather than a
   * misleading red `0%` gauge; this is what keeps a `0%` reading meaning "measured, none covered".
   */
  applicable: boolean;
  /** Coverage as a 0-100 percentage, clamped and rounded; `0` when {@link applicable} is false. */
  pct: number;
  /** The covered count (numerator). */
  have: number;
  /** The total count (denominator). */
  of: number;
  /** The specific under-documented items this meter links to; empty at 100% or when not applicable. */
  offenders: McpDocOffender[];
}

/** Clamp a raw percentage into `[0, 100]` and round it for display; non-finite reads as `0`. */
function clampPct(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.round(Math.min(100, Math.max(0, pct)));
}

/** A safe `have / of → 0-100` percentage; a zero (or missing) denominator yields `0`, never `NaN`. */
function pctOf(have: number, of: number): number {
  return of > 0 ? clampPct((have / of) * 100) : 0;
}

/** Build the base offender view (sans param counts) for an item at ordinal `index`. */
function offenderOf(item: McpCapabilityItem, index: number): McpDocOffender {
  return {
    itemType: item.item_type,
    name: item.name,
    displayName: itemDisplayName(item),
    index,
  };
}

/**
 * Compute the four {@link McpDocCoverageMeter documentation-coverage meters} for a snapshot's
 * capability `items`, in display order (described → titled → params → output-schema).
 *
 * All four are derived from the single `items` list so each meter's percentage and its drill-down are
 * guaranteed consistent — the offenders are precisely the items excluded from the numerator, in
 * surface order. `described`/`titled` score *every* capability kind; `params`/`output-schema` score
 * only tools (a resource has neither). A `null`/`undefined`/empty list yields four meters, each
 * `applicable: false` with an empty drill-down, so the caller can render a coherent (if empty) row.
 */
export function mcpDocCoverageMeters(
  items: readonly McpCapabilityItem[] | null | undefined,
): McpDocCoverageMeter[] {
  const all = items ?? [];

  // Item-level coverage (all kinds): description & title presence.
  const describedOffenders: McpDocOffender[] = [];
  const titledOffenders: McpDocOffender[] = [];
  let describedHave = 0;
  let titledHave = 0;

  // Tool-level coverage: parameter documentation and output-schema adoption.
  const paramOffenders: McpDocOffender[] = [];
  const outputSchemaOffenders: McpDocOffender[] = [];
  let toolCount = 0;
  let paramTotal = 0;
  let paramDocumented = 0;
  let outputSchemaHave = 0;

  all.forEach((item, index) => {
    if (hasText(item.description)) describedHave += 1;
    else describedOffenders.push(offenderOf(item, index));

    if (hasText(item.title)) titledHave += 1;
    else titledOffenders.push(offenderOf(item, index));

    if (item.item_type !== TOOL_ITEM_TYPE) return;
    toolCount += 1;

    const params = toolParamStats(item);
    paramTotal += params.total;
    paramDocumented += params.documented;
    if (params.total > params.documented) {
      paramOffenders.push({
        ...offenderOf(item, index),
        undocumentedParams: params.total - params.documented,
        totalParams: params.total,
      });
    }

    if (hasOutputSchema(item)) outputSchemaHave += 1;
    else outputSchemaOffenders.push(offenderOf(item, index));
  });

  const itemCount = all.length;

  return [
    {
      key: 'described',
      label: 'Items described',
      hint: 'Capabilities carrying a description agents and humans can read.',
      unit: 'items',
      applicable: itemCount > 0,
      pct: pctOf(describedHave, itemCount),
      have: describedHave,
      of: itemCount,
      offenders: describedOffenders,
    },
    {
      key: 'titled',
      label: 'Items titled',
      hint: 'Capabilities carrying a human-friendly title.',
      unit: 'items',
      applicable: itemCount > 0,
      pct: pctOf(titledHave, itemCount),
      have: titledHave,
      of: itemCount,
      offenders: titledOffenders,
    },
    {
      key: 'params',
      label: 'Tool params documented',
      hint: 'Tool parameters whose schema carries a description.',
      unit: 'parameters',
      applicable: paramTotal > 0,
      pct: pctOf(paramDocumented, paramTotal),
      have: paramDocumented,
      of: paramTotal,
      offenders: paramOffenders,
    },
    {
      key: 'output-schema',
      label: 'Tools with output schema',
      hint: 'Tools declaring a structured output schema for their result.',
      unit: 'tools',
      applicable: toolCount > 0,
      pct: pctOf(outputSchemaHave, toolCount),
      have: outputSchemaHave,
      of: toolCount,
      offenders: outputSchemaOffenders,
    },
  ];
}

/**
 * Unit tests for the pure documentation & schema coverage helpers (V2-MCP-29.5 / MCAT-15.5).
 *
 * Covers the four meters (item description / title coverage over all kinds, tool-parameter
 * documentation, output-schema adoption over tools), their percentages and raw counts, the
 * drill-down offender lists (and their consistency with each meter's numerator), the not-applicable
 * (zero-denominator) states, and the 100% / 0% edges.
 */
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  UNNAMED_ITEM_LABEL,
  mcpDocCoverageMeters,
  type McpDocCoverageKey,
  type McpDocCoverageMeter,
} from '../src/app/components/ade/dashboard/mcp/mcpDocCoverageUi';

/** Build a capability item, defaulting every optional field so a test states only what it exercises. */
function item(overrides: Partial<McpCapabilityItem>): McpCapabilityItem {
  return {
    item_type: 'tool',
    name: 'thing',
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    ...overrides,
  };
}

/** A tool with the given top-level parameters; each param is `[name, hasDescription]`. */
function toolWithParams(
  name: string,
  params: Array<[string, boolean]>,
  extra: Partial<McpCapabilityItem> = {},
): McpCapabilityItem {
  const properties: Record<string, unknown> = {};
  for (const [paramName, documented] of params) {
    properties[paramName] = documented ? { type: 'string', description: `the ${paramName}` } : { type: 'string' };
  }
  return item({ item_type: 'tool', name, input_schema: { type: 'object', properties }, ...extra });
}

/** Index the four meters by key for concise per-meter assertions. */
function byKey(items: McpCapabilityItem[] | null): Record<McpDocCoverageKey, McpDocCoverageMeter> {
  const meters = mcpDocCoverageMeters(items);
  return Object.fromEntries(meters.map((m) => [m.key, m])) as Record<
    McpDocCoverageKey,
    McpDocCoverageMeter
  >;
}

describe('mcpDocCoverageMeters', () => {
  it('returns the four meters in display order', () => {
    const keys = mcpDocCoverageMeters([]).map((m) => m.key);
    expect(keys).toEqual(['described', 'titled', 'params', 'output-schema']);
  });

  it('treats null / undefined / empty as four not-applicable, empty meters', () => {
    for (const input of [null, undefined, []]) {
      const meters = mcpDocCoverageMeters(input as McpCapabilityItem[] | null);
      for (const meter of meters) {
        expect(meter.applicable).toBe(false);
        expect(meter.pct).toBe(0);
        expect(meter.have).toBe(0);
        expect(meter.of).toBe(0);
        expect(meter.offenders).toEqual([]);
      }
    }
  });

  it('scores description & title coverage across every capability kind', () => {
    const items = [
      item({ item_type: 'tool', name: 'search', description: 'finds', title: 'Search' }),
      item({ item_type: 'resource', name: 'file', description: 'a file', title: null }),
      item({ item_type: 'prompt', name: 'greet', description: null, title: null }),
      item({ item_type: 'resource_template', name: 'doc', description: '  ', title: 'Doc' }), // blank desc
    ];
    const { described, titled } = byKey(items);

    // description: 'search' + 'file' documented; 'greet' null and 'doc' blank → 2 / 4.
    expect(described.of).toBe(4);
    expect(described.have).toBe(2);
    expect(described.pct).toBe(50);
    expect(described.offenders.map((o) => o.name)).toEqual(['greet', 'doc']);

    // title: 'search' + 'doc' titled → 2 / 4.
    expect(titled.have).toBe(2);
    expect(titled.offenders.map((o) => o.name)).toEqual(['file', 'greet']);
  });

  it('counts tool parameter documentation from input_schema.properties (tools only)', () => {
    const items = [
      toolWithParams('a', [['q', true], ['limit', false]]), // 1 / 2 documented
      toolWithParams('b', [['x', true], ['y', true], ['z', false]]), // 2 / 3 documented
      // A resource with a schema-shaped payload must never contribute to the parameter tally.
      item({ item_type: 'resource', name: 'r', input_schema: { properties: { nope: { type: 'string' } } } }),
    ];
    const { params } = byKey(items);

    expect(params.applicable).toBe(true);
    expect(params.of).toBe(5); // 2 + 3 top-level params, resource ignored
    expect(params.have).toBe(3); // 1 + 2 documented
    expect(params.pct).toBe(60);
    // Both tools have ≥1 undocumented param → both are offenders with their tallies.
    expect(params.offenders).toEqual([
      expect.objectContaining({ name: 'a', undocumentedParams: 1, totalParams: 2 }),
      expect.objectContaining({ name: 'b', undocumentedParams: 1, totalParams: 3 }),
    ]);
  });

  it('scores output-schema adoption over tools only', () => {
    const items = [
      item({ item_type: 'tool', name: 'a', output_schema: { type: 'object' } }),
      item({ item_type: 'tool', name: 'b', output_schema: null }),
      item({ item_type: 'tool', name: 'c', output_schema: {} }), // empty object ≠ declared
      item({ item_type: 'resource', name: 'r' }), // not a tool → not counted
    ];
    const { 'output-schema': outputSchema } = byKey(items);

    expect(outputSchema.of).toBe(3); // three tools
    expect(outputSchema.have).toBe(1); // only 'a'
    expect(outputSchema.offenders.map((o) => o.name)).toEqual(['b', 'c']);
  });

  it('renders 100% coverage with no offenders', () => {
    const items = [
      toolWithParams('a', [['q', true]], {
        description: 'd',
        title: 't',
        output_schema: { type: 'object' },
      }),
    ];
    const meters = mcpDocCoverageMeters(items);
    for (const meter of meters) {
      expect(meter.applicable).toBe(true);
      expect(meter.pct).toBe(100);
      expect(meter.offenders).toEqual([]);
    }
  });

  it('renders 0% coverage with every item as an offender', () => {
    const items = [
      toolWithParams('a', [['q', false]]),
      toolWithParams('b', [['x', false]]),
    ];
    const { described, params, 'output-schema': outputSchema } = byKey(items);

    expect(described.pct).toBe(0);
    expect(described.applicable).toBe(true); // measured, none covered — distinct from N/A
    expect(described.offenders).toHaveLength(2);
    expect(params.pct).toBe(0);
    expect(params.offenders).toHaveLength(2);
    expect(outputSchema.pct).toBe(0);
  });

  it('marks param & output-schema meters not-applicable when there are no tools', () => {
    const items = [
      item({ item_type: 'resource', name: 'r', description: 'd', title: 't' }),
      item({ item_type: 'prompt', name: 'p', description: 'd', title: 't' }),
    ];
    const { described, titled, params, 'output-schema': outputSchema } = byKey(items);

    // Item-level meters still apply (there are items to score).
    expect(described.applicable).toBe(true);
    expect(described.pct).toBe(100);
    expect(titled.applicable).toBe(true);
    // Tool-level meters have no denominator → not applicable, never a misleading 0%.
    expect(params.applicable).toBe(false);
    expect(params.of).toBe(0);
    expect(outputSchema.applicable).toBe(false);
    expect(outputSchema.of).toBe(0);
  });

  it('marks the param meter not-applicable when tools declare no parameters', () => {
    const items = [item({ item_type: 'tool', name: 'ping', input_schema: null })];
    const { params, 'output-schema': outputSchema } = byKey(items);
    expect(params.applicable).toBe(false); // no parameters to document
    expect(outputSchema.applicable).toBe(true); // but there is still a tool to score for output schema
    expect(outputSchema.of).toBe(1);
  });

  it('keeps a meter percentage and its drill-down consistent (offenders = of − have) for item meters', () => {
    const items = [
      item({ description: 'd', name: 'a' }),
      item({ description: null, name: 'b' }),
      item({ description: null, name: 'c' }),
    ];
    const { described } = byKey(items);
    expect(described.offenders).toHaveLength(described.of - described.have);
  });

  it('falls back to a placeholder label for an unnamed offender and preserves surface order', () => {
    const items = [
      item({ item_type: 'resource', name: '', title: null, description: null }),
      item({ item_type: 'tool', name: 'named', description: null }),
    ];
    const { described } = byKey(items);
    expect(described.offenders[0].displayName).toBe(UNNAMED_ITEM_LABEL);
    expect(described.offenders[0].index).toBe(0);
    expect(described.offenders[1].displayName).toBe('named');
    expect(described.offenders[1].index).toBe(1);
  });

  it('treats a malformed (non-object) property value as an undocumented parameter, not a crash', () => {
    const items = [
      item({ item_type: 'tool', name: 'weird', input_schema: { properties: { a: 'oops', b: { description: 'ok' } } } }),
    ];
    const { params } = byKey(items);
    expect(params.of).toBe(2);
    expect(params.have).toBe(1);
    expect(params.offenders[0]).toEqual(
      expect.objectContaining({ name: 'weird', undocumentedParams: 1, totalParams: 2 }),
    );
  });
});

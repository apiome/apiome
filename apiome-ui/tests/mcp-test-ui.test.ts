/**
 * Unit tests for the MCP Test tab model (V2-MCP-22.4 / V2-MCP-24.5, #3690 / #3701).
 */

import { describe, expect, it } from '@jest/globals';

import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  mcpBuildToolArguments,
  mcpInitialArgumentValues,
  mcpTestableTools,
  mcpTestContentText,
  mcpTestCredentialMissing,
  mcpTestOutcome,
  mcpTestResultFromPayload,
  mcpTestSummaryLine,
  mcpToolArgumentFields,
  mcpToolConfirmHints,
} from '../src/app/components/ade/dashboard/mcp/mcpTestUi';

function item(overrides: Partial<McpCapabilityItem> = {}): McpCapabilityItem {
  return {
    item_type: 'tool',
    name: 'get_forecast',
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    lifecycle: null,
    ...overrides,
  };
}

const SCHEMA = {
  type: 'object',
  required: ['city', 'days'],
  properties: {
    city: { type: 'string', title: 'City', description: 'Where to look' },
    days: { type: 'integer', default: 3 },
    ratio: { type: 'number' },
    metric: { type: 'boolean', default: true },
    units: { enum: ['c', 'f', 1] },
    filters: { type: 'object' },
    note: { type: ['string', 'null'] },
  },
};

describe('mcpTestableTools', () => {
  it('keeps tools only, in ordinal order', () => {
    const tools = mcpTestableTools([
      item({ name: 'b', ordinal: 1 }),
      item({ item_type: 'resource', name: 'r' }),
      item({ name: 'a', ordinal: 0 }),
    ]);
    expect(tools.map((t) => t.name)).toEqual(['a', 'b']);
  });

  it('is empty for no items', () => {
    expect(mcpTestableTools(null)).toEqual([]);
  });
});

describe('mcpToolArgumentFields', () => {
  it('derives one typed field per property', () => {
    const fields = mcpToolArgumentFields(SCHEMA);
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ['city', 'string', true],
      ['days', 'integer', true],
      ['ratio', 'number', false],
      ['metric', 'boolean', false],
      ['units', 'enum', false],
      ['filters', 'json', false],
      ['note', 'string', false],
    ]);
    expect(fields[0].label).toBe('City');
    expect(fields[0].description).toBe('Where to look');
    expect(fields[1].label).toBe('days');
    expect(fields[4].enumValues).toEqual(['c', 'f', '1']);
  });

  it('is empty without properties', () => {
    expect(mcpToolArgumentFields(null)).toEqual([]);
    expect(mcpToolArgumentFields({ type: 'object' })).toEqual([]);
  });
});

describe('mcpInitialArgumentValues', () => {
  it('fills schema defaults and blanks the rest', () => {
    const fields = mcpToolArgumentFields(SCHEMA);
    expect(mcpInitialArgumentValues(fields, SCHEMA)).toEqual({
      city: '',
      days: '3',
      ratio: '',
      metric: true,
      units: '',
      filters: '',
      note: '',
    });
  });

  it('maps enum and json defaults', () => {
    const schema = {
      properties: { units: { enum: ['c', 'f'], default: 'f' }, filters: { type: 'object', default: { a: 1 } } },
    };
    const values = mcpInitialArgumentValues(mcpToolArgumentFields(schema), schema);
    expect(values.units).toBe('f');
    expect(values.filters).toBe('{\n  "a": 1\n}');
  });
});

describe('mcpBuildToolArguments', () => {
  const fields = mcpToolArgumentFields(SCHEMA);

  it('types every value and omits blank optionals', () => {
    const built = mcpBuildToolArguments(fields, {
      city: 'Paris',
      days: '5',
      ratio: '0.5',
      metric: false,
      units: '1',
      filters: '{"wind": true}',
      note: '',
    });
    expect(built.errors).toEqual({});
    expect(built.arguments).toEqual({
      city: 'Paris',
      days: 5,
      ratio: 0.5,
      metric: false,
      units: 1,
      filters: { wind: true },
    });
  });

  it('reports missing required, bad numbers and bad JSON', () => {
    const built = mcpBuildToolArguments(fields, {
      city: '  ',
      days: '2.5',
      ratio: 'abc',
      metric: true,
      units: '',
      filters: '{oops',
      note: '',
    });
    expect(built.errors).toEqual({
      city: 'City is required.',
      days: 'days must be a whole number.',
      ratio: 'ratio must be a number.',
      filters: 'filters must be valid JSON.',
    });
  });
});

describe('mcpToolConfirmHints', () => {
  it('lists the asserted destructive / open-world hints only', () => {
    expect(mcpToolConfirmHints(item({ annotations: { destructiveHint: true, openWorldHint: true } }))).toEqual([
      'destructive',
      'open-world',
    ]);
    expect(mcpToolConfirmHints(item({ annotations: { destructiveHint: 'true', readOnlyHint: true } }))).toEqual([]);
    expect(mcpToolConfirmHints(null)).toEqual([]);
  });
});

describe('results', () => {
  const payload = {
    itemName: 'get_forecast',
    method: 'tools/call',
    target: 'get_forecast',
    completed: true,
    isError: false,
    content: [{ type: 'text', text: 'Sunny' }],
    structuredContent: { t: 21 },
    latencyMs: 141.6,
    error: null,
    invocationId: 'inv-1',
  };

  it('reads a payload and classifies the outcome', () => {
    const result = mcpTestResultFromPayload(payload)!;
    expect(result.structuredContent).toEqual({ t: 21 });
    expect(mcpTestOutcome(result).kind).toBe('ok');
    expect(mcpTestSummaryLine(result)).toBe('142 ms · isError: false');
    expect(mcpTestOutcome({ ...result, isError: true }).kind).toBe('tool-error');
    expect(mcpTestOutcome({ ...result, completed: false }).kind).toBe('failed');
  });

  it('reads the classified error and tolerates junk', () => {
    const failed = mcpTestResultFromPayload({ completed: false, error: { code: 'timeout', message: 'slow' } })!;
    expect(failed.error).toEqual({ code: 'timeout', message: 'slow' });
    expect(failed.content).toEqual([]);
    expect(mcpTestResultFromPayload('nope')).toBeNull();
  });

  it('renders text content as text and the rest as JSON', () => {
    expect(mcpTestContentText({ type: 'text', text: 'hi' })).toBe('hi');
    expect(mcpTestContentText({ type: 'image', mimeType: 'image/png' })).toContain('"mimeType": "image/png"');
  });
});

describe('mcpTestCredentialMissing', () => {
  it('is true only for an explicit none', () => {
    expect(mcpTestCredentialMissing('none')).toBe(true);
    expect(mcpTestCredentialMissing('bearer')).toBe(false);
    expect(mcpTestCredentialMissing(null)).toBe(false);
  });
});

/**
 * Unit tests for the private MCP browse presentation helpers (V2-MCP-23.1 / MCAT-9.1, #3691).
 *
 * Exercises the pure adapter/format functions the browse list and endpoint detail views rely on:
 * payload parsing (defensive), host-group filtering, capability grouping, and score/last-discovered
 * formatting.
 */

import {
  formatLastDiscovered,
  mcpAnnotationHints,
  mcpBrowseEndpointFromPayload,
  mcpBrowseGroupsFromPayload,
  mcpCapabilityItemFromPayload,
  mcpCapabilityLifecycleFromPayload,
  mcpEndpointDetailFromPayload,
  mcpEndpointMatchesQuery,
  mcpFilterGroups,
  mcpFormatJson,
  mcpGroupItemsByType,
  mcpItemDetailSections,
  mcpPublishTogglePatch,
  mcpScoreLabel,
  mcpScoreVariant,
  mcpVersionDetailFromPayload,
  type McpBrowseHostGroup,
} from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

describe('mcpBrowseGroupsFromPayload', () => {
  it('parses groups and rolls up endpoint capability counts', () => {
    const groups = mcpBrowseGroupsFromPayload({
      success: true,
      host_count: 1,
      endpoint_count: 1,
      groups: [
        {
          host: 'mcp.acme.example',
          endpoint_count: 1,
          capability_count: 10,
          endpoints: [
            {
              id: 'ep-1',
              name: 'Acme Weather',
              slug: 'acme-weather',
              host: 'mcp.acme.example',
              endpoint_url: 'https://mcp.acme.example/sse',
              transport: 'streamable_http',
              visibility: 'private',
              published: false,
              enabled: true,
              score: 87,
              grade: 'B',
              tool_count: 3,
              resource_count: 2,
              resource_template_count: 1,
              prompt_count: 4,
              capability_count: 10,
            },
          ],
        },
      ],
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].host).toBe('mcp.acme.example');
    expect(groups[0].endpoints[0].capability_count).toBe(10);
    expect(groups[0].endpoints[0].score).toBe(87);
  });

  it('returns an empty array for a missing/garbage payload', () => {
    expect(mcpBrowseGroupsFromPayload(null)).toEqual([]);
    expect(mcpBrowseGroupsFromPayload({})).toEqual([]);
    expect(mcpBrowseGroupsFromPayload({ groups: 'nope' })).toEqual([]);
  });

  it('derives counts when the group omits them', () => {
    const groups = mcpBrowseGroupsFromPayload({
      groups: [
        {
          host: 'h',
          endpoints: [
            { id: 'a', capability_count: 2 },
            { id: 'b', capability_count: 3 },
          ],
        },
      ],
    });
    expect(groups[0].endpoint_count).toBe(2);
    expect(groups[0].capability_count).toBe(5);
  });
});

describe('mcpBrowseEndpointFromPayload', () => {
  it('applies safe defaults for missing fields', () => {
    const ep = mcpBrowseEndpointFromPayload({ id: 'x' });
    expect(ep.host).toBe('(local)');
    expect(ep.enabled).toBe(true);
    expect(ep.published).toBe(false);
    expect(ep.score).toBeNull();
    expect(ep.capability_count).toBe(0);
    // No branding advertised → null, so the card falls back to its text form (#4656).
    expect(ep.server_branding).toBeNull();
  });

  it('parses advertised server_branding, and null for an empty block', () => {
    const branded = mcpBrowseEndpointFromPayload({
      id: 'x',
      server_branding: { icon_url: 'https://cdn.acme.dev/logo.png', website_url: 'https://acme.dev' },
    });
    expect(branded.server_branding).toEqual({
      icon_url: 'https://cdn.acme.dev/logo.png',
      website_url: 'https://acme.dev',
      icon_mime_type: null,
    });
    // An all-empty / non-object block reads back as null (never a broken image).
    expect(mcpBrowseEndpointFromPayload({ id: 'x', server_branding: {} }).server_branding).toBeNull();
    expect(
      mcpBrowseEndpointFromPayload({ id: 'x', server_branding: 'nope' }).server_branding,
    ).toBeNull();
  });
});

describe('mcpScoreVariant / mcpScoreLabel', () => {
  it('maps score bands to badge variants', () => {
    expect(mcpScoreVariant(null)).toBe('secondary');
    expect(mcpScoreVariant(95)).toBe('success');
    expect(mcpScoreVariant(80)).toBe('default');
    expect(mcpScoreVariant(60)).toBe('warning');
    expect(mcpScoreVariant(20)).toBe('error');
  });

  it('formats a score+grade label', () => {
    expect(mcpScoreLabel(null, null)).toBe('Unscored');
    expect(mcpScoreLabel(87, 'B')).toBe('87 · B');
    expect(mcpScoreLabel(87, null)).toBe('87');
  });
});

describe('formatLastDiscovered', () => {
  it('returns Never for null/invalid', () => {
    expect(formatLastDiscovered(null)).toBe('Never');
    expect(formatLastDiscovered('not-a-date')).toBe('Never');
  });

  it('formats a valid ISO timestamp', () => {
    expect(formatLastDiscovered('2026-06-26T12:00:00Z')).not.toBe('Never');
  });
});

describe('mcpEndpointMatchesQuery / mcpFilterGroups', () => {
  const groups: McpBrowseHostGroup[] = [
    {
      host: 'mcp.acme.example',
      endpoint_count: 2,
      capability_count: 7,
      endpoints: [
        mcpBrowseEndpointFromPayload({
          id: 'a',
          name: 'Weather',
          host: 'mcp.acme.example',
          category: 'weather',
          capability_count: 4,
        }),
        mcpBrowseEndpointFromPayload({
          id: 'b',
          name: 'Calendar',
          host: 'mcp.acme.example',
          category: 'time',
          capability_count: 3,
        }),
      ],
    },
    {
      host: 'beta.example',
      endpoint_count: 1,
      capability_count: 1,
      endpoints: [
        mcpBrowseEndpointFromPayload({
          id: 'c',
          name: 'Beta',
          host: 'beta.example',
          capability_count: 1,
        }),
      ],
    },
  ];

  it('matches by name, host, and category', () => {
    const ep = groups[0].endpoints[0];
    expect(mcpEndpointMatchesQuery(ep, 'weather')).toBe(true);
    expect(mcpEndpointMatchesQuery(ep, 'acme')).toBe(true);
    expect(mcpEndpointMatchesQuery(ep, 'nomatch')).toBe(false);
    expect(mcpEndpointMatchesQuery(ep, '')).toBe(true);
  });

  it('drops non-matching endpoints and empty groups, recomputing counts', () => {
    const filtered = mcpFilterGroups(groups, 'weather');
    expect(filtered).toHaveLength(1);
    expect(filtered[0].host).toBe('mcp.acme.example');
    expect(filtered[0].endpoint_count).toBe(1);
    expect(filtered[0].capability_count).toBe(4);
  });

  it('returns groups unchanged for a blank query', () => {
    expect(mcpFilterGroups(groups, '   ')).toBe(groups);
  });
});

describe('mcpVersionDetailFromPayload / mcpGroupItemsByType', () => {
  it('parses a version surface and groups items by kind in canonical order', () => {
    const version = mcpVersionDetailFromPayload({
      version: {
        id: 'v1',
        version_seq: 3,
        version_tag: '2026.06.26',
        score: 91,
        grade: 'A',
        is_current: true,
        items: [
          { item_type: 'prompt', name: 'p1' },
          { item_type: 'tool', name: 't1', title: 'Tool One' },
          { item_type: 'resource', name: 'r1', uri: 'res://x' },
          { item_type: 'tool', name: 't2' },
        ],
      },
    });
    expect(version).not.toBeNull();
    expect(version!.score).toBe(91);
    const grouped = mcpGroupItemsByType(version!.items);
    // tools first, then resources, then prompts (resource_template omitted — none present)
    expect(grouped.map((g) => g.key)).toEqual(['tool', 'resource', 'prompt']);
    expect(grouped[0].items).toHaveLength(2);
  });

  it('returns null when the payload has no version', () => {
    expect(mcpVersionDetailFromPayload({})).toBeNull();
    expect(mcpVersionDetailFromPayload(null)).toBeNull();
  });
});

describe('mcpCapabilityItemFromPayload', () => {
  it('parses schemas, annotations, and ordinal; coerces non-objects to null', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'tool',
      name: 'search',
      title: 'Search',
      input_schema: { type: 'object', properties: { q: { type: 'string' } } },
      output_schema: { type: 'object' },
      annotations: { readOnlyHint: true, title: 'Search docs' },
      ordinal: 2,
    });
    expect(item.input_schema).toEqual({
      type: 'object',
      properties: { q: { type: 'string' } },
    });
    expect(item.output_schema).toEqual({ type: 'object' });
    expect(item.annotations).toEqual({ readOnlyHint: true, title: 'Search docs' });
    expect(item.ordinal).toBe(2);
  });

  it('treats arrays and primitives as null objects and defaults ordinal to 0', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'resource',
      name: 'r',
      input_schema: ['not', 'an', 'object'],
      output_schema: 'nope',
      annotations: 42,
    });
    expect(item.input_schema).toBeNull();
    expect(item.output_schema).toBeNull();
    expect(item.annotations).toBeNull();
    expect(item.ordinal).toBe(0);
  });

  it('parses the server-computed lifecycle block onto the item (V2-MCP-34.4)', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'tool',
      name: 'old_search',
      lifecycle: {
        stage: 'deprecated',
        signals: [
          {
            id: 'mcp-lifecycle-abc',
            stage: 'deprecated',
            kind: 'annotation_flag',
            source: 'annotations',
            matched: 'deprecated=true',
            excerpt: '',
          },
        ],
        signals_truncated: 0,
      },
    });
    expect(item.lifecycle?.stage).toBe('deprecated');
    expect(item.lifecycle?.signals).toHaveLength(1);
    expect(item.lifecycle?.signals[0].matched).toBe('deprecated=true');
  });

  it('yields a null lifecycle when the API predates the field', () => {
    const item = mcpCapabilityItemFromPayload({ item_type: 'tool', name: 'search' });
    expect(item.lifecycle).toBeNull();
  });
});

describe('mcpCapabilityLifecycleFromPayload', () => {
  it('parses a full lifecycle block with signals', () => {
    const lifecycle = mcpCapabilityLifecycleFromPayload({
      stage: 'beta',
      signals: [
        {
          id: 'mcp-lifecycle-1',
          stage: 'beta',
          kind: 'name_token',
          source: 'name',
          matched: 'beta',
          excerpt: 'search_beta',
        },
      ],
      signals_truncated: 2,
    });
    expect(lifecycle).toEqual({
      stage: 'beta',
      signals: [
        {
          id: 'mcp-lifecycle-1',
          stage: 'beta',
          kind: 'name_token',
          source: 'name',
          matched: 'beta',
          excerpt: 'search_beta',
        },
      ],
      signals_truncated: 2,
    });
  });

  it('returns null for a missing/non-object payload or an absent stage', () => {
    expect(mcpCapabilityLifecycleFromPayload(undefined)).toBeNull();
    expect(mcpCapabilityLifecycleFromPayload(null)).toBeNull();
    expect(mcpCapabilityLifecycleFromPayload('deprecated')).toBeNull();
    expect(mcpCapabilityLifecycleFromPayload({ signals: [] })).toBeNull();
  });

  it('drops malformed signal entries instead of producing broken badges', () => {
    const lifecycle = mcpCapabilityLifecycleFromPayload({
      stage: 'unspecified',
      signals: ['bogus', 42, null],
      signals_truncated: 'not-a-number',
    });
    expect(lifecycle).toEqual({ stage: 'unspecified', signals: [], signals_truncated: 0 });
  });
});

describe('mcpVersionDetailFromPayload (metadata)', () => {
  it('parses server_title, protocol_version, and instructions', () => {
    const version = mcpVersionDetailFromPayload({
      version: {
        id: 'v1',
        version_seq: 1,
        server_name: 'acme-mcp',
        server_title: 'Acme MCP',
        protocol_version: '2025-06-18',
        instructions: 'Use the search tool first.',
        items: [],
      },
    });
    expect(version?.server_title).toBe('Acme MCP');
    expect(version?.protocol_version).toBe('2025-06-18');
    expect(version?.instructions).toBe('Use the search tool first.');
  });
});

describe('mcpFormatJson', () => {
  it('pretty-prints with two-space indentation', () => {
    expect(mcpFormatJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it('returns an empty string for an unserializable value (cycle)', () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    expect(mcpFormatJson(cyclic)).toBe('');
  });
});

describe('mcpItemDetailSections', () => {
  it('emits present, non-empty sections in input → output → annotations order', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'tool',
      name: 't',
      input_schema: { type: 'object' },
      annotations: { readOnlyHint: true },
    });
    const sections = mcpItemDetailSections(item);
    expect(sections.map((s) => s.key)).toEqual(['input_schema', 'annotations']);
    expect(sections[0].label).toBe('Input schema');
    expect(sections[0].json).toContain('"type": "object"');
  });

  it('skips empty objects and absent fields', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'resource',
      name: 'r',
      input_schema: {},
    });
    expect(mcpItemDetailSections(item)).toEqual([]);
  });
});

describe('mcpAnnotationHints', () => {
  it('extracts known boolean hints in spec order, skipping non-booleans and unknowns', () => {
    const item = mcpCapabilityItemFromPayload({
      item_type: 'tool',
      name: 't',
      annotations: {
        openWorldHint: false,
        readOnlyHint: true,
        destructiveHint: 'yes', // non-boolean → skipped
        somethingElse: true, // unknown → skipped
      },
    });
    const hints = mcpAnnotationHints(item);
    expect(hints.map((h) => h.key)).toEqual(['readOnlyHint', 'openWorldHint']);
    expect(hints[0]).toEqual({ key: 'readOnlyHint', label: 'Read-only', value: true });
    expect(hints[1].value).toBe(false);
  });

  it('returns an empty array when there are no annotations', () => {
    const item = mcpCapabilityItemFromPayload({ item_type: 'tool', name: 't' });
    expect(mcpAnnotationHints(item)).toEqual([]);
  });
});

describe('mcpEndpointDetailFromPayload', () => {
  it('parses an endpoint record', () => {
    const ep = mcpEndpointDetailFromPayload({
      endpoint: {
        id: 'ep-1',
        name: 'Acme',
        slug: 'acme',
        endpoint_url: 'https://mcp.acme.example/sse',
        transport: 'streamable_http',
        visibility: 'private',
        current_version_id: 'v1',
      },
    });
    expect(ep?.id).toBe('ep-1');
    expect(ep?.current_version_id).toBe('v1');
  });

  it('returns null when the payload has no endpoint', () => {
    expect(mcpEndpointDetailFromPayload({})).toBeNull();
  });
});

describe('mcpPublishTogglePatch', () => {
  it('publishing makes the endpoint public (published + visibility together)', () => {
    // An unpublished endpoint → publish: the public catalog view needs BOTH flags, so the
    // patch must flip published AND visibility, otherwise it stays private and never lists.
    expect(mcpPublishTogglePatch(false)).toEqual({ published: true, visibility: 'public' });
  });

  it('unpublishing reverts the endpoint to private', () => {
    expect(mcpPublishTogglePatch(true)).toEqual({ published: false, visibility: 'private' });
  });
});

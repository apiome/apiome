/**
 * Unit tests for capability directory helpers (V2-MCP-35.4 / MCAT-21.4, #4663).
 */

import {
  MCP_CAPABILITY_DIRECTORY_DEFAULT_FILTERS,
  mcpCapabilityDirectoryDisplayName,
  mcpCapabilityDirectoryEndpointHref,
  mcpCapabilityDirectoryEntryFromPayload,
  mcpCapabilityDirectoryFromPayload,
  mcpCapabilityDirectoryKindBadge,
  mcpCapabilityDirectoryQueryParams,
} from '../src/app/components/ade/dashboard/mcp/mcpCapabilityDirectoryUi';

describe('mcpCapabilityDirectoryFromPayload', () => {
  it('parses directory rows with owner context', () => {
    const page = mcpCapabilityDirectoryFromPayload({
      success: true,
      total: 1,
      limit: 50,
      offset: 0,
      items: [
        {
          kind: 'tool',
          item_id: 'item-1',
          item_name: 'geocode',
          item_title: 'Geocode',
          description: 'Lookup coordinates',
          endpoint_id: 'ep-1',
          endpoint_name: 'Acme Geo',
          endpoint_slug: 'acme-geo',
          host: 'mcp.acme.example',
          endpoint_url: 'https://mcp.acme.example/sse',
          visibility: 'private',
          grade: 'A',
        },
      ],
    });
    expect(page.total).toBe(1);
    expect(page.items).toHaveLength(1);
    expect(page.items[0]?.endpointSlug).toBe('acme-geo');
    expect(page.items[0]?.itemName).toBe('geocode');
  });
});

describe('mcpCapabilityDirectoryQueryParams', () => {
  it('builds filter and pagination query params', () => {
    const params = mcpCapabilityDirectoryQueryParams(
      {
        ...MCP_CAPABILITY_DIRECTORY_DEFAULT_FILTERS,
        name: 'geo',
        type: 'tool',
        host: 'mcp.acme.example',
        visibility: 'private',
      },
      'name',
      50,
      25,
    );
    expect(params.get('name')).toBe('geo');
    expect(params.get('type')).toBe('tool');
    expect(params.get('host')).toBe('mcp.acme.example');
    expect(params.get('visibility')).toBe('private');
    expect(params.get('sort')).toBe('name');
    expect(params.get('offset')).toBe('50');
    expect(params.get('limit')).toBe('25');
  });
});

describe('mcpCapabilityDirectory helpers', () => {
  it('links to endpoint detail', () => {
    expect(mcpCapabilityDirectoryEndpointHref('ep-1')).toBe('/ade/dashboard/mcp/ep-1');
  });

  it('prefers title for display name', () => {
    const entry = mcpCapabilityDirectoryEntryFromPayload({
      kind: 'prompt',
      item_id: 'p1',
      item_name: 'summarize',
      item_title: 'Summarize text',
      endpoint_id: 'ep-1',
      endpoint_name: 'Writer',
      endpoint_slug: 'writer',
      host: 'writer.example',
      endpoint_url: 'https://writer.example/mcp',
    });
    expect(entry).not.toBeNull();
    expect(mcpCapabilityDirectoryDisplayName(entry!)).toBe('Summarize text');
  });

  it('labels capability kinds', () => {
    expect(mcpCapabilityDirectoryKindBadge('resource_template').label).toBe('Resource template');
  });
});

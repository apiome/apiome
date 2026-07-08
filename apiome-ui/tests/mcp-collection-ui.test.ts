import {
  mcpCollectionCreateBody,
  mcpCollectionFromPayload,
  mcpCollectionMemberFromPayload,
  mcpCollectionPublicUrl,
  mcpCollectionsFromPayload,
  mcpVisibleEndpointIds,
} from '../src/app/components/ade/dashboard/mcp/mcpCollectionUi';

describe('mcpCollectionUi', () => {
  const sample = {
    id: 'c1',
    name: 'Geo tools',
    slug: 'geo-tools',
    description: 'Approved geo MCP servers',
    isPublished: true,
    memberCount: 1,
    createdBy: 'u1',
    createdAt: '2026-07-07T00:00:00Z',
    updatedAt: '2026-07-07T00:00:00Z',
    members: [
      {
        endpointId: 'e1',
        position: 0,
        name: 'Weather',
        slug: 'weather',
        host: 'mcp.example.com',
        grade: 'B',
        visibility: 'public',
        published: true,
        addedAt: '2026-07-07T00:00:00Z',
      },
    ],
  };

  it('parses a collection row', () => {
    const collection = mcpCollectionFromPayload(sample);
    expect(collection?.slug).toBe('geo-tools');
    expect(collection?.members?.[0]?.endpointId).toBe('e1');
  });

  it('parses a collections list envelope', () => {
    const list = mcpCollectionsFromPayload({ collections: [sample] });
    expect(list).toHaveLength(1);
  });

  it('builds a create body with optional fields', () => {
    expect(
      mcpCollectionCreateBody('Geo tools', ['e1'], {
        description: 'Curated',
        isPublished: true,
      }),
    ).toEqual({
      name: 'Geo tools',
      endpointIds: ['e1'],
      description: 'Curated',
      isPublished: true,
    });
  });

  it('builds a public share URL', () => {
    expect(mcpCollectionPublicUrl('demo', 'geo-tools')).toContain('/mcp/demo/collections/geo-tools');
  });

  it('collects visible endpoint ids from browse groups', () => {
    const ids = mcpVisibleEndpointIds([
      { endpoints: [{ id: 'a' }, { id: 'b' }] },
      { endpoints: [{ id: 'c' }] },
    ]);
    expect(ids).toEqual(['a', 'b', 'c']);
  });

  it('rejects invalid collection payloads', () => {
    expect(mcpCollectionFromPayload(null)).toBeNull();
    expect(mcpCollectionMemberFromPayload({ endpointId: 'x' })).toBeNull();
  });
});

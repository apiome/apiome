import { mcpFreshnessMeta } from '../src/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import { mcpBrowseEndpointFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

describe('mcp freshness UI helpers', () => {
  it('returns null meta for fresh endpoints', () => {
    expect(mcpFreshnessMeta('fresh')).toBeNull();
    expect(mcpFreshnessMeta(null)).toBeNull();
  });

  it('maps staleness labels to display metadata', () => {
    expect(mcpFreshnessMeta('stale')?.label).toBe('Stale');
    expect(mcpFreshnessMeta('failing')?.label).toBe('Failing');
    expect(mcpFreshnessMeta('quarantined')?.label).toBe('Quarantined');
  });

  it('parses browse freshness fields defensively', () => {
    const endpoint = mcpBrowseEndpointFromPayload({
      id: 'ep-1',
      name: 'Weather',
      freshness: 'stale',
      last_known_good_at: '2026-07-06T10:00:00Z',
    });
    expect(endpoint.freshness).toBe('stale');
    expect(endpoint.last_known_good_at).toBe('2026-07-06T10:00:00Z');
  });

  it('gives quarantined endpoints freshness precedence', () => {
    const endpoint = mcpBrowseEndpointFromPayload({
      id: 'ep-1',
      name: 'Weather',
      quarantined: true,
      freshness: 'stale',
    });
    expect(endpoint.freshness).toBe('quarantined');
  });
});

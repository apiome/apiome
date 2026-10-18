/**
 * The shadow-API report's client model (CDG-1.6, #5957): section copy, tier labels, filters.
 */

import {
  SHADOW_SECTIONS,
  confidencePercent,
  emptySectionCopy,
  environmentsOf,
  reportQuery,
  servedAt,
  tierLabel,
  type ShadowItem,
  type ShadowReport,
} from '../lib/shadow-report';
import { CONNECTOR_ITEM_ACTIONS, isConnectorItemAction } from '../lib/connector-item-actions';

function item(overrides: Partial<ShadowItem> = {}): ShadowItem {
  return {
    itemId: 'i1',
    connectorId: 'c1',
    connectorName: 'Kong',
    connectorKind: 'kong-admin',
    remoteId: 'svc',
    name: 'Service',
    environment: 'prod',
    hosts: ['api.example.com'],
    basePath: '/v2',
    status: 'discovered',
    firstSeenAt: null,
    lastSeenAt: null,
    stale: false,
    ...overrides,
  };
}

function report(overrides: Partial<ShadowReport> = {}): ShadowReport {
  return {
    generatedAt: '2026-10-18T00:00:00Z',
    filters: { connector: null, environment: null },
    connectors: [],
    stale: [],
    summary: { shadow: 0, possibleMatches: 0, drift: 0, undeployed: 0, ignored: 0 },
    shadow: [],
    possibleMatches: [],
    undeployed: [],
    drift: [],
    ignored: [],
    ...overrides,
  };
}

describe('shadow report model', () => {
  it('names the five sections in chip order, each with one sentence', () => {
    expect(SHADOW_SECTIONS.map((s) => s.key)).toEqual(['shadow', 'possibleMatches', 'drift', 'undeployed', 'ignored']);
    for (const section of SHADOW_SECTIONS) expect(section.description.split(' ').length).toBeLessThanOrEqual(16);
  });

  it('reads tiers and confidences for people', () => {
    expect(tierLabel('remote-id')).toBe('Same remote id');
    expect(tierLabel('host')).toBe('Same host');
    expect(tierLabel('title')).toBe('Similar name');
    expect(tierLabel('traffic')).toBe('traffic');
    expect(confidencePercent(0.9)).toBe('90%');
    expect(confidencePercent(1.4)).toBe('100%');
  });

  it('builds the report query from the filters', () => {
    expect(reportQuery({})).toBe('');
    expect(reportQuery({ connector: 'c 1', environment: 'prod' })).toBe('?connector=c+1&environment=prod');
  });

  it('offers the environments the rows were found in', () => {
    const r = report({
      shadow: [item({ environment: 'prod' })],
      ignored: [item({ environment: 'dev' })],
      drift: [item({ environment: null })],
    });
    expect(environmentsOf(r)).toEqual(['dev', 'prod']);
    expect(environmentsOf(null)).toEqual([]);
  });

  it('never presents a stale empty section as clean', () => {
    expect(emptySectionCopy('shadow', 0)).toMatch(/in the catalog/);
    expect(emptySectionCopy('shadow', 1)).toMatch(/stale/);
    expect(emptySectionCopy('undeployed', 1)).not.toMatch(/stale/);
  });

  it('shows where a row is served', () => {
    expect(servedAt(item())).toBe('api.example.com/v2');
    expect(servedAt(item({ hosts: ['https://x.azure-api.net/orders'] }))).toBe('https://x.azure-api.net/orders');
    expect(servedAt(item({ hosts: [], basePath: null }))).toBe('—');
  });
});

describe('connector item actions', () => {
  it('accepts only the four row actions', () => {
    expect(CONNECTOR_ITEM_ACTIONS).toEqual(['link', 'ignore', 'unignore', 'import']);
    expect(isConnectorItemAction('link')).toBe(true);
    expect(isConnectorItemAction('delete')).toBe(false);
  });
});

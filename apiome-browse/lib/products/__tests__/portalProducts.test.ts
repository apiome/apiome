import { describe, expect, it } from 'vitest';
import {
  approvalLabel,
  authStrategyLabel,
  formatLimit,
  memberKindLabel,
  normalizeLimits,
  pickPublicVersion,
  productHref,
  safeHttpUrl,
  selectorMatches,
  toPortalMember,
  toPortalPlan,
  type MemberRow,
  type PlanRow,
} from '../portalProducts';

function planRow(partial: Partial<PlanRow> = {}): PlanRow {
  return {
    slug: 'standard',
    name: 'Standard',
    description: 'For production traffic.',
    auth_strategy: 'key_auth',
    auth_config: { header_name: 'X-Api-Key' },
    limits: [{ window: 'minute', requests: 100 }],
    concurrency: null,
    approval: 'manual',
    credential_ttl_days: null,
    terms_url: null,
    pricing_note: null,
    state: 'published',
    ...partial,
  };
}

function memberRow(partial: Partial<MemberRow> = {}): MemberRow {
  return {
    kind: 'project_latest',
    name: 'Payments API',
    project_slug: 'payments',
    mcp_slug: null,
    version_selector: null,
    environment: null,
    ...partial,
  };
}

describe('productHref', () => {
  it('builds the product page path and encodes both slugs', () => {
    expect(productHref('acme', 'payments')).toBe('/tenant/acme/products/payments');
    expect(productHref('a b', 'p/q')).toBe('/tenant/a%20b/products/p%2Fq');
  });
});

describe('selectorMatches', () => {
  // The same cases as apiome-rest's app.api_products.selector_matches.
  it('treats a .x selector as a prefix range', () => {
    expect(selectorMatches('2.x', '2')).toBe(true);
    expect(selectorMatches('2.x', '2.0.0')).toBe(true);
    expect(selectorMatches('2.x', '2.9.1')).toBe(true);
    expect(selectorMatches('2.x', '20.1')).toBe(false);
    expect(selectorMatches('2.1.x', '2.1.4')).toBe(true);
    expect(selectorMatches('2.1.x', '2.2.0')).toBe(false);
  });

  it('ignores a leading v on both sides of a range', () => {
    expect(selectorMatches('v2.x', '2.3.0')).toBe(true);
    expect(selectorMatches('2.X', 'v2.3.0')).toBe(true);
  });

  it('matches any other selector exactly', () => {
    expect(selectorMatches('1.4.0', '1.4.0')).toBe(true);
    expect(selectorMatches('1.4.0', '1.4.1')).toBe(false);
    expect(selectorMatches('1.4.0', null)).toBe(false);
  });
});

describe('pickPublicVersion', () => {
  const versions = [{ label: '3.0.0' }, { label: '2.4.0' }, { label: '2.1.0' }];

  it('takes the newest version for a latest member', () => {
    expect(pickPublicVersion('project_latest', null, versions)).toBe('3.0.0');
  });

  it('takes the newest version the selector covers', () => {
    expect(pickPublicVersion('project_version', '2.x', versions)).toBe('2.4.0');
    expect(pickPublicVersion('project_version', '2.1.0', versions)).toBe('2.1.0');
  });

  it('is null when nothing public is covered', () => {
    expect(pickPublicVersion('project_version', '4.x', versions)).toBeNull();
    expect(pickPublicVersion('project_latest', null, [])).toBeNull();
  });
});

describe('toPortalPlan', () => {
  it('never carries the billing reference, environments or IdP config id', () => {
    const plan = toPortalPlan(
      planRow({
        auth_strategy: 'oauth2_client_credentials',
        auth_config: { idp_config_id: 'okta-prod', scopes: ['payments:read', 7] },
        billing_ref: 'stripe_price_123',
        environments: ['00000000-0000-0000-0000-000000000001'],
        declared_only: true,
      })
    );
    const serialized = JSON.stringify(plan);
    expect(serialized).not.toContain('stripe_price_123');
    expect(serialized).not.toContain('okta-prod');
    expect(serialized).not.toContain('00000000-0000-0000-0000-000000000001');
    expect(Object.keys(plan)).not.toContain('billingRef');
    expect(plan.scopes).toEqual(['payments:read']);
    expect(plan.headerName).toBeNull();
  });

  it('keeps the key header for a key_auth plan only', () => {
    expect(toPortalPlan(planRow()).headerName).toBe('X-Api-Key');
    expect(toPortalPlan(planRow({ auth_strategy: 'mtls' })).headerName).toBeNull();
  });

  it('folds unknown approval and state values to the safe reading', () => {
    const plan = toPortalPlan(planRow({ approval: 'whatever', state: 'deprecated' }));
    expect(plan.approval).toBe('manual');
    expect(plan.state).toBe('deprecated');
  });

  it('drops a terms URL that is not http(s)', () => {
    expect(toPortalPlan(planRow({ terms_url: 'javascript:alert(1)' })).termsUrl).toBeNull();
    expect(toPortalPlan(planRow({ terms_url: 'https://acme.test/terms' })).termsUrl).toBe('https://acme.test/terms');
  });
});

describe('normalizeLimits', () => {
  it('keeps well-formed limits, shortest window first', () => {
    expect(
      normalizeLimits([
        { window: 'day', requests: 50000 },
        { window: 'second', requests: 5 },
        { window: 'fortnight', requests: 1 },
        { window: 'hour', requests: 0 },
        { window: 'minute', requests: 1.5 },
        null,
      ])
    ).toEqual([
      { window: 'second', requests: 5 },
      { window: 'day', requests: 50000 },
    ]);
  });

  it('reads a non-array as no limits', () => {
    expect(normalizeLimits({ window: 'minute' })).toEqual([]);
    expect(normalizeLimits(null)).toEqual([]);
  });
});

describe('labels', () => {
  it('formats a limit with grouped thousands', () => {
    expect(formatLimit({ window: 'day', requests: 50000 })).toBe('50,000 requests / day');
    expect(formatLimit({ window: 'second', requests: 1 })).toBe('1 request / second');
  });

  it('names strategies, approvals and member kinds', () => {
    expect(authStrategyLabel('key_auth')).toBe('API key');
    expect(authStrategyLabel('mtls')).toBe('Mutual TLS');
    expect(authStrategyLabel('custom')).toBe('custom');
    expect(approvalLabel('auto')).toBe('Approved automatically');
    expect(approvalLabel('manual')).toBe('Approved by the API team');
    expect(memberKindLabel('project_latest')).toBe('API');
    expect(memberKindLabel('mcp_server')).toBe('MCP server');
    expect(memberKindLabel('catalog_item')).toBe('Catalog item');
  });
});

describe('safeHttpUrl', () => {
  it('accepts http(s) and refuses anything else', () => {
    expect(safeHttpUrl('http://acme.test/t')).toBe('http://acme.test/t');
    expect(safeHttpUrl('ftp://acme.test')).toBeNull();
    expect(safeHttpUrl('not a url')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });
});

describe('toPortalMember', () => {
  it('links a project member to the version it resolves to', () => {
    const member = toPortalMember('acme', memberRow({ kind: 'project_version', version_selector: '2.x' }), [
      { label: '3.0.0' },
      { label: '2.4.0' },
    ], false);
    expect(member.versionLabel).toBe('2.4.0');
    expect(member.versionSelector).toBe('2.x');
    expect(member.href).toBe('/tenant/acme/payments/2.4.0');
  });

  it('lists a project member with no public version without a link', () => {
    const member = toPortalMember('acme', memberRow(), [], false);
    expect(member.versionLabel).toBeNull();
    expect(member.href).toBeNull();
  });

  it('links a public MCP server to its catalog page, and not a private one', () => {
    const row = memberRow({ kind: 'mcp_server', name: 'Payments MCP', project_slug: null, mcp_slug: 'payments-mcp' });
    expect(toPortalMember('acme', row, [], true).href).toBe('/mcp/acme/payments-mcp');
    expect(toPortalMember('acme', row, [], false).href).toBeNull();
  });

  it('lists a catalog item by name only', () => {
    const member = toPortalMember('acme', memberRow({ kind: 'catalog_item', project_slug: null }), [], false);
    expect(member.href).toBeNull();
    expect(member.name).toBe('Payments API');
  });
});

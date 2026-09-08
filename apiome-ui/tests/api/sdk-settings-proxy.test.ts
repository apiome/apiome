/**
 * Contract tests for the SDK generation-settings proxy (SDK-3.4, #4494).
 *
 * Source-level, like the sibling governance proxies: the route's job is entirely about *where* it
 * forwards and *what it does not lose*, and both are readable without a Next.js runtime.
 */

import * as fs from 'fs';
import * as path from 'path';

const ROUTE = path.resolve(
  __dirname,
  '..',
  '..',
  'src',
  'app',
  'api',
  'sdk-settings',
  '[[...path]]',
  'route.ts',
);

const src = fs.existsSync(ROUTE) ? fs.readFileSync(ROUTE, 'utf8') : '';

describe('sdk-settings proxy route file', () => {
  it('exists as an optional catch-all', () => {
    expect(fs.existsSync(ROUTE)).toBe(true);
  });

  it('exports exactly the three verbs the surface has', () => {
    expect(src).toMatch(/export\s+async\s+function\s+GET/);
    expect(src).toMatch(/export\s+async\s+function\s+PUT/);
    expect(src).toMatch(/export\s+async\s+function\s+DELETE/);
    // There is no create/patch on this surface: a PUT replaces a scope's whole body.
    expect(src).not.toMatch(/export\s+async\s+function\s+POST/);
    expect(src).not.toMatch(/export\s+async\s+function\s+PATCH/);
  });
});

describe('session and tenant gating', () => {
  it('resolves the tenant server-side rather than trusting the browser', () => {
    expect(src).toContain('getAuthenticatedTenantContext');
    expect(src).not.toMatch(/searchParams\.get\(['"]tenant/);
  });

  it('mints the REST credential from the session', () => {
    expect(src).toContain('createRestAuthHeaders');
  });

  it('never caches a tenant-scoped read', () => {
    expect(src).toContain("cache: 'no-store'");
  });
});

describe('upstream URL shape', () => {
  it('sends the workspace scope to the tenant governance path', () => {
    expect(src).toContain('/governance/sdk-generation-settings');
  });

  it('sends a named project to the project-scoped path', () => {
    expect(src).toMatch(/\/projects\/\$\{tenant\}\/\$\{encodeURIComponent\(segments\[0\]\)\}\/sdk-settings/);
  });

  it('encodes both the tenant and the project reference', () => {
    expect(src).toContain('encodeURIComponent(tenantSlug)');
    expect(src).toContain('encodeURIComponent(segments[0])');
  });

  it('refuses a path deeper than one project, rather than forwarding it', () => {
    // Otherwise `/api/sdk-settings/a/b` would silently address something else upstream.
    expect(src).toMatch(/segments\.length > 1/);
  });

  it('forwards the query string', () => {
    expect(src).toContain('request.nextUrl.search');
  });
});

describe('refusals keep their structure', () => {
  it('lifts the stable error code onto the envelope', () => {
    expect(src).toContain("typeof shape.code === 'string'");
  });

  it('lifts the whole per-field errors list, not just the first line', () => {
    // A 422 lists every problem so a caller fixes them in one round trip; flattening it to
    // prose would throw the rest away.
    expect(src).toContain('Array.isArray(shape.errors)');
    expect(src).toContain('errors: shape.errors.map(String)');
  });

  it('still supplies a human message alongside them', () => {
    expect(src).toContain('restErrorMessage');
  });

  it('answers the standard envelope on success', () => {
    expect(src).toContain('{ success: true, data }');
  });
});

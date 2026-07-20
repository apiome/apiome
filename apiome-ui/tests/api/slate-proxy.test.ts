/**
 * Contract tests for the Slate deployment proxy route — APX-3.1 (private-suite#2456).
 *
 * `/api/slate/<...>` forwards to the REST control plane at `/v1/slate/<...>`. Rather than
 * stand up the full NextAuth + fetch stack, these assert the source-level contract the rest
 * of the feature depends on, in the same style as the Catalog and Export proxy tests.
 *
 * Two properties matter more than the rest:
 *
 * 1. **Tenancy comes from the token, not the URL.** The Slate endpoints are not
 *    tenant-slug-scoped; putting a slug in the path would make the proxy the thing that
 *    decides tenancy instead of the JWT the REST layer verifies.
 * 2. **A 409 refusal is forwarded intact.** The Release Center renders the control plane's
 *    sentence as the reason a control is disabled, so a proxy that collapsed refusals into a
 *    generic error would produce exactly the greyed-out dead end the design forbids.
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
  'slate',
  '[[...path]]',
  'route.ts'
);

const src = fs.readFileSync(ROUTE, 'utf8');

describe('slate proxy route exists', () => {
  it('is an optional catch-all so one file serves every slate path', () => {
    expect(fs.existsSync(ROUTE)).toBe(true);
  });
});

describe('verbs', () => {
  it('exports GET and POST', () => {
    expect(src).toMatch(/export\s+async\s+function\s+GET/);
    expect(src).toMatch(/export\s+async\s+function\s+POST/);
  });

  it('exports no destructive verbs', () => {
    // Releases are immutable and the audit log is append-only; there is nothing to DELETE
    // or PUT through this surface, and offering the verb would invite one.
    expect(src).not.toMatch(/export\s+async\s+function\s+(PUT|DELETE|PATCH)/);
  });
});

describe('upstream targeting', () => {
  it('forwards to the /slate REST prefix', () => {
    expect(src).toMatch(/`\/slate\$\{/);
  });

  it('does not put a tenant slug in the upstream path', () => {
    // Tenancy is decided by the JWT the REST layer verifies, not by this proxy.
    expect(src).not.toMatch(/tenantSlug/);
    expect(src).not.toMatch(/\/slate\/\$\{.*slug/i);
  });

  it('preserves the query string so environment filters reach the control plane', () => {
    expect(src).toMatch(/nextUrl\.search/);
  });

  it('encodes path segments rather than interpolating them raw', () => {
    expect(src).toMatch(/encodeURIComponent/);
  });
});

describe('authentication', () => {
  it('requires an authenticated tenant context before proxying', () => {
    expect(src).toMatch(/getAuthenticatedTenantContext/);
  });

  it('returns the auth failure status rather than proxying anonymously', () => {
    expect(src).toMatch(/status:\s*auth\.status/);
  });

  it('reuses the shared proxy helpers instead of minting its own JWT', () => {
    // A second hand-rolled copy of the signing logic is a second place for it to drift.
    expect(src).toMatch(/from\s+'@lib\/primitives-api-proxy'/);
    expect(src).not.toMatch(/jwt\.sign/);
  });
});

describe('refusal forwarding', () => {
  it('forwards the upstream status rather than normalizing it', () => {
    expect(src).toMatch(/status:\s*result\.status/);
  });

  it('forwards the structured detail body alongside the error', () => {
    expect(src).toMatch(/detail:\s*result\.data/);
  });

  it('documents that refusals must survive the trip', () => {
    expect(src).toMatch(/409/);
  });
});

describe('request bodies', () => {
  it('tolerates a missing body, because rollback and retention send none', () => {
    expect(src).toMatch(/catch\s*\{[\s\S]*body\s*=\s*undefined/);
  });
});

/**
 * Contract test for the tenant license proxy route (OLO-5.5, #4215).
 *
 * `src/app/api/tenants/license/route.ts` GET → REST `/tenants/{slug}/license`
 * (OLO-5.4). Rather than stand up the full NextAuth + fetch stack, this
 * asserts the source-level contract the license panel depends on: the route
 * exists, is GET-only, authenticates and tenant-scopes via the session, hits
 * the right REST upstream, and — critically for OLO-5.3 — passes structured
 * error `detail` payloads through instead of flattening them, so stable codes
 * like `license-seats-exhausted` survive to the client.
 */

import * as fs from 'fs';
import * as path from 'path';

const routePath = path.resolve(
  __dirname,
  '..',
  '..',
  'src',
  'app',
  'api',
  'tenants',
  'license',
  'route.ts',
);
const route = fs.readFileSync(routePath, 'utf8');

describe('tenant license proxy (GET /api/tenants/license)', () => {
  it('exports only a GET handler', () => {
    expect(route).toMatch(/export\s+async\s+function\s+GET/);
    expect(route).not.toMatch(/export\s+async\s+function\s+(POST|PUT|PATCH|DELETE)/);
  });

  it('authenticates the session and resolves the current tenant slug', () => {
    expect(route).toContain('getAuthSession');
    expect(route).toContain('current_tenant_id');
    expect(route).toContain('getTenantById');
    // Unauthenticated and tenant-less sessions are rejected before proxying.
    expect(route).toMatch(/status:\s*401/);
    expect(route).toMatch(/status:\s*400/);
  });

  it('targets the OLO-5.4 REST license upstream with REST auth headers', () => {
    expect(route).toContain('REST_API_BASE_URL');
    expect(route).toContain('createRestAuthHeaders');
    expect(route).toMatch(/\/tenants\/\$\{encodeURIComponent\(tenant\.slug\)\}\/license/);
  });

  it('returns the { success, ... } envelope and preserves structured error detail', () => {
    expect(route).toMatch(/success:\s*true/);
    // The FastAPI detail is forwarded as-is (no `typeof detail === 'string'`
    // flattening) so OLO-5.3 {code, message} payloads reach the client.
    expect(route).toMatch(/data\?\.detail\s*\?\?/);
  });
});

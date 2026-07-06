/**
 * Contract test for the one-call Verify proxy route (MFX-42.1, #4354).
 *
 * The Studio's Verify workbench reaches the REST spine through a thin proxy at
 * `src/app/api/export/verify/route.ts`, cloned from the export preview proxy. Rather than stand
 * up the full NextAuth + fetch stack, this asserts the source-level contract the feature depends
 * on: the route exists, is POST-only, authenticates + tenant-scopes via the shared helper, targets
 * the REST `/export/{tenantSlug}/verify` upstream (MFX-42.5), and returns the `{ success, ... }`
 * envelope the `useExportVerify` hook expects. If the proxy is deleted or its upstream path/shape
 * drifts from the REST verify contract, this goes red.
 */

import * as fs from 'fs';
import * as path from 'path';

const VERIFY_ROUTE = path.resolve(
  __dirname,
  '..',
  '..',
  'src',
  'app',
  'api',
  'export',
  'verify',
  'route.ts',
);

const src = fs.readFileSync(VERIFY_ROUTE, 'utf8');

describe('export verify proxy (POST /api/export/verify)', () => {
  it('exists and exports only a POST handler (verify is a write-shaped dry run)', () => {
    expect(fs.existsSync(VERIFY_ROUTE)).toBe(true);
    expect(src).toMatch(/export\s+async\s+function\s+POST/);
    expect(src).not.toMatch(/export\s+async\s+function\s+(GET|PUT|DELETE)/);
  });

  it('authenticates and tenant-scopes via the shared proxy helper', () => {
    expect(src).toContain('getAuthenticatedTenantContext');
    expect(src).toContain('proxyRestPost');
  });

  it('targets the REST /export/{tenantSlug}/verify upstream (MFX-42.5)', () => {
    expect(src).toMatch(/\/export\/\$\{ctx\.tenantSlug\}\/verify/);
  });

  it('returns the { success, ... } envelope the verify hook consumes', () => {
    expect(src).toMatch(/success:\s*true/);
    expect(src).toMatch(/success:\s*false/);
  });

  it('rejects a missing request body with a 400', () => {
    expect(src).toMatch(/Missing request body/);
    expect(src).toMatch(/status:\s*400/);
  });
});

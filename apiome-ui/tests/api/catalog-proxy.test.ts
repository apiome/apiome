/**
 * Contract tests for the Catalog API proxy routes (MFI-23.2, #4011).
 *
 * The Catalog screen reaches the REST spine through thin proxy routes under
 * `src/app/api/catalog`, cloned from the Projects proxy. Rather than stand up the full NextAuth +
 * fetch stack, these tests assert the source-level contract that the rest of the feature depends on:
 * the routes exist, build the correct upstream `${REST_API_BASE_URL}/catalog/...` URL shape (so the
 * golden-path contract stays green), require a session, forward `include_deleted`, and return the
 * documented response envelope keys. If a proxy is deleted or its upstream path/shape drifts from the
 * REST `/v1/catalog` contract, this goes red.
 */

import * as fs from 'fs';
import * as path from 'path';

const API_ROOT = path.resolve(__dirname, '..', '..', 'src', 'app', 'api', 'catalog');
const LIST_ROUTE = path.join(API_ROOT, 'route.ts');
const DETAIL_ROUTE = path.join(API_ROOT, '[itemId]', 'route.ts');
const SOURCE_ROUTE = path.join(API_ROOT, '[itemId]', 'source', 'route.ts');

function read(file: string): string {
  return fs.readFileSync(file, 'utf8');
}

describe('catalog proxy route files exist', () => {
  it('has a list route and an item-detail route', () => {
    expect(fs.existsSync(LIST_ROUTE)).toBe(true);
    expect(fs.existsSync(DETAIL_ROUTE)).toBe(true);
  });

  it('has a source-material route (MFI-23.9)', () => {
    expect(fs.existsSync(SOURCE_ROUTE)).toBe(true);
  });
});

describe('catalog list proxy (GET /api/catalog)', () => {
  const src = read(LIST_ROUTE);

  it('exports a GET handler and no write handlers (catalog is read-only here)', () => {
    expect(src).toMatch(/export\s+async\s+function\s+GET/);
    expect(src).not.toMatch(/export\s+async\s+function\s+(POST|PUT|DELETE)/);
  });

  it('targets the REST /catalog/{tenantSlug} upstream', () => {
    expect(src).toMatch(/\$\{REST_API_BASE_URL\}\/catalog\/\$\{tenantSlug\}/);
  });

  it('requires a session and a selected tenant', () => {
    expect(src).toContain('getAuthSession');
    expect(src).toMatch(/Unauthorized/);
    expect(src).toMatch(/No tenant selected/);
  });

  it('forwards the include_deleted flag for trash/restore parity with projects', () => {
    expect(src).toContain("searchParams.get('include_deleted')");
    expect(src).toContain('include_deleted=true');
  });

  it('returns the { success, catalog } envelope', () => {
    expect(src).toMatch(/success:\s*true,\s*catalog:\s*data/);
  });
});

describe('catalog detail proxy (GET /api/catalog/[itemId])', () => {
  const src = read(DETAIL_ROUTE);

  it('exports a GET handler and no write handlers', () => {
    expect(src).toMatch(/export\s+async\s+function\s+GET/);
    expect(src).not.toMatch(/export\s+async\s+function\s+(POST|PUT|DELETE)/);
  });

  it('targets the REST /catalog/{tenantSlug}/{itemId} upstream', () => {
    expect(src).toMatch(/\$\{REST_API_BASE_URL\}\/catalog\/\$\{tenantSlug\}\/\$\{itemId\}/);
  });

  it('requires a session and a selected tenant', () => {
    expect(src).toContain('getAuthSession');
    expect(src).toMatch(/Unauthorized/);
    expect(src).toMatch(/No tenant selected/);
  });

  it('returns the { success, item } envelope', () => {
    expect(src).toMatch(/success:\s*true,\s*item:\s*data/);
  });
});

describe('catalog source proxy (GET /api/catalog/[itemId]/source)', () => {
  const src = read(SOURCE_ROUTE);

  it('exports a GET handler and no write handlers', () => {
    expect(src).toMatch(/export\s+async\s+function\s+GET/);
    expect(src).not.toMatch(/export\s+async\s+function\s+(POST|PUT|DELETE)/);
  });

  it('targets the REST /catalog/{tenantSlug}/{itemId}/source upstream', () => {
    expect(src).toMatch(/\$\{REST_API_BASE_URL\}\/catalog\/\$\{tenant\.slug\}\/\$\{itemId\}\/source/);
  });

  it('requires a session and a selected tenant', () => {
    expect(src).toContain('getAuthSession');
    expect(src).toMatch(/Unauthorized/);
    expect(src).toMatch(/No tenant selected/);
  });

  it('does not follow the upstream redirect server-side (SSRF guard)', () => {
    expect(src).toMatch(/redirect:\s*'manual'/);
    expect(src).toContain('NextResponse.redirect');
  });

  it('passes the download content-disposition through for captured content', () => {
    expect(src).toContain('content-disposition');
  });
});

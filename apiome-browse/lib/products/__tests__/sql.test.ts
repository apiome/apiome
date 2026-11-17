import { describe, expect, it } from 'vitest';
import {
  MEMBER_PUBLIC_VERSIONS_SQL,
  PORTAL_PRODUCT_MEMBERS_SQL,
  PORTAL_PRODUCT_PLANS_SQL,
  PORTAL_PRODUCT_SQL,
  PORTAL_PRODUCTS_FOR_TENANT_SQL,
  PRODUCT_LIFECYCLE_FOR_PROJECT_SQL,
} from '../sql';

const ALL = [
  PRODUCT_LIFECYCLE_FOR_PROJECT_SQL,
  MEMBER_PUBLIC_VERSIONS_SQL,
  PORTAL_PRODUCT_MEMBERS_SQL,
  PORTAL_PRODUCT_PLANS_SQL,
  PORTAL_PRODUCT_SQL,
  PORTAL_PRODUCTS_FOR_TENANT_SQL,
];

describe('portal product statements', () => {
  it('never select a private plan column', () => {
    for (const text of ALL) {
      expect(text).not.toMatch(/billing_ref/);
      expect(text).not.toMatch(/\benvironments\b/);
      expect(text).not.toMatch(/declared_only/);
      expect(text).not.toMatch(/SELECT\s+\*|pl\.\*/);
    }
  });

  it('gate products on portal visibility, a portal state and liveness', () => {
    for (const text of [PORTAL_PRODUCT_SQL, PORTAL_PRODUCTS_FOR_TENANT_SQL]) {
      expect(text).toContain("ap.visibility = 'portal'");
      expect(text).toContain("ap.state IN ('published', 'deprecated')");
      expect(text).toContain('ap.deleted_at IS NULL');
      expect(text).toContain('t.deleted_at IS NULL');
    }
  });

  it('gate plans on a portal state and liveness', () => {
    for (const text of [PORTAL_PRODUCT_PLANS_SQL, PORTAL_PRODUCTS_FOR_TENANT_SQL]) {
      expect(text).toContain("pl.state IN ('published', 'deprecated')");
      expect(text).toContain('pl.deleted_at IS NULL');
    }
  });

  it('link members only to public published versions and public MCP servers', () => {
    expect(MEMBER_PUBLIC_VERSIONS_SQL).toContain('v.published = true');
    expect(MEMBER_PUBLIC_VERSIONS_SQL).toContain("v.visibility = 'public'");
    expect(PORTAL_PRODUCT_MEMBERS_SQL).toContain('apiome.mcp_v_public_endpoints');
  });

  it('keep every read inside the product tenant', () => {
    expect(PORTAL_PRODUCT_MEMBERS_SQL).toContain('p.tenant_id = m.tenant_id');
    expect(PORTAL_PRODUCT_MEMBERS_SQL).toContain('e.tenant_id = m.tenant_id');
    expect(PORTAL_PRODUCT_PLANS_SQL).toContain('pl.tenant_id = $1 AND pl.product_id = $2');
  });

  it('reads lifecycle news only for portal products that include the API (APX-1.4)', () => {
    const text = PRODUCT_LIFECYCLE_FOR_PROJECT_SQL;
    expect(text).toContain("ap.visibility = 'portal'");
    expect(text).toContain("ap.state IN ('published', 'deprecated')");
    expect(text).toContain("pl.state = 'deprecated' AND pl.deleted_at IS NULL");
    expect(text).toContain("s.state IN ('published', 'deprecated') AND s.deleted_at IS NULL");
    expect(text).toContain("m.member_kind <> 'mcp_server' AND m.member_ref = $2::uuid");
    expect(text).toContain("(ap.state = 'deprecated' OR pl.id IS NOT NULL)");
    expect(text).toContain('s.tenant_id = ap.tenant_id');
  });
});

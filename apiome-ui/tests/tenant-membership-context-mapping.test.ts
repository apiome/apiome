/**
 * Unit tests for the tenant-switcher membership mapping (OLO-6.1, #4218):
 * REST item → switcher row, and the create-tenant cap gate mirroring the
 * OLO-5.3 REST guard.
 */
import {
  DEFAULT_FREE_MAX_TENANTS,
  mapRestMembershipToRow,
  resolveCreateTenantGate,
  type RestTenantMembership,
} from '../lib/auth/tenant-membership-context-mapping';

describe('mapRestMembershipToRow', () => {
  const item: RestTenantMembership = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    slug: 'acme-corp',
    name: 'Acme Corp',
    role: 'owner',
    status: 'active',
    license_name: 'Free',
    license_type: 'free',
  };

  it('maps every enriched field onto the row', () => {
    expect(mapRestMembershipToRow(item)).toEqual({
      id: '550e8400-e29b-41d4-a716-446655440000',
      slug: 'acme-corp',
      name: 'Acme Corp',
      role: 'owner',
      status: 'active',
      licenseName: 'Free',
      licenseType: 'free',
    });
  });

  it('normalizes an unlicensed tenant (missing license fields) to nulls', () => {
    const unlicensed = { ...item, license_name: undefined, license_type: undefined };
    const row = mapRestMembershipToRow(unlicensed);
    expect(row.licenseName).toBeNull();
    expect(row.licenseType).toBeNull();
  });

  it('tolerates a null name', () => {
    const row = mapRestMembershipToRow({ ...item, name: null as unknown as string });
    expect(row.name).toBe('');
  });
});

describe('resolveCreateTenantGate', () => {
  it('allows creation while under the cap', () => {
    expect(resolveCreateTenantGate(0, 1)).toEqual({ allowed: true, used: 0, max: 1 });
    expect(resolveCreateTenantGate(2, 5)).toEqual({ allowed: true, used: 2, max: 5 });
  });

  it('blocks at the cap, matching the REST guard (current >= max blocks)', () => {
    expect(resolveCreateTenantGate(1, 1).allowed).toBe(false);
    expect(resolveCreateTenantGate(6, 5).allowed).toBe(false);
  });

  it('treats a non-positive max as blocked, like the REST guard would', () => {
    expect(resolveCreateTenantGate(0, 0).allowed).toBe(false);
    expect(resolveCreateTenantGate(0, -1).allowed).toBe(false);
  });

  it('exposes the Free default used when a user has no entitlement row', () => {
    expect(DEFAULT_FREE_MAX_TENANTS).toBe(1);
  });
});

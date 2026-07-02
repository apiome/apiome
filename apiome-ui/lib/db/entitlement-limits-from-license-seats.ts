/**
 * Maps `licenses.seats` JSONB into the columns stored on `apiome.user_entitlements`.
 * Omitted keys fall back to the same defaults as the free tier signup row.
 * Any negative numeric value is treated as unlimited (-1) for enforcement.
 *
 * Kept outside `plan-entitlements.ts` so that file can remain a Server Actions module (`'use server'`)
 * with only async exports.
 */
export function entitlementLimitsFromLicenseSeats(seats: unknown): {
  max_tenants: number;
  max_projects: number;
  max_versions: number;
} {
  let raw: unknown = seats;
  if (typeof seats === 'string') {
    try {
      raw = JSON.parse(seats) as unknown;
    } catch {
      raw = {};
    }
  }
  const s =
    raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};

  const pick = (key: string, fallback: number): number => {
    const v = s[key];
    if (v === undefined || v === null) return fallback;
    const n = typeof v === 'number' ? v : Number.parseInt(String(v), 10);
    if (!Number.isFinite(n)) return fallback;
    if (n < 0) return -1;
    return Math.min(Number.MAX_SAFE_INTEGER, Math.floor(n));
  };

  return {
    max_tenants: pick('max_tenants', 1),
    max_projects: pick('max_projects', 1),
    max_versions: pick('max_versions', 3),
  };
}

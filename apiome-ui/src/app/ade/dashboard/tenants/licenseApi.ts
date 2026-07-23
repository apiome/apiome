/**
 * Client helpers for the tenant license panel (OLO-5.5, #4215).
 *
 * Talks to the `/api/tenants/license` proxy, which forwards to apiome-rest
 * `GET /v1/tenants/{slug}/license` (OLO-5.4). Types mirror the REST
 * snake_case response models.
 */

/** The tenant's attached plan; null when the tenant predates the license backfill. */
export interface TenantLicensePlan {
  /** Plan display name, e.g. 'Free'. */
  name: string;
  /** Billing classification: 'free', 'paid', or 'sponsor'. */
  type: string;
}

/** Member-seat usage against the license limit. */
export interface TenantLicenseSeats {
  /** Seats occupied (active + pending members). */
  used: number;
  /** Seat limit from the license (Free default when unlicensed). */
  max: number;
}

/** The plan quota limits stored on the license (#64). `-1` means unlimited. */
export interface TenantLicenseQuotas {
  /** Projects the plan allows (-1 = unlimited, Free default 1). */
  max_projects: number;
  /** Published versions per project the plan allows (-1 = unlimited, Free default 3). */
  max_versions: number;
  /** AI-assistant requests the plan allows (-1 = unlimited, 0 = none, Free default 0). */
  max_ai_requests: number;
}

/** One feature flag in the tenant's effective composition. */
export interface TenantLicenseFeature {
  /** Machine slug, e.g. 'designer'. */
  name: string;
  /** Human-readable label. */
  label: string;
  /** What the feature does. */
  description: string | null;
  /** Show a 'Preview' badge when true. */
  is_preview: boolean;
  /** Effective state after license/override composition. */
  enabled: boolean;
  /** Where the state came from: 'license' or 'tenant-override'. */
  source: string;
}

/** Payload of `GET /api/tenants/license`. */
export interface TenantLicenseResponse {
  plan: TenantLicensePlan | null;
  seats: TenantLicenseSeats;
  quotas: TenantLicenseQuotas;
  features: TenantLicenseFeature[];
}

/**
 * Unwrap the proxy's `{success, data | error}` envelope.
 *
 * @throws Error whose message carries the proxy error. When the error is a
 *   structured payload (an OLO-5.3 `{code, message}` detail), it is serialized
 *   so `licenseErrors.describeLicenseError` can still recognize the code.
 */
async function readProxyJson<T>(res: Response): Promise<T> {
  const json = await res.json();
  if (!json.success) {
    const err = json.error;
    if (typeof err === 'object' && err !== null) {
      const message = (err as { message?: string }).message;
      // Keep the stable code in the message so downstream helpers can map it.
      const code = (err as { code?: string }).code;
      throw new Error(code ? `${message || 'Request failed'} [${code}]` : message || 'Request failed');
    }
    throw new Error(err || 'Request failed');
  }
  return json.data as T;
}

/** Load the current tenant's plan, seat usage, and effective features. */
export async function fetchTenantLicense(): Promise<TenantLicenseResponse> {
  const res = await fetch('/api/tenants/license', { cache: 'no-store' });
  return readProxyJson<TenantLicenseResponse>(res);
}

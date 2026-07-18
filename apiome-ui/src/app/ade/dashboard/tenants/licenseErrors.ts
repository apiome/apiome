/**
 * Friendly rendering of the stable OLO-5.3 license error codes (#4215).
 *
 * apiome-rest's license enforcement guards reject over-limit writes with a
 * structured 403 `detail` payload `{code, message}`. The codes are a stable
 * machine contract:
 *
 * - `license-seats-exhausted` — every member seat allowed by the tenant's
 *   license is occupied (member add/invite/reinstate paths).
 * - `tenant-cap-reached` — the user's entitlements do not allow creating
 *   another tenant (first-tenant/onboarding provisioning path).
 *
 * Any surface that talks to those REST paths can run the error payload it
 * received through {@link describeLicenseError} to show upgrade guidance
 * instead of a raw API error. The helpers are deliberately tolerant about
 * payload shape: proxies wrap the FastAPI `detail` differently (`error`,
 * `detail`, plain object, or a flattened string), and all of those unwrap to
 * the same code.
 */

/** Stable code for "all member seats in use" (mirrors apiome-rest OLO-5.3). */
export const LICENSE_SEATS_EXHAUSTED_CODE = 'license-seats-exhausted';

/** Stable code for "user cannot create more tenants" (mirrors apiome-rest OLO-5.3). */
export const TENANT_CAP_REACHED_CODE = 'tenant-cap-reached';

/** A structured license error extracted from an API error payload. */
export interface LicenseErrorDetail {
  /** One of the stable OLO-5.3 codes. */
  code: string;
  /** Server-provided human message, when present. */
  message?: string;
}

/** All codes {@link extractLicenseError} recognizes. */
const KNOWN_CODES: ReadonlySet<string> = new Set([
  LICENSE_SEATS_EXHAUSTED_CODE,
  TENANT_CAP_REACHED_CODE,
]);

/** Friendly, actionable copy per code — shown instead of the raw API message. */
const FRIENDLY_MESSAGES: Record<string, string> = {
  [LICENSE_SEATS_EXHAUSTED_CODE]:
    "All member seats included in this tenant's license are in use. " +
    'Suspend or remove a member, or upgrade the plan, to add more members.',
  [TENANT_CAP_REACHED_CODE]:
    'Your account has reached the maximum number of tenants its plan allows. ' +
    'Upgrade your plan to create more tenants.',
};

/**
 * Pull a structured OLO-5.3 license error out of an arbitrary error payload.
 *
 * Handles the shapes the REST error travels in:
 * - the raw FastAPI detail object: `{code, message}`
 * - a proxy envelope: `{detail: {...}}` or `{error: {...}}` (one level deep)
 * - a string that contains one of the stable codes (a proxy that flattened
 *   the payload, or a serialized detail)
 *
 * @param payload Anything caught from a license-guarded API call.
 * @returns The `{code, message}` detail when a known code is found, else null.
 */
export function extractLicenseError(payload: unknown): LicenseErrorDetail | null {
  if (payload == null) return null;

  if (typeof payload === 'string') {
    for (const code of KNOWN_CODES) {
      if (payload.includes(code)) return { code };
    }
    return null;
  }

  if (payload instanceof Error) {
    return extractLicenseError(payload.message);
  }

  if (typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    const code = obj.code;
    if (typeof code === 'string' && KNOWN_CODES.has(code)) {
      return {
        code,
        message: typeof obj.message === 'string' ? obj.message : undefined,
      };
    }
    // Common proxy envelopes wrap the detail one level down.
    return extractLicenseError(obj.detail ?? obj.error ?? null);
  }

  return null;
}

/**
 * Map an API error payload to friendly license guidance.
 *
 * @param payload Anything caught from a license-guarded API call.
 * @returns Actionable copy for a recognized OLO-5.3 code (falling back to the
 *   server's own message when no local copy exists), or null when the payload
 *   is not a license error — callers then show their normal error text.
 */
export function describeLicenseError(payload: unknown): string | null {
  const detail = extractLicenseError(payload);
  if (!detail) return null;
  return FRIENDLY_MESSAGES[detail.code] ?? detail.message ?? null;
}

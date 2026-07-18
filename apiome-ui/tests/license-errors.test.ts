/**
 * Unit tests for the OLO-5.3 license error helpers (OLO-5.5, #4215).
 *
 * The stable codes (`license-seats-exhausted`, `tenant-cap-reached`) travel in
 * several shapes depending on which proxy handled the REST 403 — a raw
 * `{code, message}` detail, a wrapped `{detail}`/`{error}` envelope, or a
 * flattened string. Every shape must unwrap to the same friendly guidance,
 * and non-license errors must pass through untouched (null).
 */

import {
  describeLicenseError,
  extractLicenseError,
  LICENSE_SEATS_EXHAUSTED_CODE,
  TENANT_CAP_REACHED_CODE,
} from '../src/app/ade/dashboard/tenants/licenseErrors';

describe('extractLicenseError', () => {
  it('reads a raw FastAPI detail object', () => {
    const detail = extractLicenseError({
      code: LICENSE_SEATS_EXHAUSTED_CODE,
      message: 'All 5 seats are in use.',
    });
    expect(detail).toEqual({
      code: LICENSE_SEATS_EXHAUSTED_CODE,
      message: 'All 5 seats are in use.',
    });
  });

  it('unwraps one-level proxy envelopes ({detail} and {error})', () => {
    expect(
      extractLicenseError({ detail: { code: TENANT_CAP_REACHED_CODE } })?.code,
    ).toBe(TENANT_CAP_REACHED_CODE);
    expect(
      extractLicenseError({ error: { code: LICENSE_SEATS_EXHAUSTED_CODE } })?.code,
    ).toBe(LICENSE_SEATS_EXHAUSTED_CODE);
  });

  it('recognizes a code embedded in a flattened string or Error message', () => {
    expect(
      extractLicenseError(`Request failed [${LICENSE_SEATS_EXHAUSTED_CODE}]`)?.code,
    ).toBe(LICENSE_SEATS_EXHAUSTED_CODE);
    expect(
      extractLicenseError(new Error(`403: ${TENANT_CAP_REACHED_CODE}`))?.code,
    ).toBe(TENANT_CAP_REACHED_CODE);
  });

  it('returns null for unrelated payloads', () => {
    expect(extractLicenseError(null)).toBeNull();
    expect(extractLicenseError(undefined)).toBeNull();
    expect(extractLicenseError('User not found')).toBeNull();
    expect(extractLicenseError({ code: 'some-other-code' })).toBeNull();
    expect(extractLicenseError({ detail: 'plain string detail' })).toBeNull();
    expect(extractLicenseError(42)).toBeNull();
  });

  it('ignores a non-string code property', () => {
    expect(extractLicenseError({ code: 123 })).toBeNull();
  });
});

describe('describeLicenseError', () => {
  it('maps seats-exhausted to actionable upgrade guidance', () => {
    const copy = describeLicenseError({ code: LICENSE_SEATS_EXHAUSTED_CODE });
    expect(copy).toMatch(/member seats/i);
    expect(copy).toMatch(/upgrade/i);
  });

  it('maps tenant-cap-reached to actionable upgrade guidance', () => {
    const copy = describeLicenseError({ code: TENANT_CAP_REACHED_CODE });
    expect(copy).toMatch(/maximum number of tenants/i);
    expect(copy).toMatch(/upgrade/i);
  });

  it('returns null for non-license errors so callers keep their own copy', () => {
    expect(describeLicenseError(new Error('network down'))).toBeNull();
    expect(describeLicenseError('Failed to fetch')).toBeNull();
  });
});

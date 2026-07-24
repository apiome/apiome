/**
 * Tests for the OLO-10.13 journey TOTP helper (`e2e/journey/support/totp.ts`).
 *
 * The 2FA journey generates live TOTP codes to satisfy Better Auth's verifier, so correctness against
 * the RFC 6238 reference is what makes those legs trustworthy. Validates the SHA1/6-digit/30s default
 * against the RFC 6238 Appendix B vector and the otpauth-URI secret parser.
 */
import { generateTotp, parseTotpSecret } from '../e2e/journey/support/totp';

describe('journey TOTP helper', () => {
  // RFC 6238 Appendix B: ASCII secret "12345678901234567890" (base32 GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ),
  // SHA1, at T=59s the 8-digit code is 94287082 → the 6-digit truncation is 287082.
  const RFC6238_SECRET_BASE32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';

  it('matches the RFC 6238 reference vector (SHA1, 6 digits, 30s step)', () => {
    expect(generateTotp(RFC6238_SECRET_BASE32, 59_000)).toBe('287082');
  });

  it('produces a stable 6-digit code within the same 30s window', () => {
    const code = generateTotp(RFC6238_SECRET_BASE32, 10_000);
    expect(code).toMatch(/^\d{6}$/);
    // 10s and 20s fall in the same step (counter 0), so the code is identical.
    expect(generateTotp(RFC6238_SECRET_BASE32, 20_000)).toBe(code);
  });

  it('rolls to a different code in the next 30s window', () => {
    const first = generateTotp(RFC6238_SECRET_BASE32, 0);
    const next = generateTotp(RFC6238_SECRET_BASE32, 30_000);
    expect(next).not.toBe(first);
  });

  it('extracts the secret from an otpauth:// enrollment URI', () => {
    const uri = `otpauth://totp/apiome:user@example.com?secret=${RFC6238_SECRET_BASE32}&issuer=apiome&algorithm=SHA1&digits=6&period=30`;
    expect(parseTotpSecret(uri)).toBe(RFC6238_SECRET_BASE32);
  });

  it('throws when the otpauth URI has no secret', () => {
    expect(() => parseTotpSecret('otpauth://totp/apiome:user@example.com?issuer=apiome')).toThrow();
  });
});

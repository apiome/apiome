/**
 * Tests for signed super-admin session tokens (OLO-8.1, #4967).
 *
 * Covers the acceptance criteria: a hand-forged cookie is rejected, valid
 * sessions verify by signature, and expiry is still enforced. Also exercises the
 * signing-key resolution (dedicated secret vs. password-derived vs. none).
 */
import { createHmac } from 'crypto';
import {
  createAdminSessionToken,
  verifyAdminSessionToken,
  ADMIN_SESSION_MAX_AGE_MS,
} from '@lib/auth/admin-session';

const SECRET = 'test-admin-session-secret';

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env.ADMIN_SESSION_SECRET = SECRET;
  delete process.env.ADMIN_PASSWORD;
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

/** Forge a `<payload>.<signature>` token, optionally signing with a wrong key. */
function forgeToken(
  payload: Record<string, unknown>,
  signingKey: string | null = null
): string {
  const encoded = Buffer.from(JSON.stringify(payload), 'utf8').toString(
    'base64url'
  );
  if (signingKey === null) {
    // Attacker with no key: a plausible but arbitrary signature.
    return `${encoded}.not-a-real-signature`;
  }
  const sig = createHmac('sha256', signingKey)
    .update(encoded)
    .digest('base64url');
  return `${encoded}.${sig}`;
}

describe('createAdminSessionToken / verifyAdminSessionToken round-trip', () => {
  it('verifies a freshly minted token', () => {
    const token = createAdminSessionToken();
    expect(verifyAdminSessionToken(token)).toBe(true);
  });

  it('produces a two-part "<payload>.<signature>" token', () => {
    const token = createAdminSessionToken();
    expect(token.split('.')).toHaveLength(2);
  });

  it('throws rather than issuing an unsigned token when no secret is set', () => {
    delete process.env.ADMIN_SESSION_SECRET;
    delete process.env.ADMIN_PASSWORD;
    expect(() => createAdminSessionToken()).toThrow(/admin session/i);
  });
});

describe('forged and tampered tokens are rejected', () => {
  it('rejects a hand-forged token signed with no/unknown key', () => {
    const now = Date.now();
    const forged = forgeToken({
      v: 1,
      sub: 'admin',
      iat: now,
      exp: now + ADMIN_SESSION_MAX_AGE_MS,
    });
    expect(verifyAdminSessionToken(forged)).toBe(false);
  });

  it('rejects a token signed with the wrong key', () => {
    const now = Date.now();
    const forged = forgeToken(
      { v: 1, sub: 'admin', iat: now, exp: now + ADMIN_SESSION_MAX_AGE_MS },
      'attacker-guessed-secret'
    );
    expect(verifyAdminSessionToken(forged)).toBe(false);
  });

  it('rejects a token whose payload was mutated after signing', () => {
    const now = 1_000_000_000_000;
    const token = createAdminSessionToken(now);
    const [, signature] = token.split('.');
    // Extend the expiry far into the future while keeping the original signature.
    const tamperedPayload = Buffer.from(
      JSON.stringify({
        v: 1,
        sub: 'admin',
        iat: now,
        exp: now + ADMIN_SESSION_MAX_AGE_MS * 1000,
      }),
      'utf8'
    ).toString('base64url');
    expect(verifyAdminSessionToken(`${tamperedPayload}.${signature}`)).toBe(
      false
    );
  });

  it('rejects the legacy unsigned base64("admin:<ts>") cookie', () => {
    const legacy = Buffer.from(`admin:${Date.now()}`).toString('base64');
    expect(verifyAdminSessionToken(legacy)).toBe(false);
  });

  it('rejects a wrong subject even when correctly signed', () => {
    const now = Date.now();
    const forged = forgeToken(
      { v: 1, sub: 'root', iat: now, exp: now + ADMIN_SESSION_MAX_AGE_MS },
      SECRET
    );
    expect(verifyAdminSessionToken(forged)).toBe(false);
  });

  it('rejects an unknown payload version even when correctly signed', () => {
    const now = Date.now();
    const forged = forgeToken(
      { v: 999, sub: 'admin', iat: now, exp: now + ADMIN_SESSION_MAX_AGE_MS },
      SECRET
    );
    expect(verifyAdminSessionToken(forged)).toBe(false);
  });
});

describe('malformed input is rejected without throwing', () => {
  it.each([
    ['empty string', ''],
    ['undefined', undefined],
    ['null', null],
    ['no separator', 'justonepart'],
    ['empty payload', '.signature'],
    ['empty signature', 'payload.'],
    ['non-base64 payload', '!!!.###'],
  ])('rejects %s', (_label, value) => {
    expect(verifyAdminSessionToken(value as string | undefined | null)).toBe(
      false
    );
  });
});

describe('expiry is enforced', () => {
  it('accepts a token that has not yet expired', () => {
    const now = 1_000_000_000_000;
    const token = createAdminSessionToken(now);
    const beforeExpiry = now + ADMIN_SESSION_MAX_AGE_MS - 1;
    expect(verifyAdminSessionToken(token, beforeExpiry)).toBe(true);
  });

  it('rejects a token once its expiry has passed', () => {
    const now = 1_000_000_000_000;
    const token = createAdminSessionToken(now);
    const afterExpiry = now + ADMIN_SESSION_MAX_AGE_MS + 1;
    expect(verifyAdminSessionToken(token, afterExpiry)).toBe(false);
  });

  it('rejects a correctly signed token whose exp is already in the past', () => {
    const now = Date.now();
    const forged = forgeToken(
      { v: 1, sub: 'admin', iat: now - 2, exp: now - 1 },
      SECRET
    );
    expect(verifyAdminSessionToken(forged, now)).toBe(false);
  });
});

describe('signing-key resolution', () => {
  it('falls back to an ADMIN_PASSWORD-derived key when no dedicated secret', () => {
    delete process.env.ADMIN_SESSION_SECRET;
    process.env.ADMIN_PASSWORD = 'hunter2';
    const token = createAdminSessionToken();
    expect(verifyAdminSessionToken(token)).toBe(true);
  });

  it('invalidates password-derived sessions when the password changes', () => {
    delete process.env.ADMIN_SESSION_SECRET;
    process.env.ADMIN_PASSWORD = 'hunter2';
    const token = createAdminSessionToken();

    process.env.ADMIN_PASSWORD = 'rotated-password';
    expect(verifyAdminSessionToken(token)).toBe(false);
  });

  it('rejects any token when no signing secret is configured', () => {
    const token = createAdminSessionToken();
    delete process.env.ADMIN_SESSION_SECRET;
    delete process.env.ADMIN_PASSWORD;
    expect(verifyAdminSessionToken(token)).toBe(false);
  });

  it('does not treat the dedicated secret and the password as interchangeable', () => {
    // A token minted under the dedicated secret must not verify if a deployment
    // later drops the secret and relies on a password that happens to match it.
    const token = createAdminSessionToken();
    delete process.env.ADMIN_SESSION_SECRET;
    process.env.ADMIN_PASSWORD = SECRET; // same string, different derivation
    expect(verifyAdminSessionToken(token)).toBe(false);
  });
});

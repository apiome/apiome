import { describe, expect, it } from 'vitest';

import {
  encodeReaderCookie,
  isSameOriginPost,
  isTenantSlug,
  parseReaderCookie,
  parseRefusal,
  portalPath,
  readerAuthHeader,
  readerCookieOptions,
  refusalFromCode,
  REFUSAL_COPY,
  safeReturnTo,
} from '../session';

const TOKEN = 'prs_' + 'a'.repeat(43);

describe('reader cookie', () => {
  it('round-trips the tenant and token', () => {
    expect(parseReaderCookie(encodeReaderCookie('acme', TOKEN))).toEqual({ tenantSlug: 'acme', token: TOKEN });
  });

  it.each([
    undefined,
    '',
    TOKEN,
    `:${TOKEN}`,
    `ACME:${TOKEN}`,
    `acme:sk_live_${'a'.repeat(30)}`,
    'acme:prs_short',
    `ac me:${TOKEN}`,
  ])('refuses %s', (value) => {
    expect(parseReaderCookie(value)).toBeNull();
  });

  it('is HttpOnly, Lax and scoped to the base path', () => {
    const expires = new Date('2026-11-21T12:00:00Z');
    expect(readerCookieOptions('/browse/', expires, true)).toEqual({
      httpOnly: true,
      secure: true,
      sameSite: 'lax',
      path: '/browse',
      expires,
    });
    expect(readerCookieOptions('', expires, false).path).toBe('/');
    expect(readerCookieOptions(undefined, expires, false).secure).toBe(false);
  });

  it('forwards the session in the Reader scheme', () => {
    expect(readerAuthHeader(TOKEN)).toEqual({ Authorization: `Reader ${TOKEN}` });
  });
});

describe('tenant slugs', () => {
  it.each(['acme', 'acme-corp', 'a1'])('accepts %s', (slug) => expect(isTenantSlug(slug)).toBe(true));
  it.each(['', 'Acme', '-acme', 'acme-', '../x', 'a/b', null])('refuses %s', (slug) =>
    expect(isTenantSlug(slug)).toBe(false),
  );
});

describe('safeReturnTo', () => {
  it('keeps same-site paths', () => {
    expect(safeReturnTo('/tenant/acme/pets?tab=try#op', '/')).toBe('/tenant/acme/pets?tab=try#op');
  });

  it.each(['https://evil.example', '//evil.example', '/\\evil.example', 'tenant/acme', '/a\nb', null, ''])(
    'falls back for %s',
    (raw) => {
      expect(safeReturnTo(raw, '/tenant/acme')).toBe('/tenant/acme');
    },
  );
});

describe('isSameOriginPost', () => {
  it('accepts a post from the same origin', () => {
    expect(isSameOriginPost('https://docs.acme.example', 'https://docs.acme.example/browse/portal/sign-out')).toBe(true);
  });

  it.each([null, 'https://evil.example', 'http://docs.acme.example', 'not a url'])('refuses %s', (origin) => {
    expect(isSameOriginPost(origin, 'https://docs.acme.example/portal/sign-out')).toBe(false);
  });
});

describe('refusals', () => {
  it('maps REST codes to a reason', () => {
    expect(refusalFromCode('portal-token-expired')).toBe('expired');
    expect(refusalFromCode('portal-token-used')).toBe('used');
    expect(refusalFromCode('portal-token-invalid')).toBe('invalid');
    expect(refusalFromCode(null)).toBe('invalid');
  });

  it('parses the error page reason and names each one', () => {
    expect(parseRefusal('expired')).toBe('expired');
    expect(parseRefusal('used')).toBe('used');
    expect(parseRefusal('<script>')).toBe('invalid');
    for (const reason of ['expired', 'used', 'invalid'] as const) {
      expect(REFUSAL_COPY[reason].title).toMatch(/sign-in link/);
    }
  });
});

describe('portalPath', () => {
  it('drops empty parameters and encodes the rest', () => {
    expect(portalPath('/portal/sign-in', { tenant: 'acme', return_to: '/tenant/acme?x=1', sent: null })).toBe(
      '/portal/sign-in?tenant=acme&return_to=%2Ftenant%2Facme%3Fx%3D1',
    );
    expect(portalPath('/portal/sign-in', {})).toBe('/portal/sign-in');
  });
});

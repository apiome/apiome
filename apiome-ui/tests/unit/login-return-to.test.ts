/**
 * Session-expiry return-to tests (OLO-3.4, #4202).
 *
 * Pins the expiry round-trip contract: an expired session redirects to /login
 * with the current location preserved as callbackUrl, login routes are never
 * used as a return-to (no redirect loops), and unsafe paths (backslash /
 * protocol-relative open-redirect vectors) fall back to a plain /login.
 */
import { buildLoginRedirect, LOGIN_PATH } from '@lib/auth/login-return-to';

describe('buildLoginRedirect', () => {
  it('preserves the current pathname as callbackUrl', () => {
    expect(buildLoginRedirect('/ade/dashboard/projects')).toBe(
      `/login?callbackUrl=${encodeURIComponent('/ade/dashboard/projects')}`
    );
  });

  it('preserves the query string alongside the pathname', () => {
    expect(buildLoginRedirect('/ade/dashboard/projects', '?tab=archived&page=2')).toBe(
      `/login?callbackUrl=${encodeURIComponent('/ade/dashboard/projects?tab=archived&page=2')}`
    );
  });

  it('accepts a query string without a leading question mark', () => {
    expect(buildLoginRedirect('/ade/database', 'view=tables')).toBe(
      `/login?callbackUrl=${encodeURIComponent('/ade/database?view=tables')}`
    );
  });

  it('returns plain /login when already on a login route', () => {
    expect(buildLoginRedirect('/login')).toBe(LOGIN_PATH);
    expect(buildLoginRedirect('/login/help', '?x=1')).toBe(LOGIN_PATH);
  });

  it('returns plain /login when the pathname is missing', () => {
    expect(buildLoginRedirect(null)).toBe(LOGIN_PATH);
    expect(buildLoginRedirect(undefined)).toBe(LOGIN_PATH);
    expect(buildLoginRedirect('')).toBe(LOGIN_PATH);
  });

  it('drops unsafe return-to paths instead of round-tripping them', () => {
    expect(buildLoginRedirect('//evil.example')).toBe(LOGIN_PATH);
    expect(buildLoginRedirect('/\\evil.example')).toBe(LOGIN_PATH);
    expect(buildLoginRedirect('/ade', '?next=\\\\evil.example')).toBe(LOGIN_PATH);
  });

  it('keeps an empty query string out of the callbackUrl', () => {
    expect(buildLoginRedirect('/ade/dashboard', '')).toBe(
      `/login?callbackUrl=${encodeURIComponent('/ade/dashboard')}`
    );
  });
});

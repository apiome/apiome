/**
 * Same-origin request check (OLO-7.3 follow-up, #4963).
 *
 * The check is what stops another site from driving a state-changing route with the visitor's
 * session cookie, so it must refuse whenever the request's origin is not provably this app's.
 */
import { isSameOriginRequest } from '@lib/auth/same-origin';

/** Build the minimal header reader from a plain record (names are case-insensitive, as on the wire). */
const headers = (values: Record<string, string>) => new Headers(values);

describe('isSameOriginRequest', () => {
  it.each([
    ['https://app.apiome.dev', 'app.apiome.dev'],
    ['http://localhost:3000', 'localhost:3000'],
    ['https://app.apiome.dev:8443', 'app.apiome.dev:8443'],
    ['https://APP.Apiome.dev', 'app.apiome.dev'],
    ['https://app.apiome.dev', 'APP.apiome.dev'],
  ])('accepts Origin %s for Host %s', (origin, host) => {
    expect(isSameOriginRequest(headers({ origin, host }))).toBe(true);
  });

  it.each([
    ['another site', 'https://evil.example', 'app.apiome.dev'],
    ['a sibling subdomain', 'https://suite.apiome.dev', 'app.apiome.dev'],
    ['a lookalike suffix', 'https://app.apiome.dev.evil.example', 'app.apiome.dev'],
    ['the same host on another port', 'http://localhost:4000', 'localhost:3000'],
    ['an opaque origin', 'null', 'app.apiome.dev'],
    ['an unparseable origin', 'not a url', 'app.apiome.dev'],
  ])('refuses %s', (_name, origin, host) => {
    expect(isSameOriginRequest(headers({ origin, host }))).toBe(false);
  });

  it('refuses a request with no Origin — a cross-site navigation sends none', () => {
    expect(isSameOriginRequest(headers({ host: 'app.apiome.dev' }))).toBe(false);
  });

  it('refuses a request with no Host', () => {
    expect(isSameOriginRequest(headers({ origin: 'https://app.apiome.dev' }))).toBe(false);
  });
});

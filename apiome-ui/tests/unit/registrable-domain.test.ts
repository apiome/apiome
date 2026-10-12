/**
 * Registrable-domain lookup on the Public Suffix List (OLO-7.3 follow-up, #4961).
 *
 * The lookup decides which hosts a login callback may leave to and how far the shared session
 * cookie reaches, so the boundary cases are the security property: a host that only shares a
 * *public suffix* with the deployment must never resolve to the same registrable domain.
 */
import { registrableDomain } from '@lib/auth/registrable-domain';

describe('registrableDomain', () => {
  it.each([
    ['apiome.dev', 'apiome.dev'],
    ['suite.apiome.dev', 'apiome.dev'],
    ['a.b.c.apiome.app', 'apiome.app'],
    ['example.com', 'example.com'],
  ])('resolves %s on a single-label suffix to %s', (host, expected) => {
    expect(registrableDomain(host)).toBe(expected);
  });

  it.each([
    ['app.example.co.uk', 'example.co.uk'],
    ['example.co.uk', 'example.co.uk'],
    ['app.example.com.au', 'example.com.au'],
    ['apiome.vercel.app', 'apiome.vercel.app'],
    ['preview.apiome.vercel.app', 'apiome.vercel.app'],
    ['apiome.pages.dev', 'apiome.pages.dev'],
    ['apiome.github.io', 'apiome.github.io'],
  ])('keeps the label in front of the multi-label suffix: %s → %s', (host, expected) => {
    expect(registrableDomain(host)).toBe(expected);
  });

  it.each([
    ['apiome.vercel.app', 'attacker.vercel.app'],
    ['apiome.pages.dev', 'attacker.pages.dev'],
    ['apiome.github.io', 'attacker.github.io'],
    ['app.example.co.uk', 'attacker.co.uk'],
  ])('never equates %s with its suffix neighbour %s', (ours, theirs) => {
    expect(registrableDomain(theirs)).not.toBe(registrableDomain(ours));
  });

  it.each(['co.uk', 'vercel.app', 'pages.dev', 'github.io', 'com', 'dev'])(
    'has no registrable domain for the public suffix %s itself',
    (suffix) => {
      expect(registrableDomain(suffix)).toBeNull();
    }
  );

  it.each(['', '   ', 'localhost', 'intranet', '127.0.0.1', '10.0.0.5', '::1', '[::1]'])(
    'has no registrable domain for %p',
    (host) => {
      expect(registrableDomain(host)).toBeNull();
    }
  );

  it('falls back to the last label for a suffix that is not on the list', () => {
    expect(registrableDomain('app.apiome.corp')).toBe('apiome.corp');
    expect(registrableDomain('studio.apiome.internal')).toBe('apiome.internal');
  });

  it('normalises case and a trailing dot', () => {
    expect(registrableDomain('Suite.APIOME.Dev')).toBe('apiome.dev');
    expect(registrableDomain('suite.apiome.dev.')).toBe('apiome.dev');
  });
});

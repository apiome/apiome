/**
 * The `/login/2fa` page's query handling (TFA-1.1, #5655).
 *
 * A provider sign-in is redirected here by the server with `?callbackUrl=…&methods=…`. Both are
 * untrusted: the destination goes through the callback allowlist and the methods are reduced to
 * the two the screen knows.
 */

import React from 'react';

const mockClient = jest.fn((_props: unknown) => null);
jest.mock('@/app/login/2fa/TwoFactorClient', () => ({
  __esModule: true,
  default: (props: unknown) => mockClient(props),
}));

import TwoFactorLoginPage from '@/app/login/2fa/page';

/** Render the page for a query string and return the props it handed the client. */
async function propsFor(query: Record<string, string>) {
  const element = (await TwoFactorLoginPage({ searchParams: Promise.resolve(query) })) as React.ReactElement<{
    callbackUrl: string;
    error?: string;
    methods?: string[];
  }>;
  return element.props;
}

describe('TwoFactorLoginPage', () => {
  it.each([
    ['totp', ['totp']],
    ['totp,otp', ['totp', 'otp']],
    ['otp', ['otp']],
    ['otp,totp,otp', ['otp', 'totp']],
    ['totp,sms,<script>', ['totp']],
  ])('reduces methods=%s to %p', async (raw, expected) => {
    expect((await propsFor({ methods: raw })).methods).toEqual(expected);
  });

  it('falls back to the authenticator when no named method is known', async () => {
    expect((await propsFor({ methods: 'sms,push' })).methods).toEqual(['totp']);
  });

  it.each([{}, { methods: '' }])('passes no methods for %p — the password path stores its own', async (query) => {
    expect((await propsFor(query)).methods).toBeUndefined();
  });

  it('keeps a same-origin destination and refuses an external one', async () => {
    expect((await propsFor({ callbackUrl: '/ade/dashboard/projects' })).callbackUrl).toBe(
      '/ade/dashboard/projects'
    );
    expect((await propsFor({ callbackUrl: 'https://evil.example/phish' })).callbackUrl).toBe('/ade');
    expect((await propsFor({ callbackUrl: '//evil.example' })).callbackUrl).toBe('/ade');
  });

  it('passes the error code through', async () => {
    expect((await propsFor({ error: 'auth-rate-limited' })).error).toBe('auth-rate-limited');
  });
});

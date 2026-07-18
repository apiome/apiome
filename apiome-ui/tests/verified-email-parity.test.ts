/**
 * GitHub/GitLab verified-email parity tests (OLO-2.5, #4197).
 *
 * The parity pass must guarantee both acceptance criteria of the ticket:
 *   1. GitHub accounts with private (null public) emails still resolve a *verified* email,
 *      via the `/user/emails` API unlocked by the `user:email` scope.
 *   2. Unverified/missing emails surface as unverified — classified by OLO-1.3 rule 4 as a
 *      structured UNVERIFIED_EMAIL rejection — never silently trusted.
 *
 * `verified-email.ts` is a pure/injectable module (no db, no next-auth runtime), so these
 * tests exercise it directly, then prove the produced profile satisfies the OLO-1.3 engine's
 * `resolveOAuthEmailVerified` resolver.
 */
import { describe, test, expect, jest } from '@jest/globals';

import {
  GITHUB_EMAILS_URL,
  GITHUB_OAUTH_SCOPE,
  GITLAB_OAUTH_SCOPE,
  fetchGithubEmailEntries,
  githubApiBaseUrl,
  githubEmailsUrl,
  gitlabBaseUrl,
  resolveGithubVerifiedEmail,
  resolveGitlabEmailVerified,
  githubUserinfoRequest,
  gitlabUserinfoRequest,
} from '../lib/auth/verified-email';
import type { GithubEmailEntry } from '../lib/auth/verified-email';
import { resolveOAuthEmailVerified } from '../lib/auth/account-resolution';

/** Build a fetch mock returning the given status/body for the GitHub emails API. */
const fetchReturning = (ok: boolean, body: unknown) =>
  jest.fn(async () => ({ ok, json: async () => body }));

describe('OAuth scopes (OLO-2.5)', () => {
  test('GitHub requests the emails API scope; GitLab requests read_user', () => {
    expect(GITHUB_OAUTH_SCOPE).toBe('read:user user:email');
    expect(GITLAB_OAUTH_SCOPE).toBe('read_user');
  });
});

describe('resolveGithubVerifiedEmail', () => {
  const entries = [
    { email: 'primary@example.com', primary: true, verified: true },
    { email: 'public@example.com', primary: false, verified: false },
    { email: 'old@example.com', primary: false, verified: true },
  ];

  test('null profile email adopts the verified primary from the emails API (AC 1)', () => {
    expect(resolveGithubVerifiedEmail(null, entries)).toEqual({
      email: 'primary@example.com',
      emailVerified: true,
    });
  });

  test('null profile email with an unverified primary surfaces it as unverified (AC 2)', () => {
    const unverifiedPrimary = [{ email: 'new@example.com', primary: true, verified: false }];
    expect(resolveGithubVerifiedEmail(null, unverifiedPrimary)).toEqual({
      email: 'new@example.com',
      emailVerified: false,
    });
  });

  test('a public profile email is verified only when its entry is verified', () => {
    expect(resolveGithubVerifiedEmail('old@example.com', entries)).toEqual({
      email: 'old@example.com',
      emailVerified: true,
    });
    expect(resolveGithubVerifiedEmail('public@example.com', entries)).toEqual({
      email: 'public@example.com',
      emailVerified: false,
    });
  });

  test('profile-email matching is case/whitespace-insensitive (OLO-1.1 canonical form)', () => {
    expect(resolveGithubVerifiedEmail(' Primary@Example.COM ', entries).emailVerified).toBe(true);
  });

  test('a profile email absent from the emails list stays unverified', () => {
    expect(resolveGithubVerifiedEmail('elsewhere@example.com', entries)).toEqual({
      email: 'elsewhere@example.com',
      emailVerified: false,
    });
  });

  test('fails closed when the emails API was unavailable (null entries)', () => {
    expect(resolveGithubVerifiedEmail(null, null)).toEqual({ email: null, emailVerified: false });
    expect(resolveGithubVerifiedEmail('public@example.com', null)).toEqual({
      email: 'public@example.com',
      emailVerified: false,
    });
  });

  test('ignores malformed entries instead of trusting them', () => {
    const junk = [null, {}, { email: '  ' }, { email: 42 }, { primary: true, verified: true }];
    expect(resolveGithubVerifiedEmail(null, junk as unknown as GithubEmailEntry[])).toEqual({
      email: null,
      emailVerified: false,
    });
  });
});

describe('fetchGithubEmailEntries', () => {
  test('returns the entries and calls the API with the token + GitHub media type', async () => {
    const body = [{ email: 'a@b.com', primary: true, verified: true }];
    const fetchImpl = fetchReturning(true, body);
    await expect(fetchGithubEmailEntries('tok-123', fetchImpl)).resolves.toEqual(body);
    expect(fetchImpl).toHaveBeenCalledWith(GITHUB_EMAILS_URL, {
      headers: {
        Authorization: 'Bearer tok-123',
        Accept: 'application/vnd.github+json',
      },
    });
  });

  test('fails soft to null on a non-2xx response', async () => {
    await expect(fetchGithubEmailEntries('t', fetchReturning(false, []))).resolves.toBeNull();
  });

  test('fails soft to null on a non-array body', async () => {
    await expect(
      fetchGithubEmailEntries('t', fetchReturning(true, { message: 'rate limited' }))
    ).resolves.toBeNull();
  });

  test('fails soft to null when the transport throws', async () => {
    const throwing = jest.fn(async (): Promise<never> => {
      throw new Error('network down');
    });
    await expect(fetchGithubEmailEntries('t', throwing)).resolves.toBeNull();
  });

  test('calls the overridden emails URL when GITHUB_API_BASE_URL is set (OLO-7.4)', async () => {
    process.env.GITHUB_API_BASE_URL = 'http://localhost:8091/github/api';
    try {
      const fetchImpl = fetchReturning(true, []);
      await fetchGithubEmailEntries('tok', fetchImpl);
      expect(fetchImpl).toHaveBeenCalledWith(
        'http://localhost:8091/github/api/user/emails',
        expect.anything()
      );
    } finally {
      delete process.env.GITHUB_API_BASE_URL;
    }
  });
});

describe('mock-provider base URL overrides (OLO-7.4)', () => {
  test('default to the real hosts when unset or blank', () => {
    expect(githubApiBaseUrl({})).toBe('https://api.github.com');
    expect(githubApiBaseUrl({ GITHUB_API_BASE_URL: '  ' })).toBe('https://api.github.com');
    expect(gitlabBaseUrl({})).toBe('https://gitlab.com');
    expect(githubEmailsUrl({})).toBe(GITHUB_EMAILS_URL);
  });

  test('use the override (trailing slash trimmed) when set', () => {
    expect(githubApiBaseUrl({ GITHUB_API_BASE_URL: 'http://m:1/gh/' })).toBe('http://m:1/gh');
    expect(gitlabBaseUrl({ GITLAB_BASE_URL: 'http://m:1/gl/' })).toBe('http://m:1/gl');
    expect(githubEmailsUrl({ GITHUB_API_BASE_URL: 'http://m:1/gh' })).toBe(
      'http://m:1/gh/user/emails'
    );
  });
});

describe('resolveGitlabEmailVerified', () => {
  test('verified when the profile carries both email and confirmed_at', () => {
    expect(
      resolveGitlabEmailVerified({ email: 'dev@example.com', confirmed_at: '2024-01-01T00:00:00Z' })
    ).toBe(true);
  });

  test('unverified when confirmed_at is missing, null, or empty (AC 2)', () => {
    expect(resolveGitlabEmailVerified({ email: 'dev@example.com' })).toBe(false);
    expect(resolveGitlabEmailVerified({ email: 'dev@example.com', confirmed_at: null })).toBe(false);
    expect(resolveGitlabEmailVerified({ email: 'dev@example.com', confirmed_at: '  ' })).toBe(false);
  });

  test('unverified when the email itself is missing', () => {
    expect(resolveGitlabEmailVerified({ confirmed_at: '2024-01-01T00:00:00Z' })).toBe(false);
    expect(resolveGitlabEmailVerified({ email: '', confirmed_at: '2024-01-01T00:00:00Z' })).toBe(false);
    expect(resolveGitlabEmailVerified(null)).toBe(false);
  });
});

describe('githubUserinfoRequest (userinfo exchange wiring)', () => {
  const context = (profile: Record<string, unknown>) => ({
    client: { userinfo: jest.fn(async () => ({ ...profile })) },
    tokens: { access_token: 'gh-token' },
  });

  test('private-email account resolves the verified primary and marks it verified (AC 1)', async () => {
    const fetchImpl = fetchReturning(true, [
      { email: 'hidden@example.com', primary: true, verified: true },
    ]);
    const profile = await githubUserinfoRequest(
      context({ id: 1, login: 'octocat', email: null }),
      fetchImpl
    );
    expect(profile.email).toBe('hidden@example.com');
    expect(profile.email_verified).toBe(true);
    // The raw profile is exactly what the OLO-1.3 resolver reads in the signIn callback.
    expect(resolveOAuthEmailVerified(profile, {})).toBe(true);
  });

  test('emails-API failure leaves the sign-in unverified, not crashed (AC 2)', async () => {
    const profile = await githubUserinfoRequest(
      context({ id: 1, login: 'octocat', email: 'public@example.com' }),
      fetchReturning(false, null)
    );
    expect(profile.email).toBe('public@example.com');
    expect(profile.email_verified).toBe(false);
    expect(resolveOAuthEmailVerified(profile, {})).toBe(false);
  });

  test('passes the access token through to the userinfo exchange', async () => {
    const ctx = context({ id: 1, email: null });
    await githubUserinfoRequest(ctx, fetchReturning(true, []));
    expect(ctx.client.userinfo).toHaveBeenCalledWith('gh-token');
  });
});

describe('gitlabUserinfoRequest (userinfo exchange wiring)', () => {
  test('stamps email_verified=true from confirmed_at evidence', async () => {
    const client = {
      userinfo: jest.fn(async () => ({
        id: 7,
        username: 'dev',
        email: 'dev@example.com',
        confirmed_at: '2024-01-01T00:00:00Z',
      })),
    };
    const profile = await gitlabUserinfoRequest({ client, tokens: { access_token: 'gl-token' } });
    expect(profile.email_verified).toBe(true);
    expect(client.userinfo).toHaveBeenCalledWith('gl-token');
    expect(resolveOAuthEmailVerified(profile, {})).toBe(true);
  });

  test('an unconfirmed account stays unverified (AC 2)', async () => {
    const client = {
      userinfo: jest.fn(async () => ({ id: 7, email: 'dev@example.com', confirmed_at: null })),
    };
    const profile = await gitlabUserinfoRequest({ client, tokens: { access_token: 'gl-token' } });
    expect(profile.email_verified).toBe(false);
    expect(resolveOAuthEmailVerified(profile, {})).toBe(false);
  });
});

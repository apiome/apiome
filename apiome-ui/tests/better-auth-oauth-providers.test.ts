/**
 * @jest-environment node
 *
 * Better Auth OAuth provider construction tests (OLO-10.7, #5002).
 *
 * The acceptance gate for porting github/gitlab/azure/google onto Better Auth's generic OAuth2/OIDC
 * plugin. These tests prove the wiring re-attaches every invariant the NextAuth path guarantees,
 * without a database or network:
 *
 *   - the provider set is built from the shared registry (single source of the enabled set), in
 *     display order, with the client credentials and endpoint/issuer overrides (OLO-7.4) honoured;
 *   - each provider's `getUserInfo` normalizes `email_verified` the same way (GitHub `/user/emails`,
 *     GitLab `confirmed_at`, Google's native claim — OLO-2.5) before the resolution engine runs;
 *   - the Google Workspace `hd` gate still rejects an out-of-domain account (OLO-9.2);
 *   - a forged nOAuth (azure) token is still rejected with the structured code (OLO-1.4), and the
 *     full decision tree (admit / onboarding / link / reject) drives the redirect override;
 *   - the request-scoped redirect override rewrites the Better Auth callback's `Location`.
 *
 * The pure resolution engine and the 10.6 adapter are exercised by their own suites; here we only
 * assert the provider layer feeds them faithfully. `better-auth/api` (ESM-only) is stubbed and the
 * db-backed store is mocked away, matching `better-auth-account-resolution.test.ts`.
 */

// `better-auth/api` is ESM-only (imported transitively via the 10.6 adapter); stub the middleware
// factory to the bare handler so the module loads under ts-jest.
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
}));

// The default production store imports the db layer; every test injects a fake store, so replace the
// default with an inert stub to keep the suite hermetic.
jest.mock('../lib/auth/resolution-store', () => ({ resolutionStore: {} }));

// `resolveLinkIntentUserId` lazily imports `./oauth-link-intent` (which reads `next/headers`) to read
// the one-shot link-intent cookie. Stub it to "no link intent" so the default path stays hermetic; the
// explicit-link test injects its own `resolveLinkToUserId`.
jest.mock('../lib/auth/oauth-link-intent', () => ({ checkLinkingIntent: async () => null }));

import { generateKeyPairSync } from 'node:crypto';

import { describe, test, expect } from '@jest/globals';

import { AUTH_ERROR_CODES, type ResolutionStore, type ResolutionUser } from '../lib/auth/account-resolution';
import {
  applyOauthRedirectOverride,
  buildGenericOAuthConfig,
  buildGenericOAuthConfigs,
  decodeJwtClaims,
  getOauthRedirectOverride,
  githubOauthWebBaseUrl,
  makeOAuthGetUserInfo,
  runWithOauthRedirectOverride,
  exchangeAppleAuthorizationCode,
  providerConfigSignature,
  type FetchLike,
  type OAuthRunnerDeps,
} from '../lib/auth/better-auth-oauth-providers';
import { runWithAppleCallbackScope } from '../lib/auth/apple-sign-in';

/* ── Fixtures & fakes ──────────────────────────────────────────────────────────────────────── */

/** A Sign in with Apple `.p8`-style key (EC P-256, PKCS#8 PEM), generated per run. */
const APPLE_KEY_PAIR = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const APPLE_PRIVATE_KEY_PEM = APPLE_KEY_PAIR.privateKey
  .export({ format: 'pem', type: 'pkcs8' })
  .toString();

const ALL_ENABLED: Record<string, string> = {
  GITHUB_ID: 'gh-id',
  GITHUB_SECRET: 'gh-secret',
  GITLAB_CLIENT_ID: 'gl-id',
  GITLAB_CLIENT_SECRET: 'gl-secret',
  AZURE_AD_CLIENT_ID: 'az-id',
  AZURE_AD_CLIENT_SECRET: 'az-secret',
  GOOGLE_CLIENT_ID: 'go-id',
  GOOGLE_CLIENT_SECRET: 'go-secret',
  OKTA_CLIENT_ID: 'ok-id',
  OKTA_CLIENT_SECRET: 'ok-secret',
  OKTA_ISSUER: 'https://example.okta.com/oauth2/default',
  COGNITO_CLIENT_ID: 'cg-id',
  COGNITO_CLIENT_SECRET: 'cg-secret',
  COGNITO_ISSUER: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf',
  KEYCLOAK_CLIENT_ID: 'kc-id',
  KEYCLOAK_CLIENT_SECRET: 'kc-secret',
  KEYCLOAK_ISSUER: 'https://kc.example.com/realms/apiome',
  OIDC_CLIENT_ID: 'oidc-id',
  OIDC_CLIENT_SECRET: 'oidc-secret',
  OIDC_ISSUER: 'https://auth.example.com',
  AUTH0_CLIENT_ID: 'a0-id',
  AUTH0_CLIENT_SECRET: 'a0-secret',
  AUTH0_ISSUER: 'https://acme.auth0.com',
  LINE_CLIENT_ID: 'line-id',
  LINE_CLIENT_SECRET: 'line-secret',
  VK_CLIENT_ID: 'vk-id',
  VK_CLIENT_SECRET: 'vk-secret',
  WECHAT_CLIENT_ID: 'wx-id',
  WECHAT_CLIENT_SECRET: 'wx-secret',
  ATLASSIAN_CLIENT_ID: 'atl-id',
  ATLASSIAN_CLIENT_SECRET: 'atl-secret',
  BITBUCKET_CLIENT_ID: 'bb-key',
  BITBUCKET_CLIENT_SECRET: 'bb-secret',
  SLACK_CLIENT_ID: 'slack-id',
  SLACK_CLIENT_SECRET: 'slack-secret',
  LINKEDIN_CLIENT_ID: 'li-id',
  LINKEDIN_CLIENT_SECRET: 'li-secret',
  DISCORD_CLIENT_ID: 'dc-id',
  DISCORD_CLIENT_SECRET: 'dc-secret',
  SALESFORCE_CLIENT_ID: 'sf-id',
  SALESFORCE_CLIENT_SECRET: 'sf-secret',
  NOTION_CLIENT_ID: 'nt-id',
  NOTION_CLIENT_SECRET: 'nt-secret',
  FIGMA_CLIENT_ID: 'fg-id',
  FIGMA_CLIENT_SECRET: 'fg-secret',
  LINEAR_CLIENT_ID: 'ln-id',
  LINEAR_CLIENT_SECRET: 'ln-secret',
  DROPBOX_CLIENT_ID: 'db-id',
  DROPBOX_CLIENT_SECRET: 'db-secret',
  ZOOM_CLIENT_ID: 'zm-id',
  ZOOM_CLIENT_SECRET: 'zm-secret',
  HUGGINGFACE_CLIENT_ID: 'hf-id',
  HUGGINGFACE_CLIENT_SECRET: 'hf-secret',
  VERCEL_CLIENT_ID: 'vc-id',
  VERCEL_CLIENT_SECRET: 'vc-secret',
  RAILWAY_CLIENT_ID: 'rw-id',
  RAILWAY_CLIENT_SECRET: 'rw-secret',
  HUBSPOT_CLIENT_ID: 'hs-id',
  HUBSPOT_CLIENT_SECRET: 'hs-secret',
  APPLE_CLIENT_ID: 'com.example.web',
  APPLE_PRIVATE_KEY: APPLE_PRIVATE_KEY_PEM,
  APPLE_TEAM_ID: 'A1B2C3D4E5',
  APPLE_KEY_ID: 'ABC123DEFG',
  FACEBOOK_CLIENT_ID: 'fb-app-id',
  FACEBOOK_CLIENT_SECRET: 'fb-secret',
  TWITTER_CLIENT_ID: 'x-client-id',
  TWITTER_CLIENT_SECRET: 'x-secret',
  REDDIT_CLIENT_ID: 'reddit-client-id',
  REDDIT_CLIENT_SECRET: 'reddit-secret',
  SPOTIFY_CLIENT_ID: 'spotify-client-id',
  SPOTIFY_CLIENT_SECRET: 'spotify-secret',
};

const OK_USER: ResolutionUser = {
  id: 'user-ok',
  enabled: true,
  verified: true,
  email: 'ada@example.com',
  name: 'Ada',
};

interface StoreConfig {
  identityUserId?: string | null;
  usersById?: Record<string, ResolutionUser>;
  usersByEmail?: Record<string, ResolutionUser>;
}

function makeStore(config: StoreConfig = {}) {
  const calls = {
    linkIdentity: [] as Array<{ userId: string; identity: any }>,
    recordUserLogin: [] as string[],
    createPendingSignup: [] as any[],
  };
  const store: ResolutionStore = {
    async getIdentity() {
      return config.identityUserId !== undefined
        ? { found: true, userId: config.identityUserId }
        : { found: false, userId: null };
    },
    async getUserById(userId) {
      return config.usersById?.[userId] ?? null;
    },
    async getUserByEmail(email) {
      return config.usersByEmail?.[email] ?? null;
    },
    async linkIdentity(userId, identity) {
      calls.linkIdentity.push({ userId, identity });
      return { success: true };
    },
    async recordIdentityLogin() {},
    async recordUserLogin(userId) {
      calls.recordUserLogin.push(userId);
    },
    async createPendingSignup(provider, providerUserId, email, _account, profile) {
      calls.createPendingSignup.push({ provider, providerUserId, email, profile });
      return { id: 'pending-1' };
    },
  };
  return { store, calls };
}

/** base64url-encode a JWT segment. */
const b64url = (obj: unknown): string => Buffer.from(JSON.stringify(obj)).toString('base64url');

/** Build a signature-less JWT carrying `claims` in the payload (the gate never verifies the sig). */
const idTokenFor = (claims: Record<string, unknown>): string => `e30.${b64url(claims)}.sig`;

/**
 * A fetch stub that routes GitHub/GitLab userinfo calls by URL suffix. `profile` answers `/user`
 * and `/api/v4/user`; `emails` answers `/user/emails`. A route with no fixture returns `ok:false`.
 */
function makeFetch(routes: { profile?: unknown; emails?: unknown }): FetchLike {
  return async (url: string) => {
    if (url.endsWith('/user/emails')) {
      return routes.emails === undefined
        ? { ok: false, json: async () => null }
        : { ok: true, json: async () => routes.emails };
    }
    if (url.endsWith('/user') || url.endsWith('/api/v4/user')) {
      return routes.profile === undefined
        ? { ok: false, json: async () => null }
        : { ok: true, json: async () => routes.profile };
    }
    return { ok: false, json: async () => null };
  };
}

/** Run a provider's getUserInfo inside a redirect-override scope and return the result + override. */
async function runGetUserInfo(
  provider: string,
  tokens: Record<string, unknown>,
  deps: OAuthRunnerDeps
): Promise<{ result: any; override: string | null }> {
  return runWithOauthRedirectOverride(async () => {
    const result = await makeOAuthGetUserInfo(provider, deps)(tokens as any);
    return { result, override: getOauthRedirectOverride() };
  });
}

/* ── Config builder from the registry ──────────────────────────────────────────────────────── */

describe('buildGenericOAuthConfigs — registry is the single source of the enabled set', () => {
  test('builds one config per enabled provider, in registry display order', () => {
    const configs = buildGenericOAuthConfigs(ALL_ENABLED);
    expect(configs.map((c) => c.providerId)).toEqual([
      'github',
      'gitlab',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
    ]);
  });

  test('unsetting a provider env removes exactly that provider', () => {
    const env = { ...ALL_ENABLED };
    delete env.GITHUB_SECRET; // github now partially configured → not enabled
    expect(buildGenericOAuthConfigs(env).map((c) => c.providerId)).toEqual([
      'gitlab',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
    ]);
  });

  test('no providers configured → empty config list (no sign-in routes)', () => {
    expect(buildGenericOAuthConfigs({})).toEqual([]);
  });

  test('client id/secret are read from the registry env keys', () => {
    const github = buildGenericOAuthConfig('github', ALL_ENABLED)!;
    expect(github.clientId).toBe('gh-id');
    expect(github.clientSecret).toBe('gh-secret');
    const azure = buildGenericOAuthConfig('azure', ALL_ENABLED)!;
    expect(azure.clientId).toBe('az-id');
    expect(azure.clientSecret).toBe('az-secret');
    const okta = buildGenericOAuthConfig('okta', ALL_ENABLED)!;
    expect(okta.clientId).toBe('ok-id');
    expect(okta.clientSecret).toBe('ok-secret');
    const aws = buildGenericOAuthConfig('aws', ALL_ENABLED)!;
    expect(aws.clientId).toBe('cg-id');
    expect(aws.clientSecret).toBe('cg-secret');
    const kc = buildGenericOAuthConfig('keycloak', ALL_ENABLED)!;
    expect(kc.clientId).toBe('kc-id');
    expect(kc.clientSecret).toBe('kc-secret');
    const oidc = buildGenericOAuthConfig('oidc', ALL_ENABLED)!;
    expect(oidc.clientId).toBe('oidc-id');
    expect(oidc.clientSecret).toBe('oidc-secret');
    const auth0 = buildGenericOAuthConfig('auth0', ALL_ENABLED)!;
    expect(auth0.clientId).toBe('a0-id');
    expect(auth0.clientSecret).toBe('a0-secret');
    const line = buildGenericOAuthConfig('line', ALL_ENABLED)!;
    expect(line.clientId).toBe('line-id');
    expect(line.clientSecret).toBe('line-secret');
    const vk = buildGenericOAuthConfig('vk', ALL_ENABLED)!;
    expect(vk.clientId).toBe('vk-id');
    expect(vk.clientSecret).toBe('vk-secret');
    const wechat = buildGenericOAuthConfig('wechat', ALL_ENABLED)!;
    expect(wechat.clientId).toBe('wx-id');
    expect(wechat.clientSecret).toBe('wx-secret');
    const atlassian = buildGenericOAuthConfig('atlassian', ALL_ENABLED)!;
    expect(atlassian.clientId).toBe('atl-id');
    expect(atlassian.clientSecret).toBe('atl-secret');
    const bitbucket = buildGenericOAuthConfig('bitbucket', ALL_ENABLED)!;
    expect(bitbucket.clientId).toBe('bb-key');
    expect(bitbucket.clientSecret).toBe('bb-secret');
    const slack = buildGenericOAuthConfig('slack', ALL_ENABLED)!;
    expect(slack.clientId).toBe('slack-id');
    expect(slack.clientSecret).toBe('slack-secret');
    const linkedin = buildGenericOAuthConfig('linkedin', ALL_ENABLED)!;
    expect(linkedin.clientId).toBe('li-id');
    expect(linkedin.clientSecret).toBe('li-secret');
    const discord = buildGenericOAuthConfig('discord', ALL_ENABLED)!;
    expect(discord.clientId).toBe('dc-id');
    expect(discord.clientSecret).toBe('dc-secret');
    const salesforce = buildGenericOAuthConfig('salesforce', ALL_ENABLED)!;
    expect(salesforce.clientId).toBe('sf-id');
    expect(salesforce.clientSecret).toBe('sf-secret');
    const notion = buildGenericOAuthConfig('notion', ALL_ENABLED)!;
    expect(notion.clientId).toBe('nt-id');
    expect(notion.clientSecret).toBe('nt-secret');
    const figma = buildGenericOAuthConfig('figma', ALL_ENABLED)!;
    expect(figma.clientId).toBe('fg-id');
    expect(figma.clientSecret).toBe('fg-secret');
    const linear = buildGenericOAuthConfig('linear', ALL_ENABLED)!;
    expect(linear.clientId).toBe('ln-id');
    expect(linear.clientSecret).toBe('ln-secret');
    const dropbox = buildGenericOAuthConfig('dropbox', ALL_ENABLED)!;
    expect(dropbox.clientId).toBe('db-id');
    expect(dropbox.clientSecret).toBe('db-secret');
    const zoom = buildGenericOAuthConfig('zoom', ALL_ENABLED)!;
    expect(zoom.clientId).toBe('zm-id');
    expect(zoom.clientSecret).toBe('zm-secret');
    const huggingface = buildGenericOAuthConfig('huggingface', ALL_ENABLED)!;
    expect(huggingface.clientId).toBe('hf-id');
    expect(huggingface.clientSecret).toBe('hf-secret');
    const vercel = buildGenericOAuthConfig('vercel', ALL_ENABLED)!;
    expect(vercel.clientId).toBe('vc-id');
    expect(vercel.clientSecret).toBe('vc-secret');
    const railway = buildGenericOAuthConfig('railway', ALL_ENABLED)!;
    expect(railway.clientId).toBe('rw-id');
    expect(railway.clientSecret).toBe('rw-secret');
    const hubspot = buildGenericOAuthConfig('hubspot', ALL_ENABLED)!;
    expect(hubspot.clientId).toBe('hs-id');
    expect(hubspot.clientSecret).toBe('hs-secret');
    // Apple: the client id is the Services ID; the .p8 key never becomes a static client secret.
    const apple = buildGenericOAuthConfig('apple', ALL_ENABLED)!;
    expect(apple.clientId).toBe('com.example.web');
    expect(apple.clientSecret).toBe('');
    const facebook = buildGenericOAuthConfig('facebook', ALL_ENABLED)!;
    expect(facebook.clientId).toBe('fb-app-id');
    expect(facebook.clientSecret).toBe('fb-secret');
    const twitter = buildGenericOAuthConfig('twitter', ALL_ENABLED)!;
    expect(twitter.clientId).toBe('x-client-id');
    expect(twitter.clientSecret).toBe('x-secret');
    const reddit = buildGenericOAuthConfig('reddit', ALL_ENABLED)!;
    expect(reddit.clientId).toBe('reddit-client-id');
    expect(reddit.clientSecret).toBe('reddit-secret');
    const spotify = buildGenericOAuthConfig('spotify', ALL_ENABLED)!;
    expect(spotify.clientId).toBe('spotify-client-id');
    expect(spotify.clientSecret).toBe('spotify-secret');
  });

  test('an unknown provider id yields null', () => {
    expect(buildGenericOAuthConfig('not-a-provider', ALL_ENABLED)).toBeNull();
  });
});

/* ── Endpoint / issuer overrides (OLO-7.4) ─────────────────────────────────────────────────── */

describe('endpoint & issuer overrides (OLO-7.4)', () => {
  test('github: default hosts, and GITHUB_OAUTH_BASE_URL / GITHUB_API_BASE_URL overrides', () => {
    const def = buildGenericOAuthConfig('github', ALL_ENABLED)!;
    expect(def.authorizationUrl).toBe('https://github.com/login/oauth/authorize');
    expect(def.tokenUrl).toBe('https://github.com/login/oauth/access_token');
    expect(def.userInfoUrl).toBe('https://api.github.com/user');
    expect(def.pkce).toBe(false); // GitHub OAuth Apps do not support PKCE

    const mock = buildGenericOAuthConfig('github', {
      ...ALL_ENABLED,
      GITHUB_OAUTH_BASE_URL: 'http://localhost:9001/',
      GITHUB_API_BASE_URL: 'http://localhost:9002',
    })!;
    expect(mock.authorizationUrl).toBe('http://localhost:9001/login/oauth/authorize');
    expect(mock.tokenUrl).toBe('http://localhost:9001/login/oauth/access_token');
    expect(mock.userInfoUrl).toBe('http://localhost:9002/user');
  });

  test('gitlab: GITLAB_BASE_URL override drives authorize/token/userinfo; PKCE on', () => {
    const cfg = buildGenericOAuthConfig('gitlab', {
      ...ALL_ENABLED,
      GITLAB_BASE_URL: 'http://localhost:9003',
    })!;
    expect(cfg.authorizationUrl).toBe('http://localhost:9003/oauth/authorize');
    expect(cfg.tokenUrl).toBe('http://localhost:9003/oauth/token');
    expect(cfg.userInfoUrl).toBe('http://localhost:9003/api/v4/user');
    expect(cfg.pkce).toBe(true);
  });

  test('google: GOOGLE_ISSUER override drives OIDC discovery', () => {
    expect(buildGenericOAuthConfig('google', ALL_ENABLED)!.discoveryUrl).toBe(
      'https://accounts.google.com/.well-known/openid-configuration'
    );
    expect(
      buildGenericOAuthConfig('google', { ...ALL_ENABLED, GOOGLE_ISSUER: 'http://localhost:9004' })!
        .discoveryUrl
    ).toBe('http://localhost:9004/.well-known/openid-configuration');
  });

  test('azure: authority + tenant drive tenant-scoped OIDC discovery', () => {
    expect(buildGenericOAuthConfig('azure', ALL_ENABLED)!.discoveryUrl).toBe(
      'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration'
    );
    const scoped = buildGenericOAuthConfig('azure', {
      ...ALL_ENABLED,
      AZURE_AD_TENANT: 'contoso',
      AZURE_AD_AUTHORITY_BASE_URL: 'http://localhost:9005',
    })!;
    expect(scoped.discoveryUrl).toBe(
      'http://localhost:9005/contoso/v2.0/.well-known/openid-configuration'
    );
    expect(scoped.scopes).toContain('offline_access');
  });

  test('okta: OKTA_ISSUER drives OIDC discovery; PKCE on (OLO-9.3)', () => {
    const cfg = buildGenericOAuthConfig('okta', ALL_ENABLED)!;
    expect(cfg.discoveryUrl).toBe(
      'https://example.okta.com/oauth2/default/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);

    const mock = buildGenericOAuthConfig('okta', {
      ...ALL_ENABLED,
      OKTA_ISSUER: 'http://localhost:9006/okta/',
    })!;
    expect(mock.discoveryUrl).toBe(
      'http://localhost:9006/okta/.well-known/openid-configuration'
    );
  });

  test('salesforce: discovery on login.salesforce.com by default; PKCE on (OLO-9.20)', () => {
    const cfg = buildGenericOAuthConfig('salesforce', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('salesforce');
    expect(cfg.discoveryUrl).toBe(
      'https://login.salesforce.com/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);
    // Discovery supplies the endpoints — nothing is hard-coded.
    expect(cfg.authorizationUrl).toBeUndefined();
    expect(cfg.tokenUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test.each([
    ['a My Domain', 'https://acme.my.salesforce.com', 'https://acme.my.salesforce.com'],
    ['a sandbox', 'https://test.salesforce.com', 'https://test.salesforce.com'],
    ['a trailing slash', 'https://acme.my.salesforce.com/', 'https://acme.my.salesforce.com'],
    ['surrounding whitespace', '  https://acme.my.salesforce.com  ', 'https://acme.my.salesforce.com'],
    ['a blank value', '   ', 'https://login.salesforce.com'],
  ])('salesforce: SALESFORCE_ISSUER with %s drives OIDC discovery (OLO-9.20)', (_label, issuer, base) => {
    const cfg = buildGenericOAuthConfig('salesforce', { ...ALL_ENABLED, SALESFORCE_ISSUER: issuer })!;
    expect(cfg.discoveryUrl).toBe(`${base}/.well-known/openid-configuration`);
  });

  test('aws: COGNITO_ISSUER drives OIDC discovery; PKCE on (OLO-9.4)', () => {
    const cfg = buildGenericOAuthConfig('aws', ALL_ENABLED)!;
    expect(cfg.discoveryUrl).toBe(
      'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);

    const mock = buildGenericOAuthConfig('aws', {
      ...ALL_ENABLED,
      COGNITO_ISSUER: 'http://localhost:9007/cognito/',
    })!;
    expect(mock.discoveryUrl).toBe(
      'http://localhost:9007/cognito/.well-known/openid-configuration'
    );
  });

  test('keycloak: KEYCLOAK_ISSUER drives OIDC discovery; PKCE on (OLO-9.5)', () => {
    const cfg = buildGenericOAuthConfig('keycloak', ALL_ENABLED)!;
    expect(cfg.discoveryUrl).toBe(
      'https://kc.example.com/realms/apiome/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);

    const mock = buildGenericOAuthConfig('keycloak', {
      ...ALL_ENABLED,
      KEYCLOAK_ISSUER: 'http://localhost:8080/realms/apiome/',
    })!;
    expect(mock.discoveryUrl).toBe(
      'http://localhost:8080/realms/apiome/.well-known/openid-configuration'
    );
  });

  test('oidc: OIDC_ISSUER drives OIDC discovery; default scopes; custom OIDC_SCOPES (OLO-9.6)', () => {
    const cfg = buildGenericOAuthConfig('oidc', ALL_ENABLED)!;
    expect(cfg.discoveryUrl).toBe(
      'https://auth.example.com/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'profile', 'email']);

    const mock = buildGenericOAuthConfig('oidc', {
      ...ALL_ENABLED,
      OIDC_ISSUER: 'http://localhost:9008/oidc/',
    })!;
    expect(mock.discoveryUrl).toBe(
      'http://localhost:9008/oidc/.well-known/openid-configuration'
    );

    const customScopes = buildGenericOAuthConfig('oidc', {
      ...ALL_ENABLED,
      OIDC_SCOPES: 'openid groups profile',
    })!;
    expect(customScopes.scopes).toEqual(['openid', 'groups', 'profile']);
  });

  test('auth0: AUTH0_ISSUER drives OIDC discovery; PKCE on (OLO-9.7)', () => {
    const cfg = buildGenericOAuthConfig('auth0', ALL_ENABLED)!;
    expect(cfg.discoveryUrl).toBe(
      'https://acme.auth0.com/.well-known/openid-configuration'
    );
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);

    const mock = buildGenericOAuthConfig('auth0', {
      ...ALL_ENABLED,
      AUTH0_ISSUER: 'http://localhost:9009/auth0/',
    })!;
    expect(mock.discoveryUrl).toBe(
      'http://localhost:9009/auth0/.well-known/openid-configuration'
    );
  });

  test('line: fixed LINE Login v2.1 endpoints; PKCE on (OLO-9.41)', () => {
    const cfg = buildGenericOAuthConfig('line', ALL_ENABLED)!;
    expect(cfg.authorizationUrl).toBe('https://access.line.me/oauth2/v2.1/authorize');
    expect(cfg.tokenUrl).toBe('https://api.line.me/oauth2/v2.1/token');
    expect(cfg.userInfoUrl).toBe('https://api.line.me/oauth2/v2.1/userinfo');
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['openid', 'profile', 'email']);
    expect(cfg.discoveryUrl).toBeUndefined();
  });

  test('vk: fixed VK ID endpoints; PKCE on (OLO-9.42)', () => {
    const cfg = buildGenericOAuthConfig('vk', ALL_ENABLED)!;
    expect(cfg.authorizationUrl).toBe('https://id.vk.com/authorize');
    expect(cfg.tokenUrl).toBe('https://id.vk.com/oauth2/auth');
    expect(cfg.userInfoUrl).toBe('https://id.vk.com/oauth2/user_info');
    expect(cfg.pkce).toBe(true);
    expect(cfg.scopes).toEqual(['email', 'phone']);
    expect(cfg.discoveryUrl).toBeUndefined();
  });

  test('atlassian: fixed Atlassian endpoints; api.atlassian.com audience; PKCE on (OLO-9.8)', () => {
    const cfg = buildGenericOAuthConfig('atlassian', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('atlassian');
    expect(cfg.authorizationUrl).toBe('https://auth.atlassian.com/authorize');
    expect(cfg.tokenUrl).toBe('https://auth.atlassian.com/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.atlassian.com/me');
    expect(cfg.scopes).toEqual(['read:me', 'read:account']);
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toEqual({
      audience: 'api.atlassian.com',
      prompt: 'consent',
    });
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('bitbucket: fixed Bitbucket Cloud endpoints; Basic client auth; PKCE off (OLO-9.9)', () => {
    const cfg = buildGenericOAuthConfig('bitbucket', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('bitbucket');
    expect(cfg.authorizationUrl).toBe('https://bitbucket.org/site/oauth2/authorize');
    expect(cfg.tokenUrl).toBe('https://bitbucket.org/site/oauth2/access_token');
    expect(cfg.userInfoUrl).toBe('https://api.bitbucket.org/2.0/user');
    expect(cfg.scopes).toEqual(['account', 'email']);
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(false);
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('slack: fixed Slack OIDC discovery; openid profile email; PKCE off (OLO-9.17)', () => {
    const cfg = buildGenericOAuthConfig('slack', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('slack');
    expect(cfg.discoveryUrl).toBe('https://slack.com/.well-known/openid-configuration');
    expect(cfg.scopes).toEqual(['openid', 'profile', 'email']);
    expect(cfg.pkce).toBe(false);
    // Discovery supplies the endpoints — nothing is hard-coded and there is no issuer to set.
    expect(cfg.authorizationUrl).toBeUndefined();
    expect(cfg.tokenUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('linkedin: fixed LinkedIn OIDC discovery; openid profile email; PKCE off (OLO-9.18)', () => {
    const cfg = buildGenericOAuthConfig('linkedin', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('linkedin');
    expect(cfg.discoveryUrl).toBe(
      'https://www.linkedin.com/oauth/.well-known/openid-configuration'
    );
    expect(cfg.scopes).toEqual(['openid', 'profile', 'email']);
    expect(cfg.pkce).toBe(false);
    // Discovery supplies the endpoints — nothing is hard-coded and there is no issuer to set.
    expect(cfg.authorizationUrl).toBeUndefined();
    expect(cfg.tokenUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('discord: fixed Discord endpoints; identify email; prompt none; PKCE off (OLO-9.19)', () => {
    const cfg = buildGenericOAuthConfig('discord', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('discord');
    expect(cfg.authorizationUrl).toBe('https://discord.com/api/oauth2/authorize');
    expect(cfg.tokenUrl).toBe('https://discord.com/api/oauth2/token');
    expect(cfg.userInfoUrl).toBe('https://discord.com/api/users/@me');
    expect(cfg.scopes).toEqual(['identify', 'email']);
    expect(cfg.pkce).toBe(false);
    expect(cfg.prompt).toBe('none');
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('notion: fixed Notion endpoints; owner=user; Basic exchange; no scopes; PKCE off (OLO-9.21)', () => {
    const cfg = buildGenericOAuthConfig('notion', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('notion');
    expect(cfg.authorizationUrl).toBe('https://api.notion.com/v1/oauth/authorize');
    expect(cfg.tokenUrl).toBe('https://api.notion.com/v1/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.notion.com/v1/users/me');
    expect(cfg.scopes).toEqual([]);
    expect(cfg.authorizationUrlParams).toEqual({ owner: 'user' });
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(false);
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('figma: fixed Figma endpoints; current_user:read; Basic exchange; PKCE on (OLO-9.22)', () => {
    const cfg = buildGenericOAuthConfig('figma', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('figma');
    expect(cfg.authorizationUrl).toBe('https://www.figma.com/oauth');
    expect(cfg.tokenUrl).toBe('https://api.figma.com/v1/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.figma.com/v1/me');
    expect(cfg.scopes).toEqual(['current_user:read']);
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(true);
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('linear: fixed Linear endpoints; read scope; body-credential exchange; no PKCE (OLO-9.23)', () => {
    const cfg = buildGenericOAuthConfig('linear', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('linear');
    expect(cfg.authorizationUrl).toBe('https://linear.app/oauth/authorize');
    expect(cfg.tokenUrl).toBe('https://api.linear.app/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.linear.app/graphql');
    expect(cfg.scopes).toEqual(['read']);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(false);
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('dropbox: fixed Dropbox endpoints; account_info.read; body-credential exchange; PKCE on (OLO-9.24)', () => {
    const cfg = buildGenericOAuthConfig('dropbox', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('dropbox');
    expect(cfg.authorizationUrl).toBe('https://www.dropbox.com/oauth2/authorize');
    expect(cfg.tokenUrl).toBe('https://api.dropboxapi.com/oauth2/token');
    expect(cfg.userInfoUrl).toBe('https://api.dropboxapi.com/2/users/get_current_account');
    expect(cfg.scopes).toEqual(['account_info.read']);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(true);
    // No offline access is requested: Apiome keeps no Dropbox token.
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('zoom: fixed Zoom endpoints; no scope parameter; body-credential exchange; PKCE on (OLO-9.25)', () => {
    const cfg = buildGenericOAuthConfig('zoom', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('zoom');
    expect(cfg.authorizationUrl).toBe('https://zoom.us/oauth/authorize');
    expect(cfg.tokenUrl).toBe('https://zoom.us/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.zoom.us/v2/users/me');
    // A Zoom app's scopes are set on the app, so none is requested.
    expect(cfg.scopes).toEqual([]);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('huggingface: fixed Hugging Face OIDC discovery; openid profile email; PKCE on (OLO-9.26)', () => {
    const cfg = buildGenericOAuthConfig('huggingface', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('huggingface');
    expect(cfg.discoveryUrl).toBe('https://huggingface.co/.well-known/openid-configuration');
    expect(cfg.scopes).toEqual(['openid', 'profile', 'email']);
    expect(cfg.pkce).toBe(true);
    // Discovery supplies the endpoints — nothing is hard-coded and there is no issuer to set.
    expect(cfg.authorizationUrl).toBeUndefined();
    expect(cfg.tokenUrl).toBeUndefined();
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('vercel: fixed Sign in with Vercel endpoints; openid email profile; body-credential exchange; PKCE on (OLO-9.27)', () => {
    const cfg = buildGenericOAuthConfig('vercel', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('vercel');
    expect(cfg.authorizationUrl).toBe('https://vercel.com/oauth/authorize');
    expect(cfg.tokenUrl).toBe('https://api.vercel.com/login/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://api.vercel.com/login/oauth/userinfo');
    // No offline_access: Apiome keeps no Vercel token, so no refresh token is asked for.
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);
    expect(cfg.authentication).toBe('post');
    // Vercel rejects an authorization request without a PKCE challenge.
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('railway: fixed Login with Railway endpoints; openid email profile; Basic exchange; PKCE on (OLO-9.28)', () => {
    const cfg = buildGenericOAuthConfig('railway', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('railway');
    expect(cfg.authorizationUrl).toBe('https://backboard.railway.com/oauth/auth');
    expect(cfg.tokenUrl).toBe('https://backboard.railway.com/oauth/token');
    expect(cfg.userInfoUrl).toBe('https://backboard.railway.com/oauth/me');
    // No offline_access: Apiome keeps no Railway token, so no refresh token is asked for, and no
    // workspace or project scope: Apiome reads no Railway resources.
    expect(cfg.scopes).toEqual(['openid', 'email', 'profile']);
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('hubspot: fixed HubSpot OAuth endpoints; oauth scope; post exchange; PKCE off (OLO-9.29)', () => {
    const cfg = buildGenericOAuthConfig('hubspot', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('hubspot');
    expect(cfg.authorizationUrl).toBe('https://app.hubspot.com/oauth/authorize');
    expect(cfg.tokenUrl).toBe('https://api.hubapi.com/oauth/v1/token');
    // Token info takes the access token in its path, so there is no fixed userinfo URL.
    expect(cfg.userInfoUrl).toBeUndefined();
    // Only `oauth`: Apiome reads no contacts, companies or other CRM data.
    expect(cfg.scopes).toEqual(['oauth']);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(false);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('apple: fixed Apple endpoints; name email scopes; form_post; custom getToken; PKCE off (OLO-9.30)', () => {
    const cfg = buildGenericOAuthConfig('apple', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('apple');
    expect(cfg.authorizationUrl).toBe('https://appleid.apple.com/auth/authorize');
    expect(cfg.tokenUrl).toBe('https://appleid.apple.com/auth/token');
    // The id token carries every claim; Apple has no userinfo endpoint.
    expect(cfg.userInfoUrl).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.scopes).toEqual(['name', 'email']);
    // Requesting name or email obliges form_post (Apple rejects `query` with those scopes).
    expect(cfg.responseMode).toBe('form_post');
    expect(cfg.authorizationUrlParams).toEqual({ response_mode: 'form_post' });
    expect(cfg.pkce).toBe(false);
    expect(typeof cfg.getToken).toBe('function');
  });

  test('facebook: fixed Graph v24.0 endpoints; email public_profile; post exchange; PKCE off (OLO-9.31)', () => {
    const cfg = buildGenericOAuthConfig('facebook', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('facebook');
    expect(cfg.authorizationUrl).toBe('https://www.facebook.com/v24.0/dialog/oauth');
    expect(cfg.tokenUrl).toBe('https://graph.facebook.com/v24.0/oauth/access_token');
    // The normalizer inspects the token with debug_token before reading /me.
    expect(cfg.userInfoUrl).toBeUndefined();
    // The helper's default scopes only: Apiome reads no pages, posts or friends.
    expect(cfg.scopes).toEqual(['email', 'public_profile']);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(false);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('twitter: fixed X OAuth 2.0 endpoints; read + email scopes; basic exchange; PKCE on (OLO-9.32)', () => {
    const cfg = buildGenericOAuthConfig('twitter', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('twitter');
    expect(cfg.authorizationUrl).toBe('https://x.com/i/oauth2/authorize');
    expect(cfg.tokenUrl).toBe('https://api.x.com/2/oauth2/token');
    // The normalizer reads the profile and the email as two requests.
    expect(cfg.userInfoUrl).toBeUndefined();
    // The helper's defaults minus offline.access: Apiome keeps no refresh token.
    expect(cfg.scopes).toEqual(['users.read', 'tweet.read', 'users.email']);
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('reddit: fixed Reddit OAuth 2.0 endpoints; identity scope; basic exchange; PKCE off (OLO-9.33)', () => {
    const cfg = buildGenericOAuthConfig('reddit', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('reddit');
    expect(cfg.authorizationUrl).toBe('https://www.reddit.com/api/v1/authorize');
    expect(cfg.tokenUrl).toBe('https://www.reddit.com/api/v1/access_token');
    // The normalizer reads /api/v1/me itself.
    expect(cfg.userInfoUrl).toBeUndefined();
    expect(cfg.scopes).toEqual(['identity']);
    expect(cfg.authentication).toBe('basic');
    expect(cfg.pkce).toBe(false);
    // No refresh token: Apiome keeps no Reddit token.
    expect(cfg.authorizationUrlParams).toEqual({ duration: 'temporary' });
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('spotify: fixed Spotify OAuth 2.0 endpoints; user-read-email scope; post exchange; PKCE on (OLO-9.34)', () => {
    const cfg = buildGenericOAuthConfig('spotify', ALL_ENABLED)!;
    expect(cfg.providerId).toBe('spotify');
    expect(cfg.authorizationUrl).toBe('https://accounts.spotify.com/authorize');
    expect(cfg.tokenUrl).toBe('https://accounts.spotify.com/api/token');
    // The normalizer reads /v1/me itself.
    expect(cfg.userInfoUrl).toBeUndefined();
    expect(cfg.scopes).toEqual(['user-read-email']);
    expect(cfg.authentication).toBe('post');
    expect(cfg.pkce).toBe(true);
    expect(cfg.authorizationUrlParams).toBeUndefined();
    expect(cfg.discoveryUrl).toBeUndefined();
    expect(cfg.getToken).toBeUndefined();
  });

  test('wechat: QR Website App endpoints; custom getToken; PKCE off (OLO-9.43)', () => {
    const cfg = buildGenericOAuthConfig('wechat', ALL_ENABLED)!;
    expect(cfg.authorizationUrl).toBe('https://open.weixin.qq.com/connect/qrconnect#wechat_redirect');
    expect(cfg.tokenUrl).toBe('https://api.weixin.qq.com/sns/oauth2/access_token');
    expect(cfg.userInfoUrl).toBe('https://api.weixin.qq.com/sns/userinfo');
    expect(cfg.pkce).toBe(false);
    expect(cfg.scopes).toEqual(['snsapi_login']);
    expect(cfg.authorizationUrlParams).toEqual({ appid: 'wx-id', lang: 'cn' });
    expect(typeof cfg.getToken).toBe('function');
    expect(cfg.discoveryUrl).toBeUndefined();
  });

  test('githubOauthWebBaseUrl strips a trailing slash', () => {
    expect(githubOauthWebBaseUrl({ GITHUB_OAUTH_BASE_URL: 'http://mock/' })).toBe('http://mock');
    expect(githubOauthWebBaseUrl({})).toBe('https://github.com');
  });
});

/* ── decodeJwtClaims ───────────────────────────────────────────────────────────────────────── */

describe('decodeJwtClaims', () => {
  test('decodes the payload segment; fails soft to null on malformed input', () => {
    expect(decodeJwtClaims(idTokenFor({ sub: 'abc', email: 'a@b.com' }))).toMatchObject({
      sub: 'abc',
      email: 'a@b.com',
    });
    expect(decodeJwtClaims(null)).toBeNull();
    expect(decodeJwtClaims('not-a-jwt')).toBeNull();
    expect(decodeJwtClaims('a.%%%.c')).toBeNull();
  });
});

/* ── getUserInfo: GitHub/GitLab verified-email parity (OLO-2.5) ─────────────────────────────── */

describe('getUserInfo — GitHub verified-email parity', () => {
  const tokens = { accessToken: 'tok', idToken: null };

  test('known identity with a verified primary email → admits with the resolved user info', async () => {
    const { store, calls } = makeStore({ identityUserId: OK_USER.id, usersById: { [OK_USER.id]: OK_USER } });
    const fetchImpl = makeFetch({
      profile: { id: 42, login: 'ada', name: 'Ada L.', email: null, avatar_url: 'http://img/a.png' },
      emails: [{ email: 'ada@example.com', primary: true, verified: true }],
    });

    const { result, override } = await runGetUserInfo('github', tokens, { store, fetchImpl });

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '42',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada L.',
      image: 'http://img/a.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('an unverified GitHub email is rejected with the structured code, no user info', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const fetchImpl = makeFetch({
      profile: { id: 42, login: 'ada', email: 'ada@example.com' },
      emails: [{ email: 'ada@example.com', primary: true, verified: false }],
    });

    const { result, override } = await runGetUserInfo('github', tokens, { store, fetchImpl });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('a verified new email routes to onboarding (no auto-create)', async () => {
    const { store, calls } = makeStore();
    const fetchImpl = makeFetch({
      profile: { id: 42, login: 'ada', email: 'ada@example.com' },
      emails: [{ email: 'ada@example.com', primary: true, verified: true }],
    });

    const { result, override } = await runGetUserInfo('github', tokens, { store, fetchImpl });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({ provider: 'github', email: 'ada@example.com' });
  });
});

describe('getUserInfo — GitLab verified-email parity', () => {
  const tokens = { accessToken: 'tok', idToken: null };

  test('confirmed_at present → verified → onboarding for a new user', async () => {
    const { store } = makeStore();
    const fetchImpl = makeFetch({
      profile: { id: 7, username: 'ada', name: 'Ada', email: 'ada@example.com', confirmed_at: '2021-01-01T00:00:00Z' },
    });

    const { result, override } = await runGetUserInfo('gitlab', tokens, { store, fetchImpl });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
  });

  test('missing confirmed_at → unverified → structured rejection', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const fetchImpl = makeFetch({ profile: { id: 7, email: 'ada@example.com' } });

    const { result, override } = await runGetUserInfo('gitlab', tokens, { store, fetchImpl });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });
});

/* ── getUserInfo: Google native email_verified + hd gate (OLO-9.2) ──────────────────────────── */

describe('getUserInfo — Google Workspace hd gate (OLO-9.2)', () => {
  test('native email_verified=true, unrestricted → onboarding for a new verified user', async () => {
    const { store } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'g-1', email: 'ada@example.com', email_verified: true, name: 'Ada' }),
    };

    const { result, override } = await runGetUserInfo('google', tokens, { store, env: ALL_ENABLED });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
  });

  test('matching hd passes the gate → a known identity signs in', async () => {
    const { store } = makeStore({ identityUserId: OK_USER.id, usersById: { [OK_USER.id]: OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'g-1', email: 'ada@corp.com', email_verified: true, hd: 'corp.com' }),
    };

    const { result, override } = await runGetUserInfo('google', tokens, {
      store,
      env: { ...ALL_ENABLED, GOOGLE_WORKSPACE_DOMAIN: 'corp.com' },
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: 'g-1', email: 'ada@corp.com', emailVerified: true });
  });

  test('out-of-domain hd is rejected before resolution — the epic acceptance criterion', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@corp.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'g-1', email: 'ada@corp.com', email_verified: true, hd: 'evil.com' }),
    };

    const { result, override } = await runGetUserInfo('google', tokens, {
      store,
      env: { ...ALL_ENABLED, GOOGLE_WORKSPACE_DOMAIN: 'corp.com' },
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.SIGN_IN_FAILED}`);
    // The gate fires before any store side effect — no link, no signup.
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('a personal account (no hd) is rejected when a domain is configured', async () => {
    const { store } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'g-1', email: 'ada@gmail.com', email_verified: true }),
    };

    const { result, override } = await runGetUserInfo('google', tokens, {
      store,
      env: { ...ALL_ENABLED, GOOGLE_WORKSPACE_DOMAIN: 'corp.com' },
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.SIGN_IN_FAILED}`);
  });
});

/* ── getUserInfo: Okta native email_verified fail-closed (OLO-9.3) ──────────────────────────── */

describe('getUserInfo — Okta email_verified fail-closed (OLO-9.3)', () => {
  test('native email_verified=true → known identity signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'okta-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        name: 'Ada',
        picture: 'http://img/okta.png',
      }),
    };

    const { result, override } = await runGetUserInfo('okta', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'okta-sub-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
      image: 'http://img/okta.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('email_verified=false → structured unverified-email rejection', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'okta-sub-1',
        email: 'ada@example.com',
        email_verified: false,
      }),
    };

    const { result, override } = await runGetUserInfo('okta', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('missing email_verified claim → fail-closed unverified rejection', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'okta-sub-1', email: 'ada@example.com' }),
    };

    const { result, override } = await runGetUserInfo('okta', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('verified new email routes to onboarding (no auto-create)', async () => {
    const { store, calls } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'okta-sub-1',
        email: 'ada@example.com',
        email_verified: true,
      }),
    };

    const { result, override } = await runGetUserInfo('okta', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'okta',
      email: 'ada@example.com',
    });
  });
});

/* ── getUserInfo: Cognito native email_verified fail-closed (OLO-9.4) ───────────────────────── */

describe('getUserInfo — Cognito email_verified fail-closed (OLO-9.4)', () => {
  test('native email_verified=true → known identity signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'cognito-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        name: 'Ada',
        'cognito:username': 'ada',
      }),
    };

    const { result, override } = await runGetUserInfo('aws', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'cognito-sub-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('falls back to cognito:username when name claim is absent', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'cognito-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        'cognito:username': 'ada-user',
      }),
    };

    const { result } = await runGetUserInfo('aws', tokens, { store, env: ALL_ENABLED });
    expect(result).toMatchObject({ name: 'ada-user' });
  });

  test('email_verified=false → structured unverified-email rejection', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'cognito-sub-1',
        email: 'ada@example.com',
        email_verified: false,
      }),
    };

    const { result, override } = await runGetUserInfo('aws', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('missing email_verified claim → fail-closed unverified rejection', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'cognito-sub-1', email: 'ada@example.com' }),
    };

    const { result, override } = await runGetUserInfo('aws', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('verified new email routes to onboarding (no auto-create)', async () => {
    const { store, calls } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'cognito-sub-1',
        email: 'ada@example.com',
        email_verified: true,
      }),
    };

    const { result, override } = await runGetUserInfo('aws', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'aws',
      email: 'ada@example.com',
    });
  });
});


/* ── getUserInfo: keycloak (OLO-9.5) ───────────────────────────────────────────────────────── */

describe('getUserInfo — keycloak (OLO-9.5)', () => {
  test('verified email admits and returns Better Auth user info', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'kc-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        name: 'Ada Lovelace',
        picture: 'http://img/kc.png',
      }),
    };

    const { result, override } = await runGetUserInfo('keycloak', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(override).toBeNull();
    expect(result).toEqual({
      id: 'kc-sub-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/kc.png',
    });
  });

  test('falls back to preferred_username when name claim is absent', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'kc-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        preferred_username: 'ada',
      }),
    };

    const { result } = await runGetUserInfo('keycloak', tokens, { store, env: ALL_ENABLED });
    expect(result?.name).toBe('ada');
  });

  test('missing / false email_verified fail-closes (unverified-email)', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'kc-sub-1',
        email: 'ada@example.com',
        email_verified: false,
      }),
    };

    const { result, override } = await runGetUserInfo('keycloak', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('absent email_verified claim also fail-closes', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'kc-sub-1', email: 'ada@example.com' }),
    };

    const { result, override } = await runGetUserInfo('keycloak', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('unknown verified email creates pending signup (onboarding)', async () => {
    const { store, calls } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'kc-sub-1',
        email: 'ada@example.com',
        email_verified: true,
      }),
    };

    const { result, override } = await runGetUserInfo('keycloak', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'keycloak',
      email: 'ada@example.com',
    });
  });
});

/* ── getUserInfo: Auth0 native email_verified fail-closed (OLO-9.7) ─────────────────────────── */

describe('getUserInfo — Auth0 email_verified fail-closed (OLO-9.7)', () => {
  test('native email_verified=true → known identity signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'auth0|sub-1',
        email: 'ada@example.com',
        email_verified: true,
        name: 'Ada',
        picture: 'http://img/auth0.png',
      }),
    };

    const { result, override } = await runGetUserInfo('auth0', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'auth0|sub-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
      image: 'http://img/auth0.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('falls back to nickname when name claim is absent', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'auth0|sub-1',
        email: 'ada@example.com',
        email_verified: true,
        nickname: 'ada',
      }),
    };

    const { result } = await runGetUserInfo('auth0', tokens, { store, env: ALL_ENABLED });
    expect(result?.name).toBe('ada');
  });

  test('email_verified=false → structured unverified-email rejection', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'auth0|sub-1',
        email: 'ada@example.com',
        email_verified: false,
      }),
    };

    const { result, override } = await runGetUserInfo('auth0', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('missing email_verified claim → fail-closed unverified rejection', async () => {
    const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'auth0|sub-1', email: 'ada@example.com' }),
    };

    const { result, override } = await runGetUserInfo('auth0', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('verified new email routes to onboarding (no auto-create)', async () => {
    const { store, calls } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'auth0|sub-1',
        email: 'ada@example.com',
        email_verified: true,
      }),
    };

    const { result, override } = await runGetUserInfo('auth0', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'auth0',
      email: 'ada@example.com',
    });
  });
});


/* ── getUserInfo: LINE email permission states (OLO-9.41) ───────────────────────────────────── */

describe('getUserInfo — LINE email permission states (OLO-9.41)', () => {
  test('email + email_verified=true → known identity signs in (permission granted)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'Uline-sub-1',
        email: 'ada@example.com',
        email_verified: true,
        name: 'Ada',
        picture: 'http://img/line.png',
      }),
    };

    const { result, override } = await runGetUserInfo('line', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'Uline-sub-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
      image: 'http://img/line.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('email without email_verified claim → fail-closed unverified (link-first)', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'Uline-sub-1',
        email: 'ada@example.com',
        name: 'Ada',
      }),
    };

    const { result, override } = await runGetUserInfo('line', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('no email claim (permission not granted) → email-required rejection', async () => {
    const { store } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ sub: 'Uline-sub-1', name: 'Ada' }),
    };

    const { result, override } = await runGetUserInfo('line', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('verified email on new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        sub: 'Uline-sub-1',
        email: 'ada@example.com',
        email_verified: true,
      }),
    };

    const { result, override } = await runGetUserInfo('line', tokens, {
      store,
      env: ALL_ENABLED,
    });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'line',
      email: 'ada@example.com',
    });
  });

  test('falls back to userinfo when id token is absent', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const fetchImpl: FetchLike = async (url) => {
      if (url.includes('/oauth2/v2.1/userinfo')) {
        return {
          ok: true,
          json: async () => ({
            sub: 'Uline-sub-1',
            email: 'ada@example.com',
            email_verified: true,
            name: 'Ada',
          }),
        };
      }
      return { ok: false, json: async () => null };
    };

    const { result, override } = await runGetUserInfo(
      'line',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'Uline-sub-1',
      email: 'ada@example.com',
      emailVerified: true,
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });
});

/* ── getUserInfo: VK ID fail-closed / link-first (OLO-9.42) ─────────────────────────────────── */

describe('getUserInfo — VK ID fail-closed link-first (OLO-9.42)', () => {
  const vkUserInfo = (user: Record<string, unknown>): FetchLike => {
    return async (url, init) => {
      if (url.includes('/oauth2/user_info') && init.method === 'POST') {
        return {
          ok: true,
          json: async () => ({ user }),
        };
      }
      return { ok: false, json: async () => null };
    };
  };

  test('known identity signs in without email_verified (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const fetchImpl = vkUserInfo({
      user_id: 'vk-user-1',
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
      avatar: 'http://img/vk.png',
    });

    const { result, override } = await runGetUserInfo(
      'vk',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'vk-user-1',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'http://img/vk.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('email without verified claim → fail-closed unverified (no auto-link)', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const fetchImpl = vkUserInfo({
      user_id: 'vk-user-1',
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
    });

    const { result, override } = await runGetUserInfo(
      'vk',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('explicit link intent links despite unverified email', async () => {
    const { store, calls } = makeStore();
    const fetchImpl = vkUserInfo({
      user_id: 'vk-user-1',
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
    });

    const { result, override } = await runGetUserInfo(
      'vk',
      { accessToken: 'tok' },
      {
        store,
        env: ALL_ENABLED,
        fetchImpl,
        resolveLinkToUserId: async () => 'session-user',
      }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'vk',
      providerUserId: 'vk-user-1',
    });
  });

  test('no email → email-required rejection', async () => {
    const { store } = makeStore();
    const fetchImpl = vkUserInfo({
      user_id: 'vk-user-1',
      first_name: 'Ada',
      last_name: 'Lovelace',
    });

    const { result, override } = await runGetUserInfo(
      'vk',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('user.verified badge is not treated as email_verified', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const fetchImpl = vkUserInfo({
      user_id: 'vk-user-1',
      email: 'ada@example.com',
      verified: true,
      first_name: 'Ada',
      last_name: 'Lovelace',
    });

    const { result, override } = await runGetUserInfo(
      'vk',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });
});


/* ── getUserInfo: WeChat link-only (OLO-9.43) ─────────────────────────────────────────────────── */

describe('getUserInfo — WeChat link-only (OLO-9.43)', () => {
  const wechatUserInfo = (profile: Record<string, unknown>): FetchLike => {
    return async (url) => {
      if (url.includes('/sns/userinfo')) {
        return {
          ok: true,
          json: async () => profile,
        };
      }
      return { ok: false, json: async () => null };
    };
  };

  const wechatTokens = (openid: string, unionid?: string) => ({
    accessToken: 'tok',
    raw: { openid, ...(unionid ? { unionid } : {}) },
  });

  test('fresh sign-in with no email → email-required rejection', async () => {
    const { store } = makeStore();
    const fetchImpl = wechatUserInfo({
      openid: 'wx-openid-1',
      nickname: 'Ada',
      headimgurl: 'http://img/wx.png',
    });

    const { result, override } = await runGetUserInfo(
      'wechat',
      wechatTokens('wx-openid-1'),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('explicit link intent links without email', async () => {
    const { store, calls } = makeStore();
    const fetchImpl = wechatUserInfo({
      openid: 'wx-openid-1',
      nickname: 'Ada',
      headimgurl: 'http://img/wx.png',
    });

    const { result, override } = await runGetUserInfo(
      'wechat',
      wechatTokens('wx-openid-1'),
      {
        store,
        env: ALL_ENABLED,
        fetchImpl,
        resolveLinkToUserId: async () => 'session-user',
      }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'wechat',
      providerUserId: 'wx-openid-1',
    });
  });

  test('known identity subsequent sign-in prefers unionid and adopts bound user email', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const fetchImpl = wechatUserInfo({
      openid: 'wx-openid-1',
      unionid: 'wx-union-1',
      nickname: 'Ada',
      headimgurl: 'http://img/wx.png',
    });

    const { result, override } = await runGetUserInfo(
      'wechat',
      wechatTokens('wx-openid-1', 'wx-union-1'),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'wx-union-1',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada',
      image: 'http://img/wx.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('identity keys on openid when unionid is absent', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const fetchImpl = wechatUserInfo({
      openid: 'wx-openid-1',
      nickname: 'Ada',
    });

    const { result } = await runGetUserInfo(
      'wechat',
      wechatTokens('wx-openid-1'),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: 'wx-openid-1', email: 'ada@example.com' });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });
});

/* ── getUserInfo: Atlassian /me profile (OLO-9.8) ──────────────────────────────────────────── */

describe('getUserInfo — Atlassian sign-in and linking (OLO-9.8)', () => {
  /** Serve `profile` from the User Identity API and record the request it was fetched with. */
  const atlassianMe = (profile: Record<string, unknown> | null) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      if (url === 'https://api.atlassian.com/me' && profile) {
        return { ok: true, json: async () => profile };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  const ME = {
    account_type: 'atlassian',
    account_id: '712020:atl-account-1',
    email: 'ada@example.com',
    name: 'Ada Lovelace',
    nickname: 'ada',
    picture: 'http://img/atl.png',
    account_status: 'active',
  };

  test('verified email auto-links an existing account and signs in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl, requests } = atlassianMe({ ...ME, email_verified: true });

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '712020:atl-account-1',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/atl.png',
    });
    expect(requests).toEqual([
      { url: 'https://api.atlassian.com/me', authorization: 'Bearer tok' },
    ]);
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'atlassian',
      providerUserId: '712020:atl-account-1',
    });
  });

  test('known identity signs in on a later visit', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = atlassianMe(ME);

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '712020:atl-account-1', email: 'ada@example.com' });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('email without a verified claim → fail-closed unverified (no auto-link)', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = atlassianMe(ME);

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('an explicit email_verified: false is not trusted', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = atlassianMe({ ...ME, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('explicit link intent links the Atlassian account to the session user', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = atlassianMe(ME);

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      {
        store,
        env: ALL_ENABLED,
        fetchImpl,
        resolveLinkToUserId: async () => 'session-user',
      }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'atlassian',
      providerUserId: '712020:atl-account-1',
    });
  });

  test('no email → email-required rejection', async () => {
    const { store } = makeStore();
    const { fetchImpl } = atlassianMe({ ...ME, email: undefined });

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('falls back to the nickname when the profile has no name', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = atlassianMe({ ...ME, name: undefined });

    const { result } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ name: 'ada' });
  });

  test('a failed /me fetch never signs anyone in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = atlassianMe(null);

    const { result, override } = await runGetUserInfo(
      'atlassian',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.recordUserLogin).toHaveLength(0);
  });
});

/* ── getUserInfo: Bitbucket /2.0/user + /2.0/user/emails (OLO-9.9) ─────────────────────────── */

describe('getUserInfo — Bitbucket primary confirmed email (OLO-9.9)', () => {
  const USER_URL = 'https://api.bitbucket.org/2.0/user';
  const EMAILS_URL = 'https://api.bitbucket.org/2.0/user/emails?pagelen=100';

  /** Serve the profile and the emails envelope, recording each request's url + bearer token. */
  const bitbucketApi = (user: Record<string, unknown> | null, emails: unknown) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      if (url === USER_URL && user) return { ok: true, json: async () => user };
      if (url === EMAILS_URL && emails) return { ok: true, json: async () => emails };
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  const USER = {
    uuid: '{5d6f0c1e-bb01-4c0f-9a57-0d2f6f2f9d11}',
    account_id: '712020:bb-account-1',
    username: 'ada',
    display_name: 'Ada Lovelace',
    links: { avatar: { href: 'http://img/bb.png' } },
  };
  /** A confirmed secondary address first, so "first entry" and "primary" cannot be confused. */
  const emailsWithPrimary = (isConfirmed: boolean) => ({
    pagelen: 100,
    values: [
      { email: 'old@example.com', is_primary: false, is_confirmed: true, type: 'email' },
      { email: 'ada@example.com', is_primary: true, is_confirmed: isConfirmed, type: 'email' },
    ],
  });

  test('primary confirmed address auto-links an existing account and signs in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl, requests } = bitbucketApi(USER, emailsWithPrimary(true));

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: USER.uuid,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/bb.png',
    });
    expect(requests).toEqual([
      { url: USER_URL, authorization: 'Bearer tok' },
      { url: EMAILS_URL, authorization: 'Bearer tok' },
    ]);
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'bitbucket',
      providerUserId: USER.uuid,
    });
  });

  test('known identity signs in on a later visit', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = bitbucketApi(USER, emailsWithPrimary(true));

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: USER.uuid, email: 'ada@example.com' });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('unconfirmed primary address → unverified-email (a confirmed secondary does not count)', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = bitbucketApi(USER, emailsWithPrimary(false));

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('explicit link intent links the Bitbucket account to the session user', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = bitbucketApi(USER, emailsWithPrimary(true));

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      {
        store,
        env: ALL_ENABLED,
        fetchImpl,
        resolveLinkToUserId: async () => 'session-user',
      }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'bitbucket',
      providerUserId: USER.uuid,
    });
  });

  test('emails API unavailable (no email scope) → email-required rejection', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = bitbucketApi(USER, null);

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('an email on the profile itself is ignored — only the emails API is trusted', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'victim@example.com': OK_USER } });
    const { fetchImpl } = bitbucketApi(
      { ...USER, email: 'victim@example.com', email_verified: true },
      emailsWithPrimary(false)
    );

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('falls back to account_id and username when uuid and display_name are missing', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = bitbucketApi(
      { account_id: USER.account_id, username: 'ada' },
      emailsWithPrimary(true)
    );

    const { result } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: USER.account_id, name: 'ada' });
  });

  test('a failed /2.0/user fetch never signs anyone in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = bitbucketApi(null, emailsWithPrimary(true));

    const { result, override } = await runGetUserInfo(
      'bitbucket',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.recordUserLogin).toHaveLength(0);
  });
});

/* ── getUserInfo: azure nOAuth hardening (OLO-1.4) ─────────────────────────────────────────── */

/* ── getUserInfo: Sign in with Slack (OLO-9.17) ────────────────────────────────────────────── */

describe('getUserInfo — Slack sign-in and linking (OLO-9.17)', () => {
  /** The claims Sign in with Slack puts on the id token (and on `openid.connect.userInfo`). */
  const CLAIMS = {
    sub: 'U0R7JM',
    'https://slack.com/user_id': 'U0R7JM',
    'https://slack.com/team_id': 'T0R7GR',
    email: 'ada@example.com',
    email_verified: true,
    name: 'Ada',
    picture: 'http://img/slack.png',
  };

  /** A fetch stub answering Slack's userinfo resource with `body`, recording each request. */
  const slackUserInfo = (body: unknown, ok = true) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init?.headers?.Authorization });
      if (url === 'https://slack.com/api/openid.connect.userInfo') {
        return { ok, json: async () => body };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Slack user id', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = slackUserInfo(null);

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: 'U0R7JM',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
      image: 'http://img/slack.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // The id token carried the claims, so the userinfo resource is never called.
    expect(requests).toEqual([]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: 'U0R7JM', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'slack', providerUserId: 'U0R7JM' },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'slack',
      providerUserId: 'U0R7JM',
      email: 'ada@example.com',
    });
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['null', null],
  ])('email_verified %s → fail-closed unverified, never linked', async (_label, claim) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: claim }) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('no email claim → email-required rejection', async () => {
    const { store } = makeStore();

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email: undefined }) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('explicit link intent links the Slack account to the session user', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: false }) },
      { store, env: ALL_ENABLED, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'slack', providerUserId: 'U0R7JM' },
    });
  });

  test('falls back to openid.connect.userInfo when the id token is absent', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    // Slack's userinfo body carries `ok: true` and may omit `sub` in favour of the namespaced id.
    const { fetchImpl, requests } = slackUserInfo({ ...CLAIMS, ok: true, sub: undefined });

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: 'U0R7JM', email: 'ada@example.com', emailVerified: true });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: 'https://slack.com/api/openid.connect.userInfo', authorization: 'Bearer tok' },
    ]);
  });

  test('a Slack `ok: false` userinfo body (HTTP 200) is discarded, never trusted', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = slackUserInfo({ ...CLAIMS, ok: false, error: 'invalid_auth' });

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('no id token and a failed userinfo fetch refuses the sign-in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = slackUserInfo(null, false);

    const { result, override } = await runGetUserInfo(
      'slack',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
  });
});

/* ── getUserInfo: Sign In with LinkedIn (OLO-9.18) ─────────────────────────────────────────── */

describe('getUserInfo — LinkedIn sign-in and linking (OLO-9.18)', () => {
  /** The claims Sign In with LinkedIn puts on the id token (and on `/v2/userinfo`). */
  const CLAIMS = {
    sub: '782bbtaQ',
    email: 'ada@example.com',
    email_verified: true,
    name: 'Ada Lovelace',
    given_name: 'Ada',
    family_name: 'Lovelace',
    picture: 'http://img/linkedin.png',
    locale: { country: 'US', language: 'en' },
  };

  /** A fetch stub answering LinkedIn's userinfo resource with `body`, recording each request. */
  const linkedinUserInfo = (body: unknown, ok = true) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init?.headers?.Authorization });
      if (url === 'https://api.linkedin.com/v2/userinfo') {
        return { ok, json: async () => body };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the LinkedIn sub', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = linkedinUserInfo(null);

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: '782bbtaQ',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/linkedin.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // The id token carried the claims, so the userinfo resource is never called.
    expect(requests).toEqual([]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '782bbtaQ', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'linkedin', providerUserId: '782bbtaQ' },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'linkedin',
      providerUserId: '782bbtaQ',
      email: 'ada@example.com',
    });
  });

  test('email_verified sent as the string "true" is honored', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: 'true' }) },
      { store, env: ALL_ENABLED }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '782bbtaQ', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['the string "false"', 'false'],
    ['null', null],
  ])('email_verified %s → fail-closed unverified, never linked', async (_label, claim) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: claim }) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('no email claim → email-required rejection', async () => {
    const { store } = makeStore();

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email: undefined }) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('explicit link intent links the LinkedIn account to the session user', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: false }) },
      { store, env: ALL_ENABLED, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'linkedin', providerUserId: '782bbtaQ' },
    });
  });

  test('falls back to /v2/userinfo when the id token is absent', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = linkedinUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '782bbtaQ',
      email: 'ada@example.com',
      emailVerified: true,
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: 'https://api.linkedin.com/v2/userinfo', authorization: 'Bearer tok' },
    ]);
  });

  test('no id token and a failed userinfo fetch refuses the sign-in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = linkedinUserInfo(null, false);

    const { result, override } = await runGetUserInfo(
      'linkedin',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Salesforce (OLO-9.20) ────────────────────────────────────────────────────── */

describe('getUserInfo — Salesforce sign-in and linking (OLO-9.20)', () => {
  /** The identity URL Salesforce uses as `sub`: it names the org and the user. */
  const SUB = 'https://login.salesforce.com/id/00Dxx0000001gPLEAY/005xx000001SwiUAAS';
  /** The claims Salesforce's userinfo resource returns (and the id token, when so configured). */
  const CLAIMS = {
    sub: SUB,
    user_id: '005xx000001SwiUAAS',
    organization_id: '00Dxx0000001gPLEAY',
    preferred_username: 'ada@acme.example',
    name: 'Ada Lovelace',
    email: 'ada@example.com',
    email_verified: true,
    picture: 'https://acme.file.force.com/profilephoto/005/F',
  };
  /** The id token Salesforce issues by default: who signed in, but no profile claims. */
  const BARE_ID_TOKEN = { iss: 'https://login.salesforce.com', sub: SUB, aud: 'sf-id' };

  /** A fetch stub answering `userInfoUrl` with `body`, recording each request. */
  const salesforceUserInfo = (
    body: unknown,
    userInfoUrl = 'https://login.salesforce.com/services/oauth2/userinfo'
  ) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init?.headers?.Authorization });
      if (url === userInfoUrl && body) return { ok: true, json: async () => body };
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the identity URL', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = salesforceUserInfo(null);

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: SUB,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'https://acme.file.force.com/profilephoto/005/F',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // The id token carried the email, so the userinfo resource is never called.
    expect(requests).toEqual([]);
  });

  test('a bare id token is completed from userinfo on the default issuer', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl, requests } = salesforceUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(BARE_ID_TOKEN) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: SUB, email: 'ada@example.com', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'salesforce', providerUserId: SUB },
    });
    expect(requests).toEqual([
      {
        url: 'https://login.salesforce.com/services/oauth2/userinfo',
        authorization: 'Bearer tok',
      },
    ]);
  });

  test('a My Domain issuer moves the userinfo call to that host', async () => {
    const env = { ...ALL_ENABLED, SALESFORCE_ISSUER: 'https://acme.my.salesforce.com/' };
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = salesforceUserInfo(
      CLAIMS,
      'https://acme.my.salesforce.com/services/oauth2/userinfo'
    );

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok' },
      { store, env, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: SUB, email: 'ada@example.com', emailVerified: true });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests.map((r) => r.url)).toEqual([
      'https://acme.my.salesforce.com/services/oauth2/userinfo',
    ]);
  });

  test('a userinfo body for another subject is discarded → email-required', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = salesforceUserInfo({
      ...CLAIMS,
      sub: 'https://login.salesforce.com/id/00Dxx0000001gPLEAY/005xx000009OTHER',
    });

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(BARE_ID_TOKEN) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(CLAIMS) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'salesforce',
      providerUserId: SUB,
      email: 'ada@example.com',
    });
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['the string "false"', 'false'],
    ['null', null],
  ])('email_verified %s → fail-closed unverified, never linked', async (_label, claim) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: claim }) },
      { store, env: ALL_ENABLED }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('unverified email from userinfo is refused the same way', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = salesforceUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(BARE_ID_TOKEN) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('no email from either source → email-required rejection', async () => {
    const { store } = makeStore();
    const { fetchImpl } = salesforceUserInfo({ ...CLAIMS, email: undefined });

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor(BARE_ID_TOKEN) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('explicit link intent links the Salesforce account to the session user', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: false }) },
      { store, env: ALL_ENABLED, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'salesforce', providerUserId: SUB },
    });
  });

  test('no id token and a failed userinfo call is refused, never linked', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = salesforceUserInfo(null);

    const { result, override } = await runGetUserInfo(
      'salesforce',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Discord (OLO-9.19) ───────────────────────────────────────────────────────── */

describe('getUserInfo — Discord sign-in and linking (OLO-9.19)', () => {
  /** The `/users/@me` body for a current-username-system account with an uploaded avatar. */
  const ME = {
    id: '80351110224678912',
    username: 'ada',
    discriminator: '0',
    global_name: 'Ada Lovelace',
    avatar: '8342729096ea3675442027381ff50dfe',
    email: 'ada@example.com',
    verified: true,
  };
  const AVATAR =
    'https://cdn.discordapp.com/avatars/80351110224678912/8342729096ea3675442027381ff50dfe.png';

  /** Serve `profile` from `/users/@me` and record the request it was fetched with. */
  const discordMe = (profile: Record<string, unknown> | null) => {
    const requests: Array<{ url: string; authorization: string | undefined }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init?.headers?.Authorization });
      if (url === 'https://discord.com/api/users/@me' && profile) {
        return { ok: true, json: async () => profile };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Discord user id', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = discordMe(ME);

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: '80351110224678912',
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: AVATAR,
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: 'https://discord.com/api/users/@me', authorization: 'Bearer tok' },
    ]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = discordMe(ME);

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '80351110224678912', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'discord', providerUserId: '80351110224678912' },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = discordMe(ME);

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'discord',
      providerUserId: '80351110224678912',
      email: 'ada@example.com',
    });
  });

  test.each([
    ['false', false],
    ['absent', undefined],
    ['null', null],
    ['the string "true"', 'true'],
    ['the number 1', 1],
  ])('verified %s → rejected with unverified-email, never linked', async (_label, verified) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = discordMe({ ...ME, verified });

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('an `email_verified` field in the body is never trusted over `verified`', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = discordMe({ ...ME, verified: false, email_verified: true });

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([
    ['null', null],
    ['absent', undefined],
  ])('email %s → email-required rejection', async (_label, email) => {
    const { store } = makeStore();
    const { fetchImpl } = discordMe({ ...ME, email });

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('explicit link intent links the Discord account to the session user', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });
    const { fetchImpl } = discordMe({ ...ME, verified: false });

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'discord', providerUserId: '80351110224678912' },
    });
  });

  test.each([
    [
      'animated avatar → .gif',
      { avatar: 'a_1269e74af4df7417b13759eae50c83dc' },
      'https://cdn.discordapp.com/avatars/80351110224678912/a_1269e74af4df7417b13759eae50c83dc.gif',
    ],
    // (80351110224678912 >> 22) % 6 === 5
    [
      'no avatar → default by user id',
      { avatar: null },
      'https://cdn.discordapp.com/embed/avatars/5.png',
    ],
    [
      'no avatar, legacy discriminator → default by discriminator',
      { avatar: null, discriminator: '1337' },
      'https://cdn.discordapp.com/embed/avatars/2.png',
    ],
  ])('avatar: %s', async (_label, overrides, expected) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = discordMe({ ...ME, ...overrides });

    const { result } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ image: expected });
  });

  test('falls back to the username when no display name is set', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = discordMe({ ...ME, global_name: null });

    const { result } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ name: 'ada' });
  });

  test('a failed /users/@me fetch refuses the sign-in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = discordMe(null);

    const { result, override } = await runGetUserInfo(
      'discord',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toMatch(/^\/login\?error=/);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

describe('getUserInfo — azure nOAuth hardening (OLO-1.4)', () => {
  test('forged token (guest upn, no evidence) is rejected with unverified-email', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'victim@corp.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({
        oid: 'aad-oid',
        email: 'victim@corp.com',
        upn: 'attacker#EXT#@evil.onmicrosoft.com',
        name: 'Mallory',
      }),
    };

    const { result, override } = await runGetUserInfo('azure', tokens, { store });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.recordUserLogin).toHaveLength(0);
  });

  test('xms_edov=true verifies the email → auto-links an existing account and admits', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'user@corp.com': OK_USER } });
    const tokens = {
      accessToken: 'tok',
      idToken: idTokenFor({ oid: 'aad-oid', email: 'user@corp.com', xms_edov: true, name: 'User' }),
    };

    const { result, override } = await runGetUserInfo('azure', tokens, { store });

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: 'aad-oid', email: 'user@corp.com', emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0].userId).toBe(OK_USER.id);
  });
});

/* ── Explicit link intent ──────────────────────────────────────────────────────────────────── */

describe('getUserInfo — explicit link intent', () => {
  test('a link-intent user id attaches the identity even with an unverified email', async () => {
    const { store, calls } = makeStore();
    const fetchImpl = makeFetch({ profile: { id: 7, email: 'ada@example.com' } }); // gitlab, no confirmed_at

    const { result, override } = await runGetUserInfo(
      'gitlab',
      { accessToken: 'tok', idToken: null },
      { store, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
  });
});

/* ── Redirect-override transport ───────────────────────────────────────────────────────────── */

describe('applyOauthRedirectOverride', () => {
  test('rewrites the Location of a redirect response when an override was published', async () => {
    const rewritten = await runWithOauthRedirectOverride(async () => {
      const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const fetchImpl = makeFetch({
        profile: { id: 42, email: 'ada@example.com' },
        emails: [{ email: 'ada@example.com', primary: true, verified: false }],
      });
      await makeOAuthGetUserInfo('github', { store, fetchImpl })({ accessToken: 'tok', idToken: null } as any);

      const response = new Response(null, { status: 302, headers: { Location: '/callback/github' } });
      return applyOauthRedirectOverride(response);
    });

    expect(rewritten.status).toBe(302);
    expect(rewritten.headers.get('Location')).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
  });

  test('leaves a redirect untouched when the sign-in was admitted (no override)', async () => {
    const untouched = await runWithOauthRedirectOverride(async () => {
      const response = new Response(null, { status: 302, headers: { Location: '/dashboard' } });
      return applyOauthRedirectOverride(response);
    });
    expect(untouched.headers.get('Location')).toBe('/dashboard');
  });

  test('leaves a non-redirect (200) response untouched even with an override set', async () => {
    const untouched = await runWithOauthRedirectOverride(async () => {
      const response = new Response('ok', { status: 200, headers: { Location: '/x' } });
      // publish an override, then confirm a 200 is not rewritten
      const { store } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const fetchImpl = makeFetch({
        profile: { id: 42, email: 'ada@example.com' },
        emails: [{ email: 'ada@example.com', primary: true, verified: false }],
      });
      await makeOAuthGetUserInfo('github', { store, fetchImpl })({ accessToken: 'tok', idToken: null } as any);
      return applyOauthRedirectOverride(response);
    });
    expect(untouched.status).toBe(200);
    expect(untouched.headers.get('Location')).toBe('/x');
  });

  test('outside a scope the override is inert (getUserInfo still returns its outcome)', async () => {
    const { store } = makeStore({ identityUserId: OK_USER.id, usersById: { [OK_USER.id]: OK_USER } });
    const fetchImpl = makeFetch({
      profile: { id: 42, email: 'ada@example.com' },
      emails: [{ email: 'ada@example.com', primary: true, verified: true }],
    });
    // No runWithOauthRedirectOverride wrapper: setOauthRedirectOverride no-ops, result still returned.
    const result = await makeOAuthGetUserInfo('github', { store, fetchImpl })({
      accessToken: 'tok',
      idToken: null,
    } as any);
    expect(result).toMatchObject({ id: '42', emailVerified: true });
    expect(getOauthRedirectOverride()).toBeNull();
  });
});

/* ── getUserInfo: Notion fail-closed / link-first (OLO-9.21) ────────────────────────────────── */

describe('getUserInfo — Notion fail-closed link-first (OLO-9.21)', () => {
  /** A Notion person as the token response's `owner.user` and `/v1/users/me` both carry it. */
  const PERSON = {
    object: 'user',
    id: 'd40e767c-d7af-4b18-a86d-55c61f1e39a4',
    type: 'person',
    name: 'Ada Lovelace',
    avatar_url: 'http://img/notion.png',
    person: { email: 'ada@example.com' },
  };

  /** Tokens whose raw exchange response names `user` as the owner. */
  const tokensFor = (user: Record<string, unknown> | null) => ({
    accessToken: 'tok',
    raw: user ? { owner: { type: 'user', user } } : {},
  });

  /** Serve `owner` as the bot owner on `/v1/users/me` and record each request's headers. */
  const notionMe = (owner: Record<string, unknown> | null) => {
    const requests: Array<{ url: string; headers: Record<string, string> }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, headers: init.headers });
      if (url === 'https://api.notion.com/v1/users/me' && owner) {
        return {
          ok: true,
          json: async () => ({ object: 'user', id: 'bot-1', type: 'bot', bot: { owner } }),
        };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in from the token exchange, with no userinfo call (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = notionMe(null);

    const { result, override } = await runGetUserInfo('notion', tokensFor(PERSON), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
    });

    expect(override).toBeNull();
    expect(result).toEqual({
      id: PERSON.id,
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'http://img/notion.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([]);
  });

  test('falls back to /v1/users/me (Bearer + Notion-Version) when the exchange kept no owner', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = notionMe({ type: 'user', user: PERSON });

    const { result, override } = await runGetUserInfo('notion', tokensFor(null), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
    });

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: PERSON.id, email: 'ada@example.com', emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe('https://api.notion.com/v1/users/me');
    expect(requests[0].headers).toMatchObject({
      Authorization: 'Bearer tok',
      'Notion-Version': '2022-06-28',
    });
  });

  test('a partial owner on the exchange is completed from /v1/users/me', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = notionMe({ type: 'user', user: PERSON });

    const { result } = await runGetUserInfo(
      'notion',
      tokensFor({ object: 'user', id: PERSON.id, type: 'person' }),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: PERSON.id, email: 'ada@example.com', name: 'Ada Lovelace' });
    expect(requests).toHaveLength(1);
  });

  test('/v1/users/me naming a different person never replaces the exchange owner', async () => {
    const { store } = makeStore();
    const { fetchImpl } = notionMe({
      type: 'user',
      user: { ...PERSON, id: 'someone-else', person: { email: 'eve@example.com' } },
    });

    const { result, override } = await runGetUserInfo(
      'notion',
      tokensFor({ object: 'user', id: PERSON.id, type: 'person' }),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = notionMe(null);

    const { result, override } = await runGetUserInfo('notion', tokensFor(PERSON), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = notionMe(null);

    const { result, override } = await runGetUserInfo('notion', tokensFor(PERSON), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
    });

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([true, 'true'])(
    'an email_verified field in a Notion body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = notionMe(null);

      const { result, override } = await runGetUserInfo(
        'notion',
        tokensFor({ ...PERSON, email_verified: emailVerified }),
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
    }
  );

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = notionMe(null);

    const { result, override } = await runGetUserInfo('notion', tokensFor(PERSON), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
      resolveLinkToUserId: async () => 'session-user',
    });

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'notion',
      providerUserId: PERSON.id,
    });
  });

  test('a person with no email → email-required rejection', async () => {
    const { store } = makeStore();
    const { fetchImpl } = notionMe({ type: 'user', user: { ...PERSON, person: {} } });

    const { result, override } = await runGetUserInfo(
      'notion',
      tokensFor({ ...PERSON, person: {} }),
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['a bot owner', { ...PERSON, type: 'bot' }],
    ['a user object without an id', { ...PERSON, id: '' }],
  ])('%s is refused: only a person can sign in', async (_label, user) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = notionMe({ type: 'user', user });

    const { result, override } = await runGetUserInfo('notion', tokensFor(user), {
      store,
      env: ALL_ENABLED,
      fetchImpl,
    });

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
  });

  test('a workspace-level token and a failed userinfo fetch yield no identity', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = notionMe(null);

    const { result, override } = await runGetUserInfo(
      'notion',
      { accessToken: 'tok', raw: { owner: { workspace: true } } },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
  });
});

/* ── getUserInfo: Figma fail-closed / link-first (OLO-9.22) ─────────────────────────────────── */

describe('getUserInfo — Figma fail-closed link-first (OLO-9.22)', () => {
  /** A Figma user as `/v1/me` returns it. */
  const ME = {
    id: '1234567890123456789',
    email: 'ada@example.com',
    handle: 'Ada Lovelace',
    img_url: 'http://img/figma.png',
  };

  /** Serve `profile` on `/v1/me` (a failed response when null) and record each request. */
  const figmaMe = (profile: Record<string, unknown> | null) => {
    const requests: Array<{ url: string; authorization: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      if (url === 'https://api.figma.com/v1/me' && profile) {
        return { ok: true, json: async () => profile };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the Figma user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = figmaMe(ME);

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: ME.id,
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'http://img/figma.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([{ url: 'https://api.figma.com/v1/me', authorization: 'Bearer tok' }]);
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = figmaMe(ME);

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = figmaMe(ME);

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([true, 'true'])(
    'an email_verified field in a Figma body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = figmaMe({ ...ME, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'figma',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
    }
  );

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = figmaMe(ME);

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'figma',
      providerUserId: ME.id,
    });
  });

  test.each([undefined, '', 42])('email %p → email-required rejection', async (email) => {
    const { store } = makeStore();
    const { fetchImpl } = figmaMe({ ...ME, email });

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['a failed /v1/me fetch', null, 'tok'],
    ['a body without an id', { ...ME, id: '' }, 'tok'],
    ['a missing access token', ME, ''],
  ])('%s yields no identity', async (_label, profile, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = figmaMe(profile);

    const { result, override } = await runGetUserInfo(
      'figma',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
  });
});

/* ── getUserInfo: Linear fail-closed / link-first (OLO-9.23) ────────────────────────────────── */

describe('getUserInfo — Linear fail-closed link-first (OLO-9.23)', () => {
  /** A Linear user as the GraphQL `viewer` query returns it. */
  const VIEWER = {
    id: '2f6c1a5e-8b0d-4c3a-9e7f-1d2c3b4a5e6f',
    email: 'ada@example.com',
    name: 'Ada Lovelace',
    avatarUrl: 'http://img/linear.png',
  };

  /**
   * Serve `body` on the GraphQL endpoint (a failed response when null) and record each request.
   * `body` is the whole response, so a test can return a GraphQL error or a missing viewer.
   */
  const linearGraphql = (body: unknown) => {
    const requests: Array<{
      url: string;
      method?: string;
      authorization: string;
      contentType: string;
      body?: string;
    }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({
        url,
        method: init.method,
        authorization: init.headers.Authorization,
        contentType: init.headers['Content-Type'],
        body: init.body,
      });
      if (url === 'https://api.linear.app/graphql' && body !== null) {
        return { ok: true, json: async () => body };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  /** Wrap a viewer in the GraphQL response envelope. */
  const viewerBody = (viewer: Record<string, unknown>) => ({ data: { viewer } });

  test('known identity signs in, keyed on the Linear user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = linearGraphql(viewerBody(VIEWER));

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: VIEWER.id,
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'http://img/linear.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      url: 'https://api.linear.app/graphql',
      method: 'POST',
      authorization: 'Bearer tok',
      contentType: 'application/json',
    });
    const query = (JSON.parse(requests[0].body ?? '{}') as { query: string }).query;
    expect(query).toContain('viewer');
    for (const field of ['id', 'name', 'email', 'avatarUrl']) expect(query).toContain(field);
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = linearGraphql(viewerBody(VIEWER));

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = linearGraphql(viewerBody(VIEWER));

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([true, 'true'])(
    'an email_verified field in a Linear viewer (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = linearGraphql(viewerBody({ ...VIEWER, email_verified: emailVerified }));

      const { result, override } = await runGetUserInfo(
        'linear',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
    }
  );

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = linearGraphql(viewerBody(VIEWER));

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'linear',
      providerUserId: VIEWER.id,
    });
  });

  test.each([undefined, '', 42])('email %p → email-required rejection', async (email) => {
    const { store } = makeStore();
    const { fetchImpl } = linearGraphql(viewerBody({ ...VIEWER, email }));

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['a failed GraphQL request', null, 'tok'],
    ['a GraphQL error with no data', { errors: [{ message: 'Authentication required' }] }, 'tok'],
    ['a null viewer', { data: { viewer: null } }, 'tok'],
    ['a viewer without an id', { data: { viewer: { ...VIEWER, id: '' } } }, 'tok'],
    ['a missing access token', { data: { viewer: VIEWER } }, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = linearGraphql(body);

    const { result, override } = await runGetUserInfo(
      'linear',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
  });
});

/* ── getUserInfo: Dropbox (OLO-9.24) ───────────────────────────────────────────────────────── */

describe('getUserInfo — Dropbox sign-in and linking (OLO-9.24)', () => {
  /** A Dropbox account as `get_current_account` returns it. */
  const ACCOUNT = {
    account_id: 'dbid:AAH4f99T0taONIb-OurWxbNQ6ywGRopQngc',
    name: {
      given_name: 'Ada',
      surname: 'Lovelace',
      familiar_name: 'Ada',
      display_name: 'Ada Lovelace',
      abbreviated_name: 'AL',
    },
    email: 'ada@example.com',
    email_verified: true,
    profile_photo_url: 'http://img/dropbox.png',
  };
  const ACCOUNT_URL = 'https://api.dropboxapi.com/2/users/get_current_account';

  /** Serve `account` from `get_current_account` (a failed response when null) and record each request. */
  const dropboxAccount = (account: unknown) => {
    const requests: Array<{
      url: string;
      method?: string;
      authorization: string;
      contentType: string | undefined;
      body?: string;
    }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({
        url,
        method: init.method,
        authorization: init.headers.Authorization,
        contentType: init.headers['Content-Type'],
        body: init.body,
      });
      if (url === ACCOUNT_URL && account !== null) {
        return { ok: true, json: async () => account };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Dropbox account id', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = dropboxAccount(ACCOUNT);

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: ACCOUNT.account_id,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/dropbox.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // An RPC endpoint: POST, no body, and no JSON content type (Dropbox rejects an empty JSON body).
    expect(requests).toEqual([
      {
        url: ACCOUNT_URL,
        method: 'POST',
        authorization: 'Bearer tok',
        contentType: undefined,
        body: undefined,
      },
    ]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = dropboxAccount(ACCOUNT);

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ACCOUNT.account_id, emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'dropbox', providerUserId: ACCOUNT.account_id },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = dropboxAccount(ACCOUNT);

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'dropbox',
      providerUserId: ACCOUNT.account_id,
      email: 'ada@example.com',
    });
  });

  test.each([
    ['false', false],
    ['absent', undefined],
    ['null', null],
    ['the string "true"', 'true'],
    ['the number 1', 1],
  ])(
    'email_verified %s → rejected with unverified-email, never linked or signed up',
    async (_label, emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = dropboxAccount({ ...ACCOUNT, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'dropbox',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('unverified email on a new account is refused, not sent to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('unverified email on an already-linked identity still signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ACCOUNT.account_id, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links the Dropbox account despite an unverified email', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'dropbox', providerUserId: ACCOUNT.account_id },
    });
  });

  test.each([
    ['null', null],
    ['absent', undefined],
    ['empty', ''],
    ['not a string', 42],
  ])('email %s → email-required rejection', async (_label, email) => {
    const { store } = makeStore();
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, email });

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['no name object', { name: undefined }],
    ['a name that is not an object', { name: 'Ada Lovelace' }],
    ['an empty display name', { name: { display_name: '' } }],
  ])('%s → signs in with no display name', async (_label, overrides) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, ...overrides });

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ACCOUNT.account_id });
    expect((result as { name?: unknown }).name).not.toBe('Ada Lovelace');
  });

  test('an account without a profile photo signs in with no image', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = dropboxAccount({ ...ACCOUNT, profile_photo_url: undefined });

    const { result } = await runGetUserInfo(
      'dropbox',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: ACCOUNT.account_id });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
  });

  test.each([
    ['a failed get_current_account request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [ACCOUNT], 'tok'],
    ['an account without an account_id', { ...ACCOUNT, account_id: '' }, 'tok'],
    ['a missing access token', ACCOUNT, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = dropboxAccount(body);

    const { result, override } = await runGetUserInfo(
      'dropbox',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Zoom (OLO-9.25) ──────────────────────────────────────────────────────────── */

describe('getUserInfo — Zoom sign-in and linking (OLO-9.25)', () => {
  /** A Zoom user as `/v2/users/me` returns it (`verified: 1` = verified email). */
  const ME = {
    id: 'KDcuGIm1QgePTO8WbOqwIQ',
    first_name: 'Ada',
    last_name: 'Lovelace',
    display_name: 'Ada Lovelace',
    email: 'ada@example.com',
    type: 2,
    verified: 1,
    pic_url: 'http://img/zoom.png',
    account_id: 'q6gBJVO5TzexKYTb_I2rpg',
    status: 'active',
  };
  const ME_URL = 'https://api.zoom.us/v2/users/me';

  /** Serve `me` from `/v2/users/me` (a failed response when null) and record each request. */
  const zoomMe = (me: unknown) => {
    const requests: Array<{ url: string; method?: string; authorization: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, method: init.method, authorization: init.headers.Authorization });
      if (url === ME_URL && me !== null) {
        return { ok: true, json: async () => me };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Zoom user id', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = zoomMe(ME);

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: ME.id,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/zoom.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([{ url: ME_URL, method: undefined, authorization: 'Bearer tok' }]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = zoomMe(ME);

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ME.id, emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'zoom', providerUserId: ME.id },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = zoomMe(ME);

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'zoom',
      providerUserId: ME.id,
      email: 'ada@example.com',
    });
  });

  test.each([
    ['0', 0],
    ['absent', undefined],
    ['null', null],
    ['the boolean true', true],
    ['the string "1"', '1'],
    ['the string "true"', 'true'],
    ['the number 2', 2],
  ])(
    'verified %s → rejected with unverified-email, never linked or signed up',
    async (_label, verified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = zoomMe({ ...ME, verified });

      const { result, override } = await runGetUserInfo(
        'zoom',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('an email_verified field in a Zoom body is overwritten, never trusted', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = zoomMe({ ...ME, verified: 0, email_verified: true });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('unverified email on a new account is refused, not sent to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = zoomMe({ ...ME, verified: 0 });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('unverified email on an already-linked identity still signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = zoomMe({ ...ME, verified: 0 });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ME.id, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links the Zoom account despite an unverified email', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });
    const { fetchImpl } = zoomMe({ ...ME, verified: 0 });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'zoom', providerUserId: ME.id },
    });
  });

  test.each([
    ['null', null],
    ['absent', undefined],
    ['empty', ''],
    ['not a string', 42],
  ])('email %s → email-required rejection', async (_label, email) => {
    const { store } = makeStore();
    const { fetchImpl } = zoomMe({ ...ME, email });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['no display name', { display_name: undefined }],
    ['an empty display name', { display_name: '' }],
    ['a display name that is not a string', { display_name: 7 }],
  ])('%s → signs in with no display name', async (_label, overrides) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = zoomMe({ ...ME, ...overrides });

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: ME.id });
    expect((result as { name?: unknown }).name).not.toBe('Ada Lovelace');
  });

  test('a user without a picture signs in with no image', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = zoomMe({ ...ME, pic_url: undefined });

    const { result } = await runGetUserInfo(
      'zoom',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: ME.id });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
  });

  test.each([
    ['a failed /v2/users/me request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [ME], 'tok'],
    ['a user without an id', { ...ME, id: '' }, 'tok'],
    ['a user id that is not a string', { ...ME, id: 42 }, 'tok'],
    ['a missing access token', ME, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = zoomMe(body);

    const { result, override } = await runGetUserInfo(
      'zoom',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Sign in with Hugging Face (OLO-9.26) ─────────────────────────────────────── */

describe('getUserInfo — Hugging Face sign-in and linking (OLO-9.26)', () => {
  /** The claims Hugging Face's userinfo resource returns for `openid profile email`. */
  const CLAIMS = {
    sub: '62f264b9f3c90f4b6514a269',
    name: 'Ada Lovelace',
    preferred_username: 'ada',
    profile: 'https://huggingface.co/ada',
    picture: 'http://img/huggingface.png',
    email: 'ada@example.com',
    email_verified: true,
    isPro: false,
  };
  const USERINFO_URL = 'https://huggingface.co/oauth/userinfo';

  /** Serve `claims` from the userinfo resource (a failed response when null); record requests. */
  const huggingfaceUserInfo = (claims: unknown) => {
    const requests: Array<{ url: string; method?: string; authorization: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, method: init.method, authorization: init.headers.Authorization });
      if (url === USERINFO_URL && claims !== null) {
        return { ok: true, json: async () => claims };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Hugging Face sub', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = huggingfaceUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: CLAIMS.sub,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'http://img/huggingface.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: USERINFO_URL, method: undefined, authorization: 'Bearer tok' },
    ]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = huggingfaceUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'huggingface', providerUserId: CLAIMS.sub },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = huggingfaceUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'huggingface',
      providerUserId: CLAIMS.sub,
      email: 'ada@example.com',
    });
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['the string "false"', 'false'],
    ['null', null],
    ['the number 1', 1],
  ])(
    'email_verified %s → rejected with unverified-email, never linked or signed up',
    async (_label, claim) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email_verified: claim });

      const { result, override } = await runGetUserInfo(
        'huggingface',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('unverified email on a new account is refused, not sent to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('unverified email on an already-linked identity still signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links the Hugging Face account despite an unverified email', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'huggingface', providerUserId: CLAIMS.sub },
    });
  });

  test.each([
    ['null', null],
    ['absent', undefined],
    ['empty', ''],
    ['not a string', 42],
  ])('email %s → email-required rejection', async (_label, email) => {
    const { store } = makeStore();
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['no full name', { name: undefined }],
    ['an empty full name', { name: '' }],
    ['a full name that is not a string', { name: 7 }],
  ])('%s → the display name falls back to the username', async (_label, overrides) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, ...overrides });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, name: 'ada' });
  });

  test('a user without a picture signs in with no image', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, picture: undefined });

    const { result } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: CLAIMS.sub });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
  });

  test('the id token is not read: the userinfo resource is the source of the claims', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = huggingfaceUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: true }) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([
    ['a failed userinfo request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [CLAIMS], 'tok'],
    ['claims without a sub', { ...CLAIMS, sub: '' }, 'tok'],
    ['a sub that is not a string', { ...CLAIMS, sub: 42 }, 'tok'],
    ['a stray id in place of the sub', { ...CLAIMS, sub: undefined, id: 'stray' }, 'tok'],
    ['a missing access token', CLAIMS, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = huggingfaceUserInfo(body);

    const { result, override } = await runGetUserInfo(
      'huggingface',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Sign in with Vercel (OLO-9.27) ───────────────────────────────────────────── */

describe('getUserInfo — Vercel sign-in and linking (OLO-9.27)', () => {
  /** The claims Vercel's userinfo resource returns for `openid email profile`. */
  const CLAIMS = {
    sub: '345e869043f1e55f8bdc837c',
    email: 'ada@example.com',
    email_verified: true,
    name: 'Ada Lovelace',
    preferred_username: 'ada',
    picture: 'https://vercel.com/api/www/avatar/ada',
  };
  const USERINFO_URL = 'https://api.vercel.com/login/oauth/userinfo';

  /** Serve `claims` from the userinfo resource (a failed response when null); record requests. */
  const vercelUserInfo = (claims: unknown) => {
    const requests: Array<{ url: string; method?: string; authorization: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, method: init.method, authorization: init.headers.Authorization });
      if (url === USERINFO_URL && claims !== null) {
        return { ok: true, json: async () => claims };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('verified email on a known identity signs in, keyed on the Vercel sub', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = vercelUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: CLAIMS.sub,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada Lovelace',
      image: 'https://vercel.com/api/www/avatar/ada',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: USERINFO_URL, method: undefined, authorization: 'Bearer tok' },
    ]);
  });

  test('verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = vercelUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, emailVerified: true });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'vercel', providerUserId: CLAIMS.sub },
    });
  });

  test('verified email on a new account routes to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = vercelUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'vercel',
      providerUserId: CLAIMS.sub,
      email: 'ada@example.com',
    });
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['the string "true"', 'true'],
    ['the string "false"', 'false'],
    ['null', null],
    ['the number 1', 1],
  ])(
    'email_verified %s → rejected with unverified-email, never linked or signed up',
    async (_label, claim) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email_verified: claim });

      const { result, override } = await runGetUserInfo(
        'vercel',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('unverified email on a new account is refused, not sent to onboarding', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('unverified email on an already-linked identity still signs in', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links the Vercel account despite an unverified email', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => OK_USER.id }
    );

    expect(result).toBeNull();
    expect(override).toContain('/ade/dashboard/linked-accounts');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'vercel', providerUserId: CLAIMS.sub },
    });
  });

  test.each([
    ['null', null],
    ['absent', undefined],
    ['empty', ''],
    ['not a string', 42],
  ])('email %s → email-required rejection', async (_label, email) => {
    const { store } = makeStore();
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['no full name', { name: undefined }],
    ['an empty full name', { name: '' }],
    ['a full name that is not a string', { name: 7 }],
  ])('%s → the display name falls back to the username', async (_label, overrides) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, ...overrides });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, name: 'ada' });
  });

  test('a user without a picture signs in with no image', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, picture: undefined });

    const { result } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: CLAIMS.sub });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
  });

  test('the id token is not read: the userinfo resource is the source of the claims', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = vercelUserInfo({ ...CLAIMS, email_verified: false });

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: true }) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([
    ['a failed userinfo request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [CLAIMS], 'tok'],
    ['claims without a sub', { ...CLAIMS, sub: '' }, 'tok'],
    ['a sub that is not a string', { ...CLAIMS, sub: 42 }, 'tok'],
    ['a stray id in place of the sub', { ...CLAIMS, sub: undefined, id: 'stray' }, 'tok'],
    ['a missing access token', CLAIMS, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = vercelUserInfo(body);

    const { result, override } = await runGetUserInfo(
      'vercel',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Login with Railway (OLO-9.28) ───────────────────────────────────────────── */

describe('getUserInfo — Railway fail-closed link-first (OLO-9.28)', () => {
  /** The claims Railway's `/oauth/me` resource returns for `openid email profile`. */
  const CLAIMS = {
    sub: 'user_abc123',
    email: 'ada@example.com',
    name: 'Ada Lovelace',
    picture: 'https://avatars.githubusercontent.com/u/12345',
  };
  const USERINFO_URL = 'https://backboard.railway.com/oauth/me';

  /** Serve `claims` from `/oauth/me` (a failed response when null); record each request. */
  const railwayUserInfo = (claims: unknown) => {
    const requests: Array<{ url: string; method?: string; authorization: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, method: init.method, authorization: init.headers.Authorization });
      if (url === USERINFO_URL && claims !== null) {
        return { ok: true, json: async () => claims };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the Railway sub (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = railwayUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toEqual({
      id: CLAIMS.sub,
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'https://avatars.githubusercontent.com/u/12345',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: USERINFO_URL, method: undefined, authorization: 'Bearer tok' },
    ]);
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = railwayUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = railwayUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([true, 'true', 1])(
    'an email_verified field in a Railway body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = railwayUserInfo({ ...CLAIMS, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'railway',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('a verified claim in the id token is not read either', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = railwayUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok', idToken: idTokenFor({ ...CLAIMS, email_verified: true }) },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = railwayUserInfo(CLAIMS);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'railway',
      providerUserId: CLAIMS.sub,
    });
  });

  test.each([undefined, null, '', 42])('email %p → email-required rejection', async (email) => {
    const { store } = makeStore();
    const { fetchImpl } = railwayUserInfo({ ...CLAIMS, email });

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test('a user without a name or picture signs in with no image, named by the sub', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = railwayUserInfo({ ...CLAIMS, name: undefined, picture: '' });

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    // Better Auth needs a display name, so the runner falls back to the account id.
    expect(result).toMatchObject({ id: CLAIMS.sub, name: CLAIMS.sub });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
  });

  test.each([
    ['a failed /oauth/me request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [CLAIMS], 'tok'],
    ['claims without a sub', { ...CLAIMS, sub: '' }, 'tok'],
    ['a sub that is not a string', { ...CLAIMS, sub: 42 }, 'tok'],
    ['a stray id in place of the sub', { ...CLAIMS, sub: undefined, id: 'stray' }, 'tok'],
    ['a missing access token', CLAIMS, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = railwayUserInfo(body);

    const { result, override } = await runGetUserInfo(
      'railway',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: HubSpot (OLO-9.29) ───────────────────────────────────────────────────────── */

describe('getUserInfo — HubSpot fail-closed link-first (OLO-9.29)', () => {
  /** The token-info body HubSpot returns for an access token granted the `oauth` scope. */
  const TOKEN_INFO = {
    token: 'tok',
    user: 'ada@example.com',
    hub_domain: 'example.hubspot.com',
    scopes: ['oauth'],
    hub_id: 62515,
    app_id: 456,
    expires_in: 1800,
    user_id: 123456,
    token_type: 'access',
    signed_access_token: { userId: 123456, hubId: 62515, appId: 456 },
  };
  const TOKEN_INFO_URL = 'https://api.hubapi.com/oauth/v1/access-tokens/tok';

  /** Serve `body` from the token-info resource (a failed response when null); record each request. */
  const hubspotTokenInfo = (body: unknown) => {
    const requests: Array<{ url: string; method?: string; authorization?: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, method: init.method, authorization: init.headers.Authorization });
      if (url.startsWith('https://api.hubapi.com/oauth/v1/access-tokens/') && body !== null) {
        return { ok: true, json: async () => body };
      }
      return { ok: false, json: async () => null };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the HubSpot user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = hubspotTokenInfo(TOKEN_INFO);

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    // Token info carries no name or picture: the email is the display name, as in Better Auth.
    expect(result).toMatchObject({
      id: '123456',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'ada@example.com',
    });
    expect((result as { image?: unknown }).image ?? null).toBeNull();
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // The token is the path segment; no bearer header is sent.
    expect(requests).toEqual([{ url: TOKEN_INFO_URL, method: undefined, authorization: undefined }]);
  });

  test('the access token is URL-encoded into the token-info path', async () => {
    const { store } = makeStore();
    const { fetchImpl, requests } = hubspotTokenInfo(TOKEN_INFO);

    await runGetUserInfo('hubspot', { accessToken: 'a/b?c#d' }, { store, env: ALL_ENABLED, fetchImpl });

    expect(requests[0].url).toBe('https://api.hubapi.com/oauth/v1/access-tokens/a%2Fb%3Fc%23d');
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = hubspotTokenInfo(TOKEN_INFO);

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = hubspotTokenInfo(TOKEN_INFO);

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test.each([true, 'true', 1])(
    'an email_verified field in a token-info body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = hubspotTokenInfo({ ...TOKEN_INFO, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'hubspot',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('explicit link intent links despite the unverified email, persisting no token-info secret', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = hubspotTokenInfo(TOKEN_INFO);

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'hubspot',
      providerUserId: '123456',
      email: 'ada@example.com',
    });
    // The token-info body echoes the access token; neither copy reaches profile_data.
    const profileData = JSON.stringify(calls.linkIdentity[0].identity.profileData);
    expect(profileData).not.toContain('signed_access_token');
    expect(profileData).not.toContain('"token"');
  });

  test('falls back to signed_access_token.userId when user_id is absent', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = hubspotTokenInfo({ ...TOKEN_INFO, user_id: undefined });

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '123456' });
  });

  test.each([undefined, null, '', 42])('user %p → email-required rejection', async (user) => {
    const { store } = makeStore();
    const { fetchImpl } = hubspotTokenInfo({ ...TOKEN_INFO, user });

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['a failed token-info request', null, 'tok'],
    ['a body that is not an object', 'nope', 'tok'],
    ['an array body', [TOKEN_INFO], 'tok'],
    ['no user id anywhere', { ...TOKEN_INFO, user_id: undefined, signed_access_token: undefined }, 'tok'],
    ['a zero user id', { ...TOKEN_INFO, user_id: 0, signed_access_token: undefined }, 'tok'],
    ['a fractional user id', { ...TOKEN_INFO, user_id: 1.5, signed_access_token: undefined }, 'tok'],
    ['a boolean user id', { ...TOKEN_INFO, user_id: true, signed_access_token: undefined }, 'tok'],
    ['a blank string user id', { ...TOKEN_INFO, user_id: '  ', signed_access_token: undefined }, 'tok'],
    ['a missing access token', TOKEN_INFO, ''],
  ])('%s yields no identity', async (_label, body, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = hubspotTokenInfo(body);

    const { result, override } = await runGetUserInfo(
      'hubspot',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── Sign in with Apple (OLO-9.30) ─────────────────────────────────────────────────────────── */

describe('exchangeAppleAuthorizationCode — ES256 client secret minted per exchange (OLO-9.30)', () => {
  /** Record every request and answer with `body` (a failed response when `ok` is false). */
  const appleTokenEndpoint = (body: unknown, ok = true) => {
    const requests: Array<{ url: string; method?: string; body?: string; contentType?: string }> =
      [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({
        url,
        method: init.method,
        body: init.body,
        contentType: init.headers['Content-Type'],
      });
      return { ok, json: async () => body };
    };
    return { fetchImpl, requests };
  };

  test('posts the code with a client-secret JWT signed by the .p8 key, and returns the id token', async () => {
    const { fetchImpl, requests } = appleTokenEndpoint({
      access_token: 'at',
      token_type: 'Bearer',
      expires_in: 3600,
      refresh_token: 'rt',
      id_token: 'id.token.value',
    });

    const tokens = await exchangeAppleAuthorizationCode(
      { code: 'the-code', redirectURI: 'https://app.example.com/api/auth/oauth2/callback/apple' },
      ALL_ENABLED,
      fetchImpl,
      1_700_000_000
    );

    expect(tokens).toMatchObject({
      tokenType: 'Bearer',
      accessToken: 'at',
      refreshToken: 'rt',
      idToken: 'id.token.value',
    });
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      url: 'https://appleid.apple.com/auth/token',
      method: 'POST',
      contentType: 'application/x-www-form-urlencoded',
    });
    const form = new URLSearchParams(requests[0].body);
    expect(form.get('client_id')).toBe('com.example.web');
    expect(form.get('code')).toBe('the-code');
    expect(form.get('grant_type')).toBe('authorization_code');
    expect(form.get('redirect_uri')).toBe('https://app.example.com/api/auth/oauth2/callback/apple');
    // The private key itself never leaves the process.
    expect(requests[0].body).not.toContain('PRIVATE KEY');

    const [header, claims, signature] = (form.get('client_secret') ?? '').split('.');
    expect(JSON.parse(Buffer.from(header, 'base64url').toString())).toEqual({
      alg: 'ES256',
      kid: 'ABC123DEFG',
    });
    expect(JSON.parse(Buffer.from(claims, 'base64url').toString())).toEqual({
      iss: 'A1B2C3D4E5',
      iat: 1_700_000_000,
      exp: 1_700_000_300,
      aud: 'https://appleid.apple.com',
      sub: 'com.example.web',
    });
    const { verify } = await import('node:crypto');
    expect(
      verify(
        'sha256',
        Buffer.from(`${header}.${claims}`),
        { key: APPLE_KEY_PAIR.publicKey, dsaEncoding: 'ieee-p1363' },
        Buffer.from(signature, 'base64url')
      )
    ).toBe(true);
  });

  test('a refused exchange throws with Apple’s error code', async () => {
    const { fetchImpl } = appleTokenEndpoint({ error: 'invalid_grant' }, false);
    await expect(
      exchangeAppleAuthorizationCode({ code: 'c', redirectURI: 'r' }, ALL_ENABLED, fetchImpl)
    ).rejects.toThrow('Apple token exchange failed: invalid_grant');
  });

  test('an unusable key is never sent, and its material never reaches the log', async () => {
    const { fetchImpl, requests } = appleTokenEndpoint({});
    const errors: unknown[][] = [];
    const original = console.error;
    console.error = (...args: unknown[]) => {
      errors.push(args);
    };
    try {
      await expect(
        exchangeAppleAuthorizationCode(
          { code: 'c', redirectURI: 'r' },
          { ...ALL_ENABLED, APPLE_PRIVATE_KEY: 'not-a-key!' },
          fetchImpl
        )
      ).rejects.toThrow('APPLE_PRIVATE_KEY');
    } finally {
      console.error = original;
    }
    expect(requests).toHaveLength(0);
    expect(JSON.stringify(errors)).not.toContain('not-a-key!');
  });

  test('the config getToken runs the exchange through the injected fetch', async () => {
    const { fetchImpl, requests } = appleTokenEndpoint({ id_token: 'x.y.z' });
    const cfg = buildGenericOAuthConfig('apple', ALL_ENABLED, { fetchImpl })!;
    const tokens = await cfg.getToken!({ code: 'c', redirectURI: 'r' });
    expect(tokens.idToken).toBe('x.y.z');
    expect(requests[0].url).toBe('https://appleid.apple.com/auth/token');
  });
});

describe('providerConfigSignature — Apple key rotation rebuilds the instance (OLO-9.30)', () => {
  const signatureFor = (env: Record<string, string>) =>
    providerConfigSignature([buildGenericOAuthConfig('apple', env)!]);

  test('the same config signs the same; a new key, Key ID or Team ID signs differently', () => {
    const base = signatureFor(ALL_ENABLED);
    expect(signatureFor(ALL_ENABLED)).toBe(base);
    const rotated = generateKeyPairSync('ec', { namedCurve: 'prime256v1' })
      .privateKey.export({ format: 'pem', type: 'pkcs8' })
      .toString();
    expect(signatureFor({ ...ALL_ENABLED, APPLE_PRIVATE_KEY: rotated })).not.toBe(base);
    expect(signatureFor({ ...ALL_ENABLED, APPLE_KEY_ID: 'ZZZ999ZZZZ' })).not.toBe(base);
    expect(signatureFor({ ...ALL_ENABLED, APPLE_TEAM_ID: 'Z9Y8X7W6V5' })).not.toBe(base);
  });

  test('the signature never contains the private key', () => {
    expect(signatureFor(ALL_ENABLED)).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe('getUserInfo — Sign in with Apple (OLO-9.30)', () => {
  /** The claims of an Apple id token for the `name email` scopes (Apple sends strings). */
  const CLAIMS = {
    iss: 'https://appleid.apple.com',
    aud: 'com.example.web',
    sub: '001234.abcdef0123456789abcdef0123456789.0123',
    email: 'ada@example.com',
    email_verified: 'true',
    is_private_email: 'false',
    nonce_supported: true,
  };
  /** The same person behind Hide My Email: a verified relay address. */
  const RELAY_CLAIMS = {
    ...CLAIMS,
    email: 'x7k2p9q4mz@privaterelay.appleid.com',
    is_private_email: 'true',
  };

  /** The GET callback the form_post bridge produces, carrying the first-consent name. */
  const firstConsentCallback = new Request(
    'https://app.example.com/api/auth/oauth2/callback/apple?code=c&state=s&user=' +
      encodeURIComponent(JSON.stringify({ name: { fullName: 'Ada Lovelace' } }))
  );
  /** A repeat sign-in's GET callback: no `user` field. */
  const repeatCallback = new Request(
    'https://app.example.com/api/auth/oauth2/callback/apple?code=c&state=s'
  );

  /** Run Apple's getUserInfo inside the callback scope of `request`. */
  const runApple = (
    request: Request,
    claims: Record<string, unknown>,
    deps: OAuthRunnerDeps
  ) =>
    runWithAppleCallbackScope(request, () =>
      runGetUserInfo('apple', { idToken: idTokenFor(claims) }, { env: ALL_ENABLED, ...deps })
    );

  test('first consent on a new account routes to onboarding and keeps the name Apple sent once', async () => {
    const { store, calls } = makeStore();

    const { result, override } = await runApple(firstConsentCallback, CLAIMS, { store });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'apple',
      providerUserId: CLAIMS.sub,
      email: 'ada@example.com',
      profile: {
        sub: CLAIMS.sub,
        email: 'ada@example.com',
        email_verified: true,
        is_private_email: false,
        name: 'Ada Lovelace',
      },
    });
    // Only the identity fields travel: no other id-token claim reaches the pending sign-up.
    expect(calls.createPendingSignup[0].profile.nonce_supported).toBeUndefined();
    expect(calls.createPendingSignup[0].profile.iss).toBeUndefined();
  });

  test('a relay-email account signs up with the relay address, flagged as private', async () => {
    // The person's real address belongs to an existing account; the relay address never matches it.
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runApple(firstConsentCallback, RELAY_CLAIMS, { store });

    expect(result).toBeNull();
    expect(override).toBe('/signup/oauth?token=pending-1');
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup[0]).toMatchObject({
      email: 'x7k2p9q4mz@privaterelay.appleid.com',
      profile: { is_private_email: true, email_verified: true },
    });
  });

  test('linking Apple while signed in binds the relay identity to the session account', async () => {
    const { store, calls } = makeStore({ usersById: { [OK_USER.id]: OK_USER } });

    const { override } = await runApple(firstConsentCallback, RELAY_CLAIMS, {
      store,
      resolveLinkToUserId: async () => OK_USER.id,
    });

    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: {
        provider: 'apple',
        providerUserId: RELAY_CLAIMS.sub,
        email: 'x7k2p9q4mz@privaterelay.appleid.com',
        emailVerified: true,
        profileData: { name: 'Ada Lovelace', is_private_email: true },
      },
    });
  });

  test('repeat sign-in after first consent: no name from Apple, the bound account supplies it', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });

    const { result, override } = await runApple(repeatCallback, CLAIMS, { store });

    expect(override).toBeNull();
    expect(result).toEqual({
      id: CLAIMS.sub,
      email: 'ada@example.com',
      emailVerified: true,
      name: 'Ada',
      image: undefined,
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('repeat sign-in with no email claim resolves through the bound identity', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { email: _email, email_verified: _verified, ...noEmail } = CLAIMS;

    const { result, override } = await runApple(repeatCallback, noEmail, { store });

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, email: 'ada@example.com', name: 'Ada' });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('a verified email auto-links the existing account with the same address', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

    const { result, override } = await runApple(repeatCallback, CLAIMS, { store });

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: CLAIMS.sub, emailVerified: true });
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: OK_USER.id,
      identity: { provider: 'apple', providerUserId: CLAIMS.sub, emailVerified: true },
    });
  });

  test('outside a callback scope there is no first-consent name', async () => {
    const { store, calls } = makeStore();
    await runGetUserInfo('apple', { idToken: idTokenFor(CLAIMS) }, { store, env: ALL_ENABLED });
    expect(calls.createPendingSignup[0].profile.name).toBeUndefined();
  });

  test.each([
    ['absent', undefined],
    ['false', false],
    ['the string "false"', 'false'],
    ['null', null],
    ['the number 1', 1],
  ])(
    'email_verified %s → rejected with unverified-email, never linked or signed up',
    async (_label, claim) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });

      const { result, override } = await runApple(
        repeatCallback,
        { ...CLAIMS, email_verified: claim },
        { store }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('email_verified true (boolean) is trusted like "true"', async () => {
    const { store, calls } = makeStore();
    await runApple(repeatCallback, { ...CLAIMS, email_verified: true }, { store });
    expect(calls.createPendingSignup).toHaveLength(1);
  });

  test.each([
    ['another issuer', { ...CLAIMS, iss: 'https://evil.example.com' }],
    ['another audience', { ...CLAIMS, aud: 'com.example.other' }],
    ['no sub', { ...CLAIMS, sub: undefined }],
    ['an undecodable id token', null],
  ])('%s yields no identity', async (_label, claims) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });

    const { result, override } = await runWithAppleCallbackScope(repeatCallback, () =>
      runGetUserInfo(
        'apple',
        { idToken: claims ? idTokenFor(claims) : 'garbage' },
        { store, env: ALL_ENABLED }
      )
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('an audience array that includes the Services ID is accepted', async () => {
    const { store, calls } = makeStore();
    await runApple(repeatCallback, { ...CLAIMS, aud: ['com.example.web'] }, { store });
    expect(calls.createPendingSignup).toHaveLength(1);
  });
});

/* ── getUserInfo: Facebook (OLO-9.31) ──────────────────────────────────────────────────────── */

describe('getUserInfo — Facebook fail-closed link-first (OLO-9.31)', () => {
  /** The `debug_token` body Graph returns for a valid user token issued to this app. */
  const DEBUG_TOKEN = { data: { app_id: 'fb-app-id', is_valid: true, user_id: '10158' } };
  /** The Graph `/me?fields=id,name,email,picture` body for that user. */
  const ME = {
    id: '10158',
    name: 'Ada Lovelace',
    email: 'ada@example.com',
    picture: {
      data: { height: 50, width: 50, is_silhouette: false, url: 'https://graph.example/ada.jpg' },
    },
  };
  const ME_URL = 'https://graph.facebook.com/me?fields=id,name,email,picture';

  /**
   * Serve `debugBody` from `debug_token` and `meBody` from `/me` (a failed response when null);
   * record each request.
   */
  const facebookGraph = (debugBody: unknown, meBody: unknown) => {
    const requests: Array<{ url: string; authorization?: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      const body = url.startsWith('https://graph.facebook.com/debug_token?')
        ? debugBody
        : url === ME_URL
          ? meBody
          : null;
      return body === null ? { ok: false, json: async () => null } : { ok: true, json: async () => body };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the Facebook user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = facebookGraph(DEBUG_TOKEN, ME);

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '10158',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'https://graph.example/ada.jpg',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // debug_token first (app access token, no bearer header), then /me with the user token.
    expect(requests).toHaveLength(2);
    const debug = new URL(requests[0].url);
    expect(debug.origin + debug.pathname).toBe('https://graph.facebook.com/debug_token');
    expect(debug.searchParams.get('input_token')).toBe('tok');
    expect(debug.searchParams.get('access_token')).toBe('fb-app-id|fb-secret');
    expect(requests[0].authorization).toBeUndefined();
    expect(requests[1]).toEqual({ url: ME_URL, authorization: 'Bearer tok' });
  });

  test('fresh sign-up attempt → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = facebookGraph(DEBUG_TOKEN, ME);

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = facebookGraph(DEBUG_TOKEN, ME);

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test.each([true, 'true', 1])(
    'an email_verified field in a /me body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = facebookGraph(DEBUG_TOKEN, { ...ME, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'facebook',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = facebookGraph(DEBUG_TOKEN, ME);

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'facebook',
      providerUserId: '10158',
      email: 'ada@example.com',
    });
  });

  test.each([undefined, null, '', 42])('email %p → email-required rejection', async (email) => {
    const { store } = makeStore();
    const { fetchImpl } = facebookGraph(DEBUG_TOKEN, { ...ME, email });

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
  });

  test.each([
    ['a failed debug_token request', null, ME, ALL_ENABLED, 'tok'],
    ['a token issued to another app', { data: { ...DEBUG_TOKEN.data, app_id: 'other-app' } }, ME, ALL_ENABLED, 'tok'],
    ['an invalid token', { data: { ...DEBUG_TOKEN.data, is_valid: false } }, ME, ALL_ENABLED, 'tok'],
    ['a truthy non-boolean is_valid', { data: { ...DEBUG_TOKEN.data, is_valid: 'true' } }, ME, ALL_ENABLED, 'tok'],
    ['a token tied to no user', { data: { ...DEBUG_TOKEN.data, user_id: undefined } }, ME, ALL_ENABLED, 'tok'],
    ['a debug_token body with no data', {}, ME, ALL_ENABLED, 'tok'],
    ['a /me id that is not the token user', DEBUG_TOKEN, { ...ME, id: '99999' }, ALL_ENABLED, 'tok'],
    ['a /me body with no id', DEBUG_TOKEN, { ...ME, id: undefined }, ALL_ENABLED, 'tok'],
    ['a numeric /me id', DEBUG_TOKEN, { ...ME, id: 10158 }, ALL_ENABLED, 'tok'],
    ['a failed /me request', DEBUG_TOKEN, null, ALL_ENABLED, 'tok'],
    ['an array /me body', DEBUG_TOKEN, [ME], ALL_ENABLED, 'tok'],
    ['no app secret to inspect the token with', DEBUG_TOKEN, ME, { ...ALL_ENABLED, FACEBOOK_CLIENT_SECRET: '' }, 'tok'],
    ['a missing access token', DEBUG_TOKEN, ME, ALL_ENABLED, ''],
  ])('%s yields no identity', async (_label, debugBody, meBody, env, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = facebookGraph(debugBody, meBody);

    const { result, override } = await runGetUserInfo(
      'facebook',
      { accessToken },
      { store, env, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('an unproven token never reaches /me', async () => {
    const { store } = makeStore();
    const { fetchImpl, requests } = facebookGraph(
      { data: { ...DEBUG_TOKEN.data, app_id: 'other-app' } },
      ME
    );

    await runGetUserInfo('facebook', { accessToken: 'tok' }, { store, env: ALL_ENABLED, fetchImpl });

    expect(requests.map((r) => r.url.split('?')[0])).toEqual(['https://graph.facebook.com/debug_token']);
  });
});

/* ── getUserInfo: X / Twitter (OLO-9.32) ───────────────────────────────────────────────────── */

describe('getUserInfo — X / Twitter fail-closed link-first (OLO-9.32)', () => {
  const PROFILE_URL = 'https://api.x.com/2/users/me?user.fields=profile_image_url';
  const EMAIL_URL = 'https://api.x.com/2/users/me?user.fields=confirmed_email';
  /** The `/2/users/me?user.fields=profile_image_url` body for the person signing in. */
  const PROFILE = {
    data: {
      id: '2244994945',
      name: 'Ada Lovelace',
      username: 'ada',
      profile_image_url: 'https://pbs.example/ada_normal.jpg',
    },
  };
  /** The `/2/users/me?user.fields=confirmed_email` body for the same person. */
  const EMAIL = {
    data: { id: '2244994945', name: 'Ada Lovelace', username: 'ada', confirmed_email: 'ada@example.com' },
  };

  /**
   * Serve `profileBody` from the profile resource and `emailBody` from the email resource (a
   * failed response when null); record each request.
   */
  const xApi = (profileBody: unknown, emailBody: unknown) => {
    const requests: Array<{ url: string; authorization?: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      const body = url === PROFILE_URL ? profileBody : url === EMAIL_URL ? emailBody : null;
      return body === null ? { ok: false, json: async () => null } : { ok: true, json: async () => body };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the X user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = xApi(PROFILE, EMAIL);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '2244994945',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      image: 'https://pbs.example/ada_normal.jpg',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([
      { url: PROFILE_URL, authorization: 'Bearer tok' },
      { url: EMAIL_URL, authorization: 'Bearer tok' },
    ]);
  });

  test('known identity signs in with no email, taking the bound user email', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = xApi(PROFILE, null);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: '2244994945', email: OK_USER.email, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links with no email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = xApi(PROFILE, null);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'twitter',
      providerUserId: '2244994945',
    });
  });

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = xApi(PROFILE, EMAIL);

    const { override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'twitter',
      providerUserId: '2244994945',
      email: 'ada@example.com',
    });
  });

  test.each([
    ['a failed email request', null],
    ['no confirmed_email', { data: { ...EMAIL.data, confirmed_email: undefined } }],
    ['an empty confirmed_email', { data: { ...EMAIL.data, confirmed_email: '' } }],
    ['a non-string confirmed_email', { data: { ...EMAIL.data, confirmed_email: 42 } }],
    ['an email body about another user', { data: { ...EMAIL.data, id: '99999' } }],
    ['an email body with no data', {}],
  ])('fresh sign-in with %s → email-required rejection (no username fallback)', async (_label, emailBody) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = xApi(PROFILE, emailBody);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
    expect(AUTH_ERROR_CODES.EMAIL_REQUIRED).toBe('OAuthEmailRequired');
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('fresh sign-up attempt with an email → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = xApi(PROFILE, EMAIL);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = xApi(PROFILE, EMAIL);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test.each([true, 'true', 1])(
    'an email_verified field in an X body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = xApi(
        { data: { ...PROFILE.data, email_verified: emailVerified } },
        { data: { ...EMAIL.data, email_verified: emailVerified } }
      );

      const { result, override } = await runGetUserInfo(
        'twitter',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test('a missing display name falls back to the @username', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = xApi({ data: { ...PROFILE.data, name: '' } }, EMAIL);

    const { result } = await runGetUserInfo(
      'twitter',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ name: 'ada' });
  });

  test.each([
    ['a failed profile request', null, 'tok'],
    ['a profile body with no data', {}, 'tok'],
    ['a profile body with no id', { data: { ...PROFILE.data, id: undefined } }, 'tok'],
    ['a numeric id', { data: { ...PROFILE.data, id: 2244994945 } }, 'tok'],
    ['an array profile body', [PROFILE], 'tok'],
    ['a missing access token', PROFILE, ''],
  ])('%s yields no identity', async (_label, profileBody, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl, requests } = xApi(profileBody, EMAIL);

    const { result, override } = await runGetUserInfo(
      'twitter',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
    // Without an identity the email resource is never asked.
    expect(requests.map((r) => r.url)).not.toContain(EMAIL_URL);
  });
});

/* ── getUserInfo: Reddit (OLO-9.33) ────────────────────────────────────────────────────────── */

describe('getUserInfo — Reddit link-only (OLO-9.33)', () => {
  const ME_URL = 'https://oauth.reddit.com/api/v1/me';
  /** The `/api/v1/me` body for the person signing in. */
  const ME = {
    id: '1w72',
    name: 'ada_lovelace',
    icon_img: 'https://styles.redditmedia.example/avatar.png?width=256&amp;s=abc',
    has_verified_email: true,
    oauth_client_id: 'reddit-client-id',
  };

  /** Serve `meBody` from `/api/v1/me` (a failed response when null); record each request. */
  const redditApi = (meBody: unknown) => {
    const requests: Array<{ url: string; authorization?: string; userAgent?: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({
        url,
        authorization: init.headers.Authorization,
        userAgent: init.headers['User-Agent'],
      });
      const body = url === ME_URL ? meBody : null;
      return body === null ? { ok: false, json: async () => null } : { ok: true, json: async () => body };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the Reddit account id, with the bound user email', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = redditApi(ME);

    const { result, override } = await runGetUserInfo(
      'reddit',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: '1w72',
      email: OK_USER.email,
      emailVerified: false,
      name: 'ada_lovelace',
      // The HTML-escaped query string is dropped, as Better Auth's helper does.
      image: 'https://styles.redditmedia.example/avatar.png',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    // Reddit rejects requests without a User-Agent; the shared fetch helper always sends one.
    expect(requests).toEqual([{ url: ME_URL, authorization: 'Bearer tok', userAgent: 'apiome' }]);
  });

  test('explicit link intent links with no email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = redditApi(ME);

    const { result, override } = await runGetUserInfo(
      'reddit',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'reddit',
      providerUserId: '1w72',
    });
    expect(calls.linkIdentity[0].identity.email ?? null).toBeNull();
  });

  test.each([
    ['has_verified_email true', ME],
    ['has_verified_email false', { ...ME, has_verified_email: false }],
    ['an email field in the body', { ...ME, email: 'ada@example.com', email_verified: true }],
  ])('fresh sign-in with %s → email-required rejection (no email is ever read)', async (_label, meBody) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = redditApi(meBody);

    const { result, override } = await runGetUserInfo(
      'reddit',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
    expect(AUTH_ERROR_CODES.EMAIL_REQUIRED).toBe('OAuthEmailRequired');
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('a missing avatar leaves the image out', async () => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = redditApi({ ...ME, icon_img: '' });

    const { result } = await runGetUserInfo(
      'reddit',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: '1w72', name: 'ada_lovelace' });
    expect(result?.image ?? null).toBeNull();
  });

  test.each([
    ['a failed request', null, 'tok'],
    ['a body with no id', { ...ME, id: undefined }, 'tok'],
    ['an empty id', { ...ME, id: '  ' }, 'tok'],
    ['a numeric id', { ...ME, id: 1234 }, 'tok'],
    ['an array body', [ME], 'tok'],
    ['a missing access token', ME, ''],
  ])('%s yields no identity', async (_label, meBody, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = redditApi(meBody);

    const { result, override } = await runGetUserInfo(
      'reddit',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

/* ── getUserInfo: Spotify (OLO-9.34) ───────────────────────────────────────────────────────── */

describe('getUserInfo — Spotify fail-closed link-first (OLO-9.34)', () => {
  const ME_URL = 'https://api.spotify.com/v1/me';
  /** The `/v1/me` body for the person signing in. */
  const ME = {
    id: 'ada.lovelace',
    display_name: 'Ada Lovelace',
    email: 'ada@example.com',
    images: [
      { url: 'https://i.scdn.example/ada-640.jpg', height: 640, width: 640 },
      { url: 'https://i.scdn.example/ada-64.jpg', height: 64, width: 64 },
    ],
    country: 'GB',
    product: 'premium',
  };

  /** Serve `meBody` from `/v1/me` (a failed response when null); record each request. */
  const spotifyApi = (meBody: unknown) => {
    const requests: Array<{ url: string; authorization?: string }> = [];
    const fetchImpl: FetchLike = async (url, init) => {
      requests.push({ url, authorization: init.headers.Authorization });
      const body = url === ME_URL ? meBody : null;
      return body === null ? { ok: false, json: async () => null } : { ok: true, json: async () => body };
    };
    return { fetchImpl, requests };
  };

  test('known identity signs in, keyed on the Spotify user id (subsequent sign-in)', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl, requests } = spotifyApi(ME);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({
      id: 'ada.lovelace',
      email: 'ada@example.com',
      emailVerified: false,
      name: 'Ada Lovelace',
      // The first image, as Better Auth's helper reads it.
      image: 'https://i.scdn.example/ada-640.jpg',
    });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(requests).toEqual([{ url: ME_URL, authorization: 'Bearer tok' }]);
  });

  test('known identity signs in with no email, taking the bound user email', async () => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = spotifyApi({ ...ME, email: undefined });

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(override).toBeNull();
    expect(result).toMatchObject({ id: 'ada.lovelace', email: OK_USER.email, emailVerified: false });
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
  });

  test('explicit link intent links despite the unverified email', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = spotifyApi(ME);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl, resolveLinkToUserId: async () => 'session-user' }
    );

    expect(result).toBeNull();
    expect(override).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity[0].userId).toBe('session-user');
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'spotify',
      providerUserId: 'ada.lovelace',
      email: 'ada@example.com',
    });
  });

  test('fresh sign-up attempt with an email → rejected with the structured unverified code', async () => {
    const { store, calls } = makeStore();
    const { fetchImpl } = spotifyApi(ME);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('email matching an existing account never auto-links', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = spotifyApi(ME);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test.each([true, 'true', 1])(
    'an email_verified field in a Spotify body (%p) is dropped, never trusted',
    async (emailVerified) => {
      const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
      const { fetchImpl } = spotifyApi({ ...ME, email_verified: emailVerified });

      const { result, override } = await runGetUserInfo(
        'spotify',
        { accessToken: 'tok' },
        { store, env: ALL_ENABLED, fetchImpl }
      );

      expect(result).toBeNull();
      expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
      expect(calls.linkIdentity).toHaveLength(0);
      expect(calls.createPendingSignup).toHaveLength(0);
    }
  );

  test.each([
    ['no email field', { ...ME, email: undefined }],
    ['an empty email', { ...ME, email: '' }],
    ['a non-string email', { ...ME, email: 42 }],
  ])('fresh sign-in with %s → email-required rejection', async (_label, meBody) => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const { fetchImpl } = spotifyApi(meBody);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).toBe(`/login?error=${AUTH_ERROR_CODES.EMAIL_REQUIRED}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test.each([
    ['no images', { ...ME, images: [] }],
    ['a missing images field', { ...ME, images: undefined }],
    ['an image with no url', { ...ME, images: [{ height: 64 }] }],
    ['a null image', { ...ME, images: [null] }],
  ])('%s leaves the image out', async (_label, meBody) => {
    const { store } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
    });
    const { fetchImpl } = spotifyApi(meBody);

    const { result } = await runGetUserInfo(
      'spotify',
      { accessToken: 'tok' },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toMatchObject({ id: 'ada.lovelace', name: 'Ada Lovelace' });
    expect(result?.image ?? null).toBeNull();
  });

  test.each([
    ['a failed request', null, 'tok'],
    ['a body with no id', { ...ME, id: undefined }, 'tok'],
    ['an empty id', { ...ME, id: '  ' }, 'tok'],
    ['a numeric id', { ...ME, id: 1234 }, 'tok'],
    ['an array body', [ME], 'tok'],
    ['a missing access token', ME, ''],
  ])('%s yields no identity', async (_label, meBody, accessToken) => {
    const { store, calls } = makeStore({
      identityUserId: OK_USER.id,
      usersById: { [OK_USER.id]: OK_USER },
      usersByEmail: { 'ada@example.com': OK_USER },
    });
    const { fetchImpl } = spotifyApi(meBody);

    const { result, override } = await runGetUserInfo(
      'spotify',
      { accessToken },
      { store, env: ALL_ENABLED, fetchImpl }
    );

    expect(result).toBeNull();
    expect(override).not.toBeNull();
    expect(calls.recordUserLogin).toEqual([]);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });
});

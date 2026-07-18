/**
 * NextAuth provider construction tests (OLO-2.3, #4195).
 *
 * `configuredOAuthProviders` maps enabled provider-registry entries to NextAuth provider
 * configs for the `[...nextauth]` route. These tests pin that the registered provider ids
 * track the registry's enabled set exactly (the "disabling via env removes the sign-in
 * route" half of the acceptance criteria) and that each factory receives its env config.
 */
import { configuredOAuthProviders } from '../lib/auth/nextauth-oauth-providers';
import { enabledProviderIds } from '../lib/auth/provider-registry';
import {
  GITHUB_OAUTH_SCOPE,
  GITLAB_OAUTH_SCOPE,
  githubUserinfoRequest,
  gitlabUserinfoRequest,
} from '../lib/auth/verified-email';

/** The provider-config fields these tests inspect (next-auth's Provider type hides them). */
interface InspectableProvider {
  id: string;
  name?: string;
  checks?: string[];
  clientId?: string;
  clientSecret?: string;
  options?: {
    clientId?: string;
    clientSecret?: string;
    authorization?: { params?: { scope?: string } };
    userinfo?: { url?: string; request?: unknown };
  };
}

const ALL_ENABLED_ENV = {
  GITHUB_ID: 'gh-id',
  GITHUB_SECRET: 'gh-secret',
  GITLAB_CLIENT_ID: 'gl-id',
  GITLAB_CLIENT_SECRET: 'gl-secret',
  AZURE_AD_CLIENT_ID: 'az-id',
  AZURE_AD_CLIENT_SECRET: 'az-secret',
};

describe('configuredOAuthProviders', () => {
  it('registers exactly the registry-enabled providers, in registry order', () => {
    const providers = configuredOAuthProviders(ALL_ENABLED_ENV);
    expect(providers.map((p) => p.id)).toEqual(['github', 'gitlab', 'azure']);
    expect(providers.map((p) => p.id)).toEqual(enabledProviderIds(ALL_ENABLED_ENV));
  });

  it('registers no providers when no env is configured', () => {
    expect(configuredOAuthProviders({})).toEqual([]);
  });

  it.each([
    ['github', { GITHUB_ID: 'gh-id', GITHUB_SECRET: 'gh-secret' }],
    ['gitlab', { GITLAB_CLIENT_ID: 'gl-id', GITLAB_CLIENT_SECRET: 'gl-secret' }],
    ['azure', { AZURE_AD_CLIENT_ID: 'az-id', AZURE_AD_CLIENT_SECRET: 'az-secret' }],
  ])('registers only %s when only its env pair is set', (id, env) => {
    expect(configuredOAuthProviders(env).map((p) => p.id)).toEqual([id]);
  });

  it('drops a provider when its env is unset — no code changes needed', () => {
    const withoutGithub = { ...ALL_ENABLED_ENV, GITHUB_ID: '' };
    expect(configuredOAuthProviders(withoutGithub).map((p) => p.id)).toEqual(['gitlab', 'azure']);
  });

  it('passes each provider its client id/secret from env', () => {
    const providers = configuredOAuthProviders(ALL_ENABLED_ENV) as unknown as InspectableProvider[];
    const byId = new Map(providers.map((p) => [p.id, p]));

    // Built-in factories (github/gitlab) carry user config under `options`
    // (NextAuth merges it at init); the hand-rolled azure config is flat.
    expect(byId.get('github').options).toMatchObject({ clientId: 'gh-id', clientSecret: 'gh-secret' });
    expect(byId.get('gitlab').options).toMatchObject({ clientId: 'gl-id', clientSecret: 'gl-secret' });
    expect(byId.get('azure').clientId).toBe('az-id');
    expect(byId.get('azure').clientSecret).toBe('az-secret');
  });

  it('pins the verified-email parity scopes and userinfo hooks (OLO-2.5, #4197)', () => {
    const providers = configuredOAuthProviders(ALL_ENABLED_ENV) as unknown as InspectableProvider[];
    const byId = new Map(providers.map((p) => [p.id, p]));

    const github = byId.get('github')!.options!;
    expect(github.authorization?.params?.scope).toBe(GITHUB_OAUTH_SCOPE);
    expect(github.userinfo?.url).toBe('https://api.github.com/user');
    expect(github.userinfo?.request).toBe(githubUserinfoRequest);

    const gitlab = byId.get('gitlab')!.options!;
    expect(gitlab.authorization?.params?.scope).toBe(GITLAB_OAUTH_SCOPE);
    expect(gitlab.userinfo?.url).toBe('https://gitlab.com/api/v4/user');
    expect(gitlab.userinfo?.request).toBe(gitlabUserinfoRequest);
  });

  it('points github/gitlab endpoints at the mock base URLs when overridden (OLO-7.4)', () => {
    const providers = configuredOAuthProviders({
      ...ALL_ENABLED_ENV,
      GITHUB_OAUTH_BASE_URL: 'http://localhost:8091/github/',
      GITHUB_API_BASE_URL: 'http://localhost:8091/github/api',
      GITLAB_BASE_URL: 'http://localhost:8091/gitlab',
    }) as unknown as InspectableProvider[];
    const byId = new Map(providers.map((p) => [p.id, p]));

    const github = byId.get('github')!.options! as Record<string, any>;
    expect(github.authorization.url).toBe('http://localhost:8091/github/login/oauth/authorize');
    expect(github.authorization.params.scope).toBe(GITHUB_OAUTH_SCOPE);
    expect(github.token).toBe('http://localhost:8091/github/login/oauth/access_token');
    expect(github.userinfo.url).toBe('http://localhost:8091/github/api/user');

    const gitlab = byId.get('gitlab')!.options! as Record<string, any>;
    expect(gitlab.authorization.url).toBe('http://localhost:8091/gitlab/oauth/authorize');
    expect(gitlab.token).toBe('http://localhost:8091/gitlab/oauth/token');
    expect(gitlab.userinfo.url).toBe('http://localhost:8091/gitlab/api/v4/user');
  });

  it('keeps the real provider hosts when no override env is set', () => {
    const providers = configuredOAuthProviders(ALL_ENABLED_ENV) as unknown as InspectableProvider[];
    const byId = new Map(providers.map((p) => [p.id, p]));

    const github = byId.get('github')!.options! as Record<string, any>;
    expect(github.authorization.url).toBe('https://github.com/login/oauth/authorize');
    expect(github.token).toBe('https://github.com/login/oauth/access_token');

    const gitlab = byId.get('gitlab')!.options! as Record<string, any>;
    expect(gitlab.authorization.url).toBe('https://gitlab.com/oauth/authorize');
    expect(gitlab.token).toBe('https://gitlab.com/oauth/token');
  });

  it('builds azure via the OLO-2.1 Entra provider (id azure, OIDC checks intact)', () => {
    const [azure] = configuredOAuthProviders({
      AZURE_AD_CLIENT_ID: 'az-id',
      AZURE_AD_CLIENT_SECRET: 'az-secret',
    }) as unknown as InspectableProvider[];

    expect(azure.id).toBe('azure');
    expect(azure.name).toBe('Microsoft Entra ID');
    expect(azure.checks).toEqual(['pkce', 'state', 'nonce']);
  });
});

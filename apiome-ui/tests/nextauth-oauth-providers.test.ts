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

/** The provider-config fields these tests inspect (next-auth's Provider type hides them). */
interface InspectableProvider {
  id: string;
  name?: string;
  checks?: string[];
  clientId?: string;
  clientSecret?: string;
  options?: { clientId?: string; clientSecret?: string };
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

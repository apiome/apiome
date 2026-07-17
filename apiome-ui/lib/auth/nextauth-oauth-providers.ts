/**
 * NextAuth provider construction from the provider registry (OLO-2.3, #4195).
 *
 * Maps each *enabled* registry entry (`provider-registry.ts`) to its NextAuth provider config,
 * so the `[...nextauth]` route registers exactly the providers this deployment enables via env.
 * Unsetting a provider's env vars therefore removes its sign-in route entirely — attempts fall
 * to NextAuth's unknown-provider handling instead of redirecting with an undefined client id
 * (the same guarantee `entraIdProviderIfConfigured` gave azure in OLO-2.1, now for all).
 *
 * Server-only: imports next-auth provider factories. Client code wanting provider metadata
 * should import `provider-registry.ts` (data) or `provider-brand.tsx` (icons) instead.
 */
import type { Provider } from 'next-auth/providers/index';
import GithubProvider from 'next-auth/providers/github';
import GitlabProvider from 'next-auth/providers/gitlab';
import { entraIdProvider } from './entra-provider';
import { enabledProviders, readEnvString } from './provider-registry';
import {
  GITHUB_OAUTH_SCOPE,
  GITLAB_OAUTH_SCOPE,
  githubUserinfoRequest,
  gitlabUserinfoRequest,
} from './verified-email';

/**
 * NextAuth provider factory per registry id. Adding a provider to the registry requires a
 * matching entry here (a registry entry without a factory is skipped and reported at startup
 * rather than crashing sign-in for the whole deployment).
 */
const PROVIDER_FACTORIES: Record<
  string,
  (env: Record<string, string | undefined>) => Provider
> = {
  // github/gitlab: scopes pinned and userinfo exchanges overridden for the verified-email
  // parity pass (OLO-2.5, #4197) — the raw profile reaching the signIn callback always
  // carries a normalized `email_verified`, and GitHub resolves a verified primary address
  // even when the public profile email is null. See `verified-email.ts`.
  github: (env) =>
    GithubProvider({
      clientId: readEnvString(env, 'GITHUB_ID') ?? '',
      clientSecret: readEnvString(env, 'GITHUB_SECRET') ?? '',
      authorization: { params: { scope: GITHUB_OAUTH_SCOPE } },
      userinfo: {
        url: 'https://api.github.com/user',
        request: githubUserinfoRequest,
      },
    }),
  gitlab: (env) =>
    GitlabProvider({
      clientId: readEnvString(env, 'GITLAB_CLIENT_ID') ?? '',
      clientSecret: readEnvString(env, 'GITLAB_CLIENT_SECRET') ?? '',
      authorization: { params: { scope: GITLAB_OAUTH_SCOPE } },
      userinfo: {
        url: 'https://gitlab.com/api/v4/user',
        request: gitlabUserinfoRequest,
      },
    }),
  azure: (env) => entraIdProvider(env),
};

/**
 * Build the NextAuth OAuth provider list for this deployment: one provider config per enabled
 * registry entry, in registry display order.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns Provider configs to spread into `authOptions.providers` (before the credentials
 *   provider, which is not part of the OAuth registry).
 */
export function configuredOAuthProviders(
  env: Record<string, string | undefined> = process.env
): Provider[] {
  const providers: Provider[] = [];
  for (const descriptor of enabledProviders(env)) {
    const factory = PROVIDER_FACTORIES[descriptor.id];
    if (!factory) {
      console.error(
        `[provider-registry] Provider '${descriptor.id}' is enabled by env but has no NextAuth factory; skipping.`
      );
      continue;
    }
    providers.push(factory(env));
  }
  return providers;
}

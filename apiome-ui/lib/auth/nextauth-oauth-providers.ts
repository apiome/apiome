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
import { googleProvider } from './google-provider';
import { enabledProviders, readEnvString } from './provider-registry';
import { resolveProviderEnv, type EnvMap } from './provider-config-resolver';
import {
  GITHUB_OAUTH_SCOPE,
  GITLAB_OAUTH_SCOPE,
  githubApiBaseUrl,
  githubUserinfoRequest,
  gitlabBaseUrl,
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
  //
  // Endpoint base URLs are overridable via env (`GITHUB_OAUTH_BASE_URL`,
  // `GITHUB_API_BASE_URL`, `GITLAB_BASE_URL`) so the e2e journey suite (OLO-7.4) can point
  // sign-in at a local mock provider. Unset (the production default) they resolve to the
  // real provider hosts — see `githubOauthBaseUrl`/`githubApiBaseUrl`/`gitlabBaseUrl`.
  github: (env) => {
    const oauthBase = githubOauthBaseUrl(env);
    return GithubProvider({
      clientId: readEnvString(env, 'GITHUB_ID') ?? '',
      clientSecret: readEnvString(env, 'GITHUB_SECRET') ?? '',
      // CSRF `state` is enforced explicitly rather than left to NextAuth's default so a future
      // refactor or dependency bump cannot silently drop it (OLO-7.3 regression insurance).
      // GitHub OAuth Apps do not support PKCE; this is a confidential client that authenticates
      // the code exchange with GITHUB_SECRET, so state + client_secret is the correct posture.
      // (GitLab keeps its built-in `['pkce','state']` and Entra sets `['pkce','state','nonce']`.)
      checks: ['state'],
      authorization: {
        url: `${oauthBase}/login/oauth/authorize`,
        params: { scope: GITHUB_OAUTH_SCOPE },
      },
      token: `${oauthBase}/login/oauth/access_token`,
      userinfo: {
        url: `${githubApiBaseUrl(env)}/user`,
        request: githubUserinfoRequest,
      },
    });
  },
  gitlab: (env) => {
    const base = gitlabBaseUrl(env);
    return GitlabProvider({
      clientId: readEnvString(env, 'GITLAB_CLIENT_ID') ?? '',
      clientSecret: readEnvString(env, 'GITLAB_CLIENT_SECRET') ?? '',
      authorization: {
        url: `${base}/oauth/authorize`,
        params: { scope: GITLAB_OAUTH_SCOPE },
      },
      token: `${base}/oauth/token`,
      userinfo: {
        url: `${base}/api/v4/user`,
        request: gitlabUserinfoRequest,
      },
    });
  },
  azure: (env) => entraIdProvider(env),
  // google: built-in next-auth GoogleProvider wrapped for optional Workspace-domain restriction
  // (the `hd` authorization param + id-token `hd`-claim gate). See `google-provider.ts` (OLO-9.2).
  google: (env) => googleProvider(env),
};

/**
 * Base URL of GitHub's OAuth web endpoints (`/login/oauth/authorize`, `…/access_token`).
 * Overridable via `GITHUB_OAUTH_BASE_URL` for the mocked-provider e2e journey (OLO-7.4);
 * defaults to the real host.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The base URL without a trailing slash.
 */
export function githubOauthBaseUrl(
  env: Record<string, string | undefined> = process.env
): string {
  return stripTrailingSlash(readEnvString(env, 'GITHUB_OAUTH_BASE_URL') ?? 'https://github.com');
}

/** Remove a single trailing slash so `${base}/path` never doubles the separator. */
function stripTrailingSlash(url: string): string {
  return url.endsWith('/') ? url.slice(0, -1) : url;
}

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

/**
 * Build the OAuth provider list from the **DB-over-env merged config** (OLO-8.6, #4972).
 *
 * This is the per-request variant of {@link configuredOAuthProviders}: it first resolves the merged
 * env via `resolveProviderEnv` (8.5) — DB value where an operator has set one, else the process env —
 * then maps the enabled set to NextAuth provider configs. Called on every sign-in request by the
 * `[...nextauth]` handler so a DB toggle changes the enabled provider set on the next request (within
 * the resolver's TTL cache) with no redeploy.
 *
 * Never throws on DB trouble: `resolveProviderEnv` degrades to the base env when the resolved endpoint
 * is unset/unreachable/errors, so a DB outage falls back to env config rather than breaking sign-in.
 *
 * @param baseEnv Base environment to merge the DB config over (injectable for tests; defaults to
 *   `process.env`).
 * @param now Current epoch ms, forwarded to the resolver's TTL cache (injectable for tests).
 * @returns Provider configs to spread into `authOptions.providers`, reflecting the merged config.
 */
export async function resolveOAuthProviders(
  baseEnv: EnvMap = process.env,
  now?: number
): Promise<Provider[]> {
  const mergedEnv =
    now === undefined ? await resolveProviderEnv(baseEnv) : await resolveProviderEnv(baseEnv, now);
  return configuredOAuthProviders(mergedEnv);
}

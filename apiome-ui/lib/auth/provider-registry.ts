/**
 * OAuth provider registry & deploy config (OLO-2.3, #4195).
 *
 * The single surface describing which sign-in providers exist and which are enabled in this
 * deployment. A provider is *enabled* purely from env config (its required env vars are set and
 * non-blank) — no code changes are needed to add or remove a provider from a deployment.
 *
 * Consumers:
 *   - the NextAuth route registers exactly the enabled providers
 *     (`nextauth-oauth-providers.ts` → `[...nextauth]/route.ts`);
 *   - the login page renders one SSO button per enabled provider (OLO-3.1, `login/page.tsx`);
 *   - the linked-accounts panel offers exactly the enabled providers for linking (OLO-2.4);
 *   - the signup-intent and link routes refuse providers that are not enabled;
 *   - setup docs list each provider's env contract (OLO-7.2).
 *
 * Adding a provider later (Okta #241, AWS #68, Google) means: one entry here, one NextAuth
 * factory in `nextauth-oauth-providers.ts`, one brand icon in
 * `src/app/components/auth/provider-brand.tsx` — no archaeology across surfaces.
 *
 * This module is intentionally free of React and next-auth imports so both server code
 * (routes, server components) and client components can import it.
 */

/**
 * Lifecycle of a registry entry:
 *   - `available`: implemented end-to-end; enabled whenever its env vars are configured.
 *   - `coming-soon`: advertised on the linked-accounts panel as a roadmap teaser, but never
 *     enabled regardless of env (no NextAuth factory exists for it yet).
 */
export type ProviderStatus = 'available' | 'coming-soon';

/** A sign-in provider this codebase knows about (enabled or not). */
export interface ProviderDescriptor {
  /**
   * The provider slug — NextAuth provider id AND the value stored in
   * `external_auth_providers.provider` (the OLO-2.2 vocabulary). Never rename an id:
   * persisted identities and the account-resolution gates match on it.
   */
  id: string;
  /** Human-readable name used on buttons and cards ("Continue with {label}"). */
  label: string;
  /** Implementation status — see {@link ProviderStatus}. */
  status: ProviderStatus;
  /**
   * Env vars that must all be set and non-blank for the provider to be enabled.
   * Empty for `coming-soon` entries (nothing can enable them).
   */
  requiredEnvKeys: readonly string[];
}

/**
 * Serializable projection of a descriptor plus its enabled state, safe to pass from a server
 * component to a client component (React component props must be serializable, so the brand
 * icon is resolved client-side from the id — see `provider-brand.tsx`).
 */
export interface ProviderSummary {
  id: string;
  label: string;
  status: ProviderStatus;
  /** True when this deployment's env enables the provider. */
  enabled: boolean;
}

/**
 * Every provider this codebase knows about, in display order.
 *
 * `azure` is Microsoft Entra ID (OLO-2.1) — its env contract is shared with
 * `entra-provider.ts`, which delegates its config check here so the two can never drift.
 */
export const PROVIDER_REGISTRY: readonly ProviderDescriptor[] = [
  {
    id: 'github',
    label: 'GitHub',
    status: 'available',
    requiredEnvKeys: ['GITHUB_ID', 'GITHUB_SECRET'],
  },
  {
    id: 'gitlab',
    label: 'GitLab',
    status: 'available',
    requiredEnvKeys: ['GITLAB_CLIENT_ID', 'GITLAB_CLIENT_SECRET'],
  },
  {
    id: 'azure',
    label: 'Microsoft',
    status: 'available',
    requiredEnvKeys: ['AZURE_AD_CLIENT_ID', 'AZURE_AD_CLIENT_SECRET'],
  },
  {
    id: 'google',
    label: 'Google / GCP',
    status: 'coming-soon',
    requiredEnvKeys: [],
  },
  {
    id: 'aws',
    label: 'AWS',
    status: 'coming-soon',
    requiredEnvKeys: [],
  },
];

/**
 * Read a trimmed env string, or null when unset/blank.
 *
 * Blank ("" or whitespace) counts as unset so a commented-template value like
 * `GITHUB_ID=` does not accidentally enable a provider.
 *
 * @param env Environment map to read.
 * @param key Env var name.
 * @returns The trimmed value, or null when unset or blank.
 */
export function readEnvString(
  env: Record<string, string | undefined>,
  key: string
): string | null {
  const raw = env[key];
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Look up a registry entry by provider id.
 *
 * @param id Provider slug (e.g. `github`).
 * @returns The descriptor, or undefined for ids the registry does not know.
 */
export function getProviderDescriptor(id: string): ProviderDescriptor | undefined {
  return PROVIDER_REGISTRY.find((provider) => provider.id === id);
}

/**
 * Whether this deployment enables a provider.
 *
 * True only when the provider exists in the registry, is `available`, and every required env
 * var is set and non-blank. Unknown ids and `coming-soon` entries are never enabled.
 *
 * @param id Provider slug.
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns True when the provider should appear on every sign-in/link surface.
 */
export function isProviderEnabled(
  id: string,
  env: Record<string, string | undefined> = process.env
): boolean {
  const descriptor = getProviderDescriptor(id);
  if (!descriptor || descriptor.status !== 'available') return false;
  return descriptor.requiredEnvKeys.every((key) => readEnvString(env, key) !== null);
}

/**
 * The enabled providers, in display order.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns Descriptors of every enabled provider.
 */
export function enabledProviders(
  env: Record<string, string | undefined> = process.env
): ProviderDescriptor[] {
  return PROVIDER_REGISTRY.filter((provider) => isProviderEnabled(provider.id, env));
}

/**
 * Ids of the enabled providers, in display order.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns Provider slugs (e.g. `['github', 'gitlab']`).
 */
export function enabledProviderIds(
  env: Record<string, string | undefined> = process.env
): string[] {
  return enabledProviders(env).map((provider) => provider.id);
}

/**
 * Serializable summaries of every registry entry with its enabled state — the shape server
 * components pass to client components (login page, linked-accounts panel).
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns One summary per registry entry, in display order.
 */
export function providerSummaries(
  env: Record<string, string | undefined> = process.env
): ProviderSummary[] {
  return PROVIDER_REGISTRY.map((provider) => ({
    id: provider.id,
    label: provider.label,
    status: provider.status,
    enabled: isProviderEnabled(provider.id, env),
  }));
}

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
 *   - setup docs list each provider's env contract (OLO-7.2, `docs/AUTH_PROVIDER_SETUP.md`);
 *   - boot-time validation (`validateProviderEnv`, called from `src/instrumentation.ts`)
 *     fails startup — or warns, per `AUTH_PROVIDER_VALIDATION` — when a provider's env is
 *     only partially configured (OLO-7.2).
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

/* ── Boot-time env validation (OLO-7.2, #4224) ──────────────────────────────────────────── */

/**
 * How boot-time validation reacts to a partially-configured provider:
 *   - `strict` (default): the server refuses to start — misconfiguration fails loud at boot,
 *     not silently at first login.
 *   - `warn`: the issue is logged and the provider stays cleanly disabled (a provider with
 *     any required env var missing is never enabled — see {@link isProviderEnabled}).
 */
export type ProviderValidationMode = 'strict' | 'warn';

/** Env var selecting the {@link ProviderValidationMode}. */
export const PROVIDER_VALIDATION_ENV_KEY = 'AUTH_PROVIDER_VALIDATION';

/** Setup guide referenced by every validation message. */
const SETUP_DOC = 'apiome-ui/docs/AUTH_PROVIDER_SETUP.md';

/** A provider whose env is partially configured (some, but not all, required vars set). */
export interface ProviderEnvIssue {
  /** Provider slug (e.g. `github`). */
  providerId: string;
  /** Human-readable provider name (e.g. `GitHub`). */
  label: string;
  /** Required env vars that are set and non-blank. */
  presentKeys: string[];
  /** Required env vars that are unset or blank. */
  missingKeys: string[];
  /** Actionable, operator-facing description of the problem and both ways to fix it. */
  message: string;
}

/**
 * Find every partially-configured provider.
 *
 * A provider with all required vars set is enabled; one with none set is cleanly disabled —
 * both are valid deployments. Some-but-not-all is always operator error (a typo'd var name,
 * a secret that never landed), so each such provider yields one issue.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns One issue per partially-configured provider, in registry display order.
 */
export function providerEnvIssues(
  env: Record<string, string | undefined> = process.env
): ProviderEnvIssue[] {
  const issues: ProviderEnvIssue[] = [];
  for (const { id, label, status, requiredEnvKeys } of PROVIDER_REGISTRY) {
    if (status !== 'available' || requiredEnvKeys.length === 0) continue;
    const presentKeys = requiredEnvKeys.filter((key) => readEnvString(env, key) !== null);
    const missingKeys = requiredEnvKeys.filter((key) => readEnvString(env, key) === null);
    if (presentKeys.length === 0 || missingKeys.length === 0) continue;
    issues.push({
      providerId: id,
      label,
      presentKeys,
      missingKeys,
      message:
        `Sign-in provider '${label}' (${id}) is partially configured: ` +
        `${missingKeys.join(', ')} ${missingKeys.length === 1 ? 'is' : 'are'} unset or blank ` +
        `while ${presentKeys.join(', ')} ${presentKeys.length === 1 ? 'is' : 'are'} set. ` +
        `Set all of ${requiredEnvKeys.join(', ')} to enable ${label} sign-in, ` +
        `or unset all of them to disable it. Setup guide: ${SETUP_DOC}`,
    });
  }
  return issues;
}

/**
 * Resolve the validation mode from `AUTH_PROVIDER_VALIDATION`.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns `strict` when unset (the default), otherwise the configured mode.
 * @throws Error when the var is set to anything other than `strict` or `warn`, so a typo'd
 *   mode cannot silently weaken (or accidentally re-enable) validation.
 */
export function providerValidationMode(
  env: Record<string, string | undefined> = process.env
): ProviderValidationMode {
  const raw = readEnvString(env, PROVIDER_VALIDATION_ENV_KEY);
  if (raw === null) return 'strict';
  const mode = raw.toLowerCase();
  if (mode === 'strict' || mode === 'warn') return mode;
  throw new Error(
    `${PROVIDER_VALIDATION_ENV_KEY}='${raw}' is not a valid validation mode; ` +
      `use 'strict' (fail startup on partial provider config, the default) or ` +
      `'warn' (log and leave the provider disabled). Setup guide: ${SETUP_DOC}`
  );
}

/**
 * Validate provider env config at boot (OLO-7.2 acceptance: misconfiguration fails loud at
 * startup, not at first login). Called from `src/instrumentation.ts` when the Node.js server
 * starts; also safe to call from tests or scripts.
 *
 * In `strict` mode (default) any partially-configured provider aborts startup with one
 * message per issue. In `warn` mode the issues are logged via `console.warn` and the
 * offending providers stay cleanly disabled.
 *
 * @param env Environment to read (injectable for tests; defaults to `process.env`).
 * @returns The issues found (empty when the deployment's provider env is coherent).
 * @throws Error in `strict` mode when any provider is partially configured, or for an
 *   invalid `AUTH_PROVIDER_VALIDATION` value in any mode.
 */
export function validateProviderEnv(
  env: Record<string, string | undefined> = process.env
): ProviderEnvIssue[] {
  const mode = providerValidationMode(env);
  const issues = providerEnvIssues(env);
  if (issues.length === 0) return issues;
  if (mode === 'strict') {
    throw new Error(
      `Refusing to start: ${issues.length} sign-in provider(s) partially configured.\n` +
        issues.map((issue) => `  - ${issue.message}`).join('\n') +
        `\nSet ${PROVIDER_VALIDATION_ENV_KEY}=warn to log instead and leave the provider(s) disabled.`
    );
  }
  for (const issue of issues) {
    console.warn(`[provider-registry] ${issue.message} (provider disabled)`);
  }
  return issues;
}

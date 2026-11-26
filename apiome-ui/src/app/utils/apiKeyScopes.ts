/**
 * Workspace API key scopes (CTG-2.3 / #4473; `usage:ingest` RDG-1.2 / #5760; `registry:read` /
 * `registry:write` CDG-4.3 / #5975; `pact:read` / `pact:publish` / `pact:verify` PFX-4.2 / #6939).
 *
 * `*` = full access (default). CI tokens use `diff:read` and/or `lint:read`. A usage source (an
 * OpenTelemetry Collector, a log shipper) uses `usage:ingest`, which admits only the usage ingest
 * route. A Kafka serializer uses `registry:read` (and `registry:write` to register schemas), which
 * admit only the Confluent-compatible schema registry at `/registry/schema/{tenant}`. Pact tooling
 * uses `pact:read` (can-i-deploy, fetching pacts), `pact:publish` (publishing pacts, recording
 * deployments) and `pact:verify` (publishing verification results), which admit only the Pact
 * Broker at `/v1/tenants/{tenant}/pact-broker` and the hosted verifier.
 */

export const API_KEY_SCOPE_FULL = '*';
export const API_KEY_SCOPE_DIFF_READ = 'diff:read';
export const API_KEY_SCOPE_LINT_READ = 'lint:read';
export const API_KEY_SCOPE_USAGE_INGEST = 'usage:ingest';
export const API_KEY_SCOPE_REGISTRY_READ = 'registry:read';
export const API_KEY_SCOPE_REGISTRY_WRITE = 'registry:write';
export const API_KEY_SCOPE_PACT_READ = 'pact:read';
export const API_KEY_SCOPE_PACT_PUBLISH = 'pact:publish';
export const API_KEY_SCOPE_PACT_VERIFY = 'pact:verify';

export const API_KEY_SCOPE_VOCAB = new Set([
  API_KEY_SCOPE_FULL,
  API_KEY_SCOPE_DIFF_READ,
  API_KEY_SCOPE_LINT_READ,
  API_KEY_SCOPE_USAGE_INGEST,
  API_KEY_SCOPE_REGISTRY_READ,
  API_KEY_SCOPE_REGISTRY_WRITE,
  API_KEY_SCOPE_PACT_READ,
  API_KEY_SCOPE_PACT_PUBLISH,
  API_KEY_SCOPE_PACT_VERIFY,
]);

/** Preset ids for the Control Panel create-key scope picker. */
export type ApiKeyScopePreset =
  | 'full'
  | 'diff'
  | 'lint'
  | 'ci_both'
  | 'usage'
  | 'registry_read'
  | 'registry_client'
  | 'pact_read'
  | 'pact_publish'
  | 'pact_verify';

export const API_KEY_SCOPE_PRESETS: Record<ApiKeyScopePreset, string[]> = {
  full: [API_KEY_SCOPE_FULL],
  diff: [API_KEY_SCOPE_DIFF_READ],
  lint: [API_KEY_SCOPE_LINT_READ],
  ci_both: [API_KEY_SCOPE_DIFF_READ, API_KEY_SCOPE_LINT_READ],
  usage: [API_KEY_SCOPE_USAGE_INGEST],
  registry_read: [API_KEY_SCOPE_REGISTRY_READ],
  registry_client: [API_KEY_SCOPE_REGISTRY_READ, API_KEY_SCOPE_REGISTRY_WRITE],
  pact_read: [API_KEY_SCOPE_PACT_READ],
  pact_publish: [API_KEY_SCOPE_PACT_READ, API_KEY_SCOPE_PACT_PUBLISH],
  pact_verify: [API_KEY_SCOPE_PACT_READ, API_KEY_SCOPE_PACT_VERIFY],
};

/**
 * Normalize scopes for insert. Empty / missing → full access.
 *
 * @param raw - Caller scopes (array or comma-separated).
 * @returns Valid non-empty scopes array.
 */
export function normalizeApiKeyScopes(raw?: string[] | string | null): string[] {
  let parts: string[];
  if (raw == null || raw === '' || (Array.isArray(raw) && raw.length === 0)) {
    parts = [API_KEY_SCOPE_FULL];
  } else if (typeof raw === 'string') {
    parts = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  } else {
    parts = raw.map((s) => String(s).trim()).filter(Boolean);
  }
  if (parts.length === 0) {
    parts = [API_KEY_SCOPE_FULL];
  }
  for (const s of parts) {
    if (!API_KEY_SCOPE_VOCAB.has(s)) {
      throw new Error(
        `Invalid API key scope "${s}". Allowed: ${[...API_KEY_SCOPE_VOCAB].join(', ')}.`,
      );
    }
  }
  if (parts.includes(API_KEY_SCOPE_FULL) && parts.length > 1) {
    throw new Error(`Scope "*" must stand alone (got: ${parts.join(', ')}).`);
  }
  return [...new Set(parts)];
}

/** Human label for a scopes array (table display). */
export function formatApiKeyScopes(scopes: string[] | null | undefined): string {
  const normalized = normalizeApiKeyScopes(scopes ?? null);
  if (normalized.includes(API_KEY_SCOPE_FULL)) {
    return 'Full access';
  }
  return normalized.join(', ');
}

/** Infer the create-dialog preset from stored scopes (best-effort). */
export function presetFromScopes(scopes: string[] | null | undefined): ApiKeyScopePreset {
  const normalized = normalizeApiKeyScopes(scopes ?? null).slice().sort().join(',');
  if (normalized === '*') return 'full';
  if (normalized === 'diff:read') return 'diff';
  if (normalized === 'lint:read') return 'lint';
  if (normalized === 'diff:read,lint:read') return 'ci_both';
  if (normalized === 'usage:ingest') return 'usage';
  if (normalized === 'registry:read') return 'registry_read';
  if (normalized === 'registry:read,registry:write') return 'registry_client';
  if (normalized === 'pact:read') return 'pact_read';
  if (normalized === 'pact:publish,pact:read') return 'pact_publish';
  if (normalized === 'pact:read,pact:verify') return 'pact_verify';
  return 'full';
}

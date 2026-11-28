/**
 * Contracts **Settings → Secrets**, **CI and commit statuses** and **Agents** — PFX-8.15 (#7312).
 *
 * The model behind the three tabs and their proxies (`/api/pact/secrets*`,
 * `/api/pact/contract-settings*`, `/api/pact/broker-address`). REST owns every rule
 * (`app.pact_contract_settings`, `app.pact_secret`); this module names the switches as the tabs show
 * them and checks bodies before they are forwarded, so nothing unknown is passed on or dropped.
 *
 * * **Secrets** are write-only: no route returns a value. A secret created by `apiome pact migrate`
 *   for a value the source redacted has `has_value: false` until someone sets it; the webhooks waiting
 *   for it are off and come on by themselves when it is set.
 * * **Commit statuses**: on the consumer's commit, on the provider's commit, and for bi-directional
 *   verdicts too (which also fires their webhooks).
 * * **Agents**: what an MCP-connected agent may do. Reading and drafting are on by default; anything
 *   that writes is the workspace's to allow. No agent tool drafts or publishes yet.
 */

/** The page's tab for each group. */
export const SECRETS_TAB_ROUTE = '/ade/dashboard/pacts/settings?tab=secrets';
export const CI_TAB_ROUTE = '/ade/dashboard/pacts/settings?tab=ci';
export const AGENTS_TAB_ROUTE = '/ade/dashboard/pacts/settings?tab=agents';

/** REST paths below `/v1/tenants/{slug}` the proxies forward to. */
export const SECRETS_PROXY_PATH = 'pact-secrets';
export const SETTINGS_PROXY_PATH = 'pact-contract-settings';
export const COMMIT_STATUSES_PROXY_PATH = 'pact-contract-settings/commit-statuses';
export const AGENTS_PROXY_PATH = 'pact-contract-settings/agents';

/** The commit-status switches. */
export interface CommitStatusSettings {
  consumer_commit: boolean;
  provider_commit: boolean;
  bidirectional: boolean;
}

/** The agent switches. */
export interface AgentSettings {
  read: boolean;
  draft: boolean;
  publish: boolean;
  record: boolean;
}

/** `GET …/pact-contract-settings`. */
export interface ContractSettings {
  commit_statuses: CommitStatusSettings;
  agents: AgentSettings;
  configured: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
  can_edit: boolean;
}

/** One switch as a tab draws it. */
export interface SwitchSpec<K extends string> {
  key: K;
  title: string;
  hint: string;
  /** Set when nothing enforces the switch yet: said under it, never hidden. */
  notYet?: string;
}

/** The **Commit statuses** switches, in the order the tab lists them. */
export const COMMIT_SWITCHES: ReadonlyArray<SwitchSpec<keyof CommitStatusSettings>> = [
  {
    key: 'consumer_commit',
    title: 'On the consumer’s commit',
    hint: '“Pact · Ledger API — awaiting verification”, then verified or failed, on the commit that published the pact.',
  },
  {
    key: 'provider_commit',
    title: 'On the provider’s commit',
    hint: 'The verdict of each verification on the provider commit that was verified.',
  },
  {
    key: 'bidirectional',
    title: 'For bi-directional verdicts too',
    hint: 'A spec comparison sets its statuses and fires its verification webhooks, as a verification does.',
  },
];

/** The **Agents** switches, in the order the tab lists them. */
export const AGENT_SWITCHES: ReadonlyArray<SwitchSpec<keyof AgentSettings>> = [
  {
    key: 'read',
    title: 'Read pacts, verdicts and can-i-deploy',
    hint: '“Is it safe to change this field?” answered from real consumers.',
  },
  {
    key: 'draft',
    title: 'Draft a pact from a project or a mock capture',
    hint: 'Returns a draft for a person to review. Publishes nothing.',
    notYet: 'No agent tool drafts pacts yet; this applies when one ships.',
  },
  {
    key: 'publish',
    title: 'Publish pacts and provider contracts',
    hint: 'Only on branches that are not a main branch.',
    notYet: 'No agent tool publishes yet; this applies when one ships.',
  },
  {
    key: 'record',
    title: 'Record deployments',
    hint: 'Never to an environment marked production.',
  },
];

/** A secret as REST lists it: never its value. */
export interface SecretUser {
  kind: 'webhook' | 'verification_target' | string;
  id: string;
  name: string;
  enabled?: boolean | null;
}

/** One workspace secret. */
export interface SecretRecord {
  id: string;
  name: string;
  description?: string | null;
  reference: string;
  used_by: { webhooks: SecretUser[]; targets: SecretUser[] };
  has_value: boolean;
  origin?: string | null;
  value_updated_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** `GET …/pact-secrets`. */
export interface SecretList {
  secrets: SecretRecord[];
  limit: number;
}

/** A secret's name, as REST shapes it (`^[A-Za-z][A-Za-z0-9_]{0,63}$`). */
export const SECRET_NAME = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
/** The longest value a secret may hold. */
export const MAX_SECRET_VALUE = 4096;

/** A body check's answer. */
export type Checked = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

/**
 * Check a switches body: exactly booleans, and only the keys named.
 *
 * @param body - The parsed JSON.
 * @param keys - The switches the group has.
 * @returns The body, or why it is refused (an unknown key or a non-boolean is named).
 */
export function checkSwitchesBody(body: unknown, keys: readonly string[]): Checked {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'Send the switches as a JSON object.' };
  const record = body as Record<string, unknown>;
  for (const [key, value] of Object.entries(record)) {
    if (!keys.includes(key)) return { ok: false, error: `Unsupported field ${key}.` };
    if (typeof value !== 'boolean') return { ok: false, error: `${key} must be true or false.` };
  }
  return { ok: true, body: record };
}

/** The commit-status switch names. */
export const COMMIT_KEYS = COMMIT_SWITCHES.map((spec) => spec.key);
/** The agent switch names. */
export const AGENT_KEYS = AGENT_SWITCHES.map((spec) => spec.key);

/**
 * Check a new secret: a name REST accepts, a value, an optional description.
 *
 * @param body - The parsed JSON.
 * @returns The body, or why it is refused.
 */
export function checkSecretCreate(body: unknown): Checked {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'Send the secret as a JSON object.' };
  const record = body as Record<string, unknown>;
  const unknown = Object.keys(record).find((key) => !['name', 'value', 'description'].includes(key));
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  if (typeof record.name !== 'string' || !SECRET_NAME.test(record.name)) {
    return { ok: false, error: 'A name starts with a letter, then letters, digits or _ (64 at most).' };
  }
  const value = checkValue(record.value);
  if (value) return { ok: false, error: value };
  if (record.description !== undefined && record.description !== null && typeof record.description !== 'string') {
    return { ok: false, error: 'The description is text.' };
  }
  return { ok: true, body: record };
}

/**
 * Check a secret change: a new value and/or description (a secret is never renamed).
 *
 * @param body - The parsed JSON.
 * @returns The body, or why it is refused.
 */
export function checkSecretUpdate(body: unknown): Checked {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'Send the change as a JSON object.' };
  const record = body as Record<string, unknown>;
  const unknown = Object.keys(record).find((key) => !['value', 'description'].includes(key));
  if (unknown !== undefined) {
    return { ok: false, error: unknown === 'name' ? 'A secret cannot be renamed; create a new one.' : `Unsupported field ${unknown}.` };
  }
  if (record.value !== undefined) {
    const value = checkValue(record.value);
    if (value) return { ok: false, error: value };
  }
  return { ok: true, body: record };
}

/**
 * Why a value cannot be stored, or `null`.
 *
 * @param value - The value as sent.
 * @returns The reason, never repeating the value.
 */
export function checkValue(value: unknown): string | null {
  if (typeof value !== 'string' || value === '') return 'Enter the value.';
  if (value.length > MAX_SECRET_VALUE) return `A value is at most ${MAX_SECRET_VALUE} characters.`;
  return null;
}

/**
 * What uses a secret, as the table's **Used by** cell reads.
 *
 * @param secret - The secret.
 * @returns E.g. `3 webhooks · verification target staging`, or `Nothing yet`.
 */
export function usedByText(secret: SecretRecord): string {
  const { webhooks, targets } = secret.used_by;
  const parts: string[] = [];
  if (webhooks.length) {
    const off = webhooks.filter((hook) => hook.enabled === false).length;
    parts.push(`${webhooks.length} webhook${webhooks.length === 1 ? '' : 's'}${off ? ` (${off} off)` : ''}`);
  }
  for (const target of targets) parts.push(`verification target ${target.name}`);
  return parts.length ? parts.join(' · ') : 'Nothing yet';
}

/**
 * Whether a secret is in use (and so cannot be deleted).
 *
 * @param secret - The secret.
 * @returns `true` when a webhook or a verification target refers to it.
 */
export function inUse(secret: SecretRecord): boolean {
  return secret.used_by.webhooks.length > 0 || secret.used_by.targets.length > 0;
}

/**
 * The list of what blocks deleting a secret, for the refusal the tab shows.
 *
 * @param secret - The secret.
 * @returns One line per webhook or target.
 */
export function blockers(secret: SecretRecord): string[] {
  return [
    ...secret.used_by.webhooks.map((hook) => `Webhook “${hook.name}”`),
    ...secret.used_by.targets.map((target) => `Verification target ${target.name}`),
  ];
}

/**
 * The broker base URL a pipeline sets as `PACT_BROKER_BASE_URL`.
 *
 * @param restBase - REST's public base, e.g. `https://api.apiome.dev/v1`.
 * @param tenantSlug - The workspace handle.
 * @returns `https://api.apiome.dev/v1/tenants/acme/pact-broker`.
 */
export function brokerBaseUrl(restBase: string, tenantSlug: string): string {
  return `${restBase.replace(/\/+$/, '')}/tenants/${encodeURIComponent(tenantSlug)}/pact-broker`;
}

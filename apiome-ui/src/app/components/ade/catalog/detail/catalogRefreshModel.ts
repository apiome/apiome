/**
 * The rules behind a catalog item's **Live refresh** card and dialog — MFI-31.1 (#4398).
 *
 * The REST API (`/v1/catalog/{slug}/{item}/refresh`) is the authority: it validates the adapter
 * and endpoint, seals the credential and never returns it. This module only turns its answer into
 * what the card prints and the dialog's form into the body it sends, so both stay pure and
 * testable.
 */

/** A refresh cadence, as REST spells it. */
export type RefreshCadence = 'off' | 'manual' | 'hourly' | 'daily' | 'weekly';

/** A credential type, as REST spells it. */
export type RefreshAuthType = 'none' | 'bearer' | 'header' | 'oauth2';

/** The outcome of the last check. */
export type RefreshStatus = 'never' | 'unchanged' | 'changed' | 'failed';

/** `GET /api/catalog/{id}/refresh` — the item's setting and last check. */
export interface CatalogRefresh {
  itemId: string;
  /** False when the item has no setting (every other field is then a default). */
  configured: boolean;
  cadence: RefreshCadence;
  adapter: string | null;
  endpoint: string | null;
  options: Record<string, unknown>;
  authType: RefreshAuthType;
  /** True when a credential is stored. Its value is never returned. */
  hasCredential: boolean;
  status: RefreshStatus;
  lastCheckedAt: string | null;
  lastSuccessAt: string | null;
  lastFailureAt: string | null;
  lastError: string | null;
  lastFingerprint: string | null;
  consecutiveFailures: number;
  /** When the sweep next checks the item; null for off / manual. */
  nextCheckAt: string | null;
  /** False when the workspace switched catalog refresh off. */
  tenantEnabled: boolean;
  /** Adapters this deployment can refresh. */
  adapters: string[];
}

/** The cadence choices, in order, with what the select prints. */
export const REFRESH_CADENCE_OPTIONS: ReadonlyArray<{ value: RefreshCadence; label: string }> = [
  { value: 'off', label: 'Off' },
  { value: 'manual', label: 'Manual only' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
];

/** The credential choices, with what the select prints. */
export const REFRESH_AUTH_OPTIONS: ReadonlyArray<{ value: RefreshAuthType; label: string }> = [
  { value: 'none', label: 'None' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'header', label: 'Custom header' },
  { value: 'oauth2', label: 'OAuth access token' },
];

/** What each adapter is called and what its endpoint looks like. */
const ADAPTER_VIEW: Readonly<Record<string, { label: string; placeholder: string; hint: string }>> = {
  graphql: {
    label: 'GraphQL introspection',
    placeholder: 'https://api.example.com/graphql',
    hint: 'The GraphQL endpoint URL. Introspection must be enabled.',
  },
  grpc: {
    label: 'gRPC server reflection',
    placeholder: 'grpc.example.com:443',
    hint: 'The server as host:port. Server reflection must be enabled.',
  },
};

/**
 * The display name of an adapter.
 *
 * @param adapter The adapter key.
 * @returns Its label, or the key itself for an adapter this screen does not know.
 */
export function refreshAdapterLabel(adapter: string | null): string {
  if (!adapter) return 'Not set';
  return ADAPTER_VIEW[adapter]?.label ?? adapter;
}

/**
 * The endpoint field's placeholder and helper text for an adapter.
 *
 * @param adapter The adapter key.
 * @returns The placeholder and hint.
 */
export function refreshEndpointHint(adapter: string): { placeholder: string; hint: string } {
  return ADAPTER_VIEW[adapter] ?? { placeholder: 'https://', hint: 'The live endpoint to discover.' };
}

/**
 * The label of a cadence.
 *
 * @param cadence The cadence.
 * @returns Its label.
 */
export function refreshCadenceLabel(cadence: RefreshCadence): string {
  return REFRESH_CADENCE_OPTIONS.find((option) => option.value === cadence)?.label ?? cadence;
}

/** The status pill: a label and a Badge tone. */
export interface RefreshStatusView {
  label: string;
  tone: 'ok' | 'warn' | 'danger' | 'neutral' | 'accent';
}

/**
 * The status pill for the card.
 *
 * The workspace switch wins (nothing is checked while it is off), then *Off*, then the last
 * check's outcome.
 *
 * @param refresh The item's refresh answer.
 * @returns The pill's label and tone.
 */
export function refreshStatusView(refresh: Pick<CatalogRefresh, 'configured' | 'cadence' | 'status' | 'tenantEnabled'>): RefreshStatusView {
  if (!refresh.tenantEnabled) return { label: 'Paused for workspace', tone: 'warn' };
  if (!refresh.configured || refresh.cadence === 'off') return { label: 'Off', tone: 'neutral' };
  switch (refresh.status) {
    case 'failed':
      return { label: 'Last check failed', tone: 'danger' };
    case 'changed':
      return { label: 'Source changed', tone: 'accent' };
    case 'unchanged':
      return { label: 'Up to date', tone: 'ok' };
    default:
      return { label: 'Not checked yet', tone: 'neutral' };
  }
}

/**
 * Whether **Check now** may run: a setting exists, it is not off, and the workspace allows it.
 *
 * @param refresh The item's refresh answer.
 * @returns True when a manual check is allowed.
 */
export function refreshCanCheck(refresh: Pick<CatalogRefresh, 'configured' | 'cadence' | 'tenantEnabled'>): boolean {
  return refresh.configured && refresh.cadence !== 'off' && refresh.tenantEnabled;
}

/**
 * The "Next check" line.
 *
 * @param refresh The item's refresh answer.
 * @returns What the card prints.
 */
export function refreshNextCheckText(refresh: Pick<CatalogRefresh, 'cadence' | 'nextCheckAt'>): string {
  if (refresh.cadence === 'off') return 'Never — refresh is off';
  if (refresh.cadence === 'manual') return 'Only when you check now';
  return refresh.nextCheckAt ? formatRefreshTime(refresh.nextCheckAt) : 'Due now';
}

/**
 * A timestamp as the card prints it (locale date and time), or a dash.
 *
 * @param iso An ISO timestamp.
 * @returns The formatted text.
 */
export function formatRefreshTime(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** The dialog's form. Secret fields are only sent when the user types a new credential. */
export interface RefreshForm {
  adapter: string;
  endpoint: string;
  cadence: RefreshCadence;
  /** gRPC: open a TLS channel. */
  secure: boolean;
  /** `keep` keeps the stored credential; otherwise the type to store. */
  authType: RefreshAuthType | 'keep';
  /** bearer token / OAuth access token / header value. */
  secret: string;
  /** Header name for `header`. */
  headerName: string;
}

/**
 * The form's starting values.
 *
 * A new setting starts on GraphQL, daily, no credential. An existing one starts with its own
 * values and **Keep current credential** when it has one.
 *
 * @param refresh The item's refresh answer, or null while it loads.
 * @returns The initial form.
 */
export function refreshFormFrom(refresh: CatalogRefresh | null): RefreshForm {
  const adapters = refresh?.adapters?.length ? refresh.adapters : ['graphql'];
  if (!refresh?.configured) {
    return { adapter: adapters[0], endpoint: '', cadence: 'daily', secure: false, authType: 'none', secret: '', headerName: '' };
  }
  return {
    adapter: refresh.adapter ?? adapters[0],
    endpoint: refresh.endpoint ?? '',
    cadence: refresh.cadence,
    secure: Boolean(refresh.options?.secure),
    authType: refresh.hasCredential ? 'keep' : 'none',
    secret: '',
    headerName: '',
  };
}

/**
 * Check the form before it is sent, so the obvious mistakes are caught without a round trip.
 *
 * @param form The form.
 * @returns A message for the first problem, or null when it can be sent.
 */
export function refreshFormError(form: RefreshForm): string | null {
  if (!form.endpoint.trim()) return 'Enter the endpoint to discover.';
  if (form.adapter !== 'grpc' && !/^https?:\/\//i.test(form.endpoint.trim())) {
    return 'The endpoint must be an http:// or https:// URL.';
  }
  if (form.authType === 'header' && !form.headerName.trim()) return 'Enter the header name.';
  if ((form.authType === 'bearer' || form.authType === 'oauth2' || form.authType === 'header') && !form.secret) {
    return 'Enter the credential, or choose None.';
  }
  return null;
}

/**
 * The `PUT` body for the form.
 *
 * `credential` is left out to keep the stored one, `null` clears it, and an object replaces it.
 *
 * @param form The form.
 * @returns The JSON body.
 */
export function refreshPayload(form: RefreshForm): Record<string, unknown> {
  const body: Record<string, unknown> = {
    cadence: form.cadence,
    adapter: form.adapter,
    endpoint: form.endpoint.trim(),
    options: form.adapter === 'grpc' ? { secure: form.secure } : {},
  };
  switch (form.authType) {
    case 'keep':
      break;
    case 'none':
      body.credential = null;
      break;
    case 'bearer':
      body.credential = { authType: 'bearer', payload: { token: form.secret } };
      break;
    case 'oauth2':
      body.credential = { authType: 'oauth2', payload: { access_token: form.secret } };
      break;
    case 'header':
      body.credential = { authType: 'header', payload: { name: form.headerName.trim(), value: form.secret } };
      break;
  }
  return body;
}

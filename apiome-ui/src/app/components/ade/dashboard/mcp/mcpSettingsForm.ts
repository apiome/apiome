/**
 * MCP endpoint-detail "Settings" tab — shared types & pure helpers (V2-MCP-24.9 / MCAT-10.9).
 *
 * The Settings tab edits an endpoint's identity & connection (name, URL, transport, visibility,
 * discovery cadence), toggles its lifecycle (enable/disable), and deletes it (purging versions,
 * jobs, and credentials per MCAT-3.5). This module holds the *pure*, React-free form helpers —
 * the editable form shape, the cadence preset table, the inline validation (which reuses the
 * import-source URL/transport rules), the change-only PATCH-body builder, and the teardown-summary
 * formatter — so they can be unit-tested without React or the network. The `McpEndpointSettings`
 * panel consumes them.
 */

import { validateMcpEndpointUrl, type McpTransport } from './mcpImportFlow';
import type { McpEndpointDetail } from './mcpBrowseUi';

/** Visibility values apiome-rest accepts (`MCP_ENDPOINT_VISIBILITIES`). */
export type McpVisibility = 'private' | 'public';

/** Option list for the visibility select (value + human label). */
export const MCP_VISIBILITY_OPTIONS: { value: McpVisibility; label: string }[] = [
  { value: 'private', label: 'Private (only your tenant)' },
  { value: 'public', label: 'Public (listed in the public catalog)' },
];

// --- Discovery cadence ----------------------------------------------------------------------
// apiome-rest bounds the periodic re-discovery cadence to [60s, 30d] (MCP_DISCOVERY_CADENCE_*).
// The Settings tab offers those bounds as a friendly preset select rather than a raw seconds box;
// `''` (the "Default" option) leaves the cadence unset so the server applies its own default.

/** Lower/upper cadence bounds in seconds, mirroring apiome-rest's API guards. */
export const MCP_CADENCE_MIN_SECONDS = 60;
export const MCP_CADENCE_MAX_SECONDS = 30 * 24 * 60 * 60; // 2_592_000 (30 days)

/** A selectable cadence preset: its value in seconds and the human label shown in the select. */
export interface McpCadencePreset {
  seconds: number;
  label: string;
}

/** Common cadence presets spanning the allowed range, newest-first then coarsening. */
export const MCP_CADENCE_PRESETS: readonly McpCadencePreset[] = [
  { seconds: 60 * 60, label: 'Every hour' },
  { seconds: 6 * 60 * 60, label: 'Every 6 hours' },
  { seconds: 12 * 60 * 60, label: 'Every 12 hours' },
  { seconds: 24 * 60 * 60, label: 'Daily' },
  { seconds: 7 * 24 * 60 * 60, label: 'Weekly' },
  { seconds: 30 * 24 * 60 * 60, label: 'Every 30 days' },
] as const;

/**
 * Format a cadence in seconds as a friendly label. Exact preset matches use the preset label;
 * any other value is rendered as a rounded relative span (`Every 90 minutes` / `Every 3 days`),
 * so an endpoint with a custom cadence still reads clearly in the select.
 */
export function mcpCadenceLabel(seconds: number): string {
  const preset = MCP_CADENCE_PRESETS.find((p) => p.seconds === seconds);
  if (preset) return preset.label;
  if (seconds % (24 * 60 * 60) === 0) {
    const days = seconds / (24 * 60 * 60);
    return days === 1 ? 'Daily' : `Every ${days} days`;
  }
  if (seconds % (60 * 60) === 0) {
    const hours = seconds / (60 * 60);
    return hours === 1 ? 'Every hour' : `Every ${hours} hours`;
  }
  const minutes = Math.round(seconds / 60);
  return `Every ${minutes} minutes`;
}

/** One cadence option for the select: a stringified seconds value (or `''`) and its label. */
export interface McpCadenceOption {
  /** Select value: the cadence in seconds as a string, or `''` for the server default. */
  value: string;
  label: string;
}

/**
 * Build the cadence-select options for an endpoint's current cadence. Always includes the
 * "Default" option and every preset; when the current cadence is a non-preset custom value it is
 * inserted (sorted) so the select can render the endpoint's actual setting.
 *
 * @param currentSeconds The endpoint's stored cadence in seconds, or `null` for the default.
 */
export function mcpCadenceOptions(currentSeconds: number | null): McpCadenceOption[] {
  const seconds = new Set<number>(MCP_CADENCE_PRESETS.map((p) => p.seconds));
  if (currentSeconds != null && currentSeconds > 0) seconds.add(currentSeconds);
  const sorted = Array.from(seconds).sort((a, b) => a - b);
  return [
    { value: '', label: 'Default cadence' },
    ...sorted.map((s) => ({ value: String(s), label: mcpCadenceLabel(s) })),
  ];
}

// --- Form state -----------------------------------------------------------------------------

/** Editable identity/connection fields of the Settings form (all rendered as text/select inputs). */
export interface McpSettingsForm {
  name: string;
  endpointUrl: string;
  transport: McpTransport;
  visibility: McpVisibility;
  /** Cadence in seconds as a string (the select value), or `''` for the server default. */
  cadence: string;
}

/** Coerce an arbitrary visibility string to a known value, defaulting to `private`. */
function asVisibility(value: string | null | undefined): McpVisibility {
  return value === 'public' ? 'public' : 'private';
}

/** Coerce an arbitrary transport string to a known value, defaulting to `streamable_http`. */
function asTransport(value: string | null | undefined): McpTransport {
  if (value === 'sse' || value === 'stdio') return value;
  return 'streamable_http';
}

/** Seed a Settings form from an endpoint-detail record. */
export function mcpSettingsFormFromEndpoint(endpoint: McpEndpointDetail): McpSettingsForm {
  return {
    name: endpoint.name ?? '',
    endpointUrl: endpoint.endpoint_url ?? '',
    transport: asTransport(endpoint.transport),
    visibility: asVisibility(endpoint.visibility),
    cadence:
      endpoint.discovery_cadence_seconds != null && endpoint.discovery_cadence_seconds > 0
        ? String(endpoint.discovery_cadence_seconds)
        : '',
  };
}

/**
 * Validate the Settings form. Returns a human-readable error string, or `null` when the form is
 * ready to save. Mirrors apiome-rest's guards: a non-blank name, and a URL valid for its
 * transport (reusing the import-source rule). The cadence comes from a bounded preset select, so
 * it needs no extra range check here.
 */
export function validateMcpSettingsForm(form: McpSettingsForm): string | null {
  if (!(form.name ?? '').trim()) return 'Enter a name for this endpoint.';
  const urlError = validateMcpEndpointUrl(form.endpointUrl, form.transport);
  if (urlError) return urlError;
  return null;
}

/** The PATCH body sent to update an endpoint — only the keys that actually changed. */
export interface McpSettingsPatchBody {
  name?: string;
  endpoint_url?: string;
  transport?: McpTransport;
  visibility?: McpVisibility;
  discovery_cadence_seconds?: number;
}

/**
 * Build a change-only PATCH body by diffing the edited form against the endpoint it was seeded
 * from. Only fields whose (trimmed/normalized) value differs from the original are included, so a
 * no-op save sends nothing. The cadence is omitted when left on "Default" (`''`) and unchanged —
 * clearing a previously-set cadence back to the default is not expressible through PATCH (which
 * only sets values), so the select offers presets, not an "unset".
 *
 * @returns The minimal patch body; an empty object means nothing changed.
 */
export function buildSettingsPatchBody(
  form: McpSettingsForm,
  original: McpEndpointDetail,
): McpSettingsPatchBody {
  const patch: McpSettingsPatchBody = {};

  const name = form.name.trim();
  if (name && name !== (original.name ?? '').trim()) patch.name = name;

  const url = form.endpointUrl.trim();
  if (url && url !== (original.endpoint_url ?? '').trim()) patch.endpoint_url = url;

  if (form.transport !== asTransport(original.transport)) patch.transport = form.transport;

  if (form.visibility !== asVisibility(original.visibility)) patch.visibility = form.visibility;

  const cadence = form.cadence ? Number(form.cadence) : null;
  const originalCadence =
    original.discovery_cadence_seconds != null && original.discovery_cadence_seconds > 0
      ? original.discovery_cadence_seconds
      : null;
  if (cadence != null && cadence !== originalCadence) {
    patch.discovery_cadence_seconds = cadence;
  }

  return patch;
}

/** True when a built patch body carries at least one field to send. */
export function hasSettingsChanges(patch: McpSettingsPatchBody): boolean {
  return Object.keys(patch).length > 0;
}

// --- Delete confirmation & teardown summary -------------------------------------------------

/** The exact word the user must type to arm the destructive delete (matches the mockup). */
export const MCP_DELETE_CONFIRM_WORD = 'DELETE';

/** True when the typed confirmation matches the required word (case-sensitive, trimmed). */
export function isDeleteConfirmed(typed: string): boolean {
  return (typed ?? '').trim() === MCP_DELETE_CONFIRM_WORD;
}

/** The teardown summary apiome-rest returns from DELETE (MCAT-3.5). */
export interface McpTeardownSummary {
  credentials_purged: boolean;
  versions_deleted: number;
  jobs_deleted: number;
}

/** Parse a DELETE response payload into a {@link McpTeardownSummary} defensively. */
export function mcpTeardownSummaryFromPayload(data: unknown): McpTeardownSummary {
  const d = (data ?? {}) as Record<string, unknown>;
  return {
    credentials_purged: d.credentials_purged === true,
    versions_deleted:
      typeof d.versions_deleted === 'number' && Number.isFinite(d.versions_deleted)
        ? Math.trunc(d.versions_deleted)
        : 0,
    jobs_deleted:
      typeof d.jobs_deleted === 'number' && Number.isFinite(d.jobs_deleted)
        ? Math.trunc(d.jobs_deleted)
        : 0,
  };
}

/** Pluralize a count: `1 version`, `3 versions`. */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * Render a one-line, human teardown summary for a deleted endpoint, e.g.
 * `Removed 3 versions, 2 jobs, and purged stored credentials.` Used in the post-delete toast so
 * the user sees exactly what the cascade removed.
 */
export function formatTeardownSummary(summary: McpTeardownSummary): string {
  const parts = [plural(summary.versions_deleted, 'version'), plural(summary.jobs_deleted, 'job')];
  const credentials = summary.credentials_purged
    ? ' and purged stored credentials'
    : '';
  return `Removed ${parts.join(', ')}${credentials}.`;
}

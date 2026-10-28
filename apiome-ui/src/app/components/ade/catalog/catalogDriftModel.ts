/**
 * Catalog drift — the shapes, wording and BFF calls behind the drift badge, banner, "What changed"
 * panel and the workspace's drift alerts (MFI-31.3, #4400).
 *
 * A live refresh that adds a version to a catalog item records **drift**: the change from the
 * version it superseded, graded by the breaking-change engine as `safe`, `dangerous` or `breaking`
 * (the worst change wins). REST stores it as an event; the catalog list and detail carry the
 * newest undismissed one as `drift`. Everything here is pure except the four `fetch` helpers at
 * the bottom, so the components stay thin and the rules are unit-tested.
 */

import type { BadgeTone } from '@/app/components/ui/Badge';

/** The breaking-change severities (MFI-3.3), least to most severe. */
export type DriftSeverity = 'safe' | 'dangerous' | 'breaking';

/** How an event was announced. */
export type DriftNotification = 'none' | 'sent' | 'pending_digest' | 'digested';

/** An item's newest undismissed drift, as the catalog list and detail carry it. */
export interface CatalogDriftBadgeData {
  eventId: string;
  severity: DriftSeverity;
  versionId: string;
  versionLabel: string;
  changeCount: number;
  counts: Partial<Record<DriftSeverity, number>>;
  trigger: 'sweep' | 'manual';
  detectedAt: string | null;
  /** The item's Versions tab, opened on this drift. */
  link: string;
}

/** One classified change. */
export interface CatalogDriftChange {
  severity: DriftSeverity;
  category?: string | null;
  kind?: string | null;
  key?: string | null;
  ruleId?: string | null;
  rationale?: string | null;
}

/** One drift event with its changes (`GET /api/catalog/{id}/drift`). */
export interface CatalogDriftEvent extends CatalogDriftBadgeData {
  parentVersionId: string | null;
  parentVersionLabel: string | null;
  notification: DriftNotification;
  notifiedAt: string | null;
  dismissedAt: string | null;
  /** Worst first; at most 200 (`changeCount` is the full count). */
  changes: CatalogDriftChange[];
}

/** The workspace's drift alert settings. */
export interface CatalogDriftSettings {
  notifyBreaking: boolean;
  notifyDangerous: boolean;
  notifySafe: boolean;
  delivery: 'immediate' | 'daily_digest';
  breakingImmediate: boolean;
  emailEnabled: boolean;
  /** False while the workspace uses the defaults. */
  configured?: boolean;
  updatedAt?: string | null;
  lastDigestAt?: string | null;
}

/** The defaults a workspace without saved settings gets (REST's defaults). */
export const DEFAULT_DRIFT_SETTINGS: CatalogDriftSettings = {
  notifyBreaking: true,
  notifyDangerous: true,
  notifySafe: false,
  delivery: 'immediate',
  breakingImmediate: true,
  emailEnabled: false,
};

/** How a severity is spoken and drawn. */
export interface DriftSeverityView {
  /** "Breaking", "Dangerous", "Safe". */
  label: string;
  /** The badge tone. */
  tone: BadgeTone;
  /** One line on what the severity means for callers. */
  meaning: string;
}

/** Severity → label, tone and meaning. */
export const DRIFT_SEVERITY_VIEW: Readonly<Record<DriftSeverity, DriftSeverityView>> = {
  breaking: { label: 'Breaking', tone: 'danger', meaning: 'Existing callers can break.' },
  dangerous: { label: 'Dangerous', tone: 'warn', meaning: 'Compatible, but worth a review.' },
  safe: { label: 'Safe', tone: 'ok', meaning: 'Additive; existing callers keep working.' },
};

/** The severities, most severe first (the order the counts and the panel use). */
export const DRIFT_SEVERITIES_WORST_FIRST: readonly DriftSeverity[] = ['breaking', 'dangerous', 'safe'];

/**
 * The badge text, e.g. "Breaking drift".
 *
 * @param severity The drift's severity.
 * @returns The label.
 */
export function driftBadgeLabel(severity: DriftSeverity): string {
  return `${DRIFT_SEVERITY_VIEW[severity].label} drift`;
}

/**
 * The non-zero counts, worst first, e.g. "1 breaking · 2 safe"; "No changes" when all are zero.
 *
 * @param counts Changes per severity.
 * @returns The phrase.
 */
export function driftCountsText(counts: Partial<Record<DriftSeverity, number>>): string {
  const parts = DRIFT_SEVERITIES_WORST_FIRST.filter((severity) => (counts[severity] ?? 0) > 0).map(
    (severity) => `${counts[severity]} ${severity}`,
  );
  return parts.length ? parts.join(' · ') : 'No changes';
}

/**
 * The badge's tooltip: what changed and when.
 *
 * @param drift The badge data.
 * @returns e.g. "The live API changed in 2026-10-28T12:00Z: 1 breaking · 2 safe".
 */
export function driftBadgeTitle(drift: CatalogDriftBadgeData): string {
  return `The live API changed in ${drift.versionLabel}: ${driftCountsText(drift.counts)}`;
}

/**
 * The banner's headline.
 *
 * @param drift The badge data.
 * @returns e.g. "Live refresh found breaking changes in version 2026-10-28T12:00Z".
 */
export function driftBannerTitle(drift: CatalogDriftBadgeData): string {
  const noun = drift.severity === 'safe' ? 'safe changes' : `${drift.severity} changes`;
  return `Live refresh found ${noun} in version ${drift.versionLabel}`;
}

/** How the announcement column reads. */
export const DRIFT_NOTIFICATION_LABEL: Readonly<Record<DriftNotification, string>> = {
  none: 'Not announced',
  sent: 'Announced',
  pending_digest: 'Waiting for the daily digest',
  digested: 'Sent in a daily digest',
};

/**
 * Which event the "What changed" panel opens on: the one the address names, else the newest
 * undismissed one, else the newest.
 *
 * @param events The item's events, newest first.
 * @param requestedId The `?drift=` id, if any.
 * @returns The event, or `null` when there are none.
 */
export function selectDriftEvent(events: readonly CatalogDriftEvent[], requestedId: string | null): CatalogDriftEvent | null {
  if (!events.length) return null;
  const requested = requestedId ? events.find((event) => event.eventId === requestedId) : undefined;
  return requested ?? events.find((event) => !event.dismissedAt) ?? events[0];
}

/**
 * The query string that opens the Versions tab on one event (the banner's link).
 *
 * @param search The current query string.
 * @param eventId The event to open.
 * @returns The new query string, with its leading `?`.
 */
export function driftVersionsSearch(search: string, eventId: string): string {
  const params = new URLSearchParams(search);
  params.set('tab', 'versions');
  params.set('drift', eventId);
  return `?${params.toString()}`;
}

/**
 * A one-line summary of the settings for the dialog's footer note.
 *
 * @param settings The settings.
 * @returns e.g. "Breaking and dangerous drift is announced right away; safe drift only shows a badge."
 */
export function driftSettingsSummary(settings: CatalogDriftSettings): string {
  const announced = DRIFT_SEVERITIES_WORST_FIRST.filter((severity) =>
    severity === 'breaking' ? settings.notifyBreaking : severity === 'dangerous' ? settings.notifyDangerous : settings.notifySafe,
  );
  const quiet = DRIFT_SEVERITIES_WORST_FIRST.filter((severity) => !announced.includes(severity));
  if (!announced.length) return 'No drift is announced; every drift only shows a badge.';
  const when =
    settings.delivery === 'daily_digest'
      ? settings.breakingImmediate && announced.includes('breaking')
        ? 'in a daily digest (breaking drift right away)'
        : 'in a daily digest'
      : 'right away';
  const joined = joinWords(announced);
  const tail = quiet.length ? `; ${joinWords(quiet)} drift only shows a badge.` : '.';
  return `${joined.charAt(0).toUpperCase()}${joined.slice(1)} drift is announced ${when}${tail}`;
}

function joinWords(words: readonly string[]): string {
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

// ---------------------------------------------------------------------------------------
// BFF calls
// ---------------------------------------------------------------------------------------

/** Read a BFF answer, throwing its error message (or `fallback`) on failure. */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error((data && (data.error || data.detail)) || fallback);
  }
  return data as T;
}

/**
 * Load an item's drift events, newest first.
 *
 * @param itemId The catalog item.
 * @returns The events.
 */
export async function fetchDriftEvents(itemId: string): Promise<CatalogDriftEvent[]> {
  const data = await readJson<{ events?: CatalogDriftEvent[] }>(
    await fetch(`/api/catalog/${encodeURIComponent(itemId)}/drift`),
    'The drift could not be loaded.',
  );
  return data.events ?? [];
}

/**
 * Dismiss an event's badge and banner.
 *
 * @param itemId The catalog item.
 * @param eventId The event.
 * @returns The dismissed event.
 */
export async function dismissDrift(itemId: string, eventId: string): Promise<CatalogDriftEvent> {
  return readJson<CatalogDriftEvent>(
    await fetch(`/api/catalog/${encodeURIComponent(itemId)}/drift/${encodeURIComponent(eventId)}/dismiss`, {
      method: 'POST',
    }),
    'The drift could not be dismissed.',
  );
}

/** Load the workspace's drift alert settings. */
export async function fetchDriftSettings(): Promise<CatalogDriftSettings> {
  return readJson<CatalogDriftSettings>(
    await fetch('/api/catalog/drift-notifications'),
    'The drift alert settings could not be loaded.',
  );
}

/**
 * Save the workspace's drift alert settings.
 *
 * @param settings The settings to store.
 * @returns The stored settings.
 */
export async function saveDriftSettings(settings: CatalogDriftSettings): Promise<CatalogDriftSettings> {
  const body = {
    notifyBreaking: settings.notifyBreaking,
    notifyDangerous: settings.notifyDangerous,
    notifySafe: settings.notifySafe,
    delivery: settings.delivery,
    breakingImmediate: settings.breakingImmediate,
    emailEnabled: settings.emailEnabled,
  };
  return readJson<CatalogDriftSettings>(
    await fetch('/api/catalog/drift-notifications', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'The drift alert settings could not be saved.',
  );
}

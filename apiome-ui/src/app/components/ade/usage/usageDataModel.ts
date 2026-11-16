/**
 * The usage-data controls' shapes and pure helpers — RDG-5.4 (#5789).
 *
 * Mirrors the REST models of `app.usage_controls` (apiome-rest). Every helper here is pure, so
 * the drawer stays a thin view and the rules can be tested without rendering.
 *
 * One vocabulary covers both body-sample opt-ins: a usage source's **body samples** (at most 5 %)
 * and an agent toolset's **body capture** (AGX-3.3, at most 100 %). Both are a `rate` plus an
 * `until` at most 7 days ahead, and opening either takes the acknowledgement sentence REST sends.
 */

/** A pair of retention values in days. `-1` keeps rows forever (a tier cap only). */
export interface RetentionDays {
  hourlyDays: number | null;
  rollupDays: number | null;
}

/** `GET …/usage/retention`. */
export interface UsageRetention {
  caps: RetentionDays;
  setting: RetentionDays;
  effective: RetentionDays;
  sampleRetentionDays: number;
  updatedAt: string | null;
}

/** A body-sample opt-in as it stands, with its hard caps. */
export interface BodySamples {
  rate: number;
  until: string | null;
  open: boolean;
  maxRate: number;
  maxWindowDays: number;
  retentionDays: number;
}

/** One usage source of the project. */
export interface UsageSource {
  id: string;
  kind: string;
  environment: string;
  enabled: boolean;
  samplingRate: number;
  fieldCapture: boolean;
  bodySamples: BodySamples;
  lastReceivedAt: string | null;
}

/** One agent toolset of the project, with its body-capture opt-in. */
export interface ToolsetBodySamples {
  id: string;
  versionId: string;
  versionLabel: string | null;
  enabled: boolean;
  bodySamples: BodySamples;
}

/** `GET …/projects/{p}/usage/sources`. */
export interface UsageSourceList {
  sources: UsageSource[];
  agentToolsets: ToolsetBodySamples[];
  acknowledgement: string;
}

/** What `PATCH …/body-samples` (and a source's `bodySamples`) takes. */
export interface BodySampleWindow {
  rate: number;
  until?: string | null;
  acknowledgement?: string | null;
}

/** The body-sample form as typed: a percentage, a number of days and the checkbox. */
export interface BodySampleDraft {
  percent: string;
  days: string;
  acknowledged: boolean;
}

/** The export formats REST streams. */
export const EXPORT_FORMATS = ['csv', 'json'] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

/** The export's default window and its longest one, in UTC days (REST bounds). */
export const DEFAULT_EXPORT_DAYS = 30;
export const MAX_EXPORT_DAYS = 730;

/** A new body-sample window: 1 % for one day, not yet acknowledged. */
export const EMPTY_BODY_SAMPLE_DRAFT: BodySampleDraft = { percent: '1', days: '1', acknowledged: false };

/** Labels for the source kinds REST reports. */
export const SOURCE_KIND_LABEL: Record<string, string> = {
  otlp: 'OpenTelemetry',
  har: 'HAR upload',
  access_log: 'Access log',
  mock: 'Mock server',
  agent: 'Agent runtime',
  sdk_beacon: 'SDK beacon',
};

/**
 * A fraction as a percentage for display (`0.05` → `5 %`, `1` → `100 %`).
 *
 * @param fraction The fraction in [0, 1].
 * @returns The label.
 */
export function percentLabel(fraction: number): string {
  const percent = Math.round(fraction * 10000) / 100;
  return `${percent} %`;
}

/**
 * A retention value for display.
 *
 * @param days Days, `-1` for forever, `null` for "not set".
 * @returns `30 days`, `Forever` or `Tier cap`.
 */
export function daysLabel(days: number | null): string {
  if (days === null) return 'Tier cap';
  if (days < 0) return 'Forever';
  return days === 1 ? '1 day' : `${days} days`;
}

/**
 * Why a typed retention value cannot be saved, or `null` when it can. Mirrors the REST rule so
 * the button explains itself before the request; REST refuses with the cap named regardless.
 *
 * @param typed The text in the field (empty = back to the cap).
 * @param cap The tier cap (`-1` = forever).
 * @param key The seats key REST names.
 * @returns The problem sentence, or `null`.
 */
export function retentionProblem(typed: string, cap: number | null, key: string): string | null {
  const text = typed.trim();
  if (!text) return null;
  const value = Number(text);
  if (!Number.isInteger(value) || value < 1) return `${key} must be a whole number of days, at least 1.`;
  if (cap !== null && cap >= 0 && value > cap) {
    return `${key} may be at most ${cap} days on this workspace's tier.`;
  }
  return null;
}

/**
 * The typed retention as the REST body value.
 *
 * @param typed The text in the field.
 * @returns The number, or `null` to go back to the cap.
 */
export function retentionValue(typed: string): number | null {
  const text = typed.trim();
  return text ? Number(text) : null;
}

/**
 * Why a body-sample draft cannot open a window, or `null` when it can.
 *
 * @param draft The form.
 * @param samples The opt-in being changed (its caps).
 * @returns The reason, worded for a disabled button's title.
 */
export function bodySampleProblem(draft: BodySampleDraft, samples: Pick<BodySamples, 'maxRate' | 'maxWindowDays'>): string | null {
  const percent = Number(draft.percent);
  const days = Number(draft.days);
  const maxPercent = samples.maxRate * 100;
  if (!draft.percent.trim() || !Number.isFinite(percent) || percent <= 0 || percent > maxPercent) {
    return `Enter a rate above 0 and at most ${maxPercent} %.`;
  }
  if (!Number.isInteger(days) || days < 1 || days > samples.maxWindowDays) {
    return `Enter a window of 1 to ${samples.maxWindowDays} days.`;
  }
  if (!draft.acknowledged) return 'Tick the acknowledgement first.';
  return null;
}

/**
 * The REST body that opens a window from a valid draft.
 *
 * @param draft The form (already checked with {@link bodySampleProblem}).
 * @param acknowledgement The sentence REST requires.
 * @param now The current time (for tests).
 * @returns The window.
 */
export function bodySampleWindow(draft: BodySampleDraft, acknowledgement: string, now: Date = new Date()): BodySampleWindow {
  const until = new Date(now.getTime() + Number(draft.days) * 24 * 60 * 60 * 1000);
  return { rate: Number(draft.percent) / 100, until: until.toISOString(), acknowledgement };
}

/**
 * One line describing a body-sample opt-in.
 *
 * @param samples The opt-in.
 * @returns `Off`, `5 % until 18 Nov 2026, 14:00 UTC` or `Ended …`.
 */
export function bodySampleLine(samples: BodySamples): string {
  if (samples.rate <= 0) return 'Off';
  const until = samples.until ? utcLabel(samples.until) : 'no end set';
  return samples.open ? `${percentLabel(samples.rate)} until ${until}` : `Ended ${until}`;
}

/**
 * A timestamp as a short UTC label, the same for every viewer and every test run.
 *
 * @param iso An ISO 8601 timestamp.
 * @returns `18 Nov 2026, 14:00 UTC`.
 */
export function utcLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getUTCDate()} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${pad(date.getUTCHours())}:${pad(
    date.getUTCMinutes(),
  )} UTC`;
}

/**
 * The browser URL that downloads an export through the UI proxy.
 *
 * @param projectRef Project slug or id.
 * @param format `csv` or `json`.
 * @param days The window, clamped to REST's bounds.
 * @returns The `/api/usage/…/export` URL.
 */
export function exportHref(projectRef: string, format: ExportFormat, days: number): string {
  const window = Math.min(Math.max(Math.round(days) || DEFAULT_EXPORT_DAYS, 1), MAX_EXPORT_DAYS);
  return `/api/usage/${encodeURIComponent(projectRef)}/export?format=${format}&days=${window}`;
}

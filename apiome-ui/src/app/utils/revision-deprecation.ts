/**
 * Client-side helpers for schema revision deprecation (versions.metadata) — #507.
 * Keep in sync with apiome-rest `revision_deprecation.py`.
 * Accepts either a plain object or a JSON string (matching the backend `coerce_metadata` helper).
 */

export const MIGRATION_GUIDE_ISSUE_URL =
  'https://github.com/KenSuenobu/objectified-commercial/issues/747';

function coerceMetadata(raw: unknown): Record<string, unknown> {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  if (typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>;
  return {};
}

export function isRevisionDeprecated(metadata: unknown): boolean {
  const m = coerceMetadata(metadata);
  const d = m.deprecated;
  if (d === true) return true;
  if (typeof d === 'string' && ['true', '1', 'yes'].includes(d.toLowerCase())) return true;
  return false;
}

/** Convert `datetime-local` value (browser local) to UTC ISO for API `sunsetAt`. */
export function localDatetimeLocalToUtcIso(local: string): string | null {
  if (!local?.trim()) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

/** Format a UTC ISO string for `datetime-local` (local timezone). */
export function utcIsoToDatetimeLocalValue(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function revisionDeprecationLines(metadata: unknown): string[] {
  if (!isRevisionDeprecated(metadata)) return [];
  const m = coerceMetadata(metadata);
  const lines: string[] = [];
  const msg = m.deprecationMessage ?? m.message;
  if (typeof msg === 'string' && msg.trim()) lines.push(msg.trim());
  const succ = m.successorRevisionId ?? m.successor_revision_id;
  if (typeof succ === 'string' && succ.trim()) {
    lines.push(`Successor revision: ${succ.trim()}.`);
  }
  const sunset = m.sunsetAt ?? m.sunsetDate ?? m.sunset_date;
  if (typeof sunset === 'string' && sunset.trim()) {
    lines.push(`Sunset: ${sunset.trim()} (UTC).`);
  }
  lines.push(`Migration guide: ${MIGRATION_GUIDE_ISSUE_URL}`);
  return lines;
}

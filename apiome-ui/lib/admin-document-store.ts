/**
 * Document store view for the admin console (COA-5.9, #7085).
 *
 * Types for the REST bodies of `GET /v1/admin/document-store` and
 * `POST /v1/admin/document-store/test` (the same bodies `/v1/ops/document-store` returns to a
 * platform admin), plus the pure helpers the **Document store** page renders them with.
 *
 * The store is configured only by the REST server's environment (`APIOME_DOCUMENT_STORE*`). These
 * bodies never carry a credential: `credentials` only says whether static keys or the default
 * credential chain are in use.
 *
 * Client-safe: no server imports.
 */

/** A backend the REST server supports. */
export type DocumentStoreBackend = 'db' | 's3' | 'filesystem';

/** The latest reachability check of the active store. */
export interface DocumentStoreHealth {
  ok: boolean;
  /** Epoch seconds. */
  checkedAt: number;
  /** The redacted failure; null when ok. */
  error: string | null;
}

/** Indexed objects one backend holds. */
export interface DocumentStoreBackendUsage {
  backend: string;
  objects: number;
  bytes: number;
}

/** Totals from the document index (originals, rendered documents, frozen schemas). */
export interface DocumentStoreUsage {
  objects: number;
  bytes: number;
  byBackend: DocumentStoreBackendUsage[];
  integrity: {
    /** ISO 8601, or null when no object has been verified yet. */
    lastVerifiedAt: string | null;
    verifiedObjects: number;
  };
}

/** `GET /v1/admin/document-store`. */
export interface DocumentStoreStatus {
  backend: DocumentStoreBackend;
  configuredBackend: string;
  fallback: boolean;
  fallbackReason: string | null;
  backends: string[];
  bucket: string | null;
  prefix: string;
  region: string | null;
  endpointUrl: string | null;
  addressingStyle: string | null;
  path: string | null;
  encryption: string | null;
  kmsKeyId: string | null;
  credentials: 'static' | 'default-chain' | null;
  presignTtlSeconds: number | null;
  maxObjectBytes: number | null;
  health: DocumentStoreHealth;
  /** Null when the document index cannot be read. */
  usage: DocumentStoreUsage | null;
}

/** One step of the connection test. */
export interface DocumentStoreProbeStep {
  name: 'write' | 'read' | 'delete';
  ok: boolean;
  skipped: boolean;
  durationMs: number;
  error: string | null;
}

/** `POST /v1/admin/document-store/test`. */
export interface DocumentStoreProbeResult {
  ok: boolean;
  backend: string;
  checkedAt: number;
  durationMs: number;
  steps: DocumentStoreProbeStep[];
}

/** One label/value row of the Settings card. */
export interface DocumentStoreSettingRow {
  label: string;
  value: string;
  /** Show the value in a monospace font (keys, paths, URLs). */
  mono?: boolean;
}

/** Display names of the backends. */
export const BACKEND_LABELS: Record<string, string> = {
  db: 'Database',
  s3: 'S3-compatible bucket',
  filesystem: 'Filesystem',
};

/** Display names of the S3 encryption modes. */
const ENCRYPTION_LABELS: Record<string, string> = {
  none: 'Bucket default',
  'sse-s3': 'SSE-S3 (AES-256)',
  'sse-kms': 'SSE-KMS',
};

/** Display names of the probe steps. */
export const PROBE_STEP_LABELS: Record<DocumentStoreProbeStep['name'], string> = {
  write: 'Write a probe object',
  read: 'Read it back',
  delete: 'Delete it',
};

/**
 * The display name of a backend.
 *
 * @param backend `db`, `s3` or `filesystem` (anything else is shown as given).
 * @returns The label, e.g. `S3-compatible bucket`.
 */
export function backendLabel(backend: string): string {
  return BACKEND_LABELS[backend] ?? backend;
}

/**
 * Format a byte count with binary units.
 *
 * @param bytes A non-negative byte count.
 * @returns e.g. `0 B`, `512 B`, `1.5 KiB`, `32 MiB`.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 1024) return `${Math.max(0, Math.trunc(bytes || 0))} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit]}`;
}

/**
 * Format a duration in seconds for the Settings card.
 *
 * @param seconds Whole seconds.
 * @returns e.g. `45 seconds`, `5 minutes`, `2 hours`.
 */
export function formatSeconds(seconds: number): string {
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600} hour${seconds === 3600 ? '' : 's'}`;
  if (seconds % 60 === 0 && seconds >= 60) return `${seconds / 60} minute${seconds === 60 ? '' : 's'}`;
  return `${seconds} second${seconds === 1 ? '' : 's'}`;
}

/**
 * The Settings card rows for the active backend — only the settings that apply to it.
 *
 * @param status The REST body.
 * @returns Rows in display order.
 */
export function settingRows(status: DocumentStoreStatus): DocumentStoreSettingRow[] {
  const rows: DocumentStoreSettingRow[] = [{ label: 'Backend', value: backendLabel(status.backend) }];
  if (status.backend === 's3') {
    rows.push({ label: 'Bucket', value: status.bucket ?? '—', mono: true });
    rows.push({ label: 'Region', value: status.region ?? '—', mono: true });
    rows.push({ label: 'Endpoint', value: status.endpointUrl ?? 'AWS S3', mono: Boolean(status.endpointUrl) });
    rows.push({ label: 'Addressing style', value: status.addressingStyle ?? 'auto' });
    const encryption = status.encryption ?? 'none';
    rows.push({
      label: 'Encryption',
      value:
        encryption === 'sse-kms' && status.kmsKeyId
          ? `${ENCRYPTION_LABELS[encryption]} · ${status.kmsKeyId}`
          : (ENCRYPTION_LABELS[encryption] ?? encryption),
    });
    rows.push({
      label: 'Credentials',
      value: status.credentials === 'static' ? 'Static keys (server environment)' : 'Default credential chain or IAM role',
    });
    if (status.presignTtlSeconds != null) {
      rows.push({ label: 'Download link lifetime', value: formatSeconds(status.presignTtlSeconds) });
    }
  } else if (status.backend === 'filesystem') {
    rows.push({ label: 'Directory', value: status.path ?? '—', mono: true });
  } else if (status.maxObjectBytes != null) {
    rows.push({ label: 'Largest object', value: formatBytes(status.maxObjectBytes) });
  }
  rows.push({ label: 'Prefix', value: status.prefix ? `${status.prefix}/` : '(bucket root)', mono: Boolean(status.prefix) });
  return rows;
}

/**
 * Format an epoch-seconds or ISO timestamp for display in the viewer's locale.
 *
 * @param value Epoch seconds, an ISO 8601 string, or null.
 * @param fallback What to show for null.
 * @returns The localized date and time, or `fallback`.
 */
export function formatWhen(value: number | string | null, fallback = 'Never'): string {
  if (value == null) return fallback;
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString();
}

/**
 * Backup manifest: the small JSON sidecar that describes a backup artifact.
 *
 * Every backup writes two files: the (optionally encrypted) data artifact and a `*.manifest.json`
 * sidecar. The manifest is always plaintext so an operator can inspect scope, size, age, and
 * integrity without the encryption key — it contains no secrets, only metadata and a SHA-256 of
 * the artifact for tamper/corruption detection during a restore or drill.
 */

import crypto from "node:crypto";

import { CliError } from "../errors.js";

/** Current manifest schema version. Bump when the shape changes incompatibly. */
export const MANIFEST_VERSION = 1;

/** What a backup covers. `full` is a whole-cluster pg_dump; `tenant`/`project` are logical exports. */
export type BackupKind = "full" | "tenant" | "project";

/** Per-table row counts captured in a logical export (empty for `full` pg_dump backups). */
export type TableCounts = Record<string, number>;

export type BackupManifest = {
  manifestVersion: number;
  /** Stable id of this backup (also the artifact filename stem). */
  id: string;
  kind: BackupKind;
  /** Tenant slug/id when scoped (null for `full`). */
  tenant: string | null;
  /** Project slug/id when project-scoped (null otherwise). */
  project: string | null;
  /** When the backup was taken (ISO 8601, UTC). */
  createdAt: string;
  /**
   * Recovery-point marker: the timestamp of the newest event/row captured (ISO 8601). The gap
   * between this and the next backup bounds the achievable RPO. Null when unknown (e.g. full
   * pg_dump with no event scan).
   */
  rpoMarker: string | null;
  /** Artifact filename (relative to the manifest). */
  artifact: string;
  /** Size of the artifact on disk, in bytes. */
  sizeBytes: number;
  /** SHA-256 (hex) of the artifact bytes for integrity verification. */
  sha256: string;
  /** Whether the artifact is AES-256-GCM encrypted. */
  encrypted: boolean;
  /** Per-table row counts for logical exports. */
  tableCounts: TableCounts;
};

/** Hex SHA-256 of a buffer — used for artifact integrity in manifests. */
export function sha256(buf: Buffer): string {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

export type BuildManifestInput = {
  id: string;
  kind: BackupKind;
  tenant?: string | null;
  project?: string | null;
  createdAt: string;
  rpoMarker?: string | null;
  artifact: string;
  artifactBytes: Buffer;
  encrypted: boolean;
  tableCounts?: TableCounts;
};

/** Build a manifest object from a finished artifact (computes size + checksum). */
export function buildManifest(input: BuildManifestInput): BackupManifest {
  return {
    manifestVersion: MANIFEST_VERSION,
    id: input.id,
    kind: input.kind,
    tenant: input.tenant ?? null,
    project: input.project ?? null,
    createdAt: input.createdAt,
    rpoMarker: input.rpoMarker ?? null,
    artifact: input.artifact,
    sizeBytes: input.artifactBytes.length,
    sha256: sha256(input.artifactBytes),
    encrypted: input.encrypted,
    tableCounts: input.tableCounts ?? {},
  };
}

/** Serialize a manifest to pretty JSON with a trailing newline. */
export function serializeManifest(manifest: BackupManifest): string {
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

/** Parse and validate manifest JSON, raising a friendly CliError on malformed input. */
export function parseManifest(json: string): BackupManifest {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    throw new CliError("Backup manifest is not valid JSON.");
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new CliError("Backup manifest must be a JSON object.");
  }
  const m = raw as Record<string, unknown>;
  const required = ["id", "kind", "createdAt", "artifact", "sha256"] as const;
  for (const key of required) {
    if (typeof m[key] !== "string" || (m[key] as string) === "") {
      throw new CliError(`Backup manifest is missing required field "${key}".`);
    }
  }
  if (m.kind !== "full" && m.kind !== "tenant" && m.kind !== "project") {
    throw new CliError(`Backup manifest has unknown kind "${String(m.kind)}".`);
  }
  return {
    manifestVersion: typeof m.manifestVersion === "number" ? m.manifestVersion : MANIFEST_VERSION,
    id: m.id as string,
    kind: m.kind,
    tenant: typeof m.tenant === "string" ? m.tenant : null,
    project: typeof m.project === "string" ? m.project : null,
    createdAt: m.createdAt as string,
    rpoMarker: typeof m.rpoMarker === "string" ? m.rpoMarker : null,
    artifact: m.artifact as string,
    sizeBytes: typeof m.sizeBytes === "number" ? m.sizeBytes : 0,
    sha256: m.sha256 as string,
    encrypted: Boolean(m.encrypted),
    tableCounts:
      typeof m.tableCounts === "object" && m.tableCounts !== null
        ? (m.tableCounts as TableCounts)
        : {},
  };
}

/** Verify an artifact's bytes match the checksum recorded in its manifest. */
export function verifyArtifactIntegrity(manifest: BackupManifest, artifactBytes: Buffer): boolean {
  return sha256(artifactBytes) === manifest.sha256;
}

import type pg from "pg";

import { CliError } from "../errors.js";
import { isUndefinedColumn, isUniqueViolation, resolveTenant, resolveUser } from "../db.js";
import { note, printRecord, printRows, type OutputMode } from "../output.js";
import { apiKeyPrefix, generateApiKey, hashApiKey } from "../secrets.js";
import { confirmDestructive, isUuid } from "../util.js";

/** Allowed workspace API key scopes (CTG-2.3 / #4473). */
export const API_KEY_SCOPE_VOCAB = new Set(["*", "diff:read", "lint:read"]);

/**
 * Normalize and validate a scopes list for insert.
 *
 * @param raw - Caller-supplied scopes (comma-separated string or array). Empty → `['*']`.
 * @returns Non-empty scopes array suitable for ``api_keys.scopes``.
 */
export function normalizeApiKeyScopes(raw?: string | string[] | null): string[] {
  let parts: string[];
  if (raw == null || (Array.isArray(raw) && raw.length === 0) || raw === "") {
    parts = ["*"];
  } else if (typeof raw === "string") {
    parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
  } else {
    parts = raw.map((s) => String(s).trim()).filter(Boolean);
  }
  if (parts.length === 0) {
    parts = ["*"];
  }
  for (const s of parts) {
    if (!API_KEY_SCOPE_VOCAB.has(s)) {
      throw new CliError(
        `Invalid API key scope "${s}". Allowed: *, diff:read, lint:read.`,
      );
    }
  }
  if (parts.includes("*") && parts.length > 1) {
    throw new CliError(`Scope "*" must stand alone (got: ${parts.join(", ")}).`);
  }
  return [...new Set(parts)];
}

export type CreateApiKeyInput = {
  tenantRef: string;
  name: string;
  description?: string;
  expiresInDays?: number;
  createdByRef?: string;
  /** Machine-key scopes; default full access (`['*']`). */
  scopes?: string | string[] | null;
};

export async function createApiKey(
  client: pg.Client,
  input: CreateApiKeyInput,
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, input.tenantRef);
  const createdByUserId = input.createdByRef
    ? (await resolveUser(client, input.createdByRef)).id
    : null;
  const scopes = normalizeApiKeyScopes(input.scopes);

  let expiresAt: Date | null = null;
  if (input.expiresInDays !== undefined && input.expiresInDays > 0) {
    expiresAt = new Date(Date.now() + input.expiresInDays * 24 * 60 * 60 * 1000);
  }

  const apiKey = generateApiKey();
  const keyPrefix = apiKeyPrefix(apiKey);
  const keyHash = await hashApiKey(apiKey);

  let row: Record<string, unknown>;
  try {
    const res = await client.query(
      `INSERT INTO apiome.api_keys (tenant_id, name, description, key_hash, key_prefix, expires_at, created_by_user_id, scopes)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       RETURNING id, name, key_prefix, expires_at, scopes, created_at`,
      [tenant.id, input.name, input.description ?? null, keyHash, keyPrefix, expiresAt, createdByUserId, scopes],
    );
    row = res.rows[0] as Record<string, unknown>;
  } catch (err) {
    if (isUniqueViolation(err)) {
      throw new CliError(`An API key named "${input.name}" already exists for tenant ${tenant.slug}.`);
    }
    if (isUndefinedColumn(err)) {
      // Older DB without scopes and/or created_by_user_id — degrade gracefully.
      const msg = String(err).toLowerCase();
      if (msg.includes("scopes")) {
        note("Note: this database predates api_keys.scopes; creating a full-access key.");
      }
      if (createdByUserId && msg.includes("created_by_user_id")) {
        note("Note: this database predates created_by_user_id; ignoring --created-by.");
      }
      try {
        const res = await client.query(
          `INSERT INTO apiome.api_keys (tenant_id, name, description, key_hash, key_prefix, expires_at, created_by_user_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id, name, key_prefix, expires_at, created_at`,
          [tenant.id, input.name, input.description ?? null, keyHash, keyPrefix, expiresAt, createdByUserId],
        );
        row = res.rows[0] as Record<string, unknown>;
      } catch (err2) {
        if (isUndefinedColumn(err2)) {
          if (createdByUserId) {
            note("Note: this database predates created_by_user_id; ignoring --created-by.");
          }
          const res = await client.query(
            `INSERT INTO apiome.api_keys (tenant_id, name, description, key_hash, key_prefix, expires_at)
             VALUES ($1, $2, $3, $4, $5, $6)
             RETURNING id, name, key_prefix, expires_at, created_at`,
            [tenant.id, input.name, input.description ?? null, keyHash, keyPrefix, expiresAt],
          );
          row = res.rows[0] as Record<string, unknown>;
        } else {
          throw err2;
        }
      }
    } else {
      throw err;
    }
  }

  note("API key (shown once — copy it now, only the hash is stored):");
  process.stdout.write(`${apiKey}\n`);
  printRecord(mode, { ...row, tenant: tenant.slug });
}

export async function listApiKeys(
  client: pg.Client,
  tenantRef: string,
  opts: { all: boolean },
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, tenantRef);
  const where = opts.all ? "WHERE tenant_id = $1" : "WHERE tenant_id = $1 AND deleted_at IS NULL";
  let res;
  try {
    res = await client.query(
      `SELECT id, name, key_prefix, enabled, scopes, expires_at, last_used_at, created_at, deleted_at
       FROM apiome.api_keys ${where}
       ORDER BY created_at`,
      [tenant.id],
    );
  } catch (err) {
    if (!isUndefinedColumn(err)) throw err;
    res = await client.query(
      `SELECT id, name, key_prefix, enabled, expires_at, last_used_at, created_at, deleted_at
       FROM apiome.api_keys ${where}
       ORDER BY created_at`,
      [tenant.id],
    );
  }
  printRows(mode, res.rows as Record<string, unknown>[], [
    { key: "id", label: "ID" },
    { key: "name", label: "Name" },
    { key: "key_prefix", label: "Prefix" },
    { key: "enabled", label: "Enabled" },
    { key: "scopes", label: "Scopes" },
    { key: "expires_at", label: "Expires" },
    { key: "last_used_at", label: "Last used" },
  ]);
}

type ApiKeyRow = { id: string; name: string; key_prefix: string; tenant_id: string };

async function resolveApiKey(client: pg.Client, ref: string): Promise<ApiKeyRow> {
  const value = ref.trim();
  if (isUuid(value)) {
    const res = await client.query<ApiKeyRow>(
      "SELECT id, name, key_prefix, tenant_id FROM apiome.api_keys WHERE id = $1",
      [value],
    );
    const row = res.rows[0];
    if (!row) throw new CliError(`API key not found: ${ref}`);
    return row;
  }
  // Accept either the stored prefix ("sk_abcd1234...") or the raw first 12 chars ("sk_abcd1234").
  const candidates = value.endsWith("...") ? [value] : [value, `${value}...`];
  const res = await client.query<ApiKeyRow>(
    "SELECT id, name, key_prefix, tenant_id FROM apiome.api_keys WHERE key_prefix = ANY($1)",
    [candidates],
  );
  if (res.rows.length === 0) throw new CliError(`API key not found: ${ref}`);
  if (res.rows.length > 1) {
    throw new CliError(`Ambiguous API key reference "${ref}" — pass the key id instead.`);
  }
  return res.rows[0] as ApiKeyRow;
}

export async function revokeApiKey(
  client: pg.Client,
  ref: string,
  opts: { hard: boolean; yes: boolean },
  mode: OutputMode,
): Promise<void> {
  const key = await resolveApiKey(client, ref);
  const action = opts.hard ? "HARD-DELETE (permanent)" : "revoke (disable)";
  const ok = await confirmDestructive(`${action} API key "${key.name}" (${key.key_prefix})?`, opts.yes);
  if (!ok) {
    note("Aborted.");
    return;
  }
  if (opts.hard) {
    await client.query("DELETE FROM apiome.api_keys WHERE id = $1", [key.id]);
  } else {
    await client.query(
      "UPDATE apiome.api_keys SET enabled = false, deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = $1",
      [key.id],
    );
  }
  printRecord(mode, { id: key.id, name: key.name, key_prefix: key.key_prefix, revoked: opts.hard ? "hard" : "soft" });
}

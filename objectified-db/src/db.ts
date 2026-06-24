/**
 * Direct PostgreSQL access for the admin CLI. No REST involved — the operator supplies DB
 * credentials and we talk to the `odb` schema straight over a connection. All table references
 * are schema-qualified (`odb.*`) to match `objectified-rest`.
 */

import pg from "pg";

import { CliError } from "./errors.js";
import { isUuid } from "./util.js";

export type ConnectionOptions = {
  databaseUrl?: string;
  host?: string;
  port?: string;
  user?: string;
  password?: string;
  database?: string;
};

export function buildPgConfig(opts: ConnectionOptions): pg.ClientConfig {
  const url = opts.databaseUrl ?? process.env.OBJECTIFIED_DB_URL ?? process.env.DATABASE_URL;
  if (url && url.trim() !== "") {
    return { connectionString: url.trim() };
  }
  const passwordRaw = opts.password ?? process.env.POSTGRES_PASSWORD;
  return {
    host: opts.host ?? process.env.POSTGRES_HOST ?? "localhost",
    port: Number(opts.port ?? process.env.POSTGRES_PORT ?? "5432"),
    user: opts.user ?? process.env.POSTGRES_USER ?? "postgres",
    password: passwordRaw === undefined || passwordRaw === "" ? undefined : passwordRaw,
    database: opts.database ?? process.env.POSTGRES_DB ?? "objectified",
  };
}

/** Human-readable target (no secrets) for status output / errors. */
export function describeConnection(opts: ConnectionOptions): string {
  const url = opts.databaseUrl ?? process.env.OBJECTIFIED_DB_URL ?? process.env.DATABASE_URL;
  if (url && url.trim() !== "") {
    try {
      const u = new URL(url.trim());
      return `${u.hostname}:${u.port || "5432"}/${u.pathname.replace(/^\//, "") || "objectified"}`;
    } catch {
      return "(database url)";
    }
  }
  const cfg = buildPgConfig(opts);
  return `${String(cfg.host)}:${String(cfg.port)}/${String(cfg.database)} (user ${String(cfg.user)})`;
}

/** Open a connection, run `fn`, always close. Connection failures surface as friendly CliErrors. */
export async function withClient<T>(
  opts: ConnectionOptions,
  fn: (client: pg.Client) => Promise<T>,
): Promise<T> {
  const client = new pg.Client(buildPgConfig(opts));
  try {
    await client.connect();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`Could not connect to the database (${describeConnection(opts)}): ${message}`, {
      hint: "Set OBJECTIFIED_DB_URL / POSTGRES_* env vars or pass --database-url (or --host/--user/...).",
      exitCode: 2,
    });
  }
  try {
    return await fn(client);
  } finally {
    await client.end();
  }
}

export type TenantRow = { id: string; slug: string; name: string };
export type UserRow = { id: string; email: string; name: string };

/** Resolve a tenant by UUID or slug (active rows only). */
export async function resolveTenant(client: pg.Client, ref: string): Promise<TenantRow> {
  const value = ref.trim();
  const query = isUuid(value)
    ? "SELECT id, slug, name FROM odb.tenants WHERE id = $1 AND deleted_at IS NULL"
    : "SELECT id, slug, name FROM odb.tenants WHERE slug = $1 AND deleted_at IS NULL";
  const res = await client.query<TenantRow>(query, [value]);
  const row = res.rows[0];
  if (!row) throw new CliError(`Tenant not found: ${ref}`);
  return row;
}

/** Resolve a user by UUID or email (active rows only). */
export async function resolveUser(client: pg.Client, ref: string): Promise<UserRow> {
  const value = ref.trim();
  const query = isUuid(value)
    ? "SELECT id, email, name FROM odb.users WHERE id = $1 AND deleted_at IS NULL"
    : "SELECT id, email, name FROM odb.users WHERE email = $1 AND deleted_at IS NULL";
  const res = await client.query<UserRow>(query, [value]);
  const row = res.rows[0];
  if (!row) throw new CliError(`User not found: ${ref}`);
  return row;
}

/** Postgres unique-violation SQLSTATE. */
export function isUniqueViolation(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: string }).code === "23505";
}

/** Postgres undefined-column SQLSTATE (used for created_by_user_id back-compat). */
export function isUndefinedColumn(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: string }).code === "42703";
}

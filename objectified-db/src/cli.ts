#!/usr/bin/env node
/**
 * objectified-db — direct-to-database admin CLI.
 *
 * Performs privileged operations (create users/tenants, assign membership, mint API keys)
 * straight against PostgreSQL, deliberately bypassing the REST API. It requires database
 * credentials and is intended for operators / break-glass use only.
 */

import { homedir } from "node:os";
import { join } from "node:path";

import { Command, CommanderError } from "commander";

import { runInteractiveRepl } from "./lib/interactive/repl.js";
import * as apikeys from "./commands/apikeys.js";
import * as migrate from "./commands/migrate.js";
import * as tenants from "./commands/tenants.js";
import * as users from "./commands/users.js";
import { type ConnectionOptions, describeConnection, withClient } from "./db.js";
import { CliError } from "./errors.js";
import { note, printRecord, type OutputMode } from "./output.js";
import { generatePassword } from "./secrets.js";
import { readLineFromStdin, slugify } from "./util.js";

type GlobalOpts = ConnectionOptions & { json?: boolean; yes?: boolean };

function connectionOf(opts: GlobalOpts): ConnectionOptions {
  return {
    databaseUrl: opts.databaseUrl,
    host: opts.host,
    port: opts.port,
    user: opts.user,
    password: opts.password,
    database: opts.database,
  };
}

function modeOf(opts: GlobalOpts): OutputMode {
  return { json: Boolean(opts.json) };
}

type PasswordOpts = { password?: string; passwordStdin?: boolean; randomPassword?: boolean };

async function resolvePassword(opts: PasswordOpts): Promise<users.PasswordInput> {
  const provided = [
    opts.password !== undefined,
    Boolean(opts.passwordStdin),
    Boolean(opts.randomPassword),
  ].filter(Boolean).length;
  if (provided > 1) {
    throw new CliError("Use only one of --password, --password-stdin, or --random-password.");
  }
  if (opts.randomPassword) {
    return { plaintext: generatePassword(), generated: true };
  }
  if (opts.passwordStdin) {
    const line = (await readLineFromStdin()).trim();
    if (line === "") throw new CliError("No password received on stdin.");
    return { plaintext: line, generated: false };
  }
  if (opts.password !== undefined && opts.password !== "") {
    return { plaintext: opts.password, generated: false };
  }
  throw new CliError("A password is required.", {
    hint: "Pass --password <pw>, --password-stdin, or --random-password.",
  });
}

function parseExpiresDays(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const n = Number(value);
  if (!Number.isInteger(n) || n <= 0) {
    throw new CliError(`--expires-days must be a positive integer (got "${value}").`);
  }
  return n;
}

function buildProgram(interactive: boolean): Command {
  const program = new Command();

  // In the REPL each command line builds a fresh program (so option state never
  // leaks between lines); surface parse/help/version as thrown errors for the
  // caller to handle instead of letting Commander call process.exit().
  if (interactive) program.exitOverride();

program
  .name("objectified-db")
  .description("Direct-to-database admin CLI for Objectified (bypasses REST; needs DB credentials).")
  .version("0.1.0")
  .showHelpAfterError();

// Connection + output globals (each also reads env: OBJECTIFIED_DB_URL/DATABASE_URL or POSTGRES_*).
program
  .option("--database-url <url>", "Postgres connection string (env: OBJECTIFIED_DB_URL / DATABASE_URL)")
  .option("--host <host>", "DB host (env: POSTGRES_HOST; default localhost)")
  .option("--port <port>", "DB port (env: POSTGRES_PORT; default 5432)")
  .option("--user <user>", "DB user (env: POSTGRES_USER; default postgres)")
  .option("--password <password>", "DB password (env: POSTGRES_PASSWORD)")
  .option("--database <database>", "DB name (env: POSTGRES_DB; default objectified)")
  .option("--json", "Emit JSON instead of tables", false)
  .option("-y, --yes", "Skip confirmation prompts (required for destructive ops without a TTY)", false);

program
  .command("ping")
  .description("Verify the database connection")
  .action(async (_opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), async (client) => {
      await client.query("SELECT 1");
      printRecord(modeOf(g), { status: "ok", target: describeConnection(connectionOf(g)) });
    });
  });

const migrateCmd = program
  .command("migrate")
  .description("Apply pending Flyway migrations (V*__*.sql) from scripts/ (flyway_schema_history)")
  .option("--scripts-dir <path>", "Directory containing V*__*.sql migrations (default: package scripts/)")
  .option("--dry-run", "Print pending scripts without applying them", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      migrate.runMigrateApply(
        client,
        { scriptsDir: opts.scriptsDir, dryRun: Boolean(opts.dryRun) },
        modeOf(g),
      ),
    );
  });

migrateCmd
  .command("status")
  .description("List applied and pending migration scripts")
  .option("--scripts-dir <path>", "Directory containing V*__*.sql migrations (default: package scripts/)")
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      migrate.runMigrateStatus(
        client,
        { scriptsDir: opts.scriptsDir },
        modeOf(g),
      ),
    );
  });

program
  .command("repair")
  .description("Realign flyway_schema_history checksums to the current files and drop failed rows")
  .option("--scripts-dir <path>", "Directory containing V*__*.sql migrations (default: package scripts/)")
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      migrate.runRepair(client, { scriptsDir: opts.scriptsDir }, modeOf(g)),
    );
  });

program
  .command("clean")
  .description("Drop the odb schema and migration history (destructive; disabled by default)")
  .option("--force", "Override FLYWAY_CLEAN_DISABLED / NODE_ENV=production guards", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      migrate.runClean(client, { yes: Boolean(g.yes), force: Boolean(opts.force) }, modeOf(g)),
    );
  });

program
  .command("seed")
  .description("Load dev seed data (sample user/tenant/license/API key) — development only")
  .option("--dir <path>", "Seed directory of *.sql files (default: package seed/dev/)")
  .option("--dry-run", "List seed files without applying them", false)
  .option("--force", "Allow seeding even when NODE_ENV=production", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      migrate.runSeed(
        client,
        { seedDir: opts.dir, dryRun: Boolean(opts.dryRun), force: Boolean(opts.force) },
        modeOf(g),
      ),
    );
  });

// ───────────────────────────── users ─────────────────────────────
const usersCmd = program.command("users").description("Create and manage users");

usersCmd
  .command("create")
  .description("Create a user")
  .requiredOption("--name <name>", "Full name")
  .requiredOption("--email <email>", "Email address (used to log in)")
  .option("--password <password>", "Password (visible in shell history — prefer --password-stdin)")
  .option("--password-stdin", "Read the password from stdin (one line)")
  .option("--random-password", "Generate a random password and print it once")
  .option("--unverified", "Mark the user email as not verified", false)
  .option("--disabled", "Create the user in a disabled state", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    const password = await resolvePassword(opts);
    await withClient(connectionOf(g), (client) =>
      users.createUser(
        client,
        {
          name: opts.name,
          email: opts.email,
          password,
          verified: !opts.unverified,
          enabled: !opts.disabled,
        },
        modeOf(g),
      ),
    );
  });

usersCmd
  .command("list")
  .description("List users")
  .option("--all", "Include disabled and soft-deleted users", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      users.listUsers(client, { all: Boolean(opts.all) }, modeOf(g)),
    );
  });

usersCmd
  .command("set-password <user>")
  .description("Set a user's password (user = email or id)")
  .option("--password <password>", "New password (prefer --password-stdin)")
  .option("--password-stdin", "Read the new password from stdin (one line)")
  .option("--random-password", "Generate a random password and print it once")
  .action(async (user: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    const password = await resolvePassword(opts);
    await withClient(connectionOf(g), (client) =>
      users.setUserPassword(client, user, password, modeOf(g)),
    );
  });

usersCmd
  .command("delete <user>")
  .description("Soft-delete (disable) a user; --hard removes the row (user = email or id)")
  .option("--hard", "Permanently delete instead of soft-deleting", false)
  .action(async (user: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      users.deleteUser(client, user, { hard: Boolean(opts.hard), yes: Boolean(g.yes) }, modeOf(g)),
    );
  });

// ──────────────────────────── tenants ────────────────────────────
const tenantsCmd = program.command("tenants").description("Create and manage tenants and membership");

tenantsCmd
  .command("create")
  .description("Create a tenant")
  .requiredOption("--name <name>", "Display name")
  .option("--slug <slug>", "URL slug (lowercase-hyphenated; derived from --name if omitted)")
  .option("--description <description>", "Optional description")
  .option("--disabled", "Create the tenant in a disabled state", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    const slug = typeof opts.slug === "string" && opts.slug.trim() !== "" ? opts.slug.trim() : slugify(opts.name);
    await withClient(connectionOf(g), (client) =>
      tenants.createTenant(
        client,
        { name: opts.name, slug, description: opts.description, enabled: !opts.disabled },
        modeOf(g),
      ),
    );
  });

tenantsCmd
  .command("list")
  .description("List tenants")
  .option("--all", "Include disabled and soft-deleted tenants", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      tenants.listTenants(client, { all: Boolean(opts.all) }, modeOf(g)),
    );
  });

tenantsCmd
  .command("delete <tenant>")
  .description("Soft-delete (disable) a tenant; --hard removes the row (tenant = slug or id)")
  .option("--hard", "Permanently delete (cascades members & API keys)", false)
  .action(async (tenant: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      tenants.deleteTenant(client, tenant, { hard: Boolean(opts.hard), yes: Boolean(g.yes) }, modeOf(g)),
    );
  });

tenantsCmd
  .command("add-user <tenant> <user>")
  .description("Assign a user to a tenant (tenant = slug/id, user = email/id)")
  .option("--admin", "Also grant tenant administrator role", false)
  .action(async (tenant: string, user: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      tenants.addUserToTenant(client, tenant, user, { admin: Boolean(opts.admin) }, modeOf(g)),
    );
  });

tenantsCmd
  .command("remove-user <tenant> <user>")
  .description("Remove a user from a tenant (or just revoke admin with --admin-only)")
  .option("--admin-only", "Only revoke the administrator role; keep membership", false)
  .action(async (tenant: string, user: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      tenants.removeUserFromTenant(
        client,
        tenant,
        user,
        { adminOnly: Boolean(opts.adminOnly), yes: Boolean(g.yes) },
        modeOf(g),
      ),
    );
  });

tenantsCmd
  .command("members <tenant>")
  .description("List a tenant's members and their admin flag")
  .action(async (tenant: string, _opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      tenants.listTenantMembers(client, tenant, modeOf(g)),
    );
  });

// ──────────────────────────── api-keys ───────────────────────────
const apiKeysCmd = program
  .command("api-keys")
  .alias("apikeys")
  .description("Mint and manage tenant API keys");

apiKeysCmd
  .command("create")
  .description("Create an API key for a tenant (the key is printed once)")
  .requiredOption("--tenant <tenant>", "Tenant slug or id")
  .requiredOption("--name <name>", "Key name (unique within the tenant)")
  .option("--description <description>", "Optional description")
  .option("--expires-days <days>", "Expire the key after N days (default: never)")
  .option("--created-by <user>", "Attribute creation to a user (email or id)")
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    const expiresInDays = parseExpiresDays(opts.expiresDays);
    await withClient(connectionOf(g), (client) =>
      apikeys.createApiKey(
        client,
        {
          tenantRef: opts.tenant,
          name: opts.name,
          description: opts.description,
          expiresInDays,
          createdByRef: opts.createdBy,
        },
        modeOf(g),
      ),
    );
  });

apiKeysCmd
  .command("list")
  .description("List a tenant's API keys (never shows the secret)")
  .requiredOption("--tenant <tenant>", "Tenant slug or id")
  .option("--all", "Include disabled and soft-deleted keys", false)
  .action(async (opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      apikeys.listApiKeys(client, opts.tenant, { all: Boolean(opts.all) }, modeOf(g)),
    );
  });

apiKeysCmd
  .command("revoke <key>")
  .description("Revoke (disable) an API key; --hard removes the row (key = id or prefix)")
  .option("--hard", "Permanently delete instead of disabling", false)
  .action(async (key: string, opts, cmd: Command) => {
    const g = cmd.optsWithGlobals() as GlobalOpts;
    await withClient(connectionOf(g), (client) =>
      apikeys.revokeApiKey(client, key, { hard: Boolean(opts.hard), yes: Boolean(g.yes) }, modeOf(g)),
    );
  });

// ──────────────────────── interactive (REPL) ─────────────────────
program
  .command("interactive")
  .alias("repl")
  .description("Start an interactive session (also the default when run with no command)")
  .action(async () => {
    await startRepl();
  });

  return program;
}

function reportError(err: unknown): void {
  if (err instanceof CliError) {
    note(`objectified-db: ${err.message}`);
    if (err.hint) note(`  hint: ${err.hint}`);
    return;
  }
  const message = err instanceof Error ? err.message : String(err);
  note(`objectified-db: ${message}`);
}

/** Execute one REPL command line in a fresh program; never exits the process. */
async function executeLine(argv: string[]): Promise<void> {
  try {
    await buildProgram(true).parseAsync(argv, { from: "user" });
  } catch (err) {
    // Commander already wrote help/version to stdout and parse errors to stderr.
    if (err instanceof CommanderError) return;
    reportError(err);
  }
}

async function startRepl(): Promise<void> {
  const color =
    Boolean(process.stdout.isTTY) &&
    (process.env.NO_COLOR === undefined || process.env.NO_COLOR === "");
  await runInteractiveRepl({
    binName: "objectified-db",
    versionLabel: "0.1.0",
    input: process.stdin,
    output: process.stdout,
    errorOutput: process.stderr,
    isTTY: Boolean(process.stdin.isTTY),
    color,
    execute: executeLine,
    historyFile: join(homedir(), ".objectified-db", "history"),
  });
}

async function main(): Promise<void> {
  // Run with no command → interactive session (TTY) or batch from stdin (pipe).
  if (process.argv.slice(2).length === 0) {
    await startRepl();
    return;
  }
  await buildProgram(false).parseAsync(process.argv);
}

main().catch((err: unknown) => {
  reportError(err);
  process.exit(err instanceof CliError ? err.exitCode : 1);
});

import type pg from "pg";

import { CliError } from "../errors.js";
import { isUniqueViolation, resolveUser } from "../db.js";
import { note, printRecord, printRows, type OutputMode } from "../output.js";
import { hashPassword } from "../secrets.js";
import { confirmDestructive, isValidEmail } from "../util.js";

export type PasswordInput = { plaintext: string; generated: boolean };

export type CreateUserInput = {
  name: string;
  email: string;
  password: PasswordInput;
  verified: boolean;
  enabled: boolean;
};

export async function createUser(
  client: pg.Client,
  input: CreateUserInput,
  mode: OutputMode,
): Promise<void> {
  if (!isValidEmail(input.email)) {
    throw new CliError(`Invalid email: ${input.email}`);
  }
  const passwordHash = await hashPassword(input.password.plaintext);
  try {
    const res = await client.query(
      `INSERT INTO apiome.users (name, email, password, verified, enabled)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, name, email, verified, enabled, created_at`,
      [input.name, input.email.trim(), passwordHash, input.verified, input.enabled],
    );
    const row = res.rows[0] as Record<string, unknown>;
    if (input.password.generated) {
      note("Generated password (store it now — it is not recoverable):");
      process.stdout.write(`${input.password.plaintext}\n`);
    }
    printRecord(mode, row);
  } catch (err) {
    if (isUniqueViolation(err)) {
      throw new CliError(`A user with email ${input.email} already exists.`);
    }
    throw err;
  }
}

export async function listUsers(
  client: pg.Client,
  opts: { all: boolean },
  mode: OutputMode,
): Promise<void> {
  const where = opts.all ? "" : "WHERE deleted_at IS NULL";
  const res = await client.query(
    `SELECT id, email, name, verified, enabled, created_at, deleted_at
     FROM apiome.users ${where}
     ORDER BY created_at`,
  );
  printRows(mode, res.rows as Record<string, unknown>[], [
    { key: "id", label: "ID" },
    { key: "email", label: "Email" },
    { key: "name", label: "Name" },
    { key: "verified", label: "Verified" },
    { key: "enabled", label: "Enabled" },
    { key: "created_at", label: "Created" },
  ]);
}

export async function setUserPassword(
  client: pg.Client,
  ref: string,
  password: PasswordInput,
  mode: OutputMode,
): Promise<void> {
  const user = await resolveUser(client, ref);
  const passwordHash = await hashPassword(password.plaintext);
  await client.query(
    "UPDATE apiome.users SET password = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
    [passwordHash, user.id],
  );
  if (password.generated) {
    note("Generated password (store it now — it is not recoverable):");
    process.stdout.write(`${password.plaintext}\n`);
  }
  printRecord(mode, { id: user.id, email: user.email, updated: true });
}

export async function deleteUser(
  client: pg.Client,
  ref: string,
  opts: { hard: boolean; yes: boolean },
  mode: OutputMode,
): Promise<void> {
  const user = await resolveUser(client, ref);
  const action = opts.hard ? "HARD-DELETE (permanent)" : "soft-delete (disable)";
  const ok = await confirmDestructive(`${action} user ${user.email} (${user.id})?`, opts.yes);
  if (!ok) {
    note("Aborted.");
    return;
  }
  if (opts.hard) {
    await client.query("DELETE FROM apiome.users WHERE id = $1", [user.id]);
  } else {
    await client.query(
      "UPDATE apiome.users SET deleted_at = CURRENT_TIMESTAMP, enabled = false, updated_at = CURRENT_TIMESTAMP WHERE id = $1",
      [user.id],
    );
  }
  printRecord(mode, { id: user.id, email: user.email, deleted: opts.hard ? "hard" : "soft" });
}

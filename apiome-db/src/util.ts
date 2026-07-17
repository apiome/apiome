import readline from "node:readline/promises";

import { CliError } from "./errors.js";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value.trim());
}

export function isValidSlug(value: string): boolean {
  return SLUG_RE.test(value);
}

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/**
 * Canonicalize an email address to the single form the database stores and indexes: trimmed and
 * lower-cased. Every read and write path must funnel through this so `Ada@Example.com` and
 * `ada@example.com` resolve to one account (OLO-1.1, #4186).
 */
export function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

/** Lowercase, hyphenate, trim — the same shape tenant slugs take elsewhere. */
export function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Confirm a destructive action. Returns true to proceed.
 * `--yes` short-circuits; without a TTY (and without `--yes`) we refuse rather than hang.
 */
export async function confirmDestructive(message: string, yes: boolean): Promise<boolean> {
  if (yes) return true;
  if (!process.stdin.isTTY) {
    throw new CliError(`Refusing destructive action without confirmation: ${message}`, {
      hint: "Re-run with --yes to proceed non-interactively.",
    });
  }
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  try {
    const answer = (await rl.question(`${message} [y/N] `)).trim().toLowerCase();
    return answer === "y" || answer === "yes";
  } finally {
    rl.close();
  }
}

/** Read a single line from stdin (used by `--password-stdin`). */
export function readLineFromStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    process.stdin.on("data", (d: string | Buffer) => {
      chunks.push(typeof d === "string" ? Buffer.from(d) : d);
    });
    process.stdin.on("end", () => {
      resolve(Buffer.concat(chunks).toString("utf8").split(/\r?\n/)[0] ?? "");
    });
    process.stdin.on("error", reject);
  });
}

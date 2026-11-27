/**
 * The model behind **The same, from anywhere** — `CommandBlock` (PFX-8.2, #7299).
 *
 * A screen that does something shows the same action as a command on each surface a pipeline uses
 * (for Contracts: `apiome pact`, Pact CLI, the GitHub Action and REST), built from what the form
 * holds right now. This module is the surface-agnostic part: the surface shape, shell quoting, and
 * the two guards that keep a secret out of anything the block prints or copies.
 *
 * **Secrets are never printed.** A value the form marks as secret is written as an environment
 * variable reference (`"$WEBHOOK_PASSWORD"`) by the builder that knows it is secret; and every
 * surface's text then goes through {@link scrubSecrets}, which replaces anything shaped like a
 * credential (an `Authorization` value, a GitHub or Apiome token, a JWT) that slipped through, so a
 * header someone typed by hand is caught too.
 */

/** One surface the block offers, as a pill. */
export interface CommandSurface {
  /** Stable id, e.g. `apiome`; the pill's value. */
  id: string;
  /** What the pill reads, e.g. `Pact CLI`. */
  label: string;
  /** The text shown and copied, or `null` when this surface cannot do the action. */
  text: string | null;
  /** Why the surface cannot do it (when `text` is `null`), never empty. */
  unavailable?: string;
  /** Short notes under the text: what this surface leaves out, or how it differs. */
  notes?: string[];
}

/** What the scrubber writes in place of a credential it found. */
export const SCRUBBED = '<redacted>';

/**
 * Names that hold a credential: a header, a field or an option named like this is secret.
 * Matched case-insensitively against the whole name.
 */
const SECRET_NAME = /(passw(or)?d|passphrase|secret|token|authorization|api[-_]?key|cookie|credential|private[-_]?key)/i;

/**
 * Whether a header, field or option name holds a credential.
 *
 * @param name - E.g. `Authorization`, `signingSecret`, `X-API-Key`.
 * @returns `true` for a name that must never be printed with its value.
 */
export function isSecretName(name: string): boolean {
  return SECRET_NAME.test(name);
}

/**
 * Credential shapes {@link scrubSecrets} replaces, with what each keeps (its prefix).
 * Each pattern's first group is kept; the rest is replaced.
 */
const CREDENTIAL_PATTERNS: readonly RegExp[] = [
  // An HTTP auth scheme and its value: `Bearer abc…`, `Basic dXNl…`, `Token abc…`.
  /(\b(?:Bearer|Basic|Token|Digest)\s+)[A-Za-z0-9._~+/=-]{8,}/g,
  // GitHub tokens.
  /()\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g,
  // Apiome API keys.
  /()\bapiome_[A-Za-z0-9_-]{16,}\b/g,
  // JSON Web Tokens.
  /()\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
  // `user:password@` in a URL.
  /(\/\/[^/\s:@]+:)[^@\s/]+(?=@)/g,
];

/**
 * Replace anything shaped like a credential with {@link SCRUBBED}.
 *
 * The last line of defence: builders write secrets as variable references already, so this only
 * fires on a value a person typed somewhere a builder did not expect one.
 *
 * @param text - A surface's text.
 * @returns The text with every credential-shaped run replaced.
 */
export function scrubSecrets(text: string): string {
  return CREDENTIAL_PATTERNS.reduce((out, pattern) => out.replace(pattern, (_match, keep: string) => `${keep}${SCRUBBED}`), text);
}

/**
 * Replace the value of every secret-named field of a JSON value (deeply) with a variable reference.
 *
 * @param value - A request body.
 * @param reference - The text to write for a secret field, given its name (e.g. `$WEBHOOK_PASSWORD`).
 * @returns A copy with every secret value replaced; non-secret values as they were.
 */
export function redactSecretFields(value: unknown, reference: (name: string) => string): unknown {
  if (Array.isArray(value)) return value.map((item) => redactSecretFields(item, reference));
  if (value === null || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([name, field]) => [
      name,
      isSecretName(name) && field !== null && field !== undefined && field !== '' ? reference(name) : redactSecretFields(field, reference),
    ]),
  );
}

/** A word the shell reads as itself, unquoted. */
const SAFE_WORD = /^[A-Za-z0-9_@%+=:,./-]+$/;

/**
 * Quote a value for a POSIX shell.
 *
 * @param value - Any text.
 * @returns The value bare when it is safe, otherwise single-quoted (`'` written as `'\''`);
 *   `''` for an empty value.
 */
export function shellQuote(value: string): string {
  if (value === '') return "''";
  if (SAFE_WORD.test(value)) return value;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * A double-quoted shell word that expands one variable: `"Authorization: $WEBHOOK_AUTHORIZATION"`.
 *
 * @param prefix - Literal text before the variable (escaped for double quotes).
 * @param variable - The variable's name, e.g. `WEBHOOK_PASSWORD`.
 * @returns The word.
 */
export function shellVariable(prefix: string, variable: string): string {
  return `"${prefix.replace(/(["\\$`])/g, '\\$1')}$${variable}"`;
}

/**
 * An environment variable name from any label: `X-API-Key` → `X_API_KEY`.
 *
 * @param label - A header or field name.
 * @param prefix - Put in front, e.g. `WEBHOOK_`.
 * @returns Upper snake case, never starting with a digit.
 */
export function variableName(label: string, prefix = ''): string {
  const snake = label
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
  const name = `${prefix}${snake || 'SECRET'}`;
  return /^[0-9]/.test(name) ? `_${name}` : name;
}

/**
 * Lay a command out one argument per line, joined with ` \`.
 *
 * @param head - The command and its positional arguments, e.g. `apiome pact publish pacts/`.
 * @param args - Each option with its value, already quoted, e.g. `--branch main`.
 * @returns The command; one line when there are no options.
 */
export function shellLines(head: string, args: string[]): string {
  return [head, ...args.map((arg) => `  ${arg}`)].join(' \\\n');
}

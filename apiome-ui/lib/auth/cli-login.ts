/**
 * `apiome login` approve page — the pure parts (#5501).
 *
 * `apiome login` prints a short code (e.g. `KTXR-MWDB`) and opens `/cli/login?code=…`. The person
 * signs in, checks the code matches the terminal, picks a workspace and approves; the CLI then
 * receives a 14-day API key for that workspace. apiome-rest owns the flow
 * (`/v1/cli/login/requests/{code}` …); this module holds what the page needs without a network:
 * code normalization (mirrors `normalize_user_code` in `apiome-rest/src/app/cli_login.py`), the
 * sign-in redirect, and the workspace choice.
 *
 * Client-safe: no Node or database imports.
 */

/** The route of the approve page. */
export const CLI_LOGIN_PATH = '/cli/login';

/** How many days the key a CLI login hands out lasts (apiome-rest `CLI_LOGIN_KEY_TTL`). */
export const CLI_LOGIN_KEY_DAYS = 14;

/** A workspace the signed-in person belongs to, as apiome-rest describes it. */
export interface CliLoginWorkspace {
  slug: string;
  name: string;
  /** Whether the person holds `api_keys:create` there (and so may approve for it). */
  can_approve: boolean;
}

/** A pending login, as apiome-rest describes it. */
export interface CliLoginRequest {
  user_code: string;
  client_name: string | null;
  status: string;
  created_at: string;
  expires_at: string;
  workspaces: CliLoginWorkspace[];
}

/**
 * Canonicalize a code typed or pasted by a person.
 *
 * Case, spaces and the dash are forgiven: `ktxr mwdb` and `KTXRMWDB` are both `KTXR-MWDB`.
 *
 * @param raw The code as typed.
 * @returns `XXXX-XXXX`, or `null` when it cannot be a code.
 */
export function normalizeCliUserCode(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const compact = raw.replace(/[\s-]/g, '').toUpperCase();
  if (!/^[A-Z0-9]{8}$/.test(compact)) return null;
  return `${compact.slice(0, 4)}-${compact.slice(4)}`;
}

/**
 * The approve page's own URL, for the sign-in redirect's `callbackUrl`.
 *
 * @param code The canonical code, or `null` when the page was opened without one.
 * @returns A relative URL.
 */
export function cliLoginPagePath(code: string | null): string {
  return code ? `${CLI_LOGIN_PATH}?code=${encodeURIComponent(code)}` : CLI_LOGIN_PATH;
}

/**
 * The workspace the picker starts on: the current one when it may be approved for, else the
 * first that may.
 *
 * @param workspaces The person's workspaces.
 * @param currentSlug The workspace the person last worked in, if known.
 * @returns A slug, or `null` when no workspace may be approved for.
 */
export function defaultCliLoginWorkspace(
  workspaces: readonly CliLoginWorkspace[],
  currentSlug?: string | null
): string | null {
  const approvable = workspaces.filter((workspace) => workspace.can_approve);
  return approvable.find((workspace) => workspace.slug === currentSlug)?.slug ?? approvable[0]?.slug ?? null;
}

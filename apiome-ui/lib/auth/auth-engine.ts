/**
 * Auth-engine feature flag (OLO-10.2, migration design §4).
 *
 * The Better Auth migration runs both engines side by side behind a single flag so a deploy can
 * switch which one serves auth without a code change (parallel-run cutover — see
 * `docs/BETTER_AUTH_MIGRATION.md` §4). `AUTH_ENGINE` selects the live engine:
 *
 * - `next-auth`    — the existing NextAuth v4 stack (the default; unchanged behaviour).
 * - `better-auth`  — the new Better Auth stack mounted on the same `/api/auth/*` catch-all.
 *
 * Anything other than the exact string `better-auth` (unset, blank, typo) resolves to `next-auth`,
 * so the safe/legacy engine is always the fallback and the flag can never leave auth un-served.
 */

/** Value of `AUTH_ENGINE` that keeps the legacy NextAuth engine live (the default). */
export const AUTH_ENGINE_NEXT_AUTH = 'next-auth' as const;

/** Value of `AUTH_ENGINE` that switches the app onto the Better Auth engine. */
export const AUTH_ENGINE_BETTER_AUTH = 'better-auth' as const;

/** The two engines the flag can select between. */
export type AuthEngine = typeof AUTH_ENGINE_NEXT_AUTH | typeof AUTH_ENGINE_BETTER_AUTH;

/**
 * Resolve the active auth engine from the `AUTH_ENGINE` env var.
 *
 * Fails safe: only the exact literal `better-auth` selects Better Auth; every other value —
 * including unset or blank — resolves to `next-auth`.
 *
 * @returns The engine that should serve auth for this process.
 */
export function getAuthEngine(): AuthEngine {
  return process.env.AUTH_ENGINE?.trim() === AUTH_ENGINE_BETTER_AUTH
    ? AUTH_ENGINE_BETTER_AUTH
    : AUTH_ENGINE_NEXT_AUTH;
}

/**
 * Whether the Better Auth engine is the active one.
 *
 * @returns `true` when `AUTH_ENGINE=better-auth`, otherwise `false`.
 */
export function isBetterAuthEngine(): boolean {
  return getAuthEngine() === AUTH_ENGINE_BETTER_AUTH;
}

/**
 * Client-safe engine check for the browser session compat layer (OLO-10.12).
 *
 * `AUTH_ENGINE` is server-only; `next.config.ts` mirrors it into the build-time-inlined
 * `NEXT_PUBLIC_AUTH_ENGINE` so the browser can read it. Same fail-safe rule: only the literal
 * `better-auth` selects Better Auth. Usable from both client and server (on the server the public var
 * is present too), so the compat layer can call it without a `'use client'`/server split.
 *
 * @returns `true` when the app is running on the Better Auth engine, otherwise `false`.
 */
export function isBetterAuthEngineClient(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_ENGINE?.trim() === AUTH_ENGINE_BETTER_AUTH;
}

'use client';

/**
 * Engine-aware browser session layer (OLO-10.12, #5007).
 *
 * The single entry point the UI uses in place of `next-auth/react` — no component imports
 * `next-auth/react` any more. It presents the legacy `{ data, status, update }` shape (so component
 * bodies barely change) while dispatching to the right transport by engine (`NEXT_PUBLIC_AUTH_ENGINE`,
 * mirrored from `AUTH_ENGINE` by `next.config.ts`):
 *
 * - **better-auth** → `authClient.useSession()` for reads, `authClient.*` for mutations
 *   (`better-auth-client-compat.ts`).
 * - **next-auth** → plain fetches to NextAuth's own HTTP endpoints (`next-auth-client-compat.ts`), so
 *   the default engine keeps working in the browser with zero `next-auth/react` imports.
 *
 * The engine is a build-time constant, so `AuthSessionProvider` picks one concrete provider component
 * up front — each calls its own hooks unconditionally (no rules-of-hooks violation).
 *
 * `useAuthSession()` also exposes `signIn`/`signOut` helpers so callers never touch a transport
 * directly; `signIn`/`signOut` are also re-exported for the few non-hook call sites.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { isBetterAuthEngineClient } from './auth-engine';
import type { AppSession } from './better-auth-session-shape';
import { setActiveTenant } from './last-active-tenant-actions';
import { authClient } from './auth-client';
import {
  mapBetterAuthSession,
  signInBetterAuth,
  signOutBetterAuth,
  updateUserNameBetterAuth,
} from './better-auth-client-compat';
import {
  getNextAuthSession,
  signInNextAuth,
  signOutNextAuth,
  updateNextAuthSession,
} from './next-auth-client-compat';

/** Session status, mirroring NextAuth's `useSession().status`. */
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

/** Options accepted by {@link useAuthSession}'s `signIn`. */
export interface AuthSignInOptions {
  /** Where to land after a successful sign-in. */
  callbackUrl?: string;
  /** Credentials `payload` JSON blob (`{email,password}` or `{oneTimeCode}`); credentials only. */
  payload?: string;
  /**
   * Accepted for drop-in compatibility with `next-auth/react`'s `signIn`. The compat `signIn` always
   * navigates on completion, so this is ignored — it exists only so existing `{ redirect: true }` call
   * sites keep type-checking.
   */
  redirect?: boolean;
}

/** The `update()` payload — the same NextAuth session-arg shape the call sites already pass. */
export interface AuthUpdatePayload {
  /** Tenant switch (passed top-level by the tenant switcher / onboarding wizard). */
  current_tenant_id?: string;
  /** Display-name change (profile passes it under `user.name`). */
  name?: string;
  user?: { name?: string | null } & Record<string, unknown>;
  [key: string]: unknown;
}

interface AuthSessionContextValue {
  data: AppSession | null;
  status: AuthStatus;
  refetch: () => Promise<void>;
}

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);

/** Better Auth provider: reads the reactive `authClient.useSession()` store. */
function BetterAuthSessionProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const { data, isPending, refetch } = authClient.useSession();
  const session = useMemo(() => mapBetterAuthSession(data as never), [data]);
  const status: AuthStatus = isPending ? 'loading' : session ? 'authenticated' : 'unauthenticated';
  const value = useMemo<AuthSessionContextValue>(
    () => ({ data: session, status, refetch: async () => void (await refetch()) }),
    [session, status, refetch]
  );
  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

/** NextAuth provider: fetches `/api/auth/session` once and shares it, with on-demand refetch. */
function NextAuthSessionProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [data, setData] = useState<AppSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');
  const refetch = useCallback(async () => {
    const next = await getNextAuthSession();
    setData(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
  }, []);
  // Initial load: fetch the session once on mount. The state writes happen after the async fetch
  // resolves (and are skipped if the provider unmounted first), so this is an external-system
  // subscription rather than a synchronous setState-in-effect.
  useEffect(() => {
    let active = true;
    void (async () => {
      const next = await getNextAuthSession();
      if (!active) {
        return;
      }
      setData(next);
      setStatus(next ? 'authenticated' : 'unauthenticated');
    })();
    return () => {
      active = false;
    };
  }, []);
  const value = useMemo<AuthSessionContextValue>(
    () => ({ data, status, refetch }),
    [data, status, refetch]
  );
  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

/**
 * Provider for the engine-aware session — the replacement for NextAuth's `SessionProvider`.
 *
 * @param children The app subtree that consumes {@link useAuthSession}.
 */
export function AuthSessionProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  // Evaluated per render (the engine is a build-time constant in practice, so the chosen provider is
  // stable across renders); reading it here rather than at module load keeps the layer testable.
  return isBetterAuthEngineClient() ? (
    <BetterAuthSessionProvider>{children}</BetterAuthSessionProvider>
  ) : (
    <NextAuthSessionProvider>{children}</NextAuthSessionProvider>
  );
}

/**
 * Sign in on the active engine, navigating on completion (the `redirect: true` contract).
 *
 * @param provider `'credentials'` or an OAuth provider id.
 * @param options `callbackUrl` and, for credentials, the `payload` blob.
 */
export function signIn(provider: string, options: AuthSignInOptions = {}): Promise<void> {
  return isBetterAuthEngineClient()
    ? signInBetterAuth(provider, options)
    : signInNextAuth(provider, options);
}

/**
 * Sign out on the active engine and navigate to `callbackUrl`.
 *
 * @param callbackUrl Where to land after sign-out.
 */
export function signOut(callbackUrl: string): Promise<void> {
  return isBetterAuthEngineClient()
    ? signOutBetterAuth(callbackUrl)
    : signOutNextAuth(callbackUrl);
}

/**
 * The engine-aware replacement for `next-auth/react`'s `useSession()`.
 *
 * @returns `{ data, status, update, signIn, signOut }` — `data`/`status` mirror NextAuth; `update`
 *   persists a tenant switch (validated) or a name change on either engine; `signIn`/`signOut` are the
 *   engine-aware helpers.
 */
export function useAuthSession(): {
  data: AppSession | null;
  status: AuthStatus;
  update: (payload: AuthUpdatePayload) => Promise<void>;
  signIn: typeof signIn;
  signOut: typeof signOut;
} {
  const ctx = useContext(AuthSessionContext);
  if (!ctx) {
    throw new Error('useAuthSession must be used within <AuthSessionProvider>');
  }
  const { data, status, refetch } = ctx;

  const update = useCallback(
    async (payload: AuthUpdatePayload): Promise<void> => {
      const betterAuth = isBetterAuthEngineClient();

      // Tenant switch: passed top-level by the switcher / onboarding wizard. Persist through the
      // validated server action; the cookie is the source of truth for the derived tenant on either
      // engine, and NextAuth additionally needs its JWT refreshed so the change lands mid-session.
      const tenantId = typeof payload.current_tenant_id === 'string' ? payload.current_tenant_id : undefined;
      if (tenantId) {
        const validated = await setActiveTenant(tenantId);
        if (!betterAuth && validated) {
          await updateNextAuthSession({ current_tenant_id: validated });
        }
      }

      // Name change: profile passes it under `user.name` (NextAuth reads `session.user.name`).
      const name =
        (typeof payload.user?.name === 'string' ? payload.user.name : undefined) ??
        (typeof payload.name === 'string' ? payload.name : undefined);
      if (name) {
        if (betterAuth) {
          await updateUserNameBetterAuth(name);
        } else {
          await updateNextAuthSession({ user: { name } });
        }
      }

      await refetch();
    },
    [refetch]
  );

  return { data, status, update, signIn, signOut };
}

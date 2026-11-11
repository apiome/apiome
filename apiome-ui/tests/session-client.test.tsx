/**
 * Browser session layer tests for `lib/auth/session-client.tsx` (OLO-10.12 #5007; Better-Auth-only
 * since the OLO-10.14 cutover #5009).
 *
 * Assert the layer (a) exposes the legacy `{ data, status, update }` shape over Better Auth's reactive
 * client, and (b) routes `update`/`signIn`/`signOut` to the Better Auth transport — including the
 * validated tenant-switch persistence and the name-change update.
 *
 * The Better Auth transport, the reactive session hook, and the tenant-switch server action are mocked.
 */

import * as React from 'react';
import { renderHook, act } from '@testing-library/react';
import {
  useAuthSession,
  AuthSessionProvider,
  signIn,
  signOut,
} from '@lib/auth/session-client';

const mockMapBetterAuthSession = jest.fn();
const mockSignInBetterAuth = jest.fn(async () => {});
const mockSignOutBetterAuth = jest.fn(async () => {});
const mockUpdateUserNameBetterAuth = jest.fn(async () => {});

const mockSetActiveTenant = jest.fn();
const mockUseSession = jest.fn();

jest.mock('@lib/auth/better-auth-client-compat', () => ({
  mapBetterAuthSession: (...args: unknown[]) => mockMapBetterAuthSession(...args),
  signInBetterAuth: (...args: unknown[]) => mockSignInBetterAuth(...args),
  signOutBetterAuth: (...args: unknown[]) => mockSignOutBetterAuth(...args),
  updateUserNameBetterAuth: (...args: unknown[]) => mockUpdateUserNameBetterAuth(...args),
}));
jest.mock('@lib/auth/last-active-tenant-actions', () => ({
  setActiveTenant: (...args: unknown[]) => mockSetActiveTenant(...args),
}));
jest.mock('@lib/auth/auth-client', () => ({ authClient: { useSession: () => mockUseSession() } }));

beforeEach(() => {
  jest.clearAllMocks();
});

describe('session-client (Better Auth)', () => {
  it('exposes the Better Auth session in the legacy shape', () => {
    const contract = { user: { user_id: 'u1', email: 'a@b.co', current_tenant_id: 't1' }, expires: '' };
    mockUseSession.mockReturnValue({ data: { user: {} }, isPending: false, refetch: jest.fn() });
    mockMapBetterAuthSession.mockReturnValue(contract);

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });

    expect(result.current.data).toEqual(contract);
    expect(result.current.status).toBe('authenticated');
  });

  it('reports loading while pending', () => {
    mockUseSession.mockReturnValue({ data: null, isPending: true, refetch: jest.fn() });
    mockMapBetterAuthSession.mockReturnValue(null);

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });

    expect(result.current.status).toBe('loading');
  });

  describe('initialSession (SUX-5.6)', () => {
    const initial = {
      user: { user_id: 'u1', email: 'a@b.co', current_tenant_id: 't1', twoFactorEnabled: false },
      expires: '',
      twoFactorElevated: false,
    };
    const withInitial = ({ children }: { children: React.ReactNode }) => (
      <AuthSessionProvider initialSession={initial}>{children}</AuthSessionProvider>
    );

    it('reports the server session as authenticated while the client read is pending', () => {
      mockUseSession.mockReturnValue({ data: null, isPending: true, refetch: jest.fn() });
      mockMapBetterAuthSession.mockReturnValue(null);

      const { result } = renderHook(() => useAuthSession(), { wrapper: withInitial });

      expect(result.current.status).toBe('authenticated');
      expect(result.current.data).toEqual(initial);
    });

    it('lets the settled client answer win over the initial session', () => {
      const fresh = { ...initial, user: { ...initial.user, current_tenant_id: 't2' } };
      mockUseSession.mockReturnValue({ data: { user: {} }, isPending: false, refetch: jest.fn() });
      mockMapBetterAuthSession.mockReturnValue(fresh);

      const { result } = renderHook(() => useAuthSession(), { wrapper: withInitial });

      expect(result.current.data).toEqual(fresh);
    });

    it('reports unauthenticated once the client read settles with no session', () => {
      mockUseSession.mockReturnValue({ data: null, isPending: false, refetch: jest.fn() });
      mockMapBetterAuthSession.mockReturnValue(null);

      const { result } = renderHook(() => useAuthSession(), { wrapper: withInitial });

      expect(result.current.status).toBe('unauthenticated');
      expect(result.current.data).toBeNull();
    });
  });

  it('reports unauthenticated when there is no session', () => {
    mockUseSession.mockReturnValue({ data: null, isPending: false, refetch: jest.fn() });
    mockMapBetterAuthSession.mockReturnValue(null);

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });

    expect(result.current.status).toBe('unauthenticated');
    expect(result.current.data).toBeNull();
  });

  it('routes signIn / signOut to the Better Auth transport', async () => {
    await signIn('github', { callbackUrl: '/ade' });
    await signOut('/login');

    expect(mockSignInBetterAuth).toHaveBeenCalledWith('github', { callbackUrl: '/ade' });
    expect(mockSignOutBetterAuth).toHaveBeenCalledWith('/login');
  });

  it('signIn forwards a credentials payload', async () => {
    await signIn('credentials', { payload: '{"email":"a@b.co","password":"x"}', callbackUrl: '/ade' });

    expect(mockSignInBetterAuth).toHaveBeenCalledWith('credentials', {
      payload: '{"email":"a@b.co","password":"x"}',
      callbackUrl: '/ade',
    });
  });

  it('update() persists a validated tenant switch through the server action', async () => {
    const refetch = jest.fn(async () => {});
    mockUseSession.mockReturnValue({ data: { user: {} }, isPending: false, refetch });
    mockMapBetterAuthSession.mockReturnValue({ user: { user_id: 'u1' }, expires: '' });
    mockSetActiveTenant.mockResolvedValue('t2');

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });
    await act(async () => {
      await result.current.update({ current_tenant_id: 't2' });
    });

    expect(mockSetActiveTenant).toHaveBeenCalledWith('t2');
    expect(refetch).toHaveBeenCalled();
  });

  it('update() with a name change calls the Better Auth updateUser', async () => {
    mockUseSession.mockReturnValue({ data: { user: {} }, isPending: false, refetch: jest.fn() });
    mockMapBetterAuthSession.mockReturnValue({ user: { user_id: 'u1' }, expires: '' });

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });
    await act(async () => {
      await result.current.update({ user: { name: 'Ada' } });
    });

    expect(mockUpdateUserNameBetterAuth).toHaveBeenCalledWith('Ada');
  });
});

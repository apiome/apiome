/**
 * Engine-aware browser session layer tests (OLO-10.12, #5007) for `lib/auth/session-client.tsx`.
 *
 * Assert the compat layer (a) picks the right transport per engine, (b) exposes the legacy
 * `{ data, status, update }` shape, and (c) routes `update`/`signIn`/`signOut` to the correct engine —
 * including the validated tenant-switch persistence and the NextAuth-only JWT refresh.
 *
 * The engine is read at call time via `isBetterAuthEngineClient()`, so it is mocked per test (no module
 * reload — that would give React a second instance). Both transports and the tenant-switch server
 * action are mocked too.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import {
  useAuthSession,
  AuthSessionProvider,
  signIn,
  signOut,
} from '@lib/auth/session-client';

const mockIsBetterAuthEngineClient = jest.fn();
const mockMapBetterAuthSession = jest.fn();
const mockSignInBetterAuth = jest.fn(async () => {});
const mockSignOutBetterAuth = jest.fn(async () => {});
const mockUpdateUserNameBetterAuth = jest.fn(async () => {});

const mockGetNextAuthSession = jest.fn();
const mockSignInNextAuth = jest.fn(async () => {});
const mockSignOutNextAuth = jest.fn(async () => {});
const mockUpdateNextAuthSession = jest.fn(async () => {});

const mockSetActiveTenant = jest.fn();
const mockUseSession = jest.fn();

jest.mock('@lib/auth/auth-engine', () => ({
  isBetterAuthEngineClient: () => mockIsBetterAuthEngineClient(),
}));
jest.mock('@lib/auth/better-auth-client-compat', () => ({
  mapBetterAuthSession: (...args: unknown[]) => mockMapBetterAuthSession(...args),
  signInBetterAuth: (...args: unknown[]) => mockSignInBetterAuth(...args),
  signOutBetterAuth: (...args: unknown[]) => mockSignOutBetterAuth(...args),
  updateUserNameBetterAuth: (...args: unknown[]) => mockUpdateUserNameBetterAuth(...args),
}));
jest.mock('@lib/auth/next-auth-client-compat', () => ({
  getNextAuthSession: (...args: unknown[]) => mockGetNextAuthSession(...args),
  signInNextAuth: (...args: unknown[]) => mockSignInNextAuth(...args),
  signOutNextAuth: (...args: unknown[]) => mockSignOutNextAuth(...args),
  updateNextAuthSession: (...args: unknown[]) => mockUpdateNextAuthSession(...args),
}));
jest.mock('@lib/auth/last-active-tenant-actions', () => ({
  setActiveTenant: (...args: unknown[]) => mockSetActiveTenant(...args),
}));
jest.mock('@lib/auth/auth-client', () => ({ authClient: { useSession: () => mockUseSession() } }));

beforeEach(() => {
  jest.clearAllMocks();
});

describe('better-auth engine', () => {
  beforeEach(() => {
    mockIsBetterAuthEngineClient.mockReturnValue(true);
  });

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

  it('routes signIn / signOut to the Better Auth transport', async () => {
    await signIn('github', { callbackUrl: '/ade' });
    await signOut('/login');

    expect(mockSignInBetterAuth).toHaveBeenCalledWith('github', { callbackUrl: '/ade' });
    expect(mockSignOutBetterAuth).toHaveBeenCalledWith('/login');
    expect(mockSignInNextAuth).not.toHaveBeenCalled();
    expect(mockSignOutNextAuth).not.toHaveBeenCalled();
  });

  it('update() persists a validated tenant switch and does NOT touch the NextAuth JWT', async () => {
    const refetch = jest.fn(async () => {});
    mockUseSession.mockReturnValue({ data: { user: {} }, isPending: false, refetch });
    mockMapBetterAuthSession.mockReturnValue({ user: { user_id: 'u1' }, expires: '' });
    mockSetActiveTenant.mockResolvedValue('t2');

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });
    await act(async () => {
      await result.current.update({ current_tenant_id: 't2' });
    });

    expect(mockSetActiveTenant).toHaveBeenCalledWith('t2');
    expect(mockUpdateNextAuthSession).not.toHaveBeenCalled();
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

describe('next-auth engine', () => {
  beforeEach(() => {
    mockIsBetterAuthEngineClient.mockReturnValue(false);
  });

  it('fetches and exposes the NextAuth session', async () => {
    mockGetNextAuthSession.mockResolvedValue({ user: { user_id: 'u1' }, expires: 'x' });

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });

    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    expect(result.current.data).toEqual({ user: { user_id: 'u1' }, expires: 'x' });
    expect(mockUseSession).not.toHaveBeenCalled();
  });

  it('routes signIn / signOut to the NextAuth transport', async () => {
    await signIn('credentials', { payload: '{"email":"a@b.co","password":"x"}', callbackUrl: '/ade' });
    await signOut('/login');

    expect(mockSignInNextAuth).toHaveBeenCalledWith('credentials', {
      payload: '{"email":"a@b.co","password":"x"}',
      callbackUrl: '/ade',
    });
    expect(mockSignOutNextAuth).toHaveBeenCalledWith('/login');
    expect(mockSignInBetterAuth).not.toHaveBeenCalled();
  });

  it('update() persists the validated tenant AND refreshes the NextAuth JWT', async () => {
    mockGetNextAuthSession.mockResolvedValue({ user: { user_id: 'u1' }, expires: 'x' });
    mockSetActiveTenant.mockResolvedValue('t2');

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });
    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    await act(async () => {
      await result.current.update({ current_tenant_id: 't2' });
    });

    expect(mockSetActiveTenant).toHaveBeenCalledWith('t2');
    expect(mockUpdateNextAuthSession).toHaveBeenCalledWith({ current_tenant_id: 't2' });
  });

  it('update() does not refresh the JWT when the tenant switch is refused', async () => {
    mockGetNextAuthSession.mockResolvedValue({ user: { user_id: 'u1' }, expires: 'x' });
    mockSetActiveTenant.mockResolvedValue(null);

    const { result } = renderHook(() => useAuthSession(), { wrapper: AuthSessionProvider });
    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    await act(async () => {
      await result.current.update({ current_tenant_id: 'bad-tenant' });
    });

    expect(mockSetActiveTenant).toHaveBeenCalledWith('bad-tenant');
    expect(mockUpdateNextAuthSession).not.toHaveBeenCalled();
  });
});

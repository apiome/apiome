/**
 * Engine-aware server reader tests (OLO-10.12, #5007) for `lib/auth/server-session.ts`.
 *
 * `getAuthSession()` is the single server-side session read for ~106 routes + the route guards, and it
 * must return the identical app-contract shape on either engine. These tests mock each engine's
 * dependencies and assert the dispatch + mapping:
 * - better-auth → `auth.api.getSession` mapped through `toAppSessionUser`;
 * - next-auth   → `getServerSession(authOptions)` passed through unchanged.
 *
 * NOTE: `@lib/auth/server-session` resolves to the REAL module here (the `^@lib/(.*)$` mapper wins over
 * the `server-session` mock mapper, which only catches relative imports), so we exercise the real
 * dispatch and mock its lazily-imported deps instead.
 */

const mockGetSession = jest.fn();
const mockToAppSessionUser = jest.fn();
const mockGetServerSession = jest.fn();
const mockHeaders = jest.fn(async () => new Headers());

jest.mock('@lib/auth/auth', () => ({ auth: { api: { getSession: mockGetSession } } }));
jest.mock('@lib/auth/better-auth-session-shape', () => ({ toAppSessionUser: mockToAppSessionUser }));
jest.mock('next/headers', () => ({ headers: mockHeaders }));
jest.mock('next-auth', () => ({ getServerSession: mockGetServerSession }));
jest.mock('@/app/api/auth/[...nextauth]/route', () => ({ authOptions: { id: 'auth-options' } }));

import { getAuthSession } from '@lib/auth/server-session';

const ORIGINAL_ENGINE = process.env.AUTH_ENGINE;

beforeEach(() => {
  jest.clearAllMocks();
});

afterAll(() => {
  process.env.AUTH_ENGINE = ORIGINAL_ENGINE;
});

describe('getAuthSession — better-auth engine', () => {
  beforeEach(() => {
    process.env.AUTH_ENGINE = 'better-auth';
  });

  it('reads the Better Auth session and maps it to the app contract', async () => {
    const expiresAt = new Date('2030-01-02T03:04:05.000Z');
    mockGetSession.mockResolvedValue({ user: { id: 'u1', email: 'a@b.co' }, session: { expiresAt } });
    mockToAppSessionUser.mockResolvedValue({ user_id: 'u1', email: 'a@b.co', current_tenant_id: 't1' });

    const session = await getAuthSession();

    expect(mockGetSession).toHaveBeenCalledWith({ headers: expect.any(Headers) });
    expect(mockToAppSessionUser).toHaveBeenCalledWith({ id: 'u1', email: 'a@b.co' });
    expect(session).toEqual({
      user: { user_id: 'u1', email: 'a@b.co', current_tenant_id: 't1' },
      expires: '2030-01-02T03:04:05.000Z',
    });
    // The NextAuth path must not be touched on the Better Auth engine.
    expect(mockGetServerSession).not.toHaveBeenCalled();
  });

  it('returns null when there is no Better Auth session', async () => {
    mockGetSession.mockResolvedValue(null);

    expect(await getAuthSession()).toBeNull();
    expect(mockToAppSessionUser).not.toHaveBeenCalled();
  });
});

describe('getAuthSession — next-auth engine', () => {
  beforeEach(() => {
    process.env.AUTH_ENGINE = 'next-auth';
  });

  it('delegates to getServerSession(authOptions) unchanged', async () => {
    const nextAuthSession = { user: { user_id: 'u1', current_tenant_id: 't1' }, expires: 'x' };
    mockGetServerSession.mockResolvedValue(nextAuthSession);

    const session = await getAuthSession();

    expect(mockGetServerSession).toHaveBeenCalledWith({ id: 'auth-options' });
    expect(session).toBe(nextAuthSession);
    // The Better Auth path must not be touched on the NextAuth engine.
    expect(mockGetSession).not.toHaveBeenCalled();
  });

  it('returns null when there is no NextAuth session', async () => {
    mockGetServerSession.mockResolvedValue(null);

    expect(await getAuthSession()).toBeNull();
  });
});

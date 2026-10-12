/**
 * @jest-environment node
 *
 * The two routes that reset someone's two-factor (TFA-1.2, #5656):
 * `POST /api/admin/users/{id}/two-factor/reset` and `POST /api/access/members/{id}/two-factor/reset`.
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * apiome-rest decides who may reset whom and writes the audit trail; these routes are what stands
 * between a browser and that call. Driven for real, with the session, the upstream `fetch` and the
 * mail sender mocked, they pin what this layer owns: a cross-site request is refused, the caller's
 * identity comes from a verified session and never from the request, apiome-rest's refusal reaches
 * the dialog with its code, and the user is emailed only after a reset that succeeded.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockCookieGet = jest.fn();
jest.mock('next/headers', () => ({ cookies: jest.fn(async () => ({ get: mockCookieGet })) }));
jest.mock('@lib/auth/admin-session', () => ({ verifyAdminSessionToken: jest.fn() }));
jest.mock('@lib/auth/admin-provider-config-proxy', () => ({ forwardToAdminRest: jest.fn() }));
jest.mock('@lib/auth/send-two-factor-reset-email', () => ({ sendTwoFactorResetEmail: jest.fn() }));
jest.mock('@lib/auth/server-session', () => ({ getAuthSession: jest.fn() }));
jest.mock('@lib/db/helper', () => ({ getTenantById: jest.fn() }));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn((user: { user_id?: string }) => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer token-for-${user.user_id}`,
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';
import { forwardToAdminRest } from '@lib/auth/admin-provider-config-proxy';
import { sendTwoFactorResetEmail } from '@lib/auth/send-two-factor-reset-email';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { POST as adminReset } from '@/app/api/admin/users/[userId]/two-factor/reset/route';
import { POST as memberReset } from '@/app/api/access/members/[userId]/two-factor/reset/route';

const mockVerify = verifyAdminSessionToken as unknown as jest.Mock;
const mockForward = forwardToAdminRest as unknown as jest.Mock;
const mockSendEmail = sendTwoFactorResetEmail as unknown as jest.Mock;
const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const HOST = 'app.apiome.dev';
const USER_ID = '660e8400-e29b-41d4-a716-446655440001';
const OWNER_ID = '770e8400-e29b-41d4-a716-446655440002';
const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const BODY = { reason: 'Lost her phone and her backup codes.', confirm: 'priya@example.com' };
const REST_OK = {
  user_id: USER_ID,
  email: 'priya@example.com',
  name: 'Priya Raman',
  had_two_factor: true,
  sessions_revoked: 3,
  trusted_devices_revoked: 1,
};

let fetchMock: jest.Mock<typeof fetch>;

/** Build a reset request as a browser on `origin` would send it (`null` sends no Origin). */
const request = (path: string, body: unknown = BODY, origin: string | null = `https://${HOST}`) =>
  new NextRequest(`https://${HOST}${path}`, {
    method: 'POST',
    headers: { host: HOST, 'content-type': 'application/json', ...(origin ? { origin } : {}) },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });

const params = { params: Promise.resolve({ userId: USER_ID }) };

/** A JSON response from apiome-rest. */
const restResponse = (status: number, payload: unknown) =>
  new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } });

beforeEach(() => {
  jest.clearAllMocks();
  mockCookieGet.mockReturnValue({ value: 'signed-admin-token' });
  mockVerify.mockReturnValue(true);
  mockForward.mockResolvedValue({ status: 200, body: REST_OK });
  mockSendEmail.mockResolvedValue(true);
  mockSession.mockResolvedValue({
    user: { user_id: OWNER_ID, email: 'owner@example.com', name: 'Owner', current_tenant_id: TENANT_ID },
  });
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' });
  fetchMock = jest.fn<typeof fetch>();
  fetchMock.mockResolvedValue(restResponse(200, REST_OK));
  global.fetch = fetchMock;
});

describe('POST /api/admin/users/{id}/two-factor/reset', () => {
  const call = (body?: unknown, origin?: string | null) =>
    adminReset(request(`/api/admin/users/${USER_ID}/two-factor/reset`, body, origin), params);

  test('forwards the reset with the verified admin session and emails the user', async () => {
    const response = await call();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      success: true,
      data: {
        userId: USER_ID,
        hadTwoFactor: true,
        sessionsRevoked: 3,
        trustedDevicesRevoked: 1,
        emailSent: true,
      },
    });
    expect(mockForward).toHaveBeenCalledWith(
      `/users/${USER_ID}/two-factor/reset`,
      { method: 'POST', body: JSON.stringify(BODY) },
      'signed-admin-token'
    );
    expect(mockSendEmail).toHaveBeenCalledWith({ email: 'priya@example.com', name: 'Priya Raman' });
  });

  test('says so when no email could be sent', async () => {
    mockSendEmail.mockResolvedValue(false);
    const response = await call();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ success: true, data: { emailSent: false } });
  });

  test.each([
    ['another site', 'https://evil.example'],
    ['no Origin header', null],
  ])('refuses %s before reading the session', async (_name, origin) => {
    const response = await call(BODY, origin);
    expect(response.status).toBe(403);
    expect(mockCookieGet).not.toHaveBeenCalled();
    expect(mockForward).not.toHaveBeenCalled();
  });

  test('needs an admin session cookie', async () => {
    mockCookieGet.mockReturnValue(undefined);
    const response = await call();
    expect(response.status).toBe(401);
    expect(mockForward).not.toHaveBeenCalled();
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  test('refuses a cookie that does not verify', async () => {
    mockVerify.mockReturnValue(false);
    const response = await call();
    expect(response.status).toBe(403);
    expect(mockForward).not.toHaveBeenCalled();
  });

  test('a workspace sign-in is not an admin session', async () => {
    mockCookieGet.mockReturnValue(undefined);
    expect((await call()).status).toBe(401);
    expect(mockSession).not.toHaveBeenCalled();
  });

  test.each([['not json', 'not json'], ['a missing confirmation', { reason: 'x' }], ['an array', []]])(
    'refuses %s without calling apiome-rest',
    async (_name, body) => {
      const response = await call(body);
      expect(response.status).toBe(400);
      expect(mockForward).not.toHaveBeenCalled();
    }
  );

  test("passes on apiome-rest's refusal with its code, and sends no email", async () => {
    mockForward.mockResolvedValue({
      status: 422,
      body: { detail: { error: 'confirmation_mismatch', message: 'Type the user’s email address exactly.' } },
    });
    const response = await call();
    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      success: false,
      error: 'Type the user’s email address exactly.',
      code: 'confirmation_mismatch',
    });
    expect(mockSendEmail).not.toHaveBeenCalled();
  });
});

describe('POST /api/access/members/{id}/two-factor/reset', () => {
  const call = (body?: unknown, origin?: string | null) =>
    memberReset(request(`/api/access/members/${USER_ID}/two-factor/reset`, body, origin), params);

  test('forwards the reset for the session’s workspace and emails the member', async () => {
    const response = await call();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ success: true, data: { emailSent: true } });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`http://rest.test/v1/access/acme/members/${USER_ID}/two-factor/reset`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(BODY);
    // The token is minted from the session: the caller cannot say who they are.
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer token-for-${OWNER_ID}`);
    expect(mockSendEmail).toHaveBeenCalledWith({ email: 'priya@example.com', name: 'Priya Raman' });
  });

  test.each([
    ['another site', 'https://evil.example'],
    ['no Origin header', null],
  ])('refuses %s before reading the session', async (_name, origin) => {
    const response = await call(BODY, origin);
    expect(response.status).toBe(403);
    expect(mockSession).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('needs a session, a selected workspace and a workspace that exists', async () => {
    mockSession.mockResolvedValueOnce(null);
    expect((await call()).status).toBe(401);

    mockSession.mockResolvedValueOnce({ user: { user_id: OWNER_ID } });
    expect((await call()).status).toBe(400);

    mockTenant.mockResolvedValueOnce(null);
    expect((await call()).status).toBe(404);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  test('refuses a malformed body without calling apiome-rest', async () => {
    expect((await call({ reason: 'only a reason' })).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each([
    [403, 'owner_required', 'Only an owner of this workspace can reset a member’s two-factor.'],
    [409, 'multi_tenant_member', 'This member also belongs to another workspace.'],
    [404, 'member_not_found', 'That user is not an active member of this workspace.'],
  ])("passes on apiome-rest's %i %s refusal and sends no email", async (status, code, message) => {
    fetchMock.mockResolvedValue(restResponse(status, { detail: { error: code, message } }));
    const response = await call();
    expect(response.status).toBe(status);
    await expect(response.json()).resolves.toEqual({ success: false, error: message, code });
    expect(mockSendEmail).not.toHaveBeenCalled();
  });

  test('answers 502 when apiome-rest cannot be reached', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    const response = await call();
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ success: false });
    expect(mockSendEmail).not.toHaveBeenCalled();
  });
});

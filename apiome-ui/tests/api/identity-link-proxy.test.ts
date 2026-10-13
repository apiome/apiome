/**
 * @jest-environment node
 *
 * The identity link proxy, `POST` / `DELETE /api/identity/link` (OLO-7.3 follow-up, #4963).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * The proxy forwards the caller's body to apiome-rest under a token minted from the session. These
 * tests drive the real handlers and pin what this layer is responsible for:
 *
 * 1. **A cross-site write is refused** before anything is read or forwarded.
 * 2. **The tenant and user come from the session**, never from the request.
 * 3. **The body is forwarded as sent** — scoping `projectId` / `relatedProjectId` to the tenant is
 *    apiome-rest's job (pinned in `apiome-rest/tests/test_api_identity.py`), and its refusal
 *    reaches the caller with its status intact.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import jwt from 'jsonwebtoken';

jest.mock('@lib/auth/server-session', () => ({ getAuthSession: jest.fn() }));
jest.mock('@lib/db/helper', () => ({ getTenantById: jest.fn() }));
jest.mock('@lib/rest-auth', () => ({ getJwtSigningSecret: jest.fn(() => 'test-signing-secret') }));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { DELETE, POST } from '@/app/api/identity/link/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const HOST = 'app.apiome.dev';
const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const USER_ID = '660e8400-e29b-41d4-a716-446655440001';
const BODY = { projectId: 'project-a', relatedProjectId: 'project-b' };

let fetchMock: jest.Mock<typeof fetch>;

/** Build a link request as a browser on `origin` would send it (omit `origin` to send none). */
const request = (method: 'POST' | 'DELETE', origin?: string) =>
  new NextRequest(`https://${HOST}/api/identity/link`, {
    method,
    headers: { host: HOST, 'content-type': 'application/json', ...(origin ? { origin } : {}) },
    body: JSON.stringify(BODY),
  });

/** A JSON response from apiome-rest. */
const restResponse = (status: number, payload: unknown) =>
  new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } });

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({
    user: { user_id: USER_ID, email: 'ada@acme.io', name: 'Ada', current_tenant_id: TENANT_ID },
  });
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' });
  fetchMock = jest.fn<typeof fetch>();
  global.fetch = fetchMock;
});

describe.each([
  ['POST', POST],
  ['DELETE', DELETE],
] as const)('%s /api/identity/link', (method, handler) => {
  test.each([
    ['another site', 'https://evil.example'],
    ['a sibling subdomain', 'https://suite.apiome.dev'],
    ['no Origin header at all', undefined],
  ])('refuses %s with 403 and forwards nothing', async (_name, origin) => {
    const response = await handler(request(method, origin));
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ success: false, error: 'Forbidden' });
    expect(mockSession).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('forwards a same-origin write for the session tenant, body as sent', async () => {
    fetchMock.mockResolvedValue(restResponse(200, { identityGroupId: 'group-1', relatedArtifacts: [] }));
    const response = await handler(request(method, `https://${HOST}`));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ success: true, identityGroupId: 'group-1' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/identity\/acme\/link$/);
    expect(init.method).toBe(method);
    expect(JSON.parse(init.body as string)).toEqual(BODY);

    // The token names the session's user and tenant — nothing in the request can change them.
    const token = (init.headers as Record<string, string>).Authorization.replace('Bearer ', '');
    expect(jwt.verify(token, 'test-signing-secret')).toMatchObject({
      user_id: USER_ID,
      current_tenant_id: TENANT_ID,
    });
  });

  test("passes on apiome-rest's refusal of a project outside the tenant", async () => {
    fetchMock.mockResolvedValue(restResponse(404, { detail: 'Project not found: project-b' }));
    const response = await handler(request(method, `https://${HOST}`));
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({
      success: false,
      error: 'Project not found: project-b',
    });
  });

  test('requires a session and an active tenant', async () => {
    mockSession.mockResolvedValueOnce(null);
    expect((await handler(request(method, `https://${HOST}`))).status).toBe(401);

    mockSession.mockResolvedValueOnce({ user: { user_id: USER_ID } });
    expect((await handler(request(method, `https://${HOST}`))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

/**
 * @jest-environment node
 *
 * The Agent access BFF routes — AGX-3.4 (#4540).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch` mocked,
 * and pins what this layer exists for:
 *
 * 1. **The tenant comes from the session**, never from the browser.
 * 2. **Each route reaches the right apiome-rest path and verb**, with ids encoded.
 * 3. **Only whitelisted query parameters are forwarded.**
 * 4. **A refusal keeps its status, a readable message and its stable code** — the toolset editor
 *    tells a missing write-op confirmation from any other failure by that code.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/helper', () => ({
  getTenantById: jest.fn(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { agentAccessErrorDetail, forwardQuery } from '@/app/api/agent-access/agent-access-proxy';
import {
  GET as listToolsets,
  POST as createToolset,
} from '@/app/api/agent-access/toolsets/route';
import {
  DELETE as deleteToolset,
  GET as getToolset,
  PATCH as patchToolset,
} from '@/app/api/agent-access/toolsets/[toolsetId]/route';
import { PATCH as patchTool } from '@/app/api/agent-access/toolsets/[toolsetId]/tools/[toolId]/route';
import { GET as listKeys, POST as createKey } from '@/app/api/agent-access/keys/route';
import { DELETE as revokeKey } from '@/app/api/agent-access/keys/[keyId]/route';
import { PUT as putAllowlist } from '@/app/api/agent-access/keys/[keyId]/allowlist/route';
import { GET as keyUsage } from '@/app/api/agent-access/keys/[keyId]/usage/route';
import { GET as usage } from '@/app/api/agent-access/usage/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const USER = {
  user_id: '660e8400-e29b-41d4-a716-446655440001',
  email: 'ada@acme.io',
  name: 'Ada',
  current_tenant_id: '550e8400-e29b-41d4-a716-446655440000',
};

let fetchMock: jest.Mock;

/** Answer every upstream call with one reply. */
function upstream(body: unknown, status = 200): void {
  fetchMock = jest.fn(async () =>
    status === 204
      ? new Response(null, { status })
      : new Response(typeof body === 'string' ? body : JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
  ) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
}

/** The URL and init of the upstream call. */
function called(): { url: string; method: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return {
    url,
    method: String(init.method),
    body: init.body ? JSON.parse(String(init.body)) : undefined,
  };
}

/** A browser request to the BFF. */
function req(path: string, init: { method?: string; body?: unknown } = {}): NextRequest {
  return new NextRequest(`http://ui.test/api/agent-access${path}`, {
    method: init.method ?? 'GET',
    ...(init.body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(init.body) }),
  });
}

const p = <T>(value: T) => ({ params: Promise.resolve(value) });

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER });
  mockTenant.mockResolvedValue({ id: USER.current_tenant_id, slug: 'acme' });
  upstream({ ok: true });
});

describe('who may ask', () => {
  test('no session is a 401 and nothing reaches apiome-rest', async () => {
    mockSession.mockResolvedValue(null);
    const res = await listToolsets(req('/toolsets'));
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('no workspace is a 400', async () => {
    mockSession.mockResolvedValue({ user: { ...USER, current_tenant_id: undefined } });
    expect((await usage(req('/usage'))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("the tenant is the session's, whatever the browser sends", async () => {
    await listToolsets(req('/toolsets?tenant=evil'));
    expect(called().url).toBe('http://rest.test/v1/tenants/acme/agent-toolsets');
  });
});

describe('routing', () => {
  test.each([
    ['list toolsets', () => listToolsets(req('/toolsets?versionId=v1&x=1')), 'GET', '/agent-toolsets?versionId=v1'],
    ['describe toolset', () => getToolset(req('/toolsets/t1'), p({ toolsetId: 't1' })), 'GET', '/agent-toolsets/t1'],
    ['delete toolset', () => deleteToolset(req('/toolsets/t1', { method: 'DELETE' }), p({ toolsetId: 't1' })), 'DELETE', '/agent-toolsets/t1'],
    ['list keys', () => listKeys(req('/keys?includeRevoked=true&toolsetId=t1&secret=x')), 'GET', '/agent-keys?toolsetId=t1&includeRevoked=true'],
    ['revoke key', () => revokeKey(req('/keys/k1', { method: 'DELETE' }), p({ keyId: 'k1' })), 'DELETE', '/agent-keys/k1'],
    ['key usage', () => keyUsage(req('/keys/k1/usage'), p({ keyId: 'k1' })), 'GET', '/agent-keys/k1/usage'],
    ['usage rollups', () => usage(req('/usage?days=7')), 'GET', '/agent-usage?days=7'],
  ])('%s', async (_name, run, method, path) => {
    const res = await run();
    expect(res.status).toBe(200);
    expect(called().method).toBe(method);
    expect(called().url).toBe(`http://rest.test/v1/tenants/acme${path}`);
  });

  test('writes forward their body', async () => {
    await createToolset(req('/toolsets', { method: 'POST', body: { versionId: 'v1', target: 'mock' } }));
    expect(called()).toMatchObject({
      method: 'POST',
      url: 'http://rest.test/v1/tenants/acme/agent-toolsets',
      body: { versionId: 'v1', target: 'mock' },
    });

    upstream({ ok: true });
    await patchToolset(req('/toolsets/t1', { method: 'PATCH', body: { enabled: false } }), p({ toolsetId: 't1' }));
    expect(called()).toMatchObject({ method: 'PATCH', body: { enabled: false } });

    upstream({ ok: true });
    await patchTool(
      req('/toolsets/t1/tools/x', { method: 'PATCH', body: { enabled: true, confirmWriteOp: true } }),
      p({ toolsetId: 't1', toolId: 'a/b' })
    );
    expect(called()).toMatchObject({
      method: 'PATCH',
      url: 'http://rest.test/v1/tenants/acme/agent-toolsets/t1/tools/a%2Fb',
      body: { enabled: true, confirmWriteOp: true },
    });

    upstream({ ok: true });
    await putAllowlist(req('/keys/k1/allowlist', { method: 'PUT', body: { toolAllowlist: ['a'] } }), p({ keyId: 'k1' }));
    expect(called()).toMatchObject({ method: 'PUT', url: 'http://rest.test/v1/tenants/acme/agent-keys/k1/allowlist' });
  });

  test("the create-key reply, secret included, is passed back with apiome-rest's status", async () => {
    upstream({ id: 'k1', secret: 'ak_once' }, 201);
    const res = await createKey(req('/keys', { method: 'POST', body: { name: 'n' } }));
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ success: true, data: { id: 'k1', secret: 'ak_once' } });
  });

  test('a 204 is a success with no data', async () => {
    upstream(null, 204);
    const res = await revokeKey(req('/keys/k1', { method: 'DELETE' }), p({ keyId: 'k1' }));
    expect(await res.json()).toEqual({ success: true, data: null });
  });

  test('a body that is not JSON is a 400', async () => {
    const bad = new NextRequest('http://ui.test/api/agent-access/keys', { method: 'POST', body: '{' });
    expect((await createKey(bad)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('refusals', () => {
  test('a typed refusal keeps status, message and code', async () => {
    upstream(
      {
        detail: {
          code: 'agent-toolset-write-op-unconfirmed',
          errors: ['enabling a write operation needs confirmWriteOp: true'],
        },
      },
      422
    );
    const res = await patchTool(
      req('/toolsets/t1/tools/x', { method: 'PATCH', body: { enabled: true } }),
      p({ toolsetId: 't1', toolId: 'x' })
    );
    expect(res.status).toBe(422);
    expect(await res.json()).toEqual({
      success: false,
      error: 'enabling a write operation needs confirmWriteOp: true',
      code: 'agent-toolset-write-op-unconfirmed',
    });
  });

  test('a permission refusal keeps its sentence', async () => {
    upstream({ detail: 'Permission denied' }, 403);
    const res = await usage(req('/usage'));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ success: false, error: 'Permission denied' });
  });

  test('an unreachable apiome-rest is a 500 with a message', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('connect ECONNREFUSED');
    }) as unknown as typeof fetch;
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const res = await usage(req('/usage'));
    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/ECONNREFUSED/);
  });
});

describe('helpers', () => {
  test('error detail handles every shape apiome-rest sends', () => {
    expect(agentAccessErrorDetail({ detail: 'nope' }, 'f')).toEqual({ message: 'nope', code: null });
    expect(agentAccessErrorDetail({ detail: [{ msg: 'a' }, { msg: 'b' }] }, 'f')).toEqual({
      message: 'a; b',
      code: null,
    });
    expect(agentAccessErrorDetail({ detail: { code: 'c', errors: [] } }, 'f')).toEqual({
      message: 'f',
      code: 'c',
    });
    expect(agentAccessErrorDetail({ detail: { code: 'c', message: 'm' } }, 'f')).toEqual({
      message: 'm',
      code: 'c',
    });
    expect(agentAccessErrorDetail(null, 'f')).toEqual({ message: 'f', code: null });
  });

  test('only named, non-empty query parameters are forwarded', () => {
    expect(forwardQuery('http://x/a?days=7&evil=1&toolsetId=', ['days', 'toolsetId'])).toBe('?days=7');
    expect(forwardQuery('http://x/a', ['days'])).toBe('');
  });
});

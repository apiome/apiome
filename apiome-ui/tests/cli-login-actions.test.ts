/**
 * Server actions behind the `apiome login` approve page (#5501): who they act as, what they send
 * to apiome-rest, and how REST answers map to the page's reasons.
 */
import jwt from 'jsonwebtoken';

const mockSession = jest.fn();
jest.mock('@lib/auth/server-session', () => ({ getAuthSession: () => mockSession() }));
jest.mock('../lib/auth/server-session', () => ({ getAuthSession: () => mockSession() }));

import { approveCliLogin, denyCliLogin, getCliLoginRequest } from '../lib/auth/cli-login-actions';
import { REST_API_BASE_URL } from '../lib/rest-auth';

const SECRET = 'test-better-auth-secret-0123456789abcdef';
const fetchMock = jest.fn();

/** A fetch answer. */
function answer(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  process.env.BETTER_AUTH_SECRET = SECRET;
  global.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  mockSession.mockResolvedValue({ user: { user_id: 'u-ada', email: 'ada@northwind.io', name: 'Ada' } });
});

it('reads a login as the signed-in user, normalizing the code', async () => {
  fetchMock.mockResolvedValue(answer(200, { user_code: 'KTXR-MWDB', workspaces: [] }));
  const result = await getCliLoginRequest('ktxr mwdb');

  expect(result).toEqual({ ok: true, data: { user_code: 'KTXR-MWDB', workspaces: [] } });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`${REST_API_BASE_URL}/cli/login/requests/KTXR-MWDB`);
  expect(init.method).toBe('GET');
  const token = String(init.headers.Authorization).replace('Bearer ', '');
  expect(jwt.verify(token, SECRET)).toMatchObject({ user_id: 'u-ada', sub: 'u-ada' });
});

it('approves with only the workspace slug in the body', async () => {
  fetchMock.mockResolvedValue(answer(200, { user_code: 'KTXR-MWDB', status: 'approved', tenant_slug: 'northwind' }));
  const result = await approveCliLogin('KTXR-MWDB', ' northwind ');
  expect(result.ok).toBe(true);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`${REST_API_BASE_URL}/cli/login/requests/KTXR-MWDB/approve`);
  expect(init.method).toBe('POST');
  expect(JSON.parse(init.body)).toEqual({ tenant_slug: 'northwind' });
});

it('denies', async () => {
  fetchMock.mockResolvedValue(answer(200, { user_code: 'KTXR-MWDB', status: 'denied' }));
  expect((await denyCliLogin('KTXR-MWDB')).ok).toBe(true);
  expect(fetchMock.mock.calls[0][0]).toBe(`${REST_API_BASE_URL}/cli/login/requests/KTXR-MWDB/deny`);
});

it.each([
  [404, 'not-found', { detail: 'gone' }],
  [401, 'signed-out', { detail: 'no' }],
  [403, 'forbidden', { detail: 'You need permission to create API keys in this workspace.' }],
  [500, 'failed', { detail: 'boom' }],
])('maps HTTP %i to %s', async (status, reason, body) => {
  fetchMock.mockResolvedValue(answer(status, body));
  const result = await approveCliLogin('KTXR-MWDB', 'northwind');
  expect(result).toMatchObject({ ok: false, reason });
  if (status === 403) expect(result).toMatchObject({ message: body.detail });
});

it('refuses without a session, a valid code or a workspace — before calling REST', async () => {
  mockSession.mockResolvedValueOnce(null);
  expect(await getCliLoginRequest('KTXR-MWDB')).toMatchObject({ ok: false, reason: 'signed-out' });
  expect(await getCliLoginRequest('../../admin')).toMatchObject({ ok: false, reason: 'not-found' });
  expect(await approveCliLogin('KTXR-MWDB', '')).toMatchObject({ ok: false, reason: 'failed' });
  expect(fetchMock).not.toHaveBeenCalled();
});

it('reports an unreachable REST service', async () => {
  fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
  expect(await denyCliLogin('KTXR-MWDB')).toMatchObject({ ok: false, reason: 'failed' });
});

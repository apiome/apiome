/**
 * The just-in-time provisioning call after an enterprise SSO sign-in — EID-1.3 (#5013).
 *
 * `lib/auth/sso-provisioning.ts` asks apiome-rest's service-token-gated
 * `POST /v1/tenants/{tenant}/sso/providers/{id}/provision`. Pinned: the call names the provider's
 * own workspace and nothing else; no token, no workspace, an outage, a refusal and a malformed
 * answer are all "no answer" (never an exception); only the outcomes this build knows are accepted;
 * and the out-of-seats link is a same-origin path with the workspace name safely encoded.
 */

jest.mock('@lib/rest-auth', () => ({ getRestApiBaseUrl: () => 'http://rest.test/v1' }));

import { afterEach, beforeEach, describe, expect, test } from '@jest/globals';

import {
  parseSsoProvisionResult,
  provisionSsoMember,
  SSO_OUT_OF_SEATS_PATH,
  SSO_PROVISION_OUTCOMES,
  ssoOutOfSeatsPath,
} from '../lib/auth/sso-provisioning';

const PROVIDER = { id: 'p-1', tenantId: 't-acme' };
const ANSWER = {
  outcome: 'provisioned',
  tenant_id: 't-acme',
  tenant_slug: 'acme',
  tenant_name: 'Acme Corp',
  role_slug: 'viewer',
  role_name: 'Viewer',
  seat_limit: 5,
};

/** A fetch double that records its calls and answers with `body`. */
function fetchAnswering(body: unknown, status = 200) {
  const calls: { url: string; init: RequestInit }[] = [];
  const impl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
  return { impl, calls };
}

const savedToken = process.env.INTERNAL_SERVICE_TOKEN;
let warn: jest.SpyInstance;

beforeEach(() => {
  process.env.INTERNAL_SERVICE_TOKEN = 'service-token';
  warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  if (savedToken === undefined) delete process.env.INTERNAL_SERVICE_TOKEN;
  else process.env.INTERNAL_SERVICE_TOKEN = savedToken;
  warn.mockRestore();
});

describe('provisionSsoMember', () => {
  test('posts the signed-in user to the provider’s own workspace, with the service token', async () => {
    const { impl, calls } = fetchAnswering(ANSWER);

    const result = await provisionSsoMember(PROVIDER, 'u-1', impl);

    expect(result).toEqual({ outcome: 'provisioned', tenantId: 't-acme', tenantName: 'Acme Corp', roleSlug: 'viewer' });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('http://rest.test/v1/tenants/t-acme/sso/providers/p-1/provision');
    expect(calls[0].init.method).toBe('POST');
    expect(calls[0].init.headers).toEqual({
      'Content-Type': 'application/json',
      'X-Internal-Service-Token': 'service-token',
    });
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ user_id: 'u-1' });
  });

  test('path segments are encoded', async () => {
    const { impl, calls } = fetchAnswering(ANSWER);
    await provisionSsoMember({ id: 'p/../x', tenantId: 't a' }, 'u-1', impl);
    expect(calls[0].url).toBe('http://rest.test/v1/tenants/t%20a/sso/providers/p%2F..%2Fx/provision');
  });

  test.each([
    ['there is no service token', () => delete process.env.INTERNAL_SERVICE_TOKEN, PROVIDER, 'u-1'],
    ['the provider has no workspace', () => undefined, { id: 'p-1', tenantId: null }, 'u-1'],
    ['there is no user', () => undefined, PROVIDER, ''],
  ])('asks nothing when %s', async (_label, arrange, provider, userId) => {
    arrange();
    const { impl, calls } = fetchAnswering(ANSWER);
    expect(await provisionSsoMember(provider, userId, impl)).toBeNull();
    expect(calls).toEqual([]);
  });

  test.each([403, 404, 409, 500, 503])('a %d refusal is no answer', async (status) => {
    const { impl } = fetchAnswering({ detail: { error: 'sso-identity-missing' } }, status);
    expect(await provisionSsoMember(PROVIDER, 'u-1', impl)).toBeNull();
  });

  test('an unreachable API is no answer, and never throws', async () => {
    const impl = (async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    await expect(provisionSsoMember(PROVIDER, 'u-1', impl)).resolves.toBeNull();
  });

  test('a response body is never logged', async () => {
    const { impl } = fetchAnswering({ detail: { error: 'secret-looking-detail' } }, 403);
    await provisionSsoMember(PROVIDER, 'u-1', impl);
    expect(warn.mock.calls.flat().join(' ')).not.toContain('secret-looking-detail');
  });
});

describe('parseSsoProvisionResult', () => {
  test.each(SSO_PROVISION_OUTCOMES.map((outcome) => [outcome]))('accepts %s', (outcome) => {
    expect(parseSsoProvisionResult({ ...ANSWER, outcome })?.outcome).toBe(outcome);
  });

  test('a blocked sign-in has no role', () => {
    expect(parseSsoProvisionResult({ ...ANSWER, outcome: 'seat-cap-blocked', role_slug: null })).toEqual({
      outcome: 'seat-cap-blocked',
      tenantId: 't-acme',
      tenantName: 'Acme Corp',
      roleSlug: null,
    });
  });

  test.each([
    ['an outcome this build does not know', { ...ANSWER, outcome: 'promoted-to-owner' }],
    ['no workspace', { ...ANSWER, tenant_id: '' }],
    ['not an object', 'provisioned'],
    ['null', null],
  ])('rejects %s', (_label, body) => {
    expect(parseSsoProvisionResult(body)).toBeNull();
  });
});

describe('ssoOutOfSeatsPath', () => {
  test('carries the workspace name, encoded', () => {
    expect(ssoOutOfSeatsPath('Acme & Sons / R&D')).toBe(
      `${SSO_OUT_OF_SEATS_PATH}?workspace=Acme%20%26%20Sons%20%2F%20R%26D`
    );
  });

  test('is the bare page when the name is unknown', () => {
    for (const name of [null, undefined, '', '   ']) expect(ssoOutOfSeatsPath(name)).toBe('/login/out-of-seats');
  });

  test('caps a long name and stays a same-origin path', () => {
    const path = ssoOutOfSeatsPath(`https://evil.example/${'x'.repeat(500)}`);
    expect(path.startsWith('/login/out-of-seats?workspace=')).toBe(true);
    expect(decodeURIComponent(path.split('=')[1])).toHaveLength(120);
  });
});

/**
 * @jest-environment node
 */
/**
 * The provider-state registry's UI model and proxies — PFX-3.3 (#6933).
 *
 * * Labels: a setup reads in one line (state-change call, recorded fixture, "already holds the
 *   data"), parameters show required ones and defaults, the check's headline never says "can be
 *   set up" while something blocks, and only a blocking problem is danger.
 * * Proxies: a malformed provider handle is a 404 without calling apiome-rest; the others forward
 *   to `/v1/tenants/{slug}/pact-verifier/providers/{provider}/provider-states…` for the session's
 *   tenant; the check forwards only a `target_ref`.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

const forward = jest.fn<(...args: unknown[]) => Promise<NextResponse>>(async () => NextResponse.json({ ok: true }));
let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: (...args: unknown[]) => forward(...args),
}));

import {
  SEVERITY_TONES,
  checkBody,
  checkProxyPath,
  checkStatement,
  parametersLine,
  setupLine,
  statesProxyPath,
} from '../lib/pact-provider-states';
import { GET as providersGet } from '../src/app/api/pact-provider-states/route';
import { GET as statesGet } from '../src/app/api/pact-provider-states/[provider]/route';
import { POST as checkPost } from '../src/app/api/pact-provider-states/[provider]/check/route';

const params = (provider: string) => ({ params: Promise.resolve({ provider }) });

beforeEach(() => {
  forward.mockClear();
  tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
});

describe('labels', () => {
  it('reads every kind of setup in one line', () => {
    expect(setupLine({ kind: 'state_change', url: '/_pact/states' })).toBe('State-change call · POST /_pact/states');
    expect(setupLine({ kind: 'state_change', url: 'https://hooks.example.test/s', teardown: false })).toBe(
      'State-change call · POST https://hooks.example.test/s · no teardown',
    );
    expect(setupLine({ kind: 'fixture', requests: [] })).toBe('Recorded fixture · target already holds the data');
    expect(setupLine({ kind: 'fixture' })).toBe('Recorded fixture · target already holds the data');
    expect(setupLine({ kind: 'fixture', requests: [{ method: 'PUT', path: '/x' }] })).toBe(
      'Recorded fixture · 1 request',
    );
    expect(
      setupLine({
        kind: 'fixture',
        requests: [
          { method: 'PUT', path: '/x' },
          { method: 'GET', path: '/y' },
        ],
      }),
    ).toBe('Recorded fixture · 2 requests');
  });

  it('shows required parameters and defaults', () => {
    expect(parametersLine([])).toBe('No parameters');
    expect(
      parametersLine([{ name: 'id', required: true }, { name: 'currency', default: 'EUR' }, { name: 'note' }]),
    ).toBe('id (required), currency = "EUR", note');
  });

  it('never reads ready while something blocks', () => {
    const base = { pacts: 3, states: [{}] as never[], target: null, warnings: 0 };
    expect(checkStatement({ ...base, ready: false, blocking: 2 })).toBe('2 problems would hold interactions back.');
    expect(checkStatement({ ...base, ready: false, blocking: 1, warnings: 1, target: 'staging' })).toBe(
      '1 problem would hold interactions back on staging. 1 warning to review.',
    );
    expect(checkStatement({ ...base, ready: true, blocking: 0 })).toBe(
      'Every provider state the 3 selected pacts name can be set up.',
    );
    expect(checkStatement({ ...base, ready: true, blocking: 0, states: [] })).toBe(
      'None of the 3 selected pacts names a provider state.',
    );
    expect(checkStatement({ ...base, pacts: 0, ready: true, blocking: 0, states: [] })).toContain('nothing to check');
  });

  it('keeps danger for blocking problems', () => {
    expect(SEVERITY_TONES).toEqual({ blocking: 'danger', warning: 'warn' });
  });
});

describe('paths and bodies', () => {
  it('accepts only pacticipant handles', () => {
    expect(statesProxyPath('ledger-api')).toBe('pact-verifier/providers/ledger-api/provider-states');
    expect(checkProxyPath('ledger-api')).toBe('pact-verifier/providers/ledger-api/provider-states/check');
    for (const bad of ['', 'Ledger', '../x', 'a/b', '-x', 'x-', 'a?b=1']) {
      expect(statesProxyPath(bad)).toBeNull();
      expect(checkProxyPath(bad)).toBeNull();
    }
  });

  it('forwards only a target reference to the check', () => {
    expect(checkBody({ target_ref: ' staging ', selection: { consumerVersionSelectors: [] } })).toEqual({
      target_ref: 'staging',
    });
    for (const bad of [null, 'x', {}, { target_ref: 3 }, { target_ref: '  ' }, { target_ref: 'x'.repeat(201) }]) {
      expect(checkBody(bad)).toEqual({});
    }
  });
});

describe('proxies', () => {
  it('lists the first page of pacticipants', async () => {
    await providersGet();
    expect(forward.mock.calls[0][0]).toBe('http://rest/v1/tenants/acme/pacticipants?limit=100');
  });

  it('reads a provider’s states', async () => {
    await statesGet(new NextRequest('http://x/api/pact-provider-states/ledger-api'), params('ledger-api'));
    expect(forward.mock.calls[0][0]).toBe(
      'http://rest/v1/tenants/acme/pact-verifier/providers/ledger-api/provider-states',
    );
  });

  it('posts the check with only the target reference', async () => {
    const request = new NextRequest('http://x/api/pact-provider-states/ledger-api/check', {
      method: 'POST',
      body: JSON.stringify({ target_ref: 'staging', selection: { anything: true } }),
    });
    await checkPost(request, params('ledger-api'));
    const [url, init] = forward.mock.calls[0] as [string, { method: string; body: unknown }];
    expect(url).toBe('http://rest/v1/tenants/acme/pact-verifier/providers/ledger-api/provider-states/check');
    expect(init.method).toBe('POST');
    expect(init.body).toEqual({ target_ref: 'staging' });
  });

  it('answers 404 for a malformed handle without calling REST', async () => {
    const read = await statesGet(new NextRequest('http://x/api/pact-provider-states/..'), params('..'));
    const check = await checkPost(new NextRequest('http://x/c', { method: 'POST', body: '{}' }), params('A B'));
    expect([read.status, check.status]).toEqual([404, 404]);
    expect(forward).not.toHaveBeenCalled();
  });

  it('passes the session failure through', async () => {
    tenant = { error: NextResponse.json({ error: 'Unauthorized' }, { status: 401 }) };
    const response = await statesGet(
      new NextRequest('http://x/api/pact-provider-states/ledger-api'),
      params('ledger-api'),
    );
    expect(response.status).toBe(401);
    expect(forward).not.toHaveBeenCalled();
  });
});

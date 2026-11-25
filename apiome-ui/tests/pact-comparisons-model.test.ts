/**
 * @jest-environment node
 */
/**
 * The Pact comparisons model and its proxy routes — PFX-2.5 (#6929).
 *
 * * **Honest labels**: a verdict always reads with its strength; only a full comparison is green.
 * * **Counts**: the list line leaves zero counts out.
 * * **Proxy paths**: only a UUID reaches the fidelity route, and `limit` only as 1 … 100; the routes
 *   forward to `/v1/tenants/{slug}/pact-comparisons…` for the session's tenant.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

const forward = jest.fn<(...args: unknown[]) => Promise<NextResponse>>(async () => NextResponse.json({ ok: true }));
let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = { user: { user_id: 'u-1' }, slug: 'acme' };

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: (...args: unknown[]) => forward(...args),
}));

import {
  STRENGTH_TONES,
  fidelityProxyPath,
  interactionName,
  listProxyPath,
  operationLine,
  summaryLine,
  verdictLabel,
  type FidelitySummary,
} from '../lib/pact-comparisons';
import { GET as listGet } from '../src/app/api/pact-comparisons/route';
import { GET as fidelityGet } from '../src/app/api/pact-comparisons/[id]/fidelity/route';

const ID = '22222222-2222-4222-8222-222222222222';
const SUMMARY: FidelitySummary = {
  interactions: 3,
  fullyCompared: 1,
  partial: 2,
  failed: 0,
  notCompared: 0,
  checksCompared: 20,
  checksPartial: 3,
  checksFailed: 0,
  checksNotRun: 0,
  unsupportedMatchingRules: 1,
  couldNotCompare: 2,
};

beforeEach(() => {
  forward.mockClear();
  tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
});

describe('labels', () => {
  it('pairs every verdict with its strength', () => {
    expect(verdictLabel('pass', 'full')).toBe('Pass · Compared in full');
    expect(verdictLabel('partial', 'partial')).toBe('Pass (partial) · Not everything compared');
    expect(verdictLabel('unverified', 'full')).toBe('Unverified · Compared in full');
    expect(verdictLabel('fail', 'none')).toBe('Fail · Nothing compared');
  });

  it('keeps green for a full comparison only', () => {
    expect(Object.entries(STRENGTH_TONES).filter(([, tone]) => tone === 'ok')).toEqual([['full', 'ok']]);
  });

  it('leaves zero counts out of the list line', () => {
    expect(summaryLine(SUMMARY)).toBe('3 interactions · 2 not compared · 1 rule unsupported');
    expect(summaryLine({ ...SUMMARY, interactions: 1, couldNotCompare: 0, unsupportedMatchingRules: 0, failed: 1, checksNotRun: 7 })).toBe(
      '1 interaction · 1 failed · 7 checks not run'
    );
  });

  it('names an interaction and its operation', () => {
    expect(interactionName({ description: '  ', index: 2 })).toBe('Interaction 3');
    expect(interactionName({ description: 'a list of events', index: 0 })).toBe('a list of events');
    expect(operationLine({ operation: { method: 'get', path: '/events', pointer: '/paths/~1events/get', operationId: null } })).toBe(
      'GET /events'
    );
    expect(operationLine({ operation: null })).toBeNull();
  });
});

describe('proxy paths', () => {
  it('accepts only a UUID for the fidelity route', () => {
    expect(fidelityProxyPath(ID.toUpperCase())).toBe(`pact-comparisons/${ID}/fidelity`);
    for (const bad of ['', 'r-1', '../tenants', `${ID}/x`, `${ID}%2F..`]) expect(fidelityProxyPath(bad)).toBeNull();
  });

  it('passes limit on only as a whole number in 1 … 100', () => {
    expect(listProxyPath('25')).toBe('pact-comparisons?limit=25');
    for (const bad of [null, '', '0', '101', '2.5', 'abc', '10&x=1']) expect(listProxyPath(bad)).toBe('pact-comparisons');
  });
});

describe('proxy routes', () => {
  it('forwards the list for the session tenant', async () => {
    await listGet(new NextRequest('http://x/api/pact-comparisons?limit=10'));
    expect(forward.mock.calls[0][0]).toBe('http://rest/v1/tenants/acme/pact-comparisons?limit=10');
    expect(forward.mock.calls[0][1]).toMatchObject({ method: 'GET', user: { user_id: 'u-1' } });
  });

  it('forwards a report, and answers 404 for a malformed id without calling REST', async () => {
    await fidelityGet(new NextRequest(`http://x/api/pact-comparisons/${ID}/fidelity`), { params: Promise.resolve({ id: ID }) });
    expect(forward.mock.calls[0][0]).toBe(`http://rest/v1/tenants/acme/pact-comparisons/${ID}/fidelity`);
    const response = await fidelityGet(new NextRequest('http://x/api/pact-comparisons/x/fidelity'), {
      params: Promise.resolve({ id: 'not-a-uuid' }),
    });
    expect(response.status).toBe(404);
    expect(forward).toHaveBeenCalledTimes(1);
  });

  it('returns the session error without calling REST', async () => {
    tenant = { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
    const response = await listGet(new NextRequest('http://x/api/pact-comparisons'));
    expect(response.status).toBe(401);
    expect(forward).not.toHaveBeenCalled();
  });
});

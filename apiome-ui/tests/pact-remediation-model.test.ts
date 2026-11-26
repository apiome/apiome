/**
 * @jest-environment node
 */
/**
 * Stale-pact remediation and verification scheduling — PFX-6.2 (#6954): the model and the
 * `/api/pact` proxies.
 *
 * * the wording of cadences, request states and notification outcomes; routes and REST paths;
 * * the body checks of Save settings, Save override and Acknowledge (every unknown field, bad
 *   value and missing value is refused with a message naming it);
 * * the request list's query check;
 * * the proxies forward checked reads and writes to the right REST path as the signed-in user, and
 *   refuse bad input without calling REST.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return NextResponse.json({ ok: true });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  CADENCES,
  cadenceLabel,
  formatHours,
  isOpen,
  isRecordId,
  notificationText,
  pickAcknowledgeBody,
  pickOverrideBody,
  pickSettingsBody,
  requestQueryProblem,
  requestRoute,
  requestsListPath,
  requestsRoute,
  stateText,
} from '../lib/pact-remediation';
import { overrideBodyOf, settingsBodyOf } from '../src/app/components/ade/pactRemediation/VerificationSettingsClient';
import { GET as settingsGet, PUT as settingsPut } from '../src/app/api/pact/verification-settings/route';
import { GET as overridesGet, PUT as overridesPut } from '../src/app/api/pact/verification-settings/overrides/route';
import { DELETE as overrideDelete } from '../src/app/api/pact/verification-settings/overrides/[overrideId]/route';
import { GET as requestsGet } from '../src/app/api/pact/republish-requests/route';
import { GET as requestGet } from '../src/app/api/pact/republish-requests/[requestId]/route';
import { POST as acknowledgePost } from '../src/app/api/pact/republish-requests/[requestId]/acknowledge/route';

const ID = '5c2b8e14-6f0a-4d3b-8a7e-1f9c4b2d6e01';
const SETTINGS = {
  cadence: 'nightly',
  stale_threshold_hours: 72,
  max_concurrent_runs: 2,
  request_window_hours: 72,
  republish_requests_enabled: true,
};

function req(url: string, init?: { method?: string; body?: string }): NextRequest {
  return new NextRequest(new URL(url, 'http://ui'), init);
}

function ctx<T>(params: T): { params: Promise<T> } {
  return { params: Promise.resolve(params) };
}

beforeEach(() => {
  forwarded.length = 0;
  tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
});

describe('wording and routes', () => {
  it('names every cadence and state', () => {
    expect(CADENCES.map(cadenceLabel)).toEqual(['On publish', 'Hourly', 'Nightly', 'Manual only']);
    expect(cadenceLabel(null)).toBe('Inherited');
    expect(stateText('acknowledged')).toMatchObject({ label: 'Acknowledged', variant: 'accent' });
    expect(stateText('expired').variant).toBe('danger');
    expect(stateText('unheard-of').label).toBe('unheard-of');
    expect([isOpen('requested'), isOpen('acknowledged'), isOpen('cleared')]).toEqual([true, true, false]);
  });

  it('says what notifying did, and that an unlinked consumer reached nobody', () => {
    expect(notificationText('routed')).toContain('inbox');
    expect(notificationText('unlinked')).toContain('linked to no consumer or project');
    expect(notificationText(null)).toBe('Not sent yet.');
    expect(notificationText('something-new')).toBe('something-new');
  });

  it('writes hours with days when whole', () => {
    expect([formatHours(72), formatHours(24), formatHours(12)]).toEqual(['72 h (3 days)', '24 h (1 day)', '12 h']);
  });

  it('builds the routes and the REST list path', () => {
    expect(requestsRoute()).toBe('/ade/dashboard/pacts/republish-requests');
    expect(requestsRoute({ state: 'open', provider: 'ledger-api' })).toBe(
      '/ade/dashboard/pacts/republish-requests?state=open&provider=ledger-api',
    );
    expect(requestRoute(ID)).toBe(`/ade/dashboard/pacts/republish-requests/${ID}`);
    expect(requestsListPath(new URLSearchParams('state=open&cursor=9'))).toBe(
      'pact-republish-requests?state=open&cursor=9&limit=25',
    );
    expect([isRecordId(ID), isRecordId('7')]).toEqual([true, false]);
  });
});

describe('body checks', () => {
  it('takes complete, in-range settings and refuses everything else by name', () => {
    expect(pickSettingsBody(SETTINGS)).toEqual({ ok: true, body: SETTINGS });
    const refusals: Array<[unknown, string]> = [
      [null, 'JSON object'],
      [{ ...SETTINGS, colour: 'blue' }, 'Unsupported field colour'],
      [{ ...SETTINGS, cadence: 'weekly' }, 'cadence must be one of'],
      [{ ...SETTINGS, stale_threshold_hours: 0 }, 'stale_threshold_hours'],
      [{ ...SETTINGS, max_concurrent_runs: 1.5 }, 'max_concurrent_runs'],
      [{ ...SETTINGS, request_window_hours: 721 }, 'request_window_hours'],
      [{ ...SETTINGS, republish_requests_enabled: 'yes' }, 'republish_requests_enabled'],
    ];
    for (const [raw, message] of refusals) {
      const picked = pickSettingsBody(raw);
      expect(picked.ok).toBe(false);
      if (!picked.ok) expect(picked.error).toContain(message);
    }
  });

  it('takes an override that sets something, for a provider or a pair', () => {
    expect(pickOverrideBody({ provider: 'ledger-api', target_ref: ' ledger-staging ' })).toEqual({
      ok: true,
      body: { provider: 'ledger-api', target_ref: 'ledger-staging' },
    });
    expect(
      pickOverrideBody({
        provider: 'ledger-api',
        consumer: 'billing-service',
        cadence: 'hourly',
        stale_threshold_hours: 24,
      }),
    ).toEqual({
      ok: true,
      body: { provider: 'ledger-api', consumer: 'billing-service', cadence: 'hourly', stale_threshold_hours: 24 },
    });
    const refusals: Array<[unknown, string]> = [
      [{ provider: 'ledger-api' }, 'at least one of'],
      [{ provider: 'Ledger API', cadence: 'hourly' }, 'provider must be'],
      [{ provider: 'ledger-api', consumer: 'ledger-api', cadence: 'hourly' }, 'its own consumer'],
      [{ provider: 'ledger-api', cadence: 'often' }, 'cadence must be'],
      [{ provider: 'ledger-api', stale_threshold_hours: 9999 }, 'stale_threshold_hours'],
      [{ provider: 'ledger-api', cadence: 'hourly', extra: 1 }, 'Unsupported field extra'],
    ];
    for (const [raw, message] of refusals) {
      const picked = pickOverrideBody(raw);
      expect(picked.ok).toBe(false);
      if (!picked.ok) expect(picked.error).toContain(message);
    }
  });

  it('takes an optional note of at most 1000 characters', () => {
    expect(pickAcknowledgeBody({})).toEqual({ ok: true, body: {} });
    expect(pickAcknowledgeBody({ note: 'Friday' })).toEqual({ ok: true, body: { note: 'Friday' } });
    expect(pickAcknowledgeBody({ note: 'x'.repeat(1001) }).ok).toBe(false);
    expect(pickAcknowledgeBody({ note: 'x', by: 'me' }).ok).toBe(false);
  });

  it('checks the request list query', () => {
    expect(requestQueryProblem(new URLSearchParams('state=open&provider=ledger-api&cursor=4'))).toBeNull();
    expect(requestQueryProblem(new URLSearchParams('page=2'))).toContain('Unsupported parameter page');
    expect(requestQueryProblem(new URLSearchParams('state=lost'))).toContain('state parameter');
    expect(requestQueryProblem(new URLSearchParams('state=open&state=expired'))).toContain('more than once');
    expect(requestQueryProblem(new URLSearchParams('consumer=Bad Name'))).toContain('not a pacticipant handle');
    expect(requestQueryProblem(new URLSearchParams('cursor=abc'))).toContain('cursor');
    expect(requestQueryProblem(new URLSearchParams('provider='))).toContain('empty');
  });

  it('turns the settings form into a body, or says what is wrong', () => {
    const form = {
      cadence: 'hourly' as const,
      stale_threshold_hours: '48',
      max_concurrent_runs: '3',
      request_window_hours: '24',
      republish_requests_enabled: false,
    };
    expect(settingsBodyOf(form)).toEqual({
      body: {
        cadence: 'hourly',
        stale_threshold_hours: 48,
        max_concurrent_runs: 3,
        request_window_hours: 24,
        republish_requests_enabled: false,
      },
    });
    expect(settingsBodyOf({ ...form, max_concurrent_runs: '11' })).toEqual({
      error: 'Concurrent scheduled runs must be a whole number from 1 to 10.',
    });
    expect(settingsBodyOf({ ...form, stale_threshold_hours: '2.5' })).toHaveProperty('error');
  });

  it('turns the override dialog into a body; empty fields inherit', () => {
    const values = { provider: 'ledger-api', consumer: '', cadence: '', threshold: '', target: 'ledger-staging' };
    expect(overrideBodyOf(values)).toEqual({ body: { provider: 'ledger-api', target_ref: 'ledger-staging' } });
    expect(overrideBodyOf({ ...values, target: '' })).toHaveProperty('error');
    expect(overrideBodyOf({ ...values, provider: '' })).toEqual({ error: 'Choose the provider.' });
    expect(overrideBodyOf({ ...values, threshold: '0' })).toHaveProperty('error');
    expect(overrideBodyOf({ ...values, consumer: 'ledger-api' })).toEqual({
      error: 'A pacticipant cannot be its own consumer.',
    });
  });
});

describe('the proxies', () => {
  const settingsUrl = '/api/pact/verification-settings';
  const requestsUrl = '/api/pact/republish-requests';

  it('forwards the settings, overrides and requests to their REST paths', async () => {
    await settingsGet(req(settingsUrl));
    await settingsPut(req(settingsUrl, { method: 'PUT', body: JSON.stringify(SETTINGS) }));
    await overridesGet(req(`${settingsUrl}/overrides`));
    await overridesPut(
      req(`${settingsUrl}/overrides`, {
        method: 'PUT',
        body: JSON.stringify({ provider: 'ledger-api', cadence: 'hourly' }),
      }),
    );
    await overrideDelete(req(`${settingsUrl}/overrides/${ID}`, { method: 'DELETE' }), ctx({ overrideId: ID }));
    await requestsGet(req(`${requestsUrl}?state=open`));
    await requestGet(req(`${requestsUrl}/${ID}`), ctx({ requestId: ID }));
    await acknowledgePost(
      req(`${requestsUrl}/${ID}/acknowledge`, { method: 'POST', body: JSON.stringify({ note: 'Friday' }) }),
      ctx({ requestId: ID }),
    );
    const rest = 'http://rest/v1/tenants/acme';
    expect(forwarded.map((call) => [call.method, call.url, call.body])).toEqual([
      ['GET', `${rest}/pact-verification-settings`, undefined],
      ['PUT', `${rest}/pact-verification-settings`, SETTINGS],
      ['GET', `${rest}/pact-verification-settings/overrides`, undefined],
      ['PUT', `${rest}/pact-verification-settings/overrides`, { provider: 'ledger-api', cadence: 'hourly' }],
      ['DELETE', `${rest}/pact-verification-settings/overrides/${ID}`, undefined],
      ['GET', `${rest}/pact-republish-requests?state=open&limit=25`, undefined],
      ['GET', `${rest}/pact-republish-requests/${ID}`, undefined],
      ['POST', `${rest}/pact-republish-requests/${ID}/acknowledge`, { note: 'Friday' }],
    ]);
  });

  it('refuses bad input without calling REST', async () => {
    const answers = [
      await settingsGet(req(`${settingsUrl}?x=1`)),
      await settingsPut(req(settingsUrl, { method: 'PUT', body: JSON.stringify({ ...SETTINGS, cadence: 'weekly' }) })),
      await settingsPut(req(settingsUrl, { method: 'PUT', body: 'not json' })),
      await overridesPut(
        req(`${settingsUrl}/overrides`, { method: 'PUT', body: JSON.stringify({ provider: 'ledger-api' }) }),
      ),
      await overrideDelete(req(`${settingsUrl}/overrides/7`, { method: 'DELETE' }), ctx({ overrideId: '7' })),
      await requestsGet(req(`${requestsUrl}?label=x`)),
      await requestGet(req(`${requestsUrl}/7`), ctx({ requestId: '7' })),
      await acknowledgePost(
        req(`${requestsUrl}/${ID}/acknowledge`, { method: 'POST', body: JSON.stringify({ note: 'x', by: 'me' }) }),
        ctx({ requestId: ID }),
      ),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 400, 400, 400, 404, 400, 404, 400]);
    expect(((await answers[1].json()) as { error: string }).error).toContain('cadence must be one of');
    expect(forwarded).toHaveLength(0);
  });

  it('passes the sign-in refusal through', async () => {
    tenant = { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
    expect((await settingsGet(req(settingsUrl))).status).toBe(401);
    expect(forwarded).toHaveLength(0);
  });
});

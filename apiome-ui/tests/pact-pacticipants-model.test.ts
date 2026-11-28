/**
 * @jest-environment node
 */
/**
 * The Pacticipants model and its `/api/pact/*` proxies — PFX-5.1 (#6945).
 *
 * * **Model**: query picking (allowed filters, `cursor`, refusals that name the parameter),
 *   handles, formatting, the http(s)-only link rule, the version summary.
 * * **Environment roll-up**: each environment's deployments and supported releases, a failed
 *   sub-read reported on its environment, a refused list kept as REST's status, batched reads.
 * * **Proxies**: each forwards the fixed REST path as the signed-in user, refuses an unknown
 *   parameter or a malformed handle without calling REST, and passes the session's refusal
 *   through (tenant scoping and `pacts:view` are REST's).
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

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  ENVIRONMENT_READ_BATCH,
  RollupError,
  collectPacticipantEnvironments,
  formatWhen,
  isPacticipantHandle,
  pacticipantRoute,
  pickListQuery,
  safeHttpUrl,
  shortVersion,
  versionsSummary,
  withQuery,
  type RestRead,
} from '../lib/pact-pacticipants';
import { GET as listGet } from '../src/app/api/pact/pacticipants/route';
import { GET as labelsGet } from '../src/app/api/pact/labels/route';
import { GET as oneGet } from '../src/app/api/pact/pacticipants/[pacticipant]/route';
import { GET as versionsGet } from '../src/app/api/pact/pacticipants/[pacticipant]/versions/route';
import { GET as branchesGet } from '../src/app/api/pact/pacticipants/[pacticipant]/branches/route';
import { GET as environmentsGet } from '../src/app/api/pact/pacticipants/[pacticipant]/environments/route';

/** A route context for one pacticipant. */
const ctx = (pacticipant: string) => ({ params: Promise.resolve({ pacticipant }) });

/** A GET request to a proxy path. */
const req = (path: string) => new NextRequest(`http://ui${path}`);

/** The REST URL the last forward went to. */
const forwardedUrl = () => forward.mock.calls[forward.mock.calls.length - 1][0];

beforeEach(() => {
  forward.mockClear();
  tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
});

// --- the model --------------------------------------------------------------------------------

describe('pickListQuery', () => {
  it('keeps the allowed filters and the cursor, trimmed', () => {
    const picked = pickListQuery(new URLSearchParams('label=%20tier-1%20&cursor=abc'), ['label']);
    expect(picked).toEqual({ ok: true, query: new URLSearchParams('label=tier-1&cursor=abc') });
  });

  it('refuses an unknown parameter, naming it and what is accepted', () => {
    expect(pickListQuery(new URLSearchParams('limit=500'), ['label'])).toEqual({
      ok: false,
      error: 'Unsupported parameter limit: this list accepts label, cursor.',
    });
  });

  it('refuses an empty, oversized or repeated filter and a bad cursor', () => {
    expect(pickListQuery(new URLSearchParams('label='), ['label'])).toMatchObject({ ok: false });
    expect(pickListQuery(new URLSearchParams(`label=${'x'.repeat(256)}`), ['label'])).toEqual({
      ok: false,
      error: 'The label filter is longer than 255 characters.',
    });
    expect(pickListQuery(new URLSearchParams('tag=a&tag=b'), ['tag'])).toEqual({
      ok: false,
      error: 'The tag parameter is given more than once.',
    });
    expect(pickListQuery(new URLSearchParams(`cursor=${'c'.repeat(2049)}`), [])).toEqual({
      ok: false,
      error: 'The cursor is not valid.',
    });
  });

  it('renders the REST path with the page size first', () => {
    expect(withQuery('pacticipants', new URLSearchParams('label=tier 1'), 50)).toBe(
      'pacticipants?limit=50&label=tier+1',
    );
  });
});

describe('formatting', () => {
  it('accepts only REST handles', () => {
    expect(isPacticipantHandle('billing-service')).toBe(true);
    expect(isPacticipantHandle('Billing Service')).toBe(false);
    expect(isPacticipantHandle('../tenants')).toBe(false);
    expect(isPacticipantHandle('-x')).toBe(false);
  });

  it('prints times in UTC and a dash for nothing', () => {
    expect(formatWhen('2026-11-24T16:40:00Z')).toBe('2026-11-24 16:40 UTC');
    expect(formatWhen(null)).toBe('—');
    expect(formatWhen('not a date')).toBe('—');
  });

  it('cuts a commit SHA to 12 and keeps other numbers', () => {
    expect(shortVersion('3f2a9c1b7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b')).toBe('3f2a9c1b7e6d');
    expect(shortVersion('2.4.0')).toBe('2.4.0');
  });

  it('links only http(s) URLs', () => {
    expect(safeHttpUrl('https://github.com/acme/x')).toBe('https://github.com/acme/x');
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('git@github.com:acme/x.git')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });

  it('summarises the versions and their filter', () => {
    expect(versionsSummary(1, false, {})).toBe('1 version');
    expect(versionsSummary(50, true, { branch: 'main' })).toBe('50+ versions on branch main');
    expect(versionsSummary(2, false, { branch: 'main', tag: 'prod' })).toBe('2 versions on branch main, tagged prod');
  });

  it('routes to a pacticipant by handle', () => {
    expect(pacticipantRoute('billing-service')).toBe('/ade/dashboard/pacts/pacticipants/billing-service');
  });
});

// --- the environment roll-up ------------------------------------------------------------------

/** A broker environment list with `n` environments. */
function environmentList(n: number) {
  return {
    _embedded: {
      environments: Array.from({ length: n }, (_, i) => ({
        uuid: `e-${i}`,
        name: `env-${i}`,
        displayName: `Env ${i}`,
        production: i === 0,
      })),
    },
  };
}

describe('collectPacticipantEnvironments', () => {
  it('reads each environment’s deployments and supported releases of the pacticipant', async () => {
    const paths: string[] = [];
    const read = async (path: string): Promise<RestRead> => {
      paths.push(path);
      if (path === 'pact-broker/environments') return { ok: true, status: 200, body: environmentList(1) };
      if (path.includes('currently-deployed')) {
        return {
          ok: true,
          status: 200,
          body: {
            _embedded: {
              deployedVersions: [
                { applicationInstance: 'eu', createdAt: '2026-11-22T17:00:00Z', _embedded: { version: { number: 'abc' } } },
              ],
            },
          },
        };
      }
      return {
        ok: true,
        status: 200,
        body: { _embedded: { releasedVersions: [{ createdAt: '2026-11-12T10:00:00Z', _embedded: { version: { number: '2.4.0' } } }] } },
      };
    };
    const result = await collectPacticipantEnvironments(read, 'billing-service');
    expect(paths).toContain('pact-broker/environments/e-0/deployed-versions/currently-deployed?pacticipant=billing-service');
    expect(paths).toContain('pact-broker/environments/e-0/released-versions/currently-supported?pacticipant=billing-service');
    expect(result.environments).toEqual([
      {
        uuid: 'e-0',
        name: 'env-0',
        displayName: 'Env 0',
        production: true,
        deployed: [{ version: 'abc', applicationInstance: 'eu', deployedAt: '2026-11-22T17:00:00Z' }],
        released: [{ version: '2.4.0', releasedAt: '2026-11-12T10:00:00Z' }],
      },
    ]);
  });

  it('reports a failed sub-read on its environment instead of dropping it', async () => {
    const read = async (path: string): Promise<RestRead> => {
      if (path === 'pact-broker/environments') return { ok: true, status: 200, body: environmentList(1) };
      if (path.includes('currently-supported')) {
        return { ok: false, status: 500, body: { detail: { code: 'boom', message: 'Database busy' } } };
      }
      return { ok: true, status: 200, body: { _embedded: { deployedVersions: [] } } };
    };
    const [environment] = (await collectPacticipantEnvironments(read, 'billing-service')).environments;
    expect(environment.error).toBe('Releases: Database busy');
    expect(environment.deployed).toEqual([]);
  });

  it('keeps REST’s status when the environment list is refused', async () => {
    const read = async (): Promise<RestRead> => ({ ok: false, status: 403, body: { detail: 'Permission denied' } });
    await expect(collectPacticipantEnvironments(read, 'billing-service')).rejects.toEqual(
      new RollupError(403, 'Permission denied'),
    );
  });

  it(`reads at most ${ENVIRONMENT_READ_BATCH} environments at a time, in REST's order`, async () => {
    let inFlight = 0;
    let peak = 0;
    const read = async (path: string): Promise<RestRead> => {
      if (path === 'pact-broker/environments') return { ok: true, status: 200, body: environmentList(10) };
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      return { ok: true, status: 200, body: {} };
    };
    const result = await collectPacticipantEnvironments(read, 'x');
    expect(result.environments.map((e) => e.uuid)).toEqual(Array.from({ length: 10 }, (_, i) => `e-${i}`));
    expect(peak).toBeLessThanOrEqual(ENVIRONMENT_READ_BATCH * 2);
  });
});

// --- the proxies ------------------------------------------------------------------------------

describe('the /api/pact proxies', () => {
  it('forwards the list with its page size and label, as the signed-in user', async () => {
    await listGet(req('/api/pact/pacticipants?label=tier-1&cursor=c1'));
    expect(forwardedUrl()).toBe('http://rest/v1/tenants/acme/pacticipants?limit=50&label=tier-1&cursor=c1');
    expect(forward.mock.calls[0][1]).toMatchObject({ method: 'GET', user: { user_id: 'u-1' } });
  });

  it('refuses an unknown list parameter without calling REST', async () => {
    const response = await listGet(req('/api/pact/pacticipants?limit=1000'));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      success: false,
      error: 'Unsupported parameter limit: this list accepts label, state, cursor.',
    });
    expect(forward).not.toHaveBeenCalled();
  });

  it('forwards the labels, one pacticipant, its versions and its branches', async () => {
    await labelsGet();
    expect(forwardedUrl()).toBe('http://rest/v1/tenants/acme/pacticipant-labels?limit=100');
    await oneGet(req('/api/pact/pacticipants/billing-service'), ctx('billing-service'));
    expect(forwardedUrl()).toBe('http://rest/v1/tenants/acme/pacticipants/billing-service');
    await versionsGet(req('/api/pact/pacticipants/billing-service/versions?branch=main&tag=prod'), ctx('billing-service'));
    expect(forwardedUrl()).toBe(
      'http://rest/v1/tenants/acme/pacticipants/billing-service/versions?limit=50&branch=main&tag=prod',
    );
    await branchesGet(req('/api/pact/pacticipants/billing-service/branches'), ctx('billing-service'));
    expect(forwardedUrl()).toBe('http://rest/v1/tenants/acme/pacticipants/billing-service/branches?limit=100');
  });

  it('refuses a version filter the list does not accept, and a branch filter on branches', async () => {
    // `state` (live / deleted) is accepted since PFX-8.11 (#7308); `label` is not a version filter.
    const versions = await versionsGet(req('/api/pact/pacticipants/x/versions?label=web'), ctx('x'));
    expect(versions.status).toBe(400);
    const branches = await branchesGet(req('/api/pact/pacticipants/x/branches?branch=main'), ctx('x'));
    expect(branches.status).toBe(400);
    expect(forward).not.toHaveBeenCalled();
  });

  it('answers 404 for a malformed handle without calling REST', async () => {
    for (const [get, path] of [
      [oneGet, ''],
      [versionsGet, '/versions'],
      [branchesGet, '/branches'],
      [environmentsGet, '/environments'],
    ] as const) {
      const response = await get(req(`/api/pact/pacticipants/..%2Fx${path}`), ctx('../x'));
      expect(response.status).toBe(404);
    }
    expect(forward).not.toHaveBeenCalled();
  });

  it('passes the session’s refusal through', async () => {
    tenant = { error: NextResponse.json({ success: false, error: 'No workspace selected' }, { status: 403 }) };
    expect((await listGet(req('/api/pact/pacticipants'))).status).toBe(403);
    expect((await environmentsGet(req('/api/pact/pacticipants/x/environments'), ctx('x'))).status).toBe(403);
    expect(forward).not.toHaveBeenCalled();
  });

  describe('environments', () => {
    const realFetch = global.fetch;
    afterEach(() => {
      global.fetch = realFetch;
    });

    it('rolls the environments up as the signed-in user, in the session tenant', async () => {
      const urls: string[] = [];
      const headers: unknown[] = [];
      global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        urls.push(String(input));
        headers.push(init?.headers);
        const body = String(input).endsWith('/environments') ? environmentList(1) : {};
        return { ok: true, status: 200, json: async () => body } as Response;
      }) as unknown as typeof fetch;
      const response = await environmentsGet(req('/api/pact/pacticipants/billing-service/environments'), ctx('billing-service'));
      expect(response.status).toBe(200);
      expect((await response.json()).environments).toHaveLength(1);
      expect(urls.every((url) => url.startsWith('http://rest/v1/tenants/acme/pact-broker/environments'))).toBe(true);
      expect(headers.every((h) => (h as Record<string, string>).Authorization === 'Bearer session')).toBe(true);
    });

    it('keeps REST’s refusal of the environment list, and says when REST is unreachable', async () => {
      global.fetch = jest.fn(async () => ({
        ok: false,
        status: 403,
        json: async () => ({ detail: 'Permission denied' }),
      })) as unknown as typeof fetch;
      const refused = await environmentsGet(req('/api/pact/pacticipants/x/environments'), ctx('x'));
      expect(refused.status).toBe(403);
      expect(await refused.json()).toEqual({ success: false, error: 'Permission denied' });

      global.fetch = jest.fn(async () => {
        throw new Error('ECONNREFUSED');
      }) as unknown as typeof fetch;
      const down = await environmentsGet(req('/api/pact/pacticipants/x/environments'), ctx('x'));
      expect(down.status).toBe(503);
    });
  });
});

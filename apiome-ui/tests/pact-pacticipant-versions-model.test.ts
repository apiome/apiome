/**
 * @jest-environment node
 */
/**
 * Version management and badges — PFX-8.11 (#7308): the model and the proxies.
 *
 * * **Versions model**: the views, the search over the loaded versions and the note that says when
 *   it does not cover every version, where each version runs, why a deployed version cannot be
 *   deleted, the Unverified view's version numbers from the matrix, what a bulk action reports
 *   (every version not changed is named with its reason), the empty states, and the commands.
 * * **Badges model**: the For choices, the REST paths, the Markdown in each style, the proxy's
 *   query checks (each failure path), the shields state.
 * * **Proxies**: forward as the signed-in user in the session tenant; refuse a bad number, a bad
 *   tag, `force` and unknown parameters without calling REST; read the public badge anonymously
 *   and keep REST's 404.
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
  getRestApiBaseUrl: () => 'http://rest/v1',
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { pactCommandSurfaces } from '../lib/pact-commands';
import type { MatrixRow } from '../lib/pact-matrix';
import type { PacticipantEnvironment, PacticipantVersion } from '../lib/pact-pacticipants';
import {
  availableViews,
  bulkOutcome,
  deleteBlock,
  deletedBy,
  emptyVersionsStatement,
  inBatches,
  matchesSearch,
  restoreBlock,
  runningInByVersion,
  searchScopeNote,
  tagCommandAction,
  tagPathSegment,
  tagProblem,
  unreadEnvironments,
  unverifiedVersionNumbers,
  versionCanIDeployHref,
  versionCommandAction,
  versionMatrixHref,
  versionNumberProblem,
  versionProxyPath,
  viewLabel,
} from '../lib/pact-pacticipant-versions';
import {
  NO_PROJECT_NOTE,
  badgeChoices,
  badgeMarkdown,
  badgePath,
  badgeSurfaces,
  notPublicNote,
  parseBadgeQuery,
  statusFromShields,
  svgDataUrl,
} from '../lib/pact-badges';
import type { PacticipantPact } from '../lib/pact-detail';
import { GET as versionGet, DELETE as versionDelete } from '../src/app/api/pact/pacticipants/[pacticipant]/versions/[number]/route';
import { POST as versionRestore } from '../src/app/api/pact/pacticipants/[pacticipant]/versions/[number]/restore/route';
import { PUT as tagPut } from '../src/app/api/pact/pacticipants/[pacticipant]/versions/[number]/tags/[...tag]/route';
import { GET as versionsList } from '../src/app/api/pact/pacticipants/[pacticipant]/versions/route';
import { GET as badgeGet } from '../src/app/api/pact/badges/route';

const VERSION = (number: string, extra: Partial<PacticipantVersion> = {}): PacticipantVersion => ({
  id: `v-${number}`,
  pacticipant_id: 'p-1',
  number,
  seq: 1,
  branches: ['main'],
  tags: [],
  ...extra,
});

const ENVIRONMENTS: PacticipantEnvironment[] = [
  {
    uuid: 'e-1',
    name: 'production',
    displayName: 'Production',
    production: true,
    deployed: [{ version: '3.3.2', applicationInstance: null, deployedAt: null }],
    released: [],
  },
  {
    uuid: 'e-2',
    name: 'staging',
    displayName: 'Staging',
    production: false,
    deployed: [
      { version: '3.3.2', applicationInstance: 'a', deployedAt: null },
      { version: '3.3.2', applicationInstance: 'b', deployedAt: null },
    ],
    released: [{ version: '3.2.0', releasedAt: null }],
  },
  { uuid: 'e-3', name: 'qa', displayName: 'QA', production: false, deployed: [], released: [], error: 'Forbidden' },
];

describe('the versions model', () => {
  it('offers the main-branch chip only when there is a main branch', () => {
    expect(availableViews('main')).toEqual(['all', 'main', 'deployed', 'unverified', 'deleted']);
    expect(availableViews(null)).toEqual(['all', 'deployed', 'unverified', 'deleted']);
    expect(viewLabel('main', 'trunk')).toBe('trunk');
    expect(viewLabel('main', null)).toBe('Main branch');
    expect(viewLabel('deleted', 'main')).toBe('Deleted');
  });

  it('refuses a number or tag REST cannot address', () => {
    expect(versionNumberProblem('')).toBe('Give the version number.');
    expect(versionNumberProblem('1/2')).toMatch(/one path segment/);
    expect(versionNumberProblem('x'.repeat(256))).toMatch(/at most 255/);
    expect(versionNumberProblem('a\u0001')).toMatch(/control/);
    expect(versionNumberProblem('3.3.2+77c0aa1')).toBeNull();
    expect(tagProblem(' prod')).toMatch(/leading or trailing/);
    expect(tagProblem('')).toBe('Give the tag.');
    expect(tagProblem('feat/new-invoice')).toBeNull();
  });

  it('builds the REST paths, keeping a tag’s slashes', () => {
    expect(versionProxyPath('pacticipants/orders-ui', '3.3.2+a')).toBe('pacticipants/orders-ui/versions/3.3.2%2Ba');
    expect(versionProxyPath('pacticipants/orders-ui', '1', 'restore')).toBe('pacticipants/orders-ui/versions/1/restore');
    expect(versionProxyPath(null, '1')).toBeNull();
    expect(versionProxyPath('pacticipants/x', 'a/b')).toBeNull();
    expect(tagPathSegment('feat/new invoice')).toBe('feat/new%20invoice');
  });

  it('searches number, branches and tags, and says when it covers only the loaded versions', () => {
    const version = VERSION('3.4.0+a1c9e02', { branches: ['feature/credit-notes'], tags: ['dev'] });
    expect(matchesSearch(version, '')).toBe(true);
    expect(matchesSearch(version, 'A1C9')).toBe(true);
    expect(matchesSearch(version, 'credit')).toBe(true);
    expect(matchesSearch(version, 'dev')).toBe(true);
    expect(matchesSearch(version, 'prod')).toBe(false);
    expect(searchScopeNote('dev', 50, true)).toBe('Searching the 50 versions loaded so far. Load more to search further.');
    expect(searchScopeNote('dev', 50, false)).toBeNull();
    expect(searchScopeNote(' ', 50, true)).toBeNull();
  });

  it('knows where each version runs, once per environment', () => {
    const running = runningInByVersion(ENVIRONMENTS);
    expect(running.get('3.3.2')).toEqual([
      { environment: 'Production', production: true, kind: 'deployed' },
      { environment: 'Staging', production: false, kind: 'deployed' },
    ]);
    expect(running.get('3.2.0')).toEqual([{ environment: 'Staging', production: false, kind: 'released' }]);
    expect(unreadEnvironments(ENVIRONMENTS)).toEqual(['QA']);
  });

  it('blocks deleting a version that runs somewhere', () => {
    const running = runningInByVersion(ENVIRONMENTS);
    expect(deleteBlock('3.2.0', running.get('3.2.0'))).toBe('3.2.0 is running in Staging. Record its undeployment first.');
    expect(deleteBlock('3.3.2', running.get('3.3.2'))).toBe(
      '3.3.2 is running in Production and Staging. Record its undeployment first.',
    );
    expect(deleteBlock('3.3.1', running.get('3.3.1'))).toBeNull();
  });

  it('finds the consumer versions with no verification result, each once', () => {
    const row = (consumer: string, version: string | null, verified: boolean): MatrixRow =>
      ({
        consumer: { name: consumer, slug: consumer, version, branch: null },
        provider: { name: 'billing', slug: 'billing', version: verified ? '9' : null, branch: null },
        publishedAt: null,
        verification: verified
          ? { success: true, verifiedAt: null, kind: 'native', pending: null, wip: false, providerContractVerified: null }
          : null,
        reason: { code: 'x', text: '' },
        ignored: false,
      }) as MatrixRow;
    const rows = [
      row('orders-ui', '3.4.0', false),
      row('orders-ui', '3.4.0', false),
      row('orders-ui', '3.3.2', true),
      row('other', '1.0.0', false),
      row('orders-ui', null, false),
    ];
    expect(unverifiedVersionNumbers(rows, 'orders-ui')).toEqual(['3.4.0']);
  });

  it('reports a bulk action, naming every version it did not change', () => {
    expect(bulkOutcome('tag', { done: ['1', '2'], failed: [], skipped: [] }, 'prod')).toEqual({
      tone: 'ok',
      text: 'Tagged 2 versions with prod.',
    });
    const mixed = bulkOutcome('delete', {
      done: ['1'],
      failed: [{ number: '2', error: 'Permission denied' }],
      skipped: [{ number: '3', reason: '3 is running in Production. Record its undeployment first.' }],
    });
    expect(mixed.tone).toBe('danger');
    expect(mixed.text).toBe(
      'Deleted 1 version. They can be restored from Deleted until they are purged. Not changed — 3: 3 is running in Production. Record its undeployment first. 2: Permission denied',
    );
    expect(bulkOutcome('tag', { done: [], failed: [{ number: '1', error: 'x' }], skipped: [] }, 'prod').text).toBe(
      'No version was tagged with prod. Not changed — 1: x',
    );
  });

  it('runs steps a few at a time, keeping the order', async () => {
    let running = 0;
    let most = 0;
    const answers = await inBatches([1, 2, 3, 4, 5, 6], async (n) => {
      running += 1;
      most = Math.max(most, running);
      await new Promise((resolve) => setTimeout(resolve, 1));
      running -= 1;
      return n * 10;
    }, 2);
    expect(answers).toEqual([10, 20, 30, 40, 50, 60]);
    expect(most).toBe(2);
  });

  it('says what each empty view means', () => {
    expect(emptyVersionsStatement('Orders UI', 'all', false)).toBe(
      'Nothing published under Orders UI yet. Publish a pact, or record one from a mock.',
    );
    expect(emptyVersionsStatement('Orders UI', 'deleted', false)).toBe('No deleted version can be restored.');
    expect(emptyVersionsStatement('Orders UI', 'all', true)).toBe('No loaded version matches the search.');
  });

  it('says who deleted a version and why a restore is not offered', () => {
    expect(deletedBy({ ...VERSION('1'), delete_cause: 'version', deleted_by_label: 'ada', delete_reason: 'bad build' })).toBe(
      'by ada — bad build',
    );
    expect(deletedBy({ ...VERSION('1'), delete_cause: 'retention' })).toBe('by a retention run');
    expect(restoreBlock({ ...VERSION('1'), delete_cause: 'pacticipant' })).toMatch(/restore the pacticipant/);
    expect(restoreBlock({ ...VERSION('1'), delete_cause: 'version' })).toBeNull();
  });

  it('links a version to its matrix and its can-i-deploy question', () => {
    expect(versionMatrixHref('orders-ui', '3.3.2')).toBe(
      '/ade/dashboard/pacts/matrix?q%5B0%5D%5Bpacticipant%5D=orders-ui&q%5B0%5D%5Bversion%5D=3.3.2&limit=100',
    );
    expect(versionCanIDeployHref('orders-ui', '3.3.2')).toBe(
      '/ade/dashboard/pacts/can-i-deploy?pacticipant=orders-ui&version=3.3.2',
    );
  });

  it('writes the same actions as apiome pact commands and REST requests', () => {
    const who = { slug: 'orders-ui', name: 'Orders UI' };
    // One line per flag in the block; compare as one line.
    const flat = (surfaces: ReturnType<typeof pactCommandSurfaces>) =>
      surfaces.map((surface) => ({ ...surface, text: surface.text?.replace(/ \\\n\s*/g, ' ') ?? null }));
    const tag = flat(pactCommandSurfaces(tagCommandAction(who, '3.3.2', 'feat/x', 'acme')));
    expect(tag.find((s) => s.id === 'apiome')?.text).toContain(
      "apiome pact create-version-tag --pacticipant 'Orders UI' --version 3.3.2 --tag feat/x",
    );
    expect(tag.find((s) => s.id === 'pact-cli')?.text).toContain('pact-broker create-version-tag');
    expect(tag.find((s) => s.id === 'rest')?.text).toContain(
      'PUT /v1/tenants/acme/pacticipants/orders-ui/versions/3.3.2/tags/feat/x',
    );
    const del = flat(pactCommandSurfaces(versionCommandAction('delete', who, '3.3.1', 'bad build')));
    expect(del.find((s) => s.id === 'apiome')?.text).toContain("delete-version --pacticipant 'Orders UI' --version 3.3.1 --reason 'bad build'");
    expect(del.find((s) => s.id === 'rest')?.text).toContain(
      'DELETE /v1/tenants/{tenant}/pacticipants/orders-ui/versions/3.3.1?reason=bad%20build',
    );
    expect(del.find((s) => s.id === 'apiome')?.text).not.toContain('force');
    const restore = flat(pactCommandSurfaces(versionCommandAction('restore', who, '3.3.1')));
    expect(restore.find((s) => s.id === 'apiome')?.text).toContain('restore-version');
    expect(restore.find((s) => s.id === 'rest')?.text).toContain('POST /v1/tenants/{tenant}/pacticipants/orders-ui/versions/3.3.1/restore');
  });
});

describe('the badges model', () => {
  const pact = (consumer: string, provider: string): PacticipantPact => ({
    consumer: { name: consumer.toUpperCase(), slug: consumer },
    provider: { name: provider.toUpperCase(), slug: provider },
    latestVersion: '1',
    publishedAt: null,
    latestVerification: null,
  });

  it('offers the pacticipant, then each pair once', () => {
    const choices = badgeChoices({ slug: 'orders-ui', name: 'Orders UI' }, [
      pact('orders-ui', 'billing'),
      pact('orders-ui', 'billing'),
      pact('web', 'orders-ui'),
    ]);
    expect(choices.map((c) => c.label)).toEqual(['Orders UI (all its pacts)', 'ORDERS-UI → BILLING', 'WEB → ORDERS-UI']);
    expect(choices[1].target).toEqual({ kind: 'pair', provider: 'billing', consumer: 'orders-ui' });
  });

  it('builds the public paths and the Markdown in each style', () => {
    const one = { kind: 'pacticipant' as const, slug: 'orders-ui' };
    const pair = { kind: 'pair' as const, provider: 'billing', consumer: 'orders-ui' };
    expect(badgePath('acme', 'ledger', one, 'badge.svg')).toBe(
      '/browse/tenants/acme/projects/ledger/pact-badges/pacticipants/orders-ui/badge.svg',
    );
    expect(badgePath('acme', 'ledger', pair, 'shields.json')).toBe(
      '/browse/tenants/acme/projects/ledger/pact-badges/pacts/provider/billing/consumer/orders-ui/shields.json',
    );
    expect(badgeMarkdown('https://api.example.com/v1/', 'acme', 'ledger', one, 'svg')).toBe(
      '![pact](https://api.example.com/v1/browse/tenants/acme/projects/ledger/pact-badges/pacticipants/orders-ui/badge.svg)',
    );
    expect(badgeMarkdown('https://api.example.com/v1', 'acme', 'ledger', one, 'shields')).toBe(
      '![pact](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.example.com%2Fv1%2Fbrowse%2Ftenants%2Facme%2Fprojects%2Fledger%2Fpact-badges%2Fpacticipants%2Forders-ui%2Fshields.json)',
    );
    expect(badgeSurfaces('https://api.example.com/v1', 'acme', 'ledger', one).map((s) => s.label)).toEqual([
      'Markdown',
      'shields.io',
      'Image URL',
    ]);
  });

  it('checks the proxy query, naming each refusal', () => {
    const parse = (query: string) => parseBadgeQuery(new URLSearchParams(query));
    expect(parse('project=ledger&pacticipant=orders-ui')).toEqual({
      ok: true,
      project: 'ledger',
      target: { kind: 'pacticipant', slug: 'orders-ui' },
    });
    expect(parse('project=ledger&provider=billing&consumer=orders-ui')).toMatchObject({ ok: true });
    expect(parse('project=ledger&pacticipant=a&branch=main')).toEqual({
      ok: false,
      error: 'Unsupported parameter branch: send project and pacticipant, or provider and consumer.',
    });
    expect(parse('project=ledger&pacticipant=a&pacticipant=b')).toMatchObject({ error: 'The pacticipant parameter is given more than once.' });
    expect(parse('project=Not%20a%20slug&pacticipant=a')).toMatchObject({ ok: false });
    expect(parse('project=ledger&pacticipant=a&provider=b')).toMatchObject({ error: 'Send pacticipant, or provider and consumer, not both.' });
    expect(parse('project=ledger&provider=b')).toMatchObject({ error: 'Send pacticipant, or both provider and consumer.' });
    expect(parse('project=ledger&pacticipant=Not%20A')).toMatchObject({ error: 'The pacticipant is not a handle.' });
    expect(parse('project=ledger&provider=B%20x&consumer=c')).toMatchObject({ ok: false });
  });

  it('reads the shields state and builds the preview source', () => {
    expect(statusFromShields({ message: 'failing' })).toBe('failing');
    expect(statusFromShields({ message: 'odd' })).toBe('unknown');
    expect(statusFromShields(null)).toBe('unknown');
    expect(svgDataUrl('<svg/>')).toBe('data:image/svg+xml;charset=utf-8,%3Csvg%2F%3E');
    expect(NO_PROJECT_NOTE).toMatch(/public project/);
    expect(notPublicNote('Ledger')).toMatch(/Ledger serves no badge/);
  });
});

describe('the version proxies', () => {
  const ctx = (params: Record<string, unknown>) => ({ params: Promise.resolve(params) }) as never;
  const req = (path: string, method = 'GET') => new NextRequest(`http://ui${path}`, { method });
  const rest = 'http://rest/v1/tenants/acme/pacticipants/orders-ui/versions';

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
  });

  it('forwards read, delete, restore, tag and the deleted list to REST', async () => {
    const one = ctx({ pacticipant: 'orders-ui', number: '3.3.2+a' });
    await versionGet(req('/x'), one);
    await versionDelete(req('/x?reason=bad%20build', 'DELETE'), one);
    await versionDelete(req('/x', 'DELETE'), one);
    await versionRestore(req('/x', 'POST'), one);
    await tagPut(req('/x', 'PUT'), ctx({ pacticipant: 'orders-ui', number: '3.3.2+a', tag: ['feat', 'new invoice'] }));
    await versionsList(req('/api/pact/pacticipants/orders-ui/versions?state=deleted'), ctx({ pacticipant: 'orders-ui' }));
    expect(forwarded.map(({ method, url }) => `${method} ${url}`)).toEqual([
      `GET ${rest}/3.3.2%2Ba`,
      `DELETE ${rest}/3.3.2%2Ba?reason=bad%20build`,
      `DELETE ${rest}/3.3.2%2Ba`,
      `POST ${rest}/3.3.2%2Ba/restore`,
      `PUT ${rest}/3.3.2%2Ba/tags/feat/new%20invoice`,
      `GET ${rest}?limit=50&state=deleted`,
    ]);
  });

  it('refuses force, unknown parameters, bad numbers, bad tags and bad handles without calling REST', async () => {
    const one = ctx({ pacticipant: 'orders-ui', number: '3.3.2' });
    const answers = [
      await versionDelete(req('/x?force=true', 'DELETE'), one),
      await versionDelete(req('/x?reason=a&reason=b', 'DELETE'), one),
      await versionDelete(req('/x?purge=1', 'DELETE'), one),
      await versionDelete(req(`/x?reason=${'x'.repeat(501)}`, 'DELETE'), one),
      await versionGet(req('/x'), ctx({ pacticipant: 'orders-ui', number: 'a/b' })),
      await versionGet(req('/x'), ctx({ pacticipant: 'Not A Handle', number: '1' })),
      await versionRestore(req('/x', 'POST'), ctx({ pacticipant: 'orders-ui', number: '' })),
      await versionRestore(req('/x', 'POST'), ctx({ pacticipant: 'Not A Handle', number: '1' })),
      await tagPut(req('/x', 'PUT'), ctx({ pacticipant: 'orders-ui', number: '1', tag: [' prod'] })),
      await tagPut(req('/x', 'PUT'), ctx({ pacticipant: 'orders-ui', number: 'a/b', tag: ['prod'] })),
      await tagPut(req('/x', 'PUT'), ctx({ pacticipant: 'Not A Handle', number: '1', tag: ['prod'] })),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 400, 400, 400, 400, 404, 400, 404, 400, 400, 404]);
    expect(((await answers[0].json()) as { error: string }).error).toMatch(/force is not accepted: record the version’s undeployment first/);
    expect(((await answers[2].json()) as { error: string }).error).toBe('Unknown parameter: purge. Send only reason.');
    expect(forwarded).toEqual([]);
  });
});

describe('the badge proxy', () => {
  const realFetch = global.fetch;
  const fetched: string[] = [];
  let answers: Record<string, { status: number; body: string }>;

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    fetched.length = 0;
    answers = {};
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      fetched.push(url);
      expect(init?.headers).toBeUndefined(); // anonymous, as a README reader
      const answer = answers[url] ?? { status: 404, body: '{"detail":"No pact badge found."}' };
      return new Response(answer.body, { status: answer.status });
    }) as unknown as typeof fetch;
  });

  afterAll(() => {
    global.fetch = realFetch;
  });

  const base = 'http://rest/v1/browse/tenants/acme/projects/ledger/pact-badges/pacticipants/orders-ui';

  it('answers the SVG REST serves and its state', async () => {
    answers[`${base}/badge.svg`] = { status: 200, body: '<svg role="img"/>' };
    answers[`${base}/shields.json`] = { status: 200, body: '{"message":"verified"}' };
    const response = await badgeGet(new NextRequest('http://ui/api/pact/badges?project=ledger&pacticipant=orders-ui'));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ tenant: 'acme', status: 'verified', svg: '<svg role="img"/>' });
    expect(fetched.sort()).toEqual([`${base}/badge.svg`, `${base}/shields.json`]);
  });

  it('keeps REST’s 404 and refuses a bad query without calling REST', async () => {
    const missing = await badgeGet(new NextRequest('http://ui/api/pact/badges?project=ledger&pacticipant=orders-ui'));
    expect(missing.status).toBe(404);
    expect(((await missing.json()) as { error: string }).error).toMatch(/not public/);
    fetched.length = 0;
    const bad = await badgeGet(new NextRequest('http://ui/api/pact/badges?project=ledger&tag=prod'));
    expect(bad.status).toBe(400);
    expect(fetched).toEqual([]);
  });

  it('says when REST cannot be reached, and refuses without a session', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const down = await badgeGet(new NextRequest('http://ui/api/pact/badges?project=ledger&pacticipant=orders-ui'));
    expect(down.status).toBe(503);
    tenant = { error: NextResponse.json({ success: false, error: 'Sign in' }, { status: 401 }) };
    const anonymous = await badgeGet(new NextRequest('http://ui/api/pact/badges?project=ledger&pacticipant=orders-ui'));
    expect(anonymous.status).toBe(401);
  });
});

/**
 * @jest-environment node
 */
/**
 * The pact model and its `/api/pact/*` proxies — PFX-5.2 (#6946).
 *
 * * **Reading a pact**: V2 `providerState`, V3 `providerStates` and `messages`, V4 typed
 *   interactions (HTTP, asynchronous and synchronous messages, wrapped bodies); an unknown type or a
 *   non-object entry is kept and marked, never dropped; duplicate identities get distinct keys.
 * * **Diff vs previous**: added, removed, changed (with value paths, parameters of states,
 *   truncation) and unchanged interactions.
 * * **History and verification status**: matrix rows grouped per consumer version (the other
 *   direction left out), the verdict of the newest result, the pacticipant's integrations.
 * * **The previous different pact**: found, first, unchanged, scan limit, not in history, a gone
 *   pact skipped, a failed read reported with REST's status.
 * * **Proxies**: each forwards the fixed REST path as the signed-in user, refuses an unknown,
 *   repeated or bad parameter and a malformed handle without calling REST, and passes the
 *   session's refusal through (tenant scoping and `pacts:view` are REST's).
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

const forward = jest.fn<(...args: unknown[]) => Promise<NextResponse>>(async () =>
  NextResponse.json({ ok: true }),
);
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

import fixture from './fixtures/pact-detail.json';
import {
  MAX_CHANGES_PER_INTERACTION,
  PREVIOUS_SCAN_LIMIT,
  diffPacts,
  diffSummary,
  findPreviousDistinct,
  formatValue,
  httpRequest,
  httpResponse,
  interactionChanges,
  interactionCounts,
  interactionStatuses,
  interactionSummary,
  latestVerification,
  messageParts,
  pactProxyPath,
  pactRoute,
  pacticipantPactsProxyPath,
  pairHistoryProxyPath,
  parsePact,
  parsePacticipantPacts,
  parsePairHistory,
  pickPactQuery,
  shortSha,
  verificationVerdict,
  versionProblem,
  type VerificationRow,
} from '../lib/pact-detail';
import { RollupError, type RestRead } from '../lib/pact-pacticipants';
import { GET as pactGet } from '../src/app/api/pact/pacts/[provider]/[consumer]/route';
import { GET as historyGet } from '../src/app/api/pact/pacts/[provider]/[consumer]/history/route';
import { GET as previousGet } from '../src/app/api/pact/pacts/[provider]/[consumer]/previous/route';
import { GET as pacticipantPactsGet } from '../src/app/api/pact/pacticipants/[pacticipant]/pacts/route';

/** A route context for one integration. */
const pair = (provider: string, consumer: string) => ({
  params: Promise.resolve({ provider, consumer }),
});

/** A GET request to a proxy path. */
const req = (path: string) => new NextRequest(`http://ui${path}`);

/** The REST URL the last forward went to. */
const forwardedUrl = () => forward.mock.calls[forward.mock.calls.length - 1][0];

beforeEach(() => {
  forward.mockClear();
  tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
});

// --- reading a pact ------------------------------------------------------------------------------

describe('parsePact', () => {
  it('reads a V3 pact: facts, HTTP interactions and messages, states with parameters', () => {
    const pact = parsePact(fixture.current);
    expect(pact).toMatchObject({
      consumerName: 'Billing Service',
      providerName: 'Ledger API',
      consumerVersion: '1.4.0',
      sha: fixture.shaA,
      specification: '3.0.0',
      publishedAt: '2026-11-24T16:40:00Z',
    });
    expect(pact.interactions.map((i) => i.kind)).toEqual(['http', 'http', 'http', 'message']);
    expect(pact.interactions[0].states).toEqual([
      { name: 'invoice INV-42 exists', params: { id: 'INV-42' } },
    ]);
    expect(pact.interactions[1].states).toEqual([{ name: 'account ACC-7 is open', params: null }]);
    expect(pact.interactions[2].states).toEqual([]);
    expect(interactionCounts(pact.interactions)).toBe('3 HTTP, 1 message');
  });

  it('reads a V2 providerState and falls back to the links for the names', () => {
    const pact = parsePact({
      interactions: [
        {
          description: 'd',
          providerState: 'a thing exists',
          request: {},
          response: { status: 204 },
        },
      ],
      metadata: { pactSpecification: { version: '2.0.0' } },
      _links: { 'pb:consumer': { name: 'C' }, 'pb:provider': { name: 'P' } },
    });
    expect(pact.consumerName).toBe('C');
    expect(pact.providerName).toBe('P');
    expect(pact.interactions[0].states).toEqual([{ name: 'a thing exists', params: null }]);
    expect(interactionSummary(pact.interactions[0])).toBe('GET / → 204');
  });

  it('reads V4 typed interactions, wrapped bodies and pending, and keeps an unknown type marked', () => {
    const pact = parsePact({
      interactions: [
        {
          type: 'Synchronous/HTTP',
          description: 'h',
          pending: true,
          request: { method: 'post', path: '/x', query: { a: ['1', '2'] } },
          response: {
            status: 200,
            body: { content: { ok: true }, contentType: 'application/json' },
          },
        },
        {
          type: 'Asynchronous/Messages',
          description: 'm',
          contents: { content: { e: 1 }, contentType: 'application/json' },
        },
        {
          type: 'Synchronous/Messages',
          description: 's',
          request: { contents: 'ping' },
          response: [{ contents: 'pong' }, { contents: 'pong again', metadata: { n: 2 } }],
        },
        { type: 'Synchronous/Plugin', description: 'p', plugin: 'grpc' },
      ],
      metadata: { pactSpecification: { version: '4.0' } },
    });
    const [http, message, sync, unknown] = pact.interactions;
    expect(http.pending).toBe(true);
    expect(httpRequest(http.raw).line).toBe('POST /x?a=1&a=2');
    expect(httpResponse(http.raw)).toMatchObject({
      line: '200',
      body: { ok: true },
      hasBody: true,
    });
    expect(messageParts(message).request.contents).toEqual({ e: 1 });
    expect(messageParts(sync).responses.map((r) => r.contents)).toEqual(['pong', 'pong again']);
    expect(messageParts(sync).responses[1].metadata).toEqual({ n: 2 });
    expect(interactionSummary(sync)).toBe('Request with 2 responses');
    expect(unknown.kind).toBe('unknown');
    expect(unknown.typeLabel).toContain('Synchronous/Plugin');
    expect(unknown.raw.plugin).toBe('grpc');
    expect(interactionCounts(pact.interactions)).toBe(
      '1 HTTP, 1 message, 1 synchronous message, 1 not drawn',
    );
  });

  it('keeps an entry that is not an object, and one with nothing to draw', () => {
    const pact = parsePact({ interactions: ['oops', { description: 'bare' }] });
    expect(pact.interactions.map((i) => i.kind)).toEqual(['unknown', 'unknown']);
    expect(pact.interactions[0].raw).toEqual({ value: 'oops' });
  });

  it('gives interactions with the same identity distinct keys', () => {
    const one = { description: 'same', request: {}, response: {} };
    const keys = parsePact({ interactions: [one, one] }).interactions.map((i) => i.key);
    expect(new Set(keys).size).toBe(2);
    expect(keys[1]).toMatch(/#2$/);
  });

  it('reads an empty or malformed document without throwing', () => {
    expect(parsePact(null)).toMatchObject({ interactions: [], sha: null, specification: null });
    expect(interactionCounts([])).toBe('No interactions');
  });

  it('separates a missing body from an empty one and prints values', () => {
    expect(httpRequest({ request: { method: 'GET', path: '/a' } }).hasBody).toBe(false);
    expect(httpResponse({ response: { body: '' } })).toMatchObject({
      hasBody: true,
      body: '',
      line: '—',
    });
    expect(formatValue('plain')).toBe('plain');
    expect(formatValue({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(formatValue(undefined)).toBe('');
  });
});

// --- diff vs previous ------------------------------------------------------------------------------

describe('diffPacts', () => {
  it('lists added, changed (with values) and removed interactions', () => {
    const diff = diffPacts(parsePact(fixture.current), parsePact(fixture.previous));
    expect(diff.added.map((i) => i.description)).toEqual(['a request for a missing invoice']);
    expect(diff.removed.map((i) => i.description)).toEqual(['a request to refund an invoice']);
    expect(diff.changed).toHaveLength(1);
    expect(diff.changed[0].changes).toEqual([
      { path: 'response.body.amount', before: '120.50', after: 120.5 },
      { path: 'response.body.currency', after: 'EUR' },
    ]);
    expect(diff.unchanged).toBe(2);
    expect(diffSummary(diff)).toBe('1 added, 1 changed, 1 removed, 2 unchanged');
    const statuses = interactionStatuses(diff);
    expect([...statuses.values()].sort()).toEqual(['added', 'changed']);
    expect(interactionStatuses(null).size).toBe(0);
  });

  it('compares provider state parameters, array items and odd names', () => {
    const before = parsePact({
      interactions: [
        {
          description: 'd',
          providerStates: [{ name: 's', params: { id: 1 } }],
          request: { headers: { 'X-Odd Name': 'a' } },
          response: { body: [1, 2] },
        },
      ],
    }).interactions[0];
    const after = parsePact({
      interactions: [
        {
          description: 'd',
          providerStates: [{ name: 's', params: { id: 2 } }],
          request: { headers: { 'X-Odd Name': 'b' } },
          response: { body: [1] },
        },
      ],
    }).interactions[0];
    expect(interactionChanges(before, after).changes).toEqual([
      { path: 'request.headers["X-Odd Name"]', before: 'a', after: 'b' },
      { path: 'response.body[1]', before: 2 },
      { path: 'providerStates.s.id', before: 1, after: 2 },
    ]);
  });

  it('caps the changes of one interaction and says so', () => {
    const wide = (offset: number) => ({
      description: 'w',
      request: {},
      response: {
        body: Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`k${i}`, i + offset])),
      },
    });
    const [before] = parsePact({ interactions: [wide(0)] }).interactions;
    const [after] = parsePact({ interactions: [wide(1)] }).interactions;
    const { changes, truncated } = interactionChanges(before, after);
    expect(changes).toHaveLength(MAX_CHANGES_PER_INTERACTION);
    expect(truncated).toBe(true);
  });

  it('treats a renamed interaction as removed and added', () => {
    const diff = diffPacts(
      parsePact({ interactions: [{ description: 'new name', request: {}, response: {} }] }),
      parsePact({ interactions: [{ description: 'old name', request: {}, response: {} }] }),
    );
    expect(diff.added).toHaveLength(1);
    expect(diff.removed).toHaveLength(1);
  });
});

// --- history and verification status -----------------------------------------------------------------

describe('parsePairHistory', () => {
  it('groups the rows per consumer version, newest first, leaving the other direction out', () => {
    const history = parsePairHistory(fixture.history, 'billing-service', 'ledger-api');
    expect(history.entries.map((e) => e.consumerVersion)).toEqual(['1.4.0', '1.3.2', '1.3.1']);
    expect(history.truncated).toBe(false);
    const [latest] = history.entries;
    expect(latest).toMatchObject({
      branch: 'main',
      tags: ['prod'],
      publishedAt: '2026-11-24T16:40:00Z',
    });
    expect(latest.verifications.map((v) => [v.providerVersion, v.success, v.pending])).toEqual([
      ['2.8.0', true, null],
      ['2.7.1', false, true],
    ]);
    expect(history.entries[2].verifications[0].kind).toBe('bidirectional');
  });

  it('says when the matrix returned as many rows as asked for', () => {
    expect(parsePairHistory(fixture.history, 'billing-service', 'ledger-api', 5).truncated).toBe(
      true,
    );
    expect(parsePairHistory({}, 'a', 'b')).toEqual({ entries: [], truncated: false });
  });
});

describe('verification verdicts', () => {
  const row = (
    success: boolean,
    verifiedAt: string,
    pending: boolean | null = null,
  ): VerificationRow => ({
    providerVersion: '1',
    providerBranch: null,
    success,
    verifiedAt,
    kind: 'native',
    pending,
    wip: false,
  });

  it('takes the newest result by time', () => {
    const latest = latestVerification([
      row(false, '2026-11-01T00:00:00Z'),
      row(true, '2026-11-02T00:00:00Z'),
    ]);
    expect(latest?.success).toBe(true);
    expect(latestVerification([])).toBeNull();
  });

  it('reads verified, failed, failed while pending and unverified', () => {
    expect(verificationVerdict(row(true, 'x'))).toBe('verified');
    expect(verificationVerdict(row(false, 'x'))).toBe('failed');
    expect(verificationVerdict(row(false, 'x', true))).toBe('failed-pending');
    expect(verificationVerdict(null)).toBe('unverified');
  });
});

describe('parsePacticipantPacts', () => {
  it('keeps one integration per consumer and provider with its newest version and verdict', () => {
    const { pacts, truncated } = parsePacticipantPacts(fixture.pacticipantPacts);
    expect(truncated).toBe(false);
    expect(pacts.map((p) => [p.consumer.slug, p.provider.slug, p.latestVersion])).toEqual([
      ['billing-service', 'ledger-api', '1.4.0'],
      ['billing-service', 'notification-service', '1.4.0'],
      ['mobile-app', 'billing-service', '3.2.0'],
    ]);
    expect(pacts[0].latestVerification?.success).toBe(true);
    expect(pacts[1].latestVerification).toBeNull();
    expect(pacts[2].latestVerification?.success).toBe(false);
  });
});

// --- routes, paths, parameters -------------------------------------------------------------------------

describe('paths and parameters', () => {
  it('builds the page route and the REST paths', () => {
    expect(pactRoute('billing-service', 'ledger-api')).toBe(
      '/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api',
    );
    expect(pactRoute('a', 'b', '1.0 rc')).toBe(
      '/ade/dashboard/pacts/pacticipants/a/pacts/b?version=1.0%20rc',
    );
    expect(pactProxyPath('p', 'c', null)).toBe('pact-broker/pacts/provider/p/consumer/c/latest');
    expect(pactProxyPath('p', 'c', '1.0+b')).toBe(
      'pact-broker/pacts/provider/p/consumer/c/version/1.0%2Bb',
    );
    expect(decodeURIComponent(pairHistoryProxyPath('p', 'c'))).toBe(
      'pact-broker/matrix?q[][pacticipant]=c&q[][pacticipant]=p&limit=500',
    );
    expect(decodeURIComponent(pacticipantPactsProxyPath('c'))).toBe(
      'pact-broker/matrix?q[][pacticipant]=c&latestby=cvp&limit=1000',
    );
    expect(shortSha(fixture.shaA)).toBe('a3f9c2e417b0');
    expect(shortSha(null)).toBe('—');
  });

  it('accepts one version and refuses anything else with the reason', () => {
    expect(pickPactQuery(new URLSearchParams('version=1.4.0'), true)).toEqual({
      ok: true,
      version: '1.4.0',
    });
    expect(pickPactQuery(new URLSearchParams(''), true)).toEqual({ ok: true, version: null });
    expect(pickPactQuery(new URLSearchParams('tag=prod'), true)).toEqual({
      ok: false,
      error: 'Unsupported parameter tag: this read accepts version.',
    });
    expect(pickPactQuery(new URLSearchParams('version=1'), false)).toEqual({
      ok: false,
      error: 'Unsupported parameter version: this read accepts no parameters.',
    });
    expect(pickPactQuery(new URLSearchParams('version=1&version=2'), true)).toEqual({
      ok: false,
      error: 'The version parameter is given more than once.',
    });
    expect(pickPactQuery(new URLSearchParams('version='), true)).toEqual({
      ok: false,
      error: 'The version is empty.',
    });
  });

  it('refuses a version REST could not be asked for', () => {
    expect(versionProblem('feat/x')).toMatch(/cannot be opened here/);
    expect(versionProblem('x'.repeat(256))).toMatch(/longer than 255/);
    expect(versionProblem('a\u0001b')).toMatch(/control character/);
    expect(versionProblem('1.4.0')).toBeNull();
  });
});

// --- the previous different pact -------------------------------------------------------------------------

/** A pact document of a consumer version with a content SHA. */
function pactDoc(version: string, sha: string, createdAt = '2026-11-01T00:00:00Z') {
  return {
    interactions: [],
    createdAt,
    _links: { 'pb:consumer-version': { name: version }, 'pb:pact-version': { name: sha } },
  };
}

/** Matrix rows of billing-service → ledger-api for the given versions, newest first. */
function historyOf(versions: string[]) {
  const base = 'http://rest/v1/tenants/acme/pact-broker/pacticipants';
  return {
    matrix: versions.map((number) => ({
      consumer: {
        name: 'Billing Service',
        version: { number },
        _links: { self: { href: `${base}/billing-service` } },
      },
      provider: {
        name: 'Ledger API',
        version: null,
        _links: { self: { href: `${base}/ledger-api` } },
      },
      pact: { createdAt: null },
      verificationResult: null,
    })),
  };
}

/** A reader over fixed answers by path; records what was read. */
function reader(answers: Record<string, RestRead>, read: string[] = []) {
  return async (path: string): Promise<RestRead> => {
    read.push(path);
    return answers[path] ?? { ok: false, status: 404, body: { detail: 'No pact found' } };
  };
}

const PAIR = 'pact-broker/pacts/provider/ledger-api/consumer/billing-service';
const HISTORY = pairHistoryProxyPath('ledger-api', 'billing-service');
const ok = (body: unknown): RestRead => ({ ok: true, status: 200, body });

describe('findPreviousDistinct', () => {
  it('walks back past versions with the same content to the first different one', async () => {
    const read: string[] = [];
    const result = await findPreviousDistinct(
      reader(
        {
          [`${PAIR}/latest`]: ok(pactDoc('3', 'sha-c')),
          [HISTORY]: ok(historyOf(['3', '2', '1'])),
          [`${PAIR}/version/2`]: ok(pactDoc('2', 'sha-c')),
          [`${PAIR}/version/1`]: ok(pactDoc('1', 'sha-a', '2026-10-01T00:00:00Z')),
        },
        read,
      ),
      'ledger-api',
      'billing-service',
      null,
    );
    expect(result).toMatchObject({
      outcome: 'found',
      consumerVersion: '3',
      scanned: 2,
      previous: { consumerVersion: '1', sha: 'sha-a', publishedAt: '2026-10-01T00:00:00Z' },
    });
    expect(read).toContain(`${PAIR}/latest`);
  });

  it('answers first, unchanged and not-in-history', async () => {
    const first = await findPreviousDistinct(
      reader({ [`${PAIR}/version/1`]: ok(pactDoc('1', 's')), [HISTORY]: ok(historyOf(['1'])) }),
      'ledger-api',
      'billing-service',
      '1',
    );
    expect(first.outcome).toBe('first');
    const unchanged = await findPreviousDistinct(
      reader({
        [`${PAIR}/version/2`]: ok(pactDoc('2', 's')),
        [`${PAIR}/version/1`]: ok(pactDoc('1', 's')),
        [HISTORY]: ok(historyOf(['2', '1'])),
      }),
      'ledger-api',
      'billing-service',
      '2',
    );
    expect(unchanged).toMatchObject({ outcome: 'unchanged', scanned: 1, previous: null });
    const missing = await findPreviousDistinct(
      reader({
        [`${PAIR}/version/9`]: ok(pactDoc('9', 's')),
        [HISTORY]: ok(historyOf(['2', '1'])),
      }),
      'ledger-api',
      'billing-service',
      '9',
    );
    expect(missing.outcome).toBe('not-in-history');
  });

  it('stops after the scan limit and skips an earlier pact that is gone', async () => {
    const versions = Array.from({ length: PREVIOUS_SCAN_LIMIT + 3 }, (_, i) => String(100 - i));
    const answers: Record<string, RestRead> = { [HISTORY]: ok(historyOf(versions)) };
    for (const v of versions) answers[`${PAIR}/version/${v}`] = ok(pactDoc(v, 'same'));
    delete answers[`${PAIR}/version/99`];
    const read: string[] = [];
    const result = await findPreviousDistinct(
      reader(answers, read),
      'ledger-api',
      'billing-service',
      '100',
    );
    expect(result).toMatchObject({ outcome: 'scan-limit', scanned: PREVIOUS_SCAN_LIMIT });
    expect(read.filter((path) => path.startsWith(`${PAIR}/version/`))).toHaveLength(
      PREVIOUS_SCAN_LIMIT + 1,
    );
  });

  it('reports a failed read with REST’s status, never as no previous pact', async () => {
    await expect(
      findPreviousDistinct(
        reader({
          [`${PAIR}/latest`]: { ok: false, status: 403, body: { detail: 'Permission denied' } },
        }),
        'ledger-api',
        'billing-service',
        null,
      ),
    ).rejects.toEqual(new RollupError(403, 'Permission denied'));
    await expect(
      findPreviousDistinct(
        reader({
          [`${PAIR}/latest`]: ok(pactDoc('2', 's')),
          [HISTORY]: { ok: false, status: 400, body: {} },
        }),
        'ledger-api',
        'billing-service',
        null,
      ),
    ).rejects.toMatchObject({ status: 400, message: 'The history could not be read.' });
    await expect(
      findPreviousDistinct(
        reader({
          [`${PAIR}/latest`]: ok(pactDoc('2', 's')),
          [HISTORY]: ok(historyOf(['2', '1'])),
          [`${PAIR}/version/1`]: { ok: false, status: 500, body: { detail: { message: 'boom' } } },
        }),
        'ledger-api',
        'billing-service',
        null,
      ),
    ).rejects.toMatchObject({ status: 500, message: 'boom' });
  });
});

// --- the proxies ---------------------------------------------------------------------------------------------

describe('the /api/pact pact proxies', () => {
  it('forwards a pact (latest, or one version) as the signed-in user', async () => {
    await pactGet(
      req('/api/pact/pacts/ledger-api/billing-service'),
      pair('ledger-api', 'billing-service'),
    );
    expect(forwardedUrl()).toBe(`http://rest/v1/tenants/acme/${PAIR}/latest`);
    expect(forward.mock.calls[0][1]).toMatchObject({ method: 'GET', user: { user_id: 'u-1' } });
    await pactGet(
      req('/api/pact/pacts/ledger-api/billing-service?version=1.4.0'),
      pair('ledger-api', 'billing-service'),
    );
    expect(forwardedUrl()).toBe(`http://rest/v1/tenants/acme/${PAIR}/version/1.4.0`);
  });

  it('forwards the history and the pacticipant’s integrations as matrix queries', async () => {
    await historyGet(
      req('/api/pact/pacts/ledger-api/billing-service/history'),
      pair('ledger-api', 'billing-service'),
    );
    expect(forwardedUrl()).toBe(`http://rest/v1/tenants/acme/${HISTORY}`);
    await pacticipantPactsGet(req('/api/pact/pacticipants/billing-service/pacts'), {
      params: Promise.resolve({ pacticipant: 'billing-service' }),
    });
    expect(forwardedUrl()).toBe(
      `http://rest/v1/tenants/acme/${pacticipantPactsProxyPath('billing-service')}`,
    );
  });

  it('refuses a bad parameter or a malformed handle without calling REST', async () => {
    const tag = await pactGet(req('/api/pact/pacts/p/c?tag=prod'), pair('p', 'c'));
    expect(tag.status).toBe(400);
    expect(await tag.json()).toEqual({
      success: false,
      error: 'Unsupported parameter tag: this read accepts version.',
    });
    expect((await pactGet(req('/api/pact/pacts/p/c?version=a%2Fb'), pair('p', 'c'))).status).toBe(
      400,
    );
    expect(
      (await historyGet(req('/api/pact/pacts/p/c/history?limit=5'), pair('p', 'c'))).status,
    ).toBe(400);
    expect(
      (await previousGet(req('/api/pact/pacts/p/c/previous?cursor=x'), pair('p', 'c'))).status,
    ).toBe(400);
    expect(
      (
        await pacticipantPactsGet(req('/api/pact/pacticipants/x/pacts?latestby=cv'), {
          params: Promise.resolve({ pacticipant: 'x' }),
        })
      ).status,
    ).toBe(400);
    for (const get of [pactGet, historyGet, previousGet]) {
      expect((await get(req('/api/pact/pacts/x'), pair('../x', 'c'))).status).toBe(404);
      expect((await get(req('/api/pact/pacts/x'), pair('p', 'Bad Name'))).status).toBe(404);
    }
    expect(
      (
        await pacticipantPactsGet(req('/api/pact/pacticipants/x/pacts'), {
          params: Promise.resolve({ pacticipant: '../x' }),
        })
      ).status,
    ).toBe(404);
    expect(forward).not.toHaveBeenCalled();
  });

  it('passes the session’s refusal through', async () => {
    tenant = {
      error: NextResponse.json({ success: false, error: 'No workspace selected' }, { status: 403 }),
    };
    expect((await pactGet(req('/api/pact/pacts/p/c'), pair('p', 'c'))).status).toBe(403);
    expect((await previousGet(req('/api/pact/pacts/p/c/previous'), pair('p', 'c'))).status).toBe(
      403,
    );
    expect(forward).not.toHaveBeenCalled();
  });

  describe('previous', () => {
    const realFetch = global.fetch;
    afterEach(() => {
      global.fetch = realFetch;
    });

    it('walks back as the signed-in user, in the session tenant', async () => {
      const urls: string[] = [];
      const headers: unknown[] = [];
      const answers: Record<string, unknown> = {
        [`http://rest/v1/tenants/acme/${PAIR}/version/1.4.0`]: fixture.current,
        [`http://rest/v1/tenants/acme/${PAIR}/version/1.3.2`]: fixture.previous,
        [`http://rest/v1/tenants/acme/${HISTORY}`]: fixture.history,
      };
      global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        urls.push(String(input));
        headers.push(init?.headers);
        const body = answers[String(input)];
        return {
          ok: body !== undefined,
          status: body ? 200 : 404,
          json: async () => body ?? {},
        } as Response;
      }) as unknown as typeof fetch;
      const response = await previousGet(
        req('/api/pact/pacts/ledger-api/billing-service/previous?version=1.4.0'),
        pair('ledger-api', 'billing-service'),
      );
      expect(response.status).toBe(200);
      const body = await response.json();
      expect(body).toMatchObject({
        outcome: 'found',
        consumerVersion: '1.4.0',
        previous: { consumerVersion: '1.3.2' },
      });
      expect(urls.every((url) => url.startsWith('http://rest/v1/tenants/acme/pact-broker/'))).toBe(
        true,
      );
      expect(
        headers.every((h) => (h as Record<string, string>).Authorization === 'Bearer session'),
      ).toBe(true);
    });

    it('keeps REST’s refusal, and says when REST is unreachable', async () => {
      global.fetch = jest.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'No pact found' }),
      })) as unknown as typeof fetch;
      const refused = await previousGet(req('/api/pact/pacts/p/c/previous'), pair('p', 'c'));
      expect(refused.status).toBe(404);
      expect(await refused.json()).toEqual({ success: false, error: 'No pact found' });

      global.fetch = jest.fn(async () => {
        throw new Error('ECONNREFUSED');
      }) as unknown as typeof fetch;
      expect((await previousGet(req('/api/pact/pacts/p/c/previous'), pair('p', 'c'))).status).toBe(
        503,
      );
    });
  });
});

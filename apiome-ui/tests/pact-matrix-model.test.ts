/**
 * @jest-environment node
 */
/**
 * The matrix and can-i-deploy console — PFX-5.4 (#6948).
 *
 * * **Matrix query**: the builder's query written as numbered broker selectors and read back;
 *   every parameter the page or proxy cannot read refused with the reason (unknown, repeated,
 *   empty, oversized, gaps, too many selectors, combinations the broker refuses).
 * * **Can-i-deploy query**: required fields, one destination, `ignore` rules; the lenient form
 *   reader; the CLI command and its quoting.
 * * **Answer**: the matrix document read (rows, reasons, ignored, retry); missing fields never
 *   read as a verdict.
 * * **Verdict explained**: headline, counts, notice groups (unknown types kept), hints.
 * * **Grid**: consumer versions × provider versions, the newest result per cell with its count,
 *   the *no result* column, axes capped with what is hidden counted, accessible names.
 * * **Proxies**: forward only what was read, as the signed-in user in the session tenant, with
 *   `Retry-After` as `retryAfterSeconds`; refuse bad input without calling REST; keep REST's
 *   refusal; 503 when REST cannot be reached.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: string[] = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string) => {
    forwarded.push(url);
    return NextResponse.json({ ok: true });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  GRID_AXIS_LIMIT,
  MAX_IGNORED,
  MAX_SELECTORS,
  NOTICE_HINTS,
  buildMatrixGrid,
  canIDeployCommand,
  canIDeployFormFrom,
  canIDeployParams,
  cellLabel,
  countsLine,
  describeSelector,
  emptyMatrixQuery,
  explainVerdict,
  gridCellKey,
  matrixQueryParams,
  matrixQueryProblem,
  parseCanIDeployQuery,
  parseMatrixAnswer,
  parseMatrixQuery,
  reasonLook,
  retryAfterSeconds,
  rowsMayBeTruncated,
  searchParamsFrom,
  shellQuote,
  verdictHeadline,
  type MatrixQuery,
  type MatrixRow,
} from '../lib/pact-matrix';
import { GET as matrixGet } from '../src/app/api/pact/matrix/route';
import { GET as canIDeployGet } from '../src/app/api/pact/can-i-deploy/route';
import { GET as environmentsGet } from '../src/app/api/pact/environments/route';
import fixture from './fixtures/pact-matrix.json';

const params = (query: string) => new URLSearchParams(query);
const decoded = (search: URLSearchParams) => decodeURIComponent(search.toString());

describe('the matrix query', () => {
  const query: MatrixQuery = {
    selectors: [
      { pacticipant: 'billing-service', scope: 'latest', value: '', latest: false },
      { pacticipant: 'ledger-api', scope: 'branch', value: 'main', latest: true },
      { pacticipant: 'audit-log', scope: 'version', value: '0.9.0', latest: false },
      { pacticipant: 'mobile-app', scope: 'main-branch', value: '', latest: false },
      {
        pacticipant: 'notification-service',
        scope: 'environment',
        value: 'production',
        latest: false,
      },
      { pacticipant: 'search', scope: 'tag', value: 'prod', latest: false },
      { pacticipant: 'web', scope: 'all', value: '', latest: false },
    ],
    latestby: 'cvpv',
    limit: 500,
  };

  it('writes numbered broker selectors and reads them back', () => {
    const written = matrixQueryParams(query);
    expect(decoded(written)).toBe(
      'q[0][pacticipant]=billing-service&q[0][latest]=true&q[1][pacticipant]=ledger-api&q[1][branch]=main&' +
        'q[1][latest]=true&q[2][pacticipant]=audit-log&q[2][version]=0.9.0&q[3][pacticipant]=mobile-app&' +
        'q[3][mainBranch]=true&q[4][pacticipant]=notification-service&q[4][environment]=production&' +
        'q[5][pacticipant]=search&q[5][tag]=prod&q[6][pacticipant]=web&latestby=cvpv&limit=500',
    );
    expect(parseMatrixQuery(written)).toEqual({ ok: true, query });
  });

  it('reads selectors in any key order (a server page does not keep it), and defaults', () => {
    const read = parseMatrixQuery(
      params('q[1][pacticipant]=b&q[0][version]=1&q[0][pacticipant]=a'),
    );
    expect(read).toEqual({
      ok: true,
      query: {
        selectors: [
          { pacticipant: 'a', scope: 'version', value: '1', latest: false },
          { pacticipant: 'b', scope: 'all', value: '', latest: false },
        ],
        latestby: null,
        limit: 100,
      },
    });
    expect(parseMatrixQuery(params(''))).toEqual({
      ok: true,
      query: { selectors: [], latestby: null, limit: 100 },
    });
  });

  it.each([
    ['foo=1', 'Unsupported parameter foo'],
    ['q[][pacticipant]=a', 'Number each selector: q[0][pacticipant]'],
    [
      'q[0][pacticipant]=a&q[0][pacticipant]=b',
      'q[0][pacticipant] parameter is given more than once',
    ],
    ['q[0][pacticipant]=a&q[0][colour]=red', 'Unsupported selector key q[0][colour]'],
    ['q[0][pacticipant]=', 'q[0][pacticipant] is empty'],
    [`q[0][pacticipant]=${'a'.repeat(256)}`, 'longer than 255 characters'],
    ['q[10][pacticipant]=a', `at most ${MAX_SELECTORS} selectors`],
    ['q[0][pacticipant]=a&q[2][pacticipant]=b', 'q[1] is missing'],
    ['q[0][version]=1', 'Selector 0 has no pacticipant'],
    ['q[0][pacticipant]=a&q[0][latest]=yes', 'q[0][latest] must be true'],
    ['q[0][pacticipant]=a&q[0][mainBranch]=false', 'q[0][mainBranch] must be true'],
    ['q[0][pacticipant]=a&q[0][version]=1&q[0][branch]=main', 'combines version and branch'],
    [
      'q[0][pacticipant]=a&q[0][version]=1&q[0][latest]=true',
      'latest cannot be combined with version',
    ],
    [
      'q[0][pacticipant]=a&q[0][environment]=prod&q[0][latest]=true',
      'latest cannot be combined with environment',
    ],
    ['q[0][pacticipant]=a&latestby=cv', 'latestby must be one of cvp, cvpv, cp'],
    ['q[0][pacticipant]=a&limit=0', 'from 1 to 1000'],
    ['q[0][pacticipant]=a&limit=1001', 'from 1 to 1000'],
    ['q[0][pacticipant]=a&limit=ten', 'from 1 to 1000'],
  ])('refuses %s', (query, reason) => {
    const read = parseMatrixQuery(params(query));
    expect(read.ok).toBe(false);
    if (!read.ok) expect(read.error).toContain(reason);
  });

  it('says what the builder still needs', () => {
    expect(matrixQueryProblem(emptyMatrixQuery())).toBe('Selector 1: choose a pacticipant.');
    expect(matrixQueryProblem({ ...emptyMatrixQuery(), selectors: [] })).toContain(
      'at least one pacticipant',
    );
    expect(
      matrixQueryProblem({
        ...emptyMatrixQuery(),
        selectors: [{ pacticipant: 'a', scope: 'branch', value: ' ', latest: false }],
      }),
    ).toBe('Selector 1: enter the branch.');
    expect(
      matrixQueryProblem({
        ...emptyMatrixQuery(),
        selectors: Array.from({ length: MAX_SELECTORS + 1 }, () => ({
          pacticipant: 'a',
          scope: 'all' as const,
          value: '',
          latest: false,
        })),
      }),
    ).toContain(`at most ${MAX_SELECTORS}`);
    expect(
      matrixQueryProblem({
        ...emptyMatrixQuery(),
        selectors: [{ pacticipant: 'a'.repeat(256), scope: 'all', value: '', latest: false }],
      }),
    ).toContain('longer than 255');
    expect(matrixQueryProblem(query)).toBeNull();
  });

  it('describes each selector', () => {
    expect(query.selectors.map(describeSelector)).toEqual([
      'the latest version of billing-service',
      'the latest version of ledger-api on branch main',
      'audit-log 0.9.0',
      'versions of mobile-app on its main branch',
      'the versions of notification-service in production',
      'versions of search tagged prod',
      'every version of web',
    ]);
  });

  it('reads a server page’s search parameters, repeated keys included', () => {
    expect(decoded(searchParamsFrom({ a: '1', ignore: ['x', 'y'], none: undefined }))).toBe(
      'a=1&ignore=x&ignore=y',
    );
  });
});

describe('the can-i-deploy query', () => {
  it('reads a whole question to an environment or a tag', () => {
    expect(
      parseCanIDeployQuery(
        params('pacticipant=a&version=1&toEnvironment=production&ignore=b&ignore=c'),
      ),
    ).toEqual({
      ok: true,
      query: {
        pacticipant: 'a',
        version: '1',
        destination: { kind: 'environment', name: 'production' },
        ignore: ['b', 'c'],
      },
    });
    expect(parseCanIDeployQuery(params('pacticipant=a&version=1&to=prod'))).toEqual({
      ok: true,
      query: {
        pacticipant: 'a',
        version: '1',
        destination: { kind: 'tag', name: 'prod' },
        ignore: [],
      },
    });
  });

  it.each([
    ['pacticipant=a&version=1&toEnvironment=p&environment=p', 'Unsupported parameter environment'],
    ['version=1&toEnvironment=p', 'Choose the pacticipant'],
    ['pacticipant=a&toEnvironment=p', 'Enter the version'],
    ['pacticipant=a&version=1', 'Choose where it is deployed'],
    ['pacticipant=a&version=1&toEnvironment=p&to=t', 'not both'],
    ['pacticipant=a&pacticipant=b&version=1&to=t', 'pacticipant parameter is given more than once'],
    ['pacticipant=a&version=&to=t', 'The version parameter is empty'],
    [`pacticipant=a&version=${'1'.repeat(256)}&to=t`, 'longer than 255'],
    ['pacticipant=a&version=1&to=t&ignore=b&ignore=b', 'b is ignored more than once'],
    ['pacticipant=a&version=1&to=t&ignore=a', 'it cannot be ignored'],
    [
      `pacticipant=a&version=1&to=t&${Array.from({ length: MAX_IGNORED + 1 }, (_, i) => `ignore=p${i}`).join('&')}`,
      `At most ${MAX_IGNORED}`,
    ],
  ])('refuses %s', (query, reason) => {
    const read = parseCanIDeployQuery(params(query));
    expect(read.ok).toBe(false);
    if (!read.ok) expect(read.error).toContain(reason);
  });

  it('fills the form from a partial address and writes it back', () => {
    const form = canIDeployFormFrom(params('pacticipant=a&to=prod&ignore=b'));
    expect(form).toEqual({
      pacticipant: 'a',
      version: '',
      kind: 'tag',
      destination: 'prod',
      ignore: ['b'],
    });
    expect(decoded(canIDeployParams(form))).toBe('pacticipant=a&to=prod&ignore=b');
    expect(canIDeployFormFrom(params(''))).toEqual({
      pacticipant: '',
      version: '',
      kind: 'environment',
      destination: '',
      ignore: [],
    });
  });

  it('writes the CLI command, quoting what a shell would split', () => {
    expect(
      canIDeployCommand({
        pacticipant: 'billing-service',
        version: '2.0.0',
        destination: { kind: 'environment', name: 'production' },
        ignore: ['audit-log'],
      }),
    ).toBe(
      'apiome pact can-i-deploy \\\n  --pacticipant billing-service \\\n  --version 2.0.0 \\\n' +
        '  --to-environment production \\\n  --ignore audit-log',
    );
    expect(
      canIDeployCommand({
        pacticipant: 'Billing Service',
        version: '1',
        destination: { kind: 'tag', name: 'prod' },
        ignore: [],
      }),
    ).toContain("--pacticipant 'Billing Service'");
    expect(shellQuote("it's $HOME")).toBe(`'it'\\''s $HOME'`);
    expect(shellQuote('a/b:c@1.0+x=y')).toBe('a/b:c@1.0+x=y');
  });
});

describe('the answer', () => {
  const answer = parseMatrixAnswer(fixture.matrix);

  it('reads the summary, notices and every row', () => {
    expect(answer.summary).toEqual({
      deployable: false,
      reason: fixture.matrix.summary.reason,
      success: 3,
      failed: 1,
      unknown: 1,
    });
    expect(answer.notices.map((n) => n.code)).toEqual([
      'verification-failed',
      'no-verification-result',
      'provider-contract-unverified',
    ]);
    expect(answer.rows).toHaveLength(8);
    expect(answer.rows[0]).toEqual({
      consumer: {
        name: 'Billing Service',
        slug: 'billing-service',
        version: '2.0.0',
        branch: 'main',
      },
      provider: { name: 'Ledger API', slug: 'ledger-api', version: '5.1.0', branch: 'main' },
      publishedAt: '2026-11-24T09:00:00+00:00',
      verification: {
        success: false,
        verifiedAt: '2026-11-24T10:05:00+00:00',
        kind: 'native',
        pending: null,
        wip: false,
        providerContractVerified: null,
      },
      reason: { code: 'verification-failed', text: 'verification failed' },
      ignored: false,
    });
    expect(answer.rows[2].provider.version).toBeNull();
    expect(answer.rows[2].verification).toBeNull();
    expect(answer.rows[5].verification?.providerContractVerified).toBe(false);
    expect(answer.rows[6].verification?.pending).toBe(true);
    expect(answer.rows[7].ignored).toBe(true);
    expect(answer.retryAfterSeconds).toBeNull();
    expect(parseMatrixAnswer(fixture.canIDeploy).retryAfterSeconds).toBe(10);
  });

  it('never reads a missing verdict as one, and fills a missing row reason from its result', () => {
    const empty = parseMatrixAnswer({});
    expect(empty.summary.deployable).toBeNull();
    expect(empty.rows).toEqual([]);
    expect(parseMatrixAnswer({ summary: { deployable: 'yes' } }).summary.deployable).toBeNull();
    const bare = parseMatrixAnswer({
      matrix: [
        {
          consumer: { name: 'A', version: { number: '1' } },
          provider: { name: 'B', version: null },
          verificationResult: null,
        },
        { consumer: { name: 'A', version: null }, provider: { name: 'B' } },
        {
          consumer: { name: 'A', version: { number: '2' } },
          provider: { name: 'B', version: { number: '9' } },
          verificationResult: { success: true },
        },
      ],
    });
    expect(bare.rows.map((row) => row.reason)).toEqual([
      { code: 'no-verification-result', text: 'no verification result' },
      { code: 'verified', text: 'verified' },
    ]);
    expect(bare.rows[0].consumer.slug).toBeNull();
  });

  it('reads Retry-After', () => {
    expect(retryAfterSeconds('10')).toBe(10);
    expect(retryAfterSeconds(' 5 ')).toBe(5);
    expect(retryAfterSeconds('0')).toBeNull();
    expect(retryAfterSeconds('Wed, 21 Oct 2026 07:28:00 GMT')).toBeNull();
    expect(retryAfterSeconds(null)).toBeNull();
  });

  it('says when the rows may be cut short', () => {
    expect(rowsMayBeTruncated(answer, 8)).toBe(true);
    expect(rowsMayBeTruncated(answer, 100)).toBe(false);
  });
});

describe('the verdict, explained', () => {
  it('heads and counts the verdict', () => {
    expect(verdictHeadline(true)).toEqual({ label: 'Yes — deployable', tone: 'ok' });
    expect(verdictHeadline(false)).toEqual({ label: 'No — not deployable', tone: 'danger' });
    expect(verdictHeadline(null)).toEqual({ label: 'Not known yet', tone: 'warn' });
    expect(countsLine(parseMatrixAnswer(fixture.matrix).summary)).toBe(
      '3 verified · 1 failed · 1 unknown',
    );
  });

  it('groups the notices, keeps unknown types, and counts considered and ignored rows', () => {
    const answer = parseMatrixAnswer({
      ...fixture.matrix,
      notices: [
        ...fixture.matrix.notices,
        { type: 'success', code: 'verified', text: 'ok' },
        { type: 'info', text: 'fyi' },
      ],
    });
    const explained = explainVerdict(answer);
    expect(explained.blocking.map((n) => n.code)).toEqual([
      'verification-failed',
      'no-verification-result',
    ]);
    expect(explained.warnings.map((n) => n.code)).toEqual(['provider-contract-unverified']);
    expect(explained.passing.map((n) => n.text)).toEqual(['ok']);
    expect(explained.other).toEqual([{ type: 'info', code: null, text: 'fyi' }]);
    expect(explained.considered).toBe(7);
    expect(explained.ignored).toBe(1);
  });

  it('has a hint for every code the verdict blocks on', () => {
    for (const code of [
      'verification-failed',
      'pact-pending',
      'no-verification-result',
      'no-pact',
      'version-not-found',
    ]) {
      expect(NOTICE_HINTS[code]).toBeTruthy();
    }
  });
});

describe('the grid', () => {
  const rows = parseMatrixAnswer(fixture.matrix).rows;

  it('lays consumer versions down and provider versions across, newest result per cell', () => {
    const grid = buildMatrixGrid(rows);
    expect(grid.consumers.map((c) => c.key)).toEqual([
      'billing-service@2.0.0',
      'billing-service@1.9.0',
      'mobile-app@3.2.0',
    ]);
    expect(grid.providers.map((p) => p.key)).toEqual([
      'ledger-api@5.1.0',
      'ledger-api@5.0.0',
      'audit-log@',
      'notification-service@1.4.0',
      'audit-log@0.9.0',
      'billing-service@2.0.0',
    ]);
    const [, older] = grid.consumers;
    const cell = grid.cells.get(gridCellKey(older, grid.providers[1]))!;
    expect(cell.count).toBe(2);
    expect(cell.row.reason.code).toBe('verified');
    expect(cellLabel(cell)).toBe(
      'Billing Service 1.9.0 → Ledger API 5.0.0: Verified (verified), 2 results. Open the pact.',
    );
    const noResult = grid.cells.get(gridCellKey(grid.consumers[0], grid.providers[2]))!;
    expect(cellLabel(noResult)).toBe(
      'Billing Service 2.0.0 → Audit Log (no result): No result (no verification result). Open the pact.',
    );
    const ignored = grid.cells.get(gridCellKey(grid.consumers[2], grid.providers[5]))!;
    expect(cellLabel(ignored)).toContain(', ignored.');
    expect(grid.cells.has(gridCellKey(grid.consumers[2], grid.providers[0]))).toBe(false);
    expect(grid.hiddenConsumers).toBe(0);
  });

  it('caps each axis and counts what it hides', () => {
    const many: MatrixRow[] = Array.from({ length: GRID_AXIS_LIMIT + 3 }, (_, i) => ({
      ...rows[0],
      consumer: { ...rows[0].consumer, version: `1.${i}` },
      provider: { ...rows[0].provider, version: `9.${i}` },
    }));
    const grid = buildMatrixGrid(many);
    expect(grid.consumers).toHaveLength(GRID_AXIS_LIMIT);
    expect(grid.providers).toHaveLength(GRID_AXIS_LIMIT);
    expect(grid.hiddenConsumers).toBe(3);
    expect(grid.hiddenProviders).toBe(3);
    expect(buildMatrixGrid(many, 5).hiddenConsumers).toBe(GRID_AXIS_LIMIT - 2);
  });

  it('draws each reason, and an unknown one by its code', () => {
    expect(reasonLook('verified')).toEqual({ mark: '✓', tone: 'ok', label: 'Verified' });
    expect(reasonLook('verification-failed').tone).toBe('danger');
    expect(reasonLook('pact-pending').mark).toBe('!');
    expect(reasonLook('no-verification-result').mark).toBe('?');
    expect(reasonLook('something-new')).toEqual({
      mark: '•',
      tone: 'muted',
      label: 'something-new',
    });
  });
});

describe('the /api/pact matrix, can-i-deploy and environments proxies', () => {
  const realFetch = global.fetch;
  const req = (path: string) => new NextRequest(`http://ui${path}`);
  let calls: { url: string; headers: unknown }[];

  /** REST answering one document, with optional headers. */
  const restAnswers = (status: number, body: unknown, headers: Record<string, string> = {}) => {
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), headers: init?.headers });
      return {
        ok: status < 400,
        status,
        json: async () => body,
        headers: new Headers(headers),
      } as Response;
    }) as unknown as typeof fetch;
  };

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    calls = [];
    forwarded.length = 0;
  });
  afterEach(() => {
    global.fetch = realFetch;
  });

  it('forwards the matrix query it read, as the signed-in user, with Retry-After', async () => {
    restAnswers(200, fixture.matrix, { 'Retry-After': '10' });
    const response = await matrixGet(
      req('/api/pact/matrix?q[0][pacticipant]=billing-service&q[0][latest]=true&latestby=cvp'),
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.retryAfterSeconds).toBe(10);
    expect((body.summary as Record<string, unknown>).deployable).toBe(false);
    expect(calls).toHaveLength(1);
    expect(decodeURIComponent(calls[0].url)).toBe(
      'http://rest/v1/tenants/acme/pact-broker/matrix?q[0][pacticipant]=billing-service&q[0][latest]=true&latestby=cvp&limit=100',
    );
    expect((calls[0].headers as Record<string, string>).Authorization).toBe('Bearer session');
  });

  it('refuses a query it cannot read, or with no selector, without calling REST', async () => {
    restAnswers(200, {});
    const unknown = await matrixGet(req('/api/pact/matrix?q[0][pacticipant]=a&success[]=true'));
    expect(unknown.status).toBe(400);
    expect(((await unknown.json()) as { error: string }).error).toContain(
      'Unsupported parameter success[]',
    );
    const none = await matrixGet(req('/api/pact/matrix?latestby=cvp'));
    expect(none.status).toBe(400);
    expect(await none.json()).toEqual({
      success: false,
      error: 'Name at least one pacticipant (q[0][pacticipant]).',
    });
    expect(calls).toHaveLength(0);
  });

  it('forwards a can-i-deploy question and refuses a bad one', async () => {
    restAnswers(200, fixture.canIDeploy);
    const response = await canIDeployGet(
      req(
        '/api/pact/can-i-deploy?pacticipant=billing-service&version=2.0.0&toEnvironment=production&ignore=audit-log',
      ),
    );
    expect(response.status).toBe(200);
    expect(((await response.json()) as Record<string, unknown>).retryAfterSeconds).toBeNull();
    expect(calls[0].url).toBe(
      'http://rest/v1/tenants/acme/pact-broker/can-i-deploy?pacticipant=billing-service&version=2.0.0&toEnvironment=production&ignore=audit-log',
    );
    calls = [];
    const bad = await canIDeployGet(req('/api/pact/can-i-deploy?pacticipant=a&version=1'));
    expect(bad.status).toBe(400);
    expect(((await bad.json()) as { error: string }).error).toContain(
      'Choose where it is deployed',
    );
    expect(calls).toHaveLength(0);
  });

  it('keeps REST’s refusal and its message, and says when REST is unreachable', async () => {
    restAnswers(400, {
      detail: {
        code: 'pact-matrix-invalid',
        message: 'Environment nowhere does not exist',
        pointer: '/environment',
      },
    });
    const refused = await matrixGet(
      req('/api/pact/matrix?q[0][pacticipant]=a&q[0][environment]=nowhere'),
    );
    expect(refused.status).toBe(400);
    expect(await refused.json()).toEqual({
      success: false,
      error: 'Environment nowhere does not exist',
    });

    restAnswers(403, { detail: 'Permission denied' });
    expect(
      (
        (await (
          await canIDeployGet(req('/api/pact/can-i-deploy?pacticipant=a&version=1&to=t'))
        ).json()) as { error: string }
      ).error,
    ).toBe('Permission denied');

    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    expect((await matrixGet(req('/api/pact/matrix?q[0][pacticipant]=a'))).status).toBe(503);
  });

  it('passes the session’s refusal through without calling REST', async () => {
    restAnswers(200, {});
    tenant = {
      error: NextResponse.json({ success: false, error: 'No workspace selected' }, { status: 403 }),
    };
    expect((await matrixGet(req('/api/pact/matrix?q[0][pacticipant]=a'))).status).toBe(403);
    expect(
      (await canIDeployGet(req('/api/pact/can-i-deploy?pacticipant=a&version=1&to=t'))).status,
    ).toBe(403);
    expect(calls).toHaveLength(0);
  });

  it('reads the environment list, and refuses any parameter', async () => {
    expect((await environmentsGet(req('/api/pact/environments'))).status).toBe(200);
    expect(forwarded).toEqual(['http://rest/v1/tenants/acme/pact-broker/environments']);
    const refused = await environmentsGet(req('/api/pact/environments?limit=5'));
    expect(refused.status).toBe(400);
    expect(await refused.json()).toEqual({
      success: false,
      error: 'Unsupported parameter limit: the environment list takes none.',
    });
    expect(forwarded).toHaveLength(1);
  });
});

/**
 * @jest-environment node
 */
/**
 * The integration network — PFX-5.3 (#6947).
 *
 * * **Roll-up** (`collectPactNetwork`): the group of pacticipants connected to one, read breadth
 *   first from each one's matrix, 4 at a time; each integration once with its verdict; a refused
 *   matrix of another pacticipant reported on it (never dropped), the starting one's refusal kept
 *   as REST's status; the read limit leaves the rest marked `not-read`; a full matrix `truncated`.
 * * **Wording**: notices per gap, verdict counts.
 * * **Layout**: consumer → provider columns, cycles drawn as arcs, crowded columns capped with the
 *   centre always drawn, edges to undrawn pacticipants counted, the accessible summary.
 * * **Proxy**: reads as the signed-in user in the session tenant, refuses any parameter and a
 *   malformed handle without calling REST, passes the session's refusal through, 503 when REST
 *   cannot be reached.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async () => NextResponse.json({ ok: true }),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  NETWORK_READ_LIMIT,
  collectPactNetwork,
  networkNotices,
  networkRoute,
  verdictCounts,
  type PactNetwork,
} from '../lib/pact-network';
import { PACTICIPANT_PACTS_ROW_LIMIT, pacticipantPactsProxyPath } from '../lib/pact-detail';
import { RollupError, type RestRead } from '../lib/pact-pacticipants';
import {
  LOOP_DEPTH,
  MAX_NODES_PER_LAYER,
  PAD_Y,
  ROW_HEIGHT,
  assignLayers,
  caption,
  networkAriaLabel,
  networkLayout,
} from '../src/app/components/ade/pactNetwork/networkLayoutModel';
import { GET as networkGet } from '../src/app/api/pact/pacticipants/[pacticipant]/network/route';
import networkFixture from './fixtures/pact-network.json';

// --- matrix fixtures -----------------------------------------------------------------------------

/** A display name from a handle: `ledger-api` → `Ledger Api`. */
const title = (slug: string) =>
  slug.replace(/(^|-)(\w)/g, (_, dash, c) => `${dash ? ' ' : ''}${c.toUpperCase()}`);

/** The broker URL of a pacticipant. */
const href = (slug: string) => `http://rest/v1/tenants/acme/pact-broker/pacticipants/${slug}`;

/** A verdict as a matrix row's verification result. */
type Result = 'ok' | 'fail' | 'pending' | null;

/**
 * One matrix row: the consumer's version 1.0.0 pact with the provider, and its result.
 *
 * @param consumer - The consumer's handle.
 * @param provider - The provider's handle.
 * @param result - The verification result, or `null` for none.
 * @returns The row.
 */
function row(consumer: string, provider: string, result: Result = 'ok') {
  return {
    consumer: {
      name: title(consumer),
      version: { number: '1.0.0', tags: [] },
      _links: { self: { href: href(consumer) } },
    },
    provider: {
      name: title(provider),
      version: result ? { number: '2.0.0' } : null,
      _links: { self: { href: href(provider) } },
    },
    pact: { createdAt: '2026-11-24T16:40:00Z' },
    verificationResult: result
      ? {
          success: result === 'ok',
          verifiedAt: '2026-11-24T17:00:00Z',
          kind: 'native',
          pending: result === 'pending',
        }
      : null,
  };
}

/**
 * A reader over a set of integrations: each pacticipant's matrix holds every row it is in.
 *
 * @param edges - `[consumer, provider, result]` triples.
 * @param refuse - Handles whose matrix is refused, with the status.
 * @returns The reader and the paths it was asked for.
 */
function reader(edges: [string, string, Result?][], refuse: Record<string, number> = {}) {
  const paths: string[] = [];
  const read = async (path: string): Promise<RestRead> => {
    paths.push(path);
    const slug = new URLSearchParams(path.split('?')[1]).get('q[][pacticipant]')!;
    if (refuse[slug])
      return { ok: false, status: refuse[slug], body: { detail: `No access to ${slug}` } };
    const matrix = edges
      .filter(([c, p]) => c === slug || p === slug)
      .map(([c, p, r]) => row(c, p, r === undefined ? 'ok' : r));
    return { ok: true, status: 200, body: { matrix } };
  };
  return { read, paths };
}

const EDGES: [string, string, Result?][] = [
  ['mobile-app', 'billing-service', 'fail'],
  ['web-app', 'billing-service', 'ok'],
  ['billing-service', 'ledger-api', 'ok'],
  ['billing-service', 'notification-service', null],
  ['ledger-api', 'audit-log', 'pending'],
  ['reporting', 'audit-log', 'ok'],
];

// --- the roll-up ---------------------------------------------------------------------------------

describe('collectPactNetwork', () => {
  it('walks the whole group breadth first, keeping each integration once with its verdict', async () => {
    const { read, paths } = reader(EDGES);
    const network = await collectPactNetwork(read, 'billing-service');
    expect(network.centre).toBe('billing-service');
    expect(network.pacticipants.map((p) => [p.slug, p.distance, p.gap])).toEqual([
      ['billing-service', 0, undefined],
      ['ledger-api', 1, undefined],
      ['mobile-app', 1, undefined],
      ['notification-service', 1, undefined],
      ['web-app', 1, undefined],
      ['audit-log', 2, undefined],
      ['reporting', 3, undefined],
    ]);
    expect(network.pacticipants[0].name).toBe('Billing Service');
    expect(network.integrations.map((i) => [i.consumer.slug, i.provider.slug, i.verdict])).toEqual([
      ['billing-service', 'ledger-api', 'verified'],
      ['billing-service', 'notification-service', 'unverified'],
      ['ledger-api', 'audit-log', 'failed-pending'],
      ['mobile-app', 'billing-service', 'failed'],
      ['reporting', 'audit-log', 'verified'],
      ['web-app', 'billing-service', 'verified'],
    ]);
    // Every pacticipant read once, with the matrix query of its pacts.
    expect(paths).toHaveLength(7);
    expect(paths[0]).toBe(pacticipantPactsProxyPath('billing-service'));
    expect(new Set(paths).size).toBe(7);
  });

  it('reads at most 4 matrices at a time', async () => {
    const edges: [string, string][] = Array.from({ length: 9 }, (_, i) => [`consumer-${i}`, 'hub']);
    let inFlight = 0;
    let peak = 0;
    const base = reader(edges).read;
    const read = async (path: string) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      return base(path);
    };
    const network = await collectPactNetwork(read, 'hub');
    expect(network.pacticipants).toHaveLength(10);
    expect(peak).toBe(4);
  });

  it('reports a refused matrix on its pacticipant and keeps what reached it', async () => {
    const { read } = reader(EDGES, { 'ledger-api': 403 });
    const network = await collectPactNetwork(read, 'billing-service');
    const ledger = network.pacticipants.find((p) => p.slug === 'ledger-api')!;
    expect(ledger).toMatchObject({ gap: 'failed', error: 'No access to ledger-api' });
    // The integration seen from billing-service stays; what only ledger-api's matrix knew does not appear.
    expect(network.integrations.some((i) => i.provider.slug === 'ledger-api')).toBe(true);
    expect(network.pacticipants.some((p) => p.slug === 'audit-log')).toBe(false);
    expect(networkNotices(network)).toEqual([
      'The pacts of Ledger Api (No access to ledger-api) could not be read, so some of their integrations may be missing.',
    ]);
  });

  it('keeps REST’s refusal of the starting pacticipant', async () => {
    const { read } = reader(EDGES, { 'billing-service': 404 });
    await expect(collectPactNetwork(read, 'billing-service')).rejects.toEqual(
      new RollupError(404, 'No access to billing-service'),
    );
  });

  it('stops at the read limit and marks what it did not read', async () => {
    const { read, paths } = reader(EDGES);
    const network = await collectPactNetwork(read, 'billing-service', 3);
    expect(paths).toHaveLength(3);
    const notRead = network.pacticipants.filter((p) => p.gap === 'not-read').map((p) => p.slug);
    expect(notRead).toEqual(['notification-service', 'web-app', 'audit-log']);
    // audit-log was found through ledger-api, so its integration is known; reporting is not.
    expect(network.pacticipants.some((p) => p.slug === 'reporting')).toBe(false);
    expect(networkNotices(network)[0]).toContain(
      `Only ${NETWORK_READ_LIMIT} pacticipants are read at once. The pacts of Notification Service, Web App, Audit Log were not read`,
    );
  });

  it('marks a pacticipant whose matrix filled the row limit', async () => {
    const read = async (path: string): Promise<RestRead> => {
      const slug = new URLSearchParams(path.split('?')[1]).get('q[][pacticipant]')!;
      const matrix =
        slug === 'hub'
          ? Array.from({ length: PACTICIPANT_PACTS_ROW_LIMIT }, () => row('app', 'hub'))
          : [row('app', 'hub')];
      return { ok: true, status: 200, body: { matrix } };
    };
    const network = await collectPactNetwork(read, 'hub');
    expect(network.pacticipants.find((p) => p.slug === 'hub')?.gap).toBe('truncated');
    expect(network.integrations).toHaveLength(1);
    expect(networkNotices(network)).toEqual([
      'Hub has more pacts than are read at once; some integrations may be missing.',
    ]);
  });

  it('answers an unconnected pacticipant with itself and no integration', async () => {
    const network = await collectPactNetwork(reader([]).read, 'lonely');
    expect(network.pacticipants).toEqual([{ slug: 'lonely', name: 'lonely', distance: 0 }]);
    expect(network.integrations).toEqual([]);
    expect(networkNotices(network)).toEqual([]);
  });

  it('skips rows whose links carry no well-formed handle', async () => {
    const read = async (): Promise<RestRead> => ({
      ok: true,
      status: 200,
      body: {
        matrix: [
          row('app', 'hub'),
          {
            ...row('app', 'hub'),
            provider: {
              name: 'Odd',
              version: null,
              _links: { self: { href: 'http://x/Bad%20Name' } },
            },
          },
        ],
      },
    });
    const network = await collectPactNetwork(read, 'hub');
    expect(network.integrations.map((i) => i.provider.slug)).toEqual(['hub']);
  });
});

describe('wording', () => {
  it('counts the verdicts, zero included', () => {
    const network = networkFixture as PactNetwork;
    expect(verdictCounts(network.integrations)).toEqual({
      verified: 3,
      failed: 1,
      'failed-pending': 1,
      unverified: 1,
    });
    expect(verdictCounts([])).toEqual({
      verified: 0,
      failed: 0,
      'failed-pending': 0,
      unverified: 0,
    });
  });

  it('builds the route', () => {
    expect(networkRoute('billing-service')).toBe(
      '/ade/dashboard/pacts/pacticipants/billing-service/network',
    );
  });
});

// --- the layout ----------------------------------------------------------------------------------

describe('networkLayout', () => {
  it('lays consumers left of their providers, one column per hop of the longest chain', async () => {
    const network = await collectPactNetwork(reader(EDGES).read, 'billing-service');
    const layout = networkLayout(network);
    const layer = (slug: string) => layout.nodes.find((n) => n.slug === slug)!.layer;
    expect([layer('mobile-app'), layer('web-app')]).toEqual([0, 0]);
    // A pure consumer sits next to its nearest provider, not in the first column.
    expect(layer('reporting')).toBe(2);
    expect(layer('billing-service')).toBe(1);
    expect([layer('ledger-api'), layer('notification-service')]).toEqual([2, 2]);
    expect(layer('audit-log')).toBe(3);
    expect(layout.edges).toHaveLength(6);
    expect(layout.edges.every((e) => !e.backward)).toBe(true);
    // No arc, so no room is kept for one under the nodes.
    expect(layout.height).toBe(PAD_Y * 2 + 3 * ROW_HEIGHT);
    expect(layout.hiddenNodes).toBe(0);
    expect(layout.hiddenEdges).toBe(0);
    const centre = layout.nodes.find((n) => n.centre)!;
    expect(centre.slug).toBe('billing-service');
    expect(centre.href).toBe(networkRoute('billing-service'));
    expect(centre.ariaLabel).toBe(
      'Billing Service, the pacticipant shown: consumes 2, provides to 2. Open its network.',
    );
    const failed = layout.edges.find((e) => e.verdict === 'failed')!;
    expect(failed.href).toBe('/ade/dashboard/pacts/pacticipants/mobile-app/pacts/billing-service');
    expect(failed.ariaLabel).toBe(
      'Mobile App → Billing Service: Failed, consumer version 1.0.0. Open the pact.',
    );
    expect(failed.d).toMatch(/^M [\d.]+ [\d.]+ C /);
  });

  it('is deterministic', async () => {
    const network = await collectPactNetwork(reader(EDGES).read, 'billing-service');
    expect(networkLayout(network)).toEqual(networkLayout(network));
  });

  it('breaks a cycle where the walk closes it and draws that edge as an arc', async () => {
    const network = await collectPactNetwork(
      reader([
        ['a-app', 'b-app'],
        ['b-app', 'c-app'],
        ['c-app', 'a-app', 'fail'],
      ]).read,
      'a-app',
    );
    const { layers, backEdges } = assignLayers(
      network.pacticipants.map((p) => p.slug),
      network.integrations,
    );
    expect([...backEdges]).toEqual(['c-app|a-app']);
    expect([layers.get('a-app'), layers.get('b-app'), layers.get('c-app')]).toEqual([0, 1, 2]);
    const layout = networkLayout(network);
    expect(layout.edges.find((e) => e.key === 'c-app|a-app')?.backward).toBe(true);
    expect(layout.edges.filter((e) => e.backward)).toHaveLength(1);
    expect(layout.height).toBe(PAD_Y * 2 + ROW_HEIGHT + LOOP_DEPTH);
  });

  it('caps a crowded column, keeps the centre drawn and counts what is left out', async () => {
    const edges: [string, string][] = Array.from({ length: MAX_NODES_PER_LAYER + 3 }, (_, i) => [
      `app-${String(i).padStart(2, '0')}`,
      'hub',
    ]);
    const network = await collectPactNetwork(reader(edges).read, 'app-14');
    const layout = networkLayout(network);
    const first = layout.nodes.filter((n) => n.layer === 0);
    expect(first).toHaveLength(MAX_NODES_PER_LAYER);
    expect(first.some((n) => n.slug === 'app-14')).toBe(true);
    expect(layout.overflow).toEqual([expect.objectContaining({ layer: 0, hidden: 3 })]);
    expect(layout.hiddenNodes).toBe(3);
    expect(layout.hiddenEdges).toBe(3);
    expect(networkAriaLabel(network, layout)).toBe(
      'Network of App 14: 16 pacticipants, 15 integrations (15 Verified); 3 pacticipants and 3 integrations are only in the table',
    );
  });

  it('marks unread pacticipants and does not draw a pact of a pacticipant with itself', () => {
    const network: PactNetwork = {
      centre: 'a-app',
      pacticipants: [
        { slug: 'a-app', name: 'A', distance: 0 },
        { slug: 'b-app', name: 'B', distance: 1, gap: 'not-read' },
      ],
      integrations: [
        {
          ...(networkFixture as PactNetwork).integrations[0],
          consumer: { slug: 'a-app', name: 'A' },
          provider: { slug: 'b-app', name: 'B' },
        },
        {
          ...(networkFixture as PactNetwork).integrations[0],
          consumer: { slug: 'a-app', name: 'A' },
          provider: { slug: 'a-app', name: 'A' },
        },
      ],
    };
    const layout = networkLayout(network);
    expect(layout.nodes.find((n) => n.slug === 'b-app')).toMatchObject({ gap: 'not-read' });
    expect(layout.nodes.find((n) => n.slug === 'b-app')?.ariaLabel).toContain(
      '(its pacts were not read)',
    );
    expect(layout.edges).toHaveLength(1);
    expect(layout.hiddenEdges).toBe(1);
  });

  it('cuts long captions', () => {
    expect(caption('short')).toBe('short');
    expect(caption('a-very-long-pacticipant-name')).toBe('a-very-long-pacticipa…');
  });
});

// --- the proxy -----------------------------------------------------------------------------------

describe('the /api/pact network proxy', () => {
  const realFetch = global.fetch;
  const ctx = (pacticipant: string) => ({ params: Promise.resolve({ pacticipant }) });
  const req = (path: string) => new NextRequest(`http://ui${path}`);

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
  });
  afterEach(() => {
    global.fetch = realFetch;
  });

  it('reads every matrix as the signed-in user, in the session tenant', async () => {
    const { read } = reader(EDGES);
    const urls: string[] = [];
    const headers: unknown[] = [];
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      urls.push(String(input));
      headers.push(init?.headers);
      const answer = await read(String(input).replace('http://rest/v1/tenants/acme/', ''));
      return { ok: answer.ok, status: answer.status, json: async () => answer.body } as Response;
    }) as unknown as typeof fetch;
    const response = await networkGet(
      req('/api/pact/pacticipants/billing-service/network'),
      ctx('billing-service'),
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as PactNetwork;
    expect(body.integrations).toHaveLength(6);
    expect(
      urls.every((url) => url.startsWith('http://rest/v1/tenants/acme/pact-broker/matrix?')),
    ).toBe(true);
    expect(
      headers.every((h) => (h as Record<string, string>).Authorization === 'Bearer session'),
    ).toBe(true);
  });

  it('refuses any parameter and a malformed handle without calling REST', async () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    const param = await networkGet(req('/api/pact/pacticipants/x/network?depth=3'), ctx('x'));
    expect(param.status).toBe(400);
    expect(await param.json()).toEqual({
      success: false,
      error: 'Unsupported parameter depth: this read accepts no parameters.',
    });
    expect((await networkGet(req('/api/pact/pacticipants/x/network'), ctx('../x'))).status).toBe(
      404,
    );
    expect(
      (await networkGet(req('/api/pact/pacticipants/x/network'), ctx('Bad Name'))).status,
    ).toBe(404);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('passes the session’s refusal through', async () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    tenant = {
      error: NextResponse.json({ success: false, error: 'No workspace selected' }, { status: 403 }),
    };
    expect((await networkGet(req('/api/pact/pacticipants/x/network'), ctx('x'))).status).toBe(403);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('keeps REST’s refusal of the pacticipant, and says when REST is unreachable', async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: { message: 'Permission denied' } }),
    })) as unknown as typeof fetch;
    const refused = await networkGet(req('/api/pact/pacticipants/x/network'), ctx('x'));
    expect(refused.status).toBe(403);
    expect(await refused.json()).toEqual({ success: false, error: 'Permission denied' });

    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    expect((await networkGet(req('/api/pact/pacticipants/x/network'), ctx('x'))).status).toBe(503);
  });
});

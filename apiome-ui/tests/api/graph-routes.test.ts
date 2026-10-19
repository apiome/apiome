/**
 * @jest-environment node
 *
 * The dependency-graph BFF routes — CDG-3.4 (#5969).
 *
 * The tenant comes from the session; the graph lives under `/v1/graph/{tenant}`; the edges route
 * always asks for labels and checks its kind and id before building a REST URL; only allowed query
 * parameters and body fields are forwarded; and REST's refusal keeps its status.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({
    ok: true,
    user: { user_id: 'u-1', email: 'ada@acme.io' },
    tenantSlug: 'acme',
  })),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { GET as listEntities } from '@/app/api/graph/entities/route';
import { GET as readEdges } from '@/app/api/graph/edges/[kind]/[id]/route';
import { POST as blastRadius } from '@/app/api/graph/blast-radius/route';

const ID = '22222222-2222-4222-8222-222222222222';
let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { ok: true } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

const params = <T extends Record<string, string>>(value: T) => ({ params: Promise.resolve(value) });

describe('entities', () => {
  test('forwards only the allowed, well-formed filters', async () => {
    await listEntities(
      new NextRequest(
        'http://ui.test/api/graph/entities?q=pet&kind=project&kind=galaxy&team=payments&provenance=declared&provenance=rumoured&limit=2000&evil=1'
      )
    );
    expect(upstream).toHaveLength(1);
    const url = new URL(upstream[0].url);
    expect(url.pathname).toBe('/v1/graph/acme/entities');
    expect(url.searchParams.getAll('kind')).toEqual(['project']);
    expect(url.searchParams.getAll('provenance')).toEqual(['declared']);
    expect(url.searchParams.get('q')).toBe('pet');
    expect(url.searchParams.get('team')).toBe('payments');
    expect(url.searchParams.get('evil')).toBeNull();
  });
});

describe('edges', () => {
  test('asks for labels and passes the direction through', async () => {
    reply = { status: 200, body: { edges: [], total: 0, truncated: false } };
    const response = await readEdges(
      new NextRequest(`http://ui.test/api/graph/edges/project/${ID}?direction=in&labels=false`),
      params({ kind: 'project', id: ID })
    );
    expect(response.status).toBe(200);
    const url = new URL(upstream[0].url);
    expect(url.pathname).toBe(`/v1/graph/acme/entities/project/${ID}/edges`);
    expect(url.searchParams.get('labels')).toBe('true');
    expect(url.searchParams.get('direction')).toBe('in');
  });

  test.each([
    ['galaxy', ID],
    ['project', 'not-an-id'],
    ['project', '../../admin'],
  ])('refuses kind %s / id %s without calling REST', async (kind, id) => {
    const response = await readEdges(new NextRequest('http://ui.test/x'), params({ kind, id }));
    expect(response.status).toBe(400);
    expect(upstream).toHaveLength(0);
  });

  test("keeps REST's refusal", async () => {
    reply = { status: 403, body: { detail: 'Missing projects:view' } };
    const response = await readEdges(new NextRequest('http://ui.test/x'), params({ kind: 'consumer', id: ID }));
    expect(response.status).toBe(403);
    expect(((await response.json()) as { success: boolean }).success).toBe(false);
  });
});

describe('blast radius', () => {
  test('forwards only the fields REST accepts', async () => {
    await blastRadius(
      new NextRequest('http://ui.test/api/graph/blast-radius', {
        method: 'POST',
        body: JSON.stringify({
          entity: { kind: 'project', id: ID, extra: 1 },
          pointers: ['/paths/~1pets/get', 7],
          depth: 2,
          provenance: ['declared'],
          version: '1.0.0',
          tenant: 'someone-else',
        }),
      })
    );
    expect(upstream[0].url).toBe('http://rest.test/v1/graph/acme/blast-radius');
    expect(upstream[0].body).toEqual({
      entity: { kind: 'project', id: ID },
      pointers: ['/paths/~1pets/get'],
      depth: 2,
      provenance: ['declared'],
      version: '1.0.0',
    });
  });

  test('refuses a body without an entity, or that is not JSON', async () => {
    const missing = await blastRadius(
      new NextRequest('http://ui.test/x', { method: 'POST', body: JSON.stringify({ pointers: [] }) })
    );
    const broken = await blastRadius(new NextRequest('http://ui.test/x', { method: 'POST', body: '{' }));
    expect([missing.status, broken.status]).toEqual([400, 400]);
    expect(upstream).toHaveLength(0);
  });
});

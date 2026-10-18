/**
 * @jest-environment node
 *
 * The teams and owners BFF routes — CDG-2.4 (#5963).
 *
 * Drives the real handlers with the tenant context and the upstream `fetch` mocked, and pins what
 * this layer exists for: the tenant comes from the session; every path segment is checked before it
 * reaches an apiome-rest URL (a crafted slug, kind or id is a 400 with no upstream call); bulk assign
 * maps to `owners:assign`; and REST's refusal keeps its status and message — an unknown team stays a
 * 404 the page can show.
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
import { GET as listTeams } from '@/app/api/teams/route';
import { GET as readTeam } from '@/app/api/teams/[slug]/route';
import { GET as readActivity } from '@/app/api/teams/[slug]/activity/route';
import { GET as readOwner, PUT as putOwner } from '@/app/api/owners/[kind]/[id]/route';
import { POST as confirmOwner } from '@/app/api/owners/[kind]/[id]/confirm/route';
import { POST as assignOwners } from '@/app/api/owners/assign/route';

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
const json = (body: unknown) =>
  new NextRequest('http://ui.test/api/x', { method: 'POST', body: JSON.stringify(body) });

describe('teams', () => {
  test('list, read and activity reach the tenant-scoped REST paths', async () => {
    await listTeams();
    await readTeam(new Request('http://ui.test'), params({ slug: 'payments' }));
    await readActivity(new Request('http://ui.test'), params({ slug: 'payments' }));
    expect(upstream.map((call) => call.url)).toEqual([
      'http://rest.test/v1/tenants/acme/teams',
      'http://rest.test/v1/tenants/acme/teams/payments',
      'http://rest.test/v1/tenants/acme/teams/payments/activity',
    ]);
  });

  test('a slug that is not slug-shaped never reaches REST', async () => {
    for (const slug of ['../owners', 'Pay ments', 'payments/members']) {
      const response = await readTeam(new Request('http://ui.test'), params({ slug }));
      expect(response.status).toBe(400);
    }
    expect(upstream).toEqual([]);
  });
});

describe('owners', () => {
  test('read and assign address the entity, with only the team in the body', async () => {
    await readOwner(new NextRequest('http://ui.test'), params({ kind: 'catalog_item', id: ID }));
    await putOwner(json({ team: 'payments', extra: 'dropped' }), params({ kind: 'catalog_item', id: ID }));
    expect(upstream[0]).toMatchObject({ url: `http://rest.test/v1/tenants/acme/owners/catalog_item/${ID}`, method: 'GET' });
    expect(upstream[1]).toMatchObject({ method: 'PUT', body: { team: 'payments' } });
  });

  test('confirm forwards the team it names, or none', async () => {
    await confirmOwner(json({ team: 'payments' }), params({ kind: 'consumer', id: ID }));
    await confirmOwner(json({}), params({ kind: 'consumer', id: ID }));
    expect(upstream.map((call) => [call.url, call.body])).toEqual([
      [`http://rest.test/v1/tenants/acme/owners/consumer/${ID}/confirm`, { team: 'payments' }],
      [`http://rest.test/v1/tenants/acme/owners/consumer/${ID}/confirm`, {}],
    ]);
  });

  test('an unknown kind or a non-UUID id is refused before REST', async () => {
    expect((await readOwner(new NextRequest('http://ui.test'), params({ kind: 'widget', id: ID }))).status).toBe(400);
    expect(
      (await confirmOwner(json({}), params({ kind: 'project', id: '../../teams' }))).status
    ).toBe(400);
    expect(upstream).toEqual([]);
  });

  test('bulk assign maps to owners:assign and validates every entity', async () => {
    await assignOwners(json({ team: 'payments', entities: [{ kind: 'project', id: ID }] }));
    expect(upstream[0]).toMatchObject({
      url: 'http://rest.test/v1/tenants/acme/owners:assign',
      method: 'POST',
      body: { team: 'payments', entities: [{ kind: 'project', id: ID }] },
    });
    for (const body of [
      { team: 'payments', entities: [] },
      { entities: [{ kind: 'project', id: ID }] },
      { team: 'payments', entities: [{ kind: 'widget', id: ID }] },
    ]) {
      expect((await assignOwners(json(body))).status).toBe(400);
    }
    expect(upstream).toHaveLength(1);
  });

  test('an unknown team keeps REST’s 404 and message', async () => {
    reply = { status: 404, body: { detail: { code: 'owner-team-not-found', message: "no team 'ghost' in this tenant" } } };
    const response = await putOwner(json({ team: 'ghost' }), params({ kind: 'project', id: ID }));
    expect(response.status).toBe(404);
    expect(((await response.json()) as { error: string }).error).toContain("no team 'ghost'");
  });
});

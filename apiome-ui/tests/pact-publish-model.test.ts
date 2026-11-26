/**
 * @jest-environment node
 */
/**
 * Publish pacts from the Pact import dialog — PFX-5.8 (#6952): the model and the `/api/pact/publish` proxy.
 */

import { jest } from '@jest/globals';
import { NextResponse } from 'next/server';

const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restStatus = 200;

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restStatus < 400
      ? NextResponse.json({ notices: [{ type: 'success', text: 'Published' }] })
      : NextResponse.json({ success: false, error: 'Conflict' }, { status: restStatus });
  },
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  buildPublishRequest,
  parseTags,
  pactConsumerName,
  pickPublishBody,
  readPublishNotices,
  validatePublishDraft,
  type PublishDraft,
} from '../lib/pact-publish';
import { POST } from '../src/app/api/pact/publish/route';

const PACT = JSON.stringify({ consumer: { name: 'billing-service' }, interactions: [] });
const DRAFT: PublishDraft = { providerName: 'orders-api', version: '9f3c2a1', branch: '', tags: '', buildUrl: '' };
const ok = (over: Record<string, unknown> = {}) => ({
  consumerName: 'billing-service',
  providerName: 'orders-api',
  version: '9f3c2a1',
  pact: PACT,
  ...over,
});
const post = (body: unknown) =>
  POST(new Request('http://x/api/pact/publish', { method: 'POST', body: JSON.stringify(body) }) as never);

beforeEach(() => {
  forwarded.length = 0;
  restStatus = 200;
});

describe('model', () => {
  it('splits and dedupes tags', () => {
    expect(parseTags('prod, release-2  prod,,')).toEqual(['prod', 'release-2']);
    expect(parseTags('')).toEqual([]);
  });

  it('reads the consumer a pact names', () => {
    expect(pactConsumerName(PACT)).toBe('billing-service');
    expect(pactConsumerName('not json')).toBe('');
    expect(pactConsumerName('[]')).toBe('');
  });

  it('names the first problem in the draft', () => {
    expect(validatePublishDraft(DRAFT, '')).toMatch(/names no consumer/);
    expect(validatePublishDraft({ ...DRAFT, providerName: ' ' }, 'c')).toMatch(/provider/);
    expect(validatePublishDraft({ ...DRAFT, version: '' }, 'c')).toMatch(/consumer version/);
    expect(validatePublishDraft({ ...DRAFT, branch: 'x'.repeat(256) }, 'c')).toMatch(/Branch/);
    expect(validatePublishDraft({ ...DRAFT, tags: Array.from({ length: 51 }, (_, i) => `t${i}`).join(' ') }, 'c')).toMatch(/50/);
    expect(validatePublishDraft({ ...DRAFT, buildUrl: 'ftp://x' }, 'c')).toMatch(/http/);
    expect(validatePublishDraft({ ...DRAFT, tags: 'a b', buildUrl: 'https://ci/1' }, 'c')).toBeNull();
  });

  it('builds the request without empty optional fields', () => {
    expect(buildPublishRequest(PACT, 'c', DRAFT)).toEqual({
      consumerName: 'c', providerName: 'orders-api', version: '9f3c2a1', pact: PACT,
    });
    expect(buildPublishRequest(PACT, 'c', { ...DRAFT, branch: 'main', tags: 'a,b', buildUrl: 'https://ci/1' })).toMatchObject({
      branch: 'main', tags: ['a', 'b'], buildUrl: 'https://ci/1',
    });
  });

  it('reads notices', () => {
    expect(readPublishNotices({ notices: [{ text: 'a' }, { nope: 1 }, null] })).toEqual(['a']);
    expect(readPublishNotices(null)).toEqual([]);
  });
});

describe('pickPublishBody', () => {
  it('base64-encodes the pact into REST\'s body', () => {
    const picked = pickPublishBody(ok({ branch: 'main', tags: ['t'], buildUrl: 'https://ci/1' }));
    expect(picked.ok).toBe(true);
    if (!picked.ok) return;
    const contract = (picked.body.contracts as Array<Record<string, string>>)[0];
    expect(Buffer.from(contract.content, 'base64').toString()).toBe(PACT);
    expect(picked.body).toMatchObject({ pacticipantName: 'billing-service', pacticipantVersionNumber: '9f3c2a1', branch: 'main', tags: ['t'] });
  });

  it.each([
    ['not an object', [], /JSON object/],
    ['unknown field', ok({ merge: true }), /Unsupported field merge/],
    ['missing pact', { ...ok(), pact: undefined }, /pact is required/],
    ['blank version', ok({ version: ' ' }), /version is required/],
    ['mistyped field', ok({ branch: 3 }), /branch must be a string/],
    ['long name', ok({ providerName: 'x'.repeat(256) }), /longer than/],
    ['bad url', ok({ buildUrl: 'javascript:1' }), /buildUrl/],
    ['bad tags', ok({ tags: [''] }), /tags must be/],
    ['too many tags', ok({ tags: Array.from({ length: 51 }, (_, i) => `t${i}`) }), /at most 50/],
    ['huge pact', ok({ pact: 'x'.repeat(8 * 1024 * 1024 + 1) }), /too large/],
  ])('refuses %s', (_name, body, message) => {
    const picked = pickPublishBody(body);
    expect(picked.ok).toBe(false);
    if (!picked.ok) expect(picked.error).toMatch(message);
  });
});

describe('proxy', () => {
  it('forwards a checked body as the user', async () => {
    const response = await post(ok());
    expect(response.status).toBe(200);
    expect(forwarded).toHaveLength(1);
    expect(forwarded[0].method).toBe('POST');
    expect(forwarded[0].url).toBe('http://rest/v1/tenants/acme/pact-broker/contracts/publish');
  });

  it('refuses a bad body or non-JSON without calling REST', async () => {
    expect((await post(ok({ extra: 1 }))).status).toBe(400);
    const bad = await POST(new Request('http://x', { method: 'POST', body: 'nope' }) as never);
    expect(bad.status).toBe(400);
    expect(forwarded).toHaveLength(0);
  });

  it('keeps REST\'s refusal', async () => {
    restStatus = 409;
    expect((await post(ok())).status).toBe(409);
  });
});


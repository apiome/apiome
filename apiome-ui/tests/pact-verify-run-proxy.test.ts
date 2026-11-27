/**
 * @jest-environment node
 */
/**
 * The BFF of **Run a verification** — PFX-8.8 (#7305): `/api/pact/verification/preview` and
 * `/api/pact/verification/run`.
 *
 * * an unknown, mistyped or oversized field is a 400 naming it, and REST is not called;
 * * a run needs a target and a provider version; a preview does not;
 * * a checked body is forwarded as the signed-in user to the REST path of its provider, and REST's
 *   refusal (the production rule) comes back with its status and message.
 */

import { pickVerifyRequest, verifyRestPath } from '../lib/pact-verify-run-proxy';

import { NextResponse } from 'next/server';

const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restAnswer: () => NextResponse = () => NextResponse.json({ ok: true });

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restAnswer();
  },
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { POST as previewPost } from '../src/app/api/pact/verification/preview/route';
import { POST as runPost } from '../src/app/api/pact/verification/run/route';

const RUN = {
  provider: 'billing-service',
  body: {
    target_ref: 'staging',
    provider_version: '2.7.0',
    selection: { consumerVersionSelectors: [{ mainBranch: true }], includePendingStatus: true },
    verification: { allow_mutating: false, provider_states_setup_url: '/_pact/states' },
    skip_already_verified: true,
    publish: true,
    context: { commit: 'abc' },
  },
};

function request(body: unknown): Request {
  return new Request('http://localhost/api/pact/verification/run', { method: 'POST', body: JSON.stringify(body) });
}

describe('pickVerifyRequest', () => {
  it('accepts what the page sends', () => {
    expect(pickVerifyRequest(RUN, 'run')).toEqual({ ok: true, request: RUN });
    expect(pickVerifyRequest({ provider: 'billing-service' }, 'preview')).toEqual({ ok: true, request: { provider: 'billing-service', body: {} } });
  });

  it.each([
    [null, 'The request must be a JSON object.'],
    [{ ...RUN, extra: 1 }, 'extra is not a field of this request.'],
    [{ body: RUN.body }, 'provider is required.'],
    [{ ...RUN, body: { ...RUN.body, widen: true } }, 'body.widen is not a field a run takes.'],
    [{ ...RUN, body: { ...RUN.body, publish: 'yes' } }, 'body.publish must be true or false.'],
    [{ ...RUN, body: { ...RUN.body, verification: { fixtures: [] } } }, 'body.verification.fixtures is not a field the page sends.'],
    [{ ...RUN, body: { ...RUN.body, selection: { providerVersionTags: [] } } }, 'body.selection.providerVersionTags is not a field the page sends.'],
    [{ ...RUN, body: { ...RUN.body, selection: { consumerVersionSelectors: [{ branch: { $ne: 1 } }] } } }, 'A consumer-version selector holds only names and true / false.'],
    [{ ...RUN, body: { ...RUN.body, target_ref: '' } }, 'body.target_ref is required.'],
    [{ ...RUN, body: { ...RUN.body, context: { a: 1 } } }, 'body.context values must be text.'],
  ])('refuses %j', (raw, error) => {
    expect(pickVerifyRequest(raw, 'run')).toEqual({ ok: false, error });
  });

  it('a preview takes no publish, build URL or context', () => {
    expect(pickVerifyRequest({ provider: 'p', body: { publish: true } }, 'preview')).toEqual({
      ok: false,
      error: 'body.publish is not a field a preview takes.',
    });
  });

  it('names the REST path of the provider', () => {
    expect(verifyRestPath('billing service', 'run')).toBe('pact-verifier/pacts/provider/billing%20service/verify');
    expect(verifyRestPath('billing', 'preview')).toBe('pact-verifier/pacts/provider/billing/verify/preview');
  });
});

describe('the routes', () => {
  beforeEach(() => {
    forwarded.length = 0;
    restAnswer = () => NextResponse.json({ ok: true });
  });

  it('forwards a checked run as the signed-in user and passes REST’s refusal through', async () => {
    restAnswer = () =>
      NextResponse.json({ success: false, error: 'Requests that change data are never sent to a production target.' }, { status: 422 });
    const answer = await runPost(request(RUN) as never);
    expect(forwarded).toEqual([
      { url: 'http://rest/v1/tenants/acme/pact-verifier/pacts/provider/billing-service/verify', method: 'POST', body: RUN.body },
    ]);
    expect(answer.status).toBe(422);
    expect((await answer.json()).error).toContain('never sent to a production target');
  });

  it('refuses a bad body without calling REST', async () => {
    const answer = await runPost(request({ provider: 'p', body: { target_ref: 'x' } }) as never);
    expect(answer.status).toBe(400);
    expect(forwarded).toEqual([]);
  });

  it('forwards a preview to its own path', async () => {
    const answer = await previewPost(request({ provider: 'billing', body: { selection: {} } }) as never);
    expect(answer.status).toBe(200);
    expect(forwarded[0]).toMatchObject({ url: 'http://rest/v1/tenants/acme/pact-verifier/pacts/provider/billing/verify/preview', method: 'POST' });
  });
});

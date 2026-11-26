/**
 * @jest-environment node
 */
/**
 * Webhooks UI and execution log — PFX-5.6 (#6950): the model and the `/api/pact/webhooks` proxies.
 *
 * * **Routes and paths**: the page routes and the REST paths the proxies forward to.
 * * **Delivery query**: `webhook` an id, `status` one of four, `cursor`; anything else refused.
 * * **Webhook body**: only the webhook's fields; a body without a request or target refused.
 * * **Wording**: events, statuses, triggers, scopes, targets; the plain-text log.
 * * **Editor**: a webhook read back into the form keeps every secret as `**********`; the form
 *   becomes the Pact Broker's body (HTTP and GitHub); what a person can fix is caught first.
 * * **Proxies**: forward as the signed-in user in the session tenant; refuse bad input without
 *   calling REST; keep REST's refusal; the overview needs both reads.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restAnswer: { status: number; body: unknown } = { status: 200, body: { ok: true } };

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restAnswer.status < 400
      ? NextResponse.json(restAnswer.body)
      : NextResponse.json({ success: false, error: 'Permission denied' }, { status: restAnswer.status });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  REDACTED,
  canRedeliver,
  collectWebhooks,
  deliveryProxyPath,
  deliveryQueryProblem,
  deliveryRoute,
  deliveryStatus,
  emptyWebhookForm,
  eventLabel,
  executeProxyPath,
  formFromWebhook,
  isWebhookId,
  parseBody,
  parseHeaders,
  pickWebhookBody,
  redeliverProxyPath,
  renderDeliveryLog,
  requestDescription,
  scopeLabel,
  targetLabel,
  toggleBody,
  triggerTypeLabel,
  webhookBodyFromForm,
  webhookFormProblem,
  webhookProxyPath,
  webhookRoute,
  type DeliveryDetail,
  type WebhookDocument,
} from '../lib/pact-webhooks';
import { RollupError } from '../lib/pact-pacticipants';
import { GET as listGet, POST as createPost } from '../src/app/api/pact/webhooks/route';
import { POST as unsavedPost } from '../src/app/api/pact/webhooks/execute/route';
import {
  DELETE as webhookDelete,
  GET as webhookGet,
  PUT as webhookPut,
} from '../src/app/api/pact/webhooks/[webhookId]/route';
import { POST as executePost } from '../src/app/api/pact/webhooks/[webhookId]/execute/route';
import { GET as deliveriesGet } from '../src/app/api/pact/webhooks/deliveries/route';
import { GET as deliveryGet } from '../src/app/api/pact/webhooks/deliveries/[deliveryId]/route';
import { POST as redeliverPost } from '../src/app/api/pact/webhooks/deliveries/[deliveryId]/redeliver/route';
import fixture from './fixtures/pact-webhooks.json';

const WEBHOOKS = fixture.webhooks as unknown as WebhookDocument[];
const [HTTP, GITHUB, PLAIN] = WEBHOOKS;
const DETAIL = fixture.detail as unknown as DeliveryDetail;

describe('routes and REST paths', () => {
  it('names the pages and the REST paths', () => {
    expect(webhookRoute(HTTP.uuid)).toBe(`/ade/dashboard/pacts/webhooks/${HTTP.uuid}`);
    expect(deliveryRoute(DETAIL.id)).toBe(`/ade/dashboard/pacts/webhooks/deliveries/${DETAIL.id}`);
    expect(webhookProxyPath(HTTP.uuid.toUpperCase())).toBe(`pact-broker/webhooks/${HTTP.uuid}`);
    expect(executeProxyPath(HTTP.uuid)).toBe(`pact-broker/webhooks/${HTTP.uuid}/execute`);
    expect(deliveryProxyPath(DETAIL.id)).toBe(`pact-webhook-deliveries/${DETAIL.id}`);
    expect(redeliverProxyPath(DETAIL.id)).toBe(`pact-webhook-deliveries/${DETAIL.id}/redeliver`);
  });

  it('knows an id when it sees one', () => {
    expect(isWebhookId(HTTP.uuid)).toBe(true);
    expect(isWebhookId(HTTP.uuid.toUpperCase())).toBe(true);
    for (const bad of ['', '7', 'not-a-uuid', `${HTTP.uuid}x`, '../webhooks']) expect(isWebhookId(bad)).toBe(false);
  });
});

describe('the delivery query', () => {
  it('accepts an id, a status and a cursor', () => {
    expect(deliveryQueryProblem(new URLSearchParams({ webhook: HTTP.uuid, status: 'failure', cursor: 'abc' }))).toBeNull();
  });

  it.each([
    [{ webhook: 'nope' }, 'The webhook parameter is not a webhook id.'],
    [{ status: 'exploded' }, 'The status parameter must be one of failure, retrying, not_run, success.'],
    [{ cursor: 'x'.repeat(3000) }, 'The cursor is not valid.'],
  ])('refuses %j', (params, error) => {
    expect(deliveryQueryProblem(new URLSearchParams(params))).toBe(error);
  });
});

describe('the webhook body', () => {
  it('keeps a body of webhook fields', () => {
    const body = { events: [{ name: 'contract_published' }], request: { method: 'POST', url: 'https://x.example' } };
    expect(pickWebhookBody(body)).toEqual({ ok: true, body });
  });

  it.each([
    [null, 'The body must be a JSON object describing the webhook.'],
    [[], 'The body must be a JSON object describing the webhook.'],
    [{ events: [] }, 'A webhook needs a request or a target.'],
    [
      { request: {}, uuid: 'x' },
      'Unsupported field uuid: a webhook takes description, consumer, provider, enabled, events, request, target, signingSecret.',
    ],
  ])('refuses %j', (raw, error) => {
    expect(pickWebhookBody(raw)).toEqual({ ok: false, error });
  });
});

describe('wording', () => {
  it('labels events, statuses and triggers, and keeps what it does not know', () => {
    expect(eventLabel('contract_requiring_verification_published')).toBe('Contract requiring verification published');
    expect(eventLabel('something_new')).toBe('something_new');
    expect(deliveryStatus('success')).toEqual({ label: 'Delivered', variant: 'ok' });
    expect(deliveryStatus('failure')).toEqual({ label: 'Failed', variant: 'danger' });
    expect(deliveryStatus('retrying').label).toBe('Retrying');
    expect(deliveryStatus('not_run').label).toBe('Queued');
    expect(deliveryStatus('odd')).toEqual({ label: 'odd', variant: 'neutral' });
    expect(triggerTypeLabel('user')).toBe('Redelivery');
    expect(triggerTypeLabel('resource_creation')).toBe('Event');
    expect(triggerTypeLabel('other')).toBe('other');
  });

  it('only a finished delivery can be sent again', () => {
    expect(['success', 'failure', 'retrying', 'not_run'].map(canRedeliver)).toEqual([true, true, false, false]);
  });

  it('says which pacts a webhook is for and where it sends', () => {
    expect(scopeLabel(HTTP)).toBe('Provider Ledger API');
    expect(scopeLabel(GITHUB)).toBe('Billing Service → Ledger API');
    expect(scopeLabel({ consumer: { name: 'Mobile App' } })).toBe('Consumer Mobile App');
    expect(scopeLabel(PLAIN)).toBe('All pacts');
    expect(targetLabel(HTTP)).toBe('POST ci.example.com');
    expect(targetLabel(GITHUB)).toBe('GitHub Actions · acme/billing-service');
    expect(targetLabel({ request: { method: 'PUT', url: 'not a url' } })).toBe('PUT not a url');
  });

  it('renders the log of every attempt, and says when nothing was sent', () => {
    const log = renderDeliveryLog(DETAIL);
    expect(log.split('\n').slice(0, 2)).toEqual([
      'Contract requiring verification published — Billing Service → Ledger API',
      'Webhook POST ci.example.com · Failed · 4 attempts',
    ]);
    expect(log).toContain('--- Attempt 1 · HTTP 503 ---');
    expect(log).toContain('moved to the dead-letter list');
    expect(renderDeliveryLog({ ...DETAIL, attemptsMade: 0, executions: [] })).toContain('Not sent yet.');
  });
});

describe('the editor', () => {
  it('reads a webhook back with every secret redacted', () => {
    const form = formFromWebhook(HTTP);
    expect(form).toMatchObject({
      description: 'Verify Ledger API when a pact changes',
      provider: 'Ledger API',
      consumer: '',
      kind: 'http',
      method: 'POST',
      events: ['contract_requiring_verification_published'],
      signingSecret: REDACTED,
      password: '',
    });
    expect(form.headers).toBe(`Content-Type: application/json\nAuthorization: ${REDACTED}`);
    expect(JSON.parse(form.body)).toEqual(HTTP.request.body);

    const github = formFromWebhook(GITHUB);
    expect(github).toMatchObject({ kind: 'github', repository: 'acme/billing-service', eventType: 'pact_verified', token: REDACTED, headers: '', url: '' });

    // A webhook saved without a description reads as its request; the form starts it empty.
    const plain = formFromWebhook(PLAIN);
    expect(requestDescription(PLAIN.request)).toBe('POST hooks.example.net');
    expect(plain).toMatchObject({ description: '', username: 'ci', password: REDACTED, enabled: false });
  });

  it('turns the form into the Pact Broker body — and a toggle keeps every stored secret', () => {
    expect(toggleBody(HTTP, false)).toEqual({
      description: 'Verify Ledger API when a pact changes',
      provider: { name: 'Ledger API' },
      events: [{ name: 'contract_requiring_verification_published' }],
      enabled: false,
      request: {
        method: 'POST',
        url: HTTP.request.url,
        headers: { 'Content-Type': 'application/json', Authorization: REDACTED },
        body: HTTP.request.body,
      },
      signingSecret: REDACTED,
    });
    expect(toggleBody(GITHUB, true)).toEqual({
      description: 'Report verification results to Billing Service',
      consumer: { name: 'Billing Service' },
      provider: { name: 'Ledger API' },
      events: [{ name: 'provider_verification_succeeded' }, { name: 'provider_verification_failed' }],
      enabled: true,
      target: { type: 'github_repository_dispatch', repository: 'acme/billing-service', token: REDACTED, eventType: 'pact_verified' },
    });
    expect(toggleBody(PLAIN, true)).toEqual({
      events: [{ name: 'contract_published' }],
      enabled: true,
      request: { method: 'POST', url: 'https://hooks.example.net/pact', username: 'ci', password: REDACTED },
    });
  });

  it('sends a text body as text and leaves an empty one out', () => {
    expect(parseBody('  ')).toBeUndefined();
    expect(parseBody('{"a": 1}')).toEqual({ a: 1 });
    expect(parseBody('plain text ${pactbroker.pactUrl}')).toBe('plain text ${pactbroker.pactUrl}');
    const body = webhookBodyFromForm({ ...emptyWebhookForm(), url: 'https://x.example/h', body: '', headers: '' });
    expect(body.request).toEqual({ method: 'POST', url: 'https://x.example/h' });
  });

  it('reads headers line by line', () => {
    expect(parseHeaders('A: 1\n\n  B:two:three  ')).toEqual({ ok: true, headers: { A: '1', B: 'two:three' } });
    expect(parseHeaders('no colon')).toEqual({ ok: false, error: 'Header line 1 is not "Name: value".' });
    expect(parseHeaders('A: 1\na: 2')).toEqual({ ok: false, error: 'The header a is given more than once.' });
  });

  it.each([
    [{ events: [] }, 'Choose at least one event.'],
    [{ url: 'ftp://x.example' }, 'Enter the http(s) URL to send to.'],
    [{ url: 'https://x.example', method: 'GET' }, 'Choose POST, PUT or PATCH.'],
    [{ url: 'https://x.example', headers: 'oops' }, 'Header line 1 is not "Name: value".'],
    [{ url: 'https://x.example', password: 'p' }, 'A password needs a username.'],
    [{ kind: 'github', repository: 'not a repo' }, 'Enter the GitHub repository as owner/name.'],
    [{ kind: 'github', repository: 'acme/api', token: '' }, 'Enter a GitHub token that may dispatch events to the repository.'],
    [{ url: 'https://x.example', signingSecret: 'short' }, 'A signing secret has at least 16 characters.'],
  ])('catches %j before sending', (overrides, problem) => {
    expect(webhookFormProblem({ ...emptyWebhookForm(), ...overrides } as never)).toBe(problem);
  });

  it('accepts a complete form, and a kept signing secret', () => {
    expect(webhookFormProblem({ ...emptyWebhookForm(), url: 'https://x.example' })).toBeNull();
    expect(webhookFormProblem({ ...formFromWebhook(HTTP) })).toBeNull();
    expect(webhookFormProblem({ ...formFromWebhook(GITHUB) })).toBeNull();
  });
});

describe('the overview roll-up', () => {
  const list = { ok: true, status: 200, body: { _embedded: { webhooks: WEBHOOKS } } };
  const latest = { ok: true, status: 200, body: { latest: fixture.latest } };

  it('joins the webhooks with the newest firing of each', async () => {
    const read = jest.fn(async (path: string) => (path === 'pact-broker/webhooks' ? list : latest));
    const overview = await collectWebhooks(read);
    expect(overview.webhooks).toHaveLength(3);
    expect(Object.keys(overview.latest)).toEqual([HTTP.uuid, GITHUB.uuid]);
    expect(read.mock.calls.map(([path]) => path).sort()).toEqual(['pact-broker/webhooks', 'pact-webhook-deliveries/latest']);
  });

  it('refuses when either read is refused, keeping REST’s status and message', async () => {
    const refused = { ok: false, status: 403, body: { detail: 'Permission denied' } };
    await expect(collectWebhooks(async (path) => (path === 'pact-broker/webhooks' ? refused : latest))).rejects.toEqual(
      new RollupError(403, 'Permission denied'),
    );
    const broken = { ok: false, status: 500, body: { detail: { message: 'boom' } } };
    await expect(collectWebhooks(async (path) => (path === 'pact-broker/webhooks' ? list : broken))).rejects.toEqual(
      new RollupError(500, 'boom'),
    );
  });
});

describe('the /api/pact/webhooks proxies', () => {
  const ctx = (params: Record<string, string>) => ({ params: Promise.resolve(params) }) as never;
  const req = (path: string, init?: { method: string; body?: string }) =>
    new NextRequest(`http://ui${path}`, init as never);
  const body = { events: [{ name: 'contract_published' }], request: { method: 'POST', url: 'https://x.example' } };
  const json = (value: unknown) => ({ method: 'POST', body: JSON.stringify(value) });

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
    restAnswer = { status: 200, body: { ok: true } };
  });

  it('reads the overview with both reads as the signed-in user', async () => {
    const fetched: string[] = [];
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      fetched.push(String(input));
      const answer = String(input).endsWith('/latest') ? { latest: fixture.latest } : { _embedded: { webhooks: WEBHOOKS } };
      return { ok: true, status: 200, json: async () => answer } as Response;
    }) as unknown as typeof fetch;
    const answer = await listGet(req('/api/pact/webhooks'));
    expect(answer.status).toBe(200);
    expect(((await answer.json()) as { webhooks: unknown[] }).webhooks).toHaveLength(3);
    expect(fetched.sort()).toEqual([
      'http://rest/v1/tenants/acme/pact-broker/webhooks',
      'http://rest/v1/tenants/acme/pact-webhook-deliveries/latest',
    ]);
    expect((await listGet(req('/api/pact/webhooks?x=1'))).status).toBe(400);
  });

  it('forwards create, replace, delete, test and redeliver to their REST routes', async () => {
    await createPost(req('/api/pact/webhooks', json(body)));
    await unsavedPost(req('/api/pact/webhooks/execute', json(body)));
    await webhookGet(req(`/api/pact/webhooks/${HTTP.uuid}`), ctx({ webhookId: HTTP.uuid }));
    await webhookPut(req(`/api/pact/webhooks/${HTTP.uuid}`, { ...json(body), method: 'PUT' }), ctx({ webhookId: HTTP.uuid }));
    await webhookDelete(req(`/api/pact/webhooks/${HTTP.uuid}`, { method: 'DELETE' }), ctx({ webhookId: HTTP.uuid }));
    await executePost(req(`/api/pact/webhooks/${HTTP.uuid}/execute`, { method: 'POST' }), ctx({ webhookId: HTTP.uuid }));
    await deliveryGet(req(`/api/pact/webhooks/deliveries/${DETAIL.id}`), ctx({ deliveryId: DETAIL.id }));
    await redeliverPost(req(`/api/pact/webhooks/deliveries/${DETAIL.id}/redeliver`, { method: 'POST' }), ctx({ deliveryId: DETAIL.id }));
    const rest = 'http://rest/v1/tenants/acme';
    expect(forwarded).toEqual([
      { method: 'POST', url: `${rest}/pact-broker/webhooks`, body },
      { method: 'POST', url: `${rest}/pact-broker/webhooks/execute`, body },
      { method: 'GET', url: `${rest}/pact-broker/webhooks/${HTTP.uuid}`, body: undefined },
      { method: 'PUT', url: `${rest}/pact-broker/webhooks/${HTTP.uuid}`, body },
      { method: 'DELETE', url: `${rest}/pact-broker/webhooks/${HTTP.uuid}`, body: undefined },
      { method: 'POST', url: `${rest}/pact-broker/webhooks/${HTTP.uuid}/execute`, body: undefined },
      { method: 'GET', url: `${rest}/pact-webhook-deliveries/${DETAIL.id}`, body: undefined },
      { method: 'POST', url: `${rest}/pact-webhook-deliveries/${DETAIL.id}/redeliver`, body: undefined },
    ]);
  });

  it('forwards the delivery log with its filters and page size', async () => {
    await deliveriesGet(req(`/api/pact/webhooks/deliveries?webhook=${HTTP.uuid}&status=failure&cursor=abc`));
    expect(forwarded[0].url).toBe(
      `http://rest/v1/tenants/acme/pact-webhook-deliveries?limit=25&webhook=${HTTP.uuid}&status=failure&cursor=abc`,
    );
  });

  it('refuses bad input without calling REST', async () => {
    const answers = [
      await createPost(req('/api/pact/webhooks', { method: 'POST', body: 'not json' })),
      await createPost(req('/api/pact/webhooks', json({ ...body, _links: {} }))),
      await unsavedPost(req('/api/pact/webhooks/execute', json({ events: [] }))),
      await webhookGet(req('/api/pact/webhooks/nope'), ctx({ webhookId: 'nope' })),
      await webhookPut(req('/api/pact/webhooks/nope', { ...json(body), method: 'PUT' }), ctx({ webhookId: 'nope' })),
      await webhookPut(req(`/api/pact/webhooks/${HTTP.uuid}`, { method: 'PUT', body: '[]' }), ctx({ webhookId: HTTP.uuid })),
      await webhookDelete(req('/api/pact/webhooks/nope', { method: 'DELETE' }), ctx({ webhookId: 'nope' })),
      await executePost(req('/api/pact/webhooks/nope/execute', { method: 'POST' }), ctx({ webhookId: 'nope' })),
      await deliveriesGet(req('/api/pact/webhooks/deliveries?status=exploded')),
      await deliveriesGet(req('/api/pact/webhooks/deliveries?webhook=nope')),
      await deliveriesGet(req('/api/pact/webhooks/deliveries?label=x')),
      await deliveriesGet(req('/api/pact/webhooks/deliveries?status=failure&status=success')),
      await deliveryGet(req('/api/pact/webhooks/deliveries/7'), ctx({ deliveryId: '7' })),
      await redeliverPost(req('/api/pact/webhooks/deliveries/7/redeliver', { method: 'POST' }), ctx({ deliveryId: '7' })),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 400, 400, 404, 404, 400, 404, 404, 400, 400, 400, 400, 404, 404]);
    expect(((await answers[1].json()) as { error: string }).error).toContain('Unsupported field _links');
    expect(((await answers[10].json()) as { error: string }).error).toContain('Unsupported parameter label');
    expect(forwarded).toHaveLength(0);
  });

  it('keeps REST’s refusal and the session’s own', async () => {
    restAnswer = { status: 409, body: {} };
    const refused = await redeliverPost(
      req(`/api/pact/webhooks/deliveries/${DETAIL.id}/redeliver`, { method: 'POST' }),
      ctx({ deliveryId: DETAIL.id }),
    );
    expect(refused.status).toBe(409);
    tenant = { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
    expect((await createPost(req('/api/pact/webhooks', json(body)))).status).toBe(401);
    expect((await listGet(req('/api/pact/webhooks'))).status).toBe(401);
    expect(forwarded).toHaveLength(1);
  });
});

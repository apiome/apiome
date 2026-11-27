/**
 * The BFF side of **Publish a provider contract** — PFX-8.6 (#7303), `lib/pact-provider-contract-proxy.ts`:
 *
 * * the browser's body is checked field by field; anything unknown, mistyped or oversized is refused
 *   with its name before REST is called (nothing silently dropped);
 * * **Run it now**: a run that does not pass — failed, errored, could not run, or whose report was
 *   not stored — **publishes nothing** and lists the failing operations; a passing run is cited by
 *   its stored report id, never by anything the browser sent;
 * * REST's refusals keep their status, message, code and pointer (a 409 conflict, a 422 with the
 *   pointer, a 403 for RBAC); an unreachable REST is a 503;
 * * the check forwards `contentUrl`; the reports list takes `project` and `version` only.
 */

import {
  CONTRACT_UNAVAILABLE,
  checkContract,
  contractPath,
  pickContractRequest,
  publishWithEvidence,
  refusal,
  reportsQuery,
  type ContractRequest,
  type RestCall,
} from '../lib/pact-provider-contract-proxy';

const BODY = { apiomeVersion: 'billing-api@2.7.0', branch: 'main' };
const REQUEST = { provider: 'Billing Service', providerVersion: '2.7.0+9f31c20', body: BODY };

/** A REST stand-in that records each call and answers from `answers` in order. */
function rest(...answers: Array<{ status: number; body: unknown } | null>) {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const call: RestCall = async (method, path, body) => {
    calls.push({ method, path, body });
    return answers.shift() ?? null;
  };
  return { call, calls };
}

const picked = (raw: unknown, mode: 'publish' | 'check' = 'publish'): ContractRequest => {
  const result = pickContractRequest(raw, mode);
  if (!result.ok) throw new Error(result.error);
  return result.request;
};

describe('reading the browser’s body', () => {
  it('accepts the page’s fields', () => {
    expect(picked(REQUEST)).toEqual({ ...REQUEST, run: null });
    expect(picked({ ...REQUEST, run: { versionRef: 'project/billing-api/2.7.0', target: 'staging' } }).run).toEqual({
      versionRef: 'project/billing-api/2.7.0',
      target: 'staging',
    });
    expect(picked({ ...REQUEST, body: { contentUrl: 'https://api.example.com/o.yaml' } }, 'check').body).toEqual({
      contentUrl: 'https://api.example.com/o.yaml',
    });
  });

  it.each([
    [null, 'must be a JSON object'],
    [{ ...REQUEST, tenant: 'other' }, 'tenant is not a field'],
    [{ ...REQUEST, provider: '' }, 'provider is required'],
    [{ ...REQUEST, provider: 'x'.repeat(256) }, 'longer than 255'],
    [{ ...REQUEST, providerVersion: 'a/b' }, 'cannot contain "/"'],
    [{ ...REQUEST, body: [] }, 'body must be an object'],
    [{ ...REQUEST, body: { ...BODY, owner: 'me' } }, 'body.owner is not a field'],
    [{ ...REQUEST, body: { ...BODY, tags: 'prod' } }, 'body.tags must be at most 50 tags'],
    [{ ...REQUEST, body: { ...BODY, branch: 7 } }, 'body.branch must be text'],
    [{ ...REQUEST, body: { ...BODY, verificationResults: { success: 'yes' } } }, 'success must be true or false'],
    [{ ...REQUEST, body: { ...BODY, verificationResults: { token: 'x' } } }, 'verificationResults.token is not a field'],
    [{ ...REQUEST, body: { contentUrl: 'https://x' } }, 'body.contentUrl is not a field'],
    [{ ...REQUEST, run: { versionRef: '../../admin', target: 's' } }, 'run.versionRef must be project/'],
    [{ ...REQUEST, run: { versionRef: 'project/a/1', target: '' } }, 'run.target is required'],
    [{ ...REQUEST, run: { versionRef: 'project/a/1', target: 's', url: 'x' } }, 'run.url is not a field'],
    [
      { ...REQUEST, body: { ...BODY, verificationResults: { providerVerificationReportId: 'forged' } }, run: { versionRef: 'project/a/1', target: 's' } },
      'Run it now brings its own evidence',
    ],
  ])('refuses %j', (raw, message) => {
    const result = pickContractRequest(raw, 'publish');
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain(message);
  });

  it('refuses a check URL that is not http(s), and a run on a check', () => {
    expect(pickContractRequest({ ...REQUEST, body: { contentUrl: 'file:///etc/passwd' } }, 'check')).toEqual({
      ok: false,
      error: 'body.contentUrl must be an http(s) URL.',
    });
    expect(pickContractRequest({ ...REQUEST, run: { versionRef: 'project/a/1', target: 's' } }, 'check')).toEqual({
      ok: false,
      error: 'run is not a field of this request.',
    });
  });
});

describe('publishing', () => {
  it('publishes and says whether the contract is new', async () => {
    const { call, calls } = rest({ status: 201, body: { providerVersion: '2.7.0+9f31c20' } });
    const answer = await publishWithEvidence(call, picked(REQUEST));
    expect(calls).toEqual([
      { method: 'PUT', path: 'pact-broker/contracts/provider/Billing%20Service/version/2.7.0%2B9f31c20', body: BODY },
    ]);
    expect(answer).toEqual({ status: 200, body: { success: true, published: true, created: true, contract: { providerVersion: '2.7.0+9f31c20' } } });
  });

  it('cites a passing run by its stored report id', async () => {
    const { call, calls } = rest(
      { status: 201, body: { ok: true, report: { outcome: 'passed', operations: [] }, stored: { id: 'report-1' }, run: { id: 'run-1' } } },
      { status: 201, body: {} },
    );
    await publishWithEvidence(call, picked({ ...REQUEST, run: { versionRef: 'project/billing-api/2.7.0', target: 'staging' } }));
    expect(calls[0]).toEqual({ method: 'POST', path: 'contracts/project/billing-api/2.7.0/verify-provider', body: { target_ref: 'staging' } });
    expect(calls[1].body).toEqual({ ...BODY, verificationResults: { providerVerificationReportId: 'report-1' } });
  });

  it.each([
    [
      'a failing run',
      {
        ok: true,
        report: {
          outcome: 'failed',
          operations: [{ http_method: 'post', http_path: '/invoices', outcome: 'failed', drift: [{ message: 'currency is missing' }] }],
        },
        stored: { id: 'report-2' },
        run: { id: 'run-2' },
      },
      'did not pass (failed)',
    ],
    ['a run that could not start', { ok: false, error: { message: 'no executable cases' } }, 'could not run: no executable cases'],
    ['a passing run that was not stored', { ok: true, report: { outcome: 'passed', operations: [] }, stored: null }, 'could not be stored'],
  ])('publishes nothing after %s and lists the failing operations', async (_name, run, message) => {
    const { call, calls } = rest({ status: 200, body: run });
    const answer = await publishWithEvidence(call, picked({ ...REQUEST, run: { versionRef: 'project/billing-api/2.7.0', target: 'staging' } }));
    expect(calls.map((c) => c.method)).toEqual(['POST']);
    expect(answer.status).toBe(200);
    expect(answer.body.published).toBe(false);
    const result = answer.body.run as { message: string; failing: unknown[] };
    expect(result.message).toContain(message);
    expect(result.message).toContain('Nothing was published');
    if (_name === 'a failing run') {
      expect(result.failing).toEqual([{ operation: 'POST /invoices', outcome: 'failed', detail: 'currency is missing' }]);
      expect(answer.body.run).toMatchObject({ reportId: 'report-2', runId: 'run-2' });
    }
  });

  it('keeps REST’s refusal of the run or the publish, and publishes nothing after a refused run', async () => {
    const forbidden = rest({ status: 403, body: { detail: 'Permission denied: verification_evidence:create' } });
    const refusedRun = await publishWithEvidence(forbidden.call, picked({ ...REQUEST, run: { versionRef: 'project/a/1', target: 's' } }));
    expect(refusedRun).toEqual({ status: 403, body: { success: false, error: 'Permission denied: verification_evidence:create' } });
    expect(forbidden.calls).toHaveLength(1);

    const conflict = rest({ status: 409, body: { detail: { code: 'provider-contract-conflict', message: 'different contract' } } });
    expect(await publishWithEvidence(conflict.call, picked(REQUEST))).toEqual({
      status: 409,
      body: { success: false, error: 'different contract', code: 'provider-contract-conflict' },
    });

    const offline = rest(null);
    expect(await publishWithEvidence(offline.call, picked(REQUEST))).toEqual({ status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } });
  });
});

describe('checking', () => {
  it('forwards the body, URL included, and passes the answer through', async () => {
    const { call, calls } = rest({ status: 200, body: { summary: { publishable: true } } });
    const answer = await checkContract(call, picked({ ...REQUEST, body: { contentUrl: 'https://api.example.com/o.yaml' } }, 'check'));
    expect(calls).toEqual([
      {
        method: 'POST',
        path: 'pact-broker/contracts/provider/Billing%20Service/version/2.7.0%2B9f31c20/check',
        body: { contentUrl: 'https://api.example.com/o.yaml' },
      },
    ]);
    expect(answer).toEqual({ status: 200, body: { success: true, summary: { publishable: true } } });
  });

  it('keeps a 422 with its pointer, a 429 and an unreachable REST', async () => {
    const invalid = rest({ status: 422, body: { detail: { code: 'provider-contract-invalid', message: '/swagger: Swagger 2.0', pointer: '/swagger' } } });
    expect(await checkContract(invalid.call, picked(REQUEST, 'check'))).toEqual({
      status: 422,
      body: { success: false, error: '/swagger: Swagger 2.0', code: 'provider-contract-invalid', pointer: '/swagger' },
    });
    expect(refusal(429, { detail: { code: 'pact-check-rate-limited', message: 'retry later' } }).status).toBe(429);
    expect(refusal(200, {}).status).toBe(502);
    expect(refusal(400, { detail: [{ msg: 'x' }] }).body.error).toBe('The request was refused.');
    expect((await checkContract(rest(null).call, picked(REQUEST, 'check'))).status).toBe(503);
  });

  it('escapes each path segment', () => {
    expect(contractPath('a/b', '1?x', '/check')).toBe('pact-broker/contracts/provider/a%2Fb/version/1%3Fx/check');
  });
});

describe('the reports list', () => {
  it('names one project version and nothing else', () => {
    expect(reportsQuery(new URLSearchParams({ project: 'billing-api', version: '2.7.0' }))).toEqual({
      ok: true,
      path: 'provider-verifications?version_ref=project%2Fbilling-api%2F2.7.0&limit=20',
    });
    expect(reportsQuery(new URLSearchParams({ project: 'billing-api' }))).toEqual({ ok: false, error: 'project and version are required.' });
    expect(reportsQuery(new URLSearchParams({ project: 'a', version: '1', outcome: 'passed' }))).toEqual({
      ok: false,
      error: 'outcome is not a parameter of this list.',
    });
    expect(reportsQuery(new URLSearchParams({ project: 'a/b', version: '1' })).ok).toBe(false);
  });
});

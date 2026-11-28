/**
 * @jest-environment node
 */
/**
 * Environments: create, edit, delete, record a deployment, record a release — PFX-8.12 (#7309):
 * the model and the write proxies.
 *
 * * **Environment form**: REST's list read into the form (the first contact in the fields, the rest
 *   kept); a name suggested from the display name; what REST would refuse, per field; the body
 *   (display name falls back to the name; kept contacts sent back unchanged).
 * * **Proxy bodies**: an unknown field is refused with its name; types checked; a release takes no
 *   instance.
 * * **Delete**: blocked while versions run there — “Production still has 9 versions running.”
 * * **can-i-deploy first**: the gate (only a "yes" records without the tick; an unknown verdict is
 *   a "no"), the reasons, what stays supported after a release, what a deployment replaces.
 * * **The same, from anywhere**: `create-environment` (contract-required left out of Pact CLI),
 *   `record-deployment` (the override in REST only), `record-release`; edit and delete REST only.
 * * **Proxies**: the name is looked up; a "no" without the tick is a 409 with its reasons and
 *   records nothing; with the tick REST is sent `overrideCanIDeploy=true`; a "yes" never is; a
 *   delete with versions running is a 409 and deletes nothing; bad input never reaches REST; REST's
 *   refusals keep their status.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = { user: { user_id: 'u-1' }, slug: 'acme' };
const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return NextResponse.json({ ok: true }, { status: 201 });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  NEW_ENVIRONMENT_FORM,
  checkEnvironmentBody,
  checkRecordBody,
  deleteBlockSentence,
  deleteEnvironmentAction,
  deploymentBody,
  deploymentCommandAction,
  environmentBody,
  environmentCommandAction,
  environmentFormFrom,
  environmentProblems,
  hasNoProblems,
  mayRecordDeployment,
  newRecordForm,
  parseBrokerEnvironments,
  recordFormProblem,
  releaseCommandAction,
  replacedVersion,
  runningCount,
  stillSupported,
  suggestedName,
  verdictGate,
  verdictReasons,
  type EnvironmentForm,
} from '../lib/pact-environment-writes';
import { deleteEnvironment, recordDeployment, recordRelease, updateEnvironment } from '../lib/pact-environment-writes-proxy';
import type { RestCall } from '../lib/pact-provider-contract-proxy';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import type { Topology } from '../lib/pact-environments';
import { POST as createPost } from '../src/app/api/pact/environments/route';
import { DELETE as deleteOne, PUT as putOne } from '../src/app/api/pact/environments/[environment]/route';
import { POST as deployPost } from '../src/app/api/pact/environments/[environment]/deployments/route';
import { POST as releasePost } from '../src/app/api/pact/environments/[environment]/releases/route';

const UUID = 'a1b2c3d4-0001-4000-8000-000000000001';
const PRODUCTION = {
  uuid: UUID,
  name: 'production',
  displayName: 'Production',
  production: true,
  contractRequired: true,
  contacts: [
    { name: 'Platform team', details: { emailAddress: 'platform@acme.dev', slack: '#platform' } },
    { name: 'On call', details: { pager: 'ops' } },
  ],
};
const LIST = { _embedded: { environments: [PRODUCTION] } };
const YES = { summary: { deployable: true, reason: 'All required verification results are published and successful', success: 1, failed: 0, unknown: 0 }, notices: [], matrix: [] };
const NO = {
  summary: { deployable: false, reason: 'One or more verifications failed', success: 0, failed: 1, unknown: 0 },
  notices: [
    { type: 'error', text: 'Orders UI 3.3.2 in Production needs currency on POST /invoices.' },
    { type: 'warning', text: 'A warning that the error outranks.' },
  ],
  matrix: [],
};

const TOPOLOGY: Topology = {
  truncated: false,
  environments: [
    {
      uuid: UUID,
      name: 'production',
      displayName: 'Production',
      production: true,
      contractRequired: true,
      deployed: [
        { pacticipant: { name: 'Billing Service', slug: 'billing-service' }, version: '2.6.1', applicationInstance: 'eu-west', deployedAt: null },
        { pacticipant: { name: 'Billing Service', slug: 'billing-service' }, version: '2.6.0', applicationInstance: null, deployedAt: null },
      ],
      released: [
        { pacticipant: { name: 'Mobile App', slug: 'mobile-app' }, version: '1.8.7', releasedAt: '2026-10-01T00:00:00+00:00' },
        { pacticipant: { name: 'Mobile App', slug: 'mobile-app' }, version: '1.9.2', releasedAt: '2026-11-01T00:00:00+00:00' },
      ],
    },
  ],
};

/** A REST double: answers by `METHOD path` prefix (longest first) and records every call. */
function restDouble(answers: Record<string, { status: number; body: unknown } | null>) {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const call: RestCall = async (method, path, body) => {
    calls.push({ method, path, body });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => `${method} ${path}`.startsWith(candidate));
    return key ? answers[key] : { status: 404, body: { detail: { code: 'not-found', message: 'no route' } } };
  };
  return { call, calls };
}

describe('the environment form', () => {
  it('reads REST’s list: the first contact in the fields, the rest kept, a missing display name filled', () => {
    const [environment] = parseBrokerEnvironments({
      _embedded: { environments: [PRODUCTION, { name: 'no-uuid' }, { uuid: 'u-2', name: 'qa', displayName: '' }] },
    }).filter((entry) => entry.name === 'production');
    const form = environmentFormFrom(environment);
    expect(form).toMatchObject({
      name: 'production',
      displayName: 'Production',
      production: true,
      contractRequired: true,
      contactName: 'Platform team',
      contactEmail: 'platform@acme.dev',
      contactDetails: { slack: '#platform' },
      otherContacts: [{ name: 'On call', details: { pager: 'ops' } }],
    });
    const qa = parseBrokerEnvironments({ _embedded: { environments: [{ uuid: 'u-2', name: 'qa', displayName: '' }, { name: 'x' }] } });
    expect(qa).toEqual([{ uuid: 'u-2', name: 'qa', displayName: 'qa', production: false, contractRequired: false, contacts: [] }]);
    expect(environmentFormFrom(qa[0]).displayName).toBe('');
    expect(parseBrokerEnvironments(null)).toEqual([]);
  });

  it('sends every contact back on an edit, and the display name falls back to the name', () => {
    const form = { ...environmentFormFrom(parseBrokerEnvironments(LIST)[0]), contactEmail: 'ops@acme.dev' };
    expect(environmentBody(form)).toEqual({
      name: 'production',
      displayName: 'Production',
      production: true,
      contractRequired: true,
      contacts: [
        { name: 'Platform team', details: { slack: '#platform', emailAddress: 'ops@acme.dev' } },
        { name: 'On call', details: { pager: 'ops' } },
      ],
    });
    expect(environmentBody({ ...NEW_ENVIRONMENT_FORM, name: ' qa ' })).toEqual({
      name: 'qa',
      displayName: 'qa',
      production: false,
      contractRequired: false,
      contacts: [],
    });
  });

  it('suggests a name from the display name', () => {
    expect(suggestedName('  Production EU ')).toBe('production-eu');
    expect(suggestedName('QA  -  2')).toBe('qa-2');
    expect(suggestedName('')).toBe('');
  });

  it('names what REST would refuse, per field', () => {
    const base: EnvironmentForm = { ...NEW_ENVIRONMENT_FORM, name: 'staging' };
    expect(environmentProblems(base)).toEqual({});
    expect(hasNoProblems(environmentProblems(base))).toBe(true);
    expect(environmentProblems({ ...base, name: ' ' }).name).toBe('Give the environment a name.');
    expect(environmentProblems({ ...base, name: 'two words' }).name).toMatch(/one word/);
    expect(environmentProblems(base, ['staging']).name).toBe('Another environment is already called staging.');
    expect(environmentProblems({ ...base, displayName: 'x'.repeat(256) }).displayName).toMatch(/at most 255/);
    expect(environmentProblems({ ...base, contactEmail: 'ops@acme.dev' }).contactName).toMatch(/Name the contact/);
    expect(environmentProblems({ ...base, contactName: 'Ops', contactEmail: 'not an email' }).contactEmail).toMatch(/not an email/);
    expect(hasNoProblems(environmentProblems({ ...base, contactName: 'Ops', contactEmail: 'ops@acme.dev' }))).toBe(true);
  });
});

describe('the proxy bodies', () => {
  it('refuses an unknown environment field by name, and a wrong type', () => {
    expect(checkEnvironmentBody({ name: 'qa', colour: 'red' })).toEqual({
      ok: false,
      error: 'Not an environment field: colour. Send only name, displayName, production, contractRequired, contacts.',
    });
    expect(checkEnvironmentBody([]).ok).toBe(false);
    expect(checkEnvironmentBody({ name: 'two words' }).ok).toBe(false);
    expect(checkEnvironmentBody({ name: 'qa', production: 'yes' })).toEqual({ ok: false, error: 'production must be true or false.' });
    expect(checkEnvironmentBody({ name: 'qa', contacts: [{ details: {} }] })).toEqual({ ok: false, error: 'contacts[0] needs a name.' });
    expect(checkEnvironmentBody({ name: 'qa', contacts: [{ name: 'Ops', phone: '1' }] }).ok).toBe(false);
    expect(checkEnvironmentBody({ name: 'qa', contacts: [{ name: 'Ops', details: 'x' }] }).ok).toBe(false);
    expect(checkEnvironmentBody({ name: 'qa', contacts: Array.from({ length: 51 }, () => ({ name: 'x' })) }).ok).toBe(false);
    expect(checkEnvironmentBody({ name: 'qa' })).toEqual({
      ok: true,
      body: { name: 'qa', displayName: 'qa', production: false, contractRequired: false, contacts: [] },
    });
  });

  it('checks a deployment and a release; a release takes no instance', () => {
    expect(checkRecordBody({ pacticipant: 'billing-service', version: '2.7.0', recordAnyway: true }, 'deployment').ok).toBe(true);
    expect(checkRecordBody({ pacticipant: 'billing-service', version: ' ' }, 'deployment')).toEqual({
      ok: false,
      error: 'version must be non-empty text.',
    });
    expect(checkRecordBody({ pacticipant: 'b', version: '1', recordAnyway: 'yes' }, 'deployment')).toEqual({
      ok: false,
      error: 'recordAnyway must be true or false.',
    });
    expect(checkRecordBody({ pacticipant: 'b', version: '1', force: true }, 'deployment').ok).toBe(false);
    expect(checkRecordBody({ pacticipant: 'b', version: '1', applicationInstance: 'eu' }, 'release')).toEqual({
      ok: false,
      error: 'Not a release field: applicationInstance. Send only pacticipant, version. A release has no instance.',
    });
    expect(checkRecordBody('x', 'release')).toEqual({ ok: false, error: 'Send a JSON object.' });
  });
});

describe('delete, can-i-deploy first, releases', () => {
  it('blocks a delete while versions run there', () => {
    expect(runningCount(TOPOLOGY.environments[0])).toBe(4);
    expect(deleteBlockSentence('Production', 9)).toBe('Production still has 9 versions running.');
    expect(deleteBlockSentence('QA', 1)).toBe('QA still has 1 version running.');
    expect(deleteBlockSentence('QA', 0)).toBeNull();
  });

  it('records without the tick only on a yes; an unknown verdict needs it too', () => {
    expect(verdictGate(null)).toBe('waiting');
    expect(verdictGate(YES as never)).toBe('yes');
    expect(verdictGate(NO as never)).toBe('no');
    expect(verdictGate({ summary: { ...YES.summary, deployable: null } } as never)).toBe('no');
    expect(mayRecordDeployment('yes', false)).toBe(true);
    expect(mayRecordDeployment('no', false)).toBe(false);
    expect(mayRecordDeployment('no', true)).toBe(true);
    expect(mayRecordDeployment('waiting', true)).toBe(false);
  });

  it('gives the reasons for a no: errors, else warnings, else the sentence', () => {
    expect(verdictReasons(NO as never)).toEqual(['Orders UI 3.3.2 in Production needs currency on POST /invoices.']);
    expect(verdictReasons({ ...NO, notices: [NO.notices[1]] } as never)).toEqual(['A warning that the error outranks.']);
    expect(verdictReasons({ ...NO, notices: [] } as never)).toEqual(['One or more verifications failed']);
    expect(verdictReasons({ summary: { reason: '' }, notices: [] } as never)).toEqual(['can-i-deploy gave no reason.']);
  });

  it('checks the record form', () => {
    const form = { ...newRecordForm('production'), pacticipant: 'billing-service', version: '2.7.0' };
    expect(recordFormProblem(newRecordForm())).toBe('Choose the service.');
    expect(recordFormProblem({ ...form, version: '' })).toBe('Choose the version.');
    expect(recordFormProblem({ ...form, environment: '' })).toBe('Choose the environment.');
    expect(recordFormProblem({ ...form, applicationInstance: ' eu' })).toMatch(/start or end with a space/);
    expect(recordFormProblem(form)).toBeNull();
    expect(deploymentBody({ ...form, version: ' 2.7.0 ' }, false)).toEqual({ pacticipant: 'billing-service', version: '2.7.0' });
    expect(deploymentBody({ ...form, applicationInstance: 'eu-west' }, true)).toEqual({
      pacticipant: 'billing-service',
      version: '2.7.0',
      applicationInstance: 'eu-west',
      recordAnyway: true,
    });
  });

  it('lists what stays supported and what a deployment replaces', () => {
    expect(stillSupported(TOPOLOGY, 'production', 'mobile-app', '1.9.3').map((r) => r.version)).toEqual(['1.9.2', '1.8.7']);
    expect(stillSupported(TOPOLOGY, 'production', 'mobile-app', '1.9.2').map((r) => r.version)).toEqual(['1.8.7']);
    expect(stillSupported(TOPOLOGY, 'staging', 'mobile-app', '1')).toEqual([]);
    expect(stillSupported(null, 'production', 'mobile-app', '1')).toEqual([]);
    const form = { ...newRecordForm('production'), pacticipant: 'billing-service', version: '2.7.0' };
    expect(replacedVersion(TOPOLOGY, form)).toBe('2.6.0');
    expect(replacedVersion(TOPOLOGY, { ...form, applicationInstance: 'eu-west' })).toBe('2.6.1');
    expect(replacedVersion(TOPOLOGY, { ...form, applicationInstance: 'us-east' })).toBeNull();
  });
});

describe('the same, from anywhere', () => {
  it('shows create-environment with every flag; contract-required is not in Pact CLI', () => {
    const form: EnvironmentForm = {
      ...NEW_ENVIRONMENT_FORM,
      name: 'production-eu',
      displayName: 'Production EU',
      production: true,
      contractRequired: true,
      contactName: 'Platform team',
      contactEmail: 'platform@acme.dev',
    };
    const action = environmentCommandAction(form, { tenant: 'acme' });
    const [apiome, pactCli, , rest] = pactCommandSurfaces(action);
    expect(apiome.text).toContain('apiome pact create-environment');
    expect(apiome.text).toContain('--name production-eu');
    expect(apiome.text).toContain("--display-name 'Production EU'");
    expect(apiome.text).toContain('--production');
    expect(apiome.text).toContain('--contract-required');
    expect(apiome.text).toContain("--contact-name 'Platform team'");
    expect(apiome.text).toContain('--contact-email-address platform@acme.dev');
    expect(pactCli.text).toContain('pact-broker create-environment');
    expect(pactCli.text).not.toContain('--contract-required');
    expect(pactCli.notes?.join(' ')).toMatch(/--contract-required is left out/);
    expect(rest.text).toContain('POST');
    expect(rest.text).toContain('/v1/tenants/acme/pact-broker/environments');
    expect(unsupportedLines(action)).toEqual([]);
    const off = pactCommandSurfaces(environmentCommandAction({ ...form, production: false, contractRequired: false }, { tenant: '' }))[0];
    expect(off.text).not.toContain('--production');
    expect(off.text).not.toContain('--contract-required');
  });

  it('lists the contacts create-environment cannot carry', () => {
    const form = { ...NEW_ENVIRONMENT_FORM, name: 'qa', contactName: 'A', otherContacts: [{ name: 'B' }] };
    expect(unsupportedLines(environmentCommandAction(form, { tenant: '' })).join(' ')).toMatch(/The other 1 contact/);
  });

  it('shows an edit and a delete as REST, saying no command does them yet', () => {
    const edit = pactCommandSurfaces(environmentCommandAction({ ...NEW_ENVIRONMENT_FORM, name: 'qa' }, { tenant: 'acme', uuid: UUID }));
    expect(edit[0].text).toBeNull();
    expect(edit[0].unavailable).toMatch(/No apiome pact command changes an environment yet/);
    expect(edit[3].text).toContain(`PUT`);
    expect(edit[3].text).toContain(`/pact-broker/environments/${UUID}`);
    const remove = pactCommandSurfaces(deleteEnvironmentAction(UUID, 'acme'));
    expect(remove[0].unavailable).toMatch(/deletes an environment/);
    expect(remove[3].text).toContain('DELETE');
  });

  it('shows record-deployment, and the override only in REST', () => {
    const form = { ...newRecordForm('production'), pacticipant: 'billing-service', version: '2.7.0+9f31c20', applicationInstance: 'eu-west' };
    const plain = deploymentCommandAction(form, { tenant: 'acme', uuid: UUID, recordAnyway: false });
    const [apiome, pactCli, action, rest] = pactCommandSurfaces(plain);
    expect(apiome.text).toContain('apiome pact record-deployment');
    expect(apiome.text).toContain('--pacticipant billing-service');
    expect(apiome.text).toContain('--version 2.7.0+9f31c20');
    expect(apiome.text).toContain('--environment production');
    expect(apiome.text).toContain('--application-instance eu-west');
    expect(pactCli.text).toContain('pact-broker record-deployment');
    expect(action.text).toContain('application-instance: eu-west');
    expect(rest.text).toContain(`/deployed-versions/environment/${UUID}`);
    expect(rest.text).not.toContain('overrideCanIDeploy');
    expect(unsupportedLines(plain)).toEqual([]);
    const over = deploymentCommandAction(form, { tenant: 'acme', uuid: UUID, recordAnyway: true });
    expect(pactCommandSurfaces(over)[3].text).toContain('overrideCanIDeploy=true');
    expect(pactCommandSurfaces(over)[0].text).not.toContain('override');
    expect(unsupportedLines(over).join(' ')).toMatch(/Record it anyway/);
    expect(pactCommandSurfaces(deploymentCommandAction(newRecordForm(), { tenant: '', uuid: null, recordAnyway: false }))[3].text).toContain(
      '{environment}',
    );
  });

  it('shows record-release', () => {
    const form = { ...newRecordForm('production'), pacticipant: 'mobile-app', version: '1.9.3' };
    const [apiome, pactCli, , rest] = pactCommandSurfaces(releaseCommandAction(form, { tenant: 'acme', uuid: UUID }));
    expect(apiome.text).toContain('apiome pact record-release');
    expect(apiome.text).toContain('--version 1.9.3');
    expect(pactCli.text).toContain('pact-broker record-release');
    expect(rest.text).toContain(`/mobile-app/versions/1.9.3/released-versions/environment/${UUID}`);
  });
});

describe('the write handlers', () => {
  const lookup = { 'GET pact-broker/environments?name=production': { status: 200, body: LIST } };
  const deployment = { pacticipant: 'billing-service', version: '2.7.0' };
  const recordPath = `pact-broker/pacticipants/billing-service/versions/2.7.0/deployed-versions/environment/${UUID}`;

  it('refuses a no without the tick, records nothing, and gives the reasons', async () => {
    const { call, calls } = restDouble({ ...lookup, 'GET pact-broker/can-i-deploy': { status: 200, body: NO } });
    const answer = await recordDeployment(call, 'production', deployment);
    expect(answer.status).toBe(409);
    expect(answer.body).toMatchObject({
      code: 'can-i-deploy-says-no',
      reasons: ['Orders UI 3.3.2 in Production needs currency on POST /invoices.'],
    });
    expect(calls.map((c) => c.method)).toEqual(['GET', 'GET']);
    expect(calls[1].path).toBe('pact-broker/can-i-deploy?pacticipant=billing-service&version=2.7.0&toEnvironment=production');
  });

  it('records over a no with the tick and tells REST, which audits it', async () => {
    const { call, calls } = restDouble({
      ...lookup,
      'GET pact-broker/can-i-deploy': { status: 200, body: NO },
      'POST pact-broker/pacticipants': { status: 201, body: { uuid: 'd-1' } },
    });
    const answer = await recordDeployment(call, 'production', { ...deployment, applicationInstance: 'eu-west', recordAnyway: true });
    expect(answer).toEqual({ status: 201, body: { uuid: 'd-1', verdict: 'no' } });
    expect(calls[2]).toEqual({ method: 'POST', path: `${recordPath}?overrideCanIDeploy=true`, body: { applicationInstance: 'eu-west' } });
  });

  it('never sends the override on a yes, tick or not', async () => {
    const { call, calls } = restDouble({
      ...lookup,
      'GET pact-broker/can-i-deploy': { status: 200, body: YES },
      'POST pact-broker/pacticipants': { status: 200, body: { uuid: 'd-1' } },
    });
    const answer = await recordDeployment(call, 'production', { ...deployment, recordAnyway: true });
    expect(answer.body.verdict).toBe('yes');
    expect(calls[2]).toEqual({ method: 'POST', path: recordPath, body: {} });
  });

  it('treats a verdict not known yet as a no', async () => {
    const unknown = { ...YES, summary: { ...YES.summary, deployable: null, reason: 'Missing a verification result' } };
    const { call } = restDouble({ ...lookup, 'GET pact-broker/can-i-deploy': { status: 200, body: unknown } });
    const answer = await recordDeployment(call, 'production', deployment);
    expect(answer.status).toBe(409);
    expect(answer.body.reasons).toEqual(['Missing a verification result']);
  });

  it('keeps REST’s refusals: an unknown environment, version, or no REST at all', async () => {
    const none = restDouble({ 'GET pact-broker/environments?name=gone': { status: 200, body: { _embedded: { environments: [] } } } });
    expect(await recordDeployment(none.call, 'gone', deployment)).toEqual({
      status: 404,
      body: { success: false, error: 'No environment is called gone.' },
    });
    const missing = restDouble({
      ...lookup,
      'GET pact-broker/can-i-deploy': { status: 404, body: { detail: { code: 'pacticipant-version-not-found', message: 'No version 2.7.0' } } },
    });
    const refused = await recordDeployment(missing.call, 'production', deployment);
    expect(refused.status).toBe(404);
    expect(refused.body).toMatchObject({ error: 'No version 2.7.0', code: 'pacticipant-version-not-found' });
    expect(missing.calls).toHaveLength(2);
    const down = restDouble({ 'GET pact-broker/environments': null });
    expect((await recordDeployment(down.call, 'production', deployment)).status).toBe(503);
    const forbidden = restDouble({ 'GET pact-broker/environments': { status: 403, body: { detail: 'Permission denied' } } });
    expect(await recordRelease(forbidden.call, 'production', deployment)).toMatchObject({ status: 403, body: { error: 'Permission denied' } });
  });

  it('records a release to the uuid', async () => {
    const { call, calls } = restDouble({ ...lookup, 'POST pact-broker/pacticipants': { status: 201, body: { uuid: 'r-1' } } });
    expect(await recordRelease(call, 'production', { pacticipant: 'mobile-app', version: '1.9.3' })).toEqual({ status: 201, body: { uuid: 'r-1' } });
    expect(calls[1].path).toBe(`pact-broker/pacticipants/mobile-app/versions/1.9.3/released-versions/environment/${UUID}`);
  });

  it('replaces an environment by its uuid, keeping a 409 for a taken name', async () => {
    const body = { name: 'prod', displayName: 'Production', production: true, contractRequired: true, contacts: [] };
    const { call, calls } = restDouble({ ...lookup, 'PUT pact-broker/environments': { status: 200, body: { uuid: UUID, name: 'prod' } } });
    expect((await updateEnvironment(call, 'production', body)).status).toBe(200);
    expect(calls[1]).toEqual({ method: 'PUT', path: `pact-broker/environments/${UUID}`, body });
    const taken = restDouble({
      ...lookup,
      'PUT pact-broker/environments': { status: 409, body: { detail: { code: 'pact-environment-name-taken', message: 'Another environment is called prod.' } } },
    });
    expect(await updateEnvironment(taken.call, 'production', body)).toMatchObject({ status: 409, body: { error: 'Another environment is called prod.' } });
  });

  it('deletes only when nothing runs there', async () => {
    const base = `GET pact-broker/environments/${UUID}`;
    const running = restDouble({
      ...lookup,
      [`${base}/deployed-versions/currently-deployed`]: { status: 200, body: { _embedded: { deployedVersions: [{}, {}] } } },
      [`${base}/released-versions/currently-supported`]: { status: 200, body: { _embedded: { releasedVersions: [{}] } } },
    });
    const blocked = await deleteEnvironment(running.call, 'production');
    expect(blocked.status).toBe(409);
    expect(blocked.body.error).toMatch(/^Production still has 3 versions running\./);
    expect(running.calls.some((c) => c.method === 'DELETE')).toBe(false);
    const empty = restDouble({
      ...lookup,
      [`${base}/deployed-versions/currently-deployed`]: { status: 200, body: { _embedded: { deployedVersions: [] } } },
      [`${base}/released-versions/currently-supported`]: { status: 200, body: { _embedded: { releasedVersions: [] } } },
      'DELETE pact-broker/environments': { status: 204, body: {} },
    });
    expect(await deleteEnvironment(empty.call, 'production')).toEqual({ status: 200, body: { deleted: true, name: 'production' } });
    expect(empty.calls.at(-1)).toEqual({ method: 'DELETE', path: `pact-broker/environments/${UUID}`, body: undefined });
    const forbidden = restDouble({
      ...lookup,
      [`${base}/deployed-versions/currently-deployed`]: { status: 200, body: { _embedded: { deployedVersions: [] } } },
      [`${base}/released-versions/currently-supported`]: { status: 200, body: { _embedded: { releasedVersions: [] } } },
      'DELETE pact-broker/environments': { status: 403, body: { detail: 'Permission denied' } },
    });
    expect((await deleteEnvironment(forbidden.call, 'production')).status).toBe(403);
  });
});

describe('the /api/pact/environments write routes', () => {
  const ctx = (environment: string) => ({ params: Promise.resolve({ environment }) }) as never;
  const req = (path: string, init?: { method: string; body?: string }) => new NextRequest(`http://ui${path}`, init as never);
  const json = (method: string, value: unknown) => ({ method, body: JSON.stringify(value) });
  let restCalls: Array<{ url: string; method: string; body?: string }>;

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
    restCalls = [];
    global.fetch = jest.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      restCalls.push({ url, method: init?.method ?? 'GET', body: init?.body });
      const body = url.includes('can-i-deploy') ? NO : url.includes('environments?name=') ? LIST : { uuid: 'x' };
      return new Response(JSON.stringify(body), { status: init?.method === 'POST' ? 201 : 200 });
    }) as unknown as typeof fetch;
  });

  it('creates an environment as the signed-in user, refusing an unknown field without calling REST', async () => {
    await createPost(req('/api/pact/environments', json('POST', { name: 'qa', production: true })));
    expect(forwarded).toEqual([
      {
        url: 'http://rest/v1/tenants/acme/pact-broker/environments',
        method: 'POST',
        body: { name: 'qa', displayName: 'qa', production: true, contractRequired: false, contacts: [] },
      },
    ]);
    const refused = await createPost(req('/api/pact/environments', json('POST', { name: 'qa', uuid: 'x' })));
    expect(refused.status).toBe(400);
    expect((await refused.json()).error).toMatch(/Not an environment field: uuid/);
    expect(forwarded).toHaveLength(1);
  });

  it('records over a no only with the tick, in the session’s tenant', async () => {
    const refused = await deployPost(req('/api/pact/environments/production/deployments', json('POST', { pacticipant: 'b', version: '1' })), ctx('production'));
    expect(refused.status).toBe(409);
    expect(restCalls.every((c) => c.method === 'GET')).toBe(true);
    expect(restCalls.every((c) => c.url.startsWith('http://rest/v1/tenants/acme/'))).toBe(true);
    restCalls = [];
    const recorded = await deployPost(
      req('/api/pact/environments/production/deployments', json('POST', { pacticipant: 'b', version: '1', recordAnyway: true })),
      ctx('production'),
    );
    expect(recorded.status).toBe(201);
    expect(restCalls.at(-1)?.url).toBe(
      `http://rest/v1/tenants/acme/pact-broker/pacticipants/b/versions/1/deployed-versions/environment/${UUID}?overrideCanIDeploy=true`,
    );
  });

  it('refuses bad input and impossible names without calling REST', async () => {
    expect((await deployPost(req('/api/pact/environments/x/deployments', json('POST', { pacticipant: 'b' })), ctx('production'))).status).toBe(400);
    expect((await releasePost(req('/api/pact/environments/x/releases', json('POST', { pacticipant: 'b', version: '1', applicationInstance: 'eu' })), ctx('production'))).status).toBe(400);
    expect((await putOne(req('/api/pact/environments/a%20b', json('PUT', { name: 'qa' })), ctx('a%20b'))).status).toBe(404);
    expect((await deleteOne(req('/api/pact/environments/production?force=true', { method: 'DELETE' }), ctx('production'))).status).toBe(400);
    expect((await putOne(req('/api/pact/environments/production', json('PUT', { name: 'qa', id: 1 })), ctx('production'))).status).toBe(400);
    expect(restCalls).toEqual([]);
  });

  it('answers the session’s refusal before any REST call', async () => {
    tenant = { error: NextResponse.json({ success: false, error: 'Sign in' }, { status: 401 }) };
    expect((await releasePost(req('/api/pact/environments/production/releases', json('POST', { pacticipant: 'b', version: '1' })), ctx('production'))).status).toBe(401);
    expect((await deleteOne(req('/api/pact/environments/production', { method: 'DELETE' }), ctx('production'))).status).toBe(401);
    expect(restCalls).toEqual([]);
  });
});

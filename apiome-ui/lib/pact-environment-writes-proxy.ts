/**
 * What the `/api/pact/environments/[environment]/*` write proxies do — PFX-8.12 (#7309).
 *
 * The page names an environment by its name; REST's writes take its uuid. Each handler looks the
 * name up (`GET pact-broker/environments?name=`), then:
 *
 * * {@link updateEnvironment} — `PUT …/environments/{uuid}` with the checked body;
 * * {@link deleteEnvironment} — refuses (409) while any version is deployed or released there,
 *   read from REST itself (`currently-deployed`, `currently-supported`), then `DELETE`s it;
 * * {@link recordDeployment} — asks can-i-deploy for the version and the environment first. A "no"
 *   (or a verdict not known yet) is refused (409, with the reasons) unless the browser sent
 *   `recordAnyway: true`; then it is recorded with `?overrideCanIDeploy=true`, which REST writes to
 *   the audit row. A "no" is never overridden silently, whatever the browser sends.
 * * {@link recordRelease} — `POST …/released-versions/environment/{uuid}`.
 *
 * Every REST call is made as the signed-in user, so tenant scoping and the `pacts` permission stay
 * REST's; a refusal keeps its status and message.
 */

import { CONTRACT_UNAVAILABLE, refusal, type ProxyAnswer, type RestCall } from '@lib/pact-provider-contract-proxy';
import { CAN_I_DEPLOY_PROXY_PATH, canIDeployParams, parseMatrixAnswer } from '@lib/pact-matrix';
import {
  deleteBlockSentence,
  parseBrokerEnvironments,
  recordProxyPath,
  verdictGate,
  verdictReasons,
  type BrokerEnvironment,
  type DeploymentBody,
  type EnvironmentBody,
  type ReleaseBody,
} from '@lib/pact-environment-writes';

/** The unreachable answer. */
function unavailable(): ProxyAnswer {
  return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
}

/** A refusal the proxy makes itself. */
function refuse(status: number, error: string, extra: Record<string, unknown> = {}): ProxyAnswer {
  return { status, body: { success: false, error, ...extra } };
}

/**
 * Find an environment by its name.
 *
 * @param call - The REST call.
 * @param name - The environment's name (already checked).
 * @returns The environment, or the answer to send back (404 for no such environment).
 */
export async function findEnvironment(call: RestCall, name: string): Promise<BrokerEnvironment | ProxyAnswer> {
  const answer = await call('GET', `pact-broker/environments?name=${encodeURIComponent(name)}`);
  if (!answer) return unavailable();
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  const found = parseBrokerEnvironments(answer.body).find((environment) => environment.name === name);
  return found ?? refuse(404, `No environment is called ${name}.`);
}

/** Whether a lookup found the environment. */
function isEnvironment(value: BrokerEnvironment | ProxyAnswer): value is BrokerEnvironment {
  return 'uuid' in value;
}

/**
 * Pass a REST write's answer through: its body on success, its refusal otherwise.
 *
 * @param answer - REST's answer, or `null` when unreachable.
 * @param extra - Fields added to a successful body.
 * @returns The answer.
 */
function passThrough(answer: { status: number; body: unknown } | null, extra: Record<string, unknown> = {}): ProxyAnswer {
  if (!answer) return unavailable();
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  const body = answer.body && typeof answer.body === 'object' && !Array.isArray(answer.body) ? (answer.body as Record<string, unknown>) : {};
  return { status: answer.status === 204 ? 200 : answer.status, body: { ...body, ...extra } };
}

/**
 * Replace an environment's fields.
 *
 * @param call - The REST call.
 * @param name - The environment's current name.
 * @param body - The checked body (it may rename the environment).
 * @returns REST's environment, or its refusal (409 for a name taken).
 */
export async function updateEnvironment(call: RestCall, name: string, body: EnvironmentBody): Promise<ProxyAnswer> {
  const found = await findEnvironment(call, name);
  if (!isEnvironment(found)) return found;
  return passThrough(await call('PUT', `pact-broker/environments/${encodeURIComponent(found.uuid)}`, body));
}

/** How many entries a currently-deployed / currently-supported answer embeds. */
function embeddedCount(body: unknown, key: string): number {
  const embedded = (body as { _embedded?: Record<string, unknown> } | null)?._embedded;
  const list = embedded?.[key];
  return Array.isArray(list) ? list.length : 0;
}

/**
 * Delete an environment — only when nothing is deployed or released there.
 *
 * @param call - The REST call.
 * @param name - The environment's name.
 * @returns `{ deleted: true }`, a 409 naming how many versions run there, or REST's refusal.
 */
export async function deleteEnvironment(call: RestCall, name: string): Promise<ProxyAnswer> {
  const found = await findEnvironment(call, name);
  if (!isEnvironment(found)) return found;
  const base = `pact-broker/environments/${encodeURIComponent(found.uuid)}`;
  const [deployed, released] = await Promise.all([
    call('GET', `${base}/deployed-versions/currently-deployed`),
    call('GET', `${base}/released-versions/currently-supported`),
  ]);
  if (!deployed || !released) return unavailable();
  if (deployed.status >= 400) return refusal(deployed.status, deployed.body);
  if (released.status >= 400) return refusal(released.status, released.body);
  const running = embeddedCount(deployed.body, 'deployedVersions') + embeddedCount(released.body, 'releasedVersions');
  const blocked = deleteBlockSentence(found.displayName, running);
  if (blocked) return refuse(409, `${blocked} Record their undeployment or end their support first.`, { running });
  const answer = await call('DELETE', base);
  if (!answer) return unavailable();
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  return { status: 200, body: { deleted: true, name: found.name } };
}

/**
 * Record a deployment, asking can-i-deploy first.
 *
 * @param call - The REST call.
 * @param name - The environment's name.
 * @param body - The checked body.
 * @returns REST's deployment with `verdict` (`yes`, or `no` when recorded anyway), a 409 with the
 *   reasons for a "no" without `recordAnyway`, or a refusal.
 */
export async function recordDeployment(call: RestCall, name: string, body: DeploymentBody): Promise<ProxyAnswer> {
  const found = await findEnvironment(call, name);
  if (!isEnvironment(found)) return found;
  const params = canIDeployParams({
    pacticipant: body.pacticipant,
    version: body.version,
    kind: 'environment',
    destination: found.name,
    ignore: [],
  });
  const asked = await call('GET', `${CAN_I_DEPLOY_PROXY_PATH}?${params.toString()}`);
  if (!asked) return unavailable();
  if (asked.status >= 400) return refusal(asked.status, asked.body);
  const verdict = parseMatrixAnswer(asked.body);
  const gate = verdictGate(verdict);
  if (gate !== 'yes' && body.recordAnyway !== true) {
    return refuse(409, 'can-i-deploy says no. Tick Record it anyway to record a deployment that already happened.', {
      code: 'can-i-deploy-says-no',
      reasons: verdictReasons(verdict),
    });
  }
  const override = gate !== 'yes';
  const path = `${recordProxyPath('deployed', body.pacticipant, body.version, found.uuid)}${override ? '?overrideCanIDeploy=true' : ''}`;
  const recorded = await call('POST', path, body.applicationInstance ? { applicationInstance: body.applicationInstance } : {});
  return passThrough(recorded, { verdict: override ? 'no' : 'yes' });
}

/**
 * Record a release.
 *
 * @param call - The REST call.
 * @param name - The environment's name.
 * @param body - The checked body.
 * @returns REST's release, or its refusal.
 */
export async function recordRelease(call: RestCall, name: string, body: ReleaseBody): Promise<ProxyAnswer> {
  const found = await findEnvironment(call, name);
  if (!isEnvironment(found)) return found;
  return passThrough(await call('POST', recordProxyPath('released', body.pacticipant, body.version, found.uuid), {}));
}

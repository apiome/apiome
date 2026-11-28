/**
 * Ending a deployment or a release from the **Environments** page — PFX-8.13 (#7310):
 * **Record an undeployment** (`apiome pact record-undeployment`) and **End support**
 * (`apiome pact record-support-ended`).
 *
 * Pure: the bodies the browser sends, the checks the `/api/pact/environments/[environment]/*`
 * proxies run on them (an unknown field is refused by name), which current deployment an
 * undeployment ends — the rule `pact-broker record-undeployment` follows — and each dialog's
 * {@link PactAction} for **The same, from anywhere**.
 *
 * REST (`/v1/tenants/{t}/pact-broker`):
 * * `GET environments/{uuid}/deployed-versions/currently-deployed?pacticipant=` then
 *   `PATCH deployed-versions/{uuid}` `{"currentlyDeployed": false}`;
 * * `GET environments/{uuid}/released-versions/currently-supported?pacticipant=&version=` then
 *   `PATCH released-versions/{uuid}` `{"currentlySupported": false}`.
 *
 * Both need `pacts:edit`. Authority: `docs/mockups/contracts/environments.html` (`#env-menu`,
 * `#release-dialog`).
 */

import { tenantPath, type PactAction } from '@lib/pact-commands';
import { MAX_TEXT_LENGTH, type CheckedBody } from '@lib/pact-pacticipant-settings';

/** Ending a deployment or a release (REST's `pacts:edit`). */
export const END_PERMISSION = 'pacts:edit';

/** The body the browser sends to record an undeployment. */
export interface UndeploymentBody {
  pacticipant: string;
  /** The instance; left out for the environment's unnamed one. */
  applicationInstance?: string;
}

/** The body the browser sends to end support for a release. */
export interface SupportEndedBody {
  pacticipant: string;
  version: string;
}

/** A JSON object, or `null`. */
function objectOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Why one text field is refused, or `null`. */
function textProblem(body: Record<string, unknown>, key: string, required: boolean): string | null {
  const value = body[key];
  if (value === undefined && !required) return null;
  if (typeof value !== 'string' || !value.trim()) return `${key} must be non-empty text.`;
  if (value.length > MAX_TEXT_LENGTH) return `${key} is longer than ${MAX_TEXT_LENGTH} characters.`;
  return null;
}

/** Refuse any field outside `fields`, by name. */
function unknownFields(body: Record<string, unknown>, fields: readonly string[], what: string): string | null {
  const unknown = Object.keys(body).filter((key) => !fields.includes(key));
  return unknown.length ? `Not ${what} field: ${unknown.join(', ')}. Send only ${fields.join(', ')}.` : null;
}

/**
 * Check an undeployment body before a proxy forwards it.
 *
 * @param raw - The parsed body.
 * @returns The body, or why it is refused.
 */
export function checkUndeploymentBody(raw: unknown): CheckedBody<UndeploymentBody> {
  const body = objectOf(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const problem =
    unknownFields(body, ['pacticipant', 'applicationInstance'], 'an undeployment') ??
    textProblem(body, 'pacticipant', true) ??
    textProblem(body, 'applicationInstance', false);
  return problem ? { ok: false, error: problem } : { ok: true, body: body as unknown as UndeploymentBody };
}

/**
 * Check a support-ended body before a proxy forwards it.
 *
 * @param raw - The parsed body.
 * @returns The body, or why it is refused.
 */
export function checkSupportEndedBody(raw: unknown): CheckedBody<SupportEndedBody> {
  const body = objectOf(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const problem =
    unknownFields(body, ['pacticipant', 'version'], 'a support-ended') ??
    textProblem(body, 'pacticipant', true) ??
    textProblem(body, 'version', true);
  return problem ? { ok: false, error: problem } : { ok: true, body: body as unknown as SupportEndedBody };
}

/** One current deployment as REST's currently-deployed list embeds it. */
export interface CurrentlyDeployed {
  uuid: string;
  applicationInstance: string | null;
  version: string;
}

/**
 * Read `_embedded.deployedVersions` of a currently-deployed answer.
 *
 * @param body - REST's answer.
 * @returns The deployments (entries without a uuid are left out — REST always sends one).
 */
export function parseCurrentlyDeployed(body: unknown): CurrentlyDeployed[] {
  const list = objectOf(objectOf(body)?._embedded)?.deployedVersions;
  if (!Array.isArray(list)) return [];
  return list.flatMap((item) => {
    const entry = objectOf(item);
    if (!entry || typeof entry.uuid !== 'string') return [];
    const version = objectOf(objectOf(entry._embedded)?.version)?.number;
    return [
      {
        uuid: entry.uuid,
        applicationInstance: typeof entry.applicationInstance === 'string' && entry.applicationInstance ? entry.applicationInstance : null,
        version: typeof version === 'string' ? version : '',
      },
    ];
  });
}

/**
 * Read the uuids of `_embedded.releasedVersions` of a currently-supported answer.
 *
 * @param body - REST's answer.
 * @returns The releases' uuids.
 */
export function parseCurrentlySupported(body: unknown): string[] {
  const list = objectOf(objectOf(body)?._embedded)?.releasedVersions;
  if (!Array.isArray(list)) return [];
  return list.flatMap((item) => {
    const uuid = objectOf(item)?.uuid;
    return typeof uuid === 'string' ? [uuid] : [];
  });
}

/** Which deployments an undeployment ends, or why none. */
export type UndeploymentTargets = { ok: true; targets: CurrentlyDeployed[] } | { ok: false; error: string };

/**
 * The deployments **Record an undeployment** ends — `pact-broker record-undeployment`'s rule: with an
 * instance, only that instance's deployment; without one, only the unnamed instance's. Nothing is
 * ended on a guess; when nothing matches the sentence says what is deployed.
 *
 * @param entries - The pacticipant's current deployments to the environment.
 * @param context - The service's name, the environment's name, and the instance (`null`: unnamed).
 * @returns The deployments to end, or the refusal.
 */
export function undeploymentTargets(
  entries: readonly CurrentlyDeployed[],
  context: { pacticipant: string; environment: string; applicationInstance: string | null },
): UndeploymentTargets {
  const { pacticipant, environment, applicationInstance } = context;
  const matches = entries.filter((entry) => entry.applicationInstance === applicationInstance);
  if (matches.length) return { ok: true, targets: matches };
  if (!entries.length) {
    return { ok: false, error: `${pacticipant} is not currently deployed to ${environment} environment. Cannot record undeployment.` };
  }
  const named = [...new Set(entries.map((entry) => entry.applicationInstance).filter((x): x is string => Boolean(x)))].sort();
  if (applicationInstance === null) {
    return {
      ok: false,
      error: `Please specify one of the following application instances to record the undeployment from: ${named.join(', ')}`,
    };
  }
  const others = named.length ? named.join(', ') : 'the unnamed instance';
  return {
    ok: false,
    error: `${pacticipant} is not currently deployed to application instance '${applicationInstance}' in ${environment} environment. It is deployed to: ${others}. Cannot record undeployment.`,
  };
}

/** What the Record an undeployment dialog holds. */
export interface UndeploymentForm {
  pacticipant: string;
  environment: string;
  /** `''` is the environment's unnamed instance. */
  applicationInstance: string;
}

/**
 * **The same, from anywhere** for Record an undeployment.
 *
 * @param form - The form.
 * @param tenant - The workspace's handle (`''` writes `{tenant}`).
 * @returns `record-undeployment` and the REST `PATCH` it ends with.
 */
export function undeploymentCommandAction(form: UndeploymentForm, tenant = ''): PactAction {
  return {
    verb: 'record-undeployment',
    options: [
      { flag: '--pacticipant', value: form.pacticipant.trim() || '<service>' },
      { flag: '--environment', value: form.environment.trim() || '<environment>' },
      { flag: '--application-instance', value: form.applicationInstance },
    ],
    rest: {
      method: 'PATCH',
      path: tenantPath(tenant, '/pact-broker/deployed-versions/{deployment}'),
      body: { currentlyDeployed: false },
    },
  };
}

/** What the End support dialog holds. */
export interface SupportEndedForm {
  pacticipant: string;
  version: string;
  environment: string;
}

/**
 * **The same, from anywhere** for End support.
 *
 * @param form - The form.
 * @param tenant - The workspace's handle (`''` writes `{tenant}`).
 * @returns `record-support-ended` and the REST `PATCH`.
 */
export function supportEndedCommandAction(form: SupportEndedForm, tenant = ''): PactAction {
  return {
    verb: 'record-support-ended',
    options: [
      { flag: '--pacticipant', value: form.pacticipant.trim() || '<service>' },
      { flag: '--version', value: form.version.trim() || '<version>' },
      { flag: '--environment', value: form.environment.trim() || '<environment>' },
    ],
    rest: {
      method: 'PATCH',
      path: tenantPath(tenant, '/pact-broker/released-versions/{release}'),
      body: { currentlySupported: false },
    },
  };
}

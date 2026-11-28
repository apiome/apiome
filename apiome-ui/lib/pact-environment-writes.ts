/**
 * The writes of the **Environments** page — PFX-8.12 (#7309): **New environment** / **Edit
 * environment**, **Delete environment**, **Record a deployment** and **Record a release**.
 *
 * Pure: the forms the dialogs hold, what each field would be refused for, the bodies the browser
 * sends, the checks the `/api/pact/environments/*` proxies run on them (an unknown field is refused
 * by name, never dropped), and each dialog's {@link PactAction} for **The same, from anywhere**.
 *
 * REST (`/v1/tenants/{t}/pact-broker`):
 * * `POST environments` — `create-environment`; `PUT environments/{uuid}` replaces every field;
 *   `DELETE environments/{uuid}` deletes it with its deployments and releases (the page and the proxy
 *   refuse while versions run there).
 * * `POST pacticipants/{p}/versions/{v}/deployed-versions/environment/{uuid}` — `record-deployment`,
 *   with `?overrideCanIDeploy=true` when it is recorded over a "no" (written to the audit row).
 * * `POST pacticipants/{p}/versions/{v}/released-versions/environment/{uuid}` — `record-release`.
 *
 * Authority: `docs/mockups/contracts/environments.html`.
 */

import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from '@lib/pact-commands';
import { isEnvironmentName, type CurrentRelease, type Topology, type TopologyEnvironment } from '@lib/pact-environments';
import type { MatrixAnswer } from '@lib/pact-matrix';
import { MAX_TEXT_LENGTH, plural, type CheckedBody } from '@lib/pact-pacticipant-settings';

// --- permissions --------------------------------------------------------------------------------

/** Creating an environment, recording a deployment or a release (REST's `pacts:create`). */
export const RECORD_PERMISSION = 'pacts:create';
/** Editing an environment (`pacts:edit`). */
export const EDIT_ENVIRONMENT_PERMISSION = 'pacts:edit';
/** Deleting an environment (`pacts:delete`). */
export const DELETE_ENVIRONMENT_PERMISSION = 'pacts:delete';

// --- environments -------------------------------------------------------------------------------

/** One contact of an environment, as REST stores it. */
export interface EnvironmentContact {
  name: string;
  details?: Record<string, unknown>;
}

/** An environment as `GET …/pact-broker/environments` lists it (the fields this page reads). */
export interface BrokerEnvironment {
  uuid: string;
  name: string;
  displayName: string;
  production: boolean;
  contractRequired: boolean;
  contacts: EnvironmentContact[];
}

/** What the New / Edit environment dialog holds. */
export interface EnvironmentForm {
  name: string;
  displayName: string;
  production: boolean;
  contractRequired: boolean;
  /** The first contact's name. */
  contactName: string;
  /** The first contact's `details.emailAddress`. */
  contactEmail: string;
  /** The first contact's other details, kept as they are (the dialog does not show them). */
  contactDetails: Record<string, unknown>;
  /** Every contact after the first, kept as they are (a `PUT` replaces every field). */
  otherContacts: EnvironmentContact[];
}

/** A field the dialog can put a problem under. */
export type EnvironmentField = 'name' | 'displayName' | 'contactName' | 'contactEmail';

/** What the dialog would be refused for, per field. */
export type EnvironmentProblems = Partial<Record<EnvironmentField, string>>;

/** The body of a create or a replace — what REST's `_ENVIRONMENT_BODY` takes. */
export interface EnvironmentBody {
  name: string;
  displayName: string;
  production: boolean;
  contractRequired: boolean;
  contacts: EnvironmentContact[];
}

/** REST's cap on contacts. */
export const MAX_CONTACTS = 50;

/** The dialog's empty form. */
export const NEW_ENVIRONMENT_FORM: EnvironmentForm = {
  name: '',
  displayName: '',
  production: false,
  contractRequired: false,
  contactName: '',
  contactEmail: '',
  contactDetails: {},
  otherContacts: [],
};

/** A plain object, or `null`. */
function objectOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/**
 * Read the environment list REST answers (`_embedded.environments`); entries without a uuid and a
 * name are left out, as no action can name them.
 *
 * @param body - `GET /api/pact/environments`'s body.
 * @returns The environments, by name.
 */
export function parseBrokerEnvironments(body: unknown): BrokerEnvironment[] {
  const embedded = objectOf(objectOf(body)?._embedded);
  const raw = Array.isArray(embedded?.environments) ? (embedded.environments as unknown[]) : [];
  const environments: BrokerEnvironment[] = [];
  for (const entry of raw) {
    const doc = objectOf(entry);
    if (!doc || typeof doc.uuid !== 'string' || typeof doc.name !== 'string') continue;
    const contacts = Array.isArray(doc.contacts)
      ? (doc.contacts as unknown[]).flatMap((contact) => {
          const value = objectOf(contact);
          if (!value || typeof value.name !== 'string') return [];
          const details = objectOf(value.details);
          return [details ? { name: value.name, details } : { name: value.name }];
        })
      : [];
    environments.push({
      uuid: doc.uuid,
      name: doc.name,
      displayName: typeof doc.displayName === 'string' && doc.displayName ? doc.displayName : doc.name,
      production: doc.production === true,
      contractRequired: doc.contractRequired === true,
      contacts,
    });
  }
  return environments.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * The Edit dialog's form for an environment: its first contact in the fields, the rest kept.
 *
 * @param environment - The environment.
 * @returns The form.
 */
export function environmentFormFrom(environment: BrokerEnvironment): EnvironmentForm {
  const [first, ...others] = environment.contacts;
  const { emailAddress, ...rest } = (first?.details ?? {}) as Record<string, unknown>;
  return {
    name: environment.name,
    displayName: environment.displayName === environment.name ? '' : environment.displayName,
    production: environment.production,
    contractRequired: environment.contractRequired,
    contactName: first?.name ?? '',
    contactEmail: typeof emailAddress === 'string' ? emailAddress : '',
    contactDetails: typeof emailAddress === 'string' || emailAddress === undefined ? rest : { ...rest, emailAddress },
    otherContacts: others,
  };
}

/**
 * A name tooling can use, suggested from a display name: lower case, words joined by `-`, nothing
 * an environment name cannot hold.
 *
 * @param displayName - E.g. `Production EU`.
 * @returns E.g. `production-eu`.
 */
export function suggestedName(displayName: string): string {
  return displayName
    .trim()
    .toLowerCase()
    .replace(/[\s\u0000-\u001f\u007f]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, MAX_TEXT_LENGTH);
}

/** An email address, loosely: something@somewhere, no spaces. */
const EMAIL = /^[^\s@]+@[^\s@]+$/;

/**
 * What REST (or the page) would refuse in the form, per field.
 *
 * @param form - The form.
 * @param taken - Names other environments already have (a create or a rename to one is a 409).
 * @returns The problems; empty when the form can be sent.
 */
export function environmentProblems(form: EnvironmentForm, taken: readonly string[] = []): EnvironmentProblems {
  const problems: EnvironmentProblems = {};
  const name = form.name.trim();
  if (!name) problems.name = 'Give the environment a name.';
  else if (!isEnvironmentName(name)) problems.name = 'A name is one word: no spaces or control characters.';
  else if (name.length > MAX_TEXT_LENGTH) problems.name = `A name is at most ${MAX_TEXT_LENGTH} characters.`;
  else if (taken.includes(name)) problems.name = `Another environment is already called ${name}.`;
  if (form.displayName.trim().length > MAX_TEXT_LENGTH)
    problems.displayName = `A display name is at most ${MAX_TEXT_LENGTH} characters.`;
  const contact = form.contactName.trim();
  const email = form.contactEmail.trim();
  if (contact.length > MAX_TEXT_LENGTH) problems.contactName = `A contact is at most ${MAX_TEXT_LENGTH} characters.`;
  else if (!contact && email) problems.contactName = 'Name the contact the email address belongs to.';
  if (email && !EMAIL.test(email)) problems.contactEmail = 'This is not an email address.';
  else if (email.length > MAX_TEXT_LENGTH) problems.contactEmail = `An email address is at most ${MAX_TEXT_LENGTH} characters.`;
  return problems;
}

/**
 * Whether there is nothing to refuse.
 *
 * @param problems - From {@link environmentProblems}.
 * @returns True when the form can be sent.
 */
export function hasNoProblems(problems: Partial<Record<string, string>>): boolean {
  return Object.values(problems).every((value) => !value);
}

/**
 * The body a form sends. The display name falls back to the name (REST's default); the first
 * contact is the fields, then the contacts the form keeps.
 *
 * @param form - The form (already checked).
 * @returns The body.
 */
export function environmentBody(form: EnvironmentForm): EnvironmentBody {
  const name = form.name.trim();
  const contactName = form.contactName.trim();
  const email = form.contactEmail.trim();
  const details = { ...form.contactDetails, ...(email ? { emailAddress: email } : {}) };
  const first: EnvironmentContact[] = contactName
    ? [Object.keys(details).length ? { name: contactName, details } : { name: contactName }]
    : [];
  return {
    name,
    displayName: form.displayName.trim() || name,
    production: form.production,
    contractRequired: form.contractRequired,
    contacts: [...first, ...form.otherContacts],
  };
}

/** The fields an environment body may carry. */
const ENVIRONMENT_FIELDS = ['name', 'displayName', 'production', 'contractRequired', 'contacts'] as const;

/**
 * Check a browser's environment body before a proxy forwards it: the fields REST takes, each of its
 * type. Anything else is refused with its name.
 *
 * @param raw - The parsed body.
 * @returns The body, or why it is refused.
 */
export function checkEnvironmentBody(raw: unknown): CheckedBody<EnvironmentBody> {
  const body = objectOf(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const unknown = Object.keys(body).filter((key) => !(ENVIRONMENT_FIELDS as readonly string[]).includes(key));
  if (unknown.length)
    return { ok: false, error: `Not an environment field: ${unknown.join(', ')}. Send only ${ENVIRONMENT_FIELDS.join(', ')}.` };
  if (typeof body.name !== 'string' || !isEnvironmentName(body.name))
    return { ok: false, error: 'name must be one word: no spaces or control characters, at most 255 characters.' };
  if (body.displayName !== undefined && (typeof body.displayName !== 'string' || body.displayName.length > MAX_TEXT_LENGTH))
    return { ok: false, error: `displayName must be text of at most ${MAX_TEXT_LENGTH} characters.` };
  for (const flag of ['production', 'contractRequired'] as const) {
    if (body[flag] !== undefined && typeof body[flag] !== 'boolean') return { ok: false, error: `${flag} must be true or false.` };
  }
  const contacts = body.contacts ?? [];
  if (!Array.isArray(contacts) || contacts.length > MAX_CONTACTS)
    return { ok: false, error: `contacts must be a list of at most ${MAX_CONTACTS}.` };
  for (const [index, contact] of contacts.entries()) {
    const value = objectOf(contact);
    const extra = value ? Object.keys(value).filter((key) => key !== 'name' && key !== 'details') : [];
    if (!value || typeof value.name !== 'string' || !value.name.trim())
      return { ok: false, error: `contacts[${index}] needs a name.` };
    if (extra.length) return { ok: false, error: `contacts[${index}] has ${extra.join(', ')}: a contact is a name and details.` };
    if (value.details !== undefined && !objectOf(value.details))
      return { ok: false, error: `contacts[${index}].details must be an object.` };
  }
  return {
    ok: true,
    body: {
      name: body.name,
      displayName: (body.displayName as string | undefined) || body.name,
      production: body.production === true,
      contractRequired: body.contractRequired === true,
      contacts: contacts as EnvironmentContact[],
    },
  };
}

/** Why Pact CLI leaves out `--contract-required`. */
export const CONTRACT_REQUIRED_NOT_IN_PACT_CLI = 'contract-required is an Apiome setting; set it in Apiome after creating the environment.';
/** Why the other contacts are not in the command. */
export const OTHER_CONTACTS_NOT_IN_CLI = 'create-environment takes one contact; the REST request carries every contact.';
/** Why an edit has no command. */
export const EDIT_NOT_IN_CLI =
  'No apiome pact command changes an environment yet; the REST request replaces every field, as pact-broker update-environment does.';
/** Why a delete has no command. */
export const DELETE_NOT_IN_CLI = 'No apiome pact command deletes an environment yet; the REST request does.';

/**
 * **The same, from anywhere** for the New / Edit environment dialog.
 *
 * @param form - The form.
 * @param context - `tenant` (empty for `{tenant}`); `uuid` of the environment being edited, if any.
 * @returns `create-environment` with its flags for a new one; the REST `PUT` alone for an edit.
 */
export function environmentCommandAction(form: EnvironmentForm, context: { tenant: string; uuid?: string | null }): PactAction {
  const body = environmentBody(form);
  if (context.uuid) {
    return {
      verb: null,
      noCommandReason: EDIT_NOT_IN_CLI,
      rest: { method: 'PUT', path: tenantPath(context.tenant, `/pact-broker/environments/${encodeURIComponent(context.uuid)}`), body },
    };
  }
  const options: PactOption[] = [
    { flag: '--name', value: body.name || '<name>' },
    { flag: '--display-name', value: form.displayName.trim() },
    { flag: '--production', value: form.production },
    { flag: '--contract-required', value: form.contractRequired, notInPactCli: CONTRACT_REQUIRED_NOT_IN_PACT_CLI },
    { flag: '--contact-name', value: form.contactName.trim() },
    { flag: '--contact-email-address', value: form.contactEmail.trim() },
  ];
  const unsupported: PactUnsupported[] = form.otherContacts.length
    ? [{ what: `The other ${plural(form.otherContacts.length, 'contact')}`, reason: OTHER_CONTACTS_NOT_IN_CLI, inRest: true }]
    : [];
  return {
    verb: 'create-environment',
    options,
    rest: { method: 'POST', path: tenantPath(context.tenant, '/pact-broker/environments'), body },
    unsupported,
  };
}

/**
 * **The same, from anywhere** for the Delete environment dialog.
 *
 * @param uuid - The environment's uuid.
 * @param tenant - The workspace handle, or empty for `{tenant}`.
 * @returns The REST `DELETE` (no command does it yet).
 */
export function deleteEnvironmentAction(uuid: string, tenant = ''): PactAction {
  return {
    verb: null,
    noCommandReason: DELETE_NOT_IN_CLI,
    rest: { method: 'DELETE', path: tenantPath(tenant, `/pact-broker/environments/${encodeURIComponent(uuid)}`) },
  };
}

/**
 * How many versions run in an environment now: its current deployments and supported releases.
 *
 * @param environment - The environment, from the topology.
 * @returns The count.
 */
export function runningCount(environment: Pick<TopologyEnvironment, 'deployed' | 'released'>): number {
  return environment.deployed.length + environment.released.length;
}

/**
 * Why an environment cannot be deleted, or `null` when nothing runs there.
 *
 * @param displayName - The environment's display name.
 * @param running - How many versions run there ({@link runningCount}).
 * @returns E.g. `Production still has 9 versions running.`
 */
export function deleteBlockSentence(displayName: string, running: number): string | null {
  return running > 0 ? `${displayName} still has ${plural(running, 'version')} running.` : null;
}

// --- deployments and releases -------------------------------------------------------------------

/** What the Record a deployment / Record a release dialogs hold. */
export interface RecordForm {
  /** The pacticipant's handle. */
  pacticipant: string;
  version: string;
  /** The environment's name. */
  environment: string;
  /** Deployments only: the instance, exactly as typed (empty for the unnamed one). */
  applicationInstance: string;
}

/** The empty record form, or one starting in an environment. */
export function newRecordForm(environment = ''): RecordForm {
  return { pacticipant: '', version: '', environment, applicationInstance: '' };
}

/**
 * Why the form cannot be asked or recorded yet, or `null`.
 *
 * @param form - The form.
 * @returns The sentence.
 */
export function recordFormProblem(form: RecordForm): string | null {
  if (!form.pacticipant.trim()) return 'Choose the service.';
  if (!form.version.trim()) return 'Choose the version.';
  if (!form.environment.trim()) return 'Choose the environment.';
  if (form.version.trim().length > MAX_TEXT_LENGTH) return `A version is at most ${MAX_TEXT_LENGTH} characters.`;
  const instance = form.applicationInstance;
  if (instance && (instance !== instance.trim() || /[\u0000-\u001f\u007f]/.test(instance)))
    return 'The instance cannot start or end with a space or hold a control character.';
  if (instance.length > MAX_TEXT_LENGTH) return `An instance is at most ${MAX_TEXT_LENGTH} characters.`;
  return null;
}

/** The body the browser sends to record a deployment. */
export interface DeploymentBody {
  pacticipant: string;
  version: string;
  applicationInstance?: string;
  /** The person ticked **Record it anyway** over a "no" from can-i-deploy. */
  recordAnyway?: boolean;
}

/** The body the browser sends to record a release. */
export interface ReleaseBody {
  pacticipant: string;
  version: string;
}

/**
 * The deployment body a form sends.
 *
 * @param form - The form (already checked).
 * @param recordAnyway - Whether **Record it anyway** is ticked.
 * @returns The body.
 */
export function deploymentBody(form: RecordForm, recordAnyway: boolean): DeploymentBody {
  return {
    pacticipant: form.pacticipant.trim(),
    version: form.version.trim(),
    ...(form.applicationInstance ? { applicationInstance: form.applicationInstance } : {}),
    ...(recordAnyway ? { recordAnyway: true } : {}),
  };
}

/** Check one text field of a record body. */
function textProblem(body: Record<string, unknown>, key: string, required: boolean): string | null {
  const value = body[key];
  if (value === undefined && !required) return null;
  if (typeof value !== 'string' || !value.trim()) return `${key} must be non-empty text.`;
  if (value.length > MAX_TEXT_LENGTH) return `${key} is longer than ${MAX_TEXT_LENGTH} characters.`;
  return null;
}

/**
 * Check a record body before a proxy forwards it. Anything else is refused with its name.
 *
 * @param raw - The parsed body.
 * @param kind - `deployment` (takes `applicationInstance` and `recordAnyway`) or `release`.
 * @returns The body, or why it is refused.
 */
export function checkRecordBody(raw: unknown, kind: 'deployment'): CheckedBody<DeploymentBody>;
export function checkRecordBody(raw: unknown, kind: 'release'): CheckedBody<ReleaseBody>;
export function checkRecordBody(raw: unknown, kind: 'deployment' | 'release'): CheckedBody<DeploymentBody | ReleaseBody> {
  const body = objectOf(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const fields = kind === 'deployment' ? ['pacticipant', 'version', 'applicationInstance', 'recordAnyway'] : ['pacticipant', 'version'];
  const unknown = Object.keys(body).filter((key) => !fields.includes(key));
  if (unknown.length) {
    const hint = kind === 'release' && unknown.includes('applicationInstance') ? ' A release has no instance.' : '';
    return { ok: false, error: `Not a ${kind} field: ${unknown.join(', ')}. Send only ${fields.join(', ')}.${hint}` };
  }
  const problem =
    textProblem(body, 'pacticipant', true) ??
    textProblem(body, 'version', true) ??
    (kind === 'deployment' ? textProblem(body, 'applicationInstance', false) : null);
  if (problem) return { ok: false, error: problem };
  if (body.recordAnyway !== undefined && typeof body.recordAnyway !== 'boolean')
    return { ok: false, error: 'recordAnyway must be true or false.' };
  return { ok: true, body: body as unknown as DeploymentBody | ReleaseBody };
}

/**
 * The REST path that records a deployment or a release.
 *
 * @param kind - `deployed` or `released`.
 * @param pacticipant - The pacticipant's handle.
 * @param version - The version number.
 * @param uuid - The environment's uuid.
 * @returns The path below `/v1/tenants/{t}/`.
 */
export function recordProxyPath(kind: 'deployed' | 'released', pacticipant: string, version: string, uuid: string): string {
  return `pact-broker/pacticipants/${encodeURIComponent(pacticipant)}/versions/${encodeURIComponent(version)}/${kind}-versions/environment/${encodeURIComponent(uuid)}`;
}

/** Why the override tick is not in the command. */
export const OVERRIDE_NOT_IN_CLI =
  'record-deployment does not ask can-i-deploy: in a pipeline run apiome pact can-i-deploy first. REST carries overrideCanIDeploy=true for the audit trail.';

/**
 * **The same, from anywhere** for Record a deployment.
 *
 * @param form - The form.
 * @param context - `tenant`, the environment's `uuid` (or `null` for `{environment}`), whether it is
 *   recorded over a "no".
 * @returns `record-deployment` and the REST `POST`.
 */
export function deploymentCommandAction(
  form: RecordForm,
  context: { tenant: string; uuid: string | null; recordAnyway: boolean },
): PactAction {
  const pacticipant = form.pacticipant.trim() || '<service>';
  const version = form.version.trim() || '<version>';
  const query = context.recordAnyway ? '?overrideCanIDeploy=true' : '';
  const path = `/pact-broker/pacticipants/${encodeURIComponent(pacticipant)}/versions/${encodeURIComponent(version)}/deployed-versions/environment/${context.uuid ? encodeURIComponent(context.uuid) : '{environment}'}${query}`;
  return {
    verb: 'record-deployment',
    options: [
      { flag: '--pacticipant', value: pacticipant, actionInput: 'pacticipant' },
      { flag: '--version', value: version, actionInput: 'version' },
      { flag: '--environment', value: form.environment.trim() || '<environment>', actionInput: 'environment' },
      { flag: '--application-instance', value: form.applicationInstance, actionInput: 'application-instance' },
    ],
    rest: {
      method: 'POST',
      path: tenantPath(context.tenant, path),
      ...(form.applicationInstance ? { body: { applicationInstance: form.applicationInstance } } : {}),
    },
    unsupported: context.recordAnyway ? [{ what: 'Record it anyway', reason: OVERRIDE_NOT_IN_CLI, inRest: true }] : [],
  };
}

/**
 * **The same, from anywhere** for Record a release.
 *
 * @param form - The form.
 * @param context - `tenant` and the environment's `uuid` (or `null`).
 * @returns `record-release` and the REST `POST`.
 */
export function releaseCommandAction(form: RecordForm, context: { tenant: string; uuid: string | null }): PactAction {
  const pacticipant = form.pacticipant.trim() || '<service>';
  const version = form.version.trim() || '<version>';
  const path = `/pact-broker/pacticipants/${encodeURIComponent(pacticipant)}/versions/${encodeURIComponent(version)}/released-versions/environment/${context.uuid ? encodeURIComponent(context.uuid) : '{environment}'}`;
  return {
    verb: 'record-release',
    options: [
      { flag: '--pacticipant', value: pacticipant },
      { flag: '--version', value: version },
      { flag: '--environment', value: form.environment.trim() || '<environment>' },
    ],
    rest: { method: 'POST', path: tenantPath(context.tenant, path) },
  };
}

/**
 * The releases of a service that stay supported in an environment after a new one is recorded:
 * releases do not replace each other (support ends only by `record-support-ended`).
 *
 * @param topology - The topology.
 * @param environment - The environment's name.
 * @param pacticipant - The service's handle.
 * @param version - The version being released (left out: it is the new one).
 * @returns The other supported releases, newest first.
 */
export function stillSupported(topology: Topology | null, environment: string, pacticipant: string, version: string): CurrentRelease[] {
  const found = topology?.environments.find((entry) => entry.name === environment);
  if (!found) return [];
  return found.released
    .filter((release) => release.pacticipant.slug === pacticipant && release.version !== version.trim())
    .sort((a, b) => (b.releasedAt ?? '').localeCompare(a.releasedAt ?? ''));
}

/**
 * What is deployed of a service to an environment instance now — what a new deployment replaces.
 *
 * @param topology - The topology.
 * @param form - The form (`pacticipant`, `environment`, `applicationInstance`).
 * @returns The version replaced, or `null` for a first deployment there.
 */
export function replacedVersion(topology: Topology | null, form: RecordForm): string | null {
  const found = topology?.environments.find((entry) => entry.name === form.environment);
  const current = found?.deployed.find(
    (deployment) =>
      deployment.pacticipant.slug === form.pacticipant && (deployment.applicationInstance ?? '') === form.applicationInstance,
  );
  return current?.version ?? null;
}

// --- can-i-deploy first ---------------------------------------------------------------------------

/** What the deployment dialog may do with the verdict it has. */
export type VerdictGate =
  /** Nothing asked yet, or asking. */
  | 'waiting'
  /** can-i-deploy says yes: record. */
  | 'yes'
  /** can-i-deploy says no (or does not know yet): recording needs the tick. */
  | 'no';

/**
 * The gate a can-i-deploy answer sets.
 *
 * @param answer - The answer, or `null` while none is in.
 * @returns `yes` only for `deployable: true`; an unknown verdict is a `no` that needs the tick.
 */
export function verdictGate(answer: Pick<MatrixAnswer, 'summary'> | null): VerdictGate {
  if (!answer) return 'waiting';
  return answer.summary.deployable === true ? 'yes' : 'no';
}

/**
 * The reasons for a "no", one per line: the blocking notices, else the warnings, else REST's
 * sentence.
 *
 * @param answer - The answer.
 * @returns The lines (never empty).
 */
export function verdictReasons(answer: Pick<MatrixAnswer, 'summary' | 'notices'>): string[] {
  const errors = answer.notices.filter((notice) => notice.type === 'error').map((notice) => notice.text);
  if (errors.length) return errors;
  const warnings = answer.notices.filter((notice) => notice.type === 'warning').map((notice) => notice.text);
  if (warnings.length) return warnings;
  return [answer.summary.reason || 'can-i-deploy gave no reason.'];
}

/**
 * Whether a deployment may be sent.
 *
 * @param gate - From {@link verdictGate}.
 * @param recordAnyway - Whether **Record it anyway** is ticked.
 * @returns True for a yes, or a no with the tick.
 */
export function mayRecordDeployment(gate: VerdictGate, recordAnyway: boolean): boolean {
  return gate === 'yes' || (gate === 'no' && recordAnyway);
}

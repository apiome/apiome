/**
 * Create, edit and delete a pacticipant — PFX-8.10 (#7307).
 *
 * The pure half of the pacticipant's **Settings** tab, the **New pacticipant** dialog and the
 * **Delete** dialog, shared by the screens and the `/api/pact/pacticipants/*` write proxies:
 *
 * - the form a pacticipant is edited with, read from the stored pacticipant, and the REST `PATCH`
 *   plus the label changes that saving it sends — only what changed, nothing silently dropped;
 * - the checks REST would make (`app.pacticipant`), so a bad field is named before anything is sent;
 * - the body a proxy forwards, refusing any field it does not know with the field's name;
 * - the consequence sentence of a delete, from `GET …/pacticipants/{ref}/deletion-impact`;
 * - **The same, from anywhere**: the form as `apiome pact create-or-update-pacticipant`.
 *
 * Renaming keeps the handle (`orders-ui`): URLs, CI jobs and stored pacts keep naming it, and the
 * old name keeps resolving (REST keeps it as an alias).
 */

import type { Pacticipant } from './pact-pacticipants';
import {
  tenantPath,
  type PactAction,
  type PactOption,
  type PactUnsupported,
} from './pact-commands';

/** The settings route below a pacticipant's page. */
export const SETTINGS_SEGMENT = 'settings';

/** What saving settings needs; read-only roles see the values without inputs. */
export const EDIT_PERMISSION = 'pacts:edit';
/** What registering a pacticipant needs. */
export const CREATE_PERMISSION = 'pacts:create';
/** What deleting or restoring one needs (the built-in Owner and Admin roles). */
export const DELETE_PERMISSION = 'pacts:delete';

/** Longest name, display name, branch and label REST stores (V432 `VARCHAR(255)`). */
export const MAX_TEXT_LENGTH = 255;
/** Longest repository URL REST stores. */
export const MAX_URL_LENGTH = 2048;
/** Longest delete reason REST stores. */
export const MAX_REASON_LENGTH = 500;
/** Most labels one save may add (each is one request). */
export const MAX_LABELS = 50;

/** The edit form, as the inputs hold it. */
export interface SettingsForm {
  name: string;
  displayName: string;
  mainBranch: string;
  repositoryUrl: string;
  /** The linked project's id, or `''` for none. */
  projectId: string;
  labels: string[];
}

/** A field of {@link SettingsForm} a problem is about. */
export type SettingsField = 'name' | 'displayName' | 'mainBranch' | 'repositoryUrl' | 'labels';

/** The problems of a form, by field; empty when it can be sent. */
export type SettingsProblems = Partial<Record<SettingsField, string>>;

/** The REST `PATCH …/pacticipants/{ref}` body: only the fields that changed. */
export interface PacticipantPatchBody {
  name?: string;
  display_name?: string | null;
  main_branch?: string | null;
  repository_url?: string | null;
  project?: string | null;
}

/** The REST `POST …/pacticipants` body. */
export interface PacticipantCreateBody {
  name: string;
  display_name?: string;
  main_branch?: string;
  repository_url?: string;
  project?: string;
}

/** What saving the form sends: the patch (or `null`) and the label changes. */
export interface SettingsChanges {
  patch: PacticipantPatchBody | null;
  addLabels: string[];
  removeLabels: string[];
}

/** `GET …/pacticipants/{ref}/deletion-impact`, as REST answers it. */
export interface DeletionImpact {
  slug: string;
  name: string;
  versions: number;
  pacts: number;
  verification_results: number;
  providers: string[];
  providers_total: number;
  consumers: string[];
  consumers_total: number;
  in_use: string[];
  blocked: boolean;
  grace_days: number;
}

/** ASCII control characters, which REST refuses in a branch or a label. */
const CONTROL = /[\u0000-\u001f\u007f]/;
/** An http(s) URL without whitespace, as REST's URL check. */
const HTTP_URL = /^https?:\/\/\S+$/i;

/**
 * The handle a name reduces to, as REST derives one (`Billing Service` → `billing-service`).
 *
 * @param name - The name.
 * @returns The handle; empty when the name has no letter or digit.
 */
export function handleOf(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 128)
    .replace(/-+$/g, '');
}

/**
 * The form for a stored pacticipant.
 *
 * @param pacticipant - As REST returns it.
 * @returns The form's starting values.
 */
export function formFromPacticipant(pacticipant: Pacticipant): SettingsForm {
  return {
    name: pacticipant.name,
    displayName: pacticipant.display_name ?? '',
    mainBranch: pacticipant.main_branch ?? '',
    repositoryUrl: pacticipant.repository_url ?? '',
    projectId: pacticipant.project_id ?? '',
    labels: [...(pacticipant.labels ?? [])],
  };
}

/**
 * Why a branch or a label would be refused, or `null`.
 *
 * @param value - Exactly as typed (REST stores it as sent, so padding is refused, not trimmed).
 * @param what - What it is, for the sentence.
 * @returns The problem, or `null`.
 */
export function labelProblem(value: string, what: string): string | null {
  if (!value) return `Give the ${what}.`;
  if (value !== value.trim()) return `A ${what} has no leading or trailing space.`;
  if (value.length > MAX_TEXT_LENGTH) return `A ${what} is at most ${MAX_TEXT_LENGTH} characters.`;
  if (CONTROL.test(value)) return `A ${what} has no control characters.`;
  return null;
}

/**
 * What REST would refuse in the form, by field.
 *
 * @param form - The form.
 * @returns The problems; empty when the form can be sent.
 */
export function settingsProblems(form: SettingsForm): SettingsProblems {
  const problems: SettingsProblems = {};
  const name = form.name.trim();
  if (!name) problems.name = 'Give the pacticipant a name.';
  else if (name.length > MAX_TEXT_LENGTH)
    problems.name = `A name is at most ${MAX_TEXT_LENGTH} characters.`;
  else if (!handleOf(name)) problems.name = 'A name needs at least one letter or digit.';
  if (form.displayName.trim().length > MAX_TEXT_LENGTH) {
    problems.displayName = `A display name is at most ${MAX_TEXT_LENGTH} characters.`;
  }
  const branch = form.mainBranch.trim();
  if (branch) {
    const problem = labelProblem(branch, 'branch');
    if (problem) problems.mainBranch = problem;
  }
  const url = form.repositoryUrl.trim();
  if (url && (!HTTP_URL.test(url) || url.length > MAX_URL_LENGTH)) {
    problems.repositoryUrl = 'Use an http(s) URL, such as https://github.com/acme/orders-ui.';
  }
  if (form.labels.length > MAX_LABELS) problems.labels = `At most ${MAX_LABELS} labels.`;
  const bad = form.labels.map((label) => labelProblem(label, 'label')).find(Boolean);
  if (bad) problems.labels = bad;
  return problems;
}

/**
 * Whether a form has no problem.
 *
 * @param problems - From {@link settingsProblems}.
 * @returns `true` when nothing is wrong.
 */
export function isSendable(problems: SettingsProblems): boolean {
  return Object.keys(problems).length === 0;
}

/** Text as REST stores it: trimmed, and `null` when empty (which clears the field). */
function cleared(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/**
 * What saving the form sends: the fields that changed and the labels to add and remove.
 *
 * @param form - The edited form.
 * @param original - The form as the pacticipant was read.
 * @returns The changes; `patch` is `null` when no field changed.
 */
export function settingsChanges(form: SettingsForm, original: SettingsForm): SettingsChanges {
  const patch: PacticipantPatchBody = {};
  if (form.name.trim() !== original.name.trim()) patch.name = form.name.trim();
  if (cleared(form.displayName) !== cleared(original.displayName))
    patch.display_name = cleared(form.displayName);
  if (cleared(form.mainBranch) !== cleared(original.mainBranch))
    patch.main_branch = cleared(form.mainBranch);
  if (cleared(form.repositoryUrl) !== cleared(original.repositoryUrl)) {
    patch.repository_url = cleared(form.repositoryUrl);
  }
  if (form.projectId !== original.projectId) patch.project = form.projectId || null;
  const unique = [...new Set(form.labels)];
  return {
    patch: Object.keys(patch).length ? patch : null,
    addLabels: unique.filter((label) => !original.labels.includes(label)),
    removeLabels: original.labels.filter((label) => !unique.includes(label)),
  };
}

/**
 * Whether the form differs from what is stored.
 *
 * @param form - The edited form.
 * @param original - As read.
 * @returns `true` when saving would send something.
 */
export function isDirty(form: SettingsForm, original: SettingsForm): boolean {
  const changes = settingsChanges(form, original);
  return Boolean(changes.patch) || changes.addLabels.length > 0 || changes.removeLabels.length > 0;
}

/**
 * The `POST …/pacticipants` body of the New pacticipant dialog.
 *
 * @param form - The dialog's form (labels are added after it is created).
 * @returns The body; empty fields are left out.
 */
export function createBody(form: SettingsForm): PacticipantCreateBody {
  const body: PacticipantCreateBody = { name: form.name.trim() };
  const display = cleared(form.displayName);
  const branch = cleared(form.mainBranch);
  const url = cleared(form.repositoryUrl);
  if (display) body.display_name = display;
  if (branch) body.main_branch = branch;
  if (url) body.repository_url = url;
  if (form.projectId) body.project = form.projectId;
  return body;
}

/** The fields each write proxy forwards. Anything else is refused with its name. */
const PATCH_FIELDS = ['name', 'display_name', 'main_branch', 'repository_url', 'project'] as const;
const CREATE_FIELDS = ['name', 'display_name', 'main_branch', 'repository_url', 'project'] as const;

/** A checked proxy body, or the reason it is refused. */
export type CheckedBody<T> = { ok: true; body: T } | { ok: false; error: string };

/**
 * Check a browser's body before a proxy forwards it: a JSON object of known fields, each text
 * (or `null` where REST clears it). An unknown field is refused with its name, never dropped.
 *
 * @param raw - The parsed request body.
 * @param fields - The fields this route accepts.
 * @param nullable - Whether `null` is allowed (a patch clears a field with it).
 * @returns The body, or the error.
 */
function checkBody<T>(raw: unknown, fields: readonly string[], nullable: boolean): CheckedBody<T> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return { ok: false, error: 'Send a JSON object.' };
  const entries = Object.entries(raw as Record<string, unknown>);
  const unknown = entries.filter(([key]) => !fields.includes(key)).map(([key]) => key);
  if (unknown.length) {
    return {
      ok: false,
      error: `Not a pacticipant field: ${unknown.join(', ')}. Send only ${fields.join(', ')}.`,
    };
  }
  for (const [key, value] of entries) {
    if (typeof value === 'string' && value.length <= MAX_URL_LENGTH) continue;
    if (value === null && nullable && key !== 'name') continue;
    return {
      ok: false,
      error: `${key} must be text${nullable && key !== 'name' ? ' or null' : ''}.`,
    };
  }
  return { ok: true, body: Object.fromEntries(entries) as T };
}

/**
 * Check the Settings tab's `PATCH` body.
 *
 * @param raw - The parsed body.
 * @returns The body, or why it is refused (also when it changes nothing).
 */
export function checkPatchBody(raw: unknown): CheckedBody<PacticipantPatchBody> {
  const checked = checkBody<PacticipantPatchBody>(raw, PATCH_FIELDS, true);
  if (checked.ok && Object.keys(checked.body).length === 0)
    return { ok: false, error: 'Nothing to change.' };
  return checked;
}

/**
 * Check the New pacticipant dialog's `POST` body.
 *
 * @param raw - The parsed body.
 * @returns The body, or why it is refused.
 */
export function checkCreateBody(raw: unknown): CheckedBody<PacticipantCreateBody> {
  const checked = checkBody<PacticipantCreateBody>(raw, CREATE_FIELDS, false);
  if (checked.ok && !checked.body.name?.trim())
    return { ok: false, error: 'Give the pacticipant a name.' };
  return checked;
}

/**
 * Check a delete's `reason` query parameter.
 *
 * @param reason - The parameter, or `null`.
 * @returns The reason to forward (`null` for none), or why it is refused.
 */
export function checkReason(reason: string | null): CheckedBody<string | null> {
  const text = (reason ?? '').trim();
  if (text.length > MAX_REASON_LENGTH)
    return { ok: false, error: `A reason is at most ${MAX_REASON_LENGTH} characters.` };
  return { ok: true, body: text || null };
}

/**
 * `1 version`, `3 versions`.
 *
 * @param count - How many.
 * @param noun - The singular.
 * @returns The phrase.
 */
export function plural(count: number, noun: string): string {
  return `${count.toLocaleString('en-US')} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * A list of names: `A`, `A and B`, `A, B and 3 more`.
 *
 * @param names - The names REST listed.
 * @param total - How many there are in all.
 * @returns The phrase.
 */
export function namesPhrase(names: string[], total: number): string {
  const shown = names.slice(0, 3);
  const more = Math.max(total, names.length) - shown.length;
  if (more > 0) return `${shown.join(', ')} and ${more} more`;
  if (shown.length <= 1) return shown.join('');
  return `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}`;
}

/** The sentences of the Delete dialog. */
export interface DeleteSentences {
  /** What goes with it. */
  removes: string;
  /** Who loses a partner, or `null`. */
  affects: string | null;
  /** How long it can be undone. */
  restore: string;
  /** Why it cannot be deleted now, or `null`. */
  blocked: string | null;
}

/**
 * The consequence of deleting a pacticipant, spelled out (DESIGN.md §8, destructive).
 *
 * @param impact - From `GET …/deletion-impact`.
 * @param name - The name to write.
 * @returns The sentences.
 */
export function deleteSentences(impact: DeletionImpact, name: string): DeleteSentences {
  const removes =
    `Its ${plural(impact.versions, 'version')}, ${plural(impact.pacts, 'pact')} and ` +
    `${plural(impact.verification_results, 'verification result')} go with it.`;
  const parts: string[] = [];
  if (impact.providers_total > 0) {
    parts.push(
      `${impact.providers_total === 1 ? '1 provider loses' : `${impact.providers_total} providers lose`} a consumer ` +
        `(${namesPhrase(impact.providers, impact.providers_total)}); their can-i-deploy answers change.`,
    );
  }
  if (impact.consumers_total > 0) {
    parts.push(
      `${impact.consumers_total === 1 ? '1 consumer loses' : `${impact.consumers_total} consumers lose`} a provider ` +
        `(${namesPhrase(impact.consumers, impact.consumers_total)}).`,
    );
  }
  const blocked = impact.blocked
    ? `${namesPhrase(impact.in_use, impact.in_use.length)} of ${name} ${impact.in_use.length === 1 ? 'is' : 'are'} ` +
      'deployed or released. Record the undeployment first.'
    : null;
  return {
    removes,
    affects: parts.length ? parts.join(' ') : null,
    restore: `You can restore it for ${plural(impact.grace_days, 'day')}.`,
    blocked,
  };
}

/**
 * Whether the confirmation typed matches the handle (type-to-confirm).
 *
 * @param typed - What was typed.
 * @param slug - The pacticipant's handle.
 * @returns `true` on an exact match, surrounding space ignored.
 */
export function confirmMatches(typed: string, slug: string): boolean {
  return typed.trim() === slug;
}

/** Why the Settings form's rename, linked project and labels have no `apiome pact` flag. */
export const RENAME_NOT_IN_CLI =
  'create-or-update-pacticipant names a pacticipant by --name and never renames it, as pact-broker does.';
export const PROJECT_NOT_IN_CLI =
  'create-or-update-pacticipant has no flag for a linked project (pact-broker has none).';
export const LABELS_NOT_IN_CLI =
  'create-or-update-pacticipant has no flag for labels; REST adds each label with PUT …/labels/{label}.';

/**
 * **The same, from anywhere** for the Settings form or the New pacticipant dialog.
 *
 * @param form - The form.
 * @param context - The tenant (empty for `{tenant}`), the stored pacticipant when editing one.
 * @returns The action: `create-or-update-pacticipant`, and the REST `PATCH` or `POST`.
 */
export function pacticipantCommandAction(
  form: SettingsForm,
  context: { tenant: string; original?: { slug: string; form: SettingsForm } | null },
): PactAction {
  const original = context.original ?? null;
  const changes = original ? settingsChanges(form, original.form) : null;
  // The CLI names an existing pacticipant by its stored name: a rename is not something it does.
  const cliName = original ? original.form.name : form.name.trim();
  const options: PactOption[] = [
    { flag: '--name', value: cliName || '<name>' },
    { flag: '--display-name', value: form.displayName.trim() },
    { flag: '--main-branch', value: form.mainBranch.trim() },
    { flag: '--repository-url', value: form.repositoryUrl.trim() },
  ];
  const unsupported: PactUnsupported[] = [];
  if (changes?.patch?.name !== undefined)
    unsupported.push({ what: 'The new name', reason: RENAME_NOT_IN_CLI, inRest: true });
  if (original ? changes?.patch?.project !== undefined : Boolean(form.projectId)) {
    unsupported.push({ what: 'The linked project', reason: PROJECT_NOT_IN_CLI, inRest: true });
  }
  if (
    original
      ? (changes?.addLabels.length ?? 0) + (changes?.removeLabels.length ?? 0) > 0
      : form.labels.length > 0
  ) {
    unsupported.push({ what: 'The labels', reason: LABELS_NOT_IN_CLI, inRest: false });
  }
  const rest = original
    ? {
        method: 'PATCH',
        path: tenantPath(context.tenant, `/pacticipants/${encodeURIComponent(original.slug)}`),
        body: changes?.patch ?? {},
      }
    : { method: 'POST', path: tenantPath(context.tenant, '/pacticipants'), body: createBody(form) };
  return { verb: 'create-or-update-pacticipant', options, rest, unsupported };
}

/**
 * **The same, from anywhere** for the Delete dialog.
 *
 * @param slug - The pacticipant's handle.
 * @param name - Its name, as the CLI's `--name`.
 * @param reason - The reason typed, if any.
 * @param tenant - The workspace handle, or empty for `{tenant}`.
 * @returns The action: `delete-pacticipant` and the REST `DELETE`.
 */
export function deleteCommandAction(
  slug: string,
  name: string,
  reason: string,
  tenant = '',
): PactAction {
  const why = reason.trim();
  const query = why ? `?reason=${encodeURIComponent(why)}` : '';
  return {
    verb: 'delete-pacticipant',
    options: [
      { flag: '--name', value: name },
      { flag: '--reason', value: why },
    ],
    rest: {
      method: 'DELETE',
      path: tenantPath(tenant, `/pacticipants/${encodeURIComponent(slug)}${query}`),
    },
  };
}

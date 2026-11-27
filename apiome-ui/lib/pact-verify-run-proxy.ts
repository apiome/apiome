/**
 * The BFF side of **Run a verification** (PFX-8.8, #7305): what `/api/pact/verification/preview`
 * and `/api/pact/verification/runs` (the live run, PFX-8.9) accept.
 *
 * {@link pickVerifyRequest} reads the browser's `{ provider, body }` and refuses, naming it, any
 * field it does not know, a mistyped one or an oversized one — so nothing reaches REST that the
 * page did not mean to send, and nothing is silently dropped. `body` is the REST body of
 * `POST …/pact-verifier/pacts/provider/{provider}/verify` (or `…/verify/preview`), field for field.
 *
 * The rule *mutating requests are never sent to a production target* is REST's to enforce
 * (`pact-verify-mutating-production`); the proxy forwards the run as the signed-in user and passes
 * REST's refusal through with its message. Tenancy and the `pacts` permission are REST's too.
 */

import { MAX_RULES, MAX_TEXT, MAX_URL } from './pact-verify-run';

/** Which proxy is reading. */
export type VerifyRequestMode = 'run' | 'preview';

/** The REST body fields each proxy forwards, and their shape. */
const BODY_FIELDS: Record<VerifyRequestMode, Record<string, 'text' | 'url' | 'boolean' | 'selection' | 'verification' | 'context'>> = {
  run: {
    target_ref: 'text',
    provider_version: 'text',
    provider_branch: 'text',
    build_url: 'url',
    selection: 'selection',
    verification: 'verification',
    publish: 'boolean',
    skip_already_verified: 'boolean',
    context: 'context',
  },
  preview: {
    target_ref: 'text',
    provider_version: 'text',
    provider_branch: 'text',
    selection: 'selection',
    verification: 'verification',
    skip_already_verified: 'boolean',
  },
};

/** The `selection` fields (the body of `…/for-verification` the page builds). */
const SELECTION_FIELDS = ['consumerVersionSelectors', 'includePendingStatus', 'includeWipPactsSince'];

/** The `verification` fields the page sets. */
const VERIFICATION_FIELDS: Record<string, 'boolean' | 'url'> = {
  allow_mutating: 'boolean',
  replay_without_state_setup: 'boolean',
  provider_states_setup_url: 'url',
};

/** The most context entries a run stores. */
const MAX_CONTEXT = 20;

/** A checked request. */
export interface VerifyRequest {
  provider: string;
  body: Record<string, unknown>;
}

/** A checked request, or why it is refused. */
export type PickedVerifyRequest = { ok: true; request: VerifyRequest } | { ok: false; error: string };

/** Whether a value is a plain object. */
function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * The problem with `selection`, if any.
 *
 * @param value - The selection.
 * @returns A message, or `null`.
 */
function selectionProblem(value: unknown): string | null {
  if (!isObject(value)) return 'body.selection must be an object.';
  for (const [key, inner] of Object.entries(value)) {
    if (!SELECTION_FIELDS.includes(key)) return `body.selection.${key} is not a field the page sends.`;
    if (key === 'includePendingStatus' && typeof inner !== 'boolean') return 'body.selection.includePendingStatus must be true or false.';
    if (key === 'includeWipPactsSince' && (typeof inner !== 'string' || inner.length > MAX_TEXT)) {
      return 'body.selection.includeWipPactsSince must be a date.';
    }
    if (key === 'consumerVersionSelectors') {
      if (!Array.isArray(inner) || inner.length > MAX_RULES) return `body.selection.consumerVersionSelectors must be at most ${MAX_RULES} selectors.`;
      for (const selector of inner) {
        if (!isObject(selector)) return 'Each consumer-version selector must be an object.';
        for (const field of Object.values(selector)) {
          if (typeof field === 'string' ? field.length > MAX_TEXT : typeof field !== 'boolean') {
            return 'A consumer-version selector holds only names and true / false.';
          }
        }
      }
    }
  }
  return null;
}

/**
 * The problem with `verification`, if any.
 *
 * @param value - The options.
 * @returns A message, or `null`.
 */
function verificationProblem(value: unknown): string | null {
  if (!isObject(value)) return 'body.verification must be an object.';
  for (const [key, inner] of Object.entries(value)) {
    const want = VERIFICATION_FIELDS[key];
    if (!want) return `body.verification.${key} is not a field the page sends.`;
    if (want === 'boolean' && typeof inner !== 'boolean') return `body.verification.${key} must be true or false.`;
    if (want === 'url' && (typeof inner !== 'string' || inner.length > 2048)) return `body.verification.${key} must be a URL.`;
  }
  return null;
}

/**
 * The problem with one body field, if any.
 *
 * @param mode - Which proxy.
 * @param name - The field.
 * @param value - Its value.
 * @returns A message, or `null`.
 */
function fieldProblem(mode: VerifyRequestMode, name: string, value: unknown): string | null {
  const kind = BODY_FIELDS[mode][name];
  if (!kind) return `body.${name} is not a field ${mode === 'run' ? 'a run' : 'a preview'} takes.`;
  if (kind === 'text') return typeof value === 'string' && value.length <= MAX_TEXT ? null : `body.${name} must be text of at most ${MAX_TEXT} characters.`;
  if (kind === 'url') return typeof value === 'string' && value.length <= MAX_URL ? null : `body.${name} must be a URL.`;
  if (kind === 'boolean') return typeof value === 'boolean' ? null : `body.${name} must be true or false.`;
  if (kind === 'selection') return selectionProblem(value);
  if (kind === 'verification') return verificationProblem(value);
  if (!isObject(value) || Object.keys(value).length > MAX_CONTEXT) return `body.context must be at most ${MAX_CONTEXT} entries.`;
  return Object.values(value).every((inner) => typeof inner === 'string' && inner.length <= MAX_TEXT)
    ? null
    : 'body.context values must be text.';
}

/**
 * Read the browser's body.
 *
 * @param raw - The parsed JSON.
 * @param mode - `run` or `preview`.
 * @returns The request, or the first reason it is refused.
 */
export function pickVerifyRequest(raw: unknown, mode: VerifyRequestMode): PickedVerifyRequest {
  if (!isObject(raw)) return { ok: false, error: 'The request must be a JSON object.' };
  const unknown = Object.keys(raw).find((key) => key !== 'provider' && key !== 'body');
  if (unknown) return { ok: false, error: `${unknown} is not a field of this request.` };
  const provider = typeof raw.provider === 'string' ? raw.provider.trim() : '';
  if (!provider) return { ok: false, error: 'provider is required.' };
  if (provider.length > MAX_TEXT) return { ok: false, error: `provider is longer than ${MAX_TEXT} characters.` };
  const body = raw.body === undefined ? {} : raw.body;
  if (!isObject(body)) return { ok: false, error: 'body must be an object.' };
  for (const [name, value] of Object.entries(body)) {
    const problem = fieldProblem(mode, name, value);
    if (problem) return { ok: false, error: problem };
  }
  if (mode === 'run') {
    for (const name of ['target_ref', 'provider_version']) {
      if (typeof body[name] !== 'string' || !(body[name] as string).trim()) return { ok: false, error: `body.${name} is required.` };
    }
  }
  return { ok: true, request: { provider, body } };
}

/**
 * The REST path below `/v1/tenants/{slug}` for one proxy.
 *
 * @param provider - The provider's handle (checked).
 * @param mode - `run` or `preview`.
 * @returns E.g. `pact-verifier/pacts/provider/billing/verify/preview`.
 */
export function verifyRestPath(provider: string, mode: VerifyRequestMode): string {
  const base = `pact-verifier/pacts/provider/${encodeURIComponent(provider)}/verify`;
  return mode === 'preview' ? `${base}/preview` : base;
}

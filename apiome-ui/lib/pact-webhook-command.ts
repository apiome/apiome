/**
 * The webhook editor's **The same, from anywhere** block (PFX-8.2, #7299): the editor's form as
 * `apiome pact create-webhook`, `pact-broker create-webhook`, a pipeline step and the REST request.
 *
 * Only an HTTP webhook can be created from the command line; a GitHub repository dispatch, the
 * signing secret, a disabled webhook and the events `create-webhook` has no flag for are listed
 * under the block with their reason, never dropped. Editing a saved webhook has no command
 * (`docs/pact-parity-ledger.json` gives the reason), so the block then shows REST only.
 *
 * Every credential — a password, a secret-named header's value, the GitHub token, the signing
 * secret — is written as a `$WEBHOOK_…` variable, the same name on every surface.
 */

import { isSecretName, variableName } from './command-block';
import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from './pact-commands';
import { eventLabel, parseHeaders, webhookBodyFromForm, type WebhookForm } from './pact-webhooks';

/** The prefix of every variable the block writes for a webhook's secrets. */
export const WEBHOOK_VARIABLE_PREFIX = 'WEBHOOK_';

/** The events `apiome pact create-webhook` has a flag for (as `pact-broker create-webhook` does). */
export const CLI_WEBHOOK_EVENTS: readonly string[] = [
  'contract_content_changed',
  'contract_published',
  'contract_requiring_verification_published',
  'provider_verification_published',
  'provider_verification_succeeded',
  'provider_verification_failed',
  'consumer_version_branch_created',
];

/** Why an edit has no command — the ledger's reason for `PUT /api/pact/webhooks/[webhookId]`, in short. */
export const EDIT_HAS_NO_COMMAND =
  'No apiome pact command changes a saved webhook (Pact CLI’s create-or-update-webhook has no counterpart yet). Use the REST request.';

/** Why a GitHub dispatch has no command. */
export const GITHUB_HAS_NO_COMMAND =
  'apiome pact create-webhook sends HTTP requests only; a GitHub repository dispatch is set up here or with the REST request.';

/**
 * The variable a secret is written as.
 *
 * @param name - The field or header name, e.g. `password`, `X-API-Key`.
 * @returns E.g. `WEBHOOK_PASSWORD`, `WEBHOOK_X_API_KEY`.
 */
export function webhookVariable(name: string): string {
  return variableName(name, WEBHOOK_VARIABLE_PREFIX);
}

/**
 * The `--header` options: one per header line, a secret-named header's value as its variable.
 *
 * @param text - The editor's headers, one `Name: value` per line.
 * @returns The options; none when the text cannot be read (the editor reports that itself).
 */
function headerOptions(text: string): PactOption[] {
  const parsed = parseHeaders(text);
  if (!parsed.ok) return [];
  return Object.entries(parsed.headers).map(([name, value]) =>
    isSecretName(name) && value
      ? { flag: '--header', value, secret: webhookVariable(name), secretPrefix: `${name}: ` }
      : { flag: '--header', value: `${name}: ${value}` },
  );
}

/**
 * The `--user` option: `username:password`, the password as `$WEBHOOK_PASSWORD`.
 *
 * @param form - The editor.
 * @returns The option, or `null` without a username.
 */
function userOption(form: WebhookForm): PactOption | null {
  const username = form.username.trim();
  if (!username) return null;
  if (!form.password) return { flag: '--user', value: `${username}:` };
  return { flag: '--user', value: form.password, secret: webhookVariable('password'), secretPrefix: `${username}:` };
}

/**
 * What the command cannot carry from this form.
 *
 * @param form - The editor.
 * @returns One entry per value, each with its reason.
 */
function webhookUnsupported(form: WebhookForm): PactUnsupported[] {
  const items: PactUnsupported[] = form.events
    .filter((name) => !CLI_WEBHOOK_EVENTS.includes(name))
    .map((name) => ({
      what: `The event “${eventLabel(name)}”`,
      reason: 'create-webhook has a flag only for the seven Pact Broker events.',
      inRest: true,
    }));
  if (!form.enabled) {
    items.push({ what: 'Turned off', reason: 'create-webhook always creates the webhook turned on.', inRest: true });
  }
  if (form.signingSecret) {
    items.push({ what: 'The signing secret', reason: 'create-webhook has no option for it.', inRest: true });
  }
  return items;
}

/**
 * The editor's form as a Contracts action.
 *
 * @param form - The editor's current values.
 * @param context - The workspace slug, and the webhook's id when editing a saved one.
 * @returns The action for `pactCommandSurfaces`.
 */
export function webhookCommandAction(form: WebhookForm, context: { tenant: string; webhookId?: string | null }): PactAction {
  const body = webhookBodyFromForm(form);
  const rest = context.webhookId
    ? { method: 'PUT', path: tenantPath(context.tenant, `/pact-broker/webhooks/${encodeURIComponent(context.webhookId)}`) }
    : { method: 'POST', path: tenantPath(context.tenant, '/pact-broker/webhooks') };
  const request = { ...rest, body, variablePrefix: WEBHOOK_VARIABLE_PREFIX };

  if (context.webhookId) return { verb: null, noCommandReason: EDIT_HAS_NO_COMMAND, rest: request };
  if (form.kind === 'github') return { verb: null, noCommandReason: GITHUB_HAS_NO_COMMAND, rest: request };

  const user = userOption(form);
  const options: PactOption[] = [
    { flag: '--request', value: form.method === 'POST' ? '' : form.method },
    ...headerOptions(form.headers),
    { flag: '--data', value: form.body.trim() ? form.body : '' },
    ...(user ? [user] : []),
    { flag: '--consumer', value: form.consumer.trim() },
    { flag: '--provider', value: form.provider.trim() },
    { flag: '--description', value: form.description.trim() },
    ...CLI_WEBHOOK_EVENTS.filter((name) => form.events.includes(name)).map((name) => ({
      flag: `--${name.replace(/_/g, '-')}`,
      value: true,
    })),
  ];
  return {
    verb: 'create-webhook',
    args: [{ value: form.url.trim() || '<url>' }],
    options,
    rest: request,
    unsupported: webhookUnsupported(form),
  };
}

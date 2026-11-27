/**
 * The model behind **The same, from anywhere** (PFX-8.2, #7299): quoting, the secret guards, the
 * four Contracts surfaces, and the webhook editor's action.
 */

import {
  isSecretName,
  redactSecretFields,
  SCRUBBED,
  scrubSecrets,
  shellLines,
  shellQuote,
  shellVariable,
  variableName,
} from '../lib/command-block';
import { PACT_ACTION_REF, pactCommandSurfaces, tenantPath, unsupportedLines, yamlScalar, type PactAction } from '../lib/pact-commands';
import { EDIT_HAS_NO_COMMAND, GITHUB_HAS_NO_COMMAND, webhookCommandAction } from '../lib/pact-webhook-command';
import { emptyWebhookForm, REDACTED, type WebhookForm } from '../lib/pact-webhooks';

/** Every surface's text, joined, for "never prints" checks. */
function everything(action: PactAction): string {
  return pactCommandSurfaces(action)
    .map((surface) => `${surface.text ?? ''}\n${(surface.notes ?? []).join('\n')}`)
    .join('\n');
}

/** A surface's text by id. */
function text(action: PactAction, id: string): string | null {
  return pactCommandSurfaces(action).find((surface) => surface.id === id)?.text ?? null;
}

describe('shell quoting', () => {
  it('leaves safe words bare and single-quotes the rest', () => {
    expect(shellQuote('3.4.0+a1c9e02')).toBe('3.4.0+a1c9e02');
    expect(shellQuote('feature/credit-notes')).toBe('feature/credit-notes');
    expect(shellQuote('Orders UI')).toBe("'Orders UI'");
    expect(shellQuote("it's")).toBe("'it'\\''s'");
    expect(shellQuote('$HOME')).toBe("'$HOME'");
    expect(shellQuote('')).toBe("''");
  });

  it('writes a variable in double quotes with its prefix escaped', () => {
    expect(shellVariable('Authorization: ', 'WEBHOOK_AUTHORIZATION')).toBe('"Authorization: $WEBHOOK_AUTHORIZATION"');
    expect(shellVariable('a"b$c', 'X')).toBe('"a\\"b\\$c$X"');
  });

  it('lays a command out one option per line', () => {
    expect(shellLines('apiome pact publish pacts/', ['--branch main', '--tag dev'])).toBe(
      'apiome pact publish pacts/ \\\n  --branch main \\\n  --tag dev',
    );
    expect(shellLines('apiome pact list-pacticipants', [])).toBe('apiome pact list-pacticipants');
  });

  it('names a variable from any label', () => {
    expect(variableName('X-API-Key', 'WEBHOOK_')).toBe('WEBHOOK_X_API_KEY');
    expect(variableName('signingSecret')).toBe('SIGNING_SECRET');
    expect(variableName('1st')).toBe('_1ST');
    expect(variableName('***')).toBe('SECRET');
  });
});

describe('the secret guards', () => {
  it('knows the names that hold credentials', () => {
    for (const name of ['Authorization', 'password', 'X-API-Key', 'api_key', 'token', 'signingSecret', 'Cookie']) {
      expect(isSecretName(name)).toBe(true);
    }
    for (const name of ['Content-Type', 'username', 'compass', 'description', 'consumer']) expect(isSecretName(name)).toBe(false);
  });

  it('scrubs credential-shaped text wherever it is', () => {
    expect(scrubSecrets('-H "Authorization: Bearer abcdefgh12345678"')).toBe(`-H "Authorization: Bearer ${SCRUBBED}"`);
    expect(scrubSecrets('token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123')).toBe(`token ${SCRUBBED}`);
    expect(scrubSecrets('key apiome_0123456789abcdefXYZ')).toBe(`key ${SCRUBBED}`);
    expect(scrubSecrets('eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4')).toBe(SCRUBBED);
    expect(scrubSecrets('https://bot:hunter2@ci.example.com/hook')).toBe(`https://bot:${SCRUBBED}@ci.example.com/hook`);
  });

  it('leaves variables and ordinary text alone', () => {
    const line = '--header "Authorization: $WEBHOOK_AUTHORIZATION" --branch main';
    expect(scrubSecrets(line)).toBe(line);
  });

  it('replaces secret fields deeply, keeping empty ones as they are', () => {
    const body = { request: { headers: { Authorization: 'Bearer x', Accept: 'json' }, password: 'p', username: 'u' }, token: '' };
    expect(redactSecretFields(body, (name) => `$${variableName(name)}`)).toEqual({
      request: { headers: { Authorization: '$AUTHORIZATION', Accept: 'json' }, password: '$PASSWORD', username: 'u' },
      token: '',
    });
  });
});

/** A publish with every kind of option. */
const PUBLISH: PactAction = {
  verb: 'publish',
  args: [{ value: 'pacts/', actionInput: 'pacts' }],
  options: [
    { flag: '--consumer-app-version', value: '3.4.0+a1c9e02', actionInput: 'version' },
    { flag: '--branch', value: 'feature/credit-notes', actionInput: 'branch' },
    { flag: '--tag', value: ['dev', 'qa'], actionInput: 'tags' },
    { flag: '--merge', value: true },
    { flag: '--build-url', value: '' },
  ],
  rest: { method: 'POST', path: tenantPath('acme', '/pact-broker/contracts/publish'), body: { branch: 'feature/credit-notes' } },
};

describe('the four surfaces', () => {
  it('come in pill order', () => {
    expect(pactCommandSurfaces(PUBLISH).map((surface) => surface.label)).toEqual(['apiome', 'Pact CLI', 'GitHub Action', 'REST']);
  });

  it('write the apiome command from the form, empty values left out', () => {
    expect(text(PUBLISH, 'apiome')).toBe(
      [
        'apiome pact publish pacts/ \\',
        '  --consumer-app-version 3.4.0+a1c9e02 \\',
        '  --branch feature/credit-notes \\',
        '  --tag dev \\',
        '  --tag qa \\',
        '  --merge',
      ].join('\n'),
    );
  });

  it('write the Pact CLI command with the broker URL as a variable', () => {
    expect(text(PUBLISH, 'pact-cli')).toMatch(/^pact-broker publish pacts\/ \\/);
    expect(text(PUBLISH, 'pact-cli')).toMatch(/--broker-base-url "\$PACT_BROKER_BASE_URL"$/);
  });

  it('use the action for a verb it runs, with its inputs, and say what it has no input for', () => {
    const surface = pactCommandSurfaces(PUBLISH).find((s) => s.id === 'github-action')!;
    expect(surface.text).toContain(`- uses: ${PACT_ACTION_REF}`);
    expect(surface.text).toContain('    command: publish');
    expect(surface.text).toContain('    pacts: pacts/');
    expect(surface.text).toContain('    tags: |\n      dev\n      qa');
    expect(surface.text).toContain('    broker-token: ${{ secrets.PACT_BROKER_TOKEN }}');
    expect(surface.notes).toEqual([expect.stringContaining('no input for --merge')]);
  });

  it('use a run: step for a verb the action does not run', () => {
    const action: PactAction = { verb: 'create-environment', options: [{ flag: '--name', value: 'staging' }], rest: { method: 'POST', path: '/x' } };
    const surface = pactCommandSurfaces(action).find((s) => s.id === 'github-action')!;
    expect(surface.text).toContain('  run: |\n    apiome pact create-environment \\\n      --name staging');
    expect(surface.text).toContain('    PACT_BROKER_TOKEN: ${{ secrets.PACT_BROKER_TOKEN }}');
    expect(surface.notes?.[0]).toContain('runs publish, can-i-deploy and record-deployment');
  });

  it('say why Pact CLI cannot do an Apiome-only verb', () => {
    const action: PactAction = { verb: 'migrate', rest: { method: 'POST', path: '/x' } };
    const surface = pactCommandSurfaces(action).find((s) => s.id === 'pact-cli')!;
    expect(surface.text).toBeNull();
    expect(surface.unavailable).toBe("Pact CLI has no command for apiome pact migrate; it is Apiome's own.");
  });

  it('name an option Pact CLI has no flag for instead of dropping it', () => {
    const action: PactAction = {
      verb: 'publish',
      options: [{ flag: '--apiome-only', value: 'x', notInPactCli: 'pact-broker has no such option.' }],
      rest: { method: 'POST', path: '/x' },
    };
    const surface = pactCommandSurfaces(action).find((s) => s.id === 'pact-cli')!;
    expect(surface.text).not.toContain('--apiome-only');
    expect(surface.notes).toContain('--apiome-only is left out: pact-broker has no such option.');
  });

  it('show only REST, with the reason on the others, when no command does the action', () => {
    const action: PactAction = { verb: null, noCommandReason: 'Nothing does this yet.', rest: { method: 'DELETE', path: '/v1/x' } };
    const surfaces = pactCommandSurfaces(action);
    expect(surfaces.filter((s) => s.text === null).map((s) => s.unavailable)).toEqual([
      'Nothing does this yet.',
      'Nothing does this yet.',
      'Nothing does this yet.',
    ]);
    expect(surfaces[3].text).toBe('DELETE /v1/x');
  });

  it('refuse a verb that is not an apiome pact command', () => {
    expect(() => pactCommandSurfaces({ verb: 'deploy-everything', rest: { method: 'POST', path: '/x' } })).toThrow(
      'apiome pact has no command "deploy-everything"',
    );
  });

  it('write the REST request line and the body', () => {
    expect(text(PUBLISH, 'rest')).toBe('POST /v1/tenants/acme/pact-broker/contracts/publish\n\n{\n  "branch": "feature/credit-notes"\n}');
    expect(tenantPath('', '/pact-broker/webhooks')).toBe('/v1/tenants/{tenant}/pact-broker/webhooks');
  });
});

describe('YAML scalars', () => {
  it('quotes what YAML would read as something else', () => {
    expect(yamlScalar('Billing Service')).toBe('Billing Service');
    expect(yamlScalar('true')).toBe('"true"');
    expect(yamlScalar('12')).toBe('"12"');
    expect(yamlScalar('a: b')).toBe('"a: b"');
    expect(yamlScalar('#hash')).toBe('"#hash"');
  });
});

/** An HTTP webhook with every kind of secret in it. */
function secretWebhook(): WebhookForm {
  return {
    ...emptyWebhookForm(),
    url: 'https://ci.example.com/hooks/pact',
    headers: 'Content-Type: application/json\nAuthorization: Bearer s3cr3t-header-value\nX-API-Key: k-123456789',
    username: 'ci-bot',
    password: 'hunter2-password',
    consumer: 'Orders UI',
    events: ['contract_published', 'contract_became_stale'],
    signingSecret: 'signing-secret-0123456789',
    enabled: false,
  };
}

describe('the webhook editor as an action', () => {
  const secrets = ['s3cr3t-header-value', 'k-123456789', 'hunter2-password', 'signing-secret-0123456789'];

  it('never prints a secret on any surface', () => {
    const all = everything(webhookCommandAction(secretWebhook(), { tenant: 'acme' }));
    for (const secret of secrets) expect(all).not.toContain(secret);
  });

  it('writes each secret as the same $WEBHOOK_… variable on every surface', () => {
    const action = webhookCommandAction(secretWebhook(), { tenant: 'acme' });
    expect(text(action, 'apiome')).toContain('--header "Authorization: $WEBHOOK_AUTHORIZATION"');
    expect(text(action, 'apiome')).toContain('--header "X-API-Key: $WEBHOOK_X_API_KEY"');
    expect(text(action, 'apiome')).toContain('--user "ci-bot:$WEBHOOK_PASSWORD"');
    expect(text(action, 'apiome')).toContain("--header 'Content-Type: application/json'");
    expect(text(action, 'rest')).toContain('"Authorization": "$WEBHOOK_AUTHORIZATION"');
    expect(text(action, 'rest')).toContain('"password": "$WEBHOOK_PASSWORD"');
    expect(text(action, 'rest')).toContain('"signingSecret": "$WEBHOOK_SIGNING_SECRET"');
    expect(text(action, 'github-action')).toContain('    WEBHOOK_PASSWORD: ${{ secrets.WEBHOOK_PASSWORD }}');
  });

  it('follows the form: event flags, scope, method and body', () => {
    const form = { ...secretWebhook(), method: 'PUT', provider: 'Billing Service' };
    const apiome = text(webhookCommandAction(form, { tenant: 'acme' }), 'apiome')!;
    expect(apiome).toMatch(/^apiome pact create-webhook https:\/\/ci\.example\.com\/hooks\/pact \\/);
    expect(apiome).toContain('--request PUT');
    expect(apiome).toContain("--consumer 'Orders UI'");
    expect(apiome).toContain("--provider 'Billing Service'");
    expect(apiome).toContain('--contract-published');
    expect(apiome).toContain(`--data '{\n  "pactUrl": "\${pactbroker.pactUrl}"\n}'`);
    expect(apiome).not.toContain('--contract-became-stale');
  });

  it('leaves the default method out and writes a placeholder until there is a URL', () => {
    const apiome = text(webhookCommandAction(emptyWebhookForm(), { tenant: 'acme' }), 'apiome')!;
    expect(apiome).toMatch(/^apiome pact create-webhook '<url>' \\/);
    expect(apiome).not.toContain('--request');
    expect(apiome).toContain('--contract-requiring-verification-published');
  });

  it('writes a username without a password as "username:"', () => {
    const form = { ...emptyWebhookForm(), url: 'https://ci.example.com/h', username: 'bot' };
    expect(text(webhookCommandAction(form, { tenant: 'acme' }), 'apiome')).toContain('--user bot:');
  });

  it('lists what create-webhook cannot carry, each with its reason', () => {
    expect(unsupportedLines(webhookCommandAction(secretWebhook(), { tenant: 'acme' }))).toEqual([
      'The event “Contract became stale” is not carried by the command (REST carries it): create-webhook has a flag only for the seven Pact Broker events.',
      'Turned off is not carried by the command (REST carries it): create-webhook always creates the webhook turned on.',
      'The signing secret is not carried by the command (REST carries it): create-webhook has no option for it.',
    ]);
  });

  it('has no command for a GitHub dispatch, and REST keeps the token as a variable', () => {
    const form: WebhookForm = { ...emptyWebhookForm(), kind: 'github', repository: 'acme/ledger', token: 'ghp_ABCDEFGHIJKLMNOPQRSTUVWX0123' };
    const action = webhookCommandAction(form, { tenant: 'acme' });
    expect(action.verb).toBeNull();
    expect(pactCommandSurfaces(action)[0].unavailable).toBe(GITHUB_HAS_NO_COMMAND);
    expect(text(action, 'rest')).toContain('"token": "$WEBHOOK_TOKEN"');
    expect(everything(action)).not.toContain('ghp_ABCDEF');
  });

  it('has no command for an edit: REST PUT to the webhook, stored secrets as variables', () => {
    const form = { ...secretWebhook(), password: REDACTED };
    const action = webhookCommandAction(form, { tenant: 'acme', webhookId: 'abc-123' });
    expect(pactCommandSurfaces(action)[0].unavailable).toBe(EDIT_HAS_NO_COMMAND);
    expect(text(action, 'rest')).toMatch(/^PUT \/v1\/tenants\/acme\/pact-broker\/webhooks\/abc-123\n/);
    expect(text(action, 'rest')).toContain('"password": "$WEBHOOK_PASSWORD"');
  });
});

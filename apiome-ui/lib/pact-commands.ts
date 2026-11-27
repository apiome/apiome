/**
 * One Contracts action as `apiome pact`, Pact CLI, the GitHub Action and REST — the four pills of
 * **The same, from anywhere** (PFX-8.2, #7299).
 *
 * A screen describes what its form would do as a {@link PactAction} — the `apiome pact` verb, its
 * arguments and options from the current form values, and the REST request — and
 * {@link pactCommandSurfaces} renders it for each surface. A surface that cannot do the action says
 * why instead of printing something that would not work, and every form value no surface carries
 * is listed under the block with its reason: nothing is dropped silently.
 *
 * Which surfaces exist for which verb is {@link PACT_VERBS}; `tests/pact-parity-ledger.test.ts`
 * holds it against `docs/pact-parity-ledger.json` and the CLI's own command list, so a verb here
 * is always a real `apiome pact` command with the REST route the ledger names.
 *
 * Secrets: an option or argument with `secret` is written as a variable reference
 * (`"$WEBHOOK_PASSWORD"`), REST bodies have every secret-named field replaced the same way, the
 * broker token is only ever `$PACT_BROKER_TOKEN` / `${{ secrets.PACT_BROKER_TOKEN }}`, and the
 * final text of each surface goes through {@link scrubSecrets}.
 */

import {
  redactSecretFields,
  scrubSecrets,
  shellLines,
  shellQuote,
  shellVariable,
  variableName,
  type CommandSurface,
} from './command-block';

/** The pill ids, in the order the block shows them. */
export const PACT_SURFACE_IDS = ['apiome', 'pact-cli', 'github-action', 'rest'] as const;

/** One pill id. */
export type PactSurfaceId = (typeof PACT_SURFACE_IDS)[number];

/** What each pill reads. */
export const PACT_SURFACE_LABELS: Record<PactSurfaceId, string> = {
  apiome: 'apiome',
  'pact-cli': 'Pact CLI',
  'github-action': 'GitHub Action',
  rest: 'REST',
};

/** The GitHub Action, as its README pins it. */
export const PACT_ACTION_REF = 'apiome/apiome/pact-action@main';

/** What a `apiome pact` verb is on the other surfaces. */
export interface PactVerbSurfaces {
  /** The Pact CLI command that does the same (`pact-broker publish`), or `null`. */
  pactCli: string | null;
  /** Whether `pact-action` runs this verb as a `command:`. Otherwise the step runs the CLI. */
  action: boolean;
  /** The REST route, `METHOD /v1/tenants/{tenant}/…`, as the ledger names it. */
  rest: string;
}

/**
 * Every `apiome pact` verb and its other surfaces. The Pact CLI column is the one
 * `ship/pact-broker/cli.mdx` documents; the action runs `publish`, `can-i-deploy` and
 * `record-deployment` (`pact-action/action.yml`).
 */
export const PACT_VERBS: Readonly<Record<string, PactVerbSurfaces>> = {
  'can-i-deploy': { pactCli: 'pact-broker can-i-deploy', action: true, rest: 'GET /v1/tenants/{tenant}/pact-broker/matrix' },
  check: { pactCli: null, action: false, rest: 'POST /v1/tenants/{tenant}/pact-broker/pacts/check' },
  'create-environment': {
    pactCli: 'pact-broker create-environment',
    action: false,
    rest: 'POST /v1/tenants/{tenant}/pact-broker/environments',
  },
  'create-or-update-pacticipant': {
    pactCli: 'pact-broker create-or-update-pacticipant',
    action: false,
    rest: 'PATCH /v1/tenants/{tenant}/pacticipants/{pacticipant}',
  },
  'create-webhook': { pactCli: 'pact-broker create-webhook', action: false, rest: 'POST /v1/tenants/{tenant}/pact-broker/webhooks' },
  'delete-pacticipant': { pactCli: null, action: false, rest: 'DELETE /v1/tenants/{tenant}/pacticipants/{pacticipant}' },
  'describe-version': {
    pactCli: 'pact-broker describe-version',
    action: false,
    rest: 'GET /v1/tenants/{tenant}/pact-broker/pacticipants/{pacticipant}/versions/{version}',
  },
  'export-consumer-contract': {
    pactCli: null,
    action: false,
    rest: 'GET /v1/tenants/{tenant}/projects/{project}/consumers/{consumer}/pact',
  },
  'export-postman': { pactCli: null, action: false, rest: 'POST /v1/tenants/{tenant}/pact-postman-collections' },
  'list-pacticipants': { pactCli: 'pact-broker list-pacticipants', action: false, rest: 'GET /v1/tenants/{tenant}/pacticipants' },
  migrate: { pactCli: null, action: false, rest: 'POST /v1/tenants/{tenant}/pact-migration/import' },
  publish: { pactCli: 'pact-broker publish', action: true, rest: 'POST /v1/tenants/{tenant}/pact-broker/contracts/publish' },
  'publish-consumer-contract': {
    pactCli: null,
    action: false,
    rest: 'POST /v1/tenants/{tenant}/projects/{project}/consumers/{consumer}/pact/publish',
  },
  'publish-provider-contract': {
    pactCli: 'pactflow publish-provider-contract',
    action: false,
    rest: 'PUT /v1/tenants/{tenant}/pact-broker/contracts/provider/{provider}/version/{version}',
  },
  'publish-verification-results': {
    pactCli: null,
    action: false,
    rest: 'POST /v1/tenants/{tenant}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/external-verification-results',
  },
  'record-deployment': {
    pactCli: 'pact-broker record-deployment',
    action: true,
    rest: 'POST /v1/tenants/{tenant}/pact-broker/pacticipants/{pacticipant}/versions/{version}/deployed-versions/environment/{environment}',
  },
  'record-release': {
    pactCli: 'pact-broker record-release',
    action: false,
    rest: 'POST /v1/tenants/{tenant}/pact-broker/pacticipants/{pacticipant}/versions/{version}/released-versions/environment/{environment}',
  },
  verify: { pactCli: null, action: false, rest: 'POST /v1/tenants/{tenant}/pact-verifier/pacts/provider/{provider}/verify' },
};

/** A value from the form: text, a switch, or a repeatable list. Empty values are left out. */
export type PactValue = string | boolean | string[] | null | undefined;

/** One option of the command, from one form field. */
export interface PactOption {
  /** The `apiome pact` flag, e.g. `--branch`. */
  flag: string;
  /** The form's value: `true` writes the bare flag, a list repeats it, empty leaves it out. */
  value: PactValue;
  /**
   * The value is a credential: it is written as this environment variable (`"$WEBHOOK_PASSWORD"`),
   * never as itself.
   */
  secret?: string;
  /** Literal text before the variable of a secret value, e.g. `Authorization: `. */
  secretPrefix?: string;
  /** The `pact-action` input that carries it, when the action runs this verb. */
  actionInput?: string;
  /** Pact CLI has no such option: set to the reason, and the Pact CLI pill says so. */
  notInPactCli?: string;
}

/** One positional argument. */
export interface PactArgument {
  value: string;
  /** As for {@link PactOption.secret}. */
  secret?: string;
  /** The `pact-action` input that carries it. */
  actionInput?: string;
}

/** Something the form holds that no command carries, and why. */
export interface PactUnsupported {
  /** What it is, as the form labels it, e.g. `GitHub repository dispatch target`. */
  what: string;
  /** Why the command cannot carry it. */
  reason: string;
  /** Whether the REST request still carries it (it usually does). */
  inRest: boolean;
}

/** What the screen's form would do. */
export interface PactAction {
  /**
   * The `apiome pact` verb, or `null` when no command does this action (an edit, a delete) — then
   * `noCommandReason` says why and only REST is shown.
   */
  verb: string | null;
  /** Why there is no command, when `verb` is `null`. */
  noCommandReason?: string;
  args?: PactArgument[];
  options?: PactOption[];
  /**
   * The REST request: method, the path with the real tenant and ids, and the body. A secret field
   * of the body is shown as `$<variablePrefix><FIELD>`, so it matches the CLI's variable.
   */
  rest: { method: string; path: string; body?: unknown; variablePrefix?: string };
  /** Form values no command carries. */
  unsupported?: PactUnsupported[];
}

/** The variables a pipeline sets for every `apiome pact` / `pact-broker` command. */
const BROKER_VARIABLES = ['PACT_BROKER_BASE_URL', 'PACT_BROKER_TOKEN'] as const;

/**
 * One shell word for an option's (or argument's) value.
 *
 * @param value - The text.
 * @param secret - The variable to write instead, when the value is a credential.
 * @param prefix - Literal text before the variable.
 * @returns The quoted word.
 */
function word(value: string, secret?: string, prefix = ''): string {
  return secret ? shellVariable(prefix, secret) : shellQuote(value);
}

/**
 * Whether a form value is set.
 *
 * @param value - The value.
 * @returns `false` for `undefined`, `null`, `false`, `''` (after trimming) and `[]`.
 */
function present(value: PactValue): boolean {
  if (Array.isArray(value)) return value.some((item) => item.trim() !== '');
  if (typeof value === 'string') return value.trim() !== '';
  return value === true;
}

/**
 * The words of one option: `--flag value`, `--flag` for a switch, one per item of a list.
 *
 * @param option - The option.
 * @returns The words, already quoted; empty when the value is not set.
 */
function optionWords(option: PactOption): string[] {
  if (!present(option.value)) return [];
  if (option.value === true) return [option.flag];
  const values = Array.isArray(option.value) ? option.value.filter((item) => item.trim() !== '') : [String(option.value)];
  return values.map((value) => `${option.flag} ${word(value, option.secret, option.secretPrefix)}`);
}

/**
 * The secret variables the action uses, in order, once each.
 *
 * @param action - The action.
 * @returns E.g. `['WEBHOOK_PASSWORD']`.
 */
function secretVariables(action: PactAction): string[] {
  const names = [
    ...(action.args ?? []).filter((arg) => arg.secret && arg.value.trim()).map((arg) => arg.secret as string),
    ...(action.options ?? []).filter((option) => option.secret && present(option.value)).map((option) => option.secret as string),
  ];
  return [...new Set(names)];
}

/**
 * A command line for one CLI.
 *
 * @param program - The program and verb, e.g. `apiome pact publish` or `pact-broker publish`.
 * @param action - The action.
 * @param options - The options to write.
 * @param extra - Options after the action's own, e.g. the broker URL.
 * @returns The command.
 */
function commandLine(program: string, action: PactAction, options: PactOption[], extra: string[] = []): string {
  const args = (action.args ?? []).filter((arg) => arg.value.trim()).map((arg) => word(arg.value, arg.secret));
  return shellLines([program, ...args].join(' '), [...options.flatMap(optionWords), ...extra]);
}

/**
 * The `apiome pact` pill.
 *
 * @param action - The action.
 * @returns The surface.
 */
function apiomeSurface(action: PactAction): CommandSurface {
  const surface = { id: 'apiome', label: PACT_SURFACE_LABELS.apiome };
  if (!action.verb) return { ...surface, text: null, unavailable: action.noCommandReason ?? 'No apiome pact command does this yet.' };
  return {
    ...surface,
    text: commandLine(`apiome pact ${action.verb}`, action, action.options ?? []),
    notes: ['Reads PACT_BROKER_BASE_URL and PACT_BROKER_TOKEN, or the workspace you signed in to with apiome login.'],
  };
}

/**
 * The Pact CLI pill.
 *
 * @param action - The action.
 * @returns The surface.
 */
function pactCliSurface(action: PactAction): CommandSurface {
  const surface = { id: 'pact-cli', label: PACT_SURFACE_LABELS['pact-cli'] };
  const program = action.verb ? PACT_VERBS[action.verb]?.pactCli : null;
  if (!action.verb || !program) {
    return {
      ...surface,
      text: null,
      unavailable: action.verb
        ? `Pact CLI has no command for apiome pact ${action.verb}; it is Apiome's own.`
        : (action.noCommandReason ?? 'No command does this yet.'),
    };
  }
  const options = action.options ?? [];
  const carried = options.filter((option) => !option.notInPactCli);
  const left = options.filter((option) => option.notInPactCli && present(option.value));
  return {
    ...surface,
    text: commandLine(program, action, carried, ['--broker-base-url "$PACT_BROKER_BASE_URL"']),
    notes: [
      'Reads the token from PACT_BROKER_TOKEN.',
      ...left.map((option) => `${option.flag} is left out: ${option.notInPactCli}`),
    ],
  };
}

/**
 * The GitHub Action pill: an `apiome/pact-action` step when the action runs this verb, otherwise a
 * `run:` step with the `apiome pact` command.
 *
 * @param action - The action.
 * @returns The surface.
 */
function githubActionSurface(action: PactAction): CommandSurface {
  const surface = { id: 'github-action', label: PACT_SURFACE_LABELS['github-action'] };
  if (!action.verb) return { ...surface, text: null, unavailable: action.noCommandReason ?? 'No command does this yet.' };
  const secrets = secretVariables(action);
  const env = [...BROKER_VARIABLES, ...secrets].map((name) => `    ${name}: \${{ secrets.${name} }}`);
  if (PACT_VERBS[action.verb]?.action) {
    const inputs: string[] = [];
    const left: string[] = [];
    for (const arg of action.args ?? []) {
      if (!arg.value.trim()) continue;
      if (arg.actionInput && !arg.secret) inputs.push(`    ${arg.actionInput}: ${yamlScalar(arg.value)}`);
      else left.push(`the argument ${arg.value}`);
    }
    for (const option of action.options ?? []) {
      if (!present(option.value)) continue;
      if (!option.actionInput || option.secret) {
        left.push(option.flag);
        continue;
      }
      const value = Array.isArray(option.value) ? option.value.filter((item) => item.trim()).join('\n') : String(option.value);
      inputs.push(`    ${option.actionInput}: ${yamlScalar(value, 4)}`);
    }
    return {
      ...surface,
      text: [
        `- uses: ${PACT_ACTION_REF}`,
        '  with:',
        `    command: ${action.verb}`,
        ...inputs,
        '    broker-base-url: ${{ secrets.PACT_BROKER_BASE_URL }}',
        '    broker-token: ${{ secrets.PACT_BROKER_TOKEN }}',
      ].join('\n'),
      notes: left.length ? [`The action has no input for ${left.join(', ')}; run the apiome command in a run: step to set it.`] : [],
    };
  }
  const command = commandLine(`apiome pact ${action.verb}`, action, action.options ?? []);
  return {
    ...surface,
    text: [`- name: apiome pact ${action.verb}`, '  run: |', ...command.split('\n').map((line) => `    ${line}`), '  env:', ...env].join('\n'),
    notes: [`${PACT_ACTION_REF} runs publish, can-i-deploy and record-deployment; this step runs the CLI the action installs.`],
  };
}

/**
 * A YAML scalar: plain when it is safe, a block (`|`) for several lines, double-quoted otherwise.
 *
 * @param value - The text.
 * @param indent - The indent of the key, for a block's lines.
 * @returns The scalar.
 */
export function yamlScalar(value: string, indent = 4): string {
  if (value.includes('\n')) {
    const pad = ' '.repeat(indent + 2);
    return `|\n${value
      .split('\n')
      .map((line) => `${pad}${line}`)
      .join('\n')}`;
  }
  if (/^[A-Za-z0-9_./@+-][A-Za-z0-9 _./@+:-]*$/.test(value) && !/:\s|\s$|^(true|false|yes|no|null|on|off|~)$/i.test(value) && !/^\d/.test(value)) {
    return value;
  }
  return JSON.stringify(value);
}

/**
 * The REST pill: the request line, then the body as JSON with every secret field replaced.
 *
 * @param action - The action.
 * @returns The surface.
 */
function restSurface(action: PactAction): CommandSurface {
  const line = `${action.rest.method} ${action.rest.path}`;
  const body =
    action.rest.body === undefined
      ? ''
      : `\n\n${JSON.stringify(
          redactSecretFields(action.rest.body, (name) => `$${variableName(name, action.rest.variablePrefix)}`),
          null,
          2,
        )}`;
  return {
    id: 'rest',
    label: PACT_SURFACE_LABELS.rest,
    text: `${line}${body}`,
    notes: ['Send a workspace API key as Authorization: Bearer $APIOME_API_KEY; secrets are shown as $VARIABLES.'],
  };
}

/**
 * Every pill for one action, in {@link PACT_SURFACE_IDS} order, with each text scrubbed.
 *
 * @param action - What the screen's form would do.
 * @returns The surfaces for `CommandBlock`.
 * @throws Error when `verb` is not an `apiome pact` command — a programming error the parity gate
 *   also catches.
 */
export function pactCommandSurfaces(action: PactAction): CommandSurface[] {
  if (action.verb && !PACT_VERBS[action.verb]) throw new Error(`apiome pact has no command "${action.verb}"`);
  return [apiomeSurface(action), pactCliSurface(action), githubActionSurface(action), restSurface(action)].map((surface) => ({
    ...surface,
    text: surface.text === null ? null : scrubSecrets(surface.text),
  }));
}

/**
 * The lines the block lists under its text: each form value no command carries, with its reason.
 *
 * @param action - The action.
 * @returns One sentence per value.
 */
export function unsupportedLines(action: PactAction): string[] {
  return (action.unsupported ?? []).map(
    (item) => `${item.what} is not carried by the command${item.inRest ? ' (REST carries it)' : ''}: ${item.reason}`,
  );
}

/**
 * The REST path with the workspace filled in.
 *
 * @param tenant - The workspace slug.
 * @param suffix - The path after `/v1/tenants/{tenant}`, starting with `/`.
 * @returns E.g. `/v1/tenants/acme/pact-broker/webhooks`.
 */
export function tenantPath(tenant: string, suffix: string): string {
  return `/v1/tenants/${tenant ? encodeURIComponent(tenant) : '{tenant}'}${suffix}`;
}

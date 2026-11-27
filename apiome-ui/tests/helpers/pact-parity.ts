/**
 * The CLI ↔ UI parity gate for Pact (PFX-8.2, #7299): the readers and the check.
 *
 * Ten `apiome pact` commands once shipped with no screen because nothing compared the two. The
 * ledger (`docs/pact-parity-ledger.json`) names, for every `apiome pact` command, the page that does
 * the same, and for every Contracts write route, the command that does the same. Either side may be
 * missing only with a written reason.
 *
 * Sources:
 *   • the commands — `apiome-cli/pact-commands.json`, which apiome-cli renders from its Typer tree
 *     (and checks fresh in `tests/test_pact_command_list.py`);
 *   • the pages — every `page.tsx` under `src/app`, as its App Router route;
 *   • the write routes — every `POST` / `PUT` / `PATCH` / `DELETE` handler exported by a `route.ts`
 *     under `src/app/api/pact`.
 *
 * {@link checkParity} is pure so each failure path is tested on its own; the readers touch the disk.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/** The package root (`apiome-ui/`). */
export const PACKAGE_ROOT = join(__dirname, '..', '..');

/** The monorepo root. */
export const MONOREPO_ROOT = join(PACKAGE_ROOT, '..');

/** The ledger, relative to the monorepo root. */
export const LEDGER_FILE = join('docs', 'pact-parity-ledger.json');

/** The command list apiome-cli exports, relative to the monorepo root. */
export const COMMANDS_FILE = join('apiome-cli', 'pact-commands.json');

/** The App Router root. */
const APP_DIR = join(PACKAGE_ROOT, 'src', 'app');

/** Where the Contracts BFF routes live. */
const PACT_API_DIR = join(APP_DIR, 'api', 'pact');

/** The HTTP methods that change something. */
export const WRITE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE'] as const;

/** A reason shorter than this is not a reason ("n/a", "later"). */
export const MIN_REASON_LENGTH = 30;

/** One `apiome pact` command, as `pact-commands.json` lists it. */
export interface CliCommand {
  name: string;
  summary: string;
  arguments: string[];
  options: string[];
}

/** A ledger row for one command. */
export interface CommandRow {
  cli: string;
  ui: string | null;
  rest: string;
  reason?: string;
}

/** A ledger row for one write route. */
export interface WriteRouteRow {
  method: string;
  bff: string;
  rest: string;
  ui: string;
  cli: string | null;
  reason?: string;
}

/** The ledger file. */
export interface ParityLedger {
  commands: CommandRow[];
  writeRoutes: WriteRouteRow[];
}

/** One write handler found on disk: `POST /api/pact/publish`. */
export interface WriteHandler {
  method: string;
  bff: string;
}

/** Everything {@link checkParity} compares. */
export interface ParityInputs {
  ledger: ParityLedger;
  commands: CliCommand[];
  /** Every page route, e.g. `/ade/dashboard/pacts/webhooks/[webhookId]`. */
  pages: string[];
  writeHandlers: WriteHandler[];
}

/**
 * Read a JSON file under the monorepo root.
 *
 * @param path - Relative to {@link MONOREPO_ROOT}.
 * @returns The parsed document.
 */
function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(join(MONOREPO_ROOT, path), 'utf8')) as T;
}

/** @returns The committed ledger. */
export function readLedger(): ParityLedger {
  return readJson<ParityLedger>(LEDGER_FILE);
}

/** @returns The commands apiome-cli exported. */
export function readCliCommands(): CliCommand[] {
  return readJson<{ commands: CliCommand[] }>(COMMANDS_FILE).commands;
}

/**
 * Every file named `name` under `directory`, recursively.
 *
 * @param directory - Where to start.
 * @param name - The file name to find.
 * @returns Absolute paths.
 */
function filesNamed(directory: string, name: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) found.push(...filesNamed(path, name));
    else if (entry === name) found.push(path);
  }
  return found;
}

/**
 * The route a file under `src/app` serves: its folders, route groups `(name)` left out.
 *
 * @param file - An absolute `page.tsx` / `route.ts` path.
 * @returns E.g. `/ade/dashboard/pacts/webhooks`; `/` for the root page.
 */
export function routeOf(file: string): string {
  const folders = relative(APP_DIR, file).split(sep).slice(0, -1);
  const segments = folders.filter((segment) => !/^\(.+\)$/.test(segment));
  return `/${segments.join('/')}`;
}

/** @returns Every page route of the app. */
export function readPageRoutes(): string[] {
  return filesNamed(APP_DIR, 'page.tsx').map(routeOf).sort();
}

/**
 * The write methods a route module exports.
 *
 * @param source - The `route.ts` source.
 * @returns E.g. `['PUT', 'DELETE']`, in {@link WRITE_METHODS} order.
 */
export function exportedWriteMethods(source: string): string[] {
  return WRITE_METHODS.filter((method) =>
    new RegExp(`export\\s+(?:async\\s+)?(?:function\\s+${method}\\b|const\\s+${method}\\b)|export\\s*\\{[^}]*\\bas\\s+${method}\\b`).test(source),
  );
}

/** @returns Every write handler under `src/app/api/pact`. */
export function readWriteHandlers(): WriteHandler[] {
  return filesNamed(PACT_API_DIR, 'route.ts')
    .flatMap((file) => exportedWriteMethods(readFileSync(file, 'utf8')).map((method) => ({ method, bff: routeOf(file) })))
    .sort((a, b) => `${a.bff} ${a.method}`.localeCompare(`${b.bff} ${b.method}`));
}

/** @returns What the real gate compares. */
export function readParityInputs(): ParityInputs {
  return {
    ledger: readLedger(),
    commands: readCliCommands(),
    pages: readPageRoutes(),
    writeHandlers: readWriteHandlers(),
  };
}

/**
 * Whether a reason explains itself.
 *
 * @param reason - The ledger's `reason`.
 * @returns `true` for a sentence of at least {@link MIN_REASON_LENGTH} characters.
 */
function isReason(reason: string | undefined): boolean {
  return typeof reason === 'string' && reason.trim().length >= MIN_REASON_LENGTH;
}

/**
 * Names that appear more than once.
 *
 * @param names - The names.
 * @returns The repeated ones, once each.
 */
function repeated(names: string[]): string[] {
  return [...new Set(names.filter((name, index) => names.indexOf(name) !== index))];
}

/**
 * Compare the ledger with the CLI, the pages and the write routes.
 *
 * @param inputs - The ledger and what it describes.
 * @returns One sentence per problem, saying how to fix it; empty when the two sides agree.
 */
export function checkParity({ ledger, commands, pages, writeHandlers }: ParityInputs): string[] {
  const problems: string[] = [];
  const pageSet = new Set(pages);
  const commandNames = new Set(commands.map((command) => command.name));

  // --- every command has a row, and every row a command -------------------------------------------
  const rowNames = ledger.commands.map((row) => row.cli);
  for (const name of repeated(rowNames)) problems.push(`\`apiome pact ${name}\` has more than one ledger row.`);
  for (const name of commandNames) {
    if (!rowNames.includes(name)) {
      problems.push(`\`apiome pact ${name}\` has no ledger row: add it to commands with its screen, or ui: null and a reason.`);
    }
  }
  for (const row of ledger.commands) {
    if (!commandNames.has(row.cli)) {
      problems.push(`The ledger row for \`apiome pact ${row.cli}\` names a command the CLI does not have: remove it or regenerate apiome-cli/pact-commands.json.`);
    }
    if (!/^(GET|POST|PUT|PATCH|DELETE) \/v1\//.test(row.rest ?? '')) {
      problems.push(`The ledger row for \`apiome pact ${row.cli}\` needs its REST route as "METHOD /v1/…".`);
    }
    if (row.ui === null) {
      if (!isReason(row.reason)) {
        problems.push(`\`apiome pact ${row.cli}\` has no screen and no reason: name the page that does the same, or say why there is none.`);
      }
    } else {
      if (!pageSet.has(row.ui)) problems.push(`The ledger says \`apiome pact ${row.cli}\` is done on ${row.ui}, which is not a page.`);
      if (row.reason !== undefined) problems.push(`\`apiome pact ${row.cli}\` has a screen, so its reason is stale: remove it.`);
    }
  }

  // --- every write route has a row, and every row a write route -----------------------------------
  const key = (route: { method: string; bff: string }) => `${route.method} ${route.bff}`;
  const handlerKeys = new Set(writeHandlers.map(key));
  const writeKeys = ledger.writeRoutes.map(key);
  for (const name of repeated(writeKeys)) problems.push(`${name} has more than one ledger row.`);
  for (const handler of writeHandlers) {
    if (!writeKeys.includes(key(handler))) {
      problems.push(`${key(handler)} is a Contracts write route with no ledger row: add it to writeRoutes with its page and \`apiome pact\` command, or cli: null and a reason.`);
    }
  }
  for (const row of ledger.writeRoutes) {
    if (!handlerKeys.has(key(row))) {
      problems.push(`The ledger row for ${key(row)} names a write route the UI does not have: remove it.`);
    }
    if (!pageSet.has(row.ui)) problems.push(`The ledger says ${key(row)} is sent from ${row.ui}, which is not a page.`);
    if (!/^(POST|PUT|PATCH|DELETE) \/v1\//.test(row.rest ?? '')) {
      problems.push(`The ledger row for ${key(row)} needs its REST route as "METHOD /v1/…".`);
    }
    if (row.cli === null) {
      if (!isReason(row.reason)) {
        problems.push(`${key(row)} has no \`apiome pact\` command and no reason: name the command, or say why there is none.`);
      }
    } else {
      if (!commandNames.has(row.cli)) problems.push(`The ledger says ${key(row)} is \`apiome pact ${row.cli}\`, which the CLI does not have.`);
      if (row.reason !== undefined) problems.push(`${key(row)} has a command, so its reason is stale: remove it.`);
    }
  }

  return problems;
}

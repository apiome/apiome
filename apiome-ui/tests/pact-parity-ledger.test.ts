/**
 * The CLI ↔ UI parity gate for Pact (PFX-8.2, #7299).
 *
 * Fails CI when an `apiome pact` command has no ledger row, when a Contracts write route
 * (`POST` / `PUT` / `PATCH` / `DELETE` under `src/app/api/pact`) has no ledger row, or when either
 * side of a row is missing without a written reason. The ledger is `docs/pact-parity-ledger.json`;
 * the commands come from `apiome-cli/pact-commands.json`, which apiome-cli renders from Typer and
 * checks fresh in its own suite. Each failure path is tested on its own below, on small inputs.
 *
 * The command block's catalogue (`lib/pact-commands.ts` `PACT_VERBS`) is held against the same
 * ledger, so the REST route a block prints is the one the ledger names.
 */

import {
  checkParity,
  exportedWriteMethods,
  readParityInputs,
  routeOf,
  type CliCommand,
  type ParityInputs,
} from './helpers/pact-parity';
import { PACT_VERBS } from '../lib/pact-commands';
import { join } from 'node:path';

const REAL = readParityInputs();

describe('the parity ledger', () => {
  it('agrees with the CLI, the pages and the Contracts write routes', () => {
    expect(checkParity(REAL)).toEqual([]);
  });

  it('reads all fifteen commands and every Contracts write route', () => {
    expect(REAL.commands).toHaveLength(15);
    expect(REAL.writeHandlers.length).toBeGreaterThanOrEqual(13);
    expect(REAL.writeHandlers).toContainEqual({ method: 'POST', bff: '/api/pact/publish' });
    expect(REAL.writeHandlers).toContainEqual({ method: 'DELETE', bff: '/api/pact/webhooks/[webhookId]' });
  });

  it('names a reason for every command without a screen', () => {
    const missing = REAL.ledger.commands.filter((row) => row.ui === null).map((row) => row.cli);
    expect(missing.length).toBeGreaterThan(0);
    for (const row of REAL.ledger.commands.filter((r) => r.ui === null)) expect(row.reason).toMatch(/#\d+/);
  });

  it('is the catalogue the command block prints from', () => {
    expect(Object.keys(PACT_VERBS).sort()).toEqual(REAL.commands.map((command) => command.name).sort());
    for (const row of REAL.ledger.commands) expect(PACT_VERBS[row.cli]?.rest).toBe(row.rest);
  });
});

/** A small, agreeing world the failure paths each break one way. */
function world(): ParityInputs {
  const commands: CliCommand[] = [
    { name: 'publish', summary: '', arguments: [], options: [] },
    { name: 'verify', summary: '', arguments: [], options: [] },
  ];
  return {
    commands,
    pages: ['/ade/dashboard/pacts/webhooks', '/ade/dashboard/pacts/publish'],
    writeHandlers: [
      { method: 'POST', bff: '/api/pact/publish' },
      { method: 'DELETE', bff: '/api/pact/webhooks/[webhookId]' },
    ],
    ledger: {
      commands: [
        { cli: 'publish', ui: '/ade/dashboard/pacts/publish', rest: 'POST /v1/tenants/{tenant}/pact-broker/contracts/publish' },
        {
          cli: 'verify',
          ui: null,
          rest: 'POST /v1/tenants/{tenant}/pact-verifier/pacts/provider/{provider}/verify',
          reason: 'The Run a verification page ships with PFX-8.8 (#7305).',
        },
      ],
      writeRoutes: [
        {
          method: 'POST',
          bff: '/api/pact/publish',
          rest: 'POST /v1/tenants/{tenant}/pact-broker/contracts/publish',
          ui: '/ade/dashboard/pacts/publish',
          cli: 'publish',
        },
        {
          method: 'DELETE',
          bff: '/api/pact/webhooks/[webhookId]',
          rest: 'DELETE /v1/tenants/{tenant}/pact-broker/webhooks/{webhook}',
          ui: '/ade/dashboard/pacts/webhooks',
          cli: null,
          reason: 'Pact CLI has no delete-webhook command and apiome pact follows it.',
        },
      ],
    },
  };
}

describe('each failure path', () => {
  it('passes the agreeing world', () => {
    expect(checkParity(world())).toEqual([]);
  });

  it('fails a new CLI command without a ledger row', () => {
    const inputs = world();
    inputs.commands.push({ name: 'record-undeployment', summary: '', arguments: [], options: [] });
    expect(checkParity(inputs)).toEqual([expect.stringContaining('`apiome pact record-undeployment` has no ledger row')]);
  });

  it('fails a ledger row for a command the CLI does not have', () => {
    const inputs = world();
    inputs.commands = inputs.commands.filter((command) => command.name !== 'verify');
    expect(checkParity(inputs)).toEqual([expect.stringContaining('names a command the CLI does not have')]);
  });

  it('fails a command row with neither a screen nor a reason', () => {
    const inputs = world();
    delete inputs.ledger.commands[1].reason;
    expect(checkParity(inputs)).toEqual([expect.stringContaining('`apiome pact verify` has no screen and no reason')]);
  });

  it('fails a reason too short to explain anything', () => {
    const inputs = world();
    inputs.ledger.commands[1].reason = 'later';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('no screen and no reason')]);
  });

  it('fails a screen that is not a page', () => {
    const inputs = world();
    inputs.ledger.commands[0].ui = '/ade/dashboard/pacts/nowhere';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('/ade/dashboard/pacts/nowhere, which is not a page')]);
  });

  it('fails a stale reason on a row that has its screen', () => {
    const inputs = world();
    inputs.ledger.commands[0].reason = 'This one used to be CLI-only, until PFX-8.3.';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('its reason is stale')]);
  });

  it('fails a command listed twice', () => {
    const inputs = world();
    inputs.ledger.commands.push({ ...inputs.ledger.commands[0] });
    expect(checkParity(inputs)).toEqual([expect.stringContaining('more than one ledger row')]);
  });

  it('fails a REST route that is not "METHOD /v1/…"', () => {
    const inputs = world();
    inputs.ledger.commands[0].rest = '/contracts/publish';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('needs its REST route')]);
  });

  it('fails a new Contracts write route without a ledger row', () => {
    const inputs = world();
    inputs.writeHandlers.push({ method: 'POST', bff: '/api/pact/environments' });
    expect(checkParity(inputs)).toEqual([
      expect.stringContaining('POST /api/pact/environments is a Contracts write route with no ledger row'),
    ]);
  });

  it('fails a write route row for a handler that is gone', () => {
    const inputs = world();
    inputs.writeHandlers = inputs.writeHandlers.slice(0, 1);
    expect(checkParity(inputs)).toEqual([expect.stringContaining('names a write route the UI does not have')]);
  });

  it('fails a write route with neither a command nor a reason', () => {
    const inputs = world();
    delete inputs.ledger.writeRoutes[1].reason;
    expect(checkParity(inputs)).toEqual([expect.stringContaining('has no `apiome pact` command and no reason')]);
  });

  it('fails a write route that names a command the CLI does not have', () => {
    const inputs = world();
    inputs.ledger.writeRoutes[0].cli = 'publish-everything';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('`apiome pact publish-everything`, which the CLI does not have')]);
  });

  it('fails a write route sent from a page that does not exist', () => {
    const inputs = world();
    inputs.ledger.writeRoutes[0].ui = '/ade/dashboard/pacts/gone';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('is sent from /ade/dashboard/pacts/gone, which is not a page')]);
  });

  it('fails a stale reason on a write route that has its command', () => {
    const inputs = world();
    inputs.ledger.writeRoutes[0].reason = 'There used to be no command for publishing a pact.';
    expect(checkParity(inputs)).toEqual([expect.stringContaining('has a command, so its reason is stale')]);
  });

  it('fails a write route listed twice', () => {
    const inputs = world();
    inputs.ledger.writeRoutes.push({ ...inputs.ledger.writeRoutes[0] });
    expect(checkParity(inputs)).toEqual([expect.stringContaining('POST /api/pact/publish has more than one ledger row')]);
  });
});

describe('the readers', () => {
  it('finds every exported write handler, whatever form the export takes', () => {
    expect(exportedWriteMethods('export async function POST(request) {}\nexport function GET() {}')).toEqual(['POST']);
    expect(exportedWriteMethods('export const PUT = handler;\nexport async function DELETE() {}')).toEqual(['PUT', 'DELETE']);
    expect(exportedWriteMethods('const handler = () => null;\nexport { handler as PATCH };')).toEqual(['PATCH']);
    expect(exportedWriteMethods('export async function GET() {} // POST is not here')).toEqual([]);
  });

  it('reads a route from its folders, route groups left out', () => {
    const app = join(__dirname, '..', 'src', 'app');
    expect(routeOf(join(app, 'ade', 'dashboard', 'pacts', 'webhooks', 'page.tsx'))).toBe('/ade/dashboard/pacts/webhooks');
    expect(routeOf(join(app, '(marketing)', 'pricing', 'page.tsx'))).toBe('/pricing');
    expect(routeOf(join(app, 'page.tsx'))).toBe('/');
  });
});

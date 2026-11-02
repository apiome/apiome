/**
 * "From a registry" in the Add MCP server dialog — the pure rules (AAU-5.4, #5725).
 *
 * The form validation, the `mcp-registry` connector draft and credential, the run summary, the
 * Done-step headline, the MCP form's registry mode and the footer's verb.
 */

import {
  MCP_REGISTRY_CONNECTOR_KIND,
  REGISTRY_SYNC_SECONDS,
  buildRegistryConnectorDraft,
  buildRegistryCredentials,
  emptyMcpRegistryForm,
  registryRunFailed,
  splitDiscoveredReason,
  summarizeRegistryRun,
  validateMcpRegistryForm,
  type McpRegistryForm,
} from '@/app/components/ade/dashboard/mcp/mcpRegistryImport';
import { emptyMcpImportForm, validateMcpImportForm } from '@/app/components/ade/dashboard/mcp/mcpImportFlow';
import { registryImportHeadline } from '@/app/components/ade/import/McpRegistryImportDonePanel';
import { importFooterFor } from '@/app/components/ade/import/importWizardModel';

const form = (overrides: Partial<McpRegistryForm> = {}): McpRegistryForm => ({
  ...emptyMcpRegistryForm(),
  registryUrl: 'https://registry.modelcontextprotocol.io',
  ...overrides,
});

describe('validateMcpRegistryForm', () => {
  it('accepts an http(s) registry URL with no credential', () => {
    expect(validateMcpRegistryForm(form())).toBeNull();
  });

  it.each([
    [{ registryUrl: '' }, 'Enter the registry URL.'],
    [{ registryUrl: 'not a url' }, 'Enter a valid registry URL (including https://).'],
    [{ registryUrl: 'ftp://registry.test' }, 'The registry URL must start with http:// or https://.'],
    [{ credentialType: 'token' as const, credential: ' ' }, 'Enter the bearer token.'],
    [{ credentialType: 'apiKey' as const }, 'Enter the Apiome workspace API key.'],
  ])('refuses %j', (overrides, message) => {
    expect(validateMcpRegistryForm(form(overrides))).toBe(message);
  });
});

describe('buildRegistryConnectorDraft', () => {
  it('names the connector after the host and search and schedules a daily sync', () => {
    expect(buildRegistryConnectorDraft(form({ registryUrl: ' https://apiome.example/registry/mcp/acme ', search: ' io.github.acme ' }))).toEqual({
      kind: MCP_REGISTRY_CONNECTOR_KIND,
      name: 'MCP registry · apiome.example · io.github.acme',
      baseUrl: 'https://apiome.example/registry/mcp/acme',
      scope: { search: 'io.github.acme' },
      refreshIntervalSeconds: REGISTRY_SYNC_SECONDS,
      conflictPolicy: 'hold-for-review',
    });
  });

  it('leaves the scope empty and the cadence unset when asked', () => {
    const draft = buildRegistryConnectorDraft(form({ keepInSync: false }));
    expect(draft.scope).toEqual({});
    expect(draft.refreshIntervalSeconds).toBeNull();
    expect(draft.name).toBe('MCP registry · registry.modelcontextprotocol.io');
  });
});

describe('buildRegistryCredentials', () => {
  it('sends a bearer token, an Apiome API key, or nothing', () => {
    expect(buildRegistryCredentials(form({ credentialType: 'token', credential: ' t0k ' }))).toEqual({ token: 't0k' });
    expect(buildRegistryCredentials(form({ credentialType: 'apiKey', credential: 'k' }))).toEqual({ apiKey: 'k' });
    expect(buildRegistryCredentials(form({ credentialType: 'none', credential: 'ignored' }))).toBeNull();
  });
});

describe('summarizeRegistryRun', () => {
  const run = {
    id: 'r1',
    status: 'succeeded',
    errorClass: null,
    httpStatus: null,
    errorMessage: null,
    summary: {
      candidates: 5,
      imported: 2,
      discovered: 3,
      failed: 0,
      discoveredItems: [
        { remoteId: 'io.github.acme/local', reason: 'no-remote: the server lists only packages' },
        { remoteId: 'io.github.acme/internal', reason: 'remote-refused: private address' },
        { notAnEntry: true },
      ],
    },
  };

  it('reads the counts and the entries left discovered', () => {
    expect(summarizeRegistryRun(run)).toEqual({
      status: 'succeeded',
      listed: 5,
      imported: 2,
      discovered: 3,
      failed: 0,
      discoveredEntries: [
        { remoteId: 'io.github.acme/local', reason: 'no-remote: the server lists only packages' },
        { remoteId: 'io.github.acme/internal', reason: 'remote-refused: private address' },
      ],
      error: null,
    });
    expect(registryRunFailed(run)).toBe(false);
    expect(registryRunFailed({ ...run, status: 'failed' })).toBe(true);
  });

  it('copes with a run that carries no summary', () => {
    expect(summarizeRegistryRun({ ...run, summary: {} }).listed).toBe(0);
  });
});

describe('splitDiscoveredReason', () => {
  it('separates the stable code from its explanation', () => {
    expect(splitDiscoveredReason('remote-templated: the remote needs {tenant}')).toEqual({
      code: 'remote-templated',
      detail: 'the remote needs {tenant}',
    });
    expect(splitDiscoveredReason('plain text')).toEqual({ code: '', detail: 'plain text' });
  });
});

describe('registryImportHeadline', () => {
  const base = { status: 'succeeded', listed: 3, imported: 2, discovered: 1, failed: 0, discoveredEntries: [], error: null };

  it('counts what was imported and what is left', () => {
    expect(registryImportHeadline(base)).toEqual({
      title: '2 servers imported from the registry',
      description:
        'The registry listed 3 servers. 2 servers were added to MCP Servers, discovered and graded; 1 server could not be added yet (below).',
    });
    expect(registryImportHeadline({ ...base, listed: 1, imported: 1, discovered: 0 }).description).toBe(
      'The registry listed 1 server. 1 server was added to MCP Servers, discovered and graded.'
    );
  });

  it('says when nothing could be added, and when nothing matched', () => {
    expect(registryImportHeadline({ ...base, imported: 0, discovered: 3 }).title).toBe('No servers could be added yet');
    expect(registryImportHeadline({ ...base, listed: 0, imported: 0, discovered: 0 }).title).toBe(
      'The registry listed no servers'
    );
  });
});

describe('the MCP form in registry mode', () => {
  it('starts on one server and validates the registry half in registry mode', () => {
    const mcp = emptyMcpImportForm();
    expect(mcp.mode).toBe('server');
    expect(validateMcpImportForm({ ...mcp, mode: 'registry' })).toBe('Enter the registry URL.');
    expect(validateMcpImportForm({ ...mcp, mode: 'registry', registry: form() })).toBeNull();
  });

  it("names the footer's verb for a registry import", () => {
    const footer = (mcpSubmitting: boolean) =>
      importFooterFor({ step: 'file-upload', source: 'mcp', importComplete: false, importSucceeded: false, mcpReady: true, mcpSubmitting, mcpRegistry: true }).primary;
    expect(footer(false)).toEqual({ label: 'Import servers →', disabled: false });
    expect(footer(true)).toEqual({ label: 'Importing servers…', disabled: true });
  });
});

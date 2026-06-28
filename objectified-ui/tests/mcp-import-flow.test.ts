/**
 * Unit tests for the MCP "import source" pure helpers (V2-MCP-24.1 / MCAT-10.1, #3697).
 *
 * Covers form validation, request-body building (create + credential), name derivation, and the
 * discovery-job interpretation helpers the Import dialog and discovery panel rely on.
 */

import {
  buildCreateEndpointBody,
  buildCredentialBody,
  deriveEndpointNameFromUrl,
  discoveryFailureMessage,
  discoveryStatusLabel,
  discoverySummary,
  emptyMcpImportForm,
  isJobSuccess,
  isTerminalJobState,
  validateMcpEndpointUrl,
  validateMcpImportForm,
  versionIdFromJob,
  type McpImportForm,
} from '../src/app/components/ade/dashboard/mcp/mcpImportFlow';

const form = (overrides: Partial<McpImportForm> = {}): McpImportForm => ({
  ...emptyMcpImportForm(),
  ...overrides,
});

describe('emptyMcpImportForm', () => {
  it('defaults to streamable_http transport and no auth', () => {
    const f = emptyMcpImportForm();
    expect(f.transport).toBe('streamable_http');
    expect(f.authType).toBe('none');
    expect(f.endpointUrl).toBe('');
  });
});

describe('deriveEndpointNameFromUrl', () => {
  it('uses the URL host', () => {
    expect(deriveEndpointNameFromUrl('https://mcp.example.com/sse')).toBe('mcp.example.com');
  });

  it('falls back to the trimmed raw value when unparseable', () => {
    expect(deriveEndpointNameFromUrl('  not a url  ')).toBe('not a url');
  });

  it('falls back to a generic name when blank', () => {
    expect(deriveEndpointNameFromUrl('   ')).toBe('MCP Server');
  });
});

describe('validateMcpEndpointUrl', () => {
  it('requires a non-blank URL', () => {
    expect(validateMcpEndpointUrl('   ', 'streamable_http')).toMatch(/endpoint URL/i);
  });

  it('requires http(s) for HTTP transports', () => {
    expect(validateMcpEndpointUrl('ftp://x/y', 'streamable_http')).toMatch(/http/i);
    expect(validateMcpEndpointUrl('not a url', 'sse')).toMatch(/valid URL/i);
  });

  it('accepts a valid https URL and any non-blank stdio target', () => {
    expect(validateMcpEndpointUrl('https://mcp.example.com/sse', 'sse')).toBeNull();
    expect(validateMcpEndpointUrl('python -m my_server', 'stdio')).toBeNull();
  });
});

describe('validateMcpImportForm', () => {
  it('requires an endpoint URL', () => {
    expect(validateMcpImportForm(form({ endpointUrl: '' }))).toMatch(/endpoint URL/i);
  });

  it('requires http(s) for HTTP transports', () => {
    expect(validateMcpImportForm(form({ endpointUrl: 'ftp://x/y', transport: 'streamable_http' }))).toMatch(
      /http/i,
    );
    expect(validateMcpImportForm(form({ endpointUrl: 'not a url', transport: 'sse' }))).toMatch(/valid URL/i);
  });

  it('accepts any non-blank target for stdio (no URL parse)', () => {
    expect(validateMcpImportForm(form({ endpointUrl: 'my-server-cmd', transport: 'stdio' }))).toBeNull();
  });

  it('accepts a valid https endpoint with no auth', () => {
    expect(validateMcpImportForm(form({ endpointUrl: 'https://mcp.example.com/sse' }))).toBeNull();
  });

  it('requires a token for bearer / oauth2', () => {
    expect(
      validateMcpImportForm(form({ endpointUrl: 'https://x/y', authType: 'bearer', authToken: '' })),
    ).toMatch(/token/i);
    expect(
      validateMcpImportForm(form({ endpointUrl: 'https://x/y', authType: 'oauth2', authToken: '  ' })),
    ).toMatch(/token/i);
  });

  it('requires both name and value for header auth', () => {
    expect(
      validateMcpImportForm(form({ endpointUrl: 'https://x/y', authType: 'header', authHeaderName: '', authToken: 'v' })),
    ).toMatch(/header name/i);
    expect(
      validateMcpImportForm(form({ endpointUrl: 'https://x/y', authType: 'header', authHeaderName: 'X-Key', authToken: '' })),
    ).toMatch(/header value/i);
    expect(
      validateMcpImportForm(form({ endpointUrl: 'https://x/y', authType: 'header', authHeaderName: 'X-Key', authToken: 'secret' })),
    ).toBeNull();
  });
});

describe('buildCreateEndpointBody', () => {
  it('uses the supplied name and trims fields', () => {
    expect(buildCreateEndpointBody(form({ endpointUrl: '  https://x/y  ', name: '  My Server  ' }))).toEqual({
      name: 'My Server',
      endpoint_url: 'https://x/y',
      transport: 'streamable_http',
      visibility: 'private',
    });
  });

  it('derives the name from the host when blank', () => {
    expect(buildCreateEndpointBody(form({ endpointUrl: 'https://mcp.example.com/sse', name: '' })).name).toBe(
      'mcp.example.com',
    );
  });
});

describe('buildCredentialBody', () => {
  it('returns null for anonymous (none)', () => {
    expect(buildCredentialBody(form({ authType: 'none' }))).toBeNull();
  });

  it('builds a bearer payload', () => {
    expect(buildCredentialBody(form({ authType: 'bearer', authToken: ' tok ' }))).toEqual({
      auth_type: 'bearer',
      payload: { token: 'tok' },
    });
  });

  it('builds an oauth2 payload', () => {
    expect(buildCredentialBody(form({ authType: 'oauth2', authToken: 'at' }))).toEqual({
      auth_type: 'oauth2',
      payload: { access_token: 'at' },
    });
  });

  it('builds a custom header payload', () => {
    expect(
      buildCredentialBody(form({ authType: 'header', authHeaderName: ' X-Key ', authToken: ' v ' })),
    ).toEqual({
      auth_type: 'header',
      payload: { name: 'X-Key', value: 'v' },
    });
  });
});

describe('discovery job helpers', () => {
  it('classifies terminal states', () => {
    expect(isTerminalJobState('completed')).toBe(true);
    expect(isTerminalJobState('failed')).toBe(true);
    expect(isTerminalJobState('queued')).toBe(false);
    expect(isTerminalJobState('running')).toBe(false);
    expect(isTerminalJobState(undefined)).toBe(false);
  });

  it('detects success only on completed', () => {
    expect(isJobSuccess({ id: 'j', endpoint_id: 'e', state: 'completed' })).toBe(true);
    expect(isJobSuccess({ id: 'j', endpoint_id: 'e', state: 'failed' })).toBe(false);
    expect(isJobSuccess(null)).toBe(false);
  });

  it('extracts the version id from a completed job', () => {
    expect(
      versionIdFromJob({ id: 'j', endpoint_id: 'e', state: 'completed', result: { version_id: 'v1' } }),
    ).toBe('v1');
    expect(versionIdFromJob({ id: 'j', endpoint_id: 'e', state: 'completed', result: {} })).toBeNull();
    expect(versionIdFromJob(null)).toBeNull();
  });

  it('labels each state for the live status line', () => {
    expect(discoveryStatusLabel('queued')).toMatch(/queued/i);
    expect(discoveryStatusLabel('running')).toMatch(/discovering/i);
    expect(discoveryStatusLabel('completed')).toMatch(/complete/i);
    expect(discoveryStatusLabel('failed')).toMatch(/failed/i);
    expect(discoveryStatusLabel(undefined)).toMatch(/starting/i);
  });

  it('surfaces the job error (or a generic fallback) on failure', () => {
    expect(
      discoveryFailureMessage({ id: 'j', endpoint_id: 'e', state: 'failed', error: 'auth_failed: 401' }),
    ).toBe('auth_failed: 401');
    expect(discoveryFailureMessage({ id: 'j', endpoint_id: 'e', state: 'failed', error: '   ' })).toMatch(
      /could not be discovered/i,
    );
    expect(discoveryFailureMessage({ id: 'j', endpoint_id: 'e', state: 'failed' })).toMatch(
      /could not be discovered/i,
    );
    expect(discoveryFailureMessage(null)).toMatch(/could not be discovered/i);
  });

  describe('discoverySummary', () => {
    const completed = (counts: Record<string, number>) => ({
      id: 'j',
      endpoint_id: 'e',
      state: 'completed',
      result: { version_id: 'v1', counts },
    });

    it('summarizes non-zero capability kinds, joined with a middot', () => {
      expect(discoverySummary(completed({ tool: 3, resource: 2, prompt: 1, total: 6 }))).toBe(
        '3 tools · 2 resources · 1 prompt',
      );
    });

    it('pluralizes per kind and labels resource templates', () => {
      expect(discoverySummary(completed({ tool: 1, resource_template: 2 }))).toBe(
        '1 tool · 2 resource templates',
      );
    });

    it('omits zero-count kinds', () => {
      expect(discoverySummary(completed({ tool: 2, resource: 0, prompt: 0 }))).toBe('2 tools');
    });

    it('reports an empty surface when nothing was exposed', () => {
      expect(discoverySummary(completed({ tool: 0, resource: 0, prompt: 0, total: 0 }))).toMatch(
        /no capabilities/i,
      );
    });

    it('returns null when the job carried no counts (so the line is omitted)', () => {
      expect(discoverySummary({ id: 'j', endpoint_id: 'e', state: 'completed', result: {} })).toBeNull();
      expect(discoverySummary(null)).toBeNull();
    });
  });
});

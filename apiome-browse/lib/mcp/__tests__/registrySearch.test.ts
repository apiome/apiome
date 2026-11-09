import { describe, expect, it, vi } from 'vitest';
import {
  federateRegistryEntries,
  fetchRegistryServers,
  mcpSearchHref,
  normalizeRegistryBase,
  parseRegistryEntry,
  parseRegistryServers,
  registryQuery,
  registryRemoteHosts,
  toClientEntry,
  urlKey,
  type McpRegistryEntry,
} from '../registrySearch';

/**
 * Federated public MCP search incl. the MCP registry (V2-MCP-26.4 / MCAT-12.4, #3710): reading the
 * registry, deduping its entries against published endpoints, and the search URL.
 */

const OFFICIAL = 'io.modelcontextprotocol.registry/official';

function element(name: string, extra: Record<string, unknown> = {}, status = 'active') {
  return { server: { name, description: `${name} server`, version: '1.0.0', ...extra }, _meta: { [OFFICIAL]: { status } } };
}

function entry(name: string, url?: string): McpRegistryEntry {
  const parsed = parseRegistryEntry(element(name, url ? { remotes: [{ type: 'streamable-http', url }] } : {}));
  if (!parsed) throw new Error('fixture did not parse');
  return parsed;
}

describe('registryQuery', () => {
  it.each([
    ['weather', 'weather'],
    ['"weather alerts"', 'weather alerts'],
    ['weather -beta', 'weather'],
    ['weather OR forecast', 'weather forecast'],
    ['-only', ''],
  ])('%s → %s', (query, expected) => {
    expect(registryQuery(query)).toBe(expected);
  });
});

describe('normalizeRegistryBase', () => {
  it('drops a trailing slash and the v0.1 suffixes', () => {
    expect(normalizeRegistryBase('https://r.example/')).toBe('https://r.example');
    expect(normalizeRegistryBase('https://r.example/v0.1')).toBe('https://r.example');
    expect(normalizeRegistryBase('https://r.example/v0.1/servers/')).toBe('https://r.example');
    expect(normalizeRegistryBase('  ')).toBe('');
  });
});

describe('urlKey', () => {
  it.each([
    ['https://MCP.Acme.example/mcp/', 'https://mcp.acme.example/mcp'],
    ['https://user:secret@mcp.acme.example/mcp?x=1#f', 'https://mcp.acme.example/mcp'],
    ['https://mcp.acme.example:8443/sse', 'https://mcp.acme.example:8443/sse'],
    ['https://mcp.acme.example', 'https://mcp.acme.example'],
    ['stdio://local', null],
    ['not a url', null],
    [null, null],
  ])('%s → %s', (url, expected) => {
    expect(urlKey(url)).toBe(expected);
  });
});

describe('parseRegistryEntry', () => {
  it('reads the v0.1 shape and picks the first concrete http remote', () => {
    const parsed = parseRegistryEntry(
      element('io.github.acme/weather', {
        title: 'Acme Weather',
        websiteUrl: 'https://acme.example/docs?ref=x',
        remotes: [
          { type: 'sse', url: 'https://{tenant}.acme.example/sse' },
          { type: 'streamable-http', url: 'https://tok:secret@mcp.acme.example/mcp?key=1' },
        ],
      }, 'deprecated')
    );
    expect(parsed).toMatchObject({
      source: 'registry',
      serverName: 'io.github.acme/weather',
      title: 'Acme Weather',
      version: '1.0.0',
      status: 'deprecated',
      websiteUrl: 'https://acme.example/docs',
      remoteUrl: 'https://mcp.acme.example/mcp',
      transport: 'streamable_http',
      host: 'mcp.acme.example',
      remoteKeys: ['https://mcp.acme.example/mcp'],
    });
    expect(JSON.stringify(parsed)).not.toContain('secret');
  });

  it('reads the flat snake_case draft shape', () => {
    const parsed = parseRegistryEntry({
      name: 'io.github.acme/flat',
      website_url: 'https://acme.example',
      remotes: [{ transport_type: 'sse', url: 'https://flat.acme.example/sse' }],
    });
    expect(parsed?.transport).toBe('sse');
    expect(parsed?.websiteUrl).toBe('https://acme.example/');
  });

  it('leaves a package-only server without a remote', () => {
    const parsed = parseRegistryEntry(element('io.github.acme/local', { packages: [{ identifier: 'x' }] }));
    expect(parsed?.remoteUrl).toBeNull();
    expect(parsed?.host).toBeNull();
    expect(parsed?.remoteKeys).toEqual([]);
  });

  it('skips deleted, nameless and non-object elements', () => {
    expect(parseRegistryEntry(element('io.github.acme/gone', {}, 'deleted'))).toBeNull();
    expect(parseRegistryEntry({ server: { description: 'no name' } })).toBeNull();
    expect(parseRegistryEntry('nope')).toBeNull();
  });
});

describe('parseRegistryServers', () => {
  it('keeps readable entries in order', () => {
    const out = parseRegistryServers({ servers: [element('a.b/one'), 42, element('a.b/two')] });
    expect(out.map((e) => e.serverName)).toEqual(['a.b/one', 'a.b/two']);
  });

  it('rejects a body with no servers list', () => {
    expect(() => parseRegistryServers({ items: [] })).toThrow(/no servers list/);
  });
});

describe('fetchRegistryServers', () => {
  it('sends search, limit and version=latest to /v0.1/servers', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ servers: [element('io.github.acme/weather')] })));
    const out = await fetchRegistryServers('weather', {
      baseUrl: 'https://r.example/v0.1',
      limit: 5,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(out).toHaveLength(1);
    const url = new URL(String((fetchImpl.mock.calls[0] as unknown[])[0]));
    expect(url.origin + url.pathname).toBe('https://r.example/v0.1/servers');
    expect(url.searchParams.get('search')).toBe('weather');
    expect(url.searchParams.get('limit')).toBe('5');
    expect(url.searchParams.get('version')).toBe('latest');
  });

  it('skips the call for a blank term', async () => {
    const fetchImpl = vi.fn();
    expect(await fetchRegistryServers('  ', { baseUrl: 'https://r.example', fetchImpl })).toEqual([]);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('throws on a non-2xx answer', async () => {
    const fetchImpl = vi.fn(async () => new Response('down', { status: 503 }));
    await expect(
      fetchRegistryServers('weather', { baseUrl: 'https://r.example', fetchImpl: fetchImpl as unknown as typeof fetch })
    ).rejects.toThrow(/HTTP 503/);
  });
});

describe('federateRegistryEntries', () => {
  it('dedupes by registry name, case-insensitively, and labels the endpoint', () => {
    const out = federateRegistryEntries(
      [entry('io.github.Acme/Weather', 'https://elsewhere.example/mcp')],
      [{ endpoint_id: 'ep-1', registry_server_name: 'io.github.acme/weather', endpoint_url: 'https://x.example/mcp' }]
    );
    expect(out.entries).toEqual([]);
    expect(out.duplicates).toBe(1);
    expect(out.serverNameByEndpoint).toEqual({ 'ep-1': 'io.github.acme/weather' });
  });

  it('dedupes by remote URL and labels a hand-added endpoint with the entry name', () => {
    const out = federateRegistryEntries(
      [entry('io.github.acme/weather', 'https://mcp.acme.example/mcp/')],
      [{ endpoint_id: 'ep-9', registry_server_name: null, endpoint_url: 'https://u:p@MCP.acme.example/mcp' }]
    );
    expect(out.entries).toEqual([]);
    expect(out.duplicates).toBe(1);
    expect(out.serverNameByEndpoint).toEqual({ 'ep-9': 'io.github.acme/weather' });
  });

  it('keeps entries the catalog does not have, in registry order', () => {
    const out = federateRegistryEntries(
      [entry('io.github.b/two', 'https://b.example/mcp'), entry('io.github.a/one', 'https://a.example/mcp')],
      [{ endpoint_id: 'ep-1', registry_server_name: null, endpoint_url: 'https://b.example/other' }]
    );
    expect(out.entries.map((e) => e.serverName)).toEqual(['io.github.b/two', 'io.github.a/one']);
    expect(out.duplicates).toBe(0);
    expect(out.serverNameByEndpoint).toEqual({});
  });

  it('labels a registry import even when its entry is not in the results', () => {
    const out = federateRegistryEntries(
      [],
      [{ endpoint_id: 'ep-3', registry_server_name: 'io.github.x/tool', endpoint_url: 'https://x.example/mcp' }]
    );
    expect(out.serverNameByEndpoint).toEqual({ 'ep-3': 'io.github.x/tool' });
  });
});

describe('registryRemoteHosts / toClientEntry', () => {
  it('collects distinct lower-case remote hosts', () => {
    expect(
      registryRemoteHosts([entry('a.b/one', 'https://B.example/mcp'), entry('a.b/two', 'https://a.example/x'), entry('a.b/three')])
    ).toEqual(['a.example', 'b.example']);
  });

  it('strips the server-only dedupe keys', () => {
    const client = toClientEntry(entry('a.b/one', 'https://a.example/mcp'));
    expect('remoteKeys' in client).toBe(false);
    expect(client.serverName).toBe('a.b/one');
  });
});

describe('mcpSearchHref', () => {
  it('carries the query, a pinned sort and the registry toggle', () => {
    expect(mcpSearchHref(' weather ', null, false)).toBe('/mcp/search?q=weather');
    expect(mcpSearchHref('weather', 'top_graded', true)).toBe('/mcp/search?q=weather&sort=top_graded&registry=1');
  });
});

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { ToolSchema } from '@modelcontextprotocol/sdk/types.js';

import { ActionRegistry } from '../src/registry/index.js';
import { createObjectifiedMcpServer } from '../src/server.js';
import { RestClient } from '../src/upstream/client.js';

describe('objectified-mcp server bootstrap', () => {
  it('handshakes over in-memory transport and reports serverInfo + capabilities', async (t) => {
    const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
    const registry = ActionRegistry.instance();
    const upstream = RestClient.withBaseUrl('http://127.0.0.1:8000');
    const server = createObjectifiedMcpServer(registry, upstream);

    const client = new Client({ name: 'test-harness', version: '0.0.0' }, { capabilities: {} });

    await Promise.all([server.connect(serverSide), client.connect(clientSide)]);

    t.after(async () => {
      await client.close();
      await server.close();
    });

    const version = client.getServerVersion();
    assert.ok(version);
    assert.equal(version?.name, 'objectified-mcp');
    assert.ok(version?.version && version.version.length > 0);

    const caps = client.getServerCapabilities();
    assert.ok(caps?.tools);
    assert.ok(caps?.resources);
    assert.ok(caps?.prompts);
    assert.ok(caps?.logging);
  });

  it('exposes the three primitive tools with Tool-shaped JSON schemas', async (t) => {
    const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
    const registry = ActionRegistry.instance();
    const upstream = RestClient.withBaseUrl('http://127.0.0.1:8000');
    const server = createObjectifiedMcpServer(registry, upstream);
    const client = new Client({ name: 'test-harness', version: '0.0.0' }, { capabilities: {} });

    await Promise.all([server.connect(serverSide), client.connect(clientSide)]);

    t.after(async () => {
      await client.close();
      await server.close();
    });

    const { tools } = await client.listTools();
    assert.equal(tools.length, 3);

    const names = tools.map((t) => t.name).sort();
    assert.deepEqual(names, ['mcp.describe', 'mcp.execute', 'mcp.search']);

    for (const tool of tools) {
      const parsed = ToolSchema.safeParse(tool);
      assert.ok(parsed.success, JSON.stringify(parsed.error?.format(), null, 2));
    }
  });

  it('closes cleanly after lifecycle', async () => {
    const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
    const registry = ActionRegistry.instance();
    const upstream = RestClient.withBaseUrl('http://127.0.0.1:8000');
    const server = createObjectifiedMcpServer(registry, upstream);
    const client = new Client({ name: 'test-harness', version: '0.0.0' }, { capabilities: {} });

    await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
    await client.close();
    await server.close();

    assert.equal(server.isConnected(), false);
  });
});

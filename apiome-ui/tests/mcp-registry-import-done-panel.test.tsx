/**
 * The MCP registry import's done panel (AAU-5.4, #5725) now that Connectors are released (RC8).
 *
 * The panel always offers both ways on: **View MCP servers** and **Open the connector**, the
 * `mcp-registry` connector the import registered and that keeps the servers in sync. Before RC8 the
 * connector link was left out while the Connectors pages were held back.
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { McpRegistryImportDonePanel } from '@/app/components/ade/import/McpRegistryImportDonePanel';
import type { RegistryImportSummary } from '@/app/components/ade/dashboard/mcp/mcpRegistryImport';

const SUMMARY: RegistryImportSummary = {
  status: 'succeeded',
  listed: 3,
  imported: 2,
  discovered: 1,
  failed: 0,
  discoveredEntries: [{ remoteId: 'io.example/local-only', reason: 'no-remote: packages only' }],
  error: null,
};

describe('McpRegistryImportDonePanel', () => {
  const ORIGINAL = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  });

  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = ORIGINAL;
  });

  it('links to the MCP servers and to the connector it registered, with no preview override', () => {
    render(<McpRegistryImportDonePanel connectorId="conn 1" summary={SUMMARY} onNavigate={() => undefined} />);

    expect(screen.getByRole('link', { name: /View MCP servers/ })).toHaveAttribute('href', '/ade/dashboard/mcp');
    expect(screen.getByRole('link', { name: /Open the connector/ })).toHaveAttribute(
      'href',
      '/ade/dashboard/connectors/conn%201'
    );
  });

  it('settles the dialog before following the connector link', () => {
    const onNavigate = jest.fn();
    render(<McpRegistryImportDonePanel connectorId="c1" summary={SUMMARY} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole('link', { name: /Open the connector/ }));

    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it('lists the servers it could not add yet', () => {
    render(<McpRegistryImportDonePanel connectorId="c1" summary={SUMMARY} onNavigate={() => undefined} />);

    expect(screen.getByText('io.example/local-only')).toBeInTheDocument();
  });
});

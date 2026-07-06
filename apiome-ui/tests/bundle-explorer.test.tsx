/**
 * Render tests for the bundle explorer (MFX-43.2, #4362).
 *
 * The explorer must: skip the tree/tabs for a single-file bundle; show the tree, tabs, and viewer
 * for a multi-file one; open a file from the tree into the viewer and add it to the tab strip; and
 * resolve each file's highlight language registry-driven. Monaco is stubbed so the assertions never
 * depend on the real editor loading.
 */

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="mock-monaco" data-language={language}>
      {value}
    </div>
  ),
}));

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { BundleExplorer } from '../src/app/components/ade/dashboard/export/BundleExplorer';
import {
  buildBundleManifest,
  countFindingsByFile,
} from '../src/app/components/ade/dashboard/export/exportBundle';

const emptyCounts = countFindingsByFile([], []);

const multiManifest = buildBundleManifest([
  { path: 'petstore.proto', text: 'syntax = "proto3";' },
  { path: 'com/example/User.avsc', text: '{"type":"record","name":"User"}' },
]);

describe('BundleExplorer (MFX-43.2)', () => {
  it('skips the tree and tabs for a single-file bundle', async () => {
    const single = buildBundleManifest([{ path: 'openapi.yaml', text: 'openapi: 3.1.0' }]);
    render(<BundleExplorer manifest={single} countsByPath={emptyCounts} targetKey="openapi" />);

    expect(screen.getByTestId('bundle-explorer')).toHaveAttribute('data-multi', 'false');
    expect(screen.queryByTestId('bundle-tree')).not.toBeInTheDocument();
    expect(screen.queryByTestId('bundle-file-tabs')).not.toBeInTheDocument();
    // The one file is shown in the viewer, YAML-highlighted (registry-driven).
    expect(await screen.findByTestId('bundle-file-editor')).toHaveAttribute('data-language', 'yaml');
  });

  it('shows the tree, tabs, and viewer for a multi-file bundle', async () => {
    render(<BundleExplorer manifest={multiManifest} countsByPath={emptyCounts} targetKey="protobuf" />);

    expect(screen.getByTestId('bundle-explorer')).toHaveAttribute('data-multi', 'true');
    expect(screen.getByTestId('bundle-tree')).toBeInTheDocument();
    expect(screen.getByTestId('bundle-file-tabs')).toBeInTheDocument();
    // The primary file opens first, protobuf-highlighted.
    const editor = await screen.findByTestId('bundle-file-editor');
    expect(editor).toHaveAttribute('data-language', 'protobuf');
    expect(editor).toHaveTextContent('syntax = "proto3"');
  });

  it('opens a file from the tree into the viewer and adds a tab', async () => {
    render(<BundleExplorer manifest={multiManifest} countsByPath={emptyCounts} targetKey="protobuf" />);

    // Only the primary is tabbed to start.
    expect(screen.queryByTestId('bundle-tab-com/example/User.avsc')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('bundle-tree-file-com/example/User.avsc'));

    // The viewer now shows the .avsc (its own language), and a tab appeared for it.
    const editor = await screen.findByTestId('bundle-file-editor');
    expect(editor).toHaveTextContent('"name":"User"');
    expect(screen.getByTestId('bundle-tab-com/example/User.avsc')).toHaveAttribute('data-active', 'true');
  });

  it('closes the active tab and falls back to a neighbour', async () => {
    render(<BundleExplorer manifest={multiManifest} countsByPath={emptyCounts} targetKey="protobuf" />);
    // Open the second file so two tabs exist, with the second active.
    fireEvent.click(screen.getByTestId('bundle-tree-file-com/example/User.avsc'));
    expect(screen.getByTestId('bundle-tab-com/example/User.avsc')).toHaveAttribute('data-active', 'true');

    // Close the active tab → focus falls back to the remaining primary.
    fireEvent.click(screen.getByTestId('bundle-tab-close-com/example/User.avsc'));
    expect(screen.queryByTestId('bundle-tab-com/example/User.avsc')).not.toBeInTheDocument();
    expect(screen.getByTestId('bundle-tab-petstore.proto')).toHaveAttribute('data-active', 'true');
    expect(await screen.findByTestId('bundle-file-editor')).toHaveTextContent('syntax = "proto3"');
  });
});

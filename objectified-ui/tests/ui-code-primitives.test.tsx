/**
 * Tests for the shared code-viewer primitives (MFI-28.7, #4123).
 *
 * These pin the promotion of the Monaco-backed JSON viewer, diff viewer, and lazy disclosure out of
 * `ui/mcp` into the format-neutral `ui/code` module:
 *   - `ui/code` owns and renders the three primitives (`JsonViewer` / `JsonDiffViewer` / `Disclosure`);
 *   - each viewer honours the new `language` prop (defaulting to JSON);
 *   - the `ui/mcp` `Mcp*` names still resolve to the exact same components (back-compat), both via the
 *     individual shim modules and via the `ui/mcp` barrel, so the MCP screens keep working unchanged.
 * Monaco is stubbed so nothing depends on the real editor loading.
 */

// Stub `@monaco-editor/react` (default editor + named DiffEditor) with prop-echoing components.
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="mock-monaco" data-language={language}>
      {value}
    </div>
  ),
  DiffEditor: ({
    original,
    modified,
    language,
  }: {
    original?: string;
    modified?: string;
    language?: string;
  }) => (
    <div
      data-testid="mock-monaco-diff"
      data-language={language}
      data-original={original}
      data-modified={modified}
    />
  ),
}));

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JsonViewer, JsonDiffViewer, Disclosure } from '../src/app/components/ui/code';
import { McpJsonViewer } from '../src/app/components/ui/mcp/McpJsonViewer';
import { McpJsonDiffViewer } from '../src/app/components/ui/mcp/McpJsonDiffViewer';
import { McpDisclosure } from '../src/app/components/ui/mcp/McpDisclosure';
import * as mcpBarrel from '../src/app/components/ui/mcp';

describe('ui/code JsonViewer', () => {
  it('renders the value and defaults the monaco language to json', async () => {
    render(<JsonViewer value={'{\n  "a": 1\n}'} label="Input schema" />);
    expect(screen.getByText('Input schema')).toBeInTheDocument();
    // The editor arrives via a dynamic import (resolves on a microtask under jsdom).
    const monaco = await screen.findByTestId('mock-monaco');
    expect(monaco).toHaveAttribute('data-language', 'json');
    expect(monaco).toHaveTextContent('"a": 1');
  });

  it('forwards a non-default language to monaco', async () => {
    render(<JsonViewer value={'type Query { id: ID }'} language="graphql" />);
    expect(await screen.findByTestId('mock-monaco')).toHaveAttribute('data-language', 'graphql');
  });

  it('offers a copy control', () => {
    render(<JsonViewer value="{}" label="Schema" />);
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });
});

describe('ui/code JsonDiffViewer', () => {
  it('renders both sides and defaults the diff language to json', async () => {
    render(<JsonDiffViewer original="{}" modified='{"a":1}' />);
    // The DiffEditor arrives via a dynamic import (resolves on a microtask under jsdom).
    const diff = await screen.findByTestId('mock-monaco-diff');
    expect(diff).toHaveAttribute('data-language', 'json');
    expect(diff).toHaveAttribute('data-original', '{}');
    expect(diff).toHaveAttribute('data-modified', '{"a":1}');
  });

  it('forwards a non-default language to the diff editor', async () => {
    render(<JsonDiffViewer original="a" modified="b" language="protobuf" />);
    expect(await screen.findByTestId('mock-monaco-diff')).toHaveAttribute('data-language', 'protobuf');
  });
});

describe('ui/code Disclosure', () => {
  it('mounts its children lazily — only after the first expand', () => {
    render(
      <Disclosure label="Output schema" meta="6 lines">
        <span data-testid="disclosure-body">heavy content</span>
      </Disclosure>,
    );
    // Collapsed by default: the body is not mounted yet.
    expect(screen.queryByTestId('disclosure-body')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Output schema/ }));
    expect(screen.getByTestId('disclosure-body')).toBeInTheDocument();
  });
});

describe('ui/mcp back-compat re-exports', () => {
  it('aliases the Mcp* names to the exact same ui/code components (per-file shims)', () => {
    expect(McpJsonViewer).toBe(JsonViewer);
    expect(McpJsonDiffViewer).toBe(JsonDiffViewer);
    expect(McpDisclosure).toBe(Disclosure);
  });

  it('also re-exports them through the ui/mcp barrel', () => {
    expect(mcpBarrel.McpJsonViewer).toBe(JsonViewer);
    expect(mcpBarrel.McpJsonDiffViewer).toBe(JsonDiffViewer);
    expect(mcpBarrel.McpDisclosure).toBe(Disclosure);
  });
});

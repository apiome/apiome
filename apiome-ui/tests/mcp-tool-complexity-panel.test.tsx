/**
 * Render/interaction tests for the MCP <ToolComplexityPanel> (V2-MCP-29.3 / MCAT-15.3, #4633).
 *
 * Covers the ticket's acceptance criteria: cards reflect the fixture metrics, the sort and filter
 * controls re-order / subset the cards, and the no-parameter and huge-schema tools both render
 * sanely — plus the loading, error, no-tools, and filtered-to-empty states.
 */
import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ToolComplexityPanel } from '../src/app/components/ui/mcp/ToolComplexityPanel';
import type { McpToolComplexity } from '../src/app/components/ade/dashboard/mcp/mcpInsightUi';

function tool(overrides: Partial<McpToolComplexity> = {}): McpToolComplexity {
  return {
    name: 'do_thing',
    property_count: 0,
    required_count: 0,
    optional_count: 0,
    documented_property_count: 0,
    max_nesting_depth: 0,
    uses_enum: false,
    uses_one_of: false,
    has_output_schema: false,
    ...overrides,
  };
}

/** A representative multi-tool surface: a bare tool, a simple one, and a deeply nested polymorphic one. */
const TOOLS: McpToolComplexity[] = [
  tool({ name: 'ping' }), // score 0 — none tier, no params
  tool({ name: 'search', property_count: 3, required_count: 1, uses_enum: true }), // score 4 — low
  tool({
    name: 'orchestrate',
    property_count: 12,
    required_count: 4,
    max_nesting_depth: 5,
    uses_enum: true,
    uses_one_of: true,
    has_output_schema: true,
  }), // score 12·1 + 5·2 + 3 + 1 = 26 — very-high
];

/** The tool-card headings (level 5), in DOM order. */
function cardNames(): string[] {
  return screen.getAllByRole('heading', { level: 5 }).map((h) => h.textContent ?? '');
}

describe('ToolComplexityPanel', () => {
  it('shows a loading state before the surface arrives', () => {
    render(<ToolComplexityPanel tools={null} loading error={null} />);
    expect(screen.getByText(/loading tool complexity/i)).toBeInTheDocument();
  });

  it('shows the surface error', () => {
    render(<ToolComplexityPanel tools={null} loading={false} error="boom" />);
    expect(screen.getByText('Tool complexity unavailable')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('shows a no-tools empty state for a tool-less snapshot', () => {
    render(<ToolComplexityPanel tools={[]} loading={false} error={null} />);
    expect(screen.getByText('No tools')).toBeInTheDocument();
  });

  it('renders one card per tool, most-complex first by default', () => {
    render(<ToolComplexityPanel tools={TOOLS} loading={false} error={null} />);
    expect(cardNames()).toEqual(['orchestrate', 'search', 'ping']);
    expect(screen.getByText('3 tools')).toBeInTheDocument();
  });

  it('renders card metrics: tier, score, param split, and schema features', () => {
    render(<ToolComplexityPanel tools={TOOLS} loading={false} error={null} />);
    const card = screen
      .getByRole('heading', { level: 5, name: 'orchestrate' })
      .closest('.rounded-lg') as HTMLElement;
    const scoped = within(card);
    expect(scoped.getByText('Very high')).toBeInTheDocument();
    expect(scoped.getByText(/complexity score 26/i)).toBeInTheDocument();
    expect(scoped.getByText('4 required')).toBeInTheDocument();
    expect(scoped.getByText('8 optional')).toBeInTheDocument();
    expect(scoped.getByText('Depth 5')).toBeInTheDocument();
    expect(scoped.getByText('enum')).toBeInTheDocument();
    expect(scoped.getByText('oneOf')).toBeInTheDocument();
    expect(scoped.getByText('Output schema')).toBeInTheDocument();
  });

  it('renders the no-parameter tool sanely (no split bar, "None" tier)', () => {
    render(<ToolComplexityPanel tools={[tool({ name: 'ping' })]} loading={false} error={null} />);
    const card = screen
      .getByRole('heading', { level: 5, name: 'ping' })
      .closest('.rounded-lg') as HTMLElement;
    const scoped = within(card);
    expect(scoped.getByText(/no parameters — this tool takes no input/i)).toBeInTheDocument();
    expect(scoped.getByText('None')).toBeInTheDocument();
    expect(scoped.getByText('No output schema')).toBeInTheDocument();
  });

  it('re-orders the cards when the sort changes', () => {
    render(<ToolComplexityPanel tools={TOOLS} loading={false} error={null} />);
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'name-asc' } });
    expect(cardNames()).toEqual(['orchestrate', 'ping', 'search']);
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'complexity-asc' } });
    expect(cardNames()).toEqual(['ping', 'search', 'orchestrate']);
  });

  it('subsets the cards when the filter changes and reports the count', () => {
    render(<ToolComplexityPanel tools={TOOLS} loading={false} error={null} />);
    fireEvent.change(screen.getByLabelText('Filter'), { target: { value: 'no-params' } });
    expect(cardNames()).toEqual(['ping']);
    expect(screen.getByText('1 of 3 tools')).toBeInTheDocument();
  });

  it('shows a filtered-to-empty message when no tool matches', () => {
    render(
      <ToolComplexityPanel tools={[tool({ name: 'ping' })]} loading={false} error={null} />,
    );
    fireEvent.change(screen.getByLabelText('Filter'), { target: { value: 'one-of' } });
    expect(screen.getByText('No tools match this filter')).toBeInTheDocument();
  });
});

/**
 * Render/interaction tests for the "changed since last view" digest panel (V2-MCP-30.5 / MCAT-16.5).
 *
 * Covers the acceptance criteria that live in the component (the pure projections are unit-tested in
 * `mcp-digest-ui.test.ts`): loading / error / null states; the three display states (new to you /
 * changed / up to date); the breaking-change callout; the change list with a "+N more" overflow; and
 * the "Review changes" button deep-linking to the current version's diff via `onReviewChanges`.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ChangedSinceDigestPanel } from '../src/app/components/ui/mcp/ChangedSinceDigestPanel';
import {
  mcpDigestFromPayload,
  type McpEndpointDigest,
} from '../src/app/components/ade/dashboard/mcp/mcpDigestUi';

function digest(overrides: Record<string, unknown> = {}): McpEndpointDigest {
  return mcpDigestFromPayload({
    success: true,
    endpoint_id: 'ep-1',
    new_to_you: false,
    has_changes: false,
    last_seen_version_id: 'v-2',
    last_seen_version_seq: 2,
    last_seen_at: '2026-06-01T10:00:00Z',
    current_version_id: 'v-3',
    current_version_seq: 3,
    current_version_tag: '2026-07-06',
    current_type_counts: { tools: 4, resources: 2, resource_templates: 0, prompts: 1, total: 7 },
    change_counts: { added: 0, removed: 0, modified: 0, total: 0 },
    severity_counts: { breaking: 0, additive: 0, review: 0, total: 0 },
    changes: [],
    ...overrides,
  })!;
}

describe('ChangedSinceDigestPanel', () => {
  it('shows a loading state before the digest arrives', () => {
    render(
      <ChangedSinceDigestPanel digest={null} loading error={null} onReviewChanges={jest.fn()} />,
    );
    expect(screen.getByText(/Checking what changed/i)).toBeInTheDocument();
  });

  it('shows an error state (not a crash) on failure', () => {
    render(
      <ChangedSinceDigestPanel
        digest={null}
        loading={false}
        error="digest engine down"
        onReviewChanges={jest.fn()}
      />,
    );
    expect(screen.getByText('Digest unavailable')).toBeInTheDocument();
    expect(screen.getByText('digest engine down')).toBeInTheDocument();
  });

  it('renders nothing when there is no digest and no error', () => {
    const { container } = render(
      <ChangedSinceDigestPanel digest={null} loading={false} error={null} onReviewChanges={jest.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the "up to date" state when nothing changed since the last view', () => {
    render(
      <ChangedSinceDigestPanel digest={digest()} loading={false} error={null} onReviewChanges={jest.fn()} />,
    );
    expect(screen.getByText(/up to date/i)).toBeInTheDocument();
  });

  it('shows the "new to you" state with the current surface size on a first visit', () => {
    render(
      <ChangedSinceDigestPanel
        digest={digest({ new_to_you: true })}
        loading={false}
        error={null}
        onReviewChanges={jest.fn()}
      />,
    );
    expect(screen.getByText('New to you')).toBeInTheDocument();
    // The current surface size is summarized (4 tools, 2 resources, 1 prompt).
    expect(screen.getByText(/4 tools, 2 resources, 1 prompt/)).toBeInTheDocument();
  });

  it('renders the changed state: breaking callout, tallies, change list, and a working CTA', () => {
    const onReviewChanges = jest.fn();
    render(
      <ChangedSinceDigestPanel
        digest={digest({
          has_changes: true,
          change_counts: { added: 1, removed: 1, modified: 0, total: 2 },
          severity_counts: { breaking: 1, additive: 1, review: 0, total: 2 },
          changes: [
            { change_type: 'removed', item_type: 'tool', item_name: 'legacy_search', severity: 'breaking' },
            { change_type: 'added', item_type: 'tool', item_name: 'summarize', severity: 'additive' },
          ],
        })}
        loading={false}
        error={null}
        onReviewChanges={onReviewChanges}
      />,
    );

    // Breaking-change callout is prominent (an alert) and names the count.
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/1 breaking change/);
    // Both changed items are listed.
    expect(screen.getByText('legacy_search')).toBeInTheDocument();
    expect(screen.getByText('summarize')).toBeInTheDocument();

    // The CTA deep-links to the current version's diff.
    fireEvent.click(screen.getByRole('button', { name: /Review changes/ }));
    expect(onReviewChanges).toHaveBeenCalledWith('v-3');
  });

  it('caps the change list and notes the overflow', () => {
    const changes = Array.from({ length: 9 }, (_, i) => ({
      change_type: 'added',
      item_type: 'tool',
      item_name: `tool_${i}`,
      severity: 'additive',
    }));
    render(
      <ChangedSinceDigestPanel
        digest={digest({
          has_changes: true,
          change_counts: { added: 9, removed: 0, modified: 0, total: 9 },
          severity_counts: { breaking: 0, additive: 9, review: 0, total: 9 },
          changes,
        })}
        loading={false}
        error={null}
        onReviewChanges={jest.fn()}
      />,
    );
    // Six are listed; the remaining three collapse into a "+3 more" note.
    expect(screen.getByText('tool_5')).toBeInTheDocument();
    expect(screen.queryByText('tool_6')).not.toBeInTheDocument();
    expect(screen.getByText(/more/)).toHaveTextContent('3');
  });

  it('omits the breaking callout when no change is breaking', () => {
    render(
      <ChangedSinceDigestPanel
        digest={digest({
          has_changes: true,
          change_counts: { added: 2, removed: 0, modified: 0, total: 2 },
          severity_counts: { breaking: 0, additive: 2, review: 0, total: 2 },
          changes: [
            { change_type: 'added', item_type: 'tool', item_name: 'a', severity: 'additive' },
            { change_type: 'added', item_type: 'tool', item_name: 'b', severity: 'additive' },
          ],
        })}
        loading={false}
        error={null}
        onReviewChanges={jest.fn()}
      />,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

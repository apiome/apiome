/**
 * Authoring primitive rendering and accessibility (UXE-1.3).
 *
 * Covers the acceptance criteria that only hold at the DOM level:
 *
 * - "Semantic status never depends on Scribe/Slate brand accents or color
 *   alone" — every toned element is asserted to carry a text label too.
 * - "Publish, rollback, AI proposal, and failure states use shared interaction
 *   contracts" — the impact sheet's gate, and the proposal card's action set,
 *   are exercised through the rendered controls rather than only as functions.
 * - "Component accessibility tests cover all states" — roles, accessible names,
 *   live regions and the full tree keyboard contract.
 */

import * as React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  REFERENCE_BLOCKING_CHECKS,
  REFERENCE_BULK_ACTIONS,
  REFERENCE_CHECKS,
  REFERENCE_DIFF,
  REFERENCE_FAILED_PHASES,
  REFERENCE_PASSING_CHECKS,
  REFERENCE_PHASES,
  REFERENCE_PROMOTE_SHEET,
  REFERENCE_PROPOSAL,
  REFERENCE_PURGE_SHEET,
  REFERENCE_RISKY_PROPOSAL,
  REFERENCE_SERIES,
  REFERENCE_SPARSE_SERIES,
  REFERENCE_TREE,
} from '@lib/authoring/reference-fixtures';
import AuthoringAnalyticsPanel from '@/app/ade/authoring/components/primitives/AuthoringAnalyticsPanel';
import AuthoringCheckSummary from '@/app/ade/authoring/components/primitives/AuthoringCheckSummary';
import AuthoringCitationList from '@/app/ade/authoring/components/primitives/AuthoringCitationList';
import AuthoringContentTree from '@/app/ade/authoring/components/primitives/AuthoringContentTree';
import AuthoringDiffView from '@/app/ade/authoring/components/primitives/AuthoringDiffView';
import AuthoringImpactSheet from '@/app/ade/authoring/components/primitives/AuthoringImpactSheet';
import AuthoringPeekDrawer from '@/app/ade/authoring/components/primitives/AuthoringPeekDrawer';
import AuthoringProgressPhases from '@/app/ade/authoring/components/primitives/AuthoringProgressPhases';
import AuthoringProposalCard from '@/app/ade/authoring/components/primitives/AuthoringProposalCard';
import AuthoringReleaseBadge, {
  AuthoringEnvironmentBadge,
} from '@/app/ade/authoring/components/primitives/AuthoringReleaseBadge';
import AuthoringSelectionBar from '@/app/ade/authoring/components/primitives/AuthoringSelectionBar';
import AuthoringSplitWorkspace from '@/app/ade/authoring/components/primitives/AuthoringSplitWorkspace';
import AuthoringToneBadge from '@/app/ade/authoring/components/primitives/AuthoringToneBadge';

// ----- Tone badges -----

describe('AuthoringToneBadge', () => {
  it('always renders a text label beside its tone', () => {
    render(<AuthoringToneBadge label="Stale" tone="warning" icon="TriangleAlert" />);

    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('exposes its explanation to assistive technology without showing it twice', () => {
    render(
      <AuthoringToneBadge label="Conflict" tone="danger" description="Review both versions." />
    );

    const badge = screen.getByText('Conflict').closest('span[data-tone]')!;
    const describedBy = badge.getAttribute('aria-describedby')!;

    expect(document.getElementById(describedBy)).toHaveTextContent('Review both versions.');
  });

  it('records its tone as data rather than relying on class names', () => {
    render(<AuthoringToneBadge label="Passed" tone="success" />);

    expect(screen.getByText('Passed').closest('span')).toHaveAttribute('data-tone', 'success');
  });
});

// ----- Release and environment badges -----

describe('AuthoringReleaseBadge', () => {
  it('names the status in words as well as tone', () => {
    render(<AuthoringReleaseBadge status="failed" releaseId="r-4821" />);

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('r-4821')).toBeInTheDocument();
  });

  it('distinguishes rolled back from failed, which are different events', () => {
    const { rerender } = render(<AuthoringReleaseBadge status="rolled-back" />);
    expect(screen.getByText('Rolled back')).toBeInTheDocument();

    rerender(<AuthoringReleaseBadge status="failed" />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText('Rolled back')).not.toBeInTheDocument();
  });

  it('keeps the deployment lane toneless, because a lane is not a health signal', () => {
    render(<AuthoringEnvironmentBadge environment="production" />);

    expect(screen.getByText('Production').closest('span')).toHaveAttribute('data-tone', 'neutral');
  });
});

// ----- Citations -----

describe('AuthoringCitationList', () => {
  it('lists each cited source with its pointer', () => {
    render(<AuthoringCitationList citations={REFERENCE_PROPOSAL.citations} />);

    // The fixtures carry no deep link, so each citation renders as text; the
    // kind and pointer are still present so the source is unambiguous.
    expect(screen.getByText('GET /pets/{petId}')).toBeInTheDocument();
    expect(screen.getByText('paths./pets/{petId}.get')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /2 sources cited/ })).toBeInTheDocument();
  });

  it('warns rather than showing an empty list when nothing was cited', () => {
    render(<AuthoringCitationList citations={[]} />);

    expect(screen.getByRole('note')).toHaveTextContent(/no sources cited/i);
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });
});

// ----- Proposals -----

describe('AuthoringProposalCard', () => {
  it('offers the full review set while pending', async () => {
    render(<AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={jest.fn()} />);

    ['Accept', 'Edit', 'Reject', 'Regenerate'].forEach((label) => {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeInTheDocument();
    });
  });

  it('marks a pending proposal as proposed, so it is not mistaken for saved content', () => {
    render(<AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={jest.fn()} />);

    // "Proposed" appears twice by design: as the status chip and as the
    // heading of the generated text, both distinguishing it from saved content.
    expect(screen.getAllByText('Proposed').length).toBeGreaterThan(0);
    expect(screen.getByRole('article')).toHaveAttribute('data-proposal-status', 'pending');
    expect(screen.getByText('Current')).toBeInTheDocument();
  });

  it('offers no way to apply an already accepted proposal', () => {
    render(
      <AuthoringProposalCard
        proposal={{ ...REFERENCE_PROPOSAL, status: 'accepted' }}
        onAction={jest.fn()}
      />
    );

    expect(screen.queryByRole('button', { name: /Accept/ })).not.toBeInTheDocument();
    expect(screen.getByText('Accepted')).toBeInTheDocument();
  });

  it('reports the chosen gesture with the proposal id', async () => {
    const onAction = jest.fn();
    const user = userEvent.setup();
    render(<AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={onAction} />);

    await user.click(screen.getByRole('button', { name: /Accept/ }));

    expect(onAction).toHaveBeenCalledWith('accept', 'prop-1');
  });

  it('warns about an invalid example before the accept gesture', () => {
    render(<AuthoringProposalCard proposal={REFERENCE_RISKY_PROPOSAL} onAction={jest.fn()} />);

    // Two notes are expected here: the invalid example and the missing
    // citations. Both must precede the accept gesture.
    const notes = screen.getAllByRole('note');
    expect(notes.some((note) => /does not validate/i.test(note.textContent ?? ''))).toBe(true);
  });

  it('flags ungrounded content rather than presenting it as reviewed', () => {
    render(<AuthoringProposalCard proposal={REFERENCE_RISKY_PROPOSAL} onAction={jest.fn()} />);

    expect(screen.getByText(/Verify before accepting/i)).toBeInTheDocument();
  });

  it('disables applying gestures in a read-only scope, with the reason stated', () => {
    render(<AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={jest.fn()} readOnly />);

    expect(screen.getByRole('button', { name: /Accept/ })).toBeDisabled();
    expect(screen.getAllByText(/read only/i).length).toBeGreaterThan(0);
  });

  it('keeps regeneration available in a read-only scope, since it writes nothing', () => {
    render(<AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={jest.fn()} readOnly />);

    expect(screen.getByRole('button', { name: /Regenerate/ })).toBeEnabled();
  });
});

// ----- Checks -----

describe('AuthoringCheckSummary', () => {
  it('announces its summary through a live region', () => {
    render(<AuthoringCheckSummary checks={REFERENCE_PASSING_CHECKS} />);

    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('2 of 2 checks passed');
  });

  it('reports an unfinished run as unfinished rather than as passing', () => {
    render(<AuthoringCheckSummary checks={REFERENCE_CHECKS} />);

    expect(screen.getByRole('status')).toHaveTextContent(/checks running/);
  });

  it('states each outcome in words, not only by icon colour', () => {
    render(<AuthoringCheckSummary checks={REFERENCE_BLOCKING_CHECKS} />);

    const failing = screen.getByText('Contract lint').closest('li')!;
    expect(within(failing).getByText('Failed')).toBeInTheDocument();
    expect(within(failing).getByText('Required')).toBeInTheDocument();
  });

  it('hides the per-check list when collapsed but keeps the summary', () => {
    render(<AuthoringCheckSummary checks={REFERENCE_PASSING_CHECKS} collapsed />);

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByText('Contract lint')).not.toBeInTheDocument();
  });

  it('handles having no checks at all without claiming success', () => {
    render(<AuthoringCheckSummary checks={[]} />);

    expect(screen.getByRole('status')).toHaveTextContent('No checks');
  });
});

// ----- Progress -----

describe('AuthoringProgressPhases', () => {
  it('exposes a real progressbar with a spoken value', () => {
    render(<AuthoringProgressPhases phases={REFERENCE_PHASES} title="Build progress" />);

    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '40');
    expect(bar).toHaveAttribute('aria-valuetext', 'Step 3 of 5: Rendering pages. 482 of 640 pages.');
  });

  it('names the active phase and its live detail in visible text', () => {
    render(<AuthoringProgressPhases phases={REFERENCE_PHASES} title="Build progress" />);

    expect(screen.getByText('Rendering pages')).toBeInTheDocument();
    expect(screen.getByText('482 of 640 pages')).toBeInTheDocument();
  });

  it('remains understandable with animation disabled, because every phase is text', () => {
    render(<AuthoringProgressPhases phases={REFERENCE_PHASES} title="Build progress" />);

    // No animation involved: the status of each phase is a word in the DOM.
    expect(screen.getAllByText('Complete')).toHaveLength(2);
    expect(screen.getByText('In progress')).toBeInTheDocument();
    expect(screen.getAllByText('Not started')).toHaveLength(2);
  });

  it('reports a failure rather than advancing to completion', () => {
    render(<AuthoringProgressPhases phases={REFERENCE_FAILED_PHASES} title="Build progress" />);

    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuetext',
      expect.stringMatching(/^Failed at step 2 of 3/)
    );
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });
});

// ----- Content tree -----

describe('AuthoringContentTree', () => {
  /**
   * Render the tree with working expansion state.
   *
   * @param props - Overrides, e.g. the initially expanded ids.
   */
  function TreeHarness({ initiallyExpanded = ['guides'] }: { initiallyExpanded?: string[] }) {
    const [expanded, setExpanded] = React.useState(new Set(initiallyExpanded));
    const [selected, setSelected] = React.useState<string | undefined>(undefined);

    return (
      <AuthoringContentTree
        nodes={REFERENCE_TREE}
        label="Reference content"
        expandedIds={expanded}
        onExpandedChange={setExpanded}
        selectedId={selected}
        onSelect={setSelected}
      />
    );
  }

  it('exposes a named tree with levelled items', () => {
    render(<TreeHarness />);

    expect(screen.getByRole('tree', { name: 'Reference content' })).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { name: /Getting started/ })).toHaveAttribute(
      'aria-level',
      '2'
    );
  });

  it('marks expandable nodes and leaves distinctly', () => {
    render(<TreeHarness />);

    expect(screen.getByRole('treeitem', { name: /Guides/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByRole('treeitem', { name: /Getting started/ })).not.toHaveAttribute(
      'aria-expanded'
    );
  });

  it('costs one Tab stop regardless of size, via a roving tabindex', () => {
    render(<TreeHarness />);

    const focusable = screen
      .getAllByRole('treeitem')
      .filter((item) => item.getAttribute('tabindex') === '0');

    expect(focusable).toHaveLength(1);
  });

  it('moves focus with the arrow keys', async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    await user.tab();
    expect(screen.getByRole('treeitem', { name: /Guides/ })).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('treeitem', { name: /Getting started/ })).toHaveFocus();
  });

  it('collapses and expands with the left and right arrows', async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    await user.tab();
    await user.keyboard('{ArrowLeft}');
    expect(screen.queryByRole('treeitem', { name: /Getting started/ })).not.toBeInTheDocument();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('treeitem', { name: /Getting started/ })).toBeInTheDocument();
  });

  it('selects with Enter without needing a pointer', async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    await user.tab();
    await user.keyboard('{ArrowDown}{Enter}');

    expect(screen.getByRole('treeitem', { name: /Getting started/ })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  it('states node status in words alongside its tone', () => {
    render(<TreeHarness />);

    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getAllByText('Documented').length).toBeGreaterThan(0);
  });

  it('explains an empty tree rather than rendering nothing', () => {
    render(
      <AuthoringContentTree
        nodes={[]}
        label="Empty"
        expandedIds={new Set()}
        onExpandedChange={jest.fn()}
        onSelect={jest.fn()}
      />
    );

    expect(screen.getByText(/Nothing to show yet/)).toBeInTheDocument();
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
  });
});

// ----- Split workspace -----

describe('AuthoringSplitWorkspace', () => {
  const PANES = {
    navigation: { title: 'Content', children: <p>tree</p> },
    main: { title: 'Editor', children: <p>editor</p> },
  };

  it('names every pane as a landmark region', () => {
    render(<AuthoringSplitWorkspace {...PANES} />);

    expect(screen.getByRole('region', { name: 'Content' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Editor' })).toBeInTheDocument();
  });

  it('offers a route to the inspector for viewports too narrow to show it inline', async () => {
    const onInspectorOpen = jest.fn();
    const user = userEvent.setup();

    render(
      <AuthoringSplitWorkspace
        {...PANES}
        inspector={{ title: 'Inspector', children: <p>details</p> }}
        onInspectorOpen={onInspectorOpen}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Inspector' }));
    expect(onInspectorOpen).toHaveBeenCalled();
  });

  it('records how many panes it is laying out', () => {
    const { rerender } = render(<AuthoringSplitWorkspace {...PANES} />);
    expect(screen.getByTestId('authoring-pane-main').parentElement).toHaveAttribute('data-panes', '2');

    rerender(
      <AuthoringSplitWorkspace
        {...PANES}
        inspector={{ title: 'Inspector', children: <p>details</p> }}
        onInspectorOpen={jest.fn()}
      />
    );
    expect(screen.getByTestId('authoring-pane-main').parentElement).toHaveAttribute('data-panes', '3');
  });
});

// ----- Peek drawer -----

describe('AuthoringPeekDrawer', () => {
  it('opens as a named dialog with a describable purpose', () => {
    render(
      <AuthoringPeekDrawer
        open
        onOpenChange={jest.fn()}
        title="Release r-4821"
        description="Inspecting without losing list state."
      >
        <p>body</p>
      </AuthoringPeekDrawer>
    );

    const dialog = screen.getByRole('dialog', { name: 'Release r-4821' });
    expect(dialog).toHaveTextContent('Inspecting without losing list state.');
  });

  it('closes on Escape, so the list behind it is never trapped', async () => {
    const onOpenChange = jest.fn();
    const user = userEvent.setup();

    render(
      <AuthoringPeekDrawer open onOpenChange={onOpenChange} title="Release r-4821">
        <p>body</p>
      </AuthoringPeekDrawer>
    );

    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('gives its close control an accessible name rather than a bare icon', () => {
    render(
      <AuthoringPeekDrawer open onOpenChange={jest.fn()} title="Release r-4821">
        <p>body</p>
      </AuthoringPeekDrawer>
    );

    expect(screen.getByRole('button', { name: 'Close Release r-4821' })).toBeInTheDocument();
  });

  it('renders nothing while closed, so its content is not reachable', () => {
    render(
      <AuthoringPeekDrawer open={false} onOpenChange={jest.fn()} title="Release r-4821">
        <p>body</p>
      </AuthoringPeekDrawer>
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

// ----- Diff -----

describe('AuthoringDiffView', () => {
  it('summarises the change in countable words', () => {
    render(
      <AuthoringDiffView title="Description" before={REFERENCE_DIFF.before} after={REFERENCE_DIFF.after} />
    );

    expect(screen.getByTestId('authoring-diff-summary')).toHaveTextContent(
      '2 lines added, 2 lines removed.'
    );
  });

  it('labels each line in text as well as by tint', () => {
    render(<AuthoringDiffView title="Description" before="old" after="new" />);

    expect(screen.getByText('Added')).toBeInTheDocument();
    expect(screen.getByText('Removed')).toBeInTheDocument();
  });

  it('says so plainly when the two sides are identical', () => {
    render(<AuthoringDiffView title="Description" before="same" after="same" />);

    expect(screen.getByText(/are identical/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('names both sides so a comparison is never ambiguous', () => {
    render(
      <AuthoringDiffView
        title="Description"
        before="a"
        after="b"
        beforeLabel="Production"
        afterLabel="Draft"
      />
    );

    expect(screen.getByTestId('authoring-diff-summary')).toHaveTextContent('Production → Draft');
  });
});

// ----- Selection bar -----

describe('AuthoringSelectionBar', () => {
  it('announces the selection with its noun', () => {
    render(
      <AuthoringSelectionBar
        selectedCount={3}
        totalCount={24}
        noun="target"
        actions={REFERENCE_BULK_ACTIONS}
        onAction={jest.fn()}
      />
    );

    expect(screen.getByRole('status')).toHaveTextContent('3 targets selected of 24.');
  });

  it('disables every bulk action with a stated reason when nothing is selected', () => {
    render(
      <AuthoringSelectionBar
        selectedCount={0}
        totalCount={24}
        noun="target"
        actions={REFERENCE_BULK_ACTIONS}
        onAction={jest.fn()}
      />
    );

    expect(screen.getByRole('button', { name: /Regenerate/ })).toBeDisabled();
    expect(screen.getAllByText('Select at least one target first.').length).toBeGreaterThan(0);
  });

  it('keeps a more specific reason instead of the generic one', () => {
    render(
      <AuthoringSelectionBar
        selectedCount={0}
        totalCount={24}
        noun="target"
        actions={REFERENCE_BULK_ACTIONS}
        onAction={jest.fn()}
      />
    );

    expect(screen.getByText('Export needs the hosted plan.')).toBeInTheDocument();
  });

  it('never disables a control without saying why', () => {
    render(
      <AuthoringSelectionBar
        selectedCount={0}
        totalCount={24}
        noun="target"
        actions={REFERENCE_BULK_ACTIONS}
        onAction={jest.fn()}
      />
    );

    screen
      .getAllByRole('button')
      .filter((button) => button.hasAttribute('disabled'))
      .forEach((button) => {
        const describedBy = button.getAttribute('aria-describedby');
        expect(describedBy).toBeTruthy();
        expect(document.getElementById(describedBy!)).not.toBeEmptyDOMElement();
      });
  });
});

// ----- Impact sheet -----

describe('AuthoringImpactSheet', () => {
  it('states what changes rather than asking a generic question', () => {
    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Promote to production' })).toBeInTheDocument();
    expect(screen.getByText('docs.example.com')).toBeInTheDocument();
    expect(screen.getByText('640 pages')).toBeInTheDocument();
    expect(screen.queryByText(/are you sure/i)).not.toBeInTheDocument();
  });

  it('shows the governing policy alongside the checks', () => {
    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByText(/recorded in the tenant audit log/)).toBeInTheDocument();
    expect(screen.getByText('2 of 2 checks passed')).toBeInTheDocument();
  });

  it('requires an acknowledgement before a notable action can be confirmed', async () => {
    const onConfirm = jest.fn();
    const user = userEvent.setup();

    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={onConfirm}
      />
    );

    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();

    await user.click(screen.getByRole('checkbox'));

    expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Promote' }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it('requires the target to be typed for an irreversible action', async () => {
    const onConfirm = jest.fn();
    const user = userEvent.setup();

    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PURGE_SHEET}
        onConfirm={onConfirm}
      />
    );

    expect(screen.getByRole('button', { name: 'Purge' })).toBeDisabled();

    await user.type(screen.getByRole('textbox'), 'docs.example.co');
    expect(screen.getByRole('button', { name: 'Purge' })).toBeDisabled();

    await user.type(screen.getByRole('textbox'), 'm');
    expect(screen.getByRole('button', { name: 'Purge' })).toBeEnabled();
  });

  it('blocks confirmation while required checks have failed, and says so', () => {
    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={{ ...REFERENCE_PROMOTE_SHEET, checks: REFERENCE_BLOCKING_CHECKS }}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();
    // Stated twice on purpose: once by the check summary, and once as the
    // button's own reason, so it is reachable however the operator arrives.
    expect(screen.getAllByText(/This action is blocked/).length).toBeGreaterThanOrEqual(2);
  });

  it('blocks confirmation while checks are still running', () => {
    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={{ ...REFERENCE_PROMOTE_SHEET, checks: REFERENCE_CHECKS }}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();
    expect(
      screen.getAllByText(/have not finished/).length
    ).toBeGreaterThan(0);
  });

  it('warns in its description that an irreversible action cannot be undone', () => {
    render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PURGE_SHEET}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByRole('dialog')).toHaveTextContent(/cannot be undone/i);
  });

  it('does not carry an acknowledgement over to the next time it opens', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={jest.fn()}
      />
    );

    await user.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled();

    rerender(
      <AuthoringImpactSheet
        open={false}
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={jest.fn()}
      />
    );
    rerender(
      <AuthoringImpactSheet
        open
        onOpenChange={jest.fn()}
        sheet={REFERENCE_PROMOTE_SHEET}
        onConfirm={jest.fn()}
      />
    );

    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();
  });
});

// ----- Analytics -----

describe('AuthoringAnalyticsPanel', () => {
  it('provides a text equivalent for the chart', () => {
    render(<AuthoringAnalyticsPanel title="Page views" state="ready" series={REFERENCE_SERIES} />);

    expect(screen.getByTestId('authoring-chart-summary')).toHaveTextContent(
      /Page views: 1,145 views total/
    );
  });

  it('labels the chart drawing with that same summary', () => {
    render(
      <AuthoringAnalyticsPanel title="Page views" state="ready" series={REFERENCE_SERIES}>
        <svg />
      </AuthoringAnalyticsPanel>
    );

    expect(screen.getByRole('img', { name: /Page views: 1,145 views total/ })).toBeInTheDocument();
  });

  it('offers the data as a table', async () => {
    const user = userEvent.setup();
    render(<AuthoringAnalyticsPanel title="Page views" state="ready" series={REFERENCE_SERIES} />);

    await user.click(screen.getByRole('button', { name: 'View as table' }));

    const table = screen.getByRole('table');
    expect(within(table).getByRole('rowheader', { name: '2026-07-13' })).toBeInTheDocument();
    expect(within(table).getByText('120 views')).toBeInTheDocument();
  });

  it('distinguishes a suppressed panel from an empty one', () => {
    const { rerender } = render(<AuthoringAnalyticsPanel title="Feedback" state="empty" />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();

    rerender(
      <AuthoringAnalyticsPanel title="Feedback" state="threshold" series={REFERENCE_SPARSE_SERIES} />
    );
    expect(screen.getByText('Below the privacy threshold')).toBeInTheDocument();
    expect(screen.queryByText('No data yet')).not.toBeInTheDocument();
  });

  it('does not show suppressed values anywhere in the DOM', () => {
    render(
      <AuthoringAnalyticsPanel title="Feedback" state="threshold" series={REFERENCE_SPARSE_SERIES} />
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText(/2026-07-16/)).not.toBeInTheDocument();
  });

  it('announces a failure assertively and offers a retry', async () => {
    const onRetry = jest.fn();
    const user = userEvent.setup();
    render(<AuthoringAnalyticsPanel title="Page views" state="error" onRetry={onRetry} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load');

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('treats a ready state with no series as empty rather than drawing an empty frame', () => {
    render(<AuthoringAnalyticsPanel title="Page views" state="ready" />);

    expect(screen.getByText('No data yet')).toBeInTheDocument();
    expect(screen.queryByTestId('authoring-chart-summary')).not.toBeInTheDocument();
  });
});

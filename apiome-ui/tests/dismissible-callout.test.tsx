/**
 * `DismissibleCallout` — an explainer that shows once (HIVE-11.5, #5601).
 *
 * Pins first-visit display, **Got it** persistence under `hive.seen.<id>` (surviving a
 * remount, undone by clearing storage), **Learn more**, `reopenFrom`, and that blocked
 * storage never throws.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { DismissibleCallout } from '@/app/components/ui/DismissibleCallout';

/**
 * Renders the callout under test.
 *
 * @param props Overrides.
 * @returns The render result.
 */
function renderCallout(props: Partial<React.ComponentProps<typeof DismissibleCallout>> = {}) {
  return render(
    <DismissibleCallout id="catalog-explainer" reopenFrom="How the catalog works" {...props}>
      Catalog items are non-publishable.
    </DismissibleCallout>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('DismissibleCallout', () => {
  it('shows on a first visit as a note in the accent tint', () => {
    renderCallout();
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Catalog items are non-publishable.');
    expect(note).toHaveClass('bg-accent-soft');
    expect(note).toHaveAttribute('data-reopen-from', 'How the catalog works');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('takes the neutral and honey tones', () => {
    const { unmount } = renderCallout({ tone: 'neutral' });
    expect(screen.getByRole('note')).toHaveClass('bg-subtle');
    unmount();
    renderCallout({ tone: 'honey' });
    expect(screen.getByRole('note')).toHaveClass('bg-honey-soft');
  });

  it('hides on Got it and stays hidden after a reload', async () => {
    const user = userEvent.setup();
    const onDismiss = jest.fn();
    const { unmount } = renderCallout({ onDismiss });
    await user.click(screen.getByRole('button', { name: 'Got it' }));
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(window.localStorage.getItem('hive.seen.catalog-explainer')).toBe('1');
    expect(onDismiss).toHaveBeenCalledTimes(1);
    unmount();

    renderCallout();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('shows again once storage is cleared', () => {
    window.localStorage.setItem('hive.seen.catalog-explainer', '1');
    const { unmount } = renderCallout();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    unmount();
    window.localStorage.clear();
    renderCallout();
    expect(screen.getByRole('note')).toBeInTheDocument();
  });

  it('keeps each id separate', () => {
    window.localStorage.setItem('hive.seen.other', '1');
    renderCallout();
    expect(screen.getByRole('note')).toBeInTheDocument();
  });

  it('offers Learn more only when given a handler', async () => {
    const user = userEvent.setup();
    const { unmount } = renderCallout();
    expect(screen.queryByRole('button', { name: 'Learn more' })).not.toBeInTheDocument();
    unmount();

    const onLearnMore = jest.fn();
    renderCallout({ onLearnMore, learnMoreLabel: 'How it works' });
    await user.click(screen.getByRole('button', { name: 'How it works' }));
    expect(onLearnMore).toHaveBeenCalledTimes(1);
    // Learning more is not dismissing.
    expect(screen.getByRole('note')).toBeInTheDocument();
    expect(window.localStorage.getItem('hive.seen.catalog-explainer')).toBeNull();
  });

  it('never throws when storage is blocked, and still hides for this visit', async () => {
    const user = userEvent.setup();
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    renderCallout();
    expect(screen.getByRole('note')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Got it' }));
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = renderCallout({ onLearnMore: () => undefined });
    expect(await axe(container)).toHaveNoViolations();
  });
});

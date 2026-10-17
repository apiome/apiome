/**
 * The first-visit catalog explainer (MFI-24.3, #4083; re-skinned HIVE-7.1, #5318; made
 * dismissible HIVE-11.6, #5602).
 *
 * Pins the banner's copy (the mockup's Keeps (1:1) list quotes it), that it is a `role="note"`
 * rather than an alert, that **Got it** hides it for good under `hive.seen.catalog-explainer`,
 * that **Learn more** opens the dialog, and that it states where its content lives afterwards.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import { CATALOG_EXPLAINER_ID, CatalogExplainerCallout } from '../src/app/components/ade/catalog';

/** The copy uses non-breaking spaces (U+00A0); normalise them to plain spaces before asserting. */
function normalisedText(el: HTMLElement): string {
  return (el.textContent ?? '').replace(/ /g, ' ');
}

/** Render the callout and wait for storage to be read after mount. */
async function renderCallout(onLearnMore = jest.fn()) {
  const view = render(<CatalogExplainerCallout onLearnMore={onLearnMore} />);
  await screen.findByRole('note');
  return { ...view, onLearnMore };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('CatalogExplainerCallout', () => {
  it('renders a note, not an alert, on a first visit', async () => {
    await renderCallout();
    expect(screen.getByRole('note')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps the banner copy: non-publishable, Convert to OpenAPI, Projects', async () => {
    await renderCallout();
    const note = screen.getByRole('note');
    const text = normalisedText(note);
    expect(text).toContain('Catalog items are non-publishable.');
    expect(text).toContain('only path to a publishable spec is Convert to OpenAPI');
    expect(text).toContain('OpenAPI/Swagger imports still land in');
    expect(within(note).getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/ade/dashboard/projects'
    );
  });

  it('states where its content lives once dismissed', async () => {
    await renderCallout();
    expect(screen.getByRole('note').getAttribute('data-reopen-from')).toMatch(
      /How the catalog works/
    );
  });

  it('opens the dialog from Learn more', async () => {
    const user = userEvent.setup();
    const { onLearnMore } = await renderCallout();
    await user.click(screen.getByRole('button', { name: 'Learn more' }));
    expect(onLearnMore).toHaveBeenCalledTimes(1);
  });

  it('hides on Got it and stays hidden on the next visit', async () => {
    const user = userEvent.setup();
    const { unmount } = await renderCallout();
    await user.click(screen.getByRole('button', { name: 'Got it' }));
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(window.localStorage.getItem(`hive.seen.${CATALOG_EXPLAINER_ID}`)).toBe('1');
    unmount();

    render(<CatalogExplainerCallout onLearnMore={jest.fn()} />);
    // Give the post-mount storage read its turn, then confirm nothing appeared.
    await Promise.resolve();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});

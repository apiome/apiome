/**
 * Unit tests for the reusable accessible tab bar (CatalogDetailTabs, MFI-25.1, #4086).
 *
 * The catalog detail shell test (catalog-item-detail.test.tsx) exercises the bar in context; these
 * pin the standalone ARIA/keyboard contract that the rest of EPIC-25 relies on: roving tabindex,
 * `aria-controls`/id wiring, click selection, and Arrow/Home/End navigation (including wraparound).
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  CatalogDetailTabs,
  panelElementId,
  tabElementId,
} from '../src/app/components/ade/dashboard/catalog/CatalogDetailTabs';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'source', label: 'Source & Code' },
  { id: 'versions', label: 'Versions' },
] as const;

/** Render a controlled bar whose `active` state is driven by `onSelect`, mirroring the real caller. */
function ControlledTabs({ initial = 'overview' }: { initial?: string }) {
  const [active, setActive] = React.useState(initial);
  return <CatalogDetailTabs tabs={TABS} active={active} onSelect={setActive} />;
}

describe('CatalogDetailTabs', () => {
  it('exposes the tablist/tab/aria wiring with a roving tabindex', () => {
    render(<ControlledTabs />);

    expect(screen.getByRole('tablist')).toHaveAttribute('aria-label');
    const overview = screen.getByTestId('catalog-detail-tab-overview');
    expect(overview).toHaveAttribute('role', 'tab');
    expect(overview).toHaveAttribute('aria-selected', 'true');
    expect(overview).toHaveAttribute('tabindex', '0');
    expect(overview).toHaveAttribute('id', tabElementId('catalog-detail', 'overview'));
    expect(overview).toHaveAttribute('aria-controls', panelElementId('catalog-detail', 'overview'));

    const source = screen.getByTestId('catalog-detail-tab-source');
    expect(source).toHaveAttribute('aria-selected', 'false');
    expect(source).toHaveAttribute('tabindex', '-1');
  });

  it('selects a tab on click', () => {
    render(<ControlledTabs />);
    fireEvent.click(screen.getByTestId('catalog-detail-tab-source'));
    expect(screen.getByTestId('catalog-detail-tab-source')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('catalog-detail-tab-overview')).toHaveAttribute('aria-selected', 'false');
  });

  it('moves selection and focus with ArrowRight/ArrowLeft, wrapping at the ends', () => {
    render(<ControlledTabs />);
    const overview = screen.getByTestId('catalog-detail-tab-overview');
    const source = screen.getByTestId('catalog-detail-tab-source');
    const versions = screen.getByTestId('catalog-detail-tab-versions');

    overview.focus();
    fireEvent.keyDown(overview, { key: 'ArrowRight' });
    expect(source).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(source);

    // ArrowLeft from the first tab wraps to the last.
    fireEvent.keyDown(overview, { key: 'ArrowLeft' });
    expect(versions).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(versions);
  });

  it('jumps to the first/last tab with Home/End', () => {
    render(<ControlledTabs initial="source" />);
    const source = screen.getByTestId('catalog-detail-tab-source');

    fireEvent.keyDown(source, { key: 'End' });
    expect(screen.getByTestId('catalog-detail-tab-versions')).toHaveAttribute('aria-selected', 'true');

    fireEvent.keyDown(screen.getByTestId('catalog-detail-tab-versions'), { key: 'Home' });
    expect(screen.getByTestId('catalog-detail-tab-overview')).toHaveAttribute('aria-selected', 'true');
  });
});

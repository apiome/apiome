/**
 * The class heatmap dialog (#560): states, the metric switch and the legend.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import ClassHeatmapDialog from '../src/app/ade/dashboard/versions/ClassHeatmapDialog';
import type { HeatmapClass } from '../src/app/utils/class-heatmap';

const NOW = new Date('2026-10-21T12:00:00Z');
const VERSION = { id: 'v1', version_id: '1.2.0' };

const CLASSES: HeatmapClass[] = [
  { id: 'a', name: 'Alpha', description: 'Documented', updated_at: '2026-10-21T08:00:00Z', properties: [] },
  {
    id: 'b',
    name: 'Beta',
    description: null,
    updated_at: '2025-01-01T00:00:00Z',
    properties: [
      { id: 'p1', name: 'alpha', description: null, data: { $ref: '#/components/schemas/Alpha' } },
      { id: 'p2', name: 'code', description: null, data: { type: 'string' } },
    ],
  },
];

function renderDialog(props: Partial<React.ComponentProps<typeof ClassHeatmapDialog>> = {}) {
  return render(
    <ClassHeatmapDialog
      open
      onOpenChange={() => {}}
      version={VERSION}
      projectName="Payments API"
      classes={CLASSES}
      now={NOW}
      {...props}
    />
  );
}

describe('ClassHeatmapDialog', () => {
  it('names the revision and draws a tile per class, warmest complexity first', () => {
    renderDialog();
    expect(screen.getByRole('heading', { name: 'Heatmap' })).toBeInTheDocument();
    expect(screen.getByText(/Payments API — v1\.2\.0/)).toBeInTheDocument();
    const tiles = within(screen.getByTestId('heatmap-grid')).getAllByRole('listitem');
    expect(tiles.map((t) => t.getAttribute('data-testid'))).toEqual(['heatmap-tile-b', 'heatmap-tile-a']);
    expect(tiles[0]).toHaveAttribute('data-heat', '4');
    expect(tiles[0]).toHaveTextContent('4 (2 props)');
    expect(tiles[0]).toHaveAttribute('title', expect.stringContaining('Beta: complexity 4'));
  });

  it('switches metric and relabels the legend', () => {
    renderDialog();
    const legend = screen.getByTestId('heatmap-legend');
    expect(legend).toHaveTextContent('Simpler');
    expect(legend).toHaveTextContent('More complex');

    fireEvent.click(screen.getByTestId('heatmap-metric-change'));
    expect(legend).toHaveTextContent('Changed recently');
    expect(screen.getByTestId('heatmap-tile-a')).toHaveAttribute('data-heat', '4');
    expect(screen.getByTestId('heatmap-tile-a')).toHaveTextContent('Today');
    expect(screen.getByTestId('heatmap-tile-b')).toHaveAttribute('data-heat', '0');

    fireEvent.click(screen.getByTestId('heatmap-metric-documentation'));
    expect(legend).toHaveTextContent('Fully documented');
    expect(screen.getByTestId('heatmap-tile-a')).toHaveTextContent('100%');
    expect(screen.getByTestId('heatmap-tile-b')).toHaveTextContent('0%');

    fireEvent.click(screen.getByTestId('heatmap-metric-references'));
    expect(screen.getByTestId('heatmap-tile-a')).toHaveTextContent('1 ref');
    expect(screen.getByRole('list', { name: 'Classes by references' })).toBeInTheDocument();
  });

  it('shows the loading state', () => {
    renderDialog({ isLoading: true, classes: null });
    expect(screen.getByText('Loading schema…')).toBeInTheDocument();
    expect(screen.queryByTestId('heatmap-grid')).not.toBeInTheDocument();
  });

  it('distinguishes an empty revision from a failed or missing load', () => {
    const { unmount } = renderDialog({ classes: [] });
    expect(screen.getByTestId('heatmap-empty')).toHaveTextContent('This version has no classes yet.');
    unmount();
    renderDialog({ classes: null });
    expect(screen.getByTestId('heatmap-empty')).toHaveTextContent('No schema data loaded.');
  });
});

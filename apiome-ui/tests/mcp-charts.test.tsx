/**
 * Render + snapshot tests for the token-driven SVG chart kit (V2-MCP-28.3 / MCAT-14.3).
 *
 * Confirms the acceptance criteria that live in the components (not the pure helpers): each chart
 * renders an accessible `role="img"` figure with a hidden data table from fixture data; empty /
 * degenerate data renders an empty state rather than crashing; and the rendered markup is snapshotted
 * so unintended visual regressions surface in review.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  Sparkline,
  BarSeries,
  Donut,
  StackedTimeline,
  Radar,
  Heatmap,
  Gauge,
} from '../src/app/components/ui/mcp/charts';

describe('Sparkline', () => {
  it('renders an accessible figure with a data table from fixture data', () => {
    render(<Sparkline data={[1, 4, 2, 8]} title="Latency trend" />);
    expect(screen.getByRole('img', { name: 'Latency trend' })).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByRole('cell', { name: '8' })).toBeInTheDocument();
  });

  it('renders an empty state (not a crash) for no data', () => {
    render(<Sparkline data={[]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<Sparkline data={[62, 65, 61, 70, 80]} tone="emerald" title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('BarSeries', () => {
  const data = [
    { label: 'tools', value: 18 },
    { label: 'prompts', value: 3 },
  ];

  it('renders one rect per bar and a data table', () => {
    const { container } = render(<BarSeries data={data} title="Surface" />);
    expect(container.querySelectorAll('rect')).toHaveLength(2);
    expect(screen.getByRole('cell', { name: '18' })).toBeInTheDocument();
  });

  it('renders an empty state for no bars', () => {
    render(<BarSeries data={[]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<BarSeries data={data} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('Donut', () => {
  const segments = [
    { label: 'http', value: 12 },
    { label: 'sse', value: 8 },
  ];

  it('renders one arc path per positive segment', () => {
    const { container } = render(<Donut segments={segments} title="Transport" centerLabel="20" />);
    // base track circle + two segment paths
    expect(container.querySelectorAll('path')).toHaveLength(2);
    expect(screen.getByText('20')).toBeInTheDocument();
  });

  it('renders an empty state when every value is zero', () => {
    render(<Donut segments={[{ label: 'a', value: 0 }]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<Donut segments={segments} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('StackedTimeline', () => {
  const series = [
    { key: 'added', label: 'Added' },
    { key: 'removed', label: 'Removed' },
  ];
  const periods = [
    { label: 'v1', values: { added: 4, removed: 0 } },
    { label: 'v2', values: { added: 2, removed: 3 } },
  ];

  it('renders a header + row per period in the fallback table', () => {
    render(<StackedTimeline series={series} periods={periods} title="Churn" />);
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Added' })).toBeInTheDocument();
    expect(within(table).getByRole('rowheader', { name: 'v2' })).toBeInTheDocument();
  });

  it('renders an empty state when there are no periods', () => {
    render(<StackedTimeline series={series} periods={[]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<StackedTimeline series={series} periods={periods} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('Radar', () => {
  const axes = [
    { label: 'Docs', value: 82 },
    { label: 'Safety', value: 90 },
    { label: 'Simplicity', value: 70 },
  ];

  it('renders the value polygon and a data table', () => {
    const { container } = render(<Radar axes={axes} max={100} title="Profile" />);
    // rings + value polygon are all <polygon>; assert the value polygon exists
    expect(container.querySelectorAll('polygon').length).toBeGreaterThan(0);
    expect(screen.getByRole('cell', { name: '82' })).toBeInTheDocument();
  });

  it('renders an empty state for fewer than three axes', () => {
    render(<Radar axes={[{ label: 'a', value: 1 }, { label: 'b', value: 2 }]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<Radar axes={axes} max={100} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('Heatmap', () => {
  const matrix = [
    [0, 2, 4],
    [1, 3, 5],
  ];

  it('renders one cell per matrix position and a labelled table', () => {
    const { container } = render(
      <Heatmap matrix={matrix} rowLabels={['a', 'b']} colLabels={['x', 'y', 'z']} title="Density" />,
    );
    expect(container.querySelectorAll('rect')).toHaveLength(6);
    expect(screen.getByRole('rowheader', { name: 'a' })).toBeInTheDocument();
  });

  it('renders an empty state for an empty matrix', () => {
    render(<Heatmap matrix={[]} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<Heatmap matrix={matrix} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe('Gauge', () => {
  it('renders the value in the center and a data table', () => {
    const { container } = render(<Gauge value={94} title="Score" />);
    expect(container.querySelector('text')?.textContent).toBe('94');
    expect(screen.getByRole('cell', { name: '94' })).toBeInTheDocument();
  });

  it('supports a custom domain and label without score-band coloring', () => {
    const { container } = render(<Gauge value={420} min={0} max={1000} tone="blue" centerLabel="420ms" />);
    expect(screen.getByText('420ms')).toBeInTheDocument();
    // the value arc uses the blue token stroke
    expect(container.querySelector('.stroke-blue-500')).toBeInTheDocument();
  });

  it('renders an empty state for a non-finite value', () => {
    render(<Gauge value={Number.NaN} />);
    expect(screen.getByRole('img', { name: /No data/ })).toBeInTheDocument();
  });

  it('matches its snapshot', () => {
    const { container } = render(<Gauge value={61} title="snap" />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

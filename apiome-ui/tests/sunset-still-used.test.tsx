/**
 * Sunset readiness in the UI — RDG-5.3 (#5788).
 *
 * The rules behind "Still used by N consumers" (`sunsetUsageView`, `stillUsedByRevision`), the
 * shared line component, and the `sunset_still_used` inbox row: its sentence, its link (an
 * `/ade/` path only) and its glyph. The screens that draw the line are pinned in
 * `sunset-timeline-hive-redesign.test.tsx` and `published-hive-redesign.test.tsx`.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { SunsetStillUsed } from '../src/app/components/ade/sunset/SunsetStillUsed';
import {
  SUNSET_USAGE_HANDLE_LIMIT,
  stillUsedByRevision,
  sunsetUsageView,
  type SunsetEntry,
  type SunsetUsage,
} from '../src/app/components/ade/sunset/sunsetModel';
import { NOTIFICATION_TYPE_ICONS } from '../src/app/components/ade/notifications/NotificationRowContent';
import {
  NOTIFICATION_TYPE_DESCRIPTIONS,
  NOTIFICATION_TYPE_LABELS,
  notificationContext,
  notificationHref,
  notificationSentence,
  type NotificationRow,
} from '../lib/notifications';

/** A `stillUsed` block, bound by default. */
function usage(overrides: Partial<SunsetUsage> = {}): SunsetUsage {
  return {
    windowDays: 7,
    environment: 'prod',
    state: 'bound',
    summary: 'Still used by 2 consumers (1,240 calls, 7-day)',
    calls: 1240,
    boundCalls: 1240,
    anonymousCalls: 0,
    consumerCount: 2,
    consumers: [
      { id: 'c1', slug: 'billing-service', name: 'Billing', calls: 1000 },
      { id: 'c2', slug: 'orders-web', name: 'Orders web', calls: 240 },
    ],
    consumersVisible: true,
    consumersHref: '/ade/dashboard/projects/p1/consumers',
    ...overrides,
  };
}

describe('sunsetUsageView', () => {
  it('reads a bound line with its handles and the Consumers link', () => {
    expect(sunsetUsageView(usage())).toEqual({
      state: 'bound',
      summary: 'Still used by 2 consumers (1,240 calls, 7-day)',
      handles: ['billing-service', 'orders-web'],
      moreHandles: 0,
      href: '/ade/dashboard/projects/p1/consumers',
      linkLabel: 'Consumers',
    });
  });

  it('names at most three handles and counts the rest', () => {
    const consumers = ['a', 'b', 'c', 'd', 'e'].map((slug) => ({ id: slug, slug, name: slug, calls: 1 }));
    const view = sunsetUsageView(usage({ consumers, consumerCount: 5 }));
    expect(view?.handles).toEqual(['a', 'b', 'c']);
    expect(view?.handles).toHaveLength(SUNSET_USAGE_HANDLE_LIMIT);
    expect(view?.moreHandles).toBe(2);
  });

  it('keeps the count but no handles when names are hidden', () => {
    const view = sunsetUsageView(usage({ consumers: null, consumersVisible: false }));
    expect(view?.handles).toEqual([]);
    expect(view?.summary).toContain('2 consumers');
  });

  it('links an anonymous-only line to binding, and an idle one nowhere', () => {
    const anonymous = sunsetUsageView(
      usage({ state: 'anonymous', summary: 'Anonymous traffic only — bind consumers to attribute it', consumers: [] })
    );
    expect(anonymous?.linkLabel).toBe('Bind consumers');
    expect(anonymous?.href).toBe('/ade/dashboard/projects/p1/consumers');
    expect(sunsetUsageView(usage({ state: 'unused', summary: 'No traffic in the last 7 days' }))?.href).toBeNull();
  });

  it('is nothing without evidence', () => {
    expect(sunsetUsageView(null)).toBeNull();
    expect(sunsetUsageView(undefined)).toBeNull();
    expect(sunsetUsageView(usage({ summary: '  ' }))).toBeNull();
  });
});

describe('stillUsedByRevision', () => {
  it('indexes only the rows that carry a block', () => {
    const base = { projectId: 'p1', versionLine: 'v1', timelineStatus: 'imminent', lifecyclePhase: 'deprecated',
      published: true, deprecationWarnings: [] };
    const rows: SunsetEntry[] = [
      { ...base, revisionId: 'r1', stillUsed: usage() },
      { ...base, revisionId: 'r2', stillUsed: null },
      { ...base, revisionId: 'r3' },
    ];
    const map = stillUsedByRevision(rows);
    expect([...map.keys()]).toEqual(['r1']);
  });
});

describe('<SunsetStillUsed>', () => {
  it('draws the line, the handles and the link', () => {
    render(<SunsetStillUsed usage={usage()} testId="line" />);
    const line = screen.getByTestId('line');
    expect(line).toHaveClass('stl-usage');
    expect(line).toHaveAttribute('data-state', 'bound');
    expect(line).toHaveTextContent('Still used by 2 consumers (1,240 calls, 7-day)');
    expect(line).toHaveTextContent('billing-service, orders-web');
    expect(screen.getByRole('link', { name: 'Consumers' })).toHaveAttribute('href', '/ade/dashboard/projects/p1/consumers');
  });

  it('says how many handles it left out', () => {
    const consumers = ['a', 'b', 'c', 'd'].map((slug) => ({ id: slug, slug, name: slug, calls: 1 }));
    render(<SunsetStillUsed usage={usage({ consumers })} testId="line" />);
    expect(screen.getByTestId('line')).toHaveTextContent('a, b, c +1 more');
  });

  it('draws nothing without a block', () => {
    const { container } = render(<SunsetStillUsed usage={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('the sunset_still_used inbox row', () => {
  const row = (payload: Record<string, unknown>): NotificationRow =>
    ({
      id: 'n1',
      tenant_id: 't1',
      user_id: 'u1',
      type: 'sunset_still_used',
      payload,
      actor_id: null,
      actor_name: null,
      project_id: 'p1',
      version_id: 'v1',
      read_at: null,
      created_at: '2026-11-16T09:00:00Z',
    }) as unknown as NotificationRow;

  it('says what the sweep wrote', () => {
    const summary = '1.2.0 sunsets in 20 days and is still used by 2 consumers (1,240 calls, 7-day)';
    expect(notificationSentence(row({ summary }))).toBe(summary);
    expect(notificationSentence(row({}))).toBe('A version near its sunset is still in use');
  });

  it('names the project and the version on the quiet line', () => {
    expect(notificationContext(row({ project_name: 'Pets', version_label: '1.2.0' }))).toBe('Pets · 1.2.0');
  });

  it('links to the sunset timeline, and never off the app', () => {
    expect(notificationHref(row({ link: '/ade/dashboard/versions/sunset-timeline' }))).toBe(
      '/ade/dashboard/versions/sunset-timeline'
    );
    expect(notificationHref(row({ link: 'https://evil.example.com' }))).toBeNull();
  });

  it('has a label, a switch description and a glyph', () => {
    expect(NOTIFICATION_TYPE_LABELS.sunset_still_used).toBe('Sunsets still in use');
    expect(NOTIFICATION_TYPE_DESCRIPTIONS.sunset_still_used).toMatch(/30 days/);
    expect(NOTIFICATION_TYPE_ICONS.sunset_still_used).toBeDefined();
  });
});

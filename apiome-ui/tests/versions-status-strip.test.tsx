/**
 * The Versions status strip (HIVE-11.2, #5598).
 *
 * `versionsStatusItems` turns what the Versions page already derived — compatibility, what's
 * new, deprecation and the git-like "server is ahead" conflict — into `StatusStrip` items.
 * This suite pins the mapping (order, tones, labels, verbatim copy and actions) and the strip's
 * session key; `versions-hive-redesign.test.tsx` covers the strip inside the page.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import VersionsStatusStrip, {
  VERSIONS_STATUS_STORAGE_PREFIX,
  versionsStatusItems,
  type VersionsStatusInput,
} from '../src/app/components/ade/versions/VersionsStatusStrip';
import type {
  CompatibilityBanner,
  DeprecationBanner,
  WhatsNewBanner,
} from '../src/app/components/ade/versions/versionsModel';

const COMPAT: CompatibilityBanner = {
  tone: 'ok',
  title: 'Compatible.',
  body: 'v2.3.0 → v2.3.1 has 2 non-breaking and no breaking changes.',
  pairLabel: 'v2.3.0 → v2.3.1',
  publishedRevisionId: 'rev-231',
};

const WHATS_NEW: WhatsNewBanner = {
  versionId: 'rev-240',
  versionLabel: 'v2.4.0',
  status: 'draft',
  summary: 'Add refund reasons and payout webhooks',
};

const DEPRECATION: DeprecationBanner = {
  versionId: 'rev-220',
  versionLabel: 'v2.2.0',
  sunsetLabel: '30 Sep 2026 00:00 UTC',
  sunsetDayLabel: '30 Sep 2026',
  successorLabel: 'v2.3.1',
  message: 'Migrate to /payment-intents before sunset.',
};

/** Every status present, with spies for each action. */
function input(over: Partial<VersionsStatusInput> = {}): VersionsStatusInput {
  return {
    compatibility: COMPAT,
    whatsNew: WHATS_NEW,
    deprecation: DEPRECATION,
    serverAhead: {
      detail: 'Head moved to v2.4.1 after your last push.',
      onPull: jest.fn(),
      onOpenMerge: jest.fn(),
    },
    changesAvailable: true,
    onOpenChanges: jest.fn(),
    ...over,
  };
}

beforeEach(() => window.sessionStorage.clear());

describe('versionsStatusItems', () => {
  it('lists the statuses in reading order with their tones', () => {
    const items = versionsStatusItems(input());
    expect(items.map((item) => [item.id, item.tone])).toEqual([
      ['compat', 'ok'],
      ['whats-new', 'accent'],
      ['deprecation', 'warn'],
      ['server-ahead', 'warn'],
    ]);
  });

  it('leaves out every status that has nothing to say', () => {
    expect(
      versionsStatusItems(input({ compatibility: null, whatsNew: null, deprecation: null, serverAhead: null }))
    ).toEqual([]);
    expect(versionsStatusItems(input({ serverAhead: null })).map((item) => item.id)).not.toContain('server-ahead');
  });

  it('maps every compatibility verdict onto a strip tone, and labels the chip with the verdict', () => {
    const tone = (t: CompatibilityBanner['tone']) =>
      versionsStatusItems(input({ compatibility: { ...COMPAT, tone: t } }))[0].tone;
    expect(tone('ok')).toBe('ok');
    expect(tone('warn')).toBe('warn');
    expect(tone('danger')).toBe('danger');
    expect(tone('neutral')).toBe('accent');
    const pending = versionsStatusItems(
      input({ compatibility: { ...COMPAT, tone: 'neutral', title: 'Classification pending.', pairLabel: null } })
    )[0];
    expect(pending.label).toBe('Classification pending');
    expect(pending.detail).toBeUndefined();
  });

  it('drops the Changes actions when the Changes tab is not available', () => {
    const items = versionsStatusItems(input({ changesAvailable: false }));
    expect(items[0].actions).toBeUndefined();
    expect(items[1].actions).toBeUndefined();
  });

  it('gives a deprecation without a sunset no chip detail and a plain title', () => {
    const item = versionsStatusItems(
      input({ deprecation: { ...DEPRECATION, sunsetLabel: null, sunsetDayLabel: null } })
    ).find((i) => i.id === 'deprecation')!;
    expect(item.detail).toBeUndefined();
    expect(item.title).toBe('v2.2.0 is deprecated.');
  });
});

describe('VersionsStatusStrip', () => {
  it('opens the first warn status and keeps the deprecation copy and actions verbatim', () => {
    render(<VersionsStatusStrip projectId="p1" {...input({ serverAhead: null })} />);
    const group = screen.getByRole('group', { name: 'Project status' });
    expect(within(group).getByRole('button', { name: /v2\.2\.0 deprecated/ })).toHaveAttribute('aria-expanded', 'true');
    const detail = document.querySelector('.status-strip__detail') as HTMLElement;
    expect(detail).toHaveTextContent(
      'v2.2.0 is deprecated — sunset 30 Sep 2026 00:00 UTC. Successor v2.3.1. Migrate to /payment-intents before sunset. Consumers see the same warning on compatibility checks (#507).'
    );
    expect(within(detail).getByRole('link', { name: 'Sunset timeline' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions/sunset-timeline'
    );
    expect(within(detail).getByRole('link', { name: 'Migration guide' })).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('draws the server-ahead chip with Pull and Open merge, and the API detail', () => {
    const props = input({ compatibility: null, whatsNew: null, deprecation: null });
    render(<VersionsStatusStrip projectId="p1" {...props} />);
    // One status: the chip renders already open and there is no Collapse button.
    expect(screen.getByRole('button', { name: /Server ahead/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('button', { name: /Collapse/ })).not.toBeInTheDocument();
    const detail = document.querySelector('.status-strip__detail') as HTMLElement;
    expect(detail).toHaveTextContent('Server is ahead of your last push. Pull to integrate or open a merge.');
    expect(detail).toHaveTextContent('Head moved to v2.4.1 after your last push.');
    fireEvent.click(within(detail).getByRole('button', { name: 'Pull' }));
    fireEvent.click(within(detail).getByRole('button', { name: 'Open merge' }));
    expect(props.serverAhead!.onPull).toHaveBeenCalledTimes(1);
    expect(props.serverAhead!.onOpenMerge).toHaveBeenCalledTimes(1);
  });

  it('shows Pulling… and disables Pull while a pull runs', () => {
    const props = input({ compatibility: null, whatsNew: null, deprecation: null });
    render(<VersionsStatusStrip projectId="p1" {...props} serverAhead={{ ...props.serverAhead!, pullLoading: true }} />);
    expect(screen.getByRole('button', { name: 'Pulling…' })).toBeDisabled();
  });

  it('remembers the open chip under hive.versions.status.<projectId>', () => {
    render(<VersionsStatusStrip projectId="p1" {...input()} />);
    fireEvent.click(screen.getByRole('button', { name: /What’s new/ }));
    expect(window.sessionStorage.getItem(`${VERSIONS_STATUS_STORAGE_PREFIX}p1`)).toBe('"whats-new"');
    expect(window.sessionStorage.getItem('hive.versions.status.p1')).toBe('"whats-new"');
    // Nothing under the primitive's default namespace.
    expect(window.sessionStorage.getItem('hive.statusStrip.p1')).toBeNull();
  });

  it('renders nothing when no status applies', () => {
    const { container } = render(
      <VersionsStatusStrip
        projectId="p1"
        {...input({ compatibility: null, whatsNew: null, deprecation: null, serverAhead: null })}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });
});

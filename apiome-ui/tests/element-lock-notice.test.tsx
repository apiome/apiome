/**
 * The presence components (COL-4.1, #4525): avatars and the lock/takeover notice.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { ElementLockNotice } from '../src/app/components/ade/presence/ElementLockNotice';
import { PresenceAvatars } from '../src/app/components/ade/presence/PresenceAvatars';
import type { PresenceLock, PresenceSnapshot } from '../lib/presence';

const KEY = 'class:1';
const base = (locks: PresenceLock[] = [], lost: string[] = []): PresenceSnapshot => ({
  viewers: [
    { user_id: 'me', name: 'Alice Anders', views: ['project'], sessions: 1 },
    { user_id: 'bob', name: 'Bob Brown', views: ['studio'], sessions: 2 },
  ],
  locks,
  lost,
  server_time: '',
  ttl_seconds: 45,
});
const bobsLock = (takeover: PresenceLock['takeover'] = null): PresenceLock => ({
  element_key: KEY,
  holder_user_id: 'bob',
  holder_name: 'Bob Brown',
  holder_session_id: 'tab-bob',
  acquired_at: '',
  expires_at: '',
  takeover,
});
const handlers = () => ({
  onRequestTakeover: jest.fn(),
  onTakeOver: jest.fn(),
  onRelease: jest.fn(),
  onDismissLost: jest.fn(),
});

describe('PresenceAvatars', () => {
  it('draws the other viewers but not the caller', () => {
    render(<PresenceAvatars snapshot={base()} selfUserId="me" />);
    expect(screen.getByLabelText('1 other person viewing this project')).toBeTruthy();
    expect(screen.getByText('BB')).toBeTruthy();
    expect(screen.queryByText('AA')).toBeNull();
  });
  it('renders nothing when alone', () => {
    const { container } = render(<PresenceAvatars snapshot={{ ...base(), viewers: [base().viewers[0]] }} selfUserId="me" />);
    expect(container.firstChild).toBeNull();
  });
});

describe('ElementLockNotice', () => {
  const props = { elementKey: KEY, sessionId: 'tab-alice', selfUserId: 'me', lost: [] as string[], now: 0 };

  it('shows nothing for a free element', () => {
    const { container } = render(<ElementLockNotice {...props} snapshot={base()} {...handlers()} />);
    expect(container.firstChild).toBeNull();
  });

  it('tells others who is editing and lets them ask to take over', () => {
    const h = handlers();
    render(<ElementLockNotice {...props} snapshot={base([bobsLock()])} {...h} />);
    expect(screen.getByText('Bob Brown is editing this')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Ask to take over' }));
    expect(h.onRequestTakeover).toHaveBeenCalledWith(KEY);
  });

  it('enables Take over only after the grace period', () => {
    const asked = bobsLock({ user_id: 'me', name: 'Alice Anders', requested_at: '', can_force_after: '2026-11-14T00:00:15Z' });
    const h = handlers();
    const early = render(<ElementLockNotice {...props} snapshot={base([asked])} now={Date.parse('2026-11-14T00:00:05Z')} {...h} />);
    expect((screen.getByRole('button', { name: 'Take over' }) as HTMLButtonElement).disabled).toBe(true);
    early.unmount();
    render(<ElementLockNotice {...props} snapshot={base([asked])} now={Date.parse('2026-11-14T00:00:20Z')} {...h} />);
    fireEvent.click(screen.getByRole('button', { name: 'Take over' }));
    expect(h.onTakeOver).toHaveBeenCalledWith(KEY);
  });

  it('prompts the holder when someone asks, and Hand over releases', () => {
    const mine: PresenceLock = { ...bobsLock({ user_id: 'bob', name: 'Bob Brown', requested_at: '', can_force_after: '' }), holder_user_id: 'me', holder_session_id: 'tab-alice' };
    const h = handlers();
    render(<ElementLockNotice {...props} snapshot={base([mine])} {...h} />);
    expect(screen.getByRole('alert').textContent).toContain('Bob Brown asked to take over');
    fireEvent.click(screen.getByRole('button', { name: 'Hand over' }));
    expect(h.onRelease).toHaveBeenCalledWith(KEY);
  });

  it('notifies the previous holder after a takeover', () => {
    const h = handlers();
    render(<ElementLockNotice {...props} lost={[KEY]} snapshot={base([bobsLock()], [KEY])} {...h} />);
    expect(screen.getByRole('status').textContent).toContain('Bob Brown took over this element');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(h.onDismissLost).toHaveBeenCalled();
  });
});

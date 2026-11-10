/**
 * The shared unsaved-changes guard (SUX-2.6, apiome#6753).
 *
 * Pins the four answers the acceptance criteria name — with a dirty form, a link click and Back
 * both ask; **Discard** leaves, **Save** saves then leaves, **Cancel** stays — plus the two that
 * keep it honest: a clean form never asks, and a failed save stays. The click classifier and the
 * sentinel helpers are tested on their own below.
 */

import * as React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const push = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push,
    replace: jest.fn(),
    back: jest.fn(),
    prefetch: jest.fn(),
  }),
}));

import { useUnsavedChangesGuard } from '../src/app/hooks/useUnsavedChangesGuard';
import {
  UNSAVED_GUARD_HISTORY_KEY,
  inAppNavigationTarget,
  isUnsavedGuardSentinel,
} from '../src/app/hooks/unsavedChangesNavigation';

/** Props for {@link GuardedForm}. */
interface GuardedFormProps {
  dirty: boolean;
  onSave?: () => boolean | void | Promise<boolean | void>;
  onDiscard?: () => void;
  onCustom?: () => void;
}

/**
 * A screen with a guard, two links and a self-made move.
 *
 * @param props See {@link GuardedFormProps}.
 * @returns The screen.
 */
function GuardedForm({ dirty, onSave, onDiscard, onCustom }: GuardedFormProps) {
  const guard = useUnsavedChangesGuard({ dirty, onSave, onDiscard });
  return (
    <div>
      <span data-testid="dirty">{String(guard.dirty)}</span>
      <a href="/other?x=1">Rail link</a>
      <a href="#section">Hash link</a>
      <a href="https://example.com/away">External</a>
      <a href="/new-tab" target="_blank">
        New tab
      </a>
      <a href="/ignored" data-unsaved-guard="ignore">
        Ignored
      </a>
      <button type="button" onClick={() => guard.confirmLeave(() => onCustom?.())}>
        Switch item
      </button>
      {guard.dialog}
    </div>
  );
}

/**
 * Click a link and report whether the guard intercepted it.
 *
 * The guard stops the click at `document` in the capture phase, so a listener on the link itself
 * never runs when it intercepted. When it did not, that listener cancels the default so jsdom does
 * not try (and fail) to navigate.
 *
 * @param name The link's accessible name.
 * @returns True when the guard intercepted the click.
 */
function clickLink(name: string): boolean {
  const link = screen.getByRole('link', { name });
  let intercepted = true;
  const observe = (event: Event) => {
    intercepted = event.defaultPrevented;
    event.preventDefault();
  };
  link.addEventListener('click', observe);
  fireEvent.click(link);
  link.removeEventListener('click', observe);
  return intercepted;
}

/** Wait for jsdom's asynchronous history traversal to settle. */
async function settleHistory(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

beforeEach(async () => {
  push.mockClear();
  // Let the previous test's unmount finish removing its sentinel before resetting the entry.
  await settleHistory();
  window.history.replaceState({ page: 'start' }, '', '/start');
});

describe('useUnsavedChangesGuard — clean', () => {
  it('never asks, never registers beforeunload, never pushes a sentinel', () => {
    const add = jest.spyOn(window, 'addEventListener');
    const before = window.history.length;
    render(<GuardedForm dirty={false} />);

    expect(clickLink('Rail link')).toBe(false);
    expect(screen.queryByTestId('unsaved-changes-dialog')).not.toBeInTheDocument();
    expect(add.mock.calls.some(([type]) => type === 'beforeunload')).toBe(false);
    expect(window.history.length).toBe(before);
    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
    add.mockRestore();
  });

  it('runs a self-made move at once', () => {
    const onCustom = jest.fn();
    render(<GuardedForm dirty={false} onCustom={onCustom} />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch item' }));
    expect(onCustom).toHaveBeenCalledTimes(1);
  });
});

describe('useUnsavedChangesGuard — dirty', () => {
  it('asks before the tab closes', () => {
    render(<GuardedForm dirty />);
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it('exposes dirty for the FormFrame footer and pushes one sentinel entry', () => {
    render(<GuardedForm dirty />);
    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
    expect(isUnsavedGuardSentinel(window.history.state)).toBe(true);
    // The existing state (Next.js keeps its router tree there) is carried onto the sentinel.
    expect(window.history.state.page).toBe('start');
  });

  it('asks on a rail link click; Cancel stays', async () => {
    render(<GuardedForm dirty />);
    expect(clickLink('Rail link')).toBe(true);
    expect(await screen.findByTestId('unsaved-changes-dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('unsaved-changes-cancel'));
    await waitFor(() =>
      expect(screen.queryByTestId('unsaved-changes-dialog')).not.toBeInTheDocument()
    );
    expect(push).not.toHaveBeenCalled();
  });

  it('Discard calls onDiscard and navigates', async () => {
    const onDiscard = jest.fn();
    render(<GuardedForm dirty onDiscard={onDiscard} />);
    clickLink('Rail link');
    fireEvent.click(await screen.findByTestId('unsaved-changes-discard'));

    expect(onDiscard).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(push).toHaveBeenCalledWith('/other?x=1'));
  });

  it('Save saves, then navigates', async () => {
    const order: string[] = [];
    const onSave = jest.fn(async () => {
      order.push('save');
      return true;
    });
    push.mockImplementationOnce(() => order.push('push'));
    render(<GuardedForm dirty onSave={onSave} />);
    clickLink('Rail link');
    fireEvent.click(await screen.findByTestId('unsaved-changes-save'));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/other?x=1'));
    expect(order).toEqual(['save', 'push']);
  });

  it('a failed save stays on the page', async () => {
    const onSave = jest.fn(async () => false);
    render(<GuardedForm dirty onSave={onSave} />);
    clickLink('Rail link');
    fireEvent.click(await screen.findByTestId('unsaved-changes-save'));

    await waitFor(() =>
      expect(screen.queryByTestId('unsaved-changes-dialog')).not.toBeInTheDocument()
    );
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
  });

  it('a save that throws stays on the page', async () => {
    const onSave = jest.fn(async () => {
      throw new Error('network');
    });
    render(<GuardedForm dirty onSave={onSave} />);
    clickLink('Rail link');
    fireEvent.click(await screen.findByTestId('unsaved-changes-save'));
    await waitFor(() =>
      expect(screen.queryByTestId('unsaved-changes-dialog')).not.toBeInTheDocument()
    );
    expect(push).not.toHaveBeenCalled();
  });

  it('offers Save only when onSave is given', async () => {
    render(<GuardedForm dirty />);
    clickLink('Rail link');
    await screen.findByTestId('unsaved-changes-dialog');
    expect(screen.queryByTestId('unsaved-changes-save')).not.toBeInTheDocument();
    expect(screen.getByTestId('unsaved-changes-discard')).toBeInTheDocument();
  });

  it.each(['Hash link', 'External', 'New tab', 'Ignored'])('lets "%s" through', (name) => {
    render(<GuardedForm dirty />);
    expect(clickLink(name)).toBe(false);
    expect(screen.queryByTestId('unsaved-changes-dialog')).not.toBeInTheDocument();
  });

  it('lets modifier clicks (open in new tab) through', () => {
    render(<GuardedForm dirty />);
    const link = screen.getByRole('link', { name: 'Rail link' });
    const event = new MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      metaKey: true,
    });
    let reachedLink = false;
    const observe = (e: Event) => {
      reachedLink = true;
      e.preventDefault();
    };
    link.addEventListener('click', observe);
    link.dispatchEvent(event);
    link.removeEventListener('click', observe);
    expect(reachedLink).toBe(true);
  });

  it('guards a self-made move with confirmLeave', async () => {
    const onCustom = jest.fn();
    render(<GuardedForm dirty onCustom={onCustom} />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch item' }));
    expect(onCustom).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('unsaved-changes-discard'));
    expect(onCustom).toHaveBeenCalledTimes(1);
  });

  it('asks on Back; Cancel returns to the sentinel, Discard goes back', async () => {
    // A page the user came from, so there is somewhere for Discard to go back to.
    window.history.replaceState({ page: 'previous' }, '', '/previous');
    window.history.pushState({ page: 'start' }, '', '/start');
    const routerPopState = jest.fn();
    window.addEventListener('popstate', routerPopState);
    render(<GuardedForm dirty />);
    expect(isUnsavedGuardSentinel(window.history.state)).toBe(true);

    act(() => window.history.back());
    await settleHistory();
    expect(await screen.findByTestId('unsaved-changes-dialog')).toBeInTheDocument();
    // The App Router (and any other bubble listener) never saw the traversal.
    expect(routerPopState).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('unsaved-changes-cancel'));
    await settleHistory();
    expect(isUnsavedGuardSentinel(window.history.state)).toBe(true);
    expect(routerPopState).not.toHaveBeenCalled();

    act(() => window.history.back());
    await settleHistory();
    fireEvent.click(await screen.findByTestId('unsaved-changes-discard'));
    await settleHistory();
    // This traversal is the real departure, so the router does see it.
    expect(routerPopState).toHaveBeenCalled();
    expect(window.location.pathname).toBe('/previous');
    window.removeEventListener('popstate', routerPopState);
  });

  it('removes the sentinel once the form is clean again', async () => {
    const { rerender } = render(<GuardedForm dirty />);
    expect(isUnsavedGuardSentinel(window.history.state)).toBe(true);
    rerender(<GuardedForm dirty={false} />);
    await settleHistory();
    expect(isUnsavedGuardSentinel(window.history.state)).toBe(false);
    expect(window.history.state.page).toBe('start');
  });
});

describe('inAppNavigationTarget', () => {
  const location = {
    href: 'https://app.test/authoring/slate?project=p1',
    origin: 'https://app.test',
    pathname: '/authoring/slate',
    search: '?project=p1',
  };

  /**
   * Classify a click on a fresh anchor, from inside its own handler (before any default runs).
   *
   * @param attrs Attributes for the anchor.
   * @param init Mouse event options.
   * @returns The classifier's answer.
   */
  function classify(attrs: Record<string, string>, init: MouseEventInit = {}): string | null {
    const anchor = document.createElement('a');
    Object.entries(attrs).forEach(([key, value]) => anchor.setAttribute(key, value));
    const inner = document.createElement('span');
    anchor.appendChild(inner);
    document.body.appendChild(anchor);
    let answer: string | null = 'unset';
    inner.addEventListener('click', (event) => {
      answer = inAppNavigationTarget(event, location);
      event.preventDefault();
    });
    inner.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
    anchor.remove();
    return answer;
  }

  it('returns the destination for a same-origin route change', () => {
    expect(classify({ href: '/authoring/scribe?project=p1#top' })).toBe(
      '/authoring/scribe?project=p1#top'
    );
    expect(classify({ href: '/authoring/slate?project=p2' })).toBe('/authoring/slate?project=p2');
  });

  it('ignores clicks that do not leave the screen', () => {
    expect(classify({ href: '/authoring/slate?project=p1#faq' })).toBeNull();
    expect(classify({ href: 'https://elsewhere.test/x' })).toBeNull();
    expect(classify({ href: '/x', target: '_blank' })).toBeNull();
    expect(classify({ href: '/x', download: '' })).toBeNull();
    expect(classify({ href: '/x', 'data-unsaved-guard': 'ignore' })).toBeNull();
    expect(classify({ href: '/x' }, { ctrlKey: true })).toBeNull();
    expect(classify({ href: '/x' }, { button: 1 })).toBeNull();
  });

  it('treats target="_self" as this tab', () => {
    expect(classify({ href: '/x', target: '_self' })).toBe('/x');
  });
});

describe('isUnsavedGuardSentinel', () => {
  it('recognises only the marked entry', () => {
    expect(isUnsavedGuardSentinel({ [UNSAVED_GUARD_HISTORY_KEY]: true })).toBe(true);
    expect(isUnsavedGuardSentinel({})).toBe(false);
    expect(isUnsavedGuardSentinel(null)).toBe(false);
    expect(isUnsavedGuardSentinel('x')).toBe(false);
  });
});

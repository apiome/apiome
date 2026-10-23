'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { Telescope } from 'lucide-react';

import { badgeVariants } from './Badge';
import { Button } from './Button';
import { ICON_SIZE, ICON_STROKE_WIDTH } from './iconSizes';
import { cn } from '@lib/utils';

/**
 * One quiet line naming what is not shipped yet (HIVE-12.5, #5612).
 *
 * Authority: `docs/mockups/proposals/launcher-focused.html` (`.next-line`, callout 3) and the
 * §10 rule `docs/mockups/PROPOSALS.md` proposes: *unreleased features appear once, as text,
 * never as disabled controls or dead buttons*.
 *
 * It replaces the pattern it was written against — a "Coming soon" card or row drawn at 60 %
 * opacity, which looks clickable, does nothing when clicked, and costs a whole tile of prime
 * space. Here an unshipped product is a word on one line, and the only interactive thing is a
 * real link to where progress is announced (What's new). There is deliberately no prop for a
 * disabled tag: nothing on this line can be in a state the reader would try to open.
 *
 * The launcher is the first user; HIVE-11.9 (Members) reuses it for the SSO/SCIM cards.
 */

/** One unshipped thing named on the line. */
export interface ComingNextItem {
  /** Stable id: the React key and the test handle. */
  id: string;
  /** What the tag says, e.g. `Developer Suite`. */
  label: string;
}

/** Props for {@link ComingNext}. */
export interface ComingNextProps {
  /** The unshipped things, in the order they should read. */
  items: readonly ComingNextItem[];
  /**
   * Open What's new in place — for a page that hosts the What's new dialog itself (the
   * launcher). Renders the follow link as a link-styled `<button>`.
   */
  onFollow?: () => void;
  /**
   * Navigate to where What's new lives — for a page that does not host the dialog. Ignored
   * when {@link onFollow} is given. With neither, the line has no link.
   */
  followHref?: string;
  /** Extra classes for the line, e.g. spacing from the content above it. */
  className?: string;
}

/** The link's text, as the mockup writes it. */
export const COMING_NEXT_FOLLOW_LABEL = 'Follow in What’s new';

/**
 * The "Coming next" line.
 *
 * @param props See {@link ComingNextProps}.
 * @returns The line, or `null` when there is nothing to announce — an empty "Coming next:"
 *          would be a promise with no content.
 */
export function ComingNext({ items, onFollow, followHref, className }: ComingNextProps) {
  if (items.length === 0) return null;

  let follow: ReactNode = null;
  if (onFollow) {
    follow = (
      <Button
        type="button"
        variant="link"
        size="sm"
        className="coming-next__follow"
        onClick={onFollow}
        data-testid="coming-next-follow"
      >
        {COMING_NEXT_FOLLOW_LABEL}
      </Button>
    );
  } else if (followHref) {
    follow = (
      <Link href={followHref} className="coming-next__follow" data-testid="coming-next-follow">
        {COMING_NEXT_FOLLOW_LABEL}
      </Link>
    );
  }

  return (
    // A paragraph, not a list: it reads as one sentence ("Coming next: A, B and C"), which
    // is how a screen reader should hear it too.
    <p className={cn('coming-next', className)} data-testid="coming-next">
      <Telescope
        size={ICON_SIZE.button}
        strokeWidth={ICON_STROKE_WIDTH}
        aria-hidden
        className="coming-next__icon"
      />
      <span>Coming next:</span>
      {items.map((item) => (
        <span
          key={item.id}
          className={cn(badgeVariants({ variant: 'outline' }), 'coming-next__tag')}
          data-testid={`coming-next-${item.id}`}
        >
          {item.label}
        </span>
      ))}
      {follow}
    </p>
  );
}

export default ComingNext;

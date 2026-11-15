'use client';

import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';

import {
  parseRecentlyShipped,
  WHATS_NEW_SOURCE_URL,
  type ShippedEntry,
} from './recentlyShippedModel';

/**
 * The launcher's "Recently shipped" card (HIVE-12.6, #5613).
 *
 * Authority: `docs/mockups/proposals/launcher-focused.html`, callout 4 (`.ship-row`). It sits
 * beside Resources where "On the roadmap" used to be, and lists the three newest What's new
 * entries — title, one line, release — so the launcher never advertises a feature the rail
 * already has. **All release notes** opens the What's new dialog.
 *
 * The card draws nothing until the notes have arrived, and nothing at all when they hold no
 * entries or could not be fetched: Resources then spans the row (`.launch-lower >
 * :only-child`). An empty "Recently shipped" heading would be the stale panel again.
 */

/** Props for {@link RecentlyShipped}. */
export interface RecentlyShippedProps {
  /** Opens the What's new dialog (and marks the build read) — the launcher's own handler. */
  onOpenNotes: () => void;
}

/**
 * Fetch the notes once and keep their newest entries.
 *
 * @returns The entries, or `null` until the fetch settles; an empty list on failure.
 */
function useShippedEntries(): ShippedEntry[] | null {
  const [entries, setEntries] = useState<ShippedEntry[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(WHATS_NEW_SOURCE_URL)
      .then((response) => (response.ok === false ? '' : response.text()))
      .then((text) => {
        if (!cancelled) setEntries(parseRecentlyShipped(text));
      })
      .catch(() => {
        // The launcher is the first page a reader loads; a missing card beats an error panel.
        if (!cancelled) setEntries([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return entries;
}

/**
 * The card.
 *
 * @param props The What's new opener — see {@link RecentlyShippedProps}.
 * @returns The card, or `null` while loading and when there is nothing to show.
 */
export default function RecentlyShipped({ onOpenNotes }: RecentlyShippedProps) {
  const entries = useShippedEntries();
  if (!entries || entries.length === 0) return null;

  return (
    <Card
      className="launch-panel"
      role="region"
      aria-labelledby="launch-shipped"
      data-testid="launch-recently-shipped"
    >
      <div className="launch-eyebrow">
        <h2 id="launch-shipped" className="hive-caps">
          Recently shipped
        </h2>
        <span className="launch-eyebrow__sub">From What’s new</span>
      </div>
      <ul className="launch-ship">
        {entries.map((entry, index) => (
          <li key={`${index}-${entry.title}`} className="launch-ship__row">
            <span className="launch-ship__dot" aria-hidden="true" />
            <span className="launch-ship__body">
              <span className="launch-ship__title">{entry.title}</span>
              {entry.summary ? <span className="launch-ship__sub">{entry.summary}</span> : null}
            </span>
            {entry.version ? <span className="launch-ship__when mono">{entry.version}</span> : null}
          </li>
        ))}
      </ul>
      <Button
        variant="ghost"
        size="sm"
        className="launch-ship__all"
        onClick={onOpenNotes}
        data-testid="launch-all-release-notes"
      >
        <Sparkles size={ICON_SIZE.dense} strokeWidth={ICON_STROKE_WIDTH} aria-hidden />
        All release notes
      </Button>
    </Card>
  );
}

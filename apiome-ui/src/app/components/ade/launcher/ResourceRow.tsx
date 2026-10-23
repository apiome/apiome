'use client';

import { ArrowRight, ArrowUpRight } from 'lucide-react';

import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';

import type { LauncherResource } from './launcherModel';

/**
 * One row in the launcher's Resources panel (HIVE-4.5, #5299).
 *
 * Authority: `docs/mockups/home/launcher.html` (`.res-row`).
 *
 * A row is a link, because every row is a destination that exists. The "Soon" and "Planned"
 * rows that used to be drawn as disabled buttons are gone (HIVE-12.5, #5612): an unshipped
 * destination is named once on the launcher's "Coming next" line instead.
 */

/** Props for {@link ResourceRow}. */
export interface ResourceRowProps {
  /** The row to draw. */
  item: LauncherResource;
}

/**
 * A resource row.
 *
 * @param props The row to draw — see {@link ResourceRowProps}.
 * @returns A link, opening in a new tab when the destination is another origin.
 */
export default function ResourceRow({ item }: ResourceRowProps) {
  const Icon = item.icon;

  return (
    <a
      href={item.href}
      {...(item.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      className="launch-tone launch-res"
      data-tone={item.tone}
      data-testid={`launch-resource-${item.id}`}
    >
      <span className="launch-tile launch-tile--sm">
        <Icon aria-hidden strokeWidth={ICON_STROKE_WIDTH} />
      </span>
      <span className="launch-res__body">
        <span className="launch-res__title">{item.name}</span>
        <span className="launch-res__sub">{item.description}</span>
      </span>
      <span aria-hidden="true">
        {item.external ? (
          <ArrowUpRight size={ICON_SIZE.dense} strokeWidth={ICON_STROKE_WIDTH} />
        ) : (
          <ArrowRight size={ICON_SIZE.dense} strokeWidth={ICON_STROKE_WIDTH} />
        )}
      </span>
    </a>
  );
}

'use client';

/**
 * The `gitlike` feature-flag marker (HIVE-6.2, #5313; quiet pass HIVE-13.1, #5614).
 *
 * Authority: `docs/mockups/build/versions.html` — its page-local flag chip, drawn beside the
 * affordances that `FEATURE_GITLIKE` gates: the Merge button, the Change report tab, the
 * server-ahead banner, the tag and branch panels, the history-graph strip, eight row-menu
 * items and the Delete/Freeze confirms.
 *
 * HIVE-13.1 took the honey out of it. DESIGN.md §2 reserves honey for brand ornament and says
 * outright that it is *never a feature-flag colour*: a feature-flag marker is
 * `.badge--outline`. So the flag is `Badge variant="outline"` with a flag glyph, in
 * `--fg-muted` on a hairline, and it is drawn **only when `FEATURE_GITLIKE` is on** — in a
 * build with the flag off the inert affordance says why through its `title`
 * ({@link GITLIKE_FLAG_TITLE}) rather than through a chip on every row.
 *
 * What it marks is decided by `gitlikeAffordance` in `versionsModel`; this only paints it.
 */

import * as React from 'react';
import { Flag } from 'lucide-react';
import { Badge, type BadgeProps } from '../../ui/Badge';
import { GITLIKE_FLAG_LABEL, GITLIKE_FLAG_ON_TITLE } from './versionsModel';

export interface GitlikeFlagProps extends Omit<BadgeProps, 'variant' | 'status' | 'data-status'> {
  /**
   * Whether `FEATURE_GITLIKE` is on for the affordance this marks — pass
   * `gitlikeAffordance().enabled`. Off (the default), nothing is drawn.
   */
  enabled?: boolean;
}

/**
 * Render the flag badge.
 *
 * @param props See {@link GitlikeFlagProps}; the rest lands on the `Badge`.
 * @returns The outline badge, or `null` when the flag is off.
 */
export function GitlikeFlag({ enabled = false, title, ...props }: GitlikeFlagProps) {
  if (!enabled) return null;
  return (
    <Badge
      variant="outline"
      title={title ?? GITLIKE_FLAG_ON_TITLE}
      data-testid="gitlike-flag"
      {...props}
    >
      <Flag aria-hidden />
      {GITLIKE_FLAG_LABEL}
    </Badge>
  );
}

export default GitlikeFlag;

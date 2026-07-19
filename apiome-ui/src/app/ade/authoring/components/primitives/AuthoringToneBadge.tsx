'use client';

/**
 * The one toned chip every Authoring primitive builds on (UXE-1.3).
 *
 * Release status, check status, phase status and content status all render as
 * a chip. Giving them one component is what guarantees the roadmap's §27.4
 * rule holds everywhere at once: a chip cannot be constructed without a text
 * label, and its icon is decorative, so meaning never rests on colour.
 *
 * It deliberately does not reuse `components/ui/Badge`, which is a marketing
 * chip with a different, non-semantic variant set (`error` rather than
 * `danger`, no `info`) and a `focus:ring` treatment that conflicts with the
 * shell's `focus-visible:outline`. Diverging vocabularies is exactly the
 * problem this ticket exists to end.
 */

import * as React from 'react';
import type { AuthoringTone } from '@lib/authoring/tokens';
import { cn } from '@lib/utils';
import {
  authoringBadgeBaseClass,
  authoringBadgeToneClass,
  authoringToneHookClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringToneBadge}. */
export type AuthoringToneBadgeProps = {
  /** Visible label. Required — a badge is never icon-only. */
  label: string;
  tone: AuthoringTone;
  /** Lucide icon name. Decorative; the label carries the meaning. */
  icon?: string;
  /**
   * Sentence explaining the state, exposed to assistive technology via
   * `aria-describedby` so the label can stay short without losing the "what do
   * I do about it" half.
   */
  description?: string;
  className?: string;
};

/**
 * Render a semantic status chip.
 *
 * @param props - Label, tone and optional icon and description.
 */
export default function AuthoringToneBadge({
  label,
  tone,
  icon,
  description,
  className,
}: AuthoringToneBadgeProps) {
  // Stable per instance so several badges can coexist without colliding ids.
  const descriptionId = React.useId();

  return (
    <span
      className={cn(
        authoringBadgeBaseClass,
        authoringBadgeToneClass[tone],
        authoringToneHookClass[tone],
        className
      )}
      data-tone={tone}
      aria-describedby={description ? descriptionId : undefined}
    >
      {icon ? <AuthoringIcon name={icon} className="h-3.5 w-3.5 shrink-0" /> : null}
      {label}
      {description ? (
        <span id={descriptionId} className="sr-only">
          {description}
        </span>
      ) : null}
    </span>
  );
}

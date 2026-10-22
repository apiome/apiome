'use client';

/**
 * The read-only note for members (HIVE-11.10, #5606).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 1 and
 * `docs/mockups/PROPOSALS.md` finding 1. Style guides used to carry a standing *Read-only for
 * members* banner between the header and the table for every visit. It now shows once, as a
 * {@link DismissibleCallout}; after **Got it** the same sentence lives in the tooltip of a lock
 * beside the page title, so a member can still find out why the verbs are missing.
 *
 * Both parts draw {@link STYLE_GUIDES_READ_ONLY} verbatim — the copy is the banner's, unchanged.
 */

import * as React from 'react';
import { Lock } from 'lucide-react';

import { DismissibleCallout } from '@/app/components/ui/DismissibleCallout';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/app/components/ui/Tooltip';

import { STYLE_GUIDES_READ_ONLY } from './styleGuidesModel';

/** Props for {@link StyleGuidesReadOnlyCallout}. */
export interface StyleGuidesReadOnlyCalloutProps {
  /** Called after **Got it** — the page then shows the lock beside its title. */
  onDismiss?: () => void;
}

/**
 * The first-visit callout.
 *
 * @param props See {@link StyleGuidesReadOnlyCalloutProps}.
 * @returns The callout, or nothing once dismissed on this device.
 */
export function StyleGuidesReadOnlyCallout({ onDismiss }: StyleGuidesReadOnlyCalloutProps) {
  return (
    <DismissibleCallout
      id={STYLE_GUIDES_READ_ONLY.id}
      reopenFrom="Lock beside the page title"
      onDismiss={onDismiss}
    >
      <span data-testid="style-guides-readonly">
        <strong>{STYLE_GUIDES_READ_ONLY.title}</strong> {STYLE_GUIDES_READ_ONLY.body}
      </span>
    </DismissibleCallout>
  );
}

/**
 * The lock beside the title, once the callout has been dismissed.
 *
 * A `<button>` rather than a bare glyph so keyboard and touch readers can reach the tooltip; it
 * has no action of its own. Its accessible name is the short title and the tooltip (announced as
 * its description) carries the full sentence.
 */
export const StyleGuidesReadOnlyLock = React.forwardRef<HTMLButtonElement>(
  function StyleGuidesReadOnlyLock(_props, ref) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            ref={ref}
            type="button"
            className="sg-readonly-lock"
            aria-label={STYLE_GUIDES_READ_ONLY.title.replace(/\.$/, '')}
            data-testid="style-guides-readonly-lock"
          >
            <Lock aria-hidden />
          </button>
        </TooltipTrigger>
        <TooltipContent className="sg-readonly-tip" data-testid="style-guides-readonly-tip">
          <strong>{STYLE_GUIDES_READ_ONLY.title}</strong> {STYLE_GUIDES_READ_ONLY.body}
        </TooltipContent>
      </Tooltip>
    );
  }
);

'use client';

import * as React from 'react';

import { hasSeen, markSeen } from '../../../../lib/seen';
import { Alert } from './Alert';
import { Button } from './Button';

/**
 * DismissibleCallout — an explainer that shows once, then lives one click away
 * (HIVE-11.5, #5601).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` (annotation 4) and
 * `docs/mockups/PROPOSALS.md`. Several list pages opened with a standing explanatory banner
 * (≈ 75 px) that teaches once and costs forever. The callout shows on a reader's first visit
 * with **Learn more** (optional) and **Got it**; **Got it** hides it on this device for good.
 *
 * ```tsx
 * <DismissibleCallout
 *   id="catalog-explainer"
 *   reopenFrom="How the catalog works (page header)"
 *   onLearnMore={() => setAboutOpen(true)}
 * >
 *   <strong>Catalog items are non-publishable.</strong> Convert one to OpenAPI to publish it.
 * </DismissibleCallout>
 * ```
 *
 * ### Rules
 *
 * - **Dismissing never hides information.** `reopenFrom` names where the same content lives
 *   afterwards (a header link, a dialog). It is required, drawn as `data-reopen-from`, and
 *   `tests/copy-voice-gate.test.ts` fails on a callout that does not state it literally.
 * - Dismissal is stored under `hive.seen.<id>` in `localStorage` (`lib/seen.ts`): it survives a
 *   reload, clearing site data shows the callout again, and blocked storage never throws (the
 *   callout then hides for the rest of this visit only).
 * - Nothing renders until storage has been read after mount, so a returning reader never sees
 *   the callout flash in and out, and the server render matches the first client render.
 * - The callout is a `role="note"` — it is supplementary, not an alert, so it is not announced
 *   when the page loads.
 *
 * Drawn with the `Alert` banner, so its tint, icon and action row are the app's own.
 */

/** The tones a callout may take. */
export type DismissibleCalloutTone = 'accent' | 'neutral' | 'honey';

/** The `Alert` variant each tone is drawn with. */
const ALERT_VARIANT: Readonly<Record<DismissibleCalloutTone, 'info' | 'neutral' | 'honey'>> = {
  accent: 'info',
  neutral: 'neutral',
  honey: 'honey',
};

/** Props for {@link DismissibleCallout}. */
export interface DismissibleCalloutProps {
  /** Stable id; the dismissal is stored under `hive.seen.<id>`. */
  id: string;
  /** Where the content lives once dismissed, e.g. `How the catalog works (page header)`. */
  reopenFrom: string;
  /** The explainer. */
  children: React.ReactNode;
  /** Tint. Defaults to `accent`. */
  tone?: DismissibleCalloutTone;
  /** Replace the leading glyph. */
  icon?: React.ReactNode;
  /** Opens the fuller explanation; the **Learn more** button shows only when given. */
  onLearnMore?: () => void;
  /** Label for the learn-more button. Defaults to `Learn more`. */
  learnMoreLabel?: string;
  /**
   * Called after **Got it** hides the callout. The button the reader pressed is gone, so a
   * page that wants focus somewhere specific moves it here.
   */
  onDismiss?: () => void;
  /** Extra classes for the banner. */
  className?: string;
}

/**
 * A first-visit explainer with **Learn more** and **Got it**.
 *
 * @param props See {@link DismissibleCalloutProps}.
 * @returns The callout, or `null` once dismissed (and before storage has been read).
 */
export function DismissibleCallout({
  id,
  reopenFrom,
  children,
  tone = 'accent',
  icon,
  onLearnMore,
  learnMoreLabel = 'Learn more',
  onDismiss,
  className,
}: DismissibleCalloutProps) {
  // `null` until storage is read, then whether the callout should show.
  const [visible, setVisible] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    setVisible(!hasSeen(id));
  }, [id]);

  if (!visible) return null;

  /** Hides the callout and remembers that for this device. */
  const dismiss = () => {
    markSeen(id);
    setVisible(false);
    onDismiss?.();
  };

  return (
    <Alert
      role="note"
      variant={ALERT_VARIANT[tone]}
      icon={icon}
      data-reopen-from={reopenFrom}
      className={className}
      actions={
        <>
          {onLearnMore ? (
            <Button type="button" variant="ghost" size="sm" onClick={onLearnMore}>
              {learnMoreLabel}
            </Button>
          ) : null}
          <Button type="button" variant="outline" size="sm" onClick={dismiss}>
            Got it
          </Button>
        </>
      }
    >
      {children}
    </Alert>
  );
}

export default DismissibleCallout;

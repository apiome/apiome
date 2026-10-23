'use client';

import Link from 'next/link';
import { ArrowRight, ArrowUpRight, ExternalLink } from 'lucide-react';

import { cardVariants } from '@/app/components/ui/Card';
import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';
import { cn } from '@lib/utils';

import { launcherItemLabel, OPENS_IN_NEW_TAB, type LauncherApp } from './launcherModel';

/**
 * One application tile on the `/ade` launcher (HIVE-4.5, #5299).
 *
 * Authority: `docs/mockups/home/launcher.html` (`.app-card`).
 *
 * The card is drawn as whatever it actually *is*, which is the whole a11y story here:
 *
 * | State | Element | Why |
 * | --- | --- | --- |
 * | internal | `next/link` | a real link: middle-click, open-in-new-tab, and a client push |
 * | external | `<a target="_blank" rel="noopener noreferrer">` | announces its own new tab |
 *
 * There is no third, disabled state any more (HIVE-12.5, #5612): a product that cannot be
 * opened is not drawn as a card at all — `launcherApps()` leaves it out and the launcher names
 * it on its "Coming next" line.
 *
 * The card's hue comes from `data-tone`, resolved to tokens by the `.launch-tone` rules in
 * `globals.css`, so no colour is written here and a commercial host's card follows every
 * theme without knowing this app's palette.
 */

/** Props for {@link AppLaunchCard}. */
export interface AppLaunchCardProps {
  /** The tile to draw. */
  app: LauncherApp;
  /**
   * The footer's quiet line, when the page knows more than the model — the Control Panel's
   * "last opened" time, read from this device after mount. Defaults to `app.footerLabel`.
   */
  footerLabel?: string;
}

/**
 * The card's inner content, shared by both elements it can be rendered as.
 *
 * Every child is a `<span>`: the card is an `<a>`, whose content here is phrasing content.
 *
 * @param props.app The tile to draw.
 * @param props.footerLabel The footer's quiet line.
 * @returns The tile's glyph, copy and footer strip.
 */
function CardBody({ app, footerLabel }: { app: LauncherApp; footerLabel: string }) {
  const Icon = app.icon;

  return (
    <>
      <span className="launch-card__go" aria-hidden="true">
        {app.external ? (
          <ArrowUpRight size={ICON_SIZE.button} strokeWidth={ICON_STROKE_WIDTH} />
        ) : (
          <ArrowRight size={ICON_SIZE.button} strokeWidth={ICON_STROKE_WIDTH} />
        )}
      </span>

      <span className="launch-tile">
        <Icon aria-hidden strokeWidth={ICON_STROKE_WIDTH} />
      </span>

      <span className="launch-card__tag">{app.tagline}</span>
      <span className="launch-card__name">{app.name}</span>
      <span className="launch-card__desc">{app.description}</span>

      <span className="launch-card__foot">
        <span data-testid={`launch-card-foot-${app.id}`}>{footerLabel}</span>
        {app.external ? (
          <span>
            <ExternalLink size={ICON_SIZE.button} strokeWidth={ICON_STROKE_WIDTH} aria-hidden />
            {OPENS_IN_NEW_TAB}
          </span>
        ) : null}
      </span>
    </>
  );
}

/**
 * An application tile.
 *
 * @param props The tile to draw — see {@link AppLaunchCardProps}.
 * @returns A link, or an external link that opens in a new tab.
 */
export default function AppLaunchCard({ app, footerLabel = app.footerLabel }: AppLaunchCardProps) {
  const className = cn(
    cardVariants({ hover: true, link: true }),
    'launch-tone launch-card',
    app.primary && 'launch-card--primary'
  );
  const shared = {
    className,
    'data-tone': app.tone,
    'data-testid': `launch-app-${app.id}`,
    'aria-label': launcherItemLabel(app.name),
  };

  if (app.external) {
    return (
      // `noopener` is what keeps the new tab from reaching back through `window.opener`;
      // `noreferrer` keeps the launcher's URL out of the destination's referrer.
      <a href={app.href} target="_blank" rel="noopener noreferrer" {...shared}>
        <CardBody app={app} footerLabel={footerLabel} />
      </a>
    );
  }

  return (
    <Link href={app.href} {...shared}>
      <CardBody app={app} footerLabel={footerLabel} />
    </Link>
  );
}

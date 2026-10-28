'use client';

/**
 * CatalogDriftBanner (MFI-31.3, #4400) — the item page's notice that a live refresh found drift.
 *
 * Shown above the panes while the item has an undismissed drift event: the severity is the tint
 * (breaking → danger, dangerous → warn, safe → ok), the headline names the version, the body the
 * counts. **See what changed** opens the Versions tab on that drift (its classified changes and
 * the inline diff of the two versions); **Dismiss** clears the badge and the banner for everyone,
 * and is offered only to callers who may edit the item (`projects:edit`).
 */

import * as React from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  dismissDrift,
  driftBannerTitle,
  driftCountsText,
  DRIFT_SEVERITY_VIEW,
  type CatalogDriftBadgeData,
} from '../catalogDriftModel';

/** Severity tone → the `Alert` variant that tints it. */
const ALERT_VARIANT = { danger: 'danger', warn: 'warn', ok: 'ok' } as const;

export interface CatalogDriftBannerProps {
  /** The catalog item. */
  itemId: string;
  /** Its newest undismissed drift; `null` draws nothing. */
  drift: CatalogDriftBadgeData | null;
  /** Whether the caller may dismiss it (`projects:edit` on a live item). */
  canDismiss: boolean;
  /** Open the Versions tab on this drift. */
  onOpen: (eventId: string) => void;
  /** Called once the drift is dismissed, so the page can drop it. */
  onDismissed: (eventId: string) => void;
}

/**
 * Render the banner. See {@link CatalogDriftBannerProps}.
 *
 * @returns The banner, or `null` without drift.
 */
export function CatalogDriftBanner({ itemId, drift, canDismiss, onOpen, onDismissed }: CatalogDriftBannerProps) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (!drift) return null;
  const view = DRIFT_SEVERITY_VIEW[drift.severity];
  const variant = ALERT_VARIANT[view.tone as keyof typeof ALERT_VARIANT] ?? 'warn';

  const dismiss = async () => {
    setBusy(true);
    setError(null);
    try {
      await dismissDrift(itemId, drift.eventId);
      onDismissed(drift.eventId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The drift could not be dismissed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Alert
      variant={variant}
      role="status"
      className="cid-drift"
      data-testid="catalog-drift-banner"
      data-severity={drift.severity}
      actions={
        <>
          <Button size="sm" variant="outline" onClick={() => onOpen(drift.eventId)} data-testid="catalog-drift-open">
            See what changed
          </Button>
          {canDismiss ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void dismiss()}
              disabled={busy}
              title={busy ? 'Dismissing the drift' : 'Hide this drift for everyone; it stays in the item history'}
              data-testid="catalog-drift-dismiss"
            >
              Dismiss
            </Button>
          ) : null}
        </>
      }
    >
      <AlertTitle>{driftBannerTitle(drift)}</AlertTitle>
      <AlertDescription>
        {driftCountsText(drift.counts)}. {view.meaning}
        {error ? <span className="cid-drift__error"> {error}</span> : null}
      </AlertDescription>
    </Alert>
  );
}

'use client';

/**
 * The **Live refresh** card on a catalog item's Provenance tab — MFI-31.1 (#4398).
 *
 * Shows whether the item is re-checked against its live source and how the last check went: a
 * status pill, then the method, endpoint, cadence, credential, last checked, last failure (with
 * its reason) and next check. With `projects:edit` it offers **Set up refresh…** / **Edit
 * refresh…**, **Check now** (any cadence but Off) and **Turn off**. The card loads its data the
 * first time the tab is shown (`active`), like the other lazily-fetched panes.
 *
 * A failed check never changes the item: it is reported here and the next scheduled check backs
 * off. Whether a changed source becomes a new version is MFI-31.2's job, not this card's.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardBody, CardHeader, CardTitle } from '@/app/components/ui/Card';

import { CatalogRefreshDialog } from './CatalogRefreshDialog';
import {
  REFRESH_KEEP_VERSIONS_DEFAULT,
  formatRefreshTime,
  refreshAdapterLabel,
  refreshCadenceLabel,
  refreshCanCheck,
  refreshNextCheckText,
  refreshStatusView,
  type CatalogRefresh,
} from './catalogRefreshModel';

export interface CatalogItemRefreshCardProps {
  /** The item's id and name. */
  item: { id: string; name: string };
  /** True once the Provenance tab has been shown; the card fetches on the first `true`. */
  active: boolean;
  /** True when the caller may change the setting (`projects:edit` on a live item). */
  canEdit: boolean;
}

/**
 * Read a REST answer through the BFF, throwing its error message on failure.
 *
 * @param url The BFF URL.
 * @param init The fetch options.
 * @returns The parsed JSON.
 */
async function requestRefresh(url: string, init?: RequestInit): Promise<CatalogRefresh> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error(data?.error || 'The refresh setting could not be loaded.');
  }
  return data as CatalogRefresh;
}

/**
 * Render the card. See {@link CatalogItemRefreshCardProps}.
 *
 * @returns The card.
 */
export function CatalogItemRefreshCard({ item, active, canEdit }: CatalogItemRefreshCardProps) {
  const [refresh, setRefresh] = React.useState<CatalogRefresh | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<'check' | 'off' | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [dialogKey, setDialogKey] = React.useState(0);
  const loaded = React.useRef(false);
  const base = `/api/catalog/${encodeURIComponent(item.id)}/refresh`;

  React.useEffect(() => {
    if (!active || loaded.current) return;
    loaded.current = true;
    requestRefresh(base)
      .then(setRefresh)
      .catch((error: unknown) => setLoadError(error instanceof Error ? error.message : String(error)));
  }, [active, base]);

  const checkNow = async () => {
    setBusy('check');
    setActionError(null);
    try {
      setRefresh(await requestRefresh(`${base}/check`, { method: 'POST' }));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The check could not run.');
    } finally {
      setBusy(null);
    }
  };

  const turnOff = async () => {
    if (!refresh) return;
    setBusy('off');
    setActionError(null);
    try {
      const response = await fetch(base, { method: 'DELETE' });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.error || 'Refresh could not be turned off.');
      }
      setRefresh(await requestRefresh(base));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Refresh could not be turned off.');
    } finally {
      setBusy(null);
    }
  };

  const status = refresh ? refreshStatusView(refresh) : null;
  /** Why the buttons are disabled while an action runs (the voice gate wants every disabled button to say). */
  const busyReason = busy === 'check' ? 'A check is running' : busy === 'off' ? 'Turning refresh off' : undefined;
  const configured = Boolean(refresh?.configured);

  return (
    <Card data-testid="catalog-detail-refresh">
      <CardHeader className="cid-refresh__head">
        <div>
          <CardTitle>
            <RefreshCw aria-hidden />
            Live refresh
          </CardTitle>
          <p className="cid-note">Re-check this item against the live endpoint it describes</p>
        </div>
        {canEdit ? (
          <div className="cid-refresh__actions">
            {configured && refresh && refreshCanCheck(refresh) ? (
              <Button
                variant="outline"
                size="sm"
                disabled={busy !== null}
                title={busyReason}
                onClick={() => void checkNow()}
                data-testid="catalog-detail-refresh-check"
              >
                {busy === 'check' ? 'Checking…' : 'Check now'}
              </Button>
            ) : null}
            {configured ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy !== null}
                title={busyReason}
                onClick={() => void turnOff()}
                data-testid="catalog-detail-refresh-off"
              >
                Turn off
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null}
              title={busyReason}
              onClick={() => {
                setDialogKey((key) => key + 1);
                setDialogOpen(true);
              }}
              data-testid="catalog-detail-refresh-edit"
            >
              {configured ? 'Edit refresh…' : 'Set up refresh…'}
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardBody>
        {loadError ? (
          <p className="cid-refresh__error" role="alert">
            {loadError}
          </p>
        ) : !refresh ? (
          <p className="cid-note" data-testid="catalog-detail-refresh-loading">
            Loading…
          </p>
        ) : (
          <dl className="cid-kv" data-testid="catalog-detail-refresh-facts">
            <dt>Status</dt>
            <dd>
              <Badge variant={status!.tone} data-testid="catalog-detail-refresh-status">
                {status!.label}
              </Badge>
              {!refresh.tenantEnabled ? (
                <span className="cid-quiet">An administrator switched catalog refresh off for this workspace.</span>
              ) : null}
            </dd>
            {configured ? (
              <>
                <dt>Discover with</dt>
                <dd>{refreshAdapterLabel(refresh.adapter)}</dd>
                <dt>Endpoint</dt>
                <dd className="mono cid-refresh__endpoint" title={refresh.endpoint ?? undefined}>
                  {refresh.endpoint}
                </dd>
                <dt>Cadence</dt>
                <dd>{refreshCadenceLabel(refresh.cadence)}</dd>
                <dt>Credential</dt>
                <dd>{refresh.hasCredential ? 'Stored (encrypted)' : 'None'}</dd>
                <dt>Last checked</dt>
                <dd>{formatRefreshTime(refresh.lastCheckedAt)}</dd>
                {refresh.status === 'failed' ? (
                  <>
                    <dt>Last failure</dt>
                    <dd data-testid="catalog-detail-refresh-failure">
                      <span className="cid-refresh__error">{refresh.lastError}</span>
                      <span className="cid-quiet">
                        {refresh.consecutiveFailures === 1
                          ? '1 failed check in a row; the next one is delayed.'
                          : `${refresh.consecutiveFailures} failed checks in a row; the next one is delayed.`}
                      </span>
                    </dd>
                  </>
                ) : null}
                <dt>Next check</dt>
                <dd>{refreshNextCheckText(refresh)}</dd>
                <dt>Keeps</dt>
                <dd data-testid="catalog-detail-refresh-keep">
                  The newest {refresh.keepVersions ?? REFRESH_KEEP_VERSIONS_DEFAULT} refresh versions
                </dd>
              </>
            ) : (
              <>
                <dt>Source</dt>
                <dd className="cid-quiet">
                  Not set up. GraphQL and gRPC sources can be re-checked hourly, daily or weekly.
                </dd>
              </>
            )}
          </dl>
        )}
        {actionError ? (
          <p className="cid-refresh__error" role="alert" data-testid="catalog-detail-refresh-action-error">
            {actionError}
          </p>
        ) : null}
      </CardBody>

      {canEdit ? (
        <CatalogRefreshDialog
          key={dialogKey}
          open={dialogOpen}
          item={item}
          refresh={refresh}
          onOpenChange={setDialogOpen}
          onSaved={setRefresh}
        />
      ) : null}
    </Card>
  );
}

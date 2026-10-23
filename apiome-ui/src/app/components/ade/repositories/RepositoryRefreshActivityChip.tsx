'use client';

import * as React from 'react';
import { RefreshCw } from 'lucide-react';

import { badgeVariants } from '@/app/components/ui/Badge';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/app/components/ui/Drawer';
import { cn } from '@lib/utils';

import { RepositoryRefreshActivityPanelBody, type RefreshActivityState } from './RepositoryRefreshActivityPanel';
import { refreshActivityChip } from './repositoriesModel';

/**
 * Refresh activity, folded into the facts line — HIVE-11.7 (#5603).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` callout 3 and
 * `docs/mockups/PROPOSALS.md` finding 1. The always-open panel (≈ 240 px above the toolbar)
 * becomes one chip: `1 stale · 1 failed` in the warn tone while anything is stale or failed,
 * a quiet `Refresh activity` otherwise. Either way it opens the unchanged panel in a drawer, so
 * every count and every drill-in link is still one click away.
 */

/** Props for {@link RepositoryRefreshActivityChip}. */
export interface RepositoryRefreshActivityChipProps {
  /** The page's one read of refresh activity (`useRefreshActivity`). */
  state: RefreshActivityState;
}

/**
 * The chip and the drawer it opens.
 *
 * @param props See {@link RepositoryRefreshActivityChipProps}.
 * @returns A chip-styled button, plus the drawer while open.
 */
export function RepositoryRefreshActivityChip({ state }: RepositoryRefreshActivityChipProps) {
  const [open, setOpen] = React.useState(false);
  const chip = refreshActivityChip(state.summary?.counts ?? null);
  const attention = chip.count > 0;

  return (
    <>
      <button
        type="button"
        className={cn(badgeVariants({ variant: attention ? 'warn' : 'outline', size: 'lg' }), 'repo-refresh-chip')}
        aria-haspopup="dialog"
        aria-label={attention ? `Refresh activity: ${chip.text}` : 'Refresh activity'}
        data-count={chip.count}
        data-testid="refresh-activity-chip"
        onClick={() => setOpen(true)}
      >
        <RefreshCw aria-hidden />
        {chip.text}
      </button>
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent size="default" data-testid="refresh-activity-drawer">
          <DrawerHeader>
            <DrawerTitle>Refresh activity</DrawerTitle>
            <DrawerDescription>
              Auto-refresh health of the specs imported from your repositories.
            </DrawerDescription>
          </DrawerHeader>
          <DrawerBody>
            <RepositoryRefreshActivityPanelBody state={state} />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </>
  );
}

export default RepositoryRefreshActivityChip;

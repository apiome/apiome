'use client';

/**
 * The Owner cell every ownership-aware list draws — CDG-2.4 (#5963).
 *
 * * A **confirmed** owner is the team's name, linking to its team page.
 * * A **suggested** owner is the team's name with a "Suggested" badge naming where it came from,
 *   and a **Confirm** button. Confirming calls the owners API and hands the new owner back through
 *   `onChange`, so the list updates the row in place — no reload.
 * * No owner is a dash, announced as "No owner".
 */

import * as React from 'react';
import Link from 'next/link';
import { isFeatureReleased } from '@lib/feature-release';
import { Badge, Button } from '@/app/components/ui';
import {
  ownerDescription,
  ownerSourceLabel,
  type EntityOwner,
  type OwnerEntityKind,
} from '@lib/owners';
import { confirmOwner } from './ownersApi';

/** Props for {@link OwnerCell}. */
export interface OwnerCellProps {
  /** The row's owner, or `null`. */
  owner: EntityOwner | null;
  /** The entity's kind, for the confirm call. */
  kind: OwnerEntityKind;
  /** The entity's id. */
  entityId: string;
  /** Called with the owner after a confirm succeeds. */
  onChange?: (owner: EntityOwner | null) => void;
  /** Hide the Confirm button (a reader who cannot edit, or a compact card). */
  readOnly?: boolean;
  /** Test id prefix; the cell is `${testId}`, its button `${testId}-confirm`. */
  testId?: string;
}

/**
 * One owner cell.
 *
 * @param props - See {@link OwnerCellProps}.
 * @returns The cell's content.
 */
export function OwnerCell({ owner, kind, entityId, onChange, readOnly = false, testId = 'owner-cell' }: OwnerCellProps) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Ownership is held back with Teams (lib/feature-release.ts); lists drop the column too.
  if (!isFeatureReleased('teams')) return null;
  if (!owner) {
    return (
      <span className="own-cell own-cell--none" data-testid={testId}>
        <span aria-hidden>—</span>
        <span className="sr-only">No owner</span>
      </span>
    );
  }

  const confirm = async (event: React.MouseEvent) => {
    // The cell sits inside clickable rows and cards; confirming must not also open the row.
    event.stopPropagation();
    setBusy(true);
    setError(null);
    try {
      onChange?.(await confirmOwner(kind, entityId, owner.team.slug));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not confirm the owner');
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="own-cell" data-testid={testId} data-status={owner.status} title={ownerDescription(owner)}>
      <Link
        className="own-cell__team"
        href={`/ade/dashboard/teams/${encodeURIComponent(owner.team.slug)}`}
        onClick={(event) => event.stopPropagation()}
      >
        {owner.team.name}
      </Link>
      {owner.status === 'suggested' ? (
        <>
          <Badge variant="warn" className="own-cell__badge">
            Suggested · {ownerSourceLabel(owner.source)}
          </Badge>
          {readOnly ? null : (
            <Button
              type="button"
              size="sm"
              variant="soft"
              className="own-cell__confirm"
              disabled={busy}
              aria-label={`Confirm ${owner.team.name} as owner`}
              data-testid={`${testId}-confirm`}
              onClick={confirm}
            >
              {busy ? 'Confirming…' : 'Confirm'}
            </Button>
          )}
        </>
      ) : null}
      {error ? (
        <span className="own-cell__error" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}

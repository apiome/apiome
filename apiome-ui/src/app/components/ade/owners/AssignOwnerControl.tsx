'use client';

/**
 * Bulk "Assign owner" for a table's bulk bar — CDG-2.4 (#5963).
 *
 * The lint-posture pattern: a control and a `DataTableBulkAction` after a rule in the bar
 * `DataTable` draws when rows are selected. Picking a team and pressing **Assign owner** makes it
 * the confirmed owner of every selected row in one all-or-nothing call; the page then re-reads.
 */

import * as React from 'react';
import { DataTableBulkAction } from '@/app/components/ui';
import { isFeatureReleased } from '@lib/feature-release';
import type { Team } from '@lib/owners';

/** Props for {@link AssignOwnerControl}. */
export interface AssignOwnerControlProps {
  /** The tenant's teams. */
  teams: readonly Team[];
  /** Called with the chosen team's slug. */
  onAssign: (team: string) => void | Promise<void>;
  /** True while an assignment is in flight. */
  busy?: boolean;
}

/**
 * The bulk-bar control.
 *
 * @param props - See {@link AssignOwnerControlProps}.
 * @returns A rule, a team select and the action.
 */
export function AssignOwnerControl({ teams, onAssign, busy = false }: AssignOwnerControlProps) {
  const [team, setTeam] = React.useState('');
  // Ownership is held back with Teams (lib/feature-release.ts).
  if (!isFeatureReleased('teams')) return null;
  return (
    <>
      <span className="lw-bulk-rule" aria-hidden />
      <select
        className="own-bulk-select"
        aria-label="Team to assign as owner"
        data-testid="bulk-owner-team"
        value={team}
        onChange={(event) => setTeam(event.target.value)}
      >
        <option value="">Choose a team…</option>
        {teams.map((option) => (
          <option key={option.id} value={option.slug}>
            {option.name}
          </option>
        ))}
      </select>
      <DataTableBulkAction
        data-testid="bulk-assign-owner"
        disabled={!team || busy}
        onClick={() => {
          if (team) void onAssign(team);
        }}
      >
        {busy ? 'Assigning…' : 'Assign owner'}
      </DataTableBulkAction>
    </>
  );
}

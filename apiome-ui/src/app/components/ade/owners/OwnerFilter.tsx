'use client';

/**
 * The owner filter every ownership-aware list puts in its toolbar — CDG-2.4 (#5963).
 *
 * A native select of the tenant's teams. The value is a team slug or empty for "Any owner"; the
 * page puts it in `?team=` and its BFF route forwards it to apiome-rest, which filters in SQL — the
 * filter is never applied to rows already in the browser.
 */

import * as React from 'react';
import { isFeatureReleased } from '@lib/feature-release';
import type { Team } from '@lib/owners';

/** Props for {@link OwnerFilter}. */
export interface OwnerFilterProps {
  /** The tenant's teams. */
  teams: readonly Team[];
  /** The selected team slug, or `null` for any owner. */
  value: string | null;
  /** Called with the new slug, or `null` for any owner. */
  onChange: (team: string | null) => void;
  /** True while the teams load. */
  loading?: boolean;
  /** Test id. */
  testId?: string;
}

/**
 * The owner filter.
 *
 * @param props - See {@link OwnerFilterProps}.
 * @returns A labelled select.
 */
export function OwnerFilter({ teams, value, onChange, loading = false, testId = 'owner-filter' }: OwnerFilterProps) {
  const id = React.useId();
  // A slug in the URL that names no loaded team still shows, so the reader can see and clear it.
  const unknown = value && !teams.some((team) => team.slug === value) ? value : null;
  // Ownership is held back with Teams (lib/feature-release.ts).
  if (!isFeatureReleased('teams')) return null;
  return (
    <span className="own-filter" data-active={value ? 'true' : 'false'}>
      <label htmlFor={id} className="own-filter__label">
        Owner
      </label>
      <select
        id={id}
        className="own-filter__select"
        data-testid={testId}
        value={value ?? ''}
        disabled={loading && teams.length === 0}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">Any team</option>
        {teams.map((team) => (
          <option key={team.id} value={team.slug}>
            {team.name}
          </option>
        ))}
        {unknown ? <option value={unknown}>{unknown}</option> : null}
      </select>
    </span>
  );
}

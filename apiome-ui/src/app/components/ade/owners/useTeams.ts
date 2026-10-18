'use client';

/**
 * The tenant's teams, loaded once per mount — CDG-2.4 (#5963).
 *
 * The owner filter and the bulk "Assign owner" control both list teams; a failed read leaves the
 * list empty and says why, so the controls render (disabled) rather than vanish.
 */

import * as React from 'react';
import type { Team } from '@lib/owners';
import { fetchTeams } from './ownersApi';

/** What {@link useTeams} returns. */
export interface TeamsState {
  /** The teams, by name; empty while loading or after a failure. */
  teams: Team[];
  /** True until the first read settles. */
  loading: boolean;
  /** The failure message, if the read failed. */
  error: string | null;
}

/**
 * Load the tenant's teams.
 *
 * @returns The teams, the loading flag and any error.
 */
export function useTeams(): TeamsState {
  const [state, setState] = React.useState<TeamsState>({ teams: [], loading: true, error: null });
  React.useEffect(() => {
    let live = true;
    fetchTeams()
      .then((teams) => live && setState({ teams, loading: false, error: null }))
      .catch((error: unknown) =>
        live && setState({ teams: [], loading: false, error: error instanceof Error ? error.message : 'Could not load teams' })
      );
    return () => {
      live = false;
    };
  }, []);
  return state;
}

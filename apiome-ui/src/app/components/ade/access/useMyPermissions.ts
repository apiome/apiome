'use client';

/**
 * The viewer's role grants, for hiding or disabling the controls their role cannot use.
 *
 * Catalog, Projects and Versions draw a write control only for a role the API would let use it
 * (RC6-H5, #6212). The rule lives in apiome-rest; this reads its verdict from
 * `GET /api/access/permissions/me` (tenant administrators hold everything) rather than re-deriving
 * it from role names. Which permission each control needs is tabled in
 * `docs/catalog-projects-permission-matrix.json`, and `tests/permission-matrix-ui.test.tsx` renders
 * each screen as Viewer, Editor and Owner against that table.
 *
 * Until the answer arrives — and if it cannot be read — nothing is allowed: a control appears once
 * the role is known to hold its permission, never the other way round.
 */

import * as React from 'react';

import { fetchMyPermissions, type MyPermissions } from './accessApi';
import { allowNothing, permissionCheck, type PermissionCheck } from './permissionCheck';

export { allowEverything, allowNothing, permissionCheck, type PermissionCheck } from './permissionCheck';

/** What {@link useMyPermissions} reports. */
export interface MyPermissionsState {
  /** `loading` until REST answers; `error` when it could not. */
  status: 'loading' | 'ready' | 'error';
  /** Whether the viewer holds a permission — `false` for everything until `ready`. */
  can: PermissionCheck;
  /** Whether the viewer is a tenant administrator (`false` until known). */
  isAdmin: boolean;
}

/**
 * Read the viewer's grants once per mount.
 *
 * @param enabled Skip the request (and allow nothing) while there is no workspace to ask about.
 * @returns The grants. See {@link MyPermissionsState}.
 */
export function useMyPermissions(enabled = true): MyPermissionsState {
  const [state, setState] = React.useState<{ status: MyPermissionsState['status']; mine: MyPermissions | null }>({
    status: 'loading',
    mine: null,
  });

  React.useEffect(() => {
    if (!enabled) return;
    let live = true;
    fetchMyPermissions()
      .then((mine) => {
        if (live) setState({ status: mine ? 'ready' : 'error', mine });
      })
      .catch(() => {
        if (live) setState({ status: 'error', mine: null });
      });
    return () => {
      live = false;
    };
  }, [enabled]);

  return React.useMemo(
    () => ({
      status: state.status,
      can: state.status === 'ready' ? permissionCheck(state.mine) : allowNothing,
      isAdmin: state.status === 'ready' && Boolean(state.mine?.is_admin),
    }),
    [state]
  );
}

/** How a write control draws for the viewer. */
export type ControlState = 'enabled' | 'disabled' | 'hidden';

/**
 * How to draw a header-level write control (a button that is always on screen).
 *
 * Disabled while the grants load, so the header does not jump when they arrive; hidden once the
 * role is known not to hold the permission — or when the grants could not be read.
 *
 * @param state The viewer's grants.
 * @param permission The `resource:action` the control's write needs.
 * @returns The control's state.
 */
export function controlState(state: MyPermissionsState, permission: string): ControlState {
  if (state.status === 'loading') return 'disabled';
  return state.can(permission) ? 'enabled' : 'hidden';
}

/** The `title` of a control disabled while the viewer's grants load. */
export const PERMISSIONS_PENDING_TITLE = 'Checking what your role can do…';

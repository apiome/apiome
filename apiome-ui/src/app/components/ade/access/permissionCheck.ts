/**
 * A viewer's role grants as a predicate — the pure half of `useMyPermissions`, importable from
 * model helpers (`catalogModel`, `projectsModel`, `versionsModel`) without React.
 */

import type { MyPermissions } from './accessApi';

/** Whether the viewer holds a `resource:action` permission. */
export type PermissionCheck = (permission: string) => boolean;

/** A check that allows everything — for model helpers called without a viewer (tests, previews). */
export const allowEverything: PermissionCheck = () => true;

/** A check that allows nothing — the answer while the grants are unknown. */
export const allowNothing: PermissionCheck = () => false;

/**
 * Build the check for a `permissions/me` answer.
 *
 * @param mine The answer, or `null` when it is unknown.
 * @returns A check that allows a tenant administrator everything, a member their grants, and an
 *   unknown viewer nothing.
 */
export function permissionCheck(mine: MyPermissions | null | undefined): PermissionCheck {
  if (!mine) return allowNothing;
  if (mine.is_admin) return allowEverything;
  const granted = new Set(mine.permissions ?? []);
  return (permission) => granted.has(permission);
}

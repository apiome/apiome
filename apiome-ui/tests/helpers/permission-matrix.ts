/**
 * The Catalog and Projects permission matrix, for the UI suites — RC6-H5 (#6212).
 *
 * `docs/catalog-projects-permission-matrix.json` tables every Catalog, Projects and Versions action,
 * the permission apiome-rest checks for it and the controls that offer it. apiome-rest's
 * `tests/test_permission_matrix.py` proves each REST call refuses the roles the table refuses; the
 * `tests/permission-matrix-*.test.tsx` suites render each screen as every role and use
 * {@link expectScreenMatchesMatrix} to prove the same roles are never offered the control.
 */

import * as fs from 'fs';
import * as path from 'path';
import { fireEvent, screen, waitFor } from '@testing-library/react';

/** One control that offers an action. */
export interface MatrixControl {
  /** The screen it is on: `catalog`, `catalog-detail`, `projects` or `versions`. */
  screen: string;
  /** Its `data-testid`; `{live}`, `{deleted}`, `{draft}` and `{published}` are row ids. */
  testid: string;
  /** The `data-testid` of the menu trigger to open first, when it is a menu item. */
  menu?: string;
  /** True for a bulk-bar button, which needs a selection first. */
  bulk?: boolean;
}

/** One row of the table. */
export interface MatrixAction {
  id: string;
  surface: string;
  label: string;
  /** The `resource:action` the API checks, or `null` for any member. */
  permission: string | null;
  /** Why the UI does not offer it in this release (e.g. `git-like`), when it does not. */
  held_back?: string;
  /** Why it has no control of its own (it lives inside another action's dialog). */
  ui_note?: string;
  rest: Array<{ method: string; path: string }>;
  ui: MatrixControl[];
}

/** A built-in role, as the table states it. */
export interface MatrixRole {
  label: string;
  /** A tenant administrator holds every permission. */
  tenantAdmin: boolean;
  grants: string[];
}

export const MATRIX_PATH = path.resolve(__dirname, '../../../docs/catalog-projects-permission-matrix.json');

export const MATRIX: { roles: Record<string, MatrixRole>; actions: MatrixAction[] } = JSON.parse(
  fs.readFileSync(MATRIX_PATH, 'utf8')
);

/** The roles, in the table's order (viewer, editor, owner). */
export const ROLES = Object.keys(MATRIX.roles);

/**
 * Whether the table lets a role perform an action.
 *
 * @param role The role key.
 * @param permission The action's permission (`null`: any member).
 * @returns The verdict.
 */
export function roleMay(role: string, permission: string | null): boolean {
  const spec = MATRIX.roles[role];
  return permission === null || spec.tenantAdmin || spec.grants.includes(permission);
}

/**
 * What `useMyPermissions()` returns for a role, once its grants have loaded.
 *
 * @param role The role key.
 * @returns A ready `MyPermissionsState`.
 */
export function permissionsFor(role: string) {
  const spec = MATRIX.roles[role];
  return {
    status: 'ready' as const,
    can: (permission: string) => spec.tenantAdmin || spec.grants.includes(permission),
    isAdmin: spec.tenantAdmin,
  };
}

/**
 * Every control the table puts on a screen, with the action it offers.
 *
 * @param screenName The screen.
 * @returns The pairs, in table order.
 */
export function controlsOn(screenName: string): Array<{ action: MatrixAction; control: MatrixControl }> {
  return MATRIX.actions.flatMap((action) =>
    action.ui.filter((control) => control.screen === screenName).map((control) => ({ action, control }))
  );
}

/** Fill a template's `{live}` / `{deleted}` / `{draft}` / `{published}` with fixture ids. */
export function fillIds(template: string, ids: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => {
    if (!(key in ids)) throw new Error(`no fixture id for {${key}} in ${template}`);
    return ids[key];
  });
}

/** Whether an element is on screen and usable (not `disabled`, `aria-disabled` or Radix-disabled). */
function offered(element: HTMLElement | null): boolean {
  return (
    element !== null &&
    !element.hasAttribute('disabled') &&
    element.getAttribute('aria-disabled') !== 'true' &&
    !element.hasAttribute('data-disabled')
  );
}

/** How a suite reaches the controls that need a menu or a selection. */
export interface ScreenDriver {
  /** Fixture ids for the templates' placeholders. */
  ids: Record<string, string>;
  /** Select every row so the bulk bar shows; omitted when the screen has no bulk controls. */
  selectAll?: () => Promise<void> | void;
  /** Clear the selection again. */
  clearSelection?: () => Promise<void> | void;
}

/**
 * Check a rendered screen against the table for one role: each control is offered exactly when
 * the role may perform its action — absent or disabled otherwise.
 *
 * @param screenName The screen being shown.
 * @param role The role it is rendered as.
 * @param driver How to reach menu and bulk controls.
 * @returns The mismatches, as sentences (empty when the screen matches).
 */
export async function screenMismatches(screenName: string, role: string, driver: ScreenDriver): Promise<string[]> {
  const problems: string[] = [];
  const pairs = controlsOn(screenName);
  if (pairs.length === 0) return [`the table puts no controls on ${screenName}`];

  const check = (action: MatrixAction, control: MatrixControl, testid: string) => {
    const expected = roleMay(role, action.permission);
    const actual = offered(screen.queryByTestId(testid));
    if (actual !== expected) {
      problems.push(
        `${role} ${expected ? 'should' : 'should not'} be offered ${testid} (${action.id}, ${action.permission ?? 'member'})`
      );
    }
  };

  for (const { action, control } of pairs.filter(({ control }) => !control.menu && !control.bulk)) {
    check(action, control, fillIds(control.testid, driver.ids));
  }

  for (const { action, control } of pairs.filter(({ control }) => control.menu)) {
    const trigger = screen.queryByTestId(fillIds(control.menu as string, driver.ids));
    if (!trigger) {
      // A menu that is not drawn offers nothing.
      if (roleMay(role, action.permission)) problems.push(`${role}: menu ${control.menu} is missing`);
      continue;
    }
    fireEvent.keyDown(trigger, { key: 'Enter' });
    await screen.findByRole('menu');
    check(action, control, fillIds(control.testid, driver.ids));
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    // Radix hides the rest of the page while a menu is open; wait for it to close.
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  }

  const bulk = pairs.filter(({ control }) => control.bulk);
  if (bulk.length > 0) {
    if (!driver.selectAll) throw new Error(`${screenName} has bulk controls but no selectAll`);
    await driver.selectAll();
    for (const { action, control } of bulk) check(action, control, fillIds(control.testid, driver.ids));
    await driver.clearSelection?.();
  }

  return problems;
}

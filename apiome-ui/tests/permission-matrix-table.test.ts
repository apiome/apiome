/**
 * The permission matrix itself — RC6-H5 (#6212).
 *
 * `docs/catalog-projects-permission-matrix.json` is read by apiome-rest's route suite and by the
 * `permission-matrix-<screen>` suites here. This checks the table is whole: every control sits on a
 * screen one of those suites renders, held-back actions offer no control, and the Roles page in the
 * docs prints the same verdicts.
 */

import * as fs from 'fs';
import * as path from 'path';

import { MATRIX, ROLES, roleMay } from './helpers/permission-matrix';

const SCREENS = ['catalog', 'catalog-detail', 'projects', 'versions'];
const ROLES_PAGE = path.resolve(__dirname, '../../apiome-docs/docs/workspace/roles.mdx');

describe('the permission matrix', () => {
  it('names the three built-in roles the issue tables', () => {
    expect(ROLES).toEqual(['viewer', 'editor', 'owner']);
  });

  it('puts every control on a screen a suite renders as each role', () => {
    for (const action of MATRIX.actions) {
      for (const control of action.ui) expect(SCREENS).toContain(control.screen);
    }
    for (const name of SCREENS) {
      expect(fs.existsSync(path.join(__dirname, `permission-matrix-${name}.test.tsx`))).toBe(true);
    }
  });

  it('offers no control for an action the release holds back, and some for every other', () => {
    for (const action of MATRIX.actions) {
      if (action.held_back) expect(action.ui).toEqual([]);
      // An action whose only control lives inside another action's dialog says so instead.
      else if (!action.ui_note) expect(action.ui.length).toBeGreaterThan(0);
    }
  });

  it('is what the Roles page prints', () => {
    const page = fs.readFileSync(ROLES_PAGE, 'utf8');
    const section = page.split('## What each role can do in Catalog, Projects and Versions')[1]?.split('\n## ')[0];
    expect(section).toBeDefined();
    for (const action of MATRIX.actions.filter((a) => !a.held_back)) {
      const needs = action.permission ? `\`${action.permission}\`` : 'any member';
      const ticks = ROLES.map((role) => (roleMay(role, action.permission) ? '✓' : '—')).join(' | ');
      expect(section).toContain(`| ${action.surface} | ${action.label} | ${needs} | ${ticks} |`);
    }
  });
});

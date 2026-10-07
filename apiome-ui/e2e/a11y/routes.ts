/**
 * The accessibility gate's route ledger — HIVE-10.2 (#5338).
 *
 * Every redesigned page mockup must name what the axe gate runs for it, so "all redesigned
 * routes" is a list on the record rather than a hope. `tests/a11y-routes.test.ts` fails when a
 * redesigned mockup (one in the visual-parity ledger, or uncovered there for any reason but
 * `awaiting-redesign`) has no entry here.
 *
 * A route is checked in one of three ways, none of which needs a database or a session:
 *
 * - **`fixtures`** — committed jsdom dumps of the page (`e2e/fixtures/<dir>/`), mounted into
 *   `/login` (which compiles the real `globals.css`). `gate.spec.ts` runs axe over *every* file in
 *   the directory, or only `files` when listed, in light, dark and high contrast.
 * - **`route`** — a page that renders without a session (`/login`, the `/design-system`
 *   galleries); `gate.spec.ts` loads it and runs axe in the three gate themes.
 * - **`spec`** — a page whose browser suite builds its markup inline. The a11y Playwright config
 *   runs that spec file as is; its axe tests import `e2e/support/a11y` and cover the gate themes.
 */

import { PARITY_ROUTES } from '../visual/routes';

/** How the gate checks one route. */
export type A11ySubject =
  | { kind: 'fixtures'; dir: string; files?: readonly string[] }
  | { kind: 'route'; path: string }
  | { kind: 'spec'; file: string };

/** One ledger entry. */
export interface A11yRoute {
  /** Stable id, used in test titles. */
  id: string;
  /** The page mockup under `docs/mockups/` this checks, or `null` for a surface with none. */
  mockup: string | null;
  /** What the gate runs. */
  subject: A11ySubject;
}

/** Pages the visual-parity harness already mounts from fixtures: gate the whole fixture directory. */
const FROM_PARITY: A11yRoute[] = PARITY_ROUTES.map((route) => {
  if (route.subject.kind !== 'fixture') {
    return { id: route.id, mockup: route.mockup, subject: { kind: 'route', path: route.route } };
  }
  return { id: route.id, mockup: route.mockup, subject: { kind: 'fixtures', dir: route.subject.dir } };
});

/** The rest of the redesign, and surfaces that have no page mockup of their own. */
const ADDITIONAL: A11yRoute[] = [
  // Auth and shells outside the app frame.
  { id: 'login', mockup: 'auth/login.html', subject: { kind: 'route', path: '/login' } },
  { id: 'two-factor', mockup: 'auth/two-factor.html', subject: { kind: 'spec', file: 'two-factor-a11y.spec.ts' } },
  {
    id: 'signup-oauth',
    mockup: 'auth/signup-oauth.html',
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['signup-oauth.html'] },
  },
  {
    id: 'onboarding',
    mockup: 'auth/onboarding.html',
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['onboarding-welcome.html', 'onboarding-organization.html'] },
  },
  { id: 'admin-login', mockup: 'admin/login.html', subject: { kind: 'route', path: '/admin/dashboard' } },
  { id: 'launcher', mockup: 'home/launcher.html', subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['launcher.html'] } },
  { id: 'shell', mockup: 'foundations/shell.html', subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['shell.html'] } },
  {
    id: 'settings-pane',
    mockup: 'foundations/settings-pane.html',
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['settings-pane.html'] },
  },
  { id: 'design-system', mockup: 'foundations/design-system.html', subject: { kind: 'route', path: '/design-system' } },

  // Overlays drawn over a page.
  { id: 'import-wizard', mockup: 'build/import-wizard.html', subject: { kind: 'fixtures', dir: 'hive-import-wizard' } },
  { id: 'version-dialogs', mockup: 'build/version-dialogs.html', subject: { kind: 'fixtures', dir: 'hive-version-dialogs' } },
  { id: 'repository-new', mockup: 'sources/repository-new.html', subject: { kind: 'fixtures', dir: 'hive-add-repository' } },

  // Pages whose browser suites build their markup inline.
  { id: 'home', mockup: 'home/overview.html', subject: { kind: 'spec', file: 'hive-home.spec.ts' } },
  { id: 'help', mockup: 'foundations/help.html', subject: { kind: 'spec', file: 'hive-help.spec.ts' } },
  { id: 'lint-posture', mockup: 'govern/lint-posture.html', subject: { kind: 'spec', file: 'hive-lint-workspace.spec.ts' } },
  { id: 'style-guides', mockup: 'govern/style-guides.html', subject: { kind: 'spec', file: 'hive-style-guides.spec.ts' } },
  {
    id: 'style-guide-detail',
    mockup: 'govern/style-guide-detail.html',
    subject: { kind: 'spec', file: 'hive-style-guide-detail.spec.ts' },
  },
  { id: 'api-keys', mockup: 'workspace/api-keys.html', subject: { kind: 'spec', file: 'hive-api-keys.spec.ts' } },
  { id: 'audit', mockup: 'workspace/audit.html', subject: { kind: 'spec', file: 'hive-audit.spec.ts' } },
  { id: 'members', mockup: 'workspace/members.html', subject: { kind: 'spec', file: 'hive-members.spec.ts' } },
  { id: 'roles', mockup: 'workspace/roles.html', subject: { kind: 'spec', file: 'hive-roles.spec.ts' } },
  { id: 'tenants', mockup: 'workspace/tenants.html', subject: { kind: 'spec', file: 'hive-tenants.spec.ts' } },

  // Redesigned ahead of their mockup's roadmap slot, or with no page mockup at all.
  { id: 'projects', mockup: null, subject: { kind: 'spec', file: 'hive-projects.spec.ts' } },
  { id: 'profile', mockup: null, subject: { kind: 'spec', file: 'hive-profile.spec.ts' } },
  { id: 'linked-accounts', mockup: null, subject: { kind: 'spec', file: 'hive-linked-accounts.spec.ts' } },
  { id: 'project-discussion', mockup: null, subject: { kind: 'fixtures', dir: 'project-discussion' } },
  { id: 'mock-correlation', mockup: null, subject: { kind: 'fixtures', dir: 'hive-mock-correlation' } },
  { id: 'command-palette', mockup: null, subject: { kind: 'route', path: '/design-system/command-palette' } },
  { id: 'page-header', mockup: null, subject: { kind: 'route', path: '/design-system/page-header' } },
  { id: 'shortcut-sheet', mockup: null, subject: { kind: 'route', path: '/design-system/shortcuts' } },
];

/** The ledger. */
export const A11Y_ROUTES: readonly A11yRoute[] = [...FROM_PARITY, ...ADDITIONAL];

/** The inline-markup spec files the a11y Playwright config runs alongside `gate.spec.ts`. */
export const A11Y_SPEC_FILES: readonly string[] = [
  ...new Set(
    A11Y_ROUTES.flatMap((route) => (route.subject.kind === 'spec' ? [route.subject.file] : [])),
  ),
];

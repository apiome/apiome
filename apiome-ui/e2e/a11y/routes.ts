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
    // `/signup` (SGN-1.2): open and closed, the email form, check-your-email (SGN-1.1), and the
    // confirmation page's states.
    id: 'signup-email',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'signup.html',
        'signup-closed.html',
        'signup-form.html',
        'signup-check-email.html',
        'signup-verify-confirm.html',
        'signup-verified.html',
        'signup-verify-expired.html',
      ],
    },
  },
  {
    id: 'onboarding',
    mockup: 'auth/onboarding.html',
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['onboarding-welcome.html', 'onboarding-organization.html', 'onboarding-two-factor.html'] },
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
  // TFA-1.3 (#5657): the blocking enrolment screen of a workspace that requires two-factor.
  {
    id: 'two-factor-required',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['two-factor-required.html'] },
  },
  { id: 'projects', mockup: null, subject: { kind: 'spec', file: 'hive-projects.spec.ts' } },
  {
    // RC6-H2 (#6209): the Projects page as the components render it — `hive-projects.spec.ts`
    // above checks hand-written copies of its markup — plus the New and Edit project dialogs,
    // dumped by `tests/projects-hive-redesign.test.tsx`.
    id: 'projects-rendered',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['projects-cards.html', 'projects-table.html', 'projects-create-dialog.html', 'projects-edit-dialog.html'],
    },
  },
  {
    // RC6-H2 (#6209): the Catalog and Versions dialogs no page suite dumps — Convert to OpenAPI,
    // Import to catalog, the version Export dialog and the Unpublish confirm — dumped by
    // `tests/rc6-dialog-fixtures.test.tsx`.
    id: 'rc6-dialogs',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-rc6-dialogs' },
  },
  { id: 'profile', mockup: null, subject: { kind: 'spec', file: 'hive-profile.spec.ts' } },
  { id: 'linked-accounts', mockup: null, subject: { kind: 'spec', file: 'hive-linked-accounts.spec.ts' } },
  { id: 'project-discussion', mockup: null, subject: { kind: 'fixtures', dir: 'project-discussion' } },
  { id: 'mock-correlation', mockup: null, subject: { kind: 'fixtures', dir: 'hive-mock-correlation' } },
  {
    id: 'connectors',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'connectors.html',
        'connector-add.html',
        'connector-add-mcp-registry.html',
        'connector-add-registry.html',
        'connector-add-schema-registry.html',
        'connector-detail.html',
        'connector-runs.html',
      ],
    },
  },
  {
    // CDG-2.4 (#5963): the teams list and a team page, dumped by `tests/teams-pages.test.tsx`.
    id: 'teams',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['teams.html', 'team-detail.html'] },
  },
  {
    // EID-1.2 (#5012): Workspace → Single sign-on — the provider list and the drawer's Configure
    // and Domains tabs (`tests/workspace-sso-page.test.tsx`), and the sign-in form once an email
    // routes to SSO (`tests/login-email-first-sso.test.tsx`).
    id: 'workspace-sso',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'sso-providers.html',
        'sso-provider-configure.html',
        'sso-domain-verify.html',
        'login-sso-routed.html',
        // EID-1.3 (#5013): where a sign-in lands when the workspace has no seat left
        // (`tests/login-out-of-seats.test.tsx`).
        'login-out-of-seats.html',
      ],
    },
  },
  {
    // CDG-3.4 (#5969): the graph page, the Dependencies tab and the blast-radius drawer, dumped by
    // `tests/dependency-graph-ui.test.tsx`.
    id: 'dependency-graph',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'dependency-graph.html',
        'dependency-graph-truncated.html',
        'dependencies-tab.html',
        'dependencies-runtime.html',
        'blast-radius.html',
      ],
    },
  },
  {
    // CDG-4.5 (#5977): the catalog item's Subjects tab and the Workspace → Schema registry page,
    // dumped by `tests/schema-registry-ui.test.tsx`.
    id: 'schema-registry',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['catalog-item-subjects.html', 'schema-registry.html'] },
  },
  {
    // CDG-5.1 (#5979): the catalog home's kind tiles, callouts and cross-kind list, dumped by
    // `tests/catalog-entities-ui.test.tsx`.
    id: 'catalog-kinds',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['catalog-kinds.html'] },
  },
  {
    // MFI-21.2 (#3992): a z/OS Connect descriptor's copybook ↔ REST binding panel, dumped by
    // `tests/catalog-zosconnect-binding.test.tsx`.
    id: 'catalog-zosconnect-binding',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['catalog-zosconnect-binding.html'] },
  },
  {
    // CDG-5.2 (#5980): an agent's page and a model's page, dumped by `tests/catalog-agents-ui.test.tsx`.
    id: 'catalog-agents',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['agent-entity.html', 'model-entity.html'] },
  },
  {
    // CDG-5.3 (#5981): a gateway config page and the push-back fidelity report, dumped by
    // `tests/gateway-config-ui.test.tsx`.
    id: 'gateway-configs',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['gateway-config-entity.html', 'export-studio-gateway.html'] },
  },
  {
    // CDG-5.4 (#5982): the Facts checklist of a catalog item and of an MCP server, dumped by
    // `tests/catalog-facts-ui.test.tsx`.
    id: 'catalog-facts',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['entity-facts.html', 'scorecard-kind.html'] },
  },
  {
    // CDG-5.5 (#5983): a Backstage import report and the Import to catalog wizard's Compass step,
    // dumped by `tests/catalog-migrations-ui.test.tsx`.
    id: 'catalog-migrations',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['backstage-import-report.html', 'import-wizard-compass.html'] },
  },
  {
    // PFX-2.5 (#6929): a bi-directional comparison's fidelity report, dumped by
    // `tests/pact-comparison-fidelity-ui.test.tsx`.
    id: 'pact-comparison-fidelity',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['pact-comparison-fidelity.html'] },
  },
  {
    // PFX-3.3 (#6933): a provider's registered provider states and the pre-run check of its pacts,
    // dumped by `tests/pact-provider-states-ui.test.tsx`.
    id: 'pact-provider-states',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['pact-provider-states.html'] },
  },
  {
    // PFX-5.1 (#6945): the Pacticipants list and one pacticipant's page (versions, branches, tags,
    // environments), dumped by `tests/pact-pacticipants-ui.test.tsx`.
    id: 'pact-pacticipants',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-pacticipants.html', 'pact-pacticipant-detail.html'],
    },
  },
  {
    // PFX-5.2 (#6946): one integration's pact — interactions, verification status, changes since
    // the previous pact, history — dumped by `tests/pact-detail-ui.test.tsx`.
    id: 'pact-detail',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['pact-detail.html'] },
  },
  {
    // PFX-5.3 (#6947): a pacticipant's integration network — the diagram with each integration's
    // verdict and the integrations table — dumped by `tests/pact-network-ui.test.tsx`.
    id: 'pact-network',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['pact-network.html'] },
  },
  {
    // PFX-5.4 (#6948): the matrix — query builder, verdict explained, grid and rows — and the
    // can-i-deploy console, dumped by `tests/pact-matrix-ui.test.tsx`.
    id: 'pact-matrix',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['pact-matrix.html', 'pact-can-i-deploy.html'] },
  },
  {
    // PFX-5.5 (#6949): a provider's Verification page (KPI strip, pacts with Re-run, history) and
    // one result (expected vs actual, requests, raw log), dumped by `tests/pact-verification-ui.test.tsx`.
    id: 'pact-verification',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-verification.html', 'pact-verification-result.html'],
    },
  },
  {
    // PFX-6.2 (#6954): Verification settings (defaults and overrides), the Re-publish requests list
    // and one request, dumped by `tests/pact-remediation-ui.test.tsx`.
    id: 'pact-remediation',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-verification-settings.html', 'pact-republish-requests.html', 'pact-republish-request.html'],
    },
  },
  {
    // PFX-8.16 (#7313): the Migration wizard on Choose (a finished dry run) and on Copy (a running
    // copy with two failures), dumped by `tests/pact-migrate-wizard-ui.test.tsx`.
    id: 'pact-migrate',
    mockup: 'contracts/migrate.html',
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-migrate-choose.html', 'pact-migrate-copy.html'],
    },
  },
  {
    // PFX-8.15 (#7312): Contracts settings → Secrets, CI and commit statuses, Agents, dumped by
    // `tests/pact-settings-tabs-ui.test.tsx`.
    id: 'pact-settings-tabs',
    mockup: 'contracts/settings.html',
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-settings-secrets.html', 'pact-settings-ci.html', 'pact-settings-agents.html'],
    },
  },
  {
    // PFX-8.14 (#7311): Contracts settings → Clean-up (keep-rules, If it ran now, Recently deleted),
    // dumped by `tests/pact-settings-cleanup-ui.test.tsx`.
    id: 'pact-settings-cleanup',
    mockup: 'contracts/settings.html',
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-settings-cleanup.html'],
    },
  },
  {
    // PFX-8.1 (#7298): the Contracts landing (strip, facts, integrations, ways in) and an empty
    // workspace with the first-run checklist, dumped by `tests/pact-overview-ui.test.tsx`.
    id: 'pact-overview',
    mockup: 'contracts/overview.html',
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-overview.html', 'pact-overview-empty.html'],
    },
  },
  {
    // PFX-6.3 (#6955): Contract health (every pair worst first) and one pair's health with its
    // signals and trends, dumped by `tests/pact-health-ui.test.tsx`.
    id: 'pact-health',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-health.html', 'pact-pair-health.html'],
    },
  },
  {
    // PFX-5.6 (#6950): the Webhooks page (webhooks with their newest delivery, recent deliveries),
    // one webhook (overview, request, delivery log) and one delivery (each attempt's log), dumped
    // by `tests/pact-webhooks-ui.test.tsx`.
    id: 'pact-webhooks',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: ['pact-webhooks.html', 'pact-webhook-detail.html', 'pact-webhook-delivery.html'],
    },
  },
  {
    // PFX-5.7 (#6951): the Environments dashboard — since PFX-8.13 (#7310) the what-is-where board
    // and its History view — one environment (overview, deployed now, released, deployment history)
    // and the deploy simulator (verdict, what else changes, CLI), dumped by
    // `tests/pact-environments-ui.test.tsx`.
    id: 'pact-environments',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'pact-environments-board.html',
        'pact-environments-history.html',
        'pact-environment-detail.html',
        'pact-deploy-simulator.html',
      ],
    },
  },
  {
    // X3 (#6224): the released export surfaces of E1. The Source and Target steps (the target grid),
    // the several-targets Verify and the bulk dialog after a run are gated with the whole
    // `hive-export-studio` directory under the parity entry `export-studio`; this entry adds the
    // other three steps, dumped by `tests/ExportStudio.test.tsx`, the source picker (both of its
    // lists), dumped by `tests/export-source-picker.test.tsx`, and the bulk Export… dialog with a
    // target picked, dumped by `tests/export-multi.test.tsx`. No file is exempt.
    id: 'export-e1',
    mockup: null,
    subject: {
      kind: 'fixtures',
      dir: 'hive-a11y',
      files: [
        'export-studio-options.html',
        'export-studio-verify.html',
        'export-studio-review.html',
        'export-source-picker.html',
        'export-source-picker-versions.html',
        'export-bulk-pick.html',
      ],
    },
  },
  {
    // APX-1.1 (#6098): Ship → Products and one product's editor, dumped by
    // `tests/api-products-ui.test.tsx`.
    id: 'api-products',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['api-products-list.html', 'api-product-editor.html'] },
  },
  {
    // APX-1.2 (#6099): the product editor with the plan editor open, dumped by
    // `tests/api-plans-ui.test.tsx`.
    id: 'api-plans',
    mockup: null,
    subject: { kind: 'fixtures', dir: 'hive-a11y', files: ['api-plan-editor.html'] },
  },
  { id: 'command-palette', mockup: null, subject: { kind: 'route', path: '/design-system/command-palette' } },
  { id: 'page-header', mockup: null, subject: { kind: 'route', path: '/design-system/page-header' } },
  { id: 'shortcut-sheet', mockup: null, subject: { kind: 'route', path: '/design-system/shortcuts' } },
  // #6274: the Hive Monaco theme, which no other gated page renders. A spec rather than a route,
  // so axe runs only after Monaco has painted the code and the gutter.
  { id: 'code-editor', mockup: null, subject: { kind: 'spec', file: 'hive-code-editor-a11y.spec.ts' } },
];

/** The ledger. */
export const A11Y_ROUTES: readonly A11yRoute[] = [...FROM_PARITY, ...ADDITIONAL];

/** The inline-markup spec files the a11y Playwright config runs alongside `gate.spec.ts`. */
export const A11Y_SPEC_FILES: readonly string[] = [
  ...new Set(
    A11Y_ROUTES.flatMap((route) => (route.subject.kind === 'spec' ? [route.subject.file] : [])),
  ),
];

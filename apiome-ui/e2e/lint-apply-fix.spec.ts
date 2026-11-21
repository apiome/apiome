import { test, expect } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { testUsers } from './fixtures/test-fixtures';
// WCAG 2.2 A/AA — the shared gate tags of HIVE-10.2 (#5338).
import { WCAG_TAGS } from './support/a11y';

/**
 * "Apply fix" in the Lint report and Lint posture — GVM-3.6 (#5874).
 *
 * Two journeys, each applying one fix end to end through the real UI and its BFF calls:
 *
 *   1. **Versions → Lint report.** Open the revision's report, press the finding's *Fix* chip,
 *      confirm the reason, and land on the new revision link — the apply request carries the
 *      fix id and the reason, and the stored report is read again afterwards.
 *   2. **Lint posture → drawer.** Open a catalog-revision finding, *Apply fix*, confirm, and
 *      the finding moves to *Fixed* only because the new revision's re-lint (its stored report)
 *      no longer lists it — the bulk decision request is asserted, not assumed.
 *
 * The REST responses behind the BFF are fulfilled here (the `versions-import.spec.ts` pattern),
 * so the journey needs no seeded OpenAPI revision; `tests/lint-fix-*.test.ts*` pin the rules.
 * Both open dialogs pass axe (serious/critical) as rendered.
 */

const PROJECT_ID = 'proj-e2e-fix';
const REVISION_ID = 'rev-e2e-fix-1';
const NEW_REVISION_ID = 'rev-e2e-fix-2';
const FINDING_ID = 'lint-e2e-opid';

/** Fulfil a route with a JSON body. */
function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

/** The source revision's report: one fixable finding. */
const REPORT = {
  success: true,
  projectId: PROJECT_ID,
  versionRecordId: REVISION_ID,
  versionId: '1.0.0',
  score: 80,
  grade: 'B',
  findings: [
    {
      id: FINDING_ID,
      path: 'paths./pets.get',
      category: 'naming',
      rule: 'operation-id-required',
      severity: 'warning',
      message: 'Operation GET /pets has no operationId.',
    },
  ],
  ruleHits: { 'operation-id-required': 1 },
  severityCounts: { error: 0, warning: 1, info: 0 },
  reportFingerprint: 'fp-1',
  baseRevisionId: null,
  compatibilityOverall: null,
};

/** The new revision's re-lint: the finding is gone. */
const FIXED_REPORT = {
  ...REPORT,
  versionRecordId: NEW_REVISION_ID,
  versionId: '1.0.1',
  score: 100,
  grade: 'A',
  findings: [],
  ruleHits: {},
  severityCounts: { error: 0, warning: 0, info: 0 },
};

const PLAN = {
  success: true,
  projectId: PROJECT_ID,
  versionRecordId: REVISION_ID,
  counts: { ready: 1 },
  published: false,
  entries: [
    {
      fixId: 'fix-e2e-opid',
      ruleId: 'operation-id-required',
      fixClass: 'fill-in',
      wireVisible: true,
      path: 'paths./pets.get',
      pointer: '/paths/~1pets/get',
      findingId: FINDING_ID,
      message: 'Operation GET /pets has no operationId.',
      ops: [{ op: 'add', path: '/paths/~1pets/get/operationId', value: 'getPets' }],
      status: 'ready',
      reason: null,
      conflictsWith: null,
      classification: { maxSeverity: 'non-breaking', counts: {}, changes: [] },
    },
  ],
};

const APPLIED = {
  success: true,
  projectId: PROJECT_ID,
  sourceVersionRecordId: REVISION_ID,
  versionRecordId: NEW_REVISION_ID,
  versionLabel: '1.0.1',
  appliedFixIds: ['fix-e2e-opid'],
  skipped: [],
  score: 100,
  grade: 'A',
};

/** Capture of the writes the journey makes. */
interface Writes {
  apply: Array<Record<string, unknown>>;
  bulk: Array<Record<string, unknown>>;
}

/** Session, projects and the lint-fix BFF routes both journeys share. */
async function mockShared(page: Page, writes: Writes) {
  await page.route('**/api/auth/get-session', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const res = await route.fetch();
    try {
      const data = JSON.parse(await res.text()) as { user?: Record<string, unknown> };
      if (data?.user) {
        data.user.current_tenant_id ??= '00000000-0000-0000-0000-00000000e2e2';
        data.user.is_tenant_admin = true;
      }
      return json(route, data, res.status());
    } catch {
      return route.fulfill({ response: res });
    }
  });
  await page.route('**/api/lint/rules**', (route) =>
    json(route, { success: true, rules: [], count: 0 }),
  );
  await page.route(`**/api/projects/${PROJECT_ID}/versions/*/lint/fixes/apply`, (route) => {
    writes.apply.push(route.request().postDataJSON());
    return json(route, APPLIED, 201);
  });
  await page.route(`**/api/projects/${PROJECT_ID}/versions/*/lint/fixes`, (route) =>
    json(route, PLAN),
  );
  await page.route(`**/api/projects/${PROJECT_ID}/versions/${NEW_REVISION_ID}/lint**`, (route) =>
    json(route, FIXED_REPORT),
  );
  await page.route(`**/api/projects/${PROJECT_ID}/versions/${REVISION_ID}/lint`, (route) =>
    json(route, REPORT),
  );
}

/** The Versions screen reads. */
async function mockVersions(page: Page) {
  await page.route('**/api/projects?**', (route) =>
    route.request().method() !== 'GET'
      ? route.continue()
      : json(route, {
          success: true,
          projects: [{ id: PROJECT_ID, name: 'E2E Fix', slug: 'e2e-fix', publishable: true }],
        }),
  );
  await page.route('**/api/versions?**', (route) =>
    route.request().method() !== 'GET'
      ? route.continue()
      : json(route, {
          success: true,
          versions: [
            {
              id: REVISION_ID,
              project_id: PROJECT_ID,
              creator_id: 'e2e-creator',
              version_id: '1.0.0',
              shortMessage: 'seed',
              changelog: null,
              enabled: true,
              published: false,
              deleted_at: null,
              created_at: '2026-01-01T00:00:00.000Z',
              updated_at: '2026-01-01T00:00:00.000Z',
              published_at: null,
              creator_name: 'E2E',
              creator_email: 'e2e@example.com',
              qualityScore: 80,
              qualityGrade: 'B',
            },
          ],
        }),
  );
  await page.route('**/api/database/versions/has-class-schema**', (route) =>
    json(route, { success: true, map: {} }),
  );
  await page.route(`**/api/projects/${PROJECT_ID}/version-branches**`, (route) =>
    json(route, { success: true, branches: [] }),
  );
  await page.route(`**/api/projects/${PROJECT_ID}/version-tags**`, (route) =>
    json(route, { success: true, tags: [] }),
  );
}

/** The Lint posture reads and the bulk decision write. */
async function mockPosture(page: Page, writes: Writes) {
  const finding = {
    sourceFingerprint: FINDING_ID,
    ruleId: 'operation-id-required',
    message: 'Operation GET /pets has no operationId.',
    severity: 'warning',
    confidence: 'high',
    category: 'naming',
    axisKey: 'quality',
    location: { path: 'paths./pets.get' },
    remediation: null,
    scannerId: 'apiome-lint',
    profile: null,
    subjectType: 'catalog_revision',
    versionRecordId: REVISION_ID,
    mcpVersionId: null,
    projectId: PROJECT_ID,
    projectName: 'E2E Fix',
    subjectLabel: 'v1.0.0',
    compositeGrade: 'B',
    requiredCoverageMet: true,
    evidenceRunId: 'run-e2e',
    evidenceCreatedAt: '2026-11-20T08:00:00Z',
    isNew: false,
    effectiveState: 'open',
    waived: false,
    decision: null,
    latestPolicyEvaluationId: null,
    policyPassed: null,
  };
  await page.route('**/api/lint/workspace/findings**', (route) =>
    json(route, {
      success: true,
      findings: [finding],
      count: 1,
      total: 1,
      limit: 50,
      offset: 0,
      facets: {},
    }),
  );
  await page.route('**/api/lint/workspace/summary**', (route) =>
    json(route, { success: false }, 500),
  );
  await page.route('**/api/lint/workspace/trends**', (route) =>
    json(route, { success: false }, 500),
  );
  await page.route('**/api/lint/workspace/quality-ranks**', (route) =>
    json(route, { success: false }, 500),
  );
  await page.route('**/api/lint/workspace/views**', (route) =>
    json(route, { success: true, views: [] }),
  );
  await page.route('**/api/lint/workspace/decisions/bulk', (route) => {
    const body = route.request().postDataJSON();
    writes.bulk.push(body);
    return json(route, {
      success: true,
      results: [
        {
          sourceFingerprint: FINDING_ID,
          projectId: PROJECT_ID,
          decisionId: 'dec-e2e',
          beforeState: null,
          afterState: 'fixed',
          ok: true,
          error: null,
        },
      ],
      appliedCount: 1,
      failedCount: 0,
    });
  });
}

/** Sign in as the seeded admin; false when the dev database has no such user. */
async function login(page: Page): Promise<boolean> {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('you@example.com').fill(testUsers.valid.email);
  await page.locator('input[type="password"]').fill(testUsers.valid.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  return !page.url().includes('/login');
}

/** axe over the open dialog, serious and critical only. */
async function expectNoSeriousViolations(page: Page, selector: string) {
  const results = await new AxeBuilder({ page }).include(selector).withTags(WCAG_TAGS).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(serious, serious.map((v) => `${v.id}: ${v.help}`).join('\n')).toEqual([]);
}

test.describe('GVM-3.6 — Apply fix (mocked REST)', () => {
  test('applies one fix from the Versions lint report', async ({ page }) => {
    const writes: Writes = { apply: [], bulk: [] };
    await mockShared(page, writes);
    await mockVersions(page);
    if (!(await login(page))) {
      test.skip(true, 'Login failed — skip E2E (seed admin@apiome.dev / 1234)');
      return;
    }
    await page.goto(`/ade/dashboard/versions?projectId=${PROJECT_ID}`);

    await page.getByTestId('version-lint-badge').first().click();
    const chip = page.getByTestId('lint-fix-chip');
    await expect(chip).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('lint-fix-apply-all')).toHaveText(/Apply 1 deterministic fix/);
    await expectNoSeriousViolations(page, '[role="dialog"]');

    await chip.click();
    const confirm = page.getByTestId('lint-fix-apply-dialog');
    await expect(confirm).toBeVisible();
    await confirm.getByTestId('lint-fix-reason').fill('Name the pets operation');
    await confirm.getByTestId('lint-fix-submit').click();

    await expect(page.getByTestId('lint-fix-result')).toContainText('v1.0.1', { timeout: 15000 });
    await expect(page.getByTestId('lint-fix-result-link')).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT_ID}`,
    );
    expect(writes.apply).toEqual([{ fixIds: ['fix-e2e-opid'], reason: 'Name the pets operation' }]);
  });

  test('applies one fix from the Lint posture drawer and observes it fixed', async ({ page }) => {
    const writes: Writes = { apply: [], bulk: [] };
    await mockShared(page, writes);
    await mockPosture(page, writes);
    if (!(await login(page))) {
      test.skip(true, 'Login failed — skip E2E (seed admin@apiome.dev / 1234)');
      return;
    }
    await page.goto('/ade/dashboard/lint-workspace');

    await page.getByText('Operation GET /pets has no operationId.').first().click();
    const drawer = page.getByTestId('finding-detail-drawer');
    await expect(drawer.getByTestId('detail-fix-ready')).toBeVisible({ timeout: 15000 });
    await expectNoSeriousViolations(page, '[data-testid="finding-detail-drawer"]');

    await drawer.getByTestId('detail-apply-fix').click();
    const confirm = page.getByTestId('lint-fix-apply-dialog');
    await confirm.getByTestId('lint-fix-submit').click();

    // Fixed only because the new revision's stored report no longer lists the finding.
    await expect(drawer.getByTestId('detail-fix-observed')).toBeVisible({ timeout: 15000 });
    expect(writes.apply).toHaveLength(1);
    expect(writes.bulk).toEqual([
      {
        items: [
          { sourceFingerprint: FINDING_ID, projectId: PROJECT_ID, ruleId: 'operation-id-required' },
        ],
        set: {
          state: 'fixed',
          rationale:
            'Fixed by lint-fix revision v1.0.1: Apply the deterministic operation-id-required fix.',
        },
      },
    ]);
  });
});

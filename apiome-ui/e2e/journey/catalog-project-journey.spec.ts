/**
 * Catalog → Project journey (RC6-H1, #6208).
 *
 * The one test that walks the whole Catalog and Projects path RC6 ships, through the real app,
 * REST and Postgres: a non-OpenAPI spec (RAML) is pasted into the Catalog import dialog, its
 * catalog item is opened from the list, converted to OpenAPI as a new project, the project is
 * edited, a version is cut, published and unpublished, and that version is exported through the
 * in-place **Export** dialog. Each screen has its own unit and fixture tests; this spec is what
 * notices when a change to one screen breaks the hand-off to the next.
 *
 * **Released surfaces only.** It runs under `playwright.catalog-journey.config.ts`, whose server
 * has no `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES` override, and its first step proves it: a held-back
 * route must show the *Not available yet* gate. The OLO journey config (which turns every preview
 * on) ignores this file.
 *
 * Every wait is on a `data-testid` or a role the step's screen draws when it is ready — no sleeps.
 * The run is self-contained and re-entrant: the persona comes from the seeded multi-tenant fixture,
 * and the spec's title carries a per-run suffix, so the catalog item and project it creates never
 * collide with an earlier run's on a shared stack.
 */
import { test, expect, type Page } from '@playwright/test';
import { loadCorpus, readCorpusFile } from '../../lib/corpus/corpus';
import { setMockPersona, type MockPersona } from './support/mock-oauth';
import { closeDb, seedMultiTenantFixture, MULTITENANT_FIXTURE } from './support/db';

const { user } = MULTITENANT_FIXTURE;

/**
 * Grace (owner of Aurora Labs in the seeded fixture), with the provider identity the other
 * journey specs use for her — a user holds one GitHub link, so a second id would be refused.
 */
const PERSONA: MockPersona = {
  email: user.email,
  name: user.name,
  login: 'grace-hopper',
  providerUserId: '900000004221',
  verified: true,
};

/** The RAML corpus entry under test, selected by manifest tag (never by hard-coded path). */
const CORPUS_ENTRY = (() => {
  const matches = loadCorpus({ format: 'raml', validityClass: 'valid', feature: 'base-uri' });
  if (matches.length !== 1) {
    throw new Error(`expected one valid RAML fixture with a base URI, found ${matches.length}`);
  }
  return matches[0];
})();

/** Unique per run: the catalog item and the converted project are both named after it. */
const TITLE = `Journey Bookstore ${Date.now()}`;

/** The RAML document, retitled so this run's catalog item can be found by name. */
const RAML = readCorpusFile(CORPUS_ENTRY).replace(/^title:.*$/m, `title: ${TITLE}`);

/** What the edit step writes into the project's description. */
const EDITED_DESCRIPTION = `Edited by the catalog journey (${TITLE}).`;

/** The export target: Protobuf, a different format family from the OpenAPI project. */
const EXPORT_TARGET = 'proto';

// Shared across the serial steps below.
let itemId: string | null = null;
let projectId: string | null = null;
let versionRecordId: string | null = null;

/**
 * Sign in as {@link PERSONA} through the mock GitHub provider.
 *
 * @param page The test's page.
 */
async function login(page: Page): Promise<void> {
  await page.context().clearCookies();
  await setMockPersona(PERSONA);
  await page.goto('/login');
  await page.getByRole('button', { name: /continue with github/i }).click();
  await page.waitForURL(/\/ade/, { timeout: 60_000 });
}

/**
 * Open the Versions page of the converted project and wait for its table.
 *
 * @param page The test's page.
 */
async function gotoVersions(page: Page): Promise<void> {
  expect(projectId, 'the convert step must have created the project').not.toBeNull();
  await page.goto(`/ade/dashboard/versions?projectId=${encodeURIComponent(projectId!)}`);
  await expect(page.getByTestId('versions-table')).toBeVisible({ timeout: 60_000 });
}

/**
 * Choose one action from a version row's ⋯ menu.
 *
 * @param page The test's page.
 * @param action The row action id, e.g. `publish`.
 */
async function rowAction(page: Page, action: string): Promise<void> {
  expect(versionRecordId, 'the cut-a-version step must have created the version').not.toBeNull();
  await page.getByTestId(`versions-row-menu-${versionRecordId}`).click();
  await page.getByTestId(`versions-row-action-${action}`).click();
}

/**
 * Open a project's **Edit project** dialog from its card on the Projects page.
 *
 * @param page The test's page.
 */
async function openEditProject(page: Page): Promise<void> {
  await page.goto('/ade/dashboard/projects');
  await page.getByTestId('projects-search').fill(TITLE);
  await page.getByTestId(`project-card-menu-${projectId}`).click();
  await page.getByRole('menuitem', { name: 'Edit project' }).click();
  await expect(page.getByTestId('projects-edit-dialog')).toBeVisible();
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  await seedMultiTenantFixture();
});

test.afterAll(async () => {
  await closeDb();
});

test.describe('RC6-H1 — Catalog → Project journey', () => {
  test('runs on released surfaces only (no preview override)', async ({ page }) => {
    await login(page);
    // Export studio is held back in RC6. With no override its route draws the gate.
    await page.goto('/ade/dashboard/export/studio');
    await expect(page.getByTestId('unreleased-feature-gate')).toBeVisible({ timeout: 60_000 });
  });

  test('imports a RAML spec into the Catalog through the import dialog', async ({ page }) => {
    await login(page);
    await page.goto('/ade/dashboard/catalog');
    await page.getByTestId('catalog-import').click();

    await page.getByTestId('catalog-import-source-paste').click();
    await page.getByLabel('Source content').fill(RAML);
    await page.getByRole('button', { name: /detect pasted source/i }).click();
    await expect(page.getByText(/Auto-detected/i).first()).toBeVisible({ timeout: 30_000 });

    // Continue through the routing and options steps to the quality step, whose own footer
    // replaces the wizard's Continue button.
    const quality = page.getByTestId('import-quality-grade');
    const next = page.getByRole('button', { name: /^continue$/i });
    for (let step = 0; step < 3 && !(await quality.isVisible()); step += 1) {
      await next.click();
      await expect(quality.or(next)).toBeVisible({ timeout: 30_000 });
    }
    await expect(quality).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('import-quality-import').click();

    await expect(page.getByText(/Stored in the catalog in its original format/)).toBeVisible({
      timeout: 120_000,
    });
    await page.keyboard.press('Escape');
  });

  test('opens the catalog item from the Catalog list', async ({ page }) => {
    await login(page);
    await page.goto('/ade/dashboard/catalog');
    await page.getByTestId('catalog-search').fill(TITLE);
    await page.getByText(TITLE, { exact: true }).first().click();

    await page.waitForURL(/\/ade\/dashboard\/catalog\/[^/?]+/, { timeout: 60_000 });
    itemId = new URL(page.url()).pathname.split('/').at(-1) ?? null;
    expect(itemId).toBeTruthy();
    await expect(page.getByTestId('catalog-detail-convert')).toBeVisible({ timeout: 60_000 });
  });

  test('converts it to OpenAPI as a new project', async ({ page }) => {
    await login(page);
    await page.goto(`/ade/dashboard/catalog/${itemId}`);

    await page.getByTestId('catalog-detail-convert').click();
    await expect(page.getByTestId('conversion-tier-pill')).toBeVisible({ timeout: 60_000 });
    const ack = page.getByTestId('conversion-ack');
    if (await ack.isVisible()) await ack.check();
    await page.getByTestId('conversion-convert-btn').click();

    const projectLink = page.getByTestId('catalog-detail-converted-project');
    await expect(projectLink).toBeVisible({ timeout: 120_000 });
    const href = await projectLink.getAttribute('href');
    projectId = new URL(href ?? '', 'http://journey.local').searchParams.get('projectId');
    expect(projectId, `the converted strip should link to the project, got ${href}`).toBeTruthy();
  });

  test('edits the project', async ({ page }) => {
    await login(page);
    await openEditProject(page);
    await page.locator('#dashboard-projects-edit-projectDescription').fill(EDITED_DESCRIPTION);
    await page.getByTestId('projects-edit-submit').click();
    await expect(page.getByTestId('projects-edit-dialog')).toBeHidden({ timeout: 30_000 });

    // Read it back from a fresh page: the edit reached the server, not only the dialog's state.
    await openEditProject(page);
    await expect(page.locator('#dashboard-projects-edit-projectDescription')).toHaveValue(
      EDITED_DESCRIPTION
    );
    await page.keyboard.press('Escape');
  });

  test('cuts a new version', async ({ page }) => {
    await login(page);
    await gotoVersions(page);

    await page.getByTestId('versions-new-button').click();
    await expect(page.getByTestId('new-version-dialog')).toBeVisible();
    const nextVersion = (
      await page.getByTestId('new-version-preview').locator('.mono').textContent()
    )?.trim();
    expect(nextVersion, 'the dialog should preview the auto-generated version').toBeTruthy();
    await page.getByTestId('new-version-message').fill('Cut by the catalog journey');
    await page.getByTestId('new-version-submit').click();
    await expect(page.getByTestId('new-version-dialog')).toBeHidden({ timeout: 60_000 });

    const cell = page.locator('[data-testid^="versions-view-"]', { hasText: nextVersion! });
    await expect(cell).toBeVisible({ timeout: 60_000 });
    versionRecordId = ((await cell.getAttribute('data-testid')) ?? '').replace('versions-view-', '');
    expect(versionRecordId).toBeTruthy();
  });

  test('publishes the version', async ({ page }) => {
    await login(page);
    await gotoVersions(page);
    await rowAction(page, 'publish');

    await expect(page.getByTestId('publish-version-dialog')).toBeVisible();
    await page.getByTestId('publish-submit').click();
    await expect(page.getByTestId(`versions-published-chip-${versionRecordId}`)).toBeVisible({
      timeout: 60_000,
    });
  });

  test('unpublishes the version', async ({ page }) => {
    await login(page);
    await gotoVersions(page);
    await rowAction(page, 'unpublish');

    await page.getByRole('alertdialog').getByRole('button', { name: 'Unpublish' }).click();
    await expect(page.getByTestId(`versions-published-chip-${versionRecordId}`)).toBeHidden({
      timeout: 60_000,
    });
  });

  test('exports the version through the Export dialog', async ({ page }) => {
    await login(page);
    await gotoVersions(page);
    await rowAction(page, 'export');

    await expect(page.getByTestId('export-dialog-body')).toBeVisible();
    await page.getByTestId('export-dialog-choose-target').click({ timeout: 60_000 });
    await page.getByTestId(`export-target-${EXPORT_TARGET}`).click();
    await page.getByTestId('export-dialog-continue').click();

    // A lossy target asks for an acknowledgement first: a checkbox, or a typed phrase for a
    // near-empty result. Either way the phrase to type is the input's placeholder.
    await expect(page.getByTestId('export-dialog-export')).toBeVisible({ timeout: 60_000 });
    const typed = page.getByTestId('export-ack-typed-input');
    if (await typed.isVisible()) {
      await typed.fill((await typed.getAttribute('placeholder')) ?? '');
    } else if (await page.getByTestId('export-ack').isVisible()) {
      await page.getByTestId('export-ack').click();
    }
    await page.getByTestId('export-dialog-export').click();

    const emitted = page.getByTestId('export-dialog-emitted');
    await expect(emitted).toBeVisible({ timeout: 120_000 });
    await expect(emitted).toContainText('.proto');
    await page.getByTestId('export-dialog-done').click();
    await expect(page.getByTestId('export-dialog-body')).toBeHidden();
  });
});

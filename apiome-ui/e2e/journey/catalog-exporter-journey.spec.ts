/**
 * Catalog Exporter journey (X2, #6223).
 *
 * The export path end to end, through the real app, REST and Postgres: non-OpenAPI specs (RAML) are
 * imported into the Catalog; one item is exported through the in-place **Export** dialog (a
 * multi-file target, downloaded as the full bundle) and through **Export to another format…** — the
 * Export studio: target → verify → job → download; then three items are ticked and exported in one
 * batch from the bulk bar, and the archive's manifest lists all three.
 *
 * **Preview override.** It runs under `playwright.catalog-exporter-journey.config.ts`, whose server
 * opens exactly `CATALOG_EXPORTER_PREVIEW` — `export-studio` while the studio is held back, nothing
 * once it ships. Its first step proves the studio is reachable and that the other held-back
 * features are still hidden.
 *
 * Every wait is on a `data-testid` or a role the step's screen draws when it is ready — no sleeps.
 * Names carry a per-run suffix, so the items never collide with an earlier run's on a shared stack.
 */
import { test, expect, type Cookie, type Page } from '@playwright/test';
import { loadCorpus, readCorpusFile } from '../../lib/corpus/corpus';
import { acknowledgeLossIfAsked, downloadArchive, importIntoCatalog } from './support/catalog-export';
import { setMockPersona, type MockPersona } from './support/mock-oauth';
import { closeDb, seedMultiTenantFixture, MULTITENANT_FIXTURE } from './support/db';

const { user } = MULTITENANT_FIXTURE;

/** The same persona the RC6 journey signs in as (one GitHub link per user). */
const PERSONA: MockPersona = {
  email: user.email,
  name: user.name,
  login: 'grace-hopper',
  providerUserId: '900000004221',
  verified: true,
};

/** The RAML corpus entry, selected by manifest tag (never by hard-coded path). */
const CORPUS_ENTRY = (() => {
  const matches = loadCorpus({ format: 'raml', validityClass: 'valid', feature: 'base-uri' });
  if (matches.length !== 1) {
    throw new Error(`expected one valid RAML fixture with a base URI, found ${matches.length}`);
  }
  return matches[0];
})();

/** Unique per run; every item this run creates starts with it. */
const RUN = `Journey Export ${Date.now()}`;
const TITLES = [`${RUN} A`, `${RUN} B`, `${RUN} C`];

/** The RAML document retitled, so each import is its own catalog item. */
const ramlTitled = (title: string) => readCorpusFile(CORPUS_ENTRY).replace(/^title:.*$/m, `title: ${title}`);

/** Targets: a multi-file one for the dialog's bundle, Protobuf for the studio, GraphQL for the batch. */
const DIALOG_TARGET = 'avro';
const STUDIO_TARGET = 'protobuf';
const BULK_TARGET = 'graphql';

/** The item page's ⋯ row that opens the studio (`page-header-overflow-<row id>`). */
const STUDIO_ROW = 'export-studio';
/** The bulk dialog's run mode (`multi-export-<mode>-start`). */
const RUN_MODE = 'generate';

let itemId: string | null = null;
let sessionCookies: Cookie[] | null = null;

/**
 * Sign in as {@link PERSONA} once; later steps reuse the session (sign-in is rate limited).
 *
 * @param page The test's page.
 */
async function login(page: Page): Promise<void> {
  await page.context().clearCookies();
  if (sessionCookies) {
    await page.context().addCookies(sessionCookies);
    return;
  }
  await setMockPersona(PERSONA);
  await page.goto('/login');
  await page.getByRole('button', { name: /continue with github/i }).click();
  await page.waitForURL(/\/ade/, { timeout: 60_000 });
  sessionCookies = await page.context().cookies();
}

/**
 * Open the first item's page.
 *
 * @param page The test's page.
 */
async function gotoItem(page: Page): Promise<void> {
  expect(itemId, 'the import step must have found the item').not.toBeNull();
  await page.goto(`/ade/dashboard/catalog/${itemId}`);
  await expect(page.getByTestId('catalog-detail-export')).toBeVisible({ timeout: 60_000 });
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  await seedMultiTenantFixture();
});

test.afterAll(async () => {
  await closeDb();
});

test.describe('X2 — Catalog Exporter journey', () => {
  test('opens the Export studio and nothing else held back', async ({ page }) => {
    await login(page);
    await page.goto('/ade/dashboard/export/studio');
    await expect(page.getByTestId('export-studio-unscoped')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('unreleased-feature-gate')).toBeHidden();
    // Connectors stays held back: only the studio is opened early.
    await page.goto('/ade/dashboard/connectors');
    await expect(page.getByTestId('unreleased-feature-gate')).toBeVisible({ timeout: 60_000 });
  });

  test('imports three RAML specs into the Catalog', async ({ page }) => {
    test.slow(); // three imports, each a background job
    await login(page);
    for (const title of TITLES) {
      await importIntoCatalog(page, ramlTitled(title));
    }
    await page.goto('/ade/dashboard/catalog');
    await page.getByTestId('catalog-search').fill(TITLES[0]);
    await page.getByText(TITLES[0], { exact: true }).first().click();
    await page.waitForURL(/\/ade\/dashboard\/catalog\/[^/?]+/, { timeout: 60_000 });
    itemId = new URL(page.url()).pathname.split('/').at(-1) ?? null;
    expect(itemId).toBeTruthy();
  });

  test('exports the item through the Export dialog and downloads the full bundle', async ({ page }) => {
    await login(page);
    await gotoItem(page);
    await page.getByTestId('catalog-detail-export').click();

    await expect(page.getByTestId('export-dialog-body')).toBeVisible();
    await page.getByTestId('export-dialog-choose-target').click({ timeout: 60_000 });
    await page.getByTestId(`export-target-${DIALOG_TARGET}`).click();
    await page.getByTestId('export-dialog-continue').click();
    await expect(page.getByTestId('export-dialog-export')).toBeVisible({ timeout: 60_000 });
    await acknowledgeLossIfAsked(page);
    await page.getByTestId('export-dialog-export').click();
    await expect(page.getByTestId('export-dialog-emitted')).toBeVisible({ timeout: 120_000 });

    // A multi-file target downloads the job's bundle: every file plus the manifest (E1-4).
    const { filename, files } = await downloadArchive(page, () =>
      page.getByTestId('export-dialog-download-zip').click(),
    );
    expect(filename).toMatch(/\.zip$/);
    const paths = files.map((file) => file.path);
    expect(paths).toContain('manifest.json');
    expect(paths.some((path) => path.endsWith('.avsc'))).toBe(true);
    await page.getByTestId('export-dialog-done').click();
  });

  test('exports it to another format in the Export studio: verify, job, download', async ({ page }) => {
    await login(page);
    await gotoItem(page);
    await page.getByTestId('page-header-overflow').click();
    await page.getByTestId(`page-header-overflow-${STUDIO_ROW}`).click();
    await page.waitForURL(/\/ade\/dashboard\/export\/studio\?/, { timeout: 60_000 });
    await expect(page.getByTestId('export-studio')).toBeVisible({ timeout: 60_000 });

    await page.getByRole('button', { name: /choose target/i }).click({ timeout: 60_000 });
    await page.getByTestId(`export-target-${STUDIO_TARGET}`).click();
    await page.getByRole('button', { name: /^continue$/i }).click(); // Target → Options
    await page.getByRole('button', { name: /^continue$/i }).click(); // Options → Verify

    await page.getByTestId('verify-run').click();
    const toReview = page.getByRole('button', { name: /continue to review/i });
    await expect(page.getByTestId('verify-workbench')).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId('verify-progress-region')).toBeHidden({ timeout: 120_000 });
    await acknowledgeLossIfAsked(page);
    await expect(toReview).toBeEnabled({ timeout: 30_000 });
    await toReview.click();

    await page.getByTestId('export-studio-generate').click();
    const zip = page.getByRole('button', { name: /download \.zip/i });
    await expect(zip).toBeVisible({ timeout: 180_000 });
    const { files } = await downloadArchive(page, () => zip.click());
    expect(files.some((file) => file.path.endsWith('.proto'))).toBe(true);
  });

  test('exports three ticked items in one batch from the bulk bar', async ({ page }) => {
    await login(page);
    await page.goto('/ade/dashboard/catalog');
    await page.getByTestId('catalog-search').fill(RUN);
    for (const title of TITLES) {
      await page.getByRole('checkbox', { name: `Select ${title}` }).check({ timeout: 60_000 });
    }

    await page.getByTestId('catalog-bulk-export').click();
    await expect(page.getByTestId('catalog-bulk-export-dialog')).toBeVisible();
    await page.getByTestId(`catalog-bulk-export-target-${BULK_TARGET}`).click({ timeout: 60_000 });
    await page.getByTestId(`multi-export-${RUN_MODE}-start`).click();
    await expect(page.getByTestId('multi-export-outcomes')).toBeVisible({ timeout: 180_000 });

    const { filename, files } = await downloadArchive(page, () =>
      page.getByTestId('multi-export-download').click(),
    );
    expect(filename).toBe('export-batch.zip');
    const manifest = JSON.parse(files.find((file) => file.path === 'manifest.json')?.text ?? '{}');
    expect(manifest.kind).toBe('batch');
    expect(manifest.artifact_count).toBe(3);
    expect(manifest.completed_count).toBe(3);
    expect(new Set(manifest.items.map((item: { artifact: string }) => item.artifact)).size).toBe(3);
  });
});

import { test, expect, Route } from '@playwright/test';
import { testUsers } from './fixtures/test-fixtures';

interface MockSpec {
  fileId: string;
  path: string;
  format: string | null;
  confidence: number | null;
  discriminator: string | null;
  status: 'importing' | 'imported' | 'parse_error' | 'manifest_error' | 'not_imported' | 'unchanged_checksum';
  importEnabled: boolean;
  autoImportEnabled: boolean;
  lastImportedVersionId: string | null;
  lastImportedAt: string | null;
}

const repositoryId = 'repo-spec-9.4';

const seededSpecs: MockSpec[] = [
  {
    fileId: '11111111-1111-1111-1111-111111111111',
    path: 'openapi/orders-v3.yaml',
    format: 'openapi_3_1',
    confidence: 0.95,
    discriminator: 'openapi: 3.1.0',
    status: 'imported',
    importEnabled: true,
    autoImportEnabled: true,
    lastImportedVersionId: '22222222-2222-2222-2222-222222222222',
    lastImportedAt: new Date('2026-04-20T12:34:56Z').toISOString(),
  },
  {
    fileId: '33333333-3333-3333-3333-333333333333',
    path: 'openapi/legacy.yaml',
    format: 'swagger_2_0',
    confidence: 0.6,
    discriminator: 'swagger: "2.0"',
    status: 'not_imported',
    importEnabled: false,
    autoImportEnabled: false,
    lastImportedVersionId: null,
    lastImportedAt: null,
  },
  {
    fileId: '44444444-4444-4444-4444-444444444444',
    path: 'asyncapi/orders.yaml',
    format: 'asyncapi_2_6',
    confidence: 0.88,
    discriminator: 'asyncapi: 2.6.0',
    status: 'parse_error',
    importEnabled: false,
    autoImportEnabled: false,
    lastImportedVersionId: null,
    lastImportedAt: null,
  },
];

function buildSpecPayload(specs: MockSpec[]) {
  return specs.map((spec) => ({
    fileId: spec.fileId,
    repositoryId,
    scanId: 'scan-1',
    branch: 'main',
    path: spec.path,
    format: spec.format,
    confidence: spec.confidence,
    discriminator: spec.discriminator,
    status: spec.status,
    importEnabled: spec.importEnabled,
    autoImportEnabled: spec.autoImportEnabled,
    lastImportedVersionId: spec.lastImportedVersionId,
    lastImportedAt: spec.lastImportedAt,
    createdAt: new Date('2026-04-19T08:00:00Z').toISOString(),
  }));
}

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByPlaceholder('you@example.com').fill(testUsers.valid.email);
  await page.locator('input[type="password"]').fill(testUsers.valid.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForTimeout(2000);
}

test.describe('REPO-9.4 — Specs tab', () => {
  test.beforeEach(async ({ page }) => {
    const state = new Map<string, MockSpec>(seededSpecs.map((spec) => [spec.fileId, { ...spec }]));

    await page.route(`**/api/repositories/${repositoryId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          repository: {
            id: repositoryId,
            provider: 'github',
            owner: 'acme',
            name: 'orders-service',
            fullName: 'acme/orders-service',
            status: 'healthy',
            branches: [{ branch: 'main', subpathGlob: '**/*' }],
            timeline: [],
          },
        }),
      });
    });

    await page.route('**/api/sso/github/branches?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ branches: ['main'], defaultBranch: 'main' }),
      });
    });

    await page.route(`**/api/repositories/${repositoryId}/specs?**`, async (route) => {
      const payload = Array.from(state.values());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, items: buildSpecPayload(payload), limit: 200, nextCursor: null }),
      });
    });

    await page.route(
      new RegExp(`/api/repositories/${repositoryId}/specs/[0-9a-f-]{36}$`),
      async (route: Route) => {
        const url = new URL(route.request().url());
        const segments = url.pathname.split('/');
        const fileId = segments[segments.length - 1];
        const body = (await route.request().postDataJSON()) as {
          importEnabled?: boolean;
          autoImportEnabled?: boolean;
        };
        const current = state.get(fileId);
        if (!current) {
          await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'not found' }) });
          return;
        }
        const nextImportEnabled = body.importEnabled ?? current.importEnabled;
        let nextAutoImportEnabled = body.autoImportEnabled ?? current.autoImportEnabled;
        if (body.importEnabled === false) nextAutoImportEnabled = false;
        if (nextAutoImportEnabled && !nextImportEnabled) {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({
              success: false,
              error: 'Selection invariant violation',
              detail: { code: 'SELECTION_INVARIANT_VIOLATION', message: 'autoImportEnabled cannot be true when importEnabled is false' },
            }),
          });
          return;
        }
        const updated: MockSpec = {
          ...current,
          importEnabled: nextImportEnabled,
          autoImportEnabled: nextAutoImportEnabled,
        };
        state.set(fileId, updated);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, spec: buildSpecPayload([updated])[0] }),
        });
      },
    );

    await page.route(`**/api/repositories/${repositoryId}/specs/bulk-update`, async (route) => {
      const body = (await route.request().postDataJSON()) as {
        fileIds: string[];
        importEnabled?: boolean;
        autoImportEnabled?: boolean;
      };
      const updated: MockSpec[] = [];
      for (const fileId of body.fileIds) {
        const current = state.get(fileId);
        if (!current) continue;
        const nextImportEnabled = body.importEnabled ?? current.importEnabled;
        let nextAutoImportEnabled = body.autoImportEnabled ?? current.autoImportEnabled;
        if (body.importEnabled === false) nextAutoImportEnabled = false;
        const next: MockSpec = {
          ...current,
          importEnabled: nextImportEnabled,
          autoImportEnabled: nextAutoImportEnabled,
        };
        state.set(fileId, next);
        updated.push(next);
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, updatedCount: updated.length, items: buildSpecPayload(updated) }),
      });
    });
  });

  test('toggles import on and off optimistically with auto-import cleanup', async ({ page }) => {
    await login(page);
    if (page.url().includes('/login')) {
      test.skip(true, 'login failed - skipping authenticated specs flow');
      return;
    }

    await page.goto(`/ade/dashboard/repositories/${repositoryId}?tab=specs`);
    await expect(page.getByTestId('specs-tab-root')).toBeVisible();

    const legacyImport = page.getByTestId('spec-import-toggle-openapi/legacy.yaml');
    await expect(legacyImport).not.toBeChecked();
    await legacyImport.click();
    await expect(legacyImport).toBeChecked();

    const ordersImport = page.getByTestId('spec-import-toggle-openapi/orders-v3.yaml');
    const ordersAuto = page.getByTestId('spec-auto-toggle-openapi/orders-v3.yaml');
    await expect(ordersImport).toBeChecked();
    await expect(ordersAuto).toBeChecked();
    await ordersImport.click();
    await expect(ordersImport).not.toBeChecked();
    await expect(ordersAuto).not.toBeChecked();
    await expect(ordersAuto).toBeDisabled();
  });

  test('bulk-edit toggles selected rows', async ({ page }) => {
    await login(page);
    if (page.url().includes('/login')) {
      test.skip(true);
      return;
    }
    await page.goto(`/ade/dashboard/repositories/${repositoryId}?tab=specs`);
    await page.getByTestId('spec-row-select-openapi/legacy.yaml').click();
    await page.getByTestId('spec-row-select-asyncapi/orders.yaml').click();
    await expect(page.getByTestId('spec-bulk-bar')).toContainText('2 selected');
    await page.getByTestId('spec-bulk-enable-import').click();
    await expect(page.getByTestId('spec-import-toggle-openapi/legacy.yaml')).toBeChecked();
    await expect(page.getByTestId('spec-import-toggle-asyncapi/orders.yaml')).toBeChecked();
  });

  test('Import Now overflow action surfaces a success notification', async ({ page }) => {
    const importNowFileId = seededSpecs[0].fileId;
    await page.route(
      `**/api/repositories/${repositoryId}/specs/${importNowFileId}/import-now`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, importJobId: 'abcdef12-0000-0000-0000-000000000000' }),
        });
      },
    );
    await login(page);
    if (page.url().includes('/login')) {
      test.skip(true);
      return;
    }
    await page.goto(`/ade/dashboard/repositories/${repositoryId}?tab=specs`);
    await page.getByTestId('spec-overflow-openapi/orders-v3.yaml').click();
    await page.getByTestId('spec-import-now-openapi/orders-v3.yaml').click();
    await expect(page.getByTestId('spec-success')).toContainText('Import started');
  });

  test('filter chip changes deep-link via the status query string', async ({ page }) => {
    await login(page);
    if (page.url().includes('/login')) {
      test.skip(true);
      return;
    }
    await page.goto(`/ade/dashboard/repositories/${repositoryId}?tab=specs`);
    await page.getByTestId('spec-filter-failing').click();
    await expect(page).toHaveURL(/status=failing/);
    await expect(page.getByTestId('spec-row-asyncapi/orders.yaml')).toBeVisible();
    await expect(page.getByTestId('spec-row-openapi/orders-v3.yaml')).toHaveCount(0);
  });

  test('clicking a path opens the spec detail drawer', async ({ page }) => {
    await login(page);
    if (page.url().includes('/login')) {
      test.skip(true);
      return;
    }
    await page.goto(`/ade/dashboard/repositories/${repositoryId}?tab=specs`);
    await page.getByTestId('spec-row-path-openapi/orders-v3.yaml').click();
    await expect(page.getByTestId('spec-drawer')).toBeVisible();
    await expect(page.getByTestId('spec-drawer')).toContainText('openapi/orders-v3.yaml');
  });
});

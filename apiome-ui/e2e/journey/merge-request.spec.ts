/**
 * The branch / merge-request workflow, end to end (COL-4.3, #4527).
 *
 * The issue's acceptance criteria, driven through the real app, apiome-rest and Postgres:
 *
 *   1. **A named branch from a version line; edits on it don't touch the line** — the fixture drafts
 *      `feature/owners` off `main` and adds a class to it; `main`'s tip is unchanged until the merge.
 *   2. **Reviewers decide via the review flow** — the reviewer opens the merge request, follows its
 *      Review tab to the review page and approves there.
 *   3. **Merge executes via a merge session; the Changes tab shows the classified diff** — the author
 *      sees the classified changes and merges from the merge request page; apiome-rest confirms the
 *      new revision on `main`.
 *
 * Stack contract is the same as the other journey specs (`playwright.journey.config.ts` brings up a
 * dev server; REST + Postgres must already be up). Self-contained: `support/merge-request-fixture.ts`
 * seeds its own tenant, users and project with a per-run suffix.
 */
import { test, expect, type Page } from '@playwright/test';
import { closeDb } from './support/db';
import {
  closeMergeRequestFixtureDb,
  openMergeRequest,
  readMergeRequest,
  seedMergeRequestFixture,
  type JourneyUser,
  type MergeRequestFixture,
} from './support/merge-request-fixture';

let fixture: MergeRequestFixture;
let mergeRequestId = '';

/**
 * Sign a user in through the login page's email/password form.
 *
 * @param page - The Playwright page.
 * @param user - Who signs in.
 */
async function signIn(page: Page, user: JourneyUser): Promise<void> {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByRole('button', { name: 'or use your email' }).click();
  await page.locator('#email').fill(user.email);
  await page.locator('#password').fill(user.password);
  await page.locator('#credentials-form').getByRole('button', { name: /Sign In/ }).click();
  await page.waitForURL(/\/ade/, { timeout: 60_000 });
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fixture = await seedMergeRequestFixture();
  mergeRequestId = (await openMergeRequest(fixture)).id;
});

test.afterAll(async () => {
  await closeMergeRequestFixtureDb();
  await closeDb();
});

test.describe('COL-4.3 — branch / merge-request workflow', () => {
  test('the line is untouched and Merge waits for the review', async ({ page }) => {
    const stored = await readMergeRequest(fixture, mergeRequestId);
    expect(stored.target_tip_revision_id).toBe(fixture.main.tipId);

    await signIn(page, fixture.author);
    await page.goto(`/ade/merge-requests/${mergeRequestId}`);
    await expect(page.getByRole('heading', { name: /^Add owners/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('review-changes-compare')).toContainText('the merge base', { timeout: 60_000 });
    await expect(page.getByTestId('mr-blocker-review-pending')).toBeVisible();
    await expect(page.getByTestId('mr-merge')).toBeDisabled();
  });

  test('the reviewer approves through the review page', async ({ page }) => {
    await signIn(page, fixture.reviewer);
    await page.goto(`/ade/merge-requests/${mergeRequestId}?tab=review`);
    await page.getByTestId('mr-review-link').click();
    await page.waitForURL(/\/ade\/reviews\//, { timeout: 60_000 });
    await page.getByTestId('review-approve').click();
    await expect(page.getByTestId('review-status')).toHaveText('Approved');
  });

  test('the author merges into main through a merge session', async ({ page }) => {
    await signIn(page, fixture.author);
    await page.goto(`/ade/merge-requests/${mergeRequestId}`);
    const merge = page.getByTestId('mr-merge');
    await expect(merge).toBeEnabled({ timeout: 60_000 });
    await merge.click();
    await expect(page.getByTestId('mr-state')).toHaveText('Merged', { timeout: 60_000 });

    const stored = await readMergeRequest(fixture, mergeRequestId);
    expect(stored.merge_request.state).toBe('merged');
    expect(stored.merge_request.merged_version_id).toBeTruthy();
    expect(stored.merge_request.merged_version_id).not.toBe(fixture.main.tipId);
  });
});

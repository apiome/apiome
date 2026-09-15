/**
 * The review page, end to end (COL-2.2, #4518).
 *
 * The issue's acceptance criteria, driven through the real app, apiome-rest and Postgres:
 *
 *   1. **A reviewer completes a decision entirely on the review page** — both flows start at
 *      `/ade/reviews/{id}` and never navigate away, and apiome-rest confirms what was recorded.
 *   2. **The diff tab lazy-loads** — no document is built until the reviewer asks for one.
 *   3. **Approve** and **request changes** (with its required note) are both covered.
 *
 * Stack contract is the same as the other journey specs (`playwright.journey.config.ts` brings up a
 * dev server; REST + Postgres must already be up). Self-contained: `support/review-fixture.ts` seeds
 * its own tenant, users and project with a per-run suffix and requests both reviews through
 * apiome-rest, so re-runs on a shared stack are independent.
 */
import { test, expect, type Page } from '@playwright/test';
import { closeDb } from './support/db';
import {
  closeReviewFixtureDb,
  readReview,
  requestReview,
  seedReviewFixture,
  type ReviewFixture,
} from './support/review-fixture';

let fixture: ReviewFixture;
let approveReviewId = '';
let changesReviewId = '';

/**
 * Sign the reviewer in through the login page's email/password form.
 *
 * @param page - The Playwright page.
 */
async function signInAsReviewer(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByRole('button', { name: 'or use your email' }).click();
  await page.locator('#email').fill(fixture.reviewer.email);
  await page.locator('#password').fill(fixture.reviewer.password);
  await page.locator('#credentials-form').getByRole('button', { name: /Sign In/ }).click();
  await page.waitForURL(/\/ade/, { timeout: 60_000 });
}

/**
 * Open a review and wait for its header.
 *
 * @param page - The Playwright page.
 * @param reviewId - The review.
 * @param versionLabel - The version under review, as the title names it.
 */
async function openReview(page: Page, reviewId: string, versionLabel: string): Promise<void> {
  await page.goto(`/ade/reviews/${reviewId}`);
  await expect(page.getByRole('heading', { name: `Review of v${versionLabel}` })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('review-status')).toHaveText('In review');
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fixture = await seedReviewFixture();
  approveReviewId = await requestReview(fixture, fixture.approveDraft);
  changesReviewId = await requestReview(fixture, fixture.changesDraft);
});

test.afterAll(async () => {
  await closeReviewFixtureDb();
  await closeDb();
});

test.describe('COL-2.2 — review page', () => {
  test('a reviewer reads every tab and approves, without leaving the page', async ({ page }) => {
    await signInAsReviewer(page);

    const documentRequests: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/reviews\/[^/]+\/spec/.test(request.url())) documentRequests.push(request.url());
    });

    await openReview(page, approveReviewId, fixture.approveDraft.label);
    const reviewUrl = page.url();

    // Changes is the default tab: it compares with the published baseline…
    await expect(page.getByTestId('review-changes-compare')).toContainText(`v${fixture.baseline.label}`, {
      timeout: 60_000,
    });
    // …and builds no document until one is asked for.
    expect(documentRequests).toEqual([]);

    await page.getByTestId('review-view-plain').click();
    await expect(page.getByTestId('review-plain-diff')).toBeVisible({ timeout: 60_000 });
    expect(documentRequests.length).toBe(2);

    await page.getByTestId('review-tab-spec').click();
    await expect(page.getByTestId('review-spec')).toBeVisible({ timeout: 60_000 });

    await page.getByTestId('review-tab-discussion').click();
    await expect(page.getByTestId('project-discussion-panel')).toBeVisible({ timeout: 60_000 });

    await page.getByTestId('review-decision-note').fill('Owners look right to me.');
    await page.getByTestId('review-approve').click();

    await expect(page.getByTestId('review-status')).toHaveText('Approved');
    await expect(page.getByTestId('review-decision-message')).toHaveText('You approved this round.');
    expect(page.url().split('?')[0]).toBe(reviewUrl.split('?')[0]);

    const stored = await readReview(fixture, approveReviewId);
    expect(stored.review.state).toBe('approved');
    expect(stored.reviewers[0]).toMatchObject({ decision: 'approve', note: 'Owners look right to me.' });
  });

  test('requesting changes needs a note, then records it', async ({ page }) => {
    await signInAsReviewer(page);

    const decisionPosts: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().includes('/decision')) decisionPosts.push(request.url());
    });

    await openReview(page, changesReviewId, fixture.changesDraft.label);

    await page.getByTestId('review-request-changes').click();
    await expect(page.getByText('Say what needs to change before requesting changes.')).toBeVisible();
    await expect(page.getByTestId('review-decision-note')).toBeFocused();
    expect(decisionPosts).toEqual([]);

    await page.getByTestId('review-decision-note').fill('Pet was removed — keep it, or bump the major version.');
    await page.getByTestId('review-request-changes').click();

    await expect(page.getByTestId('review-status')).toHaveText('Changes requested');
    await expect(page.getByTestId('review-decision-message')).toHaveText('You requested changes in this round.');
    await expect(page.getByTestId('review-reviewers')).toContainText('Pet was removed — keep it, or bump the major version.');
    expect(decisionPosts.length).toBe(1);

    const stored = await readReview(fixture, changesReviewId);
    expect(stored.review.state).toBe('changes_requested');
    expect(stored.reviewers[0]).toMatchObject({
      decision: 'request_changes',
      note: 'Pet was removed — keep it, or bump the major version.',
    });
  });
});

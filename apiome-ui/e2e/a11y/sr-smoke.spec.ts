import { test, expect } from '@playwright/test';

import { mountMarkup, readFixture } from '../support/a11y';

/**
 * Screen-reader smoke — HIVE-10.2 (#5338).
 *
 * The acceptance criterion asks for a screen-reader pass on login, home, projects and a dialog.
 * These snapshots pin what a screen reader is given on each: the landmarks, the heading outline
 * and the names of the controls a reader reaches first. They are *partial* templates — copy and
 * volatile text (a version number, a greeting) are left out — so they fail on a lost name, role,
 * heading level or landmark, not on wording. Projects is pinned in `hive-projects.spec.ts`, beside
 * the markup it mounts.
 *
 * The manual pass with a real screen reader (VoiceOver, NVDA) follows the checklist in
 * `apiome-docs/docs/reference/accessibility.md`; this is the part of it a machine can hold steady.
 */

test.use({ viewport: { width: 1280, height: 900 } });

test('login: one main landmark, an h1, and the sign-in choices by name', async ({ page }) => {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await expect(page.locator('body')).toMatchAriaSnapshot(`
    - main:
      - region "About Apiome"
      - heading "Welcome back" [level=1]
      - button "Continue with GitHub"
      - button "Continue with GitLab"
      - button "or use your email"
  `);
});

test('home: the launcher names its regions, its h1 and every application', async ({ page }) => {
  await mountMarkup(page, readFixture('hive-a11y', 'launcher.html'));
  await expect(page.locator('#a11y-mount')).toMatchAriaSnapshot(`
    - link "Apiome home"
    - button "Preferences"
    - button "Sign out"
    - main:
      - heading "Your API specification workspace" [level=1]
      - region "Applications":
        - heading "Applications" [level=2]
        - link "Open Control Panel"
      - region "Resources":
        - heading "Resources" [level=2]
  `);
});

test('a dialog: an alertdialog named by its question, with its two answers', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/design-system');
  await page.waitForLoadState('networkidle');
  await page.locator('#dialogs').getByRole('button', { name: 'Destructive confirm' }).click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toMatchAriaSnapshot(`
    - alertdialog "Delete role \\"Release manager\\"?":
      - heading "Delete role \\"Release manager\\"?" [level=2]
      - button "Cancel"
      - button "Delete role"
  `);
  // The safe answer has focus, so a reader who presses Enter by reflex deletes nothing.
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
});

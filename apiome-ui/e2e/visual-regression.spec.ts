import { test, expect } from '@playwright/test';

/**
 * Visual Regression Tests
 *
 * These tests capture screenshots to detect visual regressions
 * in the UI. They compare against baseline screenshots.
 */

test.describe('Visual Regression Tests', () => {
  test.describe('Login Page Visual Tests', () => {
    test('login page desktop view', async ({ page }) => {
      await page.setViewportSize({ width: 1920, height: 1080 });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Wait for any animations to complete
      await page.waitForTimeout(500);

      // Take screenshot for visual comparison
      await expect(page).toHaveScreenshot('login-desktop.png', {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });

    test('login page tablet view', async ({ page }) => {
      await page.setViewportSize({ width: 768, height: 1024 });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      await page.waitForTimeout(500);

      await expect(page).toHaveScreenshot('login-tablet.png', {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });

    test('login page mobile view', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      await page.waitForTimeout(500);

      await expect(page).toHaveScreenshot('login-mobile.png', {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });

    test('login page sign up mode', async ({ page }) => {
      await page.setViewportSize({ width: 1920, height: 1080 });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Toggle to sign up mode
      const createAccountLink = page.getByText(/create a new account/i);
      if (await createAccountLink.isVisible()) {
        await createAccountLink.click();
        await page.waitForTimeout(500);

        await expect(page).toHaveScreenshot('login-signup-mode.png', {
          maxDiffPixels: 100,
          fullPage: true,
        });
      }
    });
  });

  test.describe('Theme Tests', () => {
    test('should respect system dark mode preference', async ({ page }) => {
      // Emulate dark color scheme
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(500);

      await expect(page).toHaveScreenshot('login-dark-mode.png', {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });

    test('should respect system light mode preference', async ({ page }) => {
      // Emulate light color scheme
      await page.emulateMedia({ colorScheme: 'light' });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(500);

      await expect(page).toHaveScreenshot('login-light-mode.png', {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });
  });

  test.describe('Component Visual Tests', () => {
    test('login form elements are properly styled', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Screenshot just the form area
      const form = page.locator('form').first();
      if (await form.isVisible()) {
        await expect(form).toHaveScreenshot('login-form.png', {
          maxDiffPixels: 50,
        });
      }
    });

    test('SSO buttons are properly styled', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Find SSO button container or individual buttons
      const githubButton = page.getByRole('button', { name: /github/i });
      if (await githubButton.isVisible()) {
        await expect(githubButton).toHaveScreenshot('github-sso-button.png', {
          maxDiffPixels: 20,
        });
      }
    });
  });
});

test.describe('Responsive Design Tests', () => {
  const viewports = [
    { name: 'mobile-sm', width: 320, height: 568 },
    { name: 'mobile-md', width: 375, height: 667 },
    { name: 'mobile-lg', width: 414, height: 896 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'laptop', width: 1024, height: 768 },
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'desktop-lg', width: 1920, height: 1080 },
  ];

  for (const viewport of viewports) {
    test(`login page renders correctly at ${viewport.name} (${viewport.width}x${viewport.height})`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Basic checks that content is visible
      const form = page.locator('form');
      await expect(form).toBeVisible();

      // Email input should be visible
      const emailInput = page.getByPlaceholder('you@example.com');
      await expect(emailInput).toBeVisible();

      // No horizontal scroll should be present (content should fit)
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(hasHorizontalScroll).toBeFalsy();
    });
  }
});


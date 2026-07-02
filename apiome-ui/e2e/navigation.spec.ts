import { test, expect } from '@playwright/test';

/**
 * Navigation E2E Tests
 *
 * Tests the application navigation including:
 * - Route accessibility
 * - Redirect behavior
 * - Protected routes
 * - Navigation links
 */

test.describe('Application Navigation', () => {
  test.describe('Public Routes', () => {
    test('root path should redirect to login', async ({ page }) => {
      await page.goto('/');

      // Should redirect to login
      await page.waitForURL(/login/);
      expect(page.url()).toContain('login');
    });

    test('login page should be accessible', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Page should load without errors
      const title = await page.title();
      expect(title).toBeTruthy();

      // Should have form elements
      const form = page.locator('form');
      await expect(form).toBeVisible();
    });
  });

  test.describe('Protected Routes (without auth)', () => {
    test('dashboard should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/dashboard');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('studio should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/studio');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('studio editor should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/studio/editor');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('studio paths should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/studio/paths');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('studio code should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/studio/code');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('projects page should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/dashboard/projects');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('tenants page should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/dashboard/tenants');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('api-keys page should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/dashboard/api-keys');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });

    test('profile page should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/ade/dashboard/profile');

      // Should redirect to login
      await page.waitForURL(/login/, { timeout: 10000 });
      expect(page.url()).toContain('login');
    });
  });

  test.describe('Error Handling', () => {
    test('non-existent route should show 404 or redirect', async ({ page }) => {
      const response = await page.goto('/non-existent-page-12345');

      // Either shows 404 page or redirects
      const status = response?.status();
      const url = page.url();

      // Should either be 404 status, or redirect to a valid page
      expect(status === 404 || url.includes('login') || url.includes('404')).toBeTruthy();
    });
  });

  test.describe('Page Load Performance', () => {
    test('login page should load within acceptable time', async ({ page }) => {
      const startTime = Date.now();

      await page.goto('/login');
      await page.waitForLoadState('domcontentloaded');

      const loadTime = Date.now() - startTime;

      // Page should load within 10 seconds
      expect(loadTime).toBeLessThan(10000);
    });
  });
});


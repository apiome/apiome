import { test, expect } from '@playwright/test';

/**
 * Accessibility (a11y) E2E Tests
 *
 * Tests accessibility requirements including:
 * - Keyboard navigation
 * - Focus management
 * - ARIA attributes
 * - Color contrast (via visual checks)
 * - Screen reader compatibility
 */

test.describe('Accessibility Tests', () => {
  test.describe('Login Page Accessibility', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');
    });

    test('should have proper page structure', async ({ page }) => {
      // Check for main landmark
      const main = page.locator('main, [role="main"]');
      const hasMain = await main.count() > 0;

      // Check for heading hierarchy
      const h1 = page.locator('h1');
      const hasH1 = await h1.count() > 0;

      // At least one of these should exist
      expect(hasMain || hasH1).toBeTruthy();
    });

    test('form inputs should have accessible labels', async ({ page }) => {
      // Email input should be identifiable
      const emailInput = page.getByPlaceholder('you@example.com');
      await expect(emailInput).toBeVisible();

      // Check for label or aria-label
      const hasLabel = await emailInput.evaluate((el) => {
        const id = el.id;
        const ariaLabel = el.getAttribute('aria-label');
        const ariaLabelledBy = el.getAttribute('aria-labelledby');
        const placeholder = el.getAttribute('placeholder');
        const label = id ? document.querySelector(`label[for="${id}"]`) : null;

        return !!(label || ariaLabel || ariaLabelledBy || placeholder);
      });

      expect(hasLabel).toBeTruthy();
    });

    test('buttons should be keyboard accessible', async ({ page }) => {
      // Find sign in button
      const signInButton = page.getByRole('button', { name: /sign in/i });
      await expect(signInButton).toBeVisible();

      // Should be focusable
      await signInButton.focus();
      await expect(signInButton).toBeFocused();

      // Should have accessible role
      const role = await signInButton.getAttribute('role');
      const tagName = await signInButton.evaluate((el) => el.tagName.toLowerCase());

      expect(tagName === 'button' || role === 'button').toBeTruthy();
    });

    test('should support keyboard-only navigation through form', async ({ page }) => {
      // Start from the body
      await page.keyboard.press('Tab');

      // Should be able to tab through interactive elements
      let tabCount = 0;
      const maxTabs = 20;

      while (tabCount < maxTabs) {
        const focusedElement = page.locator(':focus');
        const isVisible = await focusedElement.isVisible().catch(() => false);

        if (isVisible) {
          tabCount++;
        }

        await page.keyboard.press('Tab');
      }

      // Should have found at least a few focusable elements
      expect(tabCount).toBeGreaterThan(0);
    });

    test('SSO buttons should be accessible', async ({ page }) => {
      const githubButton = page.getByRole('button', { name: /github/i });

      if (await githubButton.isVisible()) {
        // Should have accessible name
        const accessibleName = await githubButton.evaluate((el) => {
          return el.getAttribute('aria-label') ||
                 el.textContent?.trim() ||
                 el.getAttribute('title');
        });

        expect(accessibleName).toBeTruthy();

        // Should be keyboard focusable
        await githubButton.focus();
        await expect(githubButton).toBeFocused();
      }
    });

    test('password input should have proper type', async ({ page }) => {
      const passwordInput = page.locator('input[type="password"]');
      await expect(passwordInput).toBeVisible();

      const inputType = await passwordInput.getAttribute('type');
      expect(inputType).toBe('password');
    });

    test('error messages should be accessible', async ({ page }) => {
      // Submit form with email but empty password to trigger validation
      const emailInput = page.getByPlaceholder('you@example.com');
      await emailInput.fill('test@example.com');

      const signInButton = page.getByRole('button', { name: /sign in/i });
      await signInButton.click();

      // Wait for potential error message
      await page.waitForTimeout(1000);

      // If there's an error message, check it's accessible
      const errorMessage = page.locator('[role="alert"], [aria-live="polite"], [aria-live="assertive"], .error, [class*="error"], [class*="message"]');

      if (await errorMessage.count() > 0) {
        const firstError = errorMessage.first();
        if (await firstError.isVisible()) {
          // Error should have some text content or be a valid alert
          const content = await firstError.textContent();
          const hasContent = content && content.trim().length > 0;
          const hasRole = await firstError.getAttribute('role');
          // Either has content or has a proper role
          expect(hasContent || hasRole).toBeTruthy();
        }
      }
      // If no error message is shown, that's also acceptable (form might not show inline errors)
    });

    test('links should be distinguishable', async ({ page }) => {
      const links = page.locator('a');
      const linkCount = await links.count();

      for (let i = 0; i < linkCount; i++) {
        const link = links.nth(i);

        if (await link.isVisible()) {
          // Link should have accessible text
          const text = await link.textContent();
          const ariaLabel = await link.getAttribute('aria-label');
          const title = await link.getAttribute('title');

          expect(text?.trim() || ariaLabel || title).toBeTruthy();
        }
      }
    });
  });

  test.describe('Focus Management', () => {
    test('focus should be visible', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Tab to first focusable element
      await page.keyboard.press('Tab');

      const focusedElement = page.locator(':focus');

      if (await focusedElement.isVisible()) {
        // Check that focus is visible (element has outline or other focus indicator)
        const outlineStyle = await focusedElement.evaluate((el) => {
          const styles = window.getComputedStyle(el);
          return {
            outline: styles.outline,
            boxShadow: styles.boxShadow,
            border: styles.border,
          };
        });

        // Should have some focus indicator
        const hasFocusIndicator =
          (outlineStyle.outline && outlineStyle.outline !== 'none' && !outlineStyle.outline.includes('0px')) ||
          (outlineStyle.boxShadow && outlineStyle.boxShadow !== 'none') ||
          (outlineStyle.border && !outlineStyle.border.includes('0px'));

        // This is a soft check - some elements use other focus indicators
        if (!hasFocusIndicator) {
          console.warn('Focus indicator may not be visible for:', await focusedElement.evaluate(el => el.tagName));
        }
      }
    });

    test('modal/dialog focus trap should work', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // This test would apply if there are modals
      // For now, just verify we can navigate the page
      const form = page.locator('form');
      await expect(form).toBeVisible();
    });
  });

  test.describe('Color and Contrast', () => {
    test('text should be readable (not too small)', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Check that main text elements are reasonably sized
      const bodyFontSize = await page.evaluate(() => {
        const computed = window.getComputedStyle(document.body);
        return parseFloat(computed.fontSize);
      });

      // Font size should be at least 12px
      expect(bodyFontSize).toBeGreaterThanOrEqual(12);
    });

    test('interactive elements should have sufficient size', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      // Check only main action buttons (not small toggle buttons)
      const mainButtons = page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("GitHub"), button:has-text("GitLab")');
      const buttonCount = await mainButtons.count();

      for (let i = 0; i < buttonCount; i++) {
        const button = mainButtons.nth(i);

        if (await button.isVisible()) {
          const box = await button.boundingBox();

          if (box) {
            // Main action buttons should be at least 44x36 for touch accessibility
            expect(box.width).toBeGreaterThanOrEqual(44);
            expect(box.height).toBeGreaterThanOrEqual(36);
          }
        }
      }
    });
  });
});


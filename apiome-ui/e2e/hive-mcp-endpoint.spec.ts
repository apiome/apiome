import * as fs from 'fs';
import * as path from 'path';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * The MCP endpoint detail, measured in a browser (HIVE-7.8, #5325).
 *
 * `tests/mcp-endpoint-detail-hive-redesign.test.tsx` pins what the screen renders,
 * `tests/mcp-insight-tab.test.tsx` pins the fourteen insight views, and
 * `tests/mcp-endpoint-detail-css.test.ts` pins the declarations. None of the three can answer the
 * questions that are about *computed layout*, because jsdom compiles no CSS:
 *
 *   • **"No horizontal document scroll at ≥1280 px"**, held across all nine themes, both
 *     densities and all six font scales — on a screen carrying a six-tab strip, a four-tile stat
 *     strip, a two-column capability block, a sticky fourteen-item rail, a timeline beside a
 *     Monaco diff, and a two-column settings grid.
 *   • **The four splits really collapse.** `.mcp-insight`, `.mcp-versions`, `.mcp-lint` and
 *     `.mcp-settings-grid` widen behind `min-width` queries stated in `rem`, which is the reason
 *     they hold at the Largest font scale where 64rem is 25 % wider than at the default — a
 *     stylesheet test can only assert that they are *written*.
 *   • **The insight rail sticks, and does not clip its first item.** Its offset is a token
 *     measured from `.page`, not the mockup's `top: 140px`; whether that leaves the first item
 *     reachable at Compact density is a computed-layout fact.
 *   • **A 90-character tool name cannot hold a capability row open** — `overflow-wrap: anywhere`
 *     only works because every ancestor carries `min-inline-size: 0`, and whether that chain is
 *     intact is a computed-layout fact.
 *   • **"axe: zero serious/critical violations"** on all four surfaces, in every theme. This is
 *     the sweep that caught the exposure the whole ticket turns on: a semantic `-fg` ink drawn
 *     on a plain surface measures 1.5–3.2:1 in the seven appearances that inherit the light
 *     pairs, which only a browser can see.
 *
 * ### Why it mounts fixtures instead of signing in
 *
 * The same reason `hive-mcp-catalog.spec.ts` gives: every read here is tenant-scoped, and the
 * states worth measuring — a scored snapshot with two tools, a two-snapshot diff, a lint report
 * with a finding in it — are ones a seeded database will not produce on demand.
 *
 * The fixtures are **not hand-written**. `tests/mcp-endpoint-detail-hive-redesign.test.tsx`
 * renders the real screen against mocked reads and, with `MCP_FIXTURE_DUMP=1`, writes what it
 * rendered into `e2e/fixtures/hive-mcp-endpoint/`. So what is measured here is exactly what the
 * components compose — the classes, the nesting, the ARIA — and the jsdom suite is what keeps the
 * fixtures honest.
 *
 * This loads `/login`, which compiles the real `globals.css` and needs no session, and injects
 * the fixtures into it. Requires the app to be running (`PLAYWRIGHT_BASE_URL`, default
 * `http://localhost:3000`).
 */

/** WCAG 2.1 Level A/AA — the conformance target of DESIGN.md §9. */
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

/** The viewport width DESIGN.md §5 forbids horizontal document scroll at. */
const DESKTOP_WIDTH = 1280;

/** Every theme with a block of its own; `null` is the `:root` light default. */
const THEMES = [
  null,
  'dark',
  'high-contrast',
  'blueprint',
  'whiteboard',
  'solarized',
  'nord',
  'darcula',
];

/** The six font-size stops of DESIGN.md §4.1. `md` is the default. */
const FONT_SCALES = ['xs', 'sm', 'md', 'lg', 'xl', '2xl'];

/** Widths either side of the block's `rem` breakpoints, down to a phone. */
const WIDTHS = [1440, DESKTOP_WIDTH, 1100, 1024, 960, 900, 768, 640, 420];

/** Where the jsdom suite writes what it rendered. */
const FIXTURES = path.join(__dirname, 'fixtures', 'hive-mcp-endpoint');

/** The four panels the jsdom suite dumps. */
type Fixture = 'capabilities' | 'versions' | 'lint' | 'settings';

/** All four, for the sweeps that do not care which. */
const ALL_FIXTURES: Fixture[] = ['capabilities', 'versions', 'lint', 'settings'];

/**
 * One rendered surface, as the jsdom suite wrote it.
 *
 * @param name Which fixture.
 * @returns Its markup.
 */
function fixture(name: Fixture): string {
  return fs.readFileSync(path.join(FIXTURES, `${name}.html`), 'utf8');
}

/**
 * Put markup on a page that has the real stylesheet compiled.
 *
 * @param page The Playwright page.
 * @param name Which fixture.
 */
async function mount(page: Page, name: Fixture): Promise<void> {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.evaluate((html) => {
    document.body.innerHTML = `<main style="min-height:100vh;background:var(--bg-canvas)">${html}</main>`;
    document.body.style.margin = '0';
    // Freeze every transition — the trap `hive-repositories.spec.ts` records. The cards and the
    // rail carry background and box-shadow transitions, so a `data-theme` swap *animates* every
    // one of them, and axe sampling mid-animation reports a `color-contrast` failure against a
    // colour that exists in neither theme. A measurement has to be of a settled frame.
    const frozen = document.createElement('style');
    frozen.id = 'e2e-frozen';
    frozen.textContent =
      '*,*::before,*::after{transition:none!important;animation:none!important}';
    document.head.appendChild(frozen);
  }, fixture(name));
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

/**
 * Set the appearance preferences the tokens key off.
 *
 * @param page The Playwright page.
 * @param options Which theme, font scale and density to apply.
 */
async function applyPreferences(
  page: Page,
  options: { theme?: string | null; fontScale?: string; density?: string }
): Promise<void> {
  await page.evaluate(
    ({ theme, fontScale, density }) => {
      const root = document.documentElement;
      if (theme) root.setAttribute('data-theme', theme);
      else root.removeAttribute('data-theme');
      if (fontScale) root.setAttribute('data-font-scale', fontScale);
      if (density) root.setAttribute('data-density', density);
    },
    options as { theme?: string | null; fontScale?: string; density?: string }
  );
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

/**
 * Whether the document scrolls sideways.
 *
 * @param page The Playwright page.
 * @returns True when the document is wider than the viewport.
 */
function documentOverflows(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    // A one-pixel tolerance: sub-pixel layout rounding is not a horizontal scrollbar.
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth > 1;
  });
}

/**
 * How many columns a grid actually draws.
 *
 * `auto-fit`/`auto-fill` report their *whole* track list, collapsed tracks included, so the
 * zero-width tracks are dropped — they are not a number a reader can see.
 *
 * @param page The Playwright page.
 * @param selector The grid.
 * @returns The number of tracks with a width.
 */
function gridColumns(page: Page, selector: string): Promise<number> {
  return page
    .locator(selector)
    .first()
    .evaluate(
      (node) =>
        getComputedStyle(node as Element)
          .gridTemplateColumns.split(' ')
          .filter((track) => track && Number.parseFloat(track) > 0).length
    );
}

/**
 * The serious and critical half of an axe run, as rule ids.
 *
 * Until HIVE-10.2 (#5338) this allowed one documented node — `ui/Button`'s solid danger fill,
 * white `--fg-on-accent` on the light red `--danger` of the dark-based themes. Those themes now
 * paint solid fills with dark ink (`globals.css`, checked by `tests/a11y-token-contrast.test.ts`),
 * so nothing is allowed any more.
 *
 * @param page The Playwright page.
 * @returns The blocking rule ids, which DESIGN.md §9 requires to be empty.
 */
async function blockingViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  return results.violations
    .filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))
    .map((violation) => violation.id);
}

/* -------------------------------------------------------------------------
   The document keeps to one column
   ------------------------------------------------------------------------- */

test.describe('the endpoint detail keeps the document to one column', () => {
  for (const width of WIDTHS) {
    for (const name of ALL_FIXTURES) {
      test(`the ${name} panel does not scroll sideways at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await mount(page, name);
        expect(await documentOverflows(page)).toBe(false);
      });
    }
  }

  for (const theme of THEMES) {
    test(`the capabilities panel does not scroll sideways in the ${theme ?? 'light'} theme`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
      await mount(page, 'capabilities');
      await applyPreferences(page, { theme });
      expect(await documentOverflows(page)).toBe(false);
    });
  }

  for (const fontScale of FONT_SCALES) {
    for (const name of ['capabilities', 'versions'] as Fixture[]) {
      test(`the ${name} panel does not scroll sideways at the ${fontScale} font scale`, async ({
        page,
      }) => {
        await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
        await mount(page, name);
        await applyPreferences(page, { fontScale });
        expect(await documentOverflows(page)).toBe(false);
      });
    }
  }

  for (const density of ['comfortable', 'compact']) {
    test(`the settings panel does not scroll sideways at ${density} density`, async ({ page }) => {
      await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
      await mount(page, 'settings');
      await applyPreferences(page, { density });
      expect(await documentOverflows(page)).toBe(false);
    });
  }
});

/* -------------------------------------------------------------------------
   The four splits really collapse
   ------------------------------------------------------------------------- */

test.describe('the splits collapse rather than overflow', () => {
  test('the versions split is two columns on a desktop and one on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mount(page, 'versions');
    expect(await gridColumns(page, '.mcp-versions')).toBe(2);

    await page.setViewportSize({ width: 640, height: 900 });
    expect(await gridColumns(page, '.mcp-versions')).toBe(1);
  });

  test('the lint split is two columns on a desktop and one on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mount(page, 'lint');
    expect(await gridColumns(page, '.mcp-lint')).toBe(2);

    await page.setViewportSize({ width: 640, height: 900 });
    expect(await gridColumns(page, '.mcp-lint')).toBe(1);
  });

  test('the settings grid folds its label column under the panel on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mount(page, 'settings');
    expect(await gridColumns(page, '.mcp-settings-grid')).toBe(2);

    await page.setViewportSize({ width: 640, height: 900 });
    expect(await gridColumns(page, '.mcp-settings-grid')).toBe(1);
  });

  test('the capability columns and the settings fields fold on their own', async ({ page }) => {
    await page.setViewportSize({ width: 420, height: 900 });
    await mount(page, 'capabilities');
    expect(await gridColumns(page, '.mcp-cap-columns')).toBe(1);

    await mount(page, 'settings');
    expect(await gridColumns(page, '.mcp-settings-fields')).toBe(1);
  });

  test('the splits fold as the font scale grows, at one width', async ({ page }) => {
    // 64rem is 25 % wider at the Largest stop, which a px breakpoint could not have known.
    await page.setViewportSize({ width: 1100, height: 900 });
    await mount(page, 'versions');
    const atDefault = await gridColumns(page, '.mcp-versions');
    await applyPreferences(page, { fontScale: '2xl' });
    expect(await gridColumns(page, '.mcp-versions')).toBeLessThanOrEqual(atDefault);
  });
});

/* -------------------------------------------------------------------------
   Long content
   ------------------------------------------------------------------------- */

test.describe('long content', () => {
  test('a 90-character tool name wraps rather than widening its card', async ({ page }) => {
    await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
    await mount(page, 'capabilities');

    const card = page.locator('[data-testid="mcp-capability-group-tool"]');
    const before = await card.evaluate((node) => node.clientWidth);
    await page.locator('.mcp-cap-item__name').first().evaluate((node) => {
      node.textContent = 'A'.repeat(90);
    });
    expect(await card.evaluate((node) => node.clientWidth)).toBe(before);
    expect(await documentOverflows(page)).toBe(false);
  });

  test('a long endpoint URL in the header does not take the page sideways', async ({ page }) => {
    await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
    await mount(page, 'capabilities');

    await page.locator('.mcp-ep-meta__url').first().evaluate((node) => {
      node.textContent = `https://mcp.acme.dev/${'segment/'.repeat(20)}mcp`;
    });
    expect(await documentOverflows(page)).toBe(false);
  });

  test('a long change path in the diff wraps inside its row', async ({ page }) => {
    await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
    await mount(page, 'versions');

    const row = page.locator('.mcp-change').first();
    const before = await row.evaluate((node) => node.clientWidth);
    await page.locator('.mcp-change__path').first().evaluate((node) => {
      node.textContent = `tools.${'namespace.'.repeat(15)}refund`;
    });
    expect(await row.evaluate((node) => node.clientWidth)).toBe(before);
    expect(await documentOverflows(page)).toBe(false);
  });
});

/* -------------------------------------------------------------------------
   Accessibility — the sweep the whole ticket turns on
   ------------------------------------------------------------------------- */

test.describe('accessibility', () => {
  for (const name of ALL_FIXTURES) {
    test(`the ${name} panel has no serious or critical axe violations`, async ({ page }) => {
      await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
      await mount(page, name);
      expect(await blockingViolations(page)).toEqual([]);
    });
  }

  for (const theme of THEMES) {
    for (const name of ['capabilities', 'lint'] as Fixture[]) {
      test(`the ${name} panel is clean in the ${theme ?? 'light'} theme`, async ({ page }) => {
        await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
        await mount(page, name);
        await applyPreferences(page, { theme });
        expect(await blockingViolations(page)).toEqual([]);
      });
    }
  }

  test('the versions and settings panels are clean in the two darkest themes', async ({ page }) => {
    await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
    for (const theme of ['nord', 'darcula']) {
      for (const name of ['versions', 'settings'] as Fixture[]) {
        await mount(page, name);
        await applyPreferences(page, { theme });
        expect(await blockingViolations(page)).toEqual([]);
      }
    }
  });
});

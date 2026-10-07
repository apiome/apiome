/**
 * Resolve a `<Screenshot id/>` to its images — DOCS-1.3 (#5620).
 *
 * Kept free of React and CSS so it can be unit-tested in Node. The image naming mirrors
 * `imagePath` in `scripts/lib/screens.mjs`, which writes the files; `test/screenshot.test.mjs`
 * checks the two agree.
 */

/** A manifest entry, as much of it as the component needs. */
export interface ManifestScreen {
  id: string;
  route: string;
  theme?: string[];
  viewport?: {width: number; height: number};
}

/** What the component renders for one id. */
export interface ResolvedScreenshot {
  /** The product route the screen shows, for the route badge. */
  route: string;
  /** Site-relative image paths, before the base URL is applied. */
  sources: {light: string; dark: string};
  /** The capture size, so the browser reserves the space before the image loads. */
  width: number;
  height: number;
}

/** The default capture size, as in `SCREEN_DEFAULTS`. */
const DEFAULT_VIEWPORT = {width: 1440, height: 900};

/**
 * The site-relative path of one captured image.
 *
 * @param id - Manifest id.
 * @param theme - `light` or `dark`.
 * @returns e.g. `/img/screens/catalog.dark.png`.
 */
export function screenshotImagePath(id: string, theme: 'light' | 'dark'): string {
  return `/img/screens/${id}.${theme}.png`;
}

/**
 * Look a screenshot up in the manifest.
 *
 * Throws rather than rendering a broken image, so a page that names an unknown id, an entry
 * captured in one theme only, or a screenshot without alt text fails the build.
 *
 * @param screens - `screens.json`'s `screens` array.
 * @param id - The id the page asked for.
 * @param alt - The alt text the page gave.
 * @returns The route, the light and dark image paths, and the capture size.
 * @throws Error when the id is unknown, the entry lacks a theme, or `alt` is blank.
 */
export function resolveScreenshot(screens: readonly ManifestScreen[], id: string, alt: string): ResolvedScreenshot {
  if (typeof alt !== 'string' || alt.trim() === '') {
    throw new Error(`<Screenshot id="${id}"/> needs alt text that describes the screen.`);
  }
  const screen = screens.find((candidate) => candidate.id === id);
  if (!screen) {
    throw new Error(`<Screenshot id="${id}"/>: no such id in apiome-docs/screens.json.`);
  }
  const themes = screen.theme ?? ['light', 'dark'];
  if (!themes.includes('light') || !themes.includes('dark')) {
    throw new Error(`<Screenshot id="${id}"/>: the manifest entry must be captured in light and dark.`);
  }
  const viewport = screen.viewport ?? DEFAULT_VIEWPORT;
  return {
    route: screen.route,
    sources: {light: screenshotImagePath(id, 'light'), dark: screenshotImagePath(id, 'dark')},
    width: viewport.width,
    height: viewport.height,
  };
}

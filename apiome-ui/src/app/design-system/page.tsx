import type { Metadata } from 'next';
import Link from 'next/link';

import PreferenceAxes from './PreferenceAxes';
import { HiveGallery } from './galleries/HiveGallery';
import { McpGallery } from './galleries/McpGallery';
import { SupportingGallery } from './galleries/SupportingGallery';
import {
  HIVE_GALLERY_SECTIONS,
  MCP_GALLERY_SECTION,
  PATTERN_GALLERIES,
  SUPPORTING_GALLERY_SECTIONS,
} from './galleries/sections';

/**
 * `/design-system` — the design system as a route (HIVE-10.5, #5341).
 *
 * The production counterpart of `docs/mockups/foundations/design-system.html`. Every specimen
 * is the shipped component, so the page cannot drift from the app the way a static mockup can.
 *
 * - **Hive primitives**: `HiveGallery`, the buttons-to-metrics sections that used to live at
 *   `/design-system/hive` (which now redirects here).
 * - **Supporting primitives**: `SupportingGallery`, the shipped components the mockup does not
 *   draw (catalog pills, stepper, markdown, legacy modal, toasts, skeleton shapes, live region).
 * - **MCP primitives**: `McpGallery`, the gallery that used to be the whole of
 *   `/design-system/mcp`. That route still renders it on its own page.
 * - **Patterns**: links to the three galleries that take over the page and so keep their own
 *   routes (page header, command palette, shortcut sheet).
 *
 * The switchers in the header write `data-theme` / `data-density` / `data-font-scale` onto
 * `<html>`, as the preferences pane does, so every specimen can be checked in all nine
 * themes, both densities and all six font scales.
 *
 * The route is public, like the rest of `/design-system/*`: it draws only made-up specimens
 * (no session and no tenant data), and the CI accessibility gate opens it without signing in.
 *
 * `tests/design-system-gallery.test.ts` fails CI when a `components/ui` primitive ships without
 * a specimen on this page.
 */

export const metadata: Metadata = {
  title: 'Design system · Apiome',
  description: 'Every Apiome UI primitive, drawn with the shipped components.',
};

/**
 * The page: title, preference switchers, contents, then the galleries.
 *
 * @returns The full design-system gallery.
 */
export default function DesignSystemPage() {
  return (
    <main className="mx-auto flex max-w-[75rem] flex-col gap-8 p-[var(--page-pad)]">
      <header className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-[-0.02em] text-fg">Design system</h1>
        <p className="max-w-[72ch] text-sm text-fg-muted">
          Every primitive in <code className="mono">components/ui</code>, drawn with the shipped
          component. Switch theme, density and font scale to check each one.
        </p>
        <PreferenceAxes />
        <nav aria-label="Design system contents" data-testid="design-system-contents">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {[...HIVE_GALLERY_SECTIONS, ...SUPPORTING_GALLERY_SECTIONS, MCP_GALLERY_SECTION].map(
              (section) => (
                <li key={section.id}>
                  <a className="text-accent-fg hover:underline" href={`#${section.id}`}>
                    {section.label}
                  </a>
                </li>
              )
            )}
            <li>
              <a className="text-accent-fg hover:underline" href="#patterns">
                Patterns
              </a>
            </li>
          </ul>
        </nav>
      </header>

      <section aria-labelledby="design-system-hive" className="flex flex-col gap-4">
        <h2 id="design-system-hive" className="text-2xl font-semibold text-fg">
          Hive primitives
        </h2>
        <HiveGallery />
      </section>

      <section aria-labelledby="design-system-supporting" className="flex flex-col gap-4">
        <h2 id="design-system-supporting" className="text-2xl font-semibold text-fg">
          Supporting primitives
        </h2>
        <p className="max-w-[72ch] text-sm text-fg-muted">
          Shipped components the mockup does not draw: catalog pills, the stepper, markdown,
          toasts and more.
        </p>
        <SupportingGallery />
      </section>

      <section
        id={MCP_GALLERY_SECTION.id}
        aria-labelledby="design-system-mcp"
        className="flex scroll-mt-24 flex-col gap-4"
      >
        <h2 id="design-system-mcp" className="text-2xl font-semibold text-fg">
          {MCP_GALLERY_SECTION.label}
        </h2>
        <p className="max-w-[72ch] text-sm text-fg-muted">
          The shared components every MCP catalog screen reuses. Also on its own page at{' '}
          <Link className="text-accent-fg hover:underline" href="/design-system/mcp">
            /design-system/mcp
          </Link>
          .
        </p>
        <McpGallery headingLevel={3} />
      </section>

      <section
        id="patterns"
        aria-labelledby="design-system-patterns"
        className="flex scroll-mt-24 flex-col gap-4"
      >
        <h2 id="design-system-patterns" className="text-2xl font-semibold text-fg">
          Patterns
        </h2>
        <ul className="grid gap-3 md:grid-cols-3">
          {PATTERN_GALLERIES.map((gallery) => (
            <li key={gallery.href} className="rounded-lg bg-surface p-4 shadow-sm">
              <Link className="font-medium text-accent-fg hover:underline" href={gallery.href}>
                {gallery.label}
              </Link>
              <p className="mt-1 text-sm text-fg-muted">{gallery.description}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

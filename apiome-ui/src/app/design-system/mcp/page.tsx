import type { Metadata } from 'next';
import Link from 'next/link';

import PreferenceAxes from '../PreferenceAxes';
import { McpGallery } from '../galleries/McpGallery';

/**
 * `/design-system/mcp` — the MCP primitives on their own page (V2-MCP-24.7 / MCAT-10.7).
 *
 * Since HIVE-10.5 (#5341) the same `McpGallery` is also a section of `/design-system`. This
 * route stays because the MCP screens' docs link here, and a page with only the MCP
 * primitives is quicker to review against them.
 */

export const metadata: Metadata = {
  title: 'MCP primitives · Design system · Apiome',
  description: 'The shared components every MCP catalog screen reuses.',
};

/**
 * The page: title, preference switchers and the MCP gallery.
 *
 * @returns The MCP primitives gallery.
 */
export default function McpPrimitivesPage() {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 p-[var(--page-pad)]">
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold text-fg">MCP UI primitives</h1>
        <p className="text-sm text-fg-muted">
          The shared, token-driven components every MCP catalog screen reuses. Part of the{' '}
          <Link className="text-accent-fg hover:underline" href="/design-system">
            design system
          </Link>
          .
        </p>
        <PreferenceAxes />
      </header>
      <McpGallery />
    </main>
  );
}

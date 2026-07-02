'use client';

/**
 * Shared MCP UI primitives — live showcase gallery (V2-MCP-24.7 / MCAT-10.7).
 *
 * The Storybook-equivalent for this codebase (which has no Storybook): a self-contained, data-free
 * route at `/design-system/mcp` that renders every primitive in every mockup variant. It doubles as
 * a visual smoke test for the design-system foundation and as living documentation for the screens
 * (10.1 / 10.2 / 10.4 / 10.8) that consume these primitives. Paired with `docs/MCP_UI_PRIMITIVES.md`.
 */
import * as React from 'react';
import {
  GradeGlyph,
  McpBadge,
  HealthPill,
  RecencyPill,
  FindingSeverity,
  DetailTabs,
  DetailTabsList,
  DetailTabsContent,
} from '@/app/components/ui/mcp';
// The Monaco-backed code-viewer primitives were promoted out of `ui/mcp` to the format-neutral
// `ui/code` module (MFI-28.7); the gallery documents them under those neutral names.
import { JsonViewer, JsonDiffViewer, Disclosure } from '@/app/components/ui/code';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { MCP_DETAIL_TABS } from '@/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import { Server } from 'lucide-react';

/** A labelled gallery section. */
function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h2>
      <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">{description}</p>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  );
}

const NOW = Date.parse('2026-06-27T12:00:00Z');

export default function McpPrimitivesShowcase() {
  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">MCP UI primitives</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          The shared, token-driven component library every MCP catalog screen reuses (V2-MCP-24.7).
        </p>
      </header>

      <Section
        title="GradeGlyph — glyph"
        description="The A–F + 0–100 lead signal on cards and headers. Size sm/md/lg; unscored falls back to a neutral chip."
      >
        <GradeGlyph grade="A" score={96} />
        <GradeGlyph grade="B" score={82} />
        <GradeGlyph grade="C" score={64} />
        <GradeGlyph grade="D" score={45} />
        <GradeGlyph grade="F" score={20} />
        <GradeGlyph size="sm" grade="B" score={82} />
        <GradeGlyph size="lg" grade="A" score={91} />
        <GradeGlyph />
      </Section>

      <Section
        title="GradeGlyph — gauge"
        description="The same color language as a 0–100 ring, used as the headline on the Lint & Score tab."
      >
        <GradeGlyph variant="gauge" size="md" grade="A" score={94} />
        <GradeGlyph variant="gauge" size="md" grade="C" score={61} />
        <GradeGlyph variant="gauge" size="md" grade="F" score={18} />
      </Section>

      <Section
        title="McpBadge — tones"
        description="The seven-tone badge that backs transport, visibility, auth, and capability-annotation chips."
      >
        <McpBadge tone="indigo">Private</McpBadge>
        <McpBadge tone="green">Public</McpBadge>
        <McpBadge tone="slate">streamable_http</McpBadge>
        <McpBadge tone="slate">http+sse (legacy)</McpBadge>
        <McpBadge tone="green">bearer</McpBadge>
        <McpBadge tone="violet">OAuth 2.1</McpBadge>
        <McpBadge tone="green">readOnly</McpBadge>
        <McpBadge tone="blue">idempotent</McpBadge>
        <McpBadge tone="red">destructive</McpBadge>
        <McpBadge tone="amber">openWorld</McpBadge>
      </Section>

      <Section title="HealthPill" description="Endpoint reachability distilled to a colored dot + label.">
        <HealthPill status="healthy" />
        <HealthPill status="degraded" />
        <HealthPill status="unreachable" />
        <HealthPill status="unknown" />
        <HealthPill status="healthy" dotOnly />
      </Section>

      <Section title="RecencyPill" description="The 'last discovered …' recency chip (relative span; deterministic here via nowMs).">
        <RecencyPill timestamp="2026-06-27T11:59:30Z" nowMs={NOW} />
        <RecencyPill timestamp="2026-06-27T10:00:00Z" nowMs={NOW} />
        <RecencyPill timestamp="2026-06-24T12:00:00Z" nowMs={NOW} />
        <RecencyPill timestamp={null} nowMs={NOW} />
      </Section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">JsonViewer</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The read-only, monaco-backed code block for capability schemas &amp; catalog models —
          theme-aware, foldable, with one-click copy. Format-neutral via a <code>language</code> prop
          (defaults to JSON). Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <JsonViewer
          label="Input schema"
          value={JSON.stringify(
            {
              type: 'object',
              properties: {
                query: { type: 'string', description: 'Free-text search query.' },
                limit: { type: 'integer', minimum: 1, maximum: 100, default: 10 },
              },
              required: ['query'],
            },
            null,
            2,
          )}
        />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">JsonDiffViewer</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The read-only, monaco-backed split/unified diff for two revisions of a document — auto-sizing,
          theme-aware, collapsing long unchanged regions. Format-neutral via a <code>language</code> prop.
          Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <div className="w-full">
          <JsonDiffViewer
            mode="split"
            original={JSON.stringify(
              { name: 'search', limit: 10, sort: 'relevance' },
              null,
              2,
            )}
            modified={JSON.stringify(
              { name: 'search', limit: 25, sort: 'recency', highlight: true },
              null,
              2,
            )}
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Disclosure</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          A lazy-mounting collapsible wrapper for the (heavy) code viewers: its children mount only on
          first expand, so a long list of sections doesn&apos;t pay the editors&apos; cost up front.
          Lives in <code>ui/code</code> (MFI-28.7).
        </p>
        <div className="w-full space-y-2">
          <Disclosure label="Output schema" meta="6 lines">
            <JsonViewer
              className="rounded-none border-0"
              value={JSON.stringify(
                { type: 'array', items: { $ref: '#/components/schemas/Result' } },
                null,
                2,
              )}
            />
          </Disclosure>
        </div>
      </section>

      <Section title="FindingSeverity" description="The shared MUST / SHOULD / Advisory chip for the lint tab and inline hints.">
        <FindingSeverity tier="must" />
        <FindingSeverity tier="should" />
        <FindingSeverity tier="advisory" />
        <FindingSeverity severity="error" count={3} />
        <FindingSeverity severity="warning" count={5} />
      </Section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">DetailTabs</h2>
        <p className="mb-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
          The seven-tab underline detail shell. The canonical set lives in MCP_DETAIL_TABS.
        </p>
        <DetailTabs defaultValue="overview">
          <DetailTabsList items={MCP_DETAIL_TABS} />
          {MCP_DETAIL_TABS.map((tab) => (
            <DetailTabsContent key={tab.value} value={tab.value}>
              <p className="text-sm text-gray-600 dark:text-gray-300">
                {tab.label} panel content goes here.
              </p>
            </DetailTabsContent>
          ))}
        </DetailTabs>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Empty / loading / error states</h2>
        <EmptyState
          variant="compact"
          icon={<Server className="h-8 w-8 text-white" aria-hidden />}
          title="No endpoints yet"
          description="Import an MCP server to populate your catalog."
        />
        <LoadingState message="Loading catalog…" minHeightClassName="min-h-[160px]" />
        <ErrorState
          variant="compact"
          description="Could not reach the catalog service."
          onRetry={() => undefined}
        />
      </section>
    </main>
  );
}

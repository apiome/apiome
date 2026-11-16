/**
 * `/tenant/{tenantSlug}/{projectSlug}/changelog` — the public changelog of one API (PCX-2.1, #5896).
 *
 * Server-rendered: every published public version from `version_changelogs`, newest first, one
 * section each, entries in the stored CTG-1.3 order (breaking → non-breaking → docs-only, then
 * path group). Filters are plain query parameters (`?severity=`, `?pathGroup=`, `?since=`) read on
 * the server and applied by a no-JavaScript GET form, so every filtered view is a shareable URL.
 * All shaping lives in `lib/changelog/projectChangelog.ts`, where it is unit-tested; this file
 * only renders the model.
 */

import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { ChangesNote, SeverityPill } from '../../../../components/SeverityPill';
import {
  getPublicChangelogsForProject,
  getPublicProjectBySlug,
} from '../../../../../../lib/db/helper';
import { severityLabel } from '../../../../../../lib/changelog/group';
import {
  CHANGELOG_SEVERITIES,
  buildProjectChangelog,
  changelogFilterQuery,
  parseChangelogFilters,
  sectionNote,
  type ChangelogPageSection,
  type ShownCounts,
} from '../../../../../../lib/changelog/projectChangelog';

/** Upper bound on versions read for the page (the helper's default of 50 is for feeds). */
const CHANGELOG_PAGE_VERSION_LIMIT = 500;

type PageParams = Promise<{ tenantSlug: string; projectSlug: string }>;
type PageSearchParams = Promise<Record<string, string | string[] | undefined>>;

/** Shared look of the outline buttons in the header (matches the project page's actions). */
const OUTLINE_BUTTON =
  'inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800';

/** Shared look of the filter selects. */
const FILTER_SELECT =
  'mt-1 block w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-sm text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200';

/**
 * Page title plus `<link rel="alternate">` entries for the Markdown and feed variants.
 */
export async function generateMetadata({ params }: { params: PageParams }): Promise<Metadata> {
  const { tenantSlug, projectSlug } = await params;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);
  if (!project) return {};
  const base = `/tenant/${tenantSlug}/${projectSlug}`;
  return {
    title: `${project.name} — API changelog`,
    description: `Every published version of ${project.name}, breaking changes first.`,
    alternates: {
      types: {
        'text/markdown': `${base}/changelog.md`,
        'application/rss+xml': `${base}/changelog.xml`,
        'application/feed+json': `${base}/changelog.json`,
      },
    },
  };
}

/** `2026-11-01` — a deterministic, locale-free date for SSR. */
function isoDate(iso: string): string {
  return iso.slice(0, 10);
}

/** The nonzero severity count pills of a section. */
function CountPills({ counts }: { counts: ShownCounts }) {
  return (
    <>
      {CHANGELOG_SEVERITIES.map((sev) =>
        counts[sev] > 0 ? (
          <SeverityPill key={sev} severity={sev} label={`${counts[sev]} ${severityLabel(sev)}`} />
        ) : null
      )}
    </>
  );
}

/** One version's section: heading, totals, then entries or its explicit state note. */
function VersionSection({
  section,
  filtered,
  tenantSlug,
  projectSlug,
}: {
  section: ChangelogPageSection;
  filtered: boolean;
  tenantSlug: string;
  projectSlug: string;
}) {
  const headingId = `${section.anchor}-title`;
  const note = sectionNote(section, filtered);
  const totalLabel =
    section.state !== 'ready'
      ? null
      : filtered && section.storedCounts && section.shownCounts.total !== section.storedCounts.total
        ? `${section.shownCounts.total} of ${section.storedCounts.total} changes`
        : `${section.shownCounts.total} ${section.shownCounts.total === 1 ? 'change' : 'changes'}`;

  return (
    <section id={section.anchor} aria-labelledby={headingId} className="scroll-mt-20 space-y-3">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h2 id={headingId} className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
          <Link
            href={`/tenant/${tenantSlug}/${projectSlug}/${encodeURIComponent(section.versionLabel)}`}
            className="hover:underline"
          >
            v{section.versionLabel}
          </Link>
        </h2>
        {section.baselineLabel && (
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
            since v{section.baselineLabel}
          </span>
        )}
        {section.publishedAt && (
          <time dateTime={section.publishedAt} className="text-xs text-zinc-500 dark:text-zinc-400">
            {isoDate(section.publishedAt)}
          </time>
        )}
        <CountPills counts={section.shownCounts} />
        {totalLabel && (
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            {totalLabel}
          </span>
        )}
        <a
          href={`#${section.anchor}`}
          className="text-xs text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          aria-label={`Permalink to version ${section.versionLabel}`}
        >
          #
        </a>
      </header>

      {note ? (
        <div className="space-y-2">
          <ChangesNote text={note} />
          {section.state === 'failed' && section.baselineLabel && (
            <p className="text-center text-[13px]">
              <Link
                href={`/tenant/${tenantSlug}/${projectSlug}/compare?v1=${encodeURIComponent(section.baselineLabel)}&v2=${encodeURIComponent(section.versionLabel)}`}
                className="text-[var(--brand-soft-text)] hover:underline"
              >
                Open the plain diff
              </Link>
            </p>
          )}
        </div>
      ) : (
        section.severities.map((sev) => (
          <div
            key={sev.severity}
            className="rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-950"
          >
            <h3 className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800/80">
              <SeverityPill severity={sev.severity} label={severityLabel(sev.severity)} />
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                {sev.count} {sev.count === 1 ? 'change' : 'changes'}
              </span>
            </h3>
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
              {sev.groups.map((group) => (
                <div key={group.pathGroup} className="px-4 py-3">
                  <h4 className="font-mono text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                    {group.pathGroup}
                  </h4>
                  <ul className="mt-2 space-y-1">
                    {group.entries.map(({ entry, anchor, compareHref }) => (
                      <li
                        key={anchor}
                        id={anchor}
                        className="scroll-mt-20 rounded-md p-2 target:bg-[var(--brand-soft)]"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[13px] text-zinc-700 dark:text-zinc-300">
                            {entry.summary}
                          </span>
                          {entry.unclassified && (
                            <span className="text-[11px] italic text-zinc-500 dark:text-zinc-400">
                              unclassified
                            </span>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-3">
                          <code className="truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                            {entry.pointer}
                          </code>
                          {compareHref && (
                            <Link
                              href={compareHref}
                              className="text-[11px] font-medium text-[var(--brand-soft-text)] hover:underline"
                            >
                              View in compare
                            </Link>
                          )}
                          <a
                            href={`#${anchor}`}
                            className="text-[11px] text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                            aria-label={`Permalink to this change in version ${section.versionLabel}`}
                          >
                            #
                          </a>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </section>
  );
}

export default async function ProjectChangelogPage({
  params,
  searchParams,
}: {
  params: PageParams;
  searchParams: PageSearchParams;
}) {
  const { tenantSlug, projectSlug } = await params;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);
  if (!project) {
    notFound();
  }

  const filters = parseChangelogFilters(await searchParams);
  const rows = await getPublicChangelogsForProject(
    tenantSlug,
    projectSlug,
    CHANGELOG_PAGE_VERSION_LIMIT
  );
  const model = buildProjectChangelog(rows, filters, tenantSlug, projectSlug);

  const projectHref = `/tenant/${tenantSlug}/${projectSlug}`;
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
  const markdownHref = `${basePath}${projectHref}/changelog.md${changelogFilterQuery(filters)}`;

  return (
    <AppShell containerSize="normal">
      <div className="space-y-8 py-8" data-testid="project-changelog">
        <Breadcrumb
          items={[
            { label: project.tenant_name || tenantSlug, href: `/tenant/${tenantSlug}` },
            { label: project.name, href: projectHref },
            { label: 'Changelog' },
          ]}
        />

        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              {project.name} changelog
            </h1>
            <p className="mt-1 text-[13px] text-zinc-500 dark:text-zinc-400">
              {rows.length === 0
                ? 'No published versions yet.'
                : `${rows.length} published ${rows.length === 1 ? 'version' : 'versions'}, newest first. Breaking changes are listed first in each version.`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {/* Route handlers, not pages: plain basePath-prefixed anchors. */}
            <a href={markdownHref} className={OUTLINE_BUTTON}>
              Markdown
            </a>
            <a href={`${basePath}${projectHref}/changelog.xml`} className={OUTLINE_BUTTON}>
              RSS
            </a>
            <a href={`${basePath}${projectHref}/changelog.json`} className={OUTLINE_BUTTON}>
              JSON Feed
            </a>
          </div>
        </header>

        {rows.length > 0 && (
          <form
            method="get"
            action={`${basePath}${projectHref}/changelog`}
            aria-label="Filter the changelog"
            className="grid gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end dark:border-zinc-800 dark:bg-zinc-950"
          >
            <label className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
              Severity
              <select name="severity" defaultValue={filters.severity ?? ''} className={FILTER_SELECT}>
                <option value="">All severities</option>
                {CHANGELOG_SEVERITIES.map((sev) => (
                  <option key={sev} value={sev}>
                    {severityLabel(sev)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
              Path group
              <select name="pathGroup" defaultValue={filters.pathGroup ?? ''} className={FILTER_SELECT}>
                <option value="">All path groups</option>
                {model.pathGroups.map((group) => (
                  <option key={group} value={group}>
                    {group}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
              Since version
              <select name="since" defaultValue={filters.since ?? ''} className={FILTER_SELECT}>
                <option value="">All versions</option>
                {rows.map((row) => (
                  <option key={row.versionLabel} value={row.versionLabel}>
                    v{row.versionLabel}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2">
              <button type="submit" className={OUTLINE_BUTTON}>
                Apply
              </button>
              {model.filtered && (
                <Link href={`${projectHref}/changelog`} className="text-sm text-zinc-600 hover:underline dark:text-zinc-300">
                  Clear
                </Link>
              )}
            </div>
          </form>
        )}

        {model.sinceNotFound && (
          <p role="status" className="text-[13px] text-amber-700 dark:text-amber-300">
            Version {filters.since} is not published on this API — showing every version.
          </p>
        )}

        {model.sections.length === 0 ? (
          <ChangesNote
            text={
              rows.length === 0
                ? 'No published versions yet.'
                : `No versions were published after v${filters.since}.`
            }
          />
        ) : (
          <div className="space-y-10">
            {model.sections.map((section) => (
              <VersionSection
                key={section.anchor}
                section={section}
                filtered={model.filtered}
                tenantSlug={tenantSlug}
                projectSlug={projectSlug}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

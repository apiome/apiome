'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { EntityHeader } from '../../../../components/EntityHeader';
import { SpecSidebar } from '../../../../components/SpecSidebar';
import { SpecViewer, type SpecFormat } from '../../../../components/SpecViewer';
import { PublicExportDialog } from '../../../../components/export/PublicExportDialog';
import { mockCurlCommand, sampleMockPath } from '../../../../../../lib/mock/mockUrl';
import type {
  PublicVersionChangelogRow,
  Severity,
} from '../../../../../../lib/changelog/types';
import {
  groupChangelogEntries,
  severityBadgeClasses,
  severityDotClasses,
  severityLabel,
} from '../../../../../../lib/changelog/group';
import { MockCallout } from './MockCallout';

interface Version {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published_at?: string;
  tenant_name?: string;
  project_name?: string;
  mock_enabled?: boolean;
}

interface SidebarVersion {
  id: string;
  version_id: string;
  published_at?: string;
}

type VersionTab = 'specification' | 'changes';

interface VersionClientProps {
  version: Version;
  versions: SidebarVersion[];
  /** Stored publish changelog row for this version, or null when not publicly visible (CTG-3.2). */
  changelog: PublicVersionChangelogRow | null;
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
  /** Public mock base URL for this version; null when its mock is disabled (SIM-2.3, #4444). */
  mockBaseUrl: string | null;
}

export function VersionClient({
  version,
  versions,
  changelog,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
  mockBaseUrl,
}: VersionClientProps) {
  const [spec, setSpec] = useState<unknown>(null);
  const [format, setFormat] = useState<SpecFormat>('openapi');
  const [activeAnchor, setActiveAnchor] = useState<string | undefined>(undefined);
  const [showExport, setShowExport] = useState(false);
  const [activeTab, setActiveTab] = useState<VersionTab>('specification');

  const onSpecChange = useCallback((next: unknown, nextFormat: SpecFormat) => {
    setSpec(next);
    setFormat(nextFormat);
  }, []);

  const onSelectAnchor = useCallback((anchorId: string) => {
    setActiveAnchor(anchorId);
    const el = document.getElementById(anchorId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      history.replaceState(null, '', `#${anchorId}`);
    }
  }, []);

  const sidebar = (
    <SpecSidebar
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      versionSlug={versionSlug}
      versions={versions}
      spec={spec}
      format={format}
      activeAnchorId={activeAnchor}
      onSelectAnchor={onSelectAnchor}
    />
  );

  const changeCount =
    changelog?.status === 'ready' ? changelog.changelog?.counts?.total : undefined;

  const tabs: { value: VersionTab; label: string; count?: number }[] = [
    { value: 'specification', label: 'Specification' },
    { value: 'changes', label: 'Changes', count: changeCount },
  ];

  return (
    <AppShell containerSize="wide" sidebar={sidebar}>
      <div className="space-y-6 py-8">
        <Breadcrumb
          items={[
            { label: version.tenant_name || tenantSlug, href: `/tenant/${tenantSlug}` },
            { label: version.project_name || projectSlug, href: `/tenant/${tenantSlug}/${projectSlug}` },
            { label: `v${version.version_id}` },
          ]}
        />

        <EntityHeader
          variant="version"
          title={`Version ${version.version_id}`}
          subtitle={`/${tenantSlug}/${projectSlug}/${version.version_id}`}
          description={version.description}
          monogram={`v${(version.version_id.split('.')[0] || '0').slice(0, 2)}`}
          badges={
            <>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                Published
              </span>
              {mockBaseUrl && (
                <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-500"></span>
                  Mock available
                </span>
              )}
              {changelog?.maxSeverity && (
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${severityBadgeClasses(changelog.maxSeverity)}`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${severityDotClasses(changelog.maxSeverity)}`}
                  ></span>
                  {severityLabel(changelog.maxSeverity)} changes
                </span>
              )}
            </>
          }
          meta={[
            { label: 'Project', value: version.project_name ?? projectSlug },
            { label: 'Organization', value: version.tenant_name ?? tenantSlug },
            {
              label: 'Published',
              value: version.published_at
                ? new Date(version.published_at).toLocaleDateString()
                : '—',
            },
            { label: 'Format', value: 'OpenAPI / Arazzo / JSON Schema' },
          ]}
        />

        {mockBaseUrl && (
          <MockCallout
            mockBaseUrl={mockBaseUrl}
            curlCommand={mockCurlCommand(
              mockBaseUrl,
              format === 'openapi' ? sampleMockPath(spec) : '/'
            )}
          />
        )}

        <div className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
          {tabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              data-testid={`version-tab-${tab.value}`}
              onClick={() => setActiveTab(tab.value)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                activeTab === tab.value
                  ? 'border-[var(--brand)] text-[var(--brand)]'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span className="ml-1.5 rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {activeTab === 'specification' && (
          <>
            {version.change_log && (
              <section className="rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
                <header className="border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800/80">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    Changelog
                  </h2>
                </header>
                <div className="p-4">
                  <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-zinc-700 dark:text-zinc-300">
                    {version.change_log}
                  </p>
                </div>
              </section>
            )}

            <section className="space-y-3">
              <header className="flex items-end justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                    Specification
                  </h2>
                  <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
                    Browse the structured overview or view the raw document.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowExport(true)}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                  </svg>
                  Export to another format…
                </button>
              </header>
              <SpecViewer
                tenantSlug={tenantSlug}
                projectSlug={projectSlug}
                versionSlug={versionSlug}
                restApiBaseUrl={restApiBaseUrl}
                mockBaseUrl={mockBaseUrl}
                onSpecChange={onSpecChange}
              />
            </section>
          </>
        )}

        {activeTab === 'changes' && (
          <ChangesPanel
            changelog={changelog}
            tenantSlug={tenantSlug}
            projectSlug={projectSlug}
          />
        )}
      </div>

      <PublicExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        tenantSlug={tenantSlug}
        projectSlug={projectSlug}
        versionSlug={versionSlug}
        restApiBaseUrl={restApiBaseUrl}
      />
    </AppShell>
  );
}

/** Small severity pill (dot + label), the same rounded-full style as the header badges. */
function SeverityPill({ severity, label }: { severity: Severity | string; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${severityBadgeClasses(severity)}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${severityDotClasses(severity)}`}></span>
      {label}
    </span>
  );
}

/** Dashed empty-state note used for the pending / initial / failed changelog states. */
function ChangesNote({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-zinc-300 bg-white/40 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">{text}</p>
    </div>
  );
}

/**
 * The Changes tab: the stored `ctg.changelog.v1` payload rendered as severity count badges, a
 * `fromVersion → toVersion` line, and grouped entries (severity section → pathGroup → entry).
 * All grouping/labeling logic lives in `lib/changelog` where it is unit-tested.
 */
function ChangesPanel({
  changelog,
  tenantSlug,
  projectSlug,
}: {
  changelog: PublicVersionChangelogRow | null;
  tenantSlug: string;
  projectSlug: string;
}) {
  if (!changelog || changelog.status === null) {
    return <ChangesNote text="Changelog not available yet." />;
  }
  if (changelog.status === 'failed') {
    return <ChangesNote text="Classification failed for this version." />;
  }
  if (changelog.status === 'initial') {
    return <ChangesNote text="Initial publication — no prior baseline to compare against." />;
  }
  const payload = changelog.changelog;
  if (!payload) {
    return <ChangesNote text="Changelog not available yet." />;
  }

  const severities: Severity[] = ['breaking', 'non-breaking', 'docs-only'];
  const counts = payload.counts;
  const sections = groupChangelogEntries(payload.entries ?? []);
  const fromLabel = payload.fromVersion ?? changelog.baselineVersionLabel;
  const toLabel = payload.toVersion ?? changelog.versionLabel;

  /** Compare deep-link for one entry; null when there is no baseline to diff against. */
  const compareHref = (pointer: string): string | null =>
    changelog.baselineVersionLabel
      ? `/tenant/${tenantSlug}/${projectSlug}/compare?v1=${encodeURIComponent(changelog.baselineVersionLabel)}&v2=${encodeURIComponent(changelog.versionLabel)}&focus=${encodeURIComponent(pointer)}`
      : null;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {counts &&
          severities.map(
            (sev) =>
              (counts[sev] ?? 0) > 0 && (
                <SeverityPill
                  key={sev}
                  severity={sev}
                  label={`${counts[sev]} ${severityLabel(sev)}`}
                />
              )
          )}
        <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
          {fromLabel ? `v${fromLabel} → ` : ''}v{toLabel}
        </span>
      </div>

      {sections.length === 0 ? (
        <ChangesNote text="No changes detected." />
      ) : (
        sections.map((section) => (
          <section
            key={section.severity}
            className="rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-950"
          >
            <header className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800/80">
              <SeverityPill
                severity={section.severity}
                label={`${severityLabel(section.severity)}`}
              />
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                {section.count} {section.count === 1 ? 'change' : 'changes'}
              </span>
            </header>
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
              {section.groups.map((group) => (
                <div key={group.pathGroup} className="px-4 py-3">
                  <h3 className="font-mono text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                    {group.pathGroup}
                  </h3>
                  <ul className="mt-2 space-y-2">
                    {group.entries.map((entry, i) => {
                      const href = compareHref(entry.pointer);
                      const body = (
                        <>
                          <div className="flex flex-wrap items-center gap-2">
                            <SeverityPill
                              severity={entry.severity}
                              label={severityLabel(entry.severity)}
                            />
                            <span className="text-[13px] text-zinc-700 dark:text-zinc-300">
                              {entry.summary}
                            </span>
                          </div>
                          <code className="mt-1 block truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                            {entry.pointer}
                          </code>
                        </>
                      );
                      return (
                        <li key={`${entry.pointer}-${i}`}>
                          {href ? (
                            <Link
                              href={href}
                              className="block rounded-md border border-transparent p-2 transition-colors hover:border-zinc-200 hover:bg-zinc-50 dark:hover:border-zinc-800 dark:hover:bg-zinc-900"
                              title="View in compare"
                            >
                              {body}
                            </Link>
                          ) : (
                            <div className="p-2">{body}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </section>
  );
}

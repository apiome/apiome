'use client';

import { useState, useCallback } from 'react';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { EntityHeader } from '../../../../components/EntityHeader';
import { SpecSidebar } from '../../../../components/SpecSidebar';
import { SpecViewer, type SpecFormat } from '../../../../components/SpecViewer';
import { PublicExportDialog } from '../../../../components/export/PublicExportDialog';

interface Version {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published_at?: string;
  tenant_name?: string;
  project_name?: string;
}

interface SidebarVersion {
  id: string;
  version_id: string;
  published_at?: string;
}

interface VersionClientProps {
  version: Version;
  versions: SidebarVersion[];
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
}

export function VersionClient({
  version,
  versions,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
}: VersionClientProps) {
  const [spec, setSpec] = useState<unknown>(null);
  const [format, setFormat] = useState<SpecFormat>('openapi');
  const [activeAnchor, setActiveAnchor] = useState<string | undefined>(undefined);
  const [showExport, setShowExport] = useState(false);

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
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
              Published
            </span>
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
            onSpecChange={onSpecChange}
          />
        </section>
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

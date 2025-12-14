'use client';

import Link from 'next/link';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { SpecViewer } from '../../../../components/SpecViewer';

interface Version {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published_at?: string;
  tenant_name?: string;
  project_name?: string;
}

export function VersionClient({
  version,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
}: {
  version: Version;
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
}) {
  return (
    <div className="py-8">
      <div className="container mx-auto px-4">
        {/* Breadcrumb */}
        <div className="mb-6">
          <Breadcrumb
            items={[
              { label: version.tenant_name || tenantSlug, href: `/tenant/${tenantSlug}` },
              { label: version.project_name || projectSlug, href: `/tenant/${tenantSlug}/${projectSlug}` },
              { label: `v${version.version_id}` },
            ]}
          />
        </div>

        {/* Page Header */}
        <div className="mb-8">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-green-500 to-green-600 text-white text-xl font-bold shadow-lg">
                v{versionSlug.split('.')[0]}
              </div>
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                    Version {version.version_id}
                  </h1>
                  <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span>
                    Published
                  </span>
                </div>
                {version.description && (
                  <p className="mt-1 text-zinc-600 dark:text-zinc-400">
                    {version.description}
                  </p>
                )}
                <div className="mt-2 flex items-center gap-4 text-sm text-zinc-500">
                  {version.published_at && (
                    <span className="flex items-center gap-1">
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      Published {new Date(version.published_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href={`/tenant/${tenantSlug}/${projectSlug}`}
                className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                All Versions
              </Link>
            </div>
          </div>
        </div>

        {/* Changelog */}
        {version.change_log && (
          <div className="mb-8 rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h2 className="font-semibold text-zinc-900 dark:text-zinc-50">Changelog</h2>
            </div>
            <div className="p-4">
              <p className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap">
                {version.change_log}
              </p>
            </div>
          </div>
        )}

        {/* Specification Viewer */}
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 mb-4">
            API Specification
          </h2>
          <SpecViewer
            tenantSlug={tenantSlug}
            projectSlug={projectSlug}
            versionSlug={versionSlug}
            restApiBaseUrl={restApiBaseUrl}
          />
        </div>
      </div>
    </div>
  );
}


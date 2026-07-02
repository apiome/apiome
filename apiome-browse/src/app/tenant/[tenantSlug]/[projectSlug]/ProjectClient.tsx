'use client';

import Link from 'next/link';
import { useState } from 'react';
import { AppShell } from '../../../components/AppShell';
import { Breadcrumb } from '../../../components/Breadcrumb';
import { EntityHeader } from '../../../components/EntityHeader';
import { VersionTimeline } from '../../../components/VersionTimeline';

interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  tenant_name?: string;
  created_at?: string;
}

interface Version {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published: boolean;
  published_at?: string;
  created_at?: string;
}

interface ProjectClientProps {
  project: Project;
  versions: Version[];
  tenantSlug: string;
  projectSlug: string;
}

function relativeTime(iso?: string): string | undefined {
  if (!iso) return undefined;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return undefined;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}

export function ProjectClient({
  project,
  versions,
  tenantSlug,
  projectSlug,
}: ProjectClientProps) {
  const latest = versions[0];
  const [copied, setCopied] = useState(false);

  const onCopyShareUrl = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore clipboard failures */
    }
  };

  return (
    <AppShell containerSize="wide">
      <div className="space-y-8 py-8">
        <Breadcrumb
          items={[
            {
              label: project.tenant_name || tenantSlug,
              href: `/tenant/${tenantSlug}`,
            },
            { label: project.name },
          ]}
        />

        <EntityHeader
          variant="project"
          title={project.name}
          subtitle={`/${tenantSlug}/${project.slug}`}
          description={project.description}
          badges={
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
              Public
            </span>
          }
          meta={[
            { label: 'Versions', value: versions.length },
            {
              label: 'Latest version',
              value: latest ? `v${latest.version_id}` : '—',
            },
            {
              label: 'Last updated',
              value: relativeTime(latest?.published_at) ?? '—',
            },
            {
              label: 'Organization',
              value: (
                <Link
                  href={`/tenant/${tenantSlug}`}
                  className="text-[var(--brand-soft-text)] hover:underline"
                >
                  {project.tenant_name || tenantSlug}
                </Link>
              ),
            },
          ]}
          actions={
            <>
              {latest && (
                <Link
                  href={`/tenant/${tenantSlug}/${projectSlug}/${latest.version_id}`}
                  className="inline-flex items-center gap-1.5 rounded-md bg-[var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-[var(--brand-hover)]"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                  View latest
                </Link>
              )}
              {versions.length > 1 && (
                <Link
                  href={`/tenant/${tenantSlug}/${projectSlug}/compare`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                  </svg>
                  Compare
                </Link>
              )}
              <button
                type="button"
                onClick={onCopyShareUrl}
                className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                aria-label="Copy share URL"
              >
                {copied ? (
                  <>
                    <svg className="h-4 w-4 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    Copied
                  </>
                ) : (
                  <>
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    </svg>
                    Share
                  </>
                )}
              </button>
            </>
          }
        />

        <section className="space-y-4">
          <header className="flex items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                Version history
              </h2>
              <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
                {versions.length === 0
                  ? 'No published versions yet.'
                  : `${versions.length} published ${versions.length === 1 ? 'version' : 'versions'}, newest first.`}
              </p>
            </div>
          </header>

          <VersionTimeline
            versions={versions}
            tenantSlug={tenantSlug}
            projectSlug={projectSlug}
            latestVersionId={latest?.version_id}
            searchable={versions.length > 5}
          />
        </section>
      </div>
    </AppShell>
  );
}

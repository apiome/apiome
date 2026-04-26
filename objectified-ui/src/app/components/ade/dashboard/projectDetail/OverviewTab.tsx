'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import {
  Calendar,
  ExternalLink,
  FileText,
  Gauge,
  Info,
  Mail,
  Scale,
  Tag,
  TrendingUp,
  User,
} from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';
import { ProjectQualityTrendSparkline } from '../ProjectQualityTrendSparkline';
import {
  getProjectQualityHistory,
  type ProjectQualitySnapshot,
} from '../../../../utils/project-quality-score-history';
import {
  getNumericScoreTier,
  letterGradeFromOverallPercent,
} from '../../../../utils/numeric-score-tier';
import { getProjectDomainCategory } from '../../../../utils/project-domain-categories';
import type { Project } from '../projectTypes';

export interface OverviewTabProps {
  project: Project;
}

function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return Math.round((sorted[mid - 1] + sorted[mid]) / 2);
  }
  return sorted[mid];
}

interface QualitySummary {
  history: ProjectQualitySnapshot[];
  latest: number | null;
  best: number | null;
  worst: number | null;
  median: number | null;
  delta: number | null;
}

function summarise(history: ProjectQualitySnapshot[]): QualitySummary {
  if (history.length === 0) {
    return { history, latest: null, best: null, worst: null, median: null, delta: null };
  }
  const overalls = history.map((h) => h.overall);
  const latest = overalls[overalls.length - 1];
  const previous = overalls.length > 1 ? overalls[overalls.length - 2] : null;
  return {
    history,
    latest,
    best: Math.max(...overalls),
    worst: Math.min(...overalls),
    median: median(overalls),
    delta: previous == null ? null : latest - previous,
  };
}

export function OverviewTab({ project }: OverviewTabProps) {
  const summary = useMemo(() => summarise(getProjectQualityHistory(project.id)), [project.id]);

  const tier = summary.latest != null ? getNumericScoreTier(summary.latest) : null;
  const letter = summary.latest != null ? letterGradeFromOverallPercent(summary.latest) : null;

  const domain = getProjectDomainCategory(project.metadata?.domainCategory);
  const license = project.metadata?.license;
  const contact = project.metadata?.contact;

  const tierBorderClass = tier
    ? `${tier.gaugeStrokeClass.replace('text-', 'border-')} ${tier.textClass}`
    : 'border-gray-300 dark:border-gray-600 text-gray-500';

  const deltaTone =
    summary.delta == null
      ? ''
      : summary.delta > 0
        ? 'text-emerald-600 dark:text-emerald-400'
        : summary.delta < 0
          ? 'text-rose-500 dark:text-rose-400'
          : 'text-gray-500';

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <section className={projectPanelClass}>
          <div className={`${projectPanelHeaderClass} flex items-center justify-between`}>
            <div className="flex items-center gap-3">
              <Info className="w-5 h-5 text-indigo-500" />
              <div>
                <h3 className="text-base font-semibold">About</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Description &amp; OpenAPI metadata
                </p>
              </div>
            </div>
            <Link
              href={`/ade/dashboard/projects/${project.id}?tab=settings`}
              className="text-xs text-indigo-500 hover:underline"
            >
              Edit →
            </Link>
          </div>
          <div className="p-5 space-y-4">
            <div>
              <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-line">
                {project.description?.trim() || (
                  <span className="italic text-gray-400">
                    No description yet — add one in Settings.
                  </span>
                )}
              </p>
              {project.metadata?.summary ? (
                <p className="text-xs text-gray-500 mt-3 italic">{project.metadata.summary}</p>
              ) : null}
            </div>

            <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3 pt-4 border-t border-gray-100 dark:border-gray-700">
              <MetaItem icon={<Tag className="w-3.5 h-3.5" />} label="Domain category">
                {domain ? (
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300">
                    {domain.label}
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </MetaItem>
              <MetaItem icon={<FileText className="w-3.5 h-3.5" />} label="Slug">
                <span className="font-mono">{project.slug || '—'}</span>
              </MetaItem>
              <MetaItem icon={<User className="w-3.5 h-3.5" />} label="Created by">
                <span>{project.creator_name || '—'}</span>
                {project.creator_email ? (
                  <span className="text-xs text-gray-500"> · {project.creator_email}</span>
                ) : null}
              </MetaItem>
              <MetaItem icon={<Calendar className="w-3.5 h-3.5" />} label="Created">
                {formatDate(project.created_at)}
              </MetaItem>
              <MetaItem icon={<Calendar className="w-3.5 h-3.5" />} label="Last updated">
                {formatDate(project.updated_at)}
              </MetaItem>
              <MetaItem icon={<Scale className="w-3.5 h-3.5" />} label="License">
                {license?.name || license?.identifier ? (
                  <span className="inline-flex items-center gap-1">
                    {license.name || license.identifier}
                    {license.url ? (
                      <a
                        href={license.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-500 hover:underline inline-flex items-center"
                        aria-label="Open license URL"
                      >
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : null}
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </MetaItem>
              <MetaItem icon={<Mail className="w-3.5 h-3.5" />} label="Contact">
                {contact?.name || contact?.email || contact?.url ? (
                  <span className="inline-flex flex-wrap items-baseline gap-1">
                    {contact?.name ? <span>{contact.name}</span> : null}
                    {contact?.email ? (
                      <a
                        href={`mailto:${contact.email}`}
                        className="text-indigo-500 hover:underline font-mono text-xs"
                      >
                        {contact.email}
                      </a>
                    ) : null}
                    {contact?.url ? (
                      <a
                        href={contact.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-500 hover:underline font-mono text-xs inline-flex items-center gap-1"
                      >
                        {contact.url}
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : null}
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </MetaItem>
              <MetaItem icon={<FileText className="w-3.5 h-3.5" />} label="Terms of service">
                {project.metadata?.termsOfService ? (
                  <a
                    href={project.metadata.termsOfService}
                    target="_blank"
                    rel="noreferrer"
                    className="text-indigo-500 hover:underline font-mono text-xs"
                  >
                    {project.metadata.termsOfService}
                  </a>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </MetaItem>
            </dl>
          </div>
        </section>

        <section className={projectPanelClass}>
          <div className={projectPanelHeaderClass}>
            <div className="flex items-center gap-3">
              <Gauge className="w-5 h-5 text-indigo-500" />
              <div>
                <h3 className="text-base font-semibold">Quality history</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Per-import scores recorded locally
                </p>
              </div>
            </div>
          </div>
          <div className="p-5">
            {summary.history.length === 0 ? (
              <p className="text-sm text-gray-500 italic">
                No quality runs recorded yet. Importing or scoring an OpenAPI spec writes a
                snapshot here.
              </p>
            ) : (
              <>
                <div className="flex items-center gap-4">
                  <div
                    className={`inline-flex items-center justify-center w-16 h-16 rounded-full border-[3px] font-mono font-bold text-lg ${tierBorderClass}`}
                  >
                    {summary.latest}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs text-gray-500">latest score</span>
                      {summary.delta != null ? (
                        <span className={`text-xs font-mono inline-flex items-center gap-1 ${deltaTone}`}>
                          <TrendingUp className="w-3 h-3" />
                          {summary.delta > 0 ? '+' : ''}
                          {summary.delta} vs prior
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">
                      tier: <span className="font-medium text-gray-700 dark:text-gray-200">{tier?.shortLabel ?? '—'}</span>
                      {letter ? <span className="ml-2 font-mono">{letter}</span> : null}
                    </p>
                    <p className="text-[11px] text-gray-500 mt-1 font-mono">
                      {summary.history.length} snapshot{summary.history.length === 1 ? '' : 's'}
                    </p>
                  </div>
                  <div className="w-40 shrink-0">
                    <ProjectQualityTrendSparkline history={summary.history} className="h-12 w-full" />
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-3 text-center text-xs">
                  <SummaryStat label="Median" value={summary.median} />
                  <SummaryStat label="Best" value={summary.best} tone="positive" />
                  <SummaryStat label="Worst" value={summary.worst} tone="warning" />
                </div>
              </>
            )}
          </div>
        </section>
      </div>

      <div className="space-y-6">
        <section className={projectPanelClass}>
          <div className={projectPanelHeaderClass}>
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-indigo-500" />
              <h3 className="text-base font-semibold">Identifiers</h3>
            </div>
          </div>
          <dl className="p-5 space-y-3 text-xs">
            <IdRow label="Project id" value={project.id} mono />
            <IdRow label="Tenant id" value={project.tenant_id} mono />
            <IdRow label="Creator id" value={project.creator_id} mono />
          </dl>
        </section>
      </div>
    </div>
  );
}

interface MetaItemProps {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}

function MetaItem({ label, icon, children }: MetaItemProps) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold inline-flex items-center gap-1">
        {icon}
        {label}
      </dt>
      <dd className="mt-1 text-sm text-gray-700 dark:text-gray-200">{children}</dd>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone?: 'positive' | 'warning';
}) {
  const valueClass =
    tone === 'positive'
      ? 'text-emerald-500'
      : tone === 'warning'
        ? 'text-amber-500'
        : 'text-gray-700 dark:text-gray-200';
  return (
    <div>
      <p className="text-gray-500">{label}</p>
      <p className={`font-mono font-semibold mt-0.5 ${valueClass}`}>{value ?? '—'}</p>
    </div>
  );
}

function IdRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold shrink-0 pt-0.5">
        {label}
      </dt>
      <dd className={`text-right break-all ${mono ? 'font-mono text-[11px]' : ''}`}>{value}</dd>
    </div>
  );
}

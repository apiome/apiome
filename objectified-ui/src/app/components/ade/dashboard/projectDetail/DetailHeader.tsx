'use client';

import Link from 'next/link';
import { ArrowLeft, Copy } from 'lucide-react';
import { useState } from 'react';
import {
  projectAvatarGradientClasses,
  projectHeaderShellClass,
} from '../dashboardScreenClasses';
import {
  ProjectStatusChip,
  type ProjectStatusKind,
} from '../ProjectStatusChip';
import { getProjectDomainCategory } from '../../../../utils/project-domain-categories';
import type { Project } from '../projectTypes';

function avatarInitials(name: string): string {
  const cleaned = name.trim();
  if (!cleaned) return '··';
  const words = cleaned.split(/[\s_\-/]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const compact = cleaned.replace(/[^a-zA-Z0-9]/g, '');
  return (compact.slice(0, 2) || '··').toUpperCase();
}

function avatarGradient(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return projectAvatarGradientClasses[hash % projectAvatarGradientClasses.length];
}

export interface DetailHeaderProps {
  project: Project;
  /**
   * Optional secondary action(s) shown to the right of the title row. The
   * detail page supplies the "Edit" / overflow buttons; passing them through
   * keeps this header dumb about page-level state.
   */
  actions?: React.ReactNode;
  /**
   * Optional sub-nav rendered below the title row. Always the
   * {@link DetailTabs} component in practice — accepted as `children` so this
   * component doesn't need to know about tab counts.
   */
  children?: React.ReactNode;
}

export function DetailHeader({ project, actions, children }: DetailHeaderProps) {
  const [copied, setCopied] = useState(false);

  const statusKind: ProjectStatusKind = project.deleted_at
    ? 'deleted'
    : project.enabled
      ? 'enabled'
      : 'disabled';

  const domain = getProjectDomainCategory(project.metadata?.domainCategory);
  const license = project.metadata?.license;
  const licenseLabel = license?.name || license?.identifier;

  async function copyId() {
    try {
      await navigator.clipboard.writeText(project.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard unavailable — silent failure is fine here.
    }
  }

  return (
    <header className={projectHeaderShellClass}>
      <div className="px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-4 min-w-0">
            <div
              className={`w-14 h-14 rounded-xl bg-gradient-to-br ${avatarGradient(project.id)} flex items-center justify-center text-white font-bold font-mono text-xl shadow-md shrink-0`}
            >
              {avatarInitials(project.name)}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <Link
                  href="/ade/dashboard/projects"
                  className="text-xs text-gray-500 hover:text-indigo-500 inline-flex items-center gap-1"
                >
                  <ArrowLeft className="w-3 h-3" /> All projects
                </Link>
                <span className="text-gray-300 dark:text-gray-600">·</span>
                <span className="text-[11px] font-mono text-gray-500 truncate max-w-[24rem]">
                  {project.id}
                </span>
                <button
                  type="button"
                  onClick={copyId}
                  className="text-gray-400 hover:text-indigo-500"
                  title={copied ? 'Copied!' : 'Copy project id'}
                  aria-label="Copy project id"
                >
                  <Copy className="w-3 h-3" />
                </button>
                {copied ? (
                  <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                    copied
                  </span>
                ) : null}
              </div>
              <h2 className="text-2xl font-bold leading-tight mt-1">{project.name}</h2>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <ProjectStatusChip kind={statusKind} />
                {domain ? (
                  <ProjectStatusChip kind="domain" label={domain.label} showDot={false} />
                ) : null}
                {licenseLabel ? (
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                    {licenseLabel}
                  </span>
                ) : null}
                {project.slug ? (
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 font-mono">
                    {project.slug}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
          {actions ? <div className="flex items-center gap-2 shrink-0">{actions}</div> : null}
        </div>

        {children ? <div className="mt-4 -mb-px">{children}</div> : null}
      </div>
    </header>
  );
}

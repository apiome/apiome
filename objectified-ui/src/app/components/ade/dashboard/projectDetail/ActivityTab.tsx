'use client';

import {
  Activity,
  Bell,
  FileText,
  Filter,
  GitCommit,
  ShieldCheck,
  Sparkles,
  UserCog,
} from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';

export interface ActivityTabProps {
  /** Reserved for future per-project audit log queries. */
  projectId?: string;
}

interface FacetPreview {
  Icon: typeof GitCommit;
  label: string;
  description: string;
}

const FACET_PREVIEWS: FacetPreview[] = [
  {
    Icon: GitCommit,
    label: 'Schema commits',
    description: 'Every revision, branch and tag, with diffs.',
  },
  {
    Icon: UserCog,
    label: 'Membership changes',
    description: 'Invites, role updates, ownership transfers.',
  },
  {
    Icon: ShieldCheck,
    label: 'Security events',
    description: 'Token rotations, sign-ins, scope changes.',
  },
  {
    Icon: FileText,
    label: 'Spec exports',
    description: 'Who downloaded which spec and when.',
  },
  {
    Icon: Bell,
    label: 'Notifications',
    description: 'What was sent, to whom, and the delivery status.',
  },
  {
    Icon: Filter,
    label: 'Saved filters',
    description: 'Pin frequent queries (e.g. “PII changes this quarter”).',
  },
];

export function ActivityTab() {
  return (
    <div className="space-y-6">
      <section className={projectPanelClass}>
        <div className={projectPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <Activity className="w-5 h-5 text-indigo-500" />
            <div>
              <h3 className="text-base font-semibold">Project activity</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Audit log across schema, membership, security and exports
              </p>
            </div>
          </div>
        </div>
        <div className="p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-500 mb-4">
            <Sparkles className="w-6 h-6" />
          </div>
          <h4 className="text-lg font-semibold">Audit log is coming soon</h4>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 max-w-md mx-auto">
            We&rsquo;re building a unified, queryable activity stream so you can audit who did
            what, when, and from where. No mock data here on purpose &mdash; the real
            stream will appear the moment it ships.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-gray-100 dark:bg-gray-700/60 border-t border-gray-100 dark:border-gray-700/60">
          {FACET_PREVIEWS.map(({ Icon, label, description }) => (
            <div
              key={label}
              className="bg-white dark:bg-gray-800 p-4 flex items-start gap-3"
            >
              <div className="p-2 rounded-md bg-indigo-50 dark:bg-indigo-900/30 text-indigo-500 shrink-0">
                <Icon className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold">{label}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

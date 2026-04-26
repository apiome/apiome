'use client';

import {
  CalendarClock,
  CheckCircle2,
  Cloud,
  FileCode,
  Globe2,
  Package,
  Sparkles,
} from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';

export interface PublishedTabProps {
  /** Reserved for future per-project channel listings. */
  projectId?: string;
}

interface ChannelPreview {
  Icon: typeof Globe2;
  label: string;
  description: string;
}

const CHANNEL_PREVIEWS: ChannelPreview[] = [
  {
    Icon: Globe2,
    label: 'Public docs site',
    description: 'Render the OpenAPI spec at a project subdomain.',
  },
  {
    Icon: Package,
    label: 'Package registries',
    description: 'Publish typed clients to npm, PyPI, NuGet, Maven.',
  },
  {
    Icon: Cloud,
    label: 'Spec mirrors',
    description: 'Mirror the OpenAPI spec into S3 / object storage.',
  },
  {
    Icon: FileCode,
    label: 'Embeddable widgets',
    description: 'Drop a “Try it” console into your existing site.',
  },
];

const ROADMAP: Array<{ status: 'design' | 'planned'; label: string }> = [
  { status: 'design', label: 'Public docs site (Q3)' },
  { status: 'planned', label: 'npm / PyPI client publishing' },
  { status: 'planned', label: 'Per-channel access controls' },
  { status: 'planned', label: 'Spec deprecation & sunset notices' },
];

export function PublishedTab() {
  return (
    <div className="space-y-6">
      <section className={projectPanelClass}>
        <div className={projectPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <Globe2 className="w-5 h-5 text-indigo-500" />
            <div>
              <h3 className="text-base font-semibold">Publishing channels</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Where this project will be exposed to consumers
              </p>
            </div>
          </div>
        </div>
        <div className="p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-500 mb-4">
            <Sparkles className="w-6 h-6" />
          </div>
          <h4 className="text-lg font-semibold">Publishing is coming soon</h4>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 max-w-md mx-auto">
            We&rsquo;re wiring up the pipeline that will turn each tagged version into a
            published artifact. No mock data here on purpose &mdash; you&rsquo;ll see real
            channels the moment they ship.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-gray-100 dark:bg-gray-700/60 border-t border-gray-100 dark:border-gray-700/60">
          {CHANNEL_PREVIEWS.map(({ Icon, label, description }) => (
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
              <span className="ml-auto text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 shrink-0">
                Soon
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className={projectPanelClass}>
        <div className={projectPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <CalendarClock className="w-5 h-5 text-indigo-500" />
            <div>
              <h3 className="text-base font-semibold">Roadmap</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                What&rsquo;s shipping next on the publishing track
              </p>
            </div>
          </div>
        </div>
        <ul className="divide-y divide-gray-100 dark:divide-gray-700/60 text-sm">
          {ROADMAP.map(({ status, label }) => (
            <li key={label} className="px-5 py-3 flex items-center gap-3">
              <CheckCircle2
                className={`w-4 h-4 shrink-0 ${
                  status === 'design' ? 'text-indigo-500' : 'text-gray-300 dark:text-gray-600'
                }`}
              />
              <span className="flex-1">{label}</span>
              <span
                className={`text-[10px] uppercase font-semibold px-2 py-0.5 rounded ${
                  status === 'design'
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300'
                    : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                }`}
              >
                {status === 'design' ? 'In design' : 'Planned'}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

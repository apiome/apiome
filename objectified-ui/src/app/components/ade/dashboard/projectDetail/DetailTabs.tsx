'use client';

import Link from 'next/link';
import {
  Activity,
  Boxes,
  Code,
  GitBranch,
  Globe2,
  LayoutDashboard,
  Settings2,
} from 'lucide-react';
import type { ComponentType, SVGProps } from 'react';

export type ProjectDetailTab =
  | 'overview'
  | 'versions'
  | 'classes'
  | 'properties'
  | 'published'
  | 'activity'
  | 'settings';

export const PROJECT_DETAIL_TABS: ProjectDetailTab[] = [
  'overview',
  'versions',
  'classes',
  'properties',
  'published',
  'activity',
  'settings',
];

interface TabDef {
  id: ProjectDetailTab;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
}

const TABS: TabDef[] = [
  { id: 'overview', label: 'Overview', Icon: LayoutDashboard },
  { id: 'versions', label: 'Versions', Icon: GitBranch },
  { id: 'classes', label: 'Classes', Icon: Boxes },
  { id: 'properties', label: 'Properties', Icon: Code },
  { id: 'published', label: 'Published', Icon: Globe2 },
  { id: 'activity', label: 'Activity', Icon: Activity },
  { id: 'settings', label: 'Settings', Icon: Settings2 },
];

export interface DetailTabsProps {
  projectId: string;
  active: ProjectDetailTab;
  /** Optional per-tab counts. Tabs without a count omit the badge entirely
   *  rather than showing a placeholder. */
  counts?: Partial<Record<ProjectDetailTab, number | null>>;
}

export function DetailTabs({ projectId, active, counts }: DetailTabsProps) {
  return (
    <nav className="flex items-center gap-1 overflow-x-auto" aria-label="Project sections">
      {TABS.map(({ id, label, Icon }) => {
        const isActive = id === active;
        const count = counts?.[id];
        return (
          <Link
            key={id}
            href={
              id === 'overview'
                ? `/ade/dashboard/projects/${projectId}`
                : `/ade/dashboard/projects/${projectId}?tab=${id}`
            }
            className={`px-3 py-2 text-sm border-b-2 inline-flex items-center gap-2 whitespace-nowrap ${
              isActive
                ? 'font-semibold border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'font-medium border-transparent text-gray-500 hover:text-indigo-500'
            }`}
            aria-current={isActive ? 'page' : undefined}
          >
            <Icon className="w-4 h-4" />
            {label}
            {count != null ? (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500">
                {count}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

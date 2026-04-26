// SideNav.tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import React from 'react';
import { useSession } from 'next-auth/react';
import { User, Building2, Folders, Key, Eye, Link as LinkIcon, Database, Sun, GitBranchPlus } from 'lucide-react';
import { useDarkMode } from '@/app/hooks/useDarkMode';

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  disabled?: boolean;
}

interface NavSection {
  header: string;
  items: NavItem[];
}

const DashboardSideNav: React.FC = () => {
  const pathname = usePathname();
  const { data: session } = useSession();
  const isDark = useDarkMode();

  const currentTenantId = (session?.user as { current_tenant_id?: string })?.current_tenant_id;
  const hasTenant = !!currentTenantId;

  const navSections: NavSection[] = [
    {
      header: 'Account',
      items: [
        { label: 'Profile', href: '/ade/dashboard/profile', icon: User },
        { label: 'Linked Accounts', href: '/ade/dashboard/linked-accounts', icon: LinkIcon },
        { label: 'Repositories', href: '/ade/dashboard/repositories', icon: GitBranchPlus },
      ],
    },
    {
      header: 'Administration',
      items: [
        { label: 'Tenants', href: '/ade/dashboard/tenants', icon: Building2 },
        { label: 'API Keys', href: '/ade/dashboard/api-keys', icon: Key, disabled: !hasTenant },
      ],
    },
    {
      header: 'Data Management',
      items: [
        { label: 'Primitives', href: '/ade/dashboard/primitives', icon: Database, disabled: !hasTenant },
      ],
    },
    {
      header: 'Specifications',
      items: [
        { label: 'Projects', href: '/ade/dashboard/projects', icon: Folders, disabled: !hasTenant },
        { label: 'Sunset timeline', href: '/ade/dashboard/versions/sunset-timeline', icon: Sun, disabled: !hasTenant },
        { label: 'Published', href: '/ade/dashboard/published', icon: Eye, disabled: !hasTenant },
      ],
    },
  ];

  /**
   * A nav entry is "active" for its exact path and for any nested route
   * underneath it. Using `startsWith(href + '/')` rather than a bare
   * `startsWith(href)` keeps siblings that share a prefix from cross-
   * highlighting (e.g. a hypothetical `/projects-archive` won't light up
   * the Projects entry while the user is on `/projects`).
   */
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  const sidebarBg = isDark
    ? 'linear-gradient(180deg, #172033 0%, #0f172a 100%)'
    : 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)';
  const sidebarShadow = isDark ? '4px 0 18px rgba(2, 6, 23, 0.32)' : '4px 0 18px rgba(15, 23, 42, 0.06)';

  return (
    <aside
      className="flex-shrink-0 w-[280px] border-r-0"
      style={{
        width: 280,
        boxSizing: 'border-box',
        top: 48,
        height: 'calc(100vh - 48px)',
        background: sidebarBg,
        boxShadow: sidebarShadow,
      }}
    >
      <div className="overflow-auto p-4">
        {navSections.map((section, index) => (
          <div key={section.header} className={index < navSections.length - 1 ? 'mb-6' : ''}>
            <div
              className="flex items-center gap-2 px-3 py-2 font-semibold text-[0.65rem] uppercase tracking-[0.08em]"
              style={{ color: isDark ? '#94a3b8' : '#64748b' }}
            >
              <span
                className="w-1 h-1 rounded-full opacity-60"
                style={{ backgroundColor: '#6366f1' }}
              />
              {section.header}
            </div>
            <ul className="m-0 mt-1 list-none space-y-1 p-0">
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);

                return (
                  <li key={item.href} className="mb-1">
                    {item.disabled ? (
                      <div
                        className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2.5 opacity-40"
                        style={{
                          color: isDark ? '#e2e8f0' : '#334155',
                        }}
                      >
                        <Icon size={20} className="flex-shrink-0 text-slate-500 dark:text-slate-400" />
                        <span className="text-sm font-medium">{item.label}</span>
                      </div>
                    ) : (
                      <Link
                        href={item.href}
                        className={`flex items-center gap-3 rounded-lg px-3 py-2.5 transition-all duration-200 hover:bg-indigo-500/10 ${
                          active
                            ? 'border border-indigo-200 bg-indigo-500/10 dark:border-indigo-700/70'
                            : ''
                        }`}
                      >
                        <Icon
                          size={20}
                          className={`flex-shrink-0 transition-colors ${active ? 'text-indigo-500' : 'text-slate-500 dark:text-slate-400'}`}
                        />
                        <span
                          className="text-sm flex-1"
                          style={{
                            fontWeight: active ? 600 : 500,
                            color: active ? '#6366f1' : isDark ? '#e2e8f0' : '#334155',
                          }}
                        >
                          {item.label}
                        </span>
                        {active && <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-indigo-500" />}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
            {index < navSections.length - 1 && (
              <hr className="my-4 border-indigo-500/10" />
            )}
          </div>
        ))}
      </div>
    </aside>
  );
};

export default DashboardSideNav;

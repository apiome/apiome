'use client';

import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import {
  LayoutDashboard,
  Palette,
  Globe,
  Database,
  ArrowRightLeft,
  Search,
  Shield,
  ClipboardList,
  HelpCircle,
  Users,
  Store,
} from 'lucide-react';
import { cn } from '../../../lib/utils';

// Import version from package.json
import packageJson from '../../../package.json';

interface AppTile {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  href: string;
  enabled: boolean;
  color: string;
  gradient: string;
  openInNewWindow?: boolean;
}

const Ade = () => {
  const router = useRouter();
  const { data: session } = useSession();
  const userName = session?.user?.name?.split(' ')[0] || 'User';

  const mainApps: AppTile[] = [
    {
      id: 'control-panel',
      name: 'Control Panel',
      description: 'Manage tenants, projects, and settings',
      icon: <LayoutDashboard className="w-8 h-8" />,
      href: '/ade/dashboard',
      enabled: true,
      color: 'text-indigo-600 dark:text-indigo-400',
      gradient: 'from-indigo-500 to-purple-600',
    },
    {
      id: 'studio',
      name: 'Studio',
      description: 'Design schemas and API specifications',
      icon: <Palette className="w-8 h-8" />,
      href: '/ade/studio',
      enabled: true,
      color: 'text-purple-600 dark:text-purple-400',
      gradient: 'from-purple-500 to-pink-600',
    },
    {
      id: 'browser',
      name: 'Browser',
      description: 'Browse and explore published schemas',
      icon: <Globe className="w-8 h-8" />,
      href: 'https://brwose.objectified.dev/',
      enabled: true,
      color: 'text-cyan-600 dark:text-cyan-400',
      gradient: 'from-cyan-500 to-blue-600',
      openInNewWindow: true,
    },
  ];

  const dataApps: AppTile[] = [
    {
      id: 'database',
      name: 'Database',
      description: 'Connect and manage data sources',
      icon: <Database className="w-8 h-8" />,
      href: '/ade/database',
      enabled: false,
      color: 'text-emerald-600 dark:text-emerald-400',
      gradient: 'from-emerald-500 to-teal-600',
    },
    {
      id: 'etl',
      name: 'ETL',
      description: 'Extract, transform, and load data',
      icon: <ArrowRightLeft className="w-8 h-8" />,
      href: '/ade/etl',
      enabled: false,
      color: 'text-orange-600 dark:text-orange-400',
      gradient: 'from-orange-500 to-amber-600',
    },
    {
      id: 'data-explorer',
      name: 'Data Explorer',
      description: 'Query and visualize your data',
      icon: <Search className="w-8 h-8" />,
      href: '/ade/explorer',
      enabled: false,
      color: 'text-rose-600 dark:text-rose-400',
      gradient: 'from-rose-500 to-red-600',
    },
  ];

  const auditApps: AppTile[] = [
    {
      id: 'audit',
      name: 'Audit',
      description: 'Review system activity and compliance',
      icon: <Shield className="w-8 h-8" />,
      href: '/ade/audit',
      enabled: false,
      color: 'text-slate-600 dark:text-slate-400',
      gradient: 'from-slate-500 to-gray-600',
    },
    {
      id: 'audit-actions',
      name: 'Audit Actions',
      description: 'Track and manage audit workflows',
      icon: <ClipboardList className="w-8 h-8" />,
      href: '/ade/audit-actions',
      enabled: false,
      color: 'text-zinc-600 dark:text-zinc-400',
      gradient: 'from-zinc-500 to-stone-600',
    },
  ];

  const resourceApps: AppTile[] = [
    {
      id: 'help',
      name: 'Help',
      description: 'Video Support',
      icon: <HelpCircle className="w-8 h-8" />,
      href: 'https://www.youtube.com/@objectifieddev',
      enabled: true,
      color: 'text-blue-600 dark:text-blue-400',
      gradient: 'from-blue-500 to-indigo-600',
      openInNewWindow: true,
    },
    {
      id: 'community',
      name: 'Community',
      description: 'Connect with other users',
      icon: <Users className="w-8 h-8" />,
      href: '/ade/community',
      enabled: false,
      color: 'text-violet-600 dark:text-violet-400',
      gradient: 'from-violet-500 to-purple-600',
    },
    {
      id: 'marketplace',
      name: 'Marketplace',
      description: 'Browse templates and extensions',
      icon: <Store className="w-8 h-8" />,
      href: '/ade/marketplace',
      enabled: false,
      color: 'text-fuchsia-600 dark:text-fuchsia-400',
      gradient: 'from-fuchsia-500 to-pink-600',
    },
  ];

  const handleTileClick = (tile: AppTile) => {
    if (tile.enabled) {
      if (tile.openInNewWindow) {
        window.open(tile.href, '_blank', 'noopener,noreferrer');
      } else {
        router.push(tile.href);
      }
    }
  };

  const renderAppTile = (tile: AppTile) => (
    <button
      key={tile.id}
      onClick={() => handleTileClick(tile)}
      disabled={!tile.enabled}
      className={cn(
        "relative group flex flex-col items-center justify-center p-6 rounded-2xl border transition-all duration-300",
        tile.enabled
          ? "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-transparent hover:shadow-xl hover:scale-[1.02] cursor-pointer"
          : "bg-gray-50 dark:bg-gray-800/50 border-gray-200 dark:border-gray-700/50 opacity-60 cursor-not-allowed"
      )}
    >
      {/* Gradient overlay on hover for enabled tiles */}
      {tile.enabled && (
        <div className={cn(
          "absolute inset-0 rounded-2xl bg-gradient-to-br opacity-0 group-hover:opacity-5 transition-opacity duration-300",
          tile.gradient
        )} />
      )}

      {/* Icon */}
      <div className={cn(
        "mb-3 p-3 rounded-xl transition-all duration-300",
        tile.enabled
          ? `bg-gradient-to-br ${tile.gradient} text-white shadow-lg group-hover:shadow-xl group-hover:scale-110`
          : "bg-gray-200 dark:bg-gray-700 text-gray-400 dark:text-gray-500"
      )}>
        {tile.icon}
      </div>

      {/* Title */}
      <h3 className={cn(
        "text-base font-semibold mb-1",
        tile.enabled
          ? "text-gray-900 dark:text-white"
          : "text-gray-400 dark:text-gray-500"
      )}>
        {tile.name}
      </h3>

      {/* Description */}
      <p className={cn(
        "text-xs text-center leading-relaxed",
        tile.enabled
          ? "text-gray-500 dark:text-gray-400"
          : "text-gray-400 dark:text-gray-600"
      )}>
        {tile.description}
      </p>

      {/* Coming Soon badge for disabled tiles */}
      {!tile.enabled && (
        <span className="absolute top-3 right-3 text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
          Coming Soon
        </span>
      )}
    </button>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800 flex flex-col">
      <div className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col justify-center">
        {/* Welcome Header */}
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
            Objectified Dashboard
          </h1>
          <h4 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Welcome back, {userName}
          </h4>
          <p className="text-gray-500 dark:text-gray-400 text-lg">
            Select your application
          </p>
        </div>

        {/* Main Apps Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          {mainApps.map(renderAppTile)}
        </div>

        {/* Data Apps Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          {dataApps.map(renderAppTile)}
        </div>

        {/* Audit Apps Row */}
        {/*<div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto mb-8">*/}
        {/*  {auditApps.map(renderAppTile)}*/}
        {/*</div>*/}

        {/* Divider */}
        <div className="border-t border-gray-200 dark:border-gray-700 my-8" />

        {/* Resource Apps Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
          {resourceApps.map(renderAppTile)}
        </div>
      </div>

      {/* Footer */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 w-full">
        <div className="flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
          <span>v{packageJson.version}</span>
          <span>© 2018 - 2026 NobuData LLC</span>
        </div>
      </div>
    </div>
  );
};

export default Ade;

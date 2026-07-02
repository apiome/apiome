'use client';

import {
  FolderTree,
  Shapes,
  Library,
  Building2,
  Download,
} from 'lucide-react';
import {
  dashboardPanelClass,
  dashboardTableTheadClass,
  dashboardThClass,
  dashboardThRightClass,
  dashboardTbodyClass,
  dashboardTrHoverClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import type { NamespaceScopeFilter, TypeNamespaceCollection } from './primitivesRegistryTypes';

interface PrimitivesNamespaceCollectionsProps {
  namespaces: TypeNamespaceCollection[];
  unresolvedByNamespace: Record<string, number>;
  scopeFilter: NamespaceScopeFilter;
  onScopeFilterChange: (filter: NamespaceScopeFilter) => void;
  onNamespaceSelect: (namespace: string) => void;
  loading: boolean;
}

const SCOPE_FILTERS: { id: NamespaceScopeFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'system', label: 'System · core' },
  { id: 'tenant', label: 'Tenant' },
  { id: 'imported', label: 'Imported' },
];

function namespaceIcon(namespace: string, isImported: boolean) {
  if (isImported) return Download;
  if (namespace.startsWith('std/')) return namespace.includes('primitives') ? Shapes : Library;
  return Building2;
}

function scopeBadge(scope: 'system' | 'tenant') {
  if (scope === 'system') {
    return (
      <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300">
        System · core
      </span>
    );
  }
  return (
    <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
      Tenant
    </span>
  );
}

function statusBadge(unresolvedCount: number) {
  if (unresolvedCount > 0) {
    return (
      <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
        {unresolvedCount} unresolved
      </span>
    );
  }
  return (
    <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
      Resolved
    </span>
  );
}

export default function PrimitivesNamespaceCollections({
  namespaces,
  unresolvedByNamespace,
  scopeFilter,
  onScopeFilterChange,
  onNamespaceSelect,
  loading,
}: PrimitivesNamespaceCollectionsProps) {
  const filtered = namespaces.filter((ns) => {
    if (scopeFilter === 'system') return ns.scope === 'system';
    if (scopeFilter === 'tenant') return ns.scope === 'tenant';
    if (scopeFilter === 'imported') {
      return ns.scope === 'tenant' && !ns.is_default && !ns.namespace.startsWith('tenant/');
    }
    return true;
  });

  return (
    <section className={`${dashboardPanelClass} xl:col-span-2 overflow-hidden`}>
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <FolderTree className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Type collections</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Grouped by namespace · click a row to filter types below
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 border border-gray-200 dark:border-gray-700 rounded-md p-0.5 text-xs">
          {SCOPE_FILTERS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => onScopeFilterChange(id)}
              className={`px-2 py-1 rounded transition-colors ${
                scopeFilter === id
                  ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-medium'
                  : 'text-gray-500 dark:text-gray-400 hover:text-indigo-500'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="p-6 text-sm text-gray-500 dark:text-gray-400">Loading namespaces…</div>
      ) : filtered.length === 0 ? (
        <div className="p-6 text-sm text-gray-500 dark:text-gray-400">No namespace collections match this filter.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className={dashboardTableTheadClass}>
              <tr>
                <th className={dashboardThClass}>Namespace</th>
                <th className={dashboardThClass}>Scope</th>
                <th className={dashboardThRightClass}>Types</th>
                <th className={dashboardThClass}>Draft</th>
                <th className={dashboardThRightClass}>Status</th>
              </tr>
            </thead>
            <tbody className={dashboardTbodyClass}>
              {filtered.map((ns) => {
                const unresolved = unresolvedByNamespace[ns.namespace] ?? 0;
                const isImported =
                  scopeFilter === 'imported' ||
                  (!ns.is_system && !ns.namespace.startsWith('std/') && !ns.namespace.startsWith('tenant/'));
                const Icon = namespaceIcon(ns.namespace, isImported);
                return (
                  <tr
                    key={ns.id}
                    className={`${dashboardTrHoverClass} cursor-pointer`}
                    onClick={() => onNamespaceSelect(ns.namespace)}
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="w-8 h-8 rounded-md bg-indigo-100 dark:bg-indigo-900/40 inline-flex items-center justify-center text-indigo-600 dark:text-indigo-300">
                          <Icon className="w-4 h-4" />
                        </span>
                        <div>
                          <p className="font-medium font-mono text-gray-900 dark:text-white">
                            {ns.namespace}
                            {isImported ? (
                              <span className="ml-2 text-[9px] px-1 rounded bg-sky-100 dark:bg-sky-900/40 text-sky-600 dark:text-sky-300 uppercase">
                                imported
                              </span>
                            ) : null}
                          </p>
                          {ns.description ? (
                            <p className="text-[10px] text-gray-400 line-clamp-1">{ns.description}</p>
                          ) : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">{scopeBadge(ns.scope)}</td>
                    <td className="px-3 py-3 text-right font-mono text-xs text-gray-700 dark:text-gray-300">
                      {ns.type_count}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-gray-400">2020-12</td>
                    <td className="px-5 py-3 text-right">{statusBadge(unresolved)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-5 py-3 border-t border-gray-100 dark:border-gray-700/60 text-xs text-gray-500 dark:text-gray-400 flex items-center justify-between">
        <span>
          {filtered.length} of {namespaces.length} collection{namespaces.length === 1 ? '' : 's'}
        </span>
      </div>
    </section>
  );
}

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Code, Search } from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';
import { LoadingState } from '../../../ui/LoadingState';
import { EmptyState } from '../../../ui/EmptyState';
import { Alert } from '../../../ui/Alert';
import { Input } from '../../../ui/Input';

export interface PropertiesTabProps {
  projectId: string;
  /** Notifies the parent so it can refresh the tab's count badge. */
  onCountChange?: (count: number | null) => void;
}

interface PropertyRow {
  id: string;
  name: string;
  description?: string | null;
  data?: Record<string, unknown>;
}

function inferType(data: Record<string, unknown> | undefined): string {
  if (!data) return '—';
  const t = data.type;
  if (typeof t === 'string') {
    if (t === 'array' && data.items && typeof data.items === 'object') {
      const itemType = (data.items as Record<string, unknown>).type;
      if (typeof itemType === 'string') return `${itemType}[]`;
      if ((data.items as Record<string, unknown>)['$ref']) return 'ref[]';
      return 'array';
    }
    return t;
  }
  if (data['$ref']) return 'ref';
  if (Array.isArray(data.oneOf)) return 'oneOf';
  if (Array.isArray(data.anyOf)) return 'anyOf';
  if (Array.isArray(data.allOf)) return 'allOf';
  return 'object';
}

function inferFormat(data: Record<string, unknown> | undefined): string | null {
  if (!data) return null;
  const f = data.format;
  return typeof f === 'string' ? f : null;
}

export function PropertiesTab({ projectId, onCountChange }: PropertiesTabProps) {
  const [properties, setProperties] = useState<PropertyRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/properties/${projectId}`);
      const json = (await res.json()) as { success?: boolean; properties?: PropertyRow[]; error?: string };
      if (!res.ok || !json.success) {
        throw new Error(json.error || 'Failed to load properties');
      }
      const list = json.properties ?? [];
      setProperties(list);
      onCountChange?.(list.length);
      setSelectedId((prev) => prev ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load properties');
      onCountChange?.(null);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, onCountChange]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return properties;
    return properties.filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        p.description?.toLowerCase().includes(needle)
    );
  }, [properties, search]);

  const selected = useMemo(
    () => properties.find((p) => p.id === selectedId) ?? null,
    [properties, selectedId]
  );

  if (isLoading) return <LoadingState message="Loading properties…" />;
  if (error) return <Alert variant="error">{error}</Alert>;
  if (properties.length === 0) {
    return (
      <EmptyState
        icon={<Code className="w-8 h-8" />}
        title="No properties defined"
        description="Add properties in the Studio editor or by attaching them to a class."
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Code className="w-4 h-4 text-indigo-500" />
          <span className="text-sm font-semibold">
            {filtered.length === properties.length
              ? `${properties.length} properties`
              : `${filtered.length} of ${properties.length} match`}
          </span>
        </div>
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or description…"
            className="pl-7 w-72 h-9 text-sm"
          />
        </div>
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <div className={`${projectPanelClass} xl:col-span-7`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-wider text-gray-500 bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Name</th>
                  <th className="text-left px-4 py-2 font-semibold">Type</th>
                  <th className="text-left px-4 py-2 font-semibold">Format</th>
                  <th className="text-left px-4 py-2 font-semibold">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
                {filtered.map((prop) => {
                  const isSelected = prop.id === selectedId;
                  return (
                    <tr
                      key={prop.id}
                      onClick={() => setSelectedId(prop.id)}
                      className={`cursor-pointer ${
                        isSelected ? 'bg-indigo-500/5' : 'hover:bg-gray-50/60 dark:hover:bg-gray-900/30'
                      }`}
                    >
                      <td className="px-4 py-2 font-mono text-xs">{prop.name}</td>
                      <td className="px-4 py-2 font-mono text-[11px] text-indigo-600 dark:text-indigo-300">
                        {inferType(prop.data)}
                      </td>
                      <td className="px-4 py-2 font-mono text-[11px] text-gray-500">
                        {inferFormat(prop.data) ?? '—'}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600 dark:text-gray-300 max-w-md truncate">
                        {prop.description || (
                          <span className="italic text-gray-400">no description</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className={`${projectPanelClass} xl:col-span-5`}>
          <div className={projectPanelHeaderClass}>
            <div className="flex items-center gap-3">
              <Code className="w-5 h-5 text-indigo-500" />
              <div>
                <h3 className="text-base font-semibold">
                  {selected?.name ?? 'Select a property'}
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Raw schema definition
                </p>
              </div>
            </div>
          </div>
          {selected ? (
            <div className="p-5 space-y-4 text-xs">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                  Description
                </p>
                <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line">
                  {selected.description || (
                    <span className="italic text-gray-400">no description</span>
                  )}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                  Schema
                </p>
                <pre className="font-mono text-[11px] bg-gray-50 dark:bg-gray-900 border border-gray-100 dark:border-gray-700/60 rounded-md p-3 overflow-x-auto">
                  {JSON.stringify(selected.data ?? {}, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="p-8 text-center text-sm text-gray-500 italic">
              Select a property on the left to inspect its schema.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

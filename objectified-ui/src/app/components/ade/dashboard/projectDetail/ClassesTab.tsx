'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Box,
  Boxes,
  GitFork,
  Layers,
  LayoutGrid,
  List as ListIcon,
  Search,
} from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';
import { LoadingState } from '../../../ui/LoadingState';
import { EmptyState } from '../../../ui/EmptyState';
import { Alert } from '../../../ui/Alert';
import { Input } from '../../../ui/Input';

export interface ClassesTabProps {
  projectId: string;
  /** Notifies the parent so it can refresh the tab's count badge. */
  onCountChange?: (count: number | null) => void;
  /** Notifies the parent when the user toggles to the graph view. */
  onSwitchToGraph?: () => void;
}

interface VersionRow {
  id: string;
  version_id: string;
  enabled: boolean;
  published: boolean;
  deleted_at: string | null;
  created_at: string;
}

interface ClassPropertyRow {
  id: string;
  name: string;
  description?: string | null;
  data?: unknown;
}

interface ClassRow {
  id: string;
  name: string;
  description?: string | null;
  properties?: ClassPropertyRow[];
  tags?: Array<{ id: string; name: string }>;
}

function pickDefaultVersion(versions: VersionRow[]): VersionRow | null {
  if (versions.length === 0) return null;
  const published = versions.filter((v) => v.published);
  if (published.length > 0) return published[0];
  return versions[0];
}

export function ClassesTab({ projectId, onCountChange, onSwitchToGraph }: ClassesTabProps) {
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [classes, setClasses] = useState<ClassRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);
  const [layout, setLayout] = useState<'list' | 'cards'>('list');

  const loadVersions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/versions?projectId=${encodeURIComponent(projectId)}`);
      const json = (await res.json()) as { success?: boolean; versions?: VersionRow[]; error?: string };
      if (!res.ok || !json.success) {
        throw new Error(json.error || 'Failed to load versions');
      }
      const list = json.versions ?? [];
      setVersions(list);
      const next = pickDefaultVersion(list);
      setVersionId((prev) => prev ?? next?.id ?? null);
      if (!next) {
        setClasses([]);
        onCountChange?.(0);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load versions');
      onCountChange?.(null);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, onCountChange]);

  const loadClasses = useCallback(async (vid: string) => {
    setError(null);
    try {
      const res = await fetch(`/api/classes/version/${vid}/with-properties-tags`);
      const json = (await res.json()) as { success?: boolean; classes?: ClassRow[]; error?: string };
      if (!res.ok || !json.success) {
        throw new Error(json.error || 'Failed to load classes');
      }
      const list = json.classes ?? [];
      setClasses(list);
      onCountChange?.(list.length);
      setSelectedClassId((prev) => prev ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load classes');
      onCountChange?.(null);
    }
  }, [onCountChange]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  useEffect(() => {
    if (!versionId) return;
    void loadClasses(versionId);
  }, [versionId, loadClasses]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return classes;
    return classes.filter((c) =>
      c.name.toLowerCase().includes(needle) ||
      c.description?.toLowerCase().includes(needle) ||
      c.properties?.some((p) => p.name.toLowerCase().includes(needle))
    );
  }, [classes, search]);

  const selected = useMemo(
    () => classes.find((c) => c.id === selectedClassId) ?? null,
    [classes, selectedClassId]
  );

  if (isLoading) return <LoadingState message="Loading classes…" />;
  if (error) return <Alert variant="error">{error}</Alert>;
  if (versions.length === 0) {
    return (
      <EmptyState
        icon={<Boxes className="w-8 h-8" />}
        title="No versions to inspect"
        description="Commit a revision in the Studio editor before inspecting classes."
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-indigo-500" />
          <span className="text-xs text-gray-500">Version</span>
          <select
            value={versionId ?? ''}
            onChange={(e) => {
              setVersionId(e.target.value);
              setSelectedClassId(null);
            }}
            className="h-9 px-2 text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 font-mono"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_id}
                {v.published ? ' · published' : ''}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search class or property…"
              className="pl-7 w-64 h-9 text-sm"
            />
          </div>
          <div className="flex items-center text-xs rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden">
            <button
              type="button"
              onClick={() => setLayout('list')}
              className={`px-2.5 py-1.5 inline-flex items-center gap-1.5 ${
                layout === 'list'
                  ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-semibold'
                  : 'hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-500'
              }`}
            >
              <ListIcon className="w-3.5 h-3.5" /> List
            </button>
            <button
              type="button"
              onClick={() => setLayout('cards')}
              className={`px-2.5 py-1.5 inline-flex items-center gap-1.5 ${
                layout === 'cards'
                  ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-semibold'
                  : 'hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-500'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" /> Cards
            </button>
            <Link
              href={`/ade/dashboard/projects/${projectId}?tab=classes&view=graph`}
              onClick={() => onSwitchToGraph?.()}
              className="px-2.5 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-500 inline-flex items-center gap-1.5"
            >
              <GitFork className="w-3.5 h-3.5" /> Graph
            </Link>
          </div>
        </div>
      </section>

      {classes.length === 0 ? (
        <EmptyState
          icon={<Boxes className="w-8 h-8" />}
          title="No classes in this version"
          description="Add classes in the Studio editor for this version to see them here."
        />
      ) : (
        <section className="grid grid-cols-1 xl:grid-cols-12 gap-6">
          <div className={`${projectPanelClass} xl:col-span-5`}>
            <div className={projectPanelHeaderClass}>
              <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                {filtered.length === classes.length
                  ? `${classes.length} classes`
                  : `${filtered.length} of ${classes.length} match`}
              </p>
            </div>
            <div className={layout === 'cards' ? 'p-3 grid grid-cols-1 md:grid-cols-2 gap-3' : ''}>
              {layout === 'list' ? (
                <ul className="divide-y divide-gray-100 dark:divide-gray-700/60 max-h-[640px] overflow-y-auto">
                  {filtered.map((cls) => (
                    <ClassListRow
                      key={cls.id}
                      cls={cls}
                      isSelected={cls.id === selectedClassId}
                      onSelect={() => setSelectedClassId(cls.id)}
                    />
                  ))}
                </ul>
              ) : (
                filtered.map((cls) => (
                  <ClassCard
                    key={cls.id}
                    cls={cls}
                    isSelected={cls.id === selectedClassId}
                    onSelect={() => setSelectedClassId(cls.id)}
                  />
                ))
              )}
            </div>
          </div>

          <div className={`${projectPanelClass} xl:col-span-7`}>
            <div className={projectPanelHeaderClass}>
              <div className="flex items-center gap-3">
                <Box className="w-5 h-5 text-indigo-500" />
                <div>
                  <h3 className="text-base font-semibold">
                    {selected?.name ?? 'Select a class'}
                  </h3>
                  {selected ? (
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-md">
                      {selected.description ?? <span className="italic">no description</span>}
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
            {selected ? (
              <div className="p-5 space-y-4">
                <div className="grid grid-cols-3 gap-4 text-xs">
                  <DetailKpi label="Properties" value={selected.properties?.length ?? 0} />
                  <DetailKpi label="Tags" value={selected.tags?.length ?? 0} />
                  <DetailKpi
                    label="$ref properties"
                    value={
                      selected.properties?.filter((p) =>
                        JSON.stringify(p.data ?? {}).includes('"$ref"')
                      ).length ?? 0
                    }
                  />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
                    Properties
                  </p>
                  {selected.properties && selected.properties.length > 0 ? (
                    <ul className="rounded-md border border-gray-100 dark:border-gray-700/60 divide-y divide-gray-100 dark:divide-gray-700/60 text-sm">
                      {selected.properties.map((prop) => (
                        <li key={prop.id} className="px-3 py-2 flex items-baseline gap-3">
                          <span className="font-mono text-xs">{prop.name}</span>
                          {prop.description ? (
                            <span className="text-xs text-gray-500 truncate">
                              {prop.description}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-gray-500 italic">No properties.</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-8 text-center text-sm text-gray-500 italic">
                Select a class on the left to inspect its properties.
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function ClassListRow({
  cls,
  isSelected,
  onSelect,
}: {
  cls: ClassRow;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <li
      onClick={onSelect}
      className={`px-4 py-3 cursor-pointer ${
        isSelected
          ? 'bg-indigo-500/5 border-l-2 border-indigo-500'
          : 'hover:bg-gray-50 dark:hover:bg-gray-900/30 border-l-2 border-transparent'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Box className="w-3.5 h-3.5 text-indigo-400" />
            <span className="font-semibold font-mono text-sm">{cls.name}</span>
          </div>
          {cls.description ? (
            <p className="text-[11px] text-gray-500 mt-0.5 truncate">{cls.description}</p>
          ) : null}
        </div>
        <span className="font-mono text-[11px] text-gray-500 shrink-0">
          {cls.properties?.length ?? 0} props
        </span>
      </div>
    </li>
  );
}

function ClassCard({
  cls,
  isSelected,
  onSelect,
}: {
  cls: ClassRow;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-left rounded-md border p-3 transition-colors ${
        isSelected
          ? 'border-indigo-500 bg-indigo-500/5'
          : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
      }`}
    >
      <div className="flex items-center gap-2">
        <Box className="w-3.5 h-3.5 text-indigo-400" />
        <span className="font-semibold font-mono text-sm">{cls.name}</span>
      </div>
      {cls.description ? (
        <p className="text-[11px] text-gray-500 mt-1 line-clamp-2">{cls.description}</p>
      ) : null}
      <div className="flex items-center gap-3 mt-2 text-[11px] text-gray-500 font-mono">
        <span>{cls.properties?.length ?? 0} props</span>
        {cls.tags && cls.tags.length > 0 ? <span>{cls.tags.length} tags</span> : null}
      </div>
    </button>
  );
}

function DetailKpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-gray-100 dark:border-gray-700/60 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        {label}
      </p>
      <p className="text-base font-bold font-mono mt-0.5">{value}</p>
    </div>
  );
}

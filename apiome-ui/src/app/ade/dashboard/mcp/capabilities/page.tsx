'use client';

/**
 * Capability directory page (V2-MCP-35.4 / MCAT-21.4, #4663).
 *
 * Browsable, paginated index of every tool/resource/prompt across the tenant catalog, filterable by
 * name, type, and owning server, with links back to each server detail page.
 */

import Link from 'next/link';
import { useSession } from 'next-auth/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layers, RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Input } from '@/app/components/ui/Input';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardTableWrapClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  MCP_CAPABILITY_DIRECTORY_DEFAULT_FILTERS,
  MCP_CAPABILITY_DIRECTORY_KINDS,
  MCP_CAPABILITY_DIRECTORY_PAGE_SIZE,
  MCP_CAPABILITY_DIRECTORY_SORTS,
  mcpCapabilityDirectoryDisplayName,
  mcpCapabilityDirectoryEndpointHref,
  mcpCapabilityDirectoryFromPayload,
  mcpCapabilityDirectoryKindBadge,
  mcpCapabilityDirectoryQueryParams,
  type McpCapabilityDirectoryEntry,
  type McpCapabilityDirectoryFilters,
  type McpCapabilityDirectorySort,
} from '@/app/components/ade/dashboard/mcp/mcpCapabilityDirectoryUi';

export default function McpCapabilityDirectoryPage() {
  const { data: session } = useSession();
  const sessionUser = session?.user as { current_tenant_id?: string } | undefined;
  const currentTenantId = sessionUser?.current_tenant_id;

  const [items, setItems] = useState<McpCapabilityDirectoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<McpCapabilityDirectoryFilters>(
    MCP_CAPABILITY_DIRECTORY_DEFAULT_FILTERS,
  );
  const [sort, setSort] = useState<McpCapabilityDirectorySort>('server');
  const [nameDraft, setNameDraft] = useState('');

  const pageCount = Math.max(1, Math.ceil(total / MCP_CAPABILITY_DIRECTORY_PAGE_SIZE));
  const pageIndex = Math.floor(offset / MCP_CAPABILITY_DIRECTORY_PAGE_SIZE) + 1;

  const load = useCallback(async () => {
    if (!currentTenantId) {
      setItems([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const params = mcpCapabilityDirectoryQueryParams(
        filters,
        sort,
        offset,
        MCP_CAPABILITY_DIRECTORY_PAGE_SIZE,
      );
      const res = await fetch(`/api/mcp/capabilities?${params.toString()}`, {
        credentials: 'include',
        cache: 'no-store',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      const page = mcpCapabilityDirectoryFromPayload(data);
      setItems(page.items);
      setTotal(page.total);
    } catch (e) {
      setItems([]);
      setTotal(0);
      setError(e instanceof Error ? e.message : 'Could not load the capability directory.');
    } finally {
      setLoading(false);
    }
  }, [currentTenantId, filters, offset, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  const applyNameFilter = useCallback(() => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, name: nameDraft.trim() }));
  }, [nameDraft]);

  const summary = useMemo(() => {
    if (total === 0) return 'No capabilities';
    const start = offset + 1;
    const end = Math.min(offset + items.length, total);
    return `${start}–${end} of ${total}`;
  }, [items.length, offset, total]);

  return (
    <>
      <header className="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <h2 className="flex items-center gap-2 text-2xl font-bold text-gray-900 dark:text-white">
                <Layers className="h-6 w-6 text-indigo-600 dark:text-indigo-400" aria-hidden />
                Capability Directory
              </h2>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                Browse every tool, resource, and prompt across your catalog — a &ldquo;what can be
                done&rdquo; index with links back to each owning server.
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              className="h-auto min-h-10 shrink-0 whitespace-nowrap py-2"
              onClick={() => void load()}
              disabled={!currentTenantId}
              title="Reload capability directory"
            >
              <RefreshCw className="h-4 w-4 shrink-0" aria-hidden />
              Refresh
            </Button>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass} aria-busy={loading}>
        <div className={dashboardContentStackClass}>
          <div className="space-y-4 px-6 pt-4">
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
              <div className="min-w-[12rem] flex-1">
                <label
                  htmlFor="capability-directory-name"
                  className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400"
                >
                  Name
                </label>
                <div className="flex gap-2">
                  <Input
                    id="capability-directory-name"
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') applyNameFilter();
                    }}
                    placeholder="Filter by name or title…"
                  />
                  <Button type="button" variant="secondary" onClick={applyNameFilter}>
                    Apply
                  </Button>
                </div>
              </div>
              <div className="w-40">
                <label
                  htmlFor="capability-directory-type"
                  className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400"
                >
                  Type
                </label>
                <Select
                  value={filters.type || 'all'}
                  onValueChange={(value) => {
                    setOffset(0);
                    setFilters((prev) => ({
                      ...prev,
                      type: value === 'all' ? '' : (value as McpCapabilityDirectoryFilters['type']),
                    }));
                  }}
                >
                  <SelectTrigger id="capability-directory-type">
                    <SelectValue placeholder="All types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All types</SelectItem>
                    {MCP_CAPABILITY_DIRECTORY_KINDS.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {mcpCapabilityDirectoryKindBadge(kind).label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="min-w-[10rem] flex-1">
                <label
                  htmlFor="capability-directory-host"
                  className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400"
                >
                  Host
                </label>
                <Input
                  id="capability-directory-host"
                  value={filters.host}
                  onChange={(e) => {
                    setOffset(0);
                    setFilters((prev) => ({ ...prev, host: e.target.value }));
                  }}
                  placeholder="e.g. mcp.example.com"
                />
              </div>
              <div className="w-36">
                <label
                  htmlFor="capability-directory-visibility"
                  className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400"
                >
                  Visibility
                </label>
                <Select
                  value={filters.visibility || 'all'}
                  onValueChange={(value) => {
                    setOffset(0);
                    setFilters((prev) => ({
                      ...prev,
                      visibility:
                        value === 'all' ? '' : (value as McpCapabilityDirectoryFilters['visibility']),
                    }));
                  }}
                >
                  <SelectTrigger id="capability-directory-visibility">
                    <SelectValue placeholder="All" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="private">Private</SelectItem>
                    <SelectItem value="public">Public</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="w-36">
                <label
                  htmlFor="capability-directory-sort"
                  className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400"
                >
                  Sort
                </label>
                <Select
                  value={sort}
                  onValueChange={(value) => {
                    setOffset(0);
                    setSort(value as McpCapabilityDirectorySort);
                  }}
                >
                  <SelectTrigger id="capability-directory-sort">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MCP_CAPABILITY_DIRECTORY_SORTS.map((option) => (
                      <SelectItem key={option.key} value={option.key}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-gray-500 dark:text-gray-400">
              <span>{summary}</span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset((prev) => Math.max(0, prev - MCP_CAPABILITY_DIRECTORY_PAGE_SIZE))}
                >
                  Previous
                </Button>
                <span>
                  Page {pageIndex} of {pageCount}
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={offset + MCP_CAPABILITY_DIRECTORY_PAGE_SIZE >= total || loading}
                  onClick={() => setOffset((prev) => prev + MCP_CAPABILITY_DIRECTORY_PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          </div>

          <div className="px-6 pb-8">
            {loading ? (
              <div className={dashboardTableWrapClass}>
                <LoadingState minHeightClassName="min-h-[220px]" message="Loading capabilities…" />
              </div>
            ) : error ? (
              <ErrorState
                title="Could not load the capability directory"
                description={error}
                onRetry={() => void load()}
              />
            ) : items.length === 0 ? (
              <EmptyState
                className="mt-2"
                icon={<Layers className="h-10 w-10 text-white" aria-hidden />}
                title="No capabilities found"
                description="Try clearing a filter or discover MCP servers so their tools, resources, and prompts appear here."
              />
            ) : (
              <div className={dashboardTableWrapClass}>
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                  <thead className="bg-gray-50 dark:bg-gray-900/40">
                    <tr>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                      >
                        Capability
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                      >
                        Type
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                      >
                        Server
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                      >
                        Host
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-800">
                    {items.map((entry) => {
                      const kindBadge = mcpCapabilityDirectoryKindBadge(entry.kind);
                      return (
                        <tr key={`${entry.endpointId}:${entry.itemId}`}>
                          <td className="px-4 py-3">
                            <div className="font-medium text-gray-900 dark:text-white">
                              {mcpCapabilityDirectoryDisplayName(entry)}
                            </div>
                            {entry.description ? (
                              <p className="mt-0.5 line-clamp-2 text-sm text-gray-500 dark:text-gray-400">
                                {entry.description}
                              </p>
                            ) : null}
                            <p className="mt-1 font-mono text-xs text-gray-400 dark:text-gray-500">
                              {entry.itemName}
                            </p>
                          </td>
                          <td className="px-4 py-3">
                            <Badge variant={kindBadge.variant}>{kindBadge.label}</Badge>
                          </td>
                          <td className="px-4 py-3">
                            <Link
                              href={mcpCapabilityDirectoryEndpointHref(entry.endpointId)}
                              className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                            >
                              {entry.endpointName}
                            </Link>
                            {entry.grade ? (
                              <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                                Grade {entry.grade}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                            {entry.host}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

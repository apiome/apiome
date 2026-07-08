'use client';

import * as React from 'react';
import { Bookmark, Pin, Play, Trash2, X } from 'lucide-react';
import { cn } from '@lib/utils';
import { Button } from '../../../ui/Button';
import { Input } from '../../../ui/Input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../ui/Dialog';
import {
  mcpApplySavedSearch,
  mcpPinnedSavedSearches,
  mcpSavedSearchCreateBody,
  mcpSavedSearchesFromPayload,
  type McpSavedSearch,
} from './mcpSavedSearchUi';
import type { McpCatalogFilters, McpCatalogSortKey } from './mcpCatalogUi';

export interface McpSavedSearchesPanelProps {
  filters: McpCatalogFilters;
  query: string;
  sort: McpCatalogSortKey;
  onApply: (next: { filters: McpCatalogFilters; query: string; sort: McpCatalogSortKey }) => void;
}

async function fetchSavedSearches(): Promise<McpSavedSearch[]> {
  const res = await fetch('/api/mcp/saved-searches', { credentials: 'include' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
  }
  return mcpSavedSearchesFromPayload(data);
}

/**
 * Saved-search controls: pinned catalog views, save dialog, and manage list.
 */
export function McpSavedSearchesPanel({
  filters,
  query,
  sort,
  onApply,
}: McpSavedSearchesPanelProps): React.ReactElement {
  const [searches, setSearches] = React.useState<McpSavedSearch[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [panelOpen, setPanelOpen] = React.useState(false);
  const [saveOpen, setSaveOpen] = React.useState(false);
  const [saveName, setSaveName] = React.useState('');
  const [savePinned, setSavePinned] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSearches(await fetchSavedSearches());
    } catch (e) {
      setSearches([]);
      setError(e instanceof Error ? e.message : 'Could not load saved searches');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const pinned = React.useMemo(() => mcpPinnedSavedSearches(searches), [searches]);

  const handleSave = async () => {
    const name = saveName.trim();
    if (!name) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/mcp/saved-searches', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mcpSavedSearchCreateBody(name, filters, query, sort, savePinned)),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      setSaveOpen(false);
      setSaveName('');
      setSavePinned(false);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save search');
    } finally {
      setSaving(false);
    }
  };

  const handleRun = (search: McpSavedSearch) => {
    onApply(mcpApplySavedSearch(search));
    setPanelOpen(false);
  };

  const handleDelete = async (searchId: string) => {
    setError(null);
    try {
      const res = await fetch(`/api/mcp/saved-searches/${encodeURIComponent(searchId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete saved search');
    }
  };

  const handleTogglePin = async (search: McpSavedSearch) => {
    setError(null);
    try {
      const res = await fetch(`/api/mcp/saved-searches/${encodeURIComponent(search.id)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isPinned: !search.isPinned }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update saved search');
    }
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {pinned.map((search) => (
          <button
            key={search.id}
            type="button"
            onClick={() => handleRun(search)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800',
              'transition-colors hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200 dark:hover:bg-amber-900/50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500',
            )}
            title={`Run saved view: ${search.name}`}
          >
            <Pin className="h-3.5 w-3.5" aria-hidden />
            {search.name}
          </button>
        ))}

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9"
          onClick={() => setSaveOpen(true)}
        >
          <Bookmark className="h-4 w-4" aria-hidden />
          Save search
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-9"
          aria-expanded={panelOpen}
          onClick={() => setPanelOpen((v) => !v)}
        >
          Saved ({searches.length})
        </Button>
      </div>

      {panelOpen ? (
        <div className="border-t border-gray-200 bg-white px-6 py-4 dark:border-gray-700 dark:bg-gray-800">
          {error ? (
            <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">
              {error}
            </p>
          ) : null}
          {loading ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">Loading saved searches…</p>
          ) : searches.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No saved searches yet. Set your filters and click Save search.
            </p>
          ) : (
            <ul className="divide-y divide-gray-200 rounded-md border border-gray-200 dark:divide-gray-700 dark:border-gray-700">
              {searches.map((search) => (
                <li
                  key={search.id}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-gray-900 dark:text-white">
                      {search.name}
                      {search.isPinned ? (
                        <span className="ml-2 text-xs font-normal text-amber-600 dark:text-amber-400">
                          pinned
                        </span>
                      ) : null}
                    </p>
                    {search.query ? (
                      <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                        Query: {search.query}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8"
                      title="Run saved search"
                      onClick={() => handleRun(search)}
                    >
                      <Play className="h-4 w-4" aria-hidden />
                      <span className="sr-only">Run</span>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8"
                      title={search.isPinned ? 'Unpin view' : 'Pin as catalog view'}
                      onClick={() => void handleTogglePin(search)}
                    >
                      <Pin className="h-4 w-4" aria-hidden />
                      <span className="sr-only">{search.isPinned ? 'Unpin' : 'Pin'}</span>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 text-red-600 hover:text-red-700 dark:text-red-400"
                      title="Delete saved search"
                      onClick={() => void handleDelete(search.id)}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                      <span className="sr-only">Delete</span>
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Save catalog search</DialogTitle>
            <DialogDescription>
              Save the current filters, search text, and sort so you can re-run them later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300" htmlFor="saved-search-name">
              Name
            </label>
            <Input
              id="saved-search-name"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="e.g. Ungraded destructive servers"
              autoFocus
            />
            <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
              <input
                type="checkbox"
                checked={savePinned}
                onChange={(e) => setSavePinned(e.target.checked)}
                className="rounded border-gray-300"
              />
              Pin as catalog view
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setSaveOpen(false)}>
              <X className="h-4 w-4" aria-hidden />
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!saveName.trim() || saving}
              onClick={() => void handleSave()}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

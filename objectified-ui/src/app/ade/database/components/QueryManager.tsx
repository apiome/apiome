'use client';

import * as React from 'react';
import { useDatabase } from '../DatabaseContext';
import { List, Search, Sparkles, Plus, Database, Info } from 'lucide-react';
import type { SnapshotQueryFilters } from './query-manager-types';
import InsertStubModal from './InsertStubModal';
import QueryUsingAIPanel from './QueryUsingAIPanel';

const PAGE_SIZE = 20;

export default function QueryManager() {
  const { selectedProjectId, selectedVersionId, selectedTable, isReadOnly } = useDatabase();
  const [viewMode, setViewMode] = React.useState<'none' | 'viewAll' | 'search' | 'ai'>('none');
  const [count, setCount] = React.useState<number | null>(null);
  const [rows, setRows] = React.useState<Array<{ record_id: string; data: Record<string, unknown>; updated_at: string }>>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(false);
  const [searchQ, setSearchQ] = React.useState('');
  const [insertModalOpen, setInsertModalOpen] = React.useState(false);
  const [aiPanelOpen, setAiPanelOpen] = React.useState(false);

  const classSchemaId = selectedTable?.classSchemaId ?? null;

  const loadCount = React.useCallback(() => {
    if (!classSchemaId) return;
    fetch(`/api/database/snapshot/count?classSchemaId=${encodeURIComponent(classSchemaId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && typeof data.count === 'number') setCount(data.count);
      });
  }, [classSchemaId]);

  React.useEffect(() => {
    if (!classSchemaId) {
      setCount(null);
      setViewMode('none');
      setRows([]);
      setTotal(0);
      setPage(1);
      return;
    }
    // When switching to a different table, reset the right-hand view so we don't
    // show stale data or keep "view all" active for the new table.
    setViewMode('none');
    setRows([]);
    setTotal(0);
    setPage(1);
    setSearchQ('');
    loadCount();
  }, [classSchemaId, loadCount]);

  const runQuery = React.useCallback((filters: SnapshotQueryFilters, pageNum: number, pageSize: number, searchQuery?: string) => {
    if (!filters.classSchemaId) return;
    setLoading(true);
    const base = `/api/database/snapshot`;
    const url = searchQuery
      ? `${base}/search?classSchemaId=${encodeURIComponent(filters.classSchemaId)}&q=${encodeURIComponent(searchQuery)}&page=${pageNum}&pageSize=${pageSize}`
      : `${base}?classSchemaId=${encodeURIComponent(filters.classSchemaId)}&page=${pageNum}&pageSize=${pageSize}`;
    fetch(url)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.rows) {
          setRows(data.rows);
          setTotal(data.total ?? 0);
          setPage(data.page ?? pageNum);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const handleViewAll = () => {
    setViewMode('viewAll');
    if (classSchemaId) runQuery({ classSchemaId }, 1, PAGE_SIZE);
  };

  const handleSearch = () => {
    setViewMode('search');
    if (classSchemaId) runQuery({ classSchemaId }, 1, PAGE_SIZE, searchQ);
  };

  const handlePageChange = (newPage: number) => {
    if (!classSchemaId) return;
    if (viewMode === 'search') {
      runQuery({ classSchemaId }, newPage, PAGE_SIZE, searchQ);
    } else {
      runQuery({ classSchemaId }, newPage, PAGE_SIZE);
    }
  };

  if (!selectedProjectId || !selectedVersionId) {
    return (
      <div className="h-full flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
        <div className="relative">
          <div className="absolute -top-20 -left-20 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
          <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-gradient-to-br from-blue-100 to-cyan-100 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />

          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-12 md:p-16 text-center shadow-xl shadow-gray-200/50 dark:shadow-gray-900/50">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Database className="h-10 w-10 text-white" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-3">
              No Project Selected
            </h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto leading-relaxed">
              Select a project and version from the dropdowns above to view and query data records
            </p>

            <div className="mt-8 pt-6 border-t border-gray-100 dark:border-gray-700/50">
              <p className="text-xs text-gray-400 dark:text-gray-500 flex items-center justify-center gap-2">
                <Info className="w-4 h-4" />
                Tip: Published versions have frozen schemas; pick a table to view records, search, or query with AI
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!selectedTable) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-10 text-center shadow-lg max-w-md">
          <div className="w-16 h-16 mx-auto mb-4 bg-gradient-to-br from-indigo-500/20 to-purple-600/20 dark:from-indigo-500/30 dark:to-purple-600/30 rounded-xl flex items-center justify-center">
            <Database className="h-8 w-8 text-indigo-600 dark:text-indigo-400" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Select a table</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Select a table from the left to view records, search, or query with AI.
          </p>
        </div>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col h-full overflow-hidden p-4">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">{selectedTable.className}</h3>
          {count !== null && (
            <p className="text-sm text-gray-500 dark:text-gray-400">{count} record{count !== 1 ? 's' : ''}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleViewAll}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <List className="w-4 h-4" />
            View all records
          </button>
          <div className="inline-flex items-center gap-2">
            <input
              type="text"
              placeholder="Search..."
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              className="px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white min-w-[160px]"
            />
            <button
              type="button"
              onClick={handleSearch}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              <Search className="w-4 h-4" />
              Search
            </button>
          </div>
          <button
            type="button"
            onClick={() => setAiPanelOpen(true)}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/30 text-sm text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/50"
          >
            <Sparkles className="w-4 h-4" />
            Query using AI
          </button>
          {!isReadOnly && (
            <button
              type="button"
              onClick={() => setInsertModalOpen(true)}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/30 text-sm text-green-700 dark:text-green-300 hover:bg-green-100 dark:hover:bg-green-900/50"
            >
              <Plus className="w-4 h-4" />
              Insert
            </button>
          )}
        </div>
      </div>

      {(viewMode === 'viewAll' || viewMode === 'search') && (
        <div className="flex-1 flex flex-col min-h-0 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
          {loading ? (
            <div className="p-4 text-sm text-gray-500">Loading...</div>
          ) : rows.length === 0 ? (
            <div className="p-4 text-sm text-gray-500">No records found.</div>
          ) : (
            <>
              <div className="flex-1 overflow-auto p-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-600">
                      <th className="text-left py-2 px-2 font-medium text-gray-700 dark:text-gray-300">Record ID</th>
                      <th className="text-left py-2 px-2 font-medium text-gray-700 dark:text-gray-300">Updated</th>
                      <th className="text-left py-2 px-2 font-medium text-gray-700 dark:text-gray-300">Data</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.record_id} className="border-b border-gray-100 dark:border-gray-700">
                        <td className="py-2 px-2 font-mono text-xs text-gray-600 dark:text-gray-400">{row.record_id}</td>
                        <td className="py-2 px-2 text-gray-600 dark:text-gray-400">{row.updated_at}</td>
                        <td className="py-2 px-2">
                          <pre className="text-xs overflow-x-auto max-w-md whitespace-pre-wrap break-all text-gray-700 dark:text-gray-300">
                            {JSON.stringify(row.data)}
                          </pre>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {totalPages > 1 && (
                <div className="flex items-center justify-between gap-2 p-2 border-t border-gray-200 dark:border-gray-700">
                  <button
                    type="button"
                    onClick={() => handlePageChange(page - 1)}
                    disabled={page <= 1}
                    className="px-3 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    Page {page} of {totalPages}
                  </span>
                  <button
                    type="button"
                    onClick={() => handlePageChange(page + 1)}
                    disabled={page >= totalPages}
                    className="px-3 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {viewMode === 'none' && (
        <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400 text-sm">
          Click &quot;View all records&quot; or &quot;Search&quot; to load data.
        </div>
      )}

      {classSchemaId && (
        <InsertStubModal
          open={insertModalOpen}
          onClose={() => setInsertModalOpen(false)}
          tableName={selectedTable.className}
          classSchemaId={classSchemaId}
          onInserted={() => {
            loadCount();
            if (viewMode === 'viewAll') runQuery({ classSchemaId }, 1, PAGE_SIZE);
            if (viewMode === 'search') runQuery({ classSchemaId }, 1, PAGE_SIZE, searchQ);
          }}
        />
      )}
      <QueryUsingAIPanel
        open={aiPanelOpen}
        onClose={() => setAiPanelOpen(false)}
        versionId={selectedVersionId ?? ''}
        tableName={selectedTable.className}
        classSchemaId={classSchemaId}
      />
    </div>
  );
}

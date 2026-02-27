'use client';

import * as React from 'react';
import { useDatabase } from '../DatabaseContext';
import { List, Search, Sparkles, Plus } from 'lucide-react';
import type { SnapshotQueryFilters } from './query-manager-types';
import InsertStubModal from './InsertStubModal';
import QueryUsingAIPanel from './QueryUsingAIPanel';

const PAGE_SIZE = 20;

export default function QueryManager() {
  const { selectedTable, selectedVersionId, isReadOnly } = useDatabase();
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
      return;
    }
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

  if (!selectedTable) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400 p-8">
        <p className="text-sm">Select a table from the left to view records, search, or query with AI.</p>
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

      <InsertStubModal open={insertModalOpen} onClose={() => setInsertModalOpen(false)} tableName={selectedTable.className} />
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

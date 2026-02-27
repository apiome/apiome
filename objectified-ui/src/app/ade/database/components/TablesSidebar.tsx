'use client';

import * as React from 'react';
import { useDatabase } from '../DatabaseContext';

interface TableRow {
  class_schema_id: string;
  class_id: string;
  class_name: string;
  schema: Record<string, unknown>;
}

export default function TablesSidebar() {
  const { selectedVersionId, selectedTable, setSelectedTable, isReadOnly } = useDatabase();
  const [tables, setTables] = React.useState<TableRow[]>([]);
  const [counts, setCounts] = React.useState<Record<string, number>>({});
  const [loading, setLoading] = React.useState(false);
  const [countLoading, setCountLoading] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!selectedVersionId) {
      setTables([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/database/versions/${selectedVersionId}/tables`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        if (data.success && data.tables) setTables(data.tables);
        else setTables([]);
      })
      .catch(() => { if (!cancelled) setTables([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedVersionId]);

  const loadCount = React.useCallback((classSchemaId: string) => {
    setCountLoading(classSchemaId);
    fetch(`/api/database/snapshot/count?classSchemaId=${encodeURIComponent(classSchemaId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && typeof data.count === 'number') {
          setCounts((prev) => ({ ...prev, [classSchemaId]: data.count }));
        }
      })
      .finally(() => setCountLoading(null));
  }, []);

  const handleTableClick = (row: TableRow) => {
    setSelectedTable({ classSchemaId: row.class_schema_id, className: row.class_name });
    if (counts[row.class_schema_id] === undefined) loadCount(row.class_schema_id);
  };

  React.useEffect(() => {
    if (selectedTable && counts[selectedTable.classSchemaId] === undefined && !countLoading) {
      loadCount(selectedTable.classSchemaId);
    }
  }, [selectedTable, counts, countLoading, loadCount]);

  return (
    <aside
      className="border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex flex-col overflow-hidden"
      style={{ width: 280, minWidth: 280 }}
    >
      <div className="p-2 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Tables</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="text-sm text-gray-500 dark:text-gray-400">Loading tables...</div>
        ) : tables.length === 0 ? (
          <div className="text-sm text-gray-500 dark:text-gray-400">No tables. Publish a version to see class schemas.</div>
        ) : (
          <ul className="space-y-1">
            {tables.map((row) => {
              const isSelected = selectedTable?.classSchemaId === row.class_schema_id;
              const count = counts[row.class_schema_id];
              const loadingCount = countLoading === row.class_schema_id;
              return (
                <li key={row.class_schema_id}>
                  <button
                    type="button"
                    onClick={() => handleTableClick(row)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                      isSelected
                        ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-800 dark:text-indigo-200'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
                    }`}
                  >
                    <span className="font-medium">{row.class_name}</span>
                    {loadingCount && <span className="ml-2 text-xs text-gray-400">...</span>}
                    {!loadingCount && typeof count === 'number' && (
                      <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">({count})</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

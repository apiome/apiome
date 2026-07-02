'use client';

import React, { createContext, useContext, useState, useRef, useCallback, ReactNode } from 'react';

export interface SelectedTable {
  classSchemaId: string;
  className: string;
}

export type RefreshTableCountHandler = (classSchemaId: string) => void;

export interface DatabaseContextType {
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
  selectedVersionId: string | null;
  setSelectedVersionId: (id: string | null) => void;
  latestVersionId: string | null;
  setLatestVersionId: (id: string | null) => void;
  isReadOnly: boolean;
  setIsReadOnly: (value: boolean) => void;
  selectedTable: SelectedTable | null;
  setSelectedTable: (t: SelectedTable | null) => void;
  /** Ref for the sidebar to register its count-refresh handler. Called after insert/update/delete for a class. */
  refreshTableCountRef: React.MutableRefObject<RefreshTableCountHandler | null>;
  /** Call this after a successful insert/update/delete to refresh the sidebar count for that class. */
  refreshTableCount: (classSchemaId: string) => void;
}

const DatabaseContext = createContext<DatabaseContextType | undefined>(undefined);

export function DatabaseProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [latestVersionId, setLatestVersionId] = useState<string | null>(null);
  const [isReadOnly, setIsReadOnly] = useState<boolean>(false);
  const [selectedTable, setSelectedTable] = useState<SelectedTable | null>(null);
  const refreshTableCountRef = useRef<RefreshTableCountHandler | null>(null);
  const refreshTableCount = useCallback((classSchemaId: string) => {
    refreshTableCountRef.current?.(classSchemaId);
  }, []);

  return (
    <DatabaseContext.Provider
      value={{
        selectedProjectId,
        setSelectedProjectId,
        selectedVersionId,
        setSelectedVersionId,
        latestVersionId,
        setLatestVersionId,
        isReadOnly,
        setIsReadOnly,
        selectedTable,
        setSelectedTable,
        refreshTableCountRef,
        refreshTableCount,
      }}
    >
      {children}
    </DatabaseContext.Provider>
  );
}

export function useDatabase() {
  const ctx = useContext(DatabaseContext);
  if (ctx === undefined) {
    throw new Error('useDatabase must be used within DatabaseProvider');
  }
  return ctx;
}

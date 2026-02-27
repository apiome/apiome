'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

export interface SelectedTable {
  classSchemaId: string;
  className: string;
}

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
}

const DatabaseContext = createContext<DatabaseContextType | undefined>(undefined);

export function DatabaseProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [latestVersionId, setLatestVersionId] = useState<string | null>(null);
  const [isReadOnly, setIsReadOnly] = useState<boolean>(false);
  const [selectedTable, setSelectedTable] = useState<SelectedTable | null>(null);

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

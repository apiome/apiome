'use client';

import '../../globals.css';
import * as React from 'react';
import { DatabaseProvider, useDatabase } from './DatabaseContext';
import DatabaseHeader from './components/DatabaseHeader';
import TablesSidebar from './components/TablesSidebar';
import { ADE_SUBHEADER_RESERVE_PX } from '../constants/subheader-layout';

function DatabaseLayoutInner({ children }: { children: React.ReactNode }) {
  const { selectedProjectId, selectedVersionId } = useDatabase();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 48px)' }}>
      <DatabaseHeader />
      <div
        style={{
          display: 'flex',
          flex: 1,
          overflow: 'hidden',
          marginTop: ADE_SUBHEADER_RESERVE_PX,
        }}
      >
        {selectedProjectId && selectedVersionId && <TablesSidebar />}
        <main
          style={{
            flex: 1,
            overflow: 'hidden',
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

export default function DatabaseLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <DatabaseProvider>
      <DatabaseLayoutInner>{children}</DatabaseLayoutInner>
    </DatabaseProvider>
  );
}

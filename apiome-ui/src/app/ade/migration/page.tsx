'use client';

import { useState } from 'react';
import { useMigration } from './MigrationContext';
import { GitCompare, Palette, ClipboardList, CalendarClock } from 'lucide-react';
import { EmptyState } from '../../components/ui/EmptyState';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/Tabs';
import MigrationCanvas from './components/MigrationCanvas';
import DataInspectionView from './components/DataInspectionView';
import MigrationPlanView from './components/MigrationPlanView';
import MigrationSchedulerView from './components/MigrationSchedulerView';

export default function MigrationPage() {
  const { selectedProjectId, fromVersionId, toVersionId } = useMigration();
  const [activeTab, setActiveTab] = useState<'designer' | 'explorer' | 'scheduler'>('designer');

  const hasSelection = selectedProjectId && fromVersionId && toVersionId;
  const fromToSame = fromVersionId && toVersionId && fromVersionId === toVersionId;
  const showCanvas = hasSelection && !fromToSame;

  if (showCanvas) {
    return (
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'designer' | 'explorer' | 'scheduler')} className="h-full flex flex-col min-h-0">
        <TabsList className="w-full shrink-0 flex-nowrap">
          <TabsTrigger value="designer">
            <Palette className="h-4 w-4" />
            Designer
          </TabsTrigger>
          <TabsTrigger value="explorer">
            <ClipboardList className="h-4 w-4" />
            Explorer
          </TabsTrigger>
          <TabsTrigger value="scheduler">
            <CalendarClock className="h-4 w-4" />
            Scheduler
          </TabsTrigger>
        </TabsList>
        <TabsContent value="designer" className="flex-1 flex flex-col min-h-0 mt-0 data-[state=inactive]:hidden">
          <div className="flex-1 min-h-0">
            <MigrationCanvas />
          </div>
          <div className="flex-1 min-h-0">
            <DataInspectionView />
          </div>
        </TabsContent>
        <TabsContent value="explorer" className="flex-1 min-h-0 mt-0 data-[state=inactive]:hidden overflow-auto">
          <MigrationPlanView />
        </TabsContent>
        <TabsContent value="scheduler" className="flex-1 min-h-0 mt-0 data-[state=inactive]:hidden overflow-auto">
          <MigrationSchedulerView />
        </TabsContent>
      </Tabs>
    );
  }

  // The shared honeycomb empty state (DESIGN.md §10, HIVE-10.4). Only two states reach here:
  // nothing chosen yet, or the same version picked on both sides.
  return (
    <div className="flex h-full items-center justify-center p-6">
      {fromToSame ? (
        <EmptyState
          icon={<GitCompare aria-hidden />}
          title="Pick two different versions"
          description="From and to are the same version. Change the target in the header."
          data-testid="migration-same-versions"
        />
      ) : (
        <EmptyState
          icon={<GitCompare aria-hidden />}
          title="No project selected"
          description="Pick a project and two frozen versions in the header to begin."
          data-testid="migration-no-selection"
        />
      )}
    </div>
  );
}

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Edit2, Loader2 } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Alert } from '@/app/components/ui/Alert';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { EmptyState } from '@/app/components/ui/EmptyState';
import {
  dashboardContentStackClass,
  dashboardMainClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { DetailHeader } from '@/app/components/ade/dashboard/projectDetail/DetailHeader';
import {
  DetailTabs,
  PROJECT_DETAIL_TABS,
  type ProjectDetailTab,
} from '@/app/components/ade/dashboard/projectDetail/DetailTabs';
import { OverviewTab } from '@/app/components/ade/dashboard/projectDetail/OverviewTab';
import { SettingsTab } from '@/app/components/ade/dashboard/projectDetail/SettingsTab';
import { VersionsTab } from '@/app/components/ade/dashboard/projectDetail/VersionsTab';
import { ClassesTab } from '@/app/components/ade/dashboard/projectDetail/ClassesTab';
import { ClassesGraphView } from '@/app/components/ade/dashboard/projectDetail/ClassesGraphView';
import { PropertiesTab } from '@/app/components/ade/dashboard/projectDetail/PropertiesTab';
import { PublishedTab } from '@/app/components/ade/dashboard/projectDetail/PublishedTab';
import { ActivityTab } from '@/app/components/ade/dashboard/projectDetail/ActivityTab';
import type { Project } from '@/app/components/ade/dashboard/projectTypes';

function parseTab(value: string | null): ProjectDetailTab {
  if (value && (PROJECT_DETAIL_TABS as readonly string[]).includes(value)) {
    return value as ProjectDetailTab;
  }
  return 'overview';
}

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = params?.id;

  const activeTab = parseTab(searchParams.get('tab'));
  const isGraphView = activeTab === 'classes' && searchParams.get('view') === 'graph';

  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [tabCounts, setTabCounts] = useState<Partial<Record<ProjectDetailTab, number | null>>>({});

  const setCount = useCallback((tab: ProjectDetailTab) => (count: number | null) => {
    setTabCounts((prev) => (prev[tab] === count ? prev : { ...prev, [tab]: count }));
  }, []);

  const loadProject = useCallback(async () => {
    if (!projectId) return;
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}`);
      if (response.status === 404) {
        setProject(null);
        setLoadError('Project not found');
        return;
      }
      if (!response.ok) {
        throw new Error(`Failed to load project (${response.status})`);
      }
      const data = await response.json();
      if (!data.success) {
        throw new Error(data.error || 'Failed to load project');
      }
      setProject(data.project as Project);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Failed to load project');
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  const headerActions = useMemo(() => {
    if (!project) return null;
    if (activeTab !== 'overview') {
      return null;
    }
    return (
      <Button
        size="sm"
        variant="outline"
        onClick={() =>
          router.push(`/ade/dashboard/projects/${project.id}?tab=settings`)
        }
      >
        <Edit2 className="w-4 h-4 mr-1.5" /> Edit
      </Button>
    );
  }, [activeTab, project, router]);

  if (isLoading) {
    return (
      <main className={dashboardMainClass}>
        <LoadingState message="Loading project…" />
      </main>
    );
  }

  if (loadError || !project) {
    return (
      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          <Alert variant="error">{loadError || 'Project not available'}</Alert>
          <EmptyState
            icon={<Loader2 className="w-8 h-8" />}
            title="Project not available"
            description="This project may have been deleted or you may not have access."
            action={
              <Button onClick={() => router.push('/ade/dashboard/projects')}>
                Back to projects
              </Button>
            }
          />
        </div>
      </main>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <DetailHeader project={project} actions={headerActions}>
        <DetailTabs projectId={project.id} active={activeTab} counts={tabCounts} />
      </DetailHeader>

      <main className={dashboardMainClass}>
        {activeTab === 'overview' ? <OverviewTab project={project} /> : null}

        {activeTab === 'versions' ? (
          <VersionsTab projectId={project.id} onCountChange={setCount('versions')} />
        ) : null}

        {activeTab === 'classes' && !isGraphView ? (
          <ClassesTab projectId={project.id} onCountChange={setCount('classes')} />
        ) : null}

        {activeTab === 'classes' && isGraphView ? (
          <ClassesGraphView projectId={project.id} />
        ) : null}

        {activeTab === 'properties' ? (
          <PropertiesTab projectId={project.id} onCountChange={setCount('properties')} />
        ) : null}

        {activeTab === 'settings' ? (
          <SettingsTab
            project={project}
            onSaved={(updated) => {
              setProject((prev) => (prev ? { ...prev, ...updated } : prev));
              void loadProject();
            }}
            onDeleted={() => router.push('/ade/dashboard/projects')}
          />
        ) : null}

        {activeTab === 'published' ? <PublishedTab /> : null}

        {activeTab === 'activity' ? <ActivityTab /> : null}
      </main>
    </div>
  );
}

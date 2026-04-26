'use client';

import Link from 'next/link';
import { useSession } from 'next-auth/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  Clock,
  Edit2,
  FileText,
  FolderOpen,
  Folders,
  Gauge,
  LayoutGrid,
  List as ListIcon,
  Lock,
  MoreVertical,
  Plus,
  Search,
  Sparkles,
  Trash2,
  TrendingUp,
  Upload,
} from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { EmptyState } from '../../../components/ui/EmptyState';
import { Skeleton } from '../../../components/ui/Skeleton';
import { toast } from 'sonner';
import { deleteProject, permanentDeleteProject } from '../../../../../lib/db/helper';
import { cn } from '../../../../../lib/utils';
import ImportDialog from '../../../components/ade/dashboard/ImportDialog';
import { ProjectWizardDialog } from '../../../components/ade/dashboard/ProjectWizardDialog';
import { useDialog } from '../../../components/providers/DialogProvider';
import { getProjectDomainCategoryLabel } from '../../../utils/project-domain-categories';
import { getProjectQualityHistory } from '../../../utils/project-quality-score-history';
import { getNumericScoreTier } from '../../../utils/numeric-score-tier';
import { ProjectQualityTrendSparkline } from '../../../components/ade/dashboard/ProjectQualityTrendSparkline';
import { ProjectQualityHistoryDialog } from '../../../components/ade/dashboard/ProjectQualityHistoryDialog';
import { ProjectKpiCard } from '../../../components/ade/dashboard/ProjectKpiCard';
import { ProjectStatusChip, type ProjectStatusKind } from '../../../components/ade/dashboard/ProjectStatusChip';
import { deriveProjectKpis } from '../../../components/ade/dashboard/projectListKpis';
import type { Project } from '../../../components/ade/dashboard/projectTypes';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  projectAvatarGradientClasses,
  projectHeaderEyebrowClass,
  projectHeaderIconTileClass,
  projectHeaderShellClass,
  projectPanelClass,
  projectPanelHeaderClass,
  projectStatusChipBaseClass,
  projectStatusChipToneClass,
  repositoryKpiCardClass,
} from '../../../components/ade/dashboard/dashboardScreenClasses';

type ViewFilter = 'all' | 'mine' | 'recent' | 'attention' | 'disabled';
type SortValue =
  | 'updated-desc'
  | 'updated-asc'
  | 'created-desc'
  | 'name-asc'
  | 'name-desc'
  | 'quality-desc';
type GroupBy = 'none' | 'domain';
type LayoutMode = 'cards' | 'table';

const SORT_OPTIONS: { value: SortValue; label: string }[] = [
  { value: 'updated-desc', label: 'Last activity ↓' },
  { value: 'updated-asc', label: 'Last activity ↑' },
  { value: 'created-desc', label: 'Newest first' },
  { value: 'name-asc', label: 'Name A → Z' },
  { value: 'name-desc', label: 'Name Z → A' },
  { value: 'quality-desc', label: 'Quality ↓' },
];

const RECENT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

function avatarInitials(name: string): string {
  const cleaned = name.trim();
  if (!cleaned) return '··';
  const words = cleaned.split(/[\s_\-/]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const compact = cleaned.replace(/[^a-zA-Z0-9]/g, '');
  return (compact.slice(0, 2) || '··').toUpperCase();
}

function avatarGradient(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return projectAvatarGradientClasses[hash % projectAvatarGradientClasses.length];
}

function relativeTime(iso: string): string {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return '—';
  const diff = Date.now() - ts;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months} mo ago`;
  return `${Math.round(months / 12)} y ago`;
}

function deriveProjectStatusKinds(
  project: Project,
  qualityScore: number | undefined
): ProjectStatusKind[] {
  if (project.deleted_at) return ['deleted'];
  const kinds: ProjectStatusKind[] = [project.enabled ? 'enabled' : 'disabled'];
  if (qualityScore != null && qualityScore < 70) kinds.push('attention');
  return kinds;
}

/** Local view of the next-auth session user. The auth callbacks decorate the
 * user object with these fields but the official type doesn't reflect that
 * yet; declaring it here keeps the file `any`-free without touching the
 * shared next-auth type augmentation. */
type SessionUserExtensions = {
  current_tenant_id?: string;
  user_id?: string;
};

type ProjectsPageSkeletonMode = 'full' | 'main';

function ProjectsPageSkeleton({ mode }: { mode: ProjectsPageSkeletonMode }) {
  const kpi = (
    <section aria-label="Project KPIs" className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={cn(repositoryKpiCardClass, 'p-4 space-y-2')}>
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-8 w-12" />
          <Skeleton className="h-3 w-28" />
        </div>
      ))}
    </section>
  );

  const filters = (
    <section className="flex items-center gap-2 flex-wrap" aria-hidden="true">
      <Skeleton className="h-4 w-10" />
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-7 w-20 rounded-full" />
      ))}
      <div className="ml-auto flex items-center gap-2">
        <Skeleton className="h-5 w-14" />
        <Skeleton className="h-7 w-[7.5rem]" />
        <Skeleton className="h-5 w-8" />
        <Skeleton className="h-7 w-[7.5rem]" />
      </div>
    </section>
  );

  const projectCards = (
    <div className="space-y-6" aria-hidden="true">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {Array.from({ length: 6 }).map((_, i) => (
          <article
            key={i}
            className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col"
          >
            <div className="p-5 space-y-4">
              <div className="flex items-start gap-3">
                <Skeleton className="h-12 w-12 rounded-lg shrink-0" />
                <div className="flex-1 min-w-0 space-y-2.5">
                  <Skeleton className="h-4 w-[85%] max-w-[12rem]" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <Skeleton className="h-6 w-6 rounded shrink-0" />
              </div>
              <div className="flex gap-2">
                <Skeleton className="h-5 w-20 rounded" />
                <Skeleton className="h-5 w-24 rounded" />
                <Skeleton className="h-5 w-12 rounded" />
              </div>
            </div>
            <div className="p-3 border-t border-gray-100 dark:border-gray-700/80 space-y-2.5 bg-gray-50/50 dark:bg-gray-900/30">
              <div className="flex justify-between gap-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
          </article>
        ))}
        <div className="min-h-[180px] rounded-lg border-2 border-dashed border-gray-200 dark:border-gray-700" />
      </div>
    </div>
  );

  const lowerPanels = (
    <section className="grid grid-cols-1 gap-6 lg:grid-cols-3" aria-hidden="true">
      <div className={`${projectPanelClass} lg:col-span-2`}>
        <div className={`${projectPanelHeaderClass} space-y-2`}>
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3 w-72" />
        </div>
        <div className="p-5 space-y-3">
          <Skeleton className="h-24 w-full rounded-md" />
          <div className="flex gap-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-20" />
          </div>
        </div>
      </div>
      <div className={projectPanelClass}>
        <div className={`${projectPanelHeaderClass} space-y-2`}>
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-24" />
        </div>
        <div className="p-5">
          <Skeleton className="h-28 w-full rounded-md" />
        </div>
      </div>
    </section>
  );

  if (mode === 'main') {
    return (
      <>
        <span className="sr-only" role="status" aria-live="polite">
          Loading projects
        </span>
        {kpi}
        {filters}
        {projectCards}
        {lowerPanels}
      </>
    );
  }

  const main = (
    <div className={cn(dashboardContentStackClass, 'min-h-[320px]')}>
      {kpi}
      {filters}
      {projectCards}
      {lowerPanels}
    </div>
  );

  return (
    <>
      <span className="sr-only">Loading projects</span>
      <header className={projectHeaderShellClass}>
        <div className="px-6 py-4 flex items-end justify-between gap-4 flex-wrap">
          <div className="flex min-w-0 items-center gap-3">
            <span className={projectHeaderIconTileClass} aria-hidden="true">
              <Folders className="w-5 h-5" />
            </span>
            <div className="min-w-0">
              <h2 className="text-2xl font-bold leading-tight text-gray-900 dark:text-white">Projects</h2>
              <div className={`${projectHeaderEyebrowClass} max-w-sm`} aria-hidden="true">
                <Skeleton className="h-3.5 w-64" />
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2" aria-hidden="true">
            <Skeleton className="h-8 w-24 rounded-md" />
            <Skeleton className="h-7 w-24 rounded-md" />
            <Skeleton className="h-7 w-16 rounded-md" />
            <Skeleton className="h-8 w-20 rounded-md" />
          </div>
        </div>
      </header>
      <main className={dashboardMainClass} role="status" aria-live="polite">
        {main}
      </main>
    </>
  );
}

const Projects = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();

  const [projects, setProjects] = useState<Project[]>([]);
  const [isInitialLoading, setIsInitialLoading] = useState(true);

  const [showWizard, setShowWizard] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [openProjectDropdown, setOpenProjectDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);

  const [qualityHistoryEpoch, setQualityHistoryEpoch] = useState(0);
  const [qualityTrendProject, setQualityTrendProject] = useState<Project | null>(null);
  const prevImportOpen = useRef(false);

  const [search, setSearch] = useState('');
  const [activeView, setActiveView] = useState<ViewFilter>('all');
  const [sortValue, setSortValue] = useState<SortValue>('updated-desc');
  const [groupBy, setGroupBy] = useState<GroupBy>('none');
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('cards');

  const sessionUser = session?.user as SessionUserExtensions | undefined;
  const currentTenantId = sessionUser?.current_tenant_id;
  const currentUserId = sessionUser?.user_id;

  const loadProjects = useCallback(async () => {
    if (!currentTenantId) return;
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) {
        throw new Error(`Failed to fetch projects: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.projects) {
        setProjects(data.projects);
      } else {
        throw new Error(data.error || 'Failed to load projects');
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
      setProjects([]);
    } finally {
      setIsInitialLoading(false);
    }
  }, [currentTenantId]);

  useEffect(() => {
    if (currentTenantId) void loadProjects();
  }, [currentTenantId, loadProjects]);

  useEffect(() => {
    if (prevImportOpen.current && !showImport) {
      setQualityHistoryEpoch((e) => e + 1);
    }
    prevImportOpen.current = showImport;
  }, [showImport]);

  const projectQualityHistoryCacheRef = useRef<Record<string, ReturnType<typeof getProjectQualityHistory>>>({});
  const projectQualityHistoryCacheEpochRef = useRef(qualityHistoryEpoch);

  const projectQualityHistoryMap = useMemo(() => {
    if (projectQualityHistoryCacheEpochRef.current !== qualityHistoryEpoch) {
      projectQualityHistoryCacheRef.current = {};
      projectQualityHistoryCacheEpochRef.current = qualityHistoryEpoch;
    }

    const cache = projectQualityHistoryCacheRef.current;
    const m: Record<string, ReturnType<typeof getProjectQualityHistory>> = {};

    for (const p of projects) {
      if (!(p.id in cache)) {
        cache[p.id] = getProjectQualityHistory(p.id);
      }
      m[p.id] = cache[p.id];
    }
    return m;
  }, [projects, qualityHistoryEpoch]);

  const handleImportSuccess = useCallback(async () => {
    await loadProjects();
    setQualityHistoryEpoch((e) => e + 1);
  }, [loadProjects]);

  const handleDelete = async (projectId: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Project',
      message: 'Are you sure you want to delete this project? This action cannot be undone.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    try {
      const result = await deleteProject(projectId);
      const response = JSON.parse(result);
      if (response.success) await loadProjects();
      else await alertDialog({ message: response.error || 'Failed to delete project', variant: 'error' });
    } catch (error) {
      await alertDialog({ message: error instanceof Error ? error.message : 'An error occurred', variant: 'error' });
    }
  };

  const handlePermanentDelete = async (project: Project) => {
    const confirmed = await confirmDialog({
      title: 'Permanently Delete Project',
      message: `Are you absolutely sure you want to permanently delete "${project.name}"?\n\nThis will permanently delete:\n• All versions of this project\n• All publications associated with those versions\n• All classes and their properties\n• All properties directly linked to this project\n\nThis action CANNOT be undone and all data will be lost forever.`,
      variant: 'danger',
      confirmLabel: 'Permanently Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    const doubleConfirmed = await confirmDialog({
      title: 'Final Confirmation',
      message: `Type "DELETE" mentally and confirm: You are about to permanently destroy all data for project "${project.name}". This is your last chance to cancel.`,
      variant: 'danger',
      confirmLabel: 'Yes, Delete Everything',
      cancelLabel: 'Cancel',
    });
    if (!doubleConfirmed) return;

    try {
      const result = await permanentDeleteProject(project.id);
      const response = JSON.parse(result);
      if (response.success) {
        toast.success('Project and all associated data have been permanently deleted.');
        await loadProjects();
      } else {
        await alertDialog({ message: response.error || 'Failed to permanently delete project', variant: 'error' });
      }
    } catch (error) {
      await alertDialog({ message: error instanceof Error ? error.message : 'An error occurred', variant: 'error' });
    }
  };

  const kpis = useMemo(
    () => deriveProjectKpis(projects, projectQualityHistoryMap),
    [projects, projectQualityHistoryMap]
  );

  const viewCounts = useMemo(() => {
    const now = Date.now();
    const recent = projects.filter((p) => Date.now() - Date.parse(p.updated_at) <= RECENT_WINDOW_MS).length;
    const mine = projects.filter((p) => p.creator_id === currentUserId).length;
    const disabledCount = projects.filter((p) => !p.enabled && !p.deleted_at).length;
    void now;
    return {
      all: projects.length,
      mine,
      recent,
      attention: kpis.attention,
      disabled: disabledCount,
    };
  }, [projects, currentUserId, kpis.attention]);

  const filteredProjects = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projects.filter((project) => {
      if (q) {
        const haystack = [
          project.name,
          project.slug ?? '',
          project.description ?? '',
          project.metadata?.summary ?? '',
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (activeView === 'mine' && project.creator_id !== currentUserId) return false;
      if (
        activeView === 'recent' &&
        Date.now() - Date.parse(project.updated_at) > RECENT_WINDOW_MS
      )
        return false;
      if (activeView === 'attention') {
        const score = kpis.latestQuality[project.id];
        if (score == null || score >= 70) return false;
      }
      if (activeView === 'disabled' && (project.enabled || project.deleted_at)) return false;
      return true;
    });
  }, [projects, search, activeView, currentUserId, kpis.latestQuality]);

  const sortedProjects = useMemo(() => {
    const arr = [...filteredProjects];
    arr.sort((a, b) => {
      switch (sortValue) {
        case 'updated-asc':
          return Date.parse(a.updated_at) - Date.parse(b.updated_at);
        case 'created-desc':
          return Date.parse(b.created_at) - Date.parse(a.created_at);
        case 'name-asc':
          return a.name.localeCompare(b.name);
        case 'name-desc':
          return b.name.localeCompare(a.name);
        case 'quality-desc': {
          const aq = kpis.latestQuality[a.id] ?? -1;
          const bq = kpis.latestQuality[b.id] ?? -1;
          return bq - aq;
        }
        case 'updated-desc':
        default:
          return Date.parse(b.updated_at) - Date.parse(a.updated_at);
      }
    });
    return arr;
  }, [filteredProjects, sortValue, kpis.latestQuality]);

  const groupedProjects = useMemo(() => {
    if (groupBy === 'none') {
      return [{ key: '__all', label: '', items: sortedProjects }];
    }
    const buckets = new Map<string, Project[]>();
    for (const project of sortedProjects) {
      const key = project.metadata?.domainCategory ?? '__none';
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(project);
    }
    return Array.from(buckets.entries())
      .map(([key, items]) => ({
        key,
        label: key === '__none' ? 'No domain' : getProjectDomainCategoryLabel(key) ?? key,
        items,
      }))
      .sort((a, b) => {
        if (a.key === '__none') return 1;
        if (b.key === '__none') return -1;
        return a.label.localeCompare(b.label);
      });
  }, [sortedProjects, groupBy]);

  const portfolioTrend = useMemo(() => {
    const series = kpis.qualitySeries;
    const populated = series.filter((v) => v > 0);
    if (populated.length < 2) return null;
    const firstPopulatedIdx = series.findIndex((v) => v > 0);
    const lastIdx = series.length - 1;
    const start = series[firstPopulatedIdx];
    const end = series[lastIdx];
    return {
      series,
      delta: end - start,
      latest: end,
      best: kpis.best,
      worst: kpis.worst,
    };
  }, [kpis.qualitySeries, kpis.best, kpis.worst]);

  const headerEyebrowParts: string[] = [];
  headerEyebrowParts.push(`${kpis.total} ${kpis.total === 1 ? 'project' : 'projects'}`);
  if (kpis.enabled !== kpis.total) headerEyebrowParts.push(`${kpis.enabled} enabled`);
  if (kpis.avgQuality != null) headerEyebrowParts.push(`avg quality ${kpis.avgQuality}`);
  if (kpis.attention > 0) headerEyebrowParts.push(`${kpis.attention} need attention`);
  const headerEyebrow = headerEyebrowParts.join(' · ');

  if (!session) {
    return <ProjectsPageSkeleton mode="full" />;
  }

  if (!currentTenantId) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <Lock className="h-6 w-6 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-1" />
            <div>
              <h2 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100 mb-2">No Tenant Selected</h2>
              <p className="text-yellow-800 dark:text-yellow-200 mb-3">Please select a tenant before managing projects.</p>
              <Button asChild><a href="/ade/dashboard/tenants">Go to Tenants</a></Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <header className={projectHeaderShellClass}>
        <div className="px-6 py-4 flex items-end justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <span className={projectHeaderIconTileClass} aria-hidden="true">
              <Folders className="w-5 h-5" />
            </span>
            <div className="min-w-0">
              <h2 className="text-2xl font-bold leading-tight text-gray-900 dark:text-white">Projects</h2>
              {isInitialLoading ? (
                <div className={`${projectHeaderEyebrowClass} max-w-sm`} aria-hidden="true">
                  <Skeleton className="h-3.5 w-64" />
                </div>
              ) : (
                <p className={`${projectHeaderEyebrowClass} truncate`}>{headerEyebrow}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <div className="hidden md:flex items-center gap-2 h-8 px-2.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-xs">
              <Search className="w-3.5 h-3.5 text-gray-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="bg-transparent outline-none w-44 placeholder:text-gray-400"
                placeholder="Filter projects…"
                aria-label="Filter projects"
              />
            </div>
            <div className="flex items-center gap-1 border border-gray-200 dark:border-gray-700 rounded-md p-0.5">
              <button
                type="button"
                onClick={() => setLayoutMode('cards')}
                className={`px-2 py-1 rounded text-xs font-medium inline-flex items-center gap-1 ${
                  layoutMode === 'cards'
                    ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                    : 'text-gray-500 hover:text-indigo-500'
                }`}
                aria-pressed={layoutMode === 'cards'}
              >
                <LayoutGrid className="w-3.5 h-3.5" /> Cards
              </button>
              <button
                type="button"
                onClick={() => setLayoutMode('table')}
                className={`px-2 py-1 rounded text-xs font-medium inline-flex items-center gap-1 ${
                  layoutMode === 'table'
                    ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                    : 'text-gray-500 hover:text-indigo-500'
                }`}
                aria-pressed={layoutMode === 'table'}
              >
                <ListIcon className="w-3.5 h-3.5" /> Table
              </button>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowImport(true)}
              disabled={!currentTenantId}
              title={!currentTenantId ? 'Please select a tenant first' : 'Import specification'}
            >
              <Upload className="w-4 h-4" />
              Import
            </Button>
            <Button size="sm" onClick={() => setShowWizard(true)}>
              <Plus className="w-4 h-4" />
              New project
            </Button>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          {isInitialLoading ? (
            <ProjectsPageSkeleton mode="main" />
          ) : (
            <>
              <section
                aria-label="Project KPIs"
                className="grid grid-cols-2 md:grid-cols-4 gap-4"
              >
                <ProjectKpiCard
                  label="Total projects"
                  value={kpis.total}
                  subtitle={
                    kpis.total === 0
                      ? 'No projects yet'
                      : `${kpis.enabled} enabled · ${kpis.disabled} disabled`
                  }
                  tone="indigo"
                  icon={<Folders className="w-4 h-4" />}
                  sparkline={kpis.arrivalsSeries.some((n) => n > 0) ? kpis.arrivalsSeries : undefined}
                />
                <ProjectKpiCard
                  label="Avg quality"
                  value={kpis.avgQuality ?? '—'}
                  subtitle={
                    kpis.avgQuality == null
                      ? 'Import a spec to record a snapshot'
                      : portfolioTrend && portfolioTrend.delta !== 0
                        ? `${portfolioTrend.delta > 0 ? '+' : ''}${portfolioTrend.delta} pts vs ${kpis.qualitySeries.length}w ago`
                        : 'Steady this window'
                  }
                  subtitleTone={
                    portfolioTrend && portfolioTrend.delta > 0
                      ? 'positive'
                      : portfolioTrend && portfolioTrend.delta < 0
                        ? 'negative'
                        : 'default'
                  }
                  subtitleIcon={
                    portfolioTrend && portfolioTrend.delta > 0
                      ? <TrendingUp className="w-3 h-3" />
                      : portfolioTrend && portfolioTrend.delta < 0
                        ? <AlertOctagon className="w-3 h-3" />
                        : undefined
                  }
                  tone={kpis.avgQuality != null && kpis.avgQuality >= 70 ? 'emerald' : 'amber'}
                  icon={<Gauge className="w-4 h-4" />}
                  sparkline={
                    kpis.qualitySeries.some((v) => v > 0)
                      ? kpis.qualitySeries.map((v) => (v === 0 ? (kpis.avgQuality ?? 0) : v))
                      : undefined
                  }
                />
                <ProjectKpiCard
                  label="Needs attention"
                  value={kpis.attention}
                  subtitle={
                    kpis.attention === 0
                      ? 'All measured projects ≥ 70'
                      : 'Quality below 70 — review and improve'
                  }
                  subtitleTone={kpis.attention > 0 ? 'warning' : 'default'}
                  tone={kpis.attention > 0 ? 'amber' : 'slate'}
                  icon={<AlertTriangle className="w-4 h-4" />}
                />
                <ProjectKpiCard
                  label="Updated · 24 h"
                  value={kpis.recentlyUpdated}
                  subtitle={
                    kpis.recentlyUpdated === 0
                      ? 'No recent edits'
                      : `${kpis.recentlyUpdated} active in the last day`
                  }
                  tone="sky"
                  icon={<Activity className="w-4 h-4" />}
                />
              </section>

              <section className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] uppercase tracking-wider text-gray-500 mr-1">Views</span>
                <ViewChip
                  active={activeView === 'all'}
                  onClick={() => setActiveView('all')}
                  label="All"
                  count={viewCounts.all}
                />
                <ViewChip
                  active={activeView === 'mine'}
                  onClick={() => setActiveView('mine')}
                  label="Owned by me"
                  count={viewCounts.mine}
                />
                <ViewChip
                  active={activeView === 'recent'}
                  onClick={() => setActiveView('recent')}
                  label="Recently active"
                  count={viewCounts.recent}
                />
                <ViewChip
                  active={activeView === 'attention'}
                  onClick={() => setActiveView('attention')}
                  label="Needs attention"
                  count={viewCounts.attention}
                  tone="amber"
                />
                <ViewChip
                  active={activeView === 'disabled'}
                  onClick={() => setActiveView('disabled')}
                  label="Disabled"
                  count={viewCounts.disabled}
                />

                <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
                  <label className="flex items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Group</span>
                    <select
                      value={groupBy}
                      onChange={(e) => setGroupBy(e.target.value as GroupBy)}
                      className="h-7 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-xs"
                    >
                      <option value="none">None</option>
                      <option value="domain">Domain</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Sort</span>
                    <select
                      value={sortValue}
                      onChange={(e) => setSortValue(e.target.value as SortValue)}
                      className="h-7 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-xs"
                    >
                      {SORT_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </section>

              {sortedProjects.length === 0 ? (
                <div className={projectPanelClass}>
                  <div className="p-8">
                    <EmptyState
                      icon={<FolderOpen className="h-10 w-10" />}
                      title={projects.length === 0 ? 'No projects yet' : 'No projects match this view'}
                      description={
                        projects.length === 0
                          ? 'Create your first project from a template, an OpenAPI import, or AI-assisted design.'
                          : 'Adjust the filter chips or clear the search box to see more.'
                      }
                      variant="compact"
                      showOrbs={false}
                      iconContainerClassName="from-indigo-500 to-purple-600 shadow-indigo-500/30"
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-6">
                  {groupedProjects.map((group) => (
                    <div key={group.key} className="space-y-3">
                      {group.label && (
                        <div className="flex items-center justify-between">
                          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 inline-flex items-center gap-2">
                            <span className={`${projectStatusChipBaseClass} ${projectStatusChipToneClass.domain}`}>
                              {group.label}
                            </span>
                            <span className="text-gray-400 font-mono">{group.items.length}</span>
                          </h3>
                        </div>
                      )}
                      {layoutMode === 'cards' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                          {group.items.map((project) => (
                            <ProjectCard
                              key={project.id}
                              project={project}
                              qualityScore={kpis.latestQuality[project.id]}
                              qualityHistory={projectQualityHistoryMap[project.id] ?? []}
                              onOpenQualityHistory={() => setQualityTrendProject(project)}
                              dropdownOpen={openProjectDropdown === project.id}
                              dropdownPosition={openProjectDropdown === project.id ? dropdownPosition : null}
                              onOpenDropdown={(rect) => {
                                setDropdownPosition({
                                  top: rect.bottom + 4,
                                  right: window.innerWidth - rect.right,
                                });
                                setOpenProjectDropdown(project.id);
                              }}
                              onCloseDropdown={() => setOpenProjectDropdown(null)}
                              onDelete={() => handleDelete(project.id)}
                              onPermanentDelete={() => handlePermanentDelete(project)}
                            />
                          ))}
                          {group.key === '__all' || groupedProjects.length === 1 ? (
                            <button
                              type="button"
                              onClick={() => setShowWizard(true)}
                              className="border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-lg p-6 flex flex-col items-center justify-center text-center hover:border-indigo-400 hover:bg-indigo-500/5 transition-colors min-h-[300px]"
                            >
                              <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-sm">
                                <Plus className="w-6 h-6 text-white" />
                              </div>
                              <h3 className="mt-3 text-lg font-semibold text-gray-900 dark:text-gray-100">Start a new project</h3>
                              <p className="mt-1.5 text-sm text-gray-500 max-w-xs">
                                Create from a template, import an OpenAPI spec, or design with AI.
                              </p>
                              <span className="mt-4 inline-flex items-center gap-1.5 text-[11px] text-indigo-600 dark:text-indigo-400">
                                Open the wizard
                                <ArrowRight className="w-3 h-3" />
                              </span>
                            </button>
                          ) : null}
                        </div>
                      ) : (
                        <ProjectsTable
                          projects={group.items}
                          qualityHistoryMap={projectQualityHistoryMap}
                          latestQuality={kpis.latestQuality}
                          onOpenQualityHistory={(p) => setQualityTrendProject(p)}
                          onDelete={(id) => handleDelete(id)}
                          onPermanentDelete={(p) => handlePermanentDelete(p)}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}

              <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className={`${projectPanelClass} lg:col-span-2`}>
                  <div className={`${projectPanelHeaderClass} flex items-center justify-between`}>
                    <div className="flex items-center gap-3">
                      <TrendingUp className="w-5 h-5 text-indigo-500" />
                      <div>
                        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                          Portfolio quality trend
                        </h3>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          Average quality across projects with recorded snapshots · last 8 weeks
                        </p>
                      </div>
                    </div>
                  </div>
                  <div className="p-5">
                    {portfolioTrend ? (
                      <PortfolioTrendChart
                        series={portfolioTrend.series}
                        latest={portfolioTrend.latest}
                        delta={portfolioTrend.delta}
                        best={portfolioTrend.best}
                        worst={portfolioTrend.worst}
                      />
                    ) : (
                      <EmptyState
                        icon={<Sparkles className="h-8 w-8" />}
                        title="Not enough quality history"
                        description="Quality snapshots are recorded when you import an OpenAPI spec. Run an import on at least one project to start tracking the portfolio trend."
                        variant="compact"
                        showOrbs={false}
                      />
                    )}
                  </div>
                </div>

                <div className={`${projectPanelClass} flex flex-col`}>
                  <div className={`${projectPanelHeaderClass} flex items-center gap-3`}>
                    <Activity className="w-5 h-5 text-indigo-500" />
                    <div>
                      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Recent activity</h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400">Across all projects</p>
                    </div>
                  </div>
                  <div className="flex-1 p-5">
                    <EmptyState
                      icon={<Clock className="h-8 w-8" />}
                      title="Activity feed coming soon"
                      description="A unified activity log across versions, classes, properties, and publishing events will appear here once the audit pipeline lands."
                      variant="compact"
                      showOrbs={false}
                    />
                  </div>
                </div>
              </section>
            </>
          )}
        </div>
      </main>

      <ProjectQualityHistoryDialog
        open={qualityTrendProject !== null}
        onOpenChange={(open) => {
          if (!open) setQualityTrendProject(null);
        }}
        projectName={qualityTrendProject?.name ?? ''}
        history={qualityTrendProject ? projectQualityHistoryMap[qualityTrendProject.id] ?? [] : []}
      />

      {currentTenantId && currentUserId && (
        <ImportDialog
          open={showImport}
          onClose={() => setShowImport(false)}
          onSuccess={handleImportSuccess}
          tenantId={currentTenantId}
          userId={currentUserId}
        />
      )}

      <ProjectWizardDialog
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreated={async () => {
          await loadProjects();
          setQualityHistoryEpoch((e) => e + 1);
        }}
      />
    </>
  );
};

interface ViewChipProps {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone?: 'indigo' | 'amber';
}

function ViewChip({ active, onClick, label, count, tone = 'indigo' }: ViewChipProps) {
  const inactiveBase =
    'border border-gray-200 dark:border-gray-700 hover:border-indigo-300 text-gray-600 dark:text-gray-300';
  const activeStyles =
    tone === 'amber'
      ? 'border-amber-300 dark:border-amber-700/40 bg-amber-50/60 dark:bg-amber-500/5 text-amber-700 dark:text-amber-300'
      : 'border-indigo-300 dark:border-indigo-700/60 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-medium';
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1 text-xs rounded-full inline-flex items-center gap-1.5 transition-colors ${
        active ? activeStyles : inactiveBase
      }`}
      aria-pressed={active}
    >
      {tone === 'amber' && active ? <AlertTriangle className="w-3 h-3" /> : null}
      <span>{label}</span>
      <span className="font-mono text-[10px] text-gray-400">{count}</span>
    </button>
  );
}

interface ProjectCardProps {
  project: Project;
  qualityScore: number | undefined;
  qualityHistory: ReturnType<typeof getProjectQualityHistory>;
  onOpenQualityHistory: () => void;
  dropdownOpen: boolean;
  dropdownPosition: { top: number; right: number } | null;
  onOpenDropdown: (rect: DOMRect) => void;
  onCloseDropdown: () => void;
  onDelete: () => void;
  onPermanentDelete: () => void;
}

function ProjectCard({
  project,
  qualityScore,
  qualityHistory,
  onOpenQualityHistory,
  dropdownOpen,
  dropdownPosition,
  onOpenDropdown,
  onCloseDropdown,
  onDelete,
  onPermanentDelete,
}: ProjectCardProps) {
  const detailHref = `/ade/dashboard/projects/${project.id}`;
  const initials = avatarInitials(project.name);
  const gradient = avatarGradient(project.id);
  const tier = qualityScore != null ? getNumericScoreTier(qualityScore) : null;
  const statusKinds = deriveProjectStatusKinds(project, qualityScore);
  const domainLabel = getProjectDomainCategoryLabel(project.metadata?.domainCategory);
  const isAttention = statusKinds.includes('attention');
  const cardBorder = isAttention
    ? 'border-amber-300/70 dark:border-amber-700/40 ring-1 ring-amber-200/60 dark:ring-amber-800/30'
    : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-600';
  const footerBorder = isAttention
    ? 'border-amber-200/60 dark:border-amber-700/40 bg-amber-50/40 dark:bg-amber-900/10'
    : 'border-gray-100 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900/40';

  return (
    <article
      className={`bg-white dark:bg-gray-800 rounded-lg border overflow-hidden transition-colors flex flex-col ${cardBorder}`}
    >
      <div className="p-5 flex-1">
        <div className="flex items-start gap-3">
          <Link
            href={detailHref}
            className={`w-12 h-12 rounded-lg bg-gradient-to-br ${gradient} inline-flex items-center justify-center text-white font-bold font-mono shrink-0 shadow-sm`}
            aria-label={`Open ${project.name}`}
          >
            {initials}
          </Link>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <Link
                href={detailHref}
                className="font-semibold truncate hover:text-indigo-500 text-gray-900 dark:text-gray-100"
              >
                {project.name}
              </Link>
            </div>
            <p className="text-[11px] font-mono text-gray-500 truncate">
              {(project.slug ?? '—')} · <span title={project.id}>{project.id.slice(0, 12)}</span>
            </p>
            <div className="flex items-center gap-1.5 mt-2 flex-wrap">
              {statusKinds.map((kind) => (
                <ProjectStatusChip key={kind} kind={kind} />
              ))}
              {domainLabel ? (
                <span
                  className={`${projectStatusChipBaseClass} ${projectStatusChipToneClass.domain}`}
                  title={domainLabel}
                >
                  {domainLabel}
                </span>
              ) : null}
            </div>
          </div>
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (dropdownOpen) onCloseDropdown();
                else onOpenDropdown((e.currentTarget as HTMLElement).getBoundingClientRect());
              }}
              className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600"
              aria-label="Project actions"
              aria-expanded={dropdownOpen}
            >
              <MoreVertical className="w-4 h-4" />
            </button>
            {dropdownOpen && dropdownPosition ? (
              <>
                <div className="fixed inset-0 z-10" onClick={onCloseDropdown} />
                <div
                  className="fixed w-56 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20"
                  style={{ top: `${dropdownPosition.top}px`, right: `${dropdownPosition.right}px` }}
                >
                  <div className="py-1">
                    <Link
                      href={`${detailHref}?tab=settings`}
                      onClick={onCloseDropdown}
                      className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300"
                    >
                      <Edit2 className="w-4 h-4 text-indigo-500" />
                      Open settings
                    </Link>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCloseDropdown();
                        onDelete();
                      }}
                      className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300"
                    >
                      <Trash2 className="w-4 h-4 text-red-500" />
                      Delete
                    </button>
                    <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCloseDropdown();
                        onPermanentDelete();
                      }}
                      className="w-full px-4 py-2 text-left text-sm hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 text-red-600 dark:text-red-400"
                    >
                      <AlertTriangle className="w-4 h-4" />
                      Permanently delete
                    </button>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
        {project.description ? (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 line-clamp-2">{project.description}</p>
        ) : project.metadata?.summary ? (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 line-clamp-2">{project.metadata.summary}</p>
        ) : (
          <p className="text-xs text-gray-400 dark:text-gray-600 italic mt-3">No description</p>
        )}

        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-[9px] uppercase tracking-wider text-gray-500">Quality</p>
            {tier ? (
              <button
                type="button"
                onClick={onOpenQualityHistory}
                className={`inline-flex items-center justify-center w-11 h-11 rounded-full border-2 mt-1 font-mono text-xs font-semibold ${tier.gaugeStrokeClass.replace('text-', 'border-')} ${tier.textClass}`}
                title="Open quality history"
              >
                {qualityScore}
              </button>
            ) : (
              <span
                className="inline-flex items-center justify-center w-11 h-11 rounded-full border-2 border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-600 mt-1 font-mono text-xs"
                title="No quality snapshots yet"
              >
                —
              </span>
            )}
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-gray-500">Trend</p>
            <div className="w-12 h-8 mx-auto mt-1.5">
              {qualityHistory.length >= 2 ? (
                <ProjectQualityTrendSparkline history={qualityHistory} className="block w-full h-full" />
              ) : (
                <span className="block text-[10px] text-gray-400 mt-2">—</span>
              )}
            </div>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-gray-500">Snapshots</p>
            <div className="inline-flex items-center justify-center w-11 h-11 rounded-full border-2 border-gray-200 dark:border-gray-700 mt-1 font-mono text-xs text-gray-700 dark:text-gray-300">
              {qualityHistory.length}
            </div>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-y-1.5 gap-x-3 text-[11px]">
          <div className="flex items-center gap-1.5 text-gray-500" title={project.creator_email}>
            <span className="w-3 h-3 rounded-full bg-gradient-to-br from-indigo-400 to-purple-400" aria-hidden />
            <span className="truncate">{project.creator_name}</span>
          </div>
          <div className="flex items-center gap-1.5 text-gray-500">
            <Clock className="w-3 h-3" />
            <span>updated {relativeTime(project.updated_at)}</span>
          </div>
          <div className="flex items-center gap-1.5 text-gray-500">
            <Sparkles className="w-3 h-3" />
            <span>created {relativeTime(project.created_at)}</span>
          </div>
          {project.metadata?.license?.identifier ? (
            <div className="flex items-center gap-1.5 text-gray-500">
              <FileText className="w-3 h-3" />
              <span className="font-mono">{project.metadata.license.identifier}</span>
            </div>
          ) : null}
        </dl>
      </div>
      <Link
        href={detailHref}
        className={`px-5 py-2.5 border-t flex items-center justify-between text-xs ${footerBorder} ${
          isAttention
            ? 'text-amber-700 dark:text-amber-300 hover:underline'
            : 'text-gray-500 hover:text-indigo-600'
        }`}
      >
        <span className="flex items-center gap-2">
          <Clock className="w-3 h-3" />
          {isAttention
            ? `attention · quality ${qualityScore ?? '—'}`
            : `updated ${relativeTime(project.updated_at)}`}
        </span>
        <span className="inline-flex items-center gap-1">
          {isAttention ? 'Review' : 'Open'} <ArrowRight className="w-3 h-3" />
        </span>
      </Link>
    </article>
  );
}

interface ProjectsTableProps {
  projects: Project[];
  qualityHistoryMap: Record<string, ReturnType<typeof getProjectQualityHistory>>;
  latestQuality: Record<string, number>;
  onOpenQualityHistory: (project: Project) => void;
  onDelete: (id: string) => void;
  onPermanentDelete: (project: Project) => void;
}

function ProjectsTable({
  projects,
  qualityHistoryMap,
  latestQuality,
  onOpenQualityHistory,
  onDelete,
  onPermanentDelete,
}: ProjectsTableProps) {
  return (
    <div className={`${projectPanelClass} overflow-hidden`}>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
            <tr>
              <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Project</th>
              <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Status</th>
              <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Quality</th>
              <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Owner</th>
              <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Updated</th>
              <th className="px-4 py-2 text-right text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {projects.map((project) => {
              const score = latestQuality[project.id];
              const tier = score != null ? getNumericScoreTier(score) : null;
              const statusKinds = deriveProjectStatusKinds(project, score);
              const history = qualityHistoryMap[project.id] ?? [];
              return (
                <tr key={project.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/50">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-7 h-7 rounded-md bg-gradient-to-br ${avatarGradient(project.id)} text-white font-mono text-[10px] font-bold inline-flex items-center justify-center`}
                      >
                        {avatarInitials(project.name)}
                      </span>
                      <div className="min-w-0">
                        <Link
                          href={`/ade/dashboard/projects/${project.id}`}
                          className="font-semibold text-gray-900 dark:text-gray-100 hover:text-indigo-500 truncate block"
                        >
                          {project.name}
                        </Link>
                        <span className="text-[11px] font-mono text-gray-500 truncate block">{project.slug ?? '—'}</span>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap items-center gap-1">
                      {statusKinds.map((kind) => (
                        <ProjectStatusChip key={kind} kind={kind} />
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    {tier ? (
                      <button
                        type="button"
                        onClick={() => onOpenQualityHistory(project)}
                        className="inline-flex items-center gap-2"
                      >
                        <span className="block h-6 w-16 overflow-hidden rounded border border-gray-200 dark:border-gray-700">
                          {history.length >= 2 ? (
                            <ProjectQualityTrendSparkline history={history} className="block h-full w-full" />
                          ) : null}
                        </span>
                        <span className={`text-sm font-semibold tabular-nums ${tier.textClass}`}>
                          {score}
                        </span>
                      </button>
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="text-xs text-gray-700 dark:text-gray-300 truncate" title={project.creator_email}>
                      {project.creator_name}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500" title={new Date(project.updated_at).toLocaleString()}>
                    {relativeTime(project.updated_at)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="inline-flex items-center gap-1">
                      <Link
                        href={`/ade/dashboard/projects/${project.id}?tab=settings`}
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-indigo-500"
                        title="Open settings"
                      >
                        <Edit2 className="w-4 h-4" />
                      </Link>
                      <button
                        type="button"
                        onClick={() => onDelete(project.id)}
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-rose-500"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onPermanentDelete(project)}
                        className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"
                        title="Permanently delete"
                      >
                        <AlertOctagon className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface PortfolioTrendChartProps {
  series: number[];
  latest: number;
  delta: number;
  best: { project: Project; score: number } | null;
  worst: { project: Project; score: number } | null;
}

function PortfolioTrendChart({ series, latest, delta, best, worst }: PortfolioTrendChartProps) {
  const width = 600;
  const height = 160;
  const populated = series
    .map((value, idx) => ({ value, idx }))
    .filter((point) => point.value > 0);
  const minValue = Math.min(...populated.map((p) => p.value), 100);
  const maxValue = Math.max(...populated.map((p) => p.value), 0);
  const span = Math.max(20, maxValue - minValue);
  const baselineMin = Math.max(0, Math.floor(minValue / 10) * 10 - 5);
  const baselineMax = Math.min(100, Math.ceil(maxValue / 10) * 10 + 5);
  const range = Math.max(20, baselineMax - baselineMin);
  void span;
  const stepX = width / Math.max(1, series.length - 1);
  const path = populated
    .map((point, i) => {
      const x = point.idx * stepX;
      const y = height - ((point.value - baselineMin) / range) * (height - 24) - 12;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  const area = path
    ? `${path} L${(populated[populated.length - 1].idx * stepX).toFixed(2)},${height} L${(populated[0].idx * stepX).toFixed(2)},${height} Z`
    : '';

  return (
    <div>
      <div className="flex items-center gap-6 mb-3 flex-wrap">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-500">Current</p>
          <p className="text-2xl font-bold font-mono text-emerald-500">{latest}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-500">Δ vs {series.length}w ago</p>
          <p
            className={`text-base font-semibold inline-flex items-center gap-1 ${
              delta > 0 ? 'text-emerald-500' : delta < 0 ? 'text-rose-500' : 'text-gray-500'
            }`}
          >
            {delta > 0 ? <TrendingUp className="w-4 h-4" /> : delta < 0 ? <AlertOctagon className="w-4 h-4" /> : null}
            {delta > 0 ? '+' : ''}{delta} pts
          </p>
        </div>
        {best ? (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500">Best</p>
            <p className="text-base font-semibold font-mono">
              {best.score} <span className="text-xs font-normal text-gray-500">{best.project.name}</span>
            </p>
          </div>
        ) : null}
        {worst ? (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500">Worst</p>
            <p
              className={`text-base font-semibold font-mono ${
                worst.score < 70 ? 'text-amber-500' : 'text-gray-700 dark:text-gray-200'
              }`}
            >
              {worst.score} <span className="text-xs font-normal text-gray-500">{worst.project.name}</span>
            </p>
          </div>
        ) : null}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-40" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id="portfolioFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#6366f1" stopOpacity={0.4} />
            <stop offset="1" stopColor="#6366f1" stopOpacity={0} />
          </linearGradient>
        </defs>
        <g stroke="#e2e8f0" strokeDasharray="3,3" strokeWidth={0.5} className="dark:stroke-gray-700">
          <line x1={0} y1={20} x2={width} y2={20} />
          <line x1={0} y1={60} x2={width} y2={60} />
          <line x1={0} y1={100} x2={width} y2={100} />
          <line x1={0} y1={140} x2={width} y2={140} />
        </g>
        {area ? <path d={area} fill="url(#portfolioFill)" /> : null}
        {path ? <path d={path} fill="none" stroke="#6366f1" strokeWidth={2} /> : null}
      </svg>
      <div className="flex items-center justify-between mt-2 text-[10px] font-mono text-gray-400">
        <span>{series.length} w ago</span>
        <span>now</span>
      </div>
    </div>
  );
}

export default Projects;

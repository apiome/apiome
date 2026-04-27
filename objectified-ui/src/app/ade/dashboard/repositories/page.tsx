'use client';

import { useMemo, useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  CheckCircle2,
  Eye,
  GitBranch,
  GitBranchPlus,
  History,
  Hourglass,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Star,
  Timer,
} from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Alert } from '@/app/components/ui/Alert';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Skeleton } from '@/app/components/ui/Skeleton';
import {
  RepositoryWizardDialog,
  type RegisteredRepositoryResult,
} from '@/app/components/ade/dashboard/RepositoryWizardDialog';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  repositoryHeaderShellClass,
  repositoryHeaderIconTileClass,
  repositoryHeaderEyebrowClass,
  repositoryPanelClass,
  repositoryPanelHeaderClass,
  repositoryPanelEyebrowClass,
  repositoryMonoCellClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  RepositoryStatusChip,
  formatRepositoryStatusLabel,
} from '@/app/components/ade/dashboard/RepositoryStatusChip';
import { RepositoryKpiCard } from '@/app/components/ade/dashboard/RepositoryKpiCard';
import {
  deriveRepositoryKpis,
  formatScanDuration,
} from '@/app/components/ade/dashboard/repositoryKpis';
import {
  loadRepositoryFavorites,
  toggleRepositoryFavorite,
} from '@/app/utils/repository-favorites';
import { getRepositoriesI18nBundle } from './i18n';

interface RegisteredRepository {
  id: string;
  provider: string;
  owner: string;
  name: string;
  fullName: string;
  status: string;
  branches: string[];
  lastScanAt?: string | null;
  lastScanDurationMs?: number | null;
  lastScanBranch?: string | null;
}

type RepositorySortField = 'name' | 'lastScan' | 'status' | 'favorite';
type RepositorySortDirection = 'asc' | 'desc';

const SORT_OPTIONS: ReadonlyArray<{
  value: string;
  field: RepositorySortField;
  direction: RepositorySortDirection;
  copyKey:
    | 'sortLastScanDesc'
    | 'sortLastScanAsc'
    | 'sortNameAsc'
    | 'sortNameDesc'
    | 'sortStatus'
    | 'sortFavoritesFirst';
}> = [
  { value: 'lastScan-desc', field: 'lastScan', direction: 'desc', copyKey: 'sortLastScanDesc' },
  { value: 'lastScan-asc', field: 'lastScan', direction: 'asc', copyKey: 'sortLastScanAsc' },
  { value: 'name-asc', field: 'name', direction: 'asc', copyKey: 'sortNameAsc' },
  { value: 'name-desc', field: 'name', direction: 'desc', copyKey: 'sortNameDesc' },
  { value: 'status-asc', field: 'status', direction: 'asc', copyKey: 'sortStatus' },
  { value: 'favorite-desc', field: 'favorite', direction: 'desc', copyKey: 'sortFavoritesFirst' },
];

function formatLastScan(lastScanAt: string | null | undefined): string {
  if (!lastScanAt) return 'Never';
  return new Date(lastScanAt).toLocaleString();
}

const PROVIDER_BAR_TONE: Record<string, string> = {
  github: 'bg-gray-700 dark:bg-gray-300',
  gitlab: 'bg-orange-500',
  bitbucket: 'bg-sky-500',
};

function providerBarToneClass(provider: string): string {
  return PROVIDER_BAR_TONE[provider] ?? 'bg-indigo-500';
}

const RepositoriesPage = () => {
  const router = useRouter();
  const copy = getRepositoriesI18nBundle('en');

  const [repositories, setRepositories] = useState<RegisteredRepository[]>([]);
  const [favorites, setFavorites] = useState<Set<string>>(() => new Set());
  const [search, setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [sortField, setSortField] = useState<RepositorySortField>('lastScan');
  const [sortDirection, setSortDirection] = useState<RepositorySortDirection>('desc');
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [wizardOpen, setWizardOpen] = useState(false);

  useEffect(() => {
    setFavorites(loadRepositoryFavorites());
  }, []);

  const loadRepositories = useCallback(async (mode: 'initial' | 'refresh' = 'initial') => {
    if (mode === 'refresh') {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    try {
      const response = await fetch('/api/repositories');
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load repositories');
      }
      setRepositories(data.repositories || []);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load repositories';
      setErrorMessage(message);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadRepositories('initial');
  }, [loadRepositories]);

  const handleRepositoryRegistered = useCallback(
    (repository: RegisteredRepositoryResult) => {
      setRepositories((prev) => [repository, ...prev]);
      router.push(`/ade/dashboard/repositories/${repository.id}`);
    },
    [router],
  );

  const handleNavigateToLinkedAccounts = useCallback(() => {
    router.push('/ade/dashboard/linked-accounts');
  }, [router]);

  const providerOptions = useMemo(() => {
    return Array.from(new Set(repositories.map((repo) => repo.provider))).sort((a, b) => a.localeCompare(b));
  }, [repositories]);

  const statusOptions = useMemo(() => {
    return Array.from(new Set(repositories.map((repo) => repo.status))).sort((a, b) => a.localeCompare(b));
  }, [repositories]);

  const filteredAndSortedRepos = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = repositories.filter((repo) => {
      const matchesSearch =
        q.length === 0 ||
        repo.fullName.toLowerCase().includes(q) ||
        repo.name.toLowerCase().includes(q) ||
        repo.owner.toLowerCase().includes(q);
      const matchesProvider = providerFilter === 'all' || repo.provider === providerFilter;
      const matchesStatus = statusFilter === 'all' || repo.status === statusFilter;
      const matchesFavorite = !favoritesOnly || favorites.has(repo.id);
      return matchesSearch && matchesProvider && matchesStatus && matchesFavorite;
    });

    const sorted = [...filtered].sort((left, right) => {
      if (sortField === 'name') {
        return left.fullName.localeCompare(right.fullName);
      }
      if (sortField === 'status') {
        return formatRepositoryStatusLabel(left.status).localeCompare(formatRepositoryStatusLabel(right.status));
      }
      if (sortField === 'favorite') {
        const leftFav = favorites.has(left.id) ? 1 : 0;
        const rightFav = favorites.has(right.id) ? 1 : 0;
        return leftFav - rightFav;
      }
      const leftStamp = left.lastScanAt ? Date.parse(left.lastScanAt) : 0;
      const rightStamp = right.lastScanAt ? Date.parse(right.lastScanAt) : 0;
      return leftStamp - rightStamp;
    });

    return sortDirection === 'asc' ? sorted : sorted.reverse();
  }, [
    repositories,
    providerFilter,
    search,
    sortDirection,
    sortField,
    statusFilter,
    favoritesOnly,
    favorites,
  ]);

  const kpis = useMemo(() => deriveRepositoryKpis(repositories), [repositories]);

  const providerMix = useMemo(() => {
    if (repositories.length === 0) return [] as Array<{ provider: string; count: number; percent: number }>;
    const counts = new Map<string, number>();
    for (const repo of repositories) {
      counts.set(repo.provider, (counts.get(repo.provider) ?? 0) + 1);
    }
    const total = repositories.length;
    return Array.from(counts.entries())
      .map(([provider, count]) => ({ provider, count, percent: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count);
  }, [repositories]);

  const headerEyebrow = useMemo(() => {
    if (isLoading) return copy.loadingRepositories;
    const parts = [
      `${kpis.tracked} ${copy.kpiTrackedSubtitle}`,
      `${favorites.size} ${copy.favoritesOnlyButton.toLowerCase()}`,
      `${kpis.healthy} ${copy.kpiHealthyLabel.toLowerCase()}`,
    ];
    return parts.join(' · ');
  }, [
    copy.favoritesOnlyButton,
    copy.kpiHealthyLabel,
    copy.kpiTrackedSubtitle,
    copy.loadingRepositories,
    favorites.size,
    isLoading,
    kpis.healthy,
    kpis.tracked,
  ]);

  const handleSort = (field: RepositorySortField) => {
    if (sortField !== field) {
      setSortField(field);
      setSortDirection(field === 'lastScan' ? 'desc' : 'asc');
      return;
    }
    setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
  };

  const handleSortMenuChange = (value: string) => {
    const match = SORT_OPTIONS.find((option) => option.value === value);
    if (!match) return;
    setSortField(match.field);
    setSortDirection(match.direction);
  };

  const currentSortValue = useMemo(() => {
    const match = SORT_OPTIONS.find(
      (option) => option.field === sortField && option.direction === sortDirection
    );
    return match?.value ?? 'lastScan-desc';
  }, [sortField, sortDirection]);

  const handleToggleFavorite = (repositoryId: string) => {
    const next = toggleRepositoryFavorite(repositoryId);
    setFavorites(new Set(next));
  };

  const triggerScanNow = async (repository: RegisteredRepository) => {
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const fallbackBranch = repository.branches[0] || 'main';
      const response = await fetch(`/api/repositories/${repository.id}/scans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ branch: fallbackBranch, force: true }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to queue repository scan');
      }
      await loadRepositories('refresh');
      setSuccessMessage(copy.scanQueuedMessage);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to queue repository scan';
      setErrorMessage(message);
    }
  };

  const togglePauseState = async (repository: RegisteredRepository) => {
    setErrorMessage('');
    setSuccessMessage('');
    const isArchived = repository.status === 'archived';
    const action = isArchived ? 'unarchive' : 'archive';
    try {
      const response = await fetch(`/api/repositories/${repository.id}/${action}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || `Failed to ${isArchived ? 'resume' : 'pause'} repository`);
      }
      await loadRepositories('refresh');
      setSuccessMessage(isArchived ? copy.resumedMessage : copy.pausedMessage);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to ${isArchived ? 'resume' : 'pause'} repository`;
      setErrorMessage(message);
    }
  };

  const hasNoResults = !isLoading && filteredAndSortedRepos.length === 0;
  const hasAnyRepositories = repositories.length > 0;

  const renderSortHeader = (field: RepositorySortField, label: string, ariaLabel: string) => {
    const isActive = sortField === field;
    const ariaSort: 'ascending' | 'descending' | 'none' = isActive
      ? sortDirection === 'asc'
        ? 'ascending'
        : 'descending'
      : 'none';
    return (
      <th
        scope="col"
        aria-sort={ariaSort}
        className="text-left px-3 py-2 font-semibold text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400"
      >
        <button
          type="button"
          onClick={() => handleSort(field)}
          aria-label={ariaLabel}
          className={`inline-flex items-center gap-1 ${
            isActive
              ? 'text-indigo-600 dark:text-indigo-400'
              : 'hover:text-gray-700 dark:hover:text-gray-200'
          }`}
        >
          {label}
          {isActive ? (
            sortDirection === 'asc' ? (
              <ArrowUp className="w-3 h-3" />
            ) : (
              <ArrowDown className="w-3 h-3" />
            )
          ) : (
            <ChevronsUpDown className="w-3 h-3 opacity-40" />
          )}
        </button>
      </th>
    );
  };

  return (
    <>
      <header className={repositoryHeaderShellClass}>
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              <span className={repositoryHeaderIconTileClass} aria-hidden="true">
                <GitBranchPlus className="w-5 h-5" />
              </span>
              <div>
                <h2 className="text-2xl font-bold leading-tight text-gray-900 dark:text-white">
                  {copy.pageTitle}
                </h2>
                <p className={repositoryHeaderEyebrowClass}>
                  {headerEyebrow}
                  <span className="mx-2 text-gray-400" aria-hidden>
                    ·
                  </span>
                  <Link
                    className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                    href="/ade/dashboard/repositories/reports"
                  >
                    {copy.scanReportsLink}
                  </Link>
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void loadRepositories('refresh')}
                disabled={isRefreshing || isLoading}
                aria-label="Refresh repositories"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                {isRefreshing ? copy.refreshingButton : 'Refresh'}
              </Button>
              <Button onClick={() => setWizardOpen(true)} size="sm">
                <Plus className="w-4 h-4" />
                {copy.addRepositoryButton}
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          {successMessage && (
            <Alert variant="success" onClose={() => setSuccessMessage('')}>
              {successMessage}
            </Alert>
          )}
          {errorMessage && (
            <Alert variant="error" onClose={() => setErrorMessage('')}>
              {errorMessage}
            </Alert>
          )}

          <section
            aria-label="Repository KPIs"
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4"
          >
            <RepositoryKpiCard
              label={copy.kpiTrackedLabel}
              value={kpis.tracked}
              subtitle={`${kpis.tracked} ${copy.kpiTrackedSubtitle}`}
              tone="indigo"
              icon={<GitBranchPlus className="w-4 h-4" />}
            />
            <RepositoryKpiCard
              label={copy.kpiHealthyLabel}
              value={kpis.healthy}
              subtitle={copy.kpiHealthySubtitleFormat.replace('{pct}', String(kpis.healthyPct))}
              tone="emerald"
              icon={<CheckCircle2 className="w-4 h-4" />}
            />
            <RepositoryKpiCard
              label={copy.kpiAttentionLabel}
              value={kpis.warnings + kpis.scanning}
              subtitle={copy.kpiAttentionSubtitleFormat
                .replace('{warnings}', String(kpis.warnings))
                .replace('{scanning}', String(kpis.scanning))}
              subtitleTone={kpis.warnings + kpis.scanning > 0 ? 'warning' : 'default'}
              tone="amber"
              icon={<AlertTriangle className="w-4 h-4" />}
            />
            <RepositoryKpiCard
              label={copy.kpiScannedLabel}
              value={kpis.scanned24h}
              subtitle={copy.kpiScannedSubtitleFormat.replace('{stale}', String(kpis.stale))}
              tone="sky"
              icon={<Activity className="w-4 h-4" />}
              sparkline={kpis.scannedSeries}
            />
            <RepositoryKpiCard
              label={copy.kpiAvgScanLabel}
              value={formatScanDuration(kpis.avgScanMs, copy.scanDurationFallback)}
              subtitle={kpis.avgScanMs == null ? copy.kpiAvgScanNoData : copy.kpiAvgScanSubtitle}
              tone="violet"
              icon={<Timer className="w-4 h-4" />}
            />
            <RepositoryKpiCard
              label={copy.kpiSlowestLabel}
              value={formatScanDuration(
                kpis.slowestScan?.lastScanDurationMs ?? null,
                copy.scanDurationFallback,
                'text-rose-300',
              )}
              subtitle={
                kpis.slowestScan
                  ? `${kpis.slowestScan.fullName}${
                      kpis.slowestScan.lastScanBranch ? ` · ${kpis.slowestScan.lastScanBranch}` : ''
                    }`
                  : copy.kpiSlowestNoData
              }
              tone="rose"
              icon={<Hourglass className="w-4 h-4" />}
            />
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <section
              className={`${repositoryPanelClass} lg:col-span-2 flex flex-col`}
              aria-label="Recent scans"
            >
              <div className={repositoryPanelHeaderClass}>
                <div className="flex items-center gap-3">
                  <History className="w-5 h-5 text-indigo-500 shrink-0" />
                  <div>
                    <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                      {copy.tableLastScan === 'Last scan' ? 'Recent scans' : copy.tableLastScan}
                    </h3>
                    <p className={repositoryPanelEyebrowClass}>{copy.recentScansEyebrow}</p>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-2 flex-wrap">
                  <div className="relative flex-1 min-w-[12rem]">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                    <Input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder={copy.searchPlaceholder}
                      className="h-8 pl-7 text-xs"
                    />
                  </div>
                  <button
                    type="button"
                    aria-pressed={favoritesOnly}
                    onClick={() => setFavoritesOnly((prev) => !prev)}
                    className={`h-8 px-2.5 rounded-md border text-xs inline-flex items-center gap-1.5 shrink-0 transition-colors ${
                      favoritesOnly
                        ? 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-500/40 dark:bg-amber-900/20 dark:text-amber-200'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
                    }`}
                  >
                    <Star
                      className={`w-3.5 h-3.5 ${favoritesOnly || favorites.size > 0 ? 'text-amber-400 fill-amber-400' : 'text-gray-400'}`}
                    />
                    {copy.favoritesOnlyButton}
                    <span className="font-mono text-[10px] text-gray-400">({favorites.size})</span>
                  </button>
                  <select
                    aria-label={copy.tableProvider}
                    value={providerFilter}
                    onChange={(event) => setProviderFilter(event.target.value)}
                    className="h-8 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-xs text-gray-700 dark:text-gray-200 shrink-0"
                  >
                    <option value="all">{copy.providerAll}</option>
                    {providerOptions.map((provider) => (
                      <option key={provider} value={provider}>
                        {provider}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={copy.tableStatus}
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                    className="h-8 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-xs text-gray-700 dark:text-gray-200 shrink-0"
                  >
                    <option value="all">{copy.statusAll}</option>
                    {statusOptions.map((status) => (
                      <option key={status} value={status}>
                        {formatRepositoryStatusLabel(status)}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={copy.sortLabel}
                    value={currentSortValue}
                    onChange={(event) => handleSortMenuChange(event.target.value)}
                    className="h-8 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 text-xs text-gray-700 dark:text-gray-200 shrink-0"
                  >
                    {SORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {`${copy.sortLabel}: ${copy[option.copyKey]}`}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {hasNoResults && hasAnyRepositories ? (
                <div className="px-5 py-12 text-center text-sm text-gray-500 dark:text-gray-400">
                  No repositories match the current filters.
                </div>
              ) : hasNoResults ? (
                <div className="px-5 py-10">
                  <EmptyState
                    icon={<GitBranchPlus className="h-10 w-10" />}
                    title={copy.emptyTitle}
                    description={copy.emptyDescription}
                    action={<Button onClick={() => setWizardOpen(true)}>{copy.emptyAction}</Button>}
                  />
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50/60 dark:bg-gray-900/40 border-y border-gray-200 dark:border-gray-700">
                        <tr>
                          <th
                            scope="col"
                            className="px-2 py-2 w-8 text-center font-semibold"
                            aria-label="Favorite"
                          >
                            <Star className="inline w-3.5 h-3.5 text-gray-400" />
                          </th>
                          {renderSortHeader('name', copy.tableRepo, `Sort by ${copy.tableRepo.toLowerCase()}`)}
                          <th
                            scope="col"
                            className="text-left px-3 py-2 font-semibold text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400"
                          >
                            {copy.tableProvider}
                          </th>
                          <th
                            scope="col"
                            className="text-left px-3 py-2 font-semibold text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400"
                          >
                            {copy.tableBranches}
                          </th>
                          {renderSortHeader('status', copy.tableStatus, `Sort by ${copy.tableStatus.toLowerCase()}`)}
                          {renderSortHeader('lastScan', copy.tableLastScan, `Sort by ${copy.tableLastScan.toLowerCase()}`)}
                          <th
                            scope="col"
                            className="text-right px-5 py-2 font-semibold text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400"
                          >
                            {copy.tableActions}
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
                        {isLoading
                          ? Array.from({ length: 6 }).map((_, idx) => (
                              <tr key={`skeleton-${idx}`}>
                                <td className="px-2 py-3"><Skeleton className="h-4 w-4 mx-auto" /></td>
                                <td className="px-5 py-3"><Skeleton className="h-4 w-52" /></td>
                                <td className="px-3 py-3"><Skeleton className="h-4 w-16" /></td>
                                <td className="px-3 py-3"><Skeleton className="h-4 w-24" /></td>
                                <td className="px-3 py-3"><Skeleton className="h-5 w-20 rounded" /></td>
                                <td className="px-3 py-3"><Skeleton className="h-4 w-28" /></td>
                                <td className="px-5 py-3"><Skeleton className="h-7 w-32 ml-auto" /></td>
                              </tr>
                            ))
                          : filteredAndSortedRepos.map((repo) => {
                              const isFavorite = favorites.has(repo.id);
                              const isScanning = repo.status === 'scan_in_progress';
                              const isArchived = repo.status === 'archived';
                              const branchList = (repo.branches || []).join(', ');
                              const openDetail = () =>
                                router.push(`/ade/dashboard/repositories/${repo.id}`);
                              return (
                                <tr
                                  key={repo.id}
                                  role="button"
                                  tabIndex={0}
                                  aria-label={`${copy.openDetailButton}: ${repo.fullName}`}
                                  onClick={openDetail}
                                  onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                      event.preventDefault();
                                      openDetail();
                                    }
                                  }}
                                  className="cursor-pointer hover:bg-gray-50/60 dark:hover:bg-gray-900/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
                                >
                                  {/* Favorite cell intercepts clicks so toggling
                                      a star doesn't also navigate to the detail. */}
                                  <td
                                    className="px-2 py-3 w-8 text-center"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    <button
                                      type="button"
                                      aria-label={isFavorite ? copy.unfavoriteAriaLabel : copy.favoriteAriaLabel}
                                      aria-pressed={isFavorite}
                                      onClick={() => handleToggleFavorite(repo.id)}
                                      className="inline-flex p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
                                    >
                                      <Star
                                        className={`w-3.5 h-3.5 ${
                                          isFavorite
                                            ? 'text-amber-400 fill-amber-400'
                                            : 'text-gray-300 dark:text-gray-600 hover:text-amber-400'
                                        }`}
                                      />
                                    </button>
                                  </td>
                                  <td className="px-5 py-3">
                                    <div className="flex items-center gap-2">
                                      <GitBranch className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                                      <span className="font-mono text-xs font-medium text-gray-900 dark:text-gray-100">
                                        {repo.fullName}
                                      </span>
                                    </div>
                                  </td>
                                  <td className="px-3 py-3 text-xs text-gray-500 dark:text-gray-400 capitalize">
                                    {repo.provider}
                                  </td>
                                  <td className={`px-3 py-3 ${repositoryMonoCellClass}`}>
                                    {branchList || '—'}
                                  </td>
                                  <td className="px-3 py-3">
                                    <RepositoryStatusChip status={repo.status} />
                                  </td>
                                  <td className={`px-3 py-3 ${repositoryMonoCellClass}`}>
                                    {formatLastScan(repo.lastScanAt)}
                                  </td>
                                  {/* Actions cell intercepts clicks so the row's
                                      navigate-on-click doesn't fire when the user
                                      really meant to scan/pause/open. */}
                                  <td className="px-5 py-3" onClick={(event) => event.stopPropagation()}>
                                    <div className="flex items-center justify-end gap-1.5">
                                      <button
                                        type="button"
                                        aria-label={copy.scanNowButton}
                                        title={copy.scanNowButton}
                                        disabled={isScanning}
                                        onClick={() => void triggerScanNow(repo)}
                                        className="p-1.5 rounded border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 inline-flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                                      >
                                        <Play className="w-3.5 h-3.5" />
                                        <span className="sr-only">{copy.scanNowButton}</span>
                                      </button>
                                      <button
                                        type="button"
                                        aria-label={isArchived ? copy.resumeButton : copy.pauseButton}
                                        title={isArchived ? copy.resumeButton : copy.pauseButton}
                                        onClick={() => void togglePauseState(repo)}
                                        className="p-1.5 rounded border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 inline-flex items-center justify-center"
                                      >
                                        <Pause className="w-3.5 h-3.5" />
                                        <span className="sr-only">
                                          {isArchived ? copy.resumeButton : copy.pauseButton}
                                        </span>
                                      </button>
                                      <button
                                        type="button"
                                        aria-label={copy.openDetailButton}
                                        title={copy.openDetailButton}
                                        onClick={() =>
                                          router.push(`/ade/dashboard/repositories/${repo.id}`)
                                        }
                                        className="p-1.5 rounded border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 inline-flex items-center justify-center"
                                      >
                                        <Eye className="w-3.5 h-3.5" />
                                        <span className="sr-only">{copy.openDetailButton}</span>
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                      </tbody>
                    </table>
                  </div>
                  {!isLoading ? (
                    <div className="px-5 py-2.5 border-t border-gray-100 dark:border-gray-700/60 text-[11px] text-gray-500 font-mono flex items-center justify-between">
                      <span>
                        {copy.paginationFooterFormat
                          .replace('{visible}', String(filteredAndSortedRepos.length))
                          .replace('{total}', String(repositories.length))}
                      </span>
                    </div>
                  ) : null}
                </>
              )}
            </section>

            <aside className={repositoryPanelClass} aria-label="Provider mix">
              <div className={repositoryPanelHeaderClass}>
                <div className="flex items-center gap-3">
                  <Activity className="w-5 h-5 text-indigo-500 shrink-0" />
                  <div>
                    <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                      {copy.tableProvider}
                    </h3>
                    <p className={repositoryPanelEyebrowClass}>{copy.providerMixEyebrow}</p>
                  </div>
                </div>
              </div>
              <div className="px-5 py-4 space-y-3">
                {providerMix.length === 0 ? (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    No repositories tracked yet.
                  </p>
                ) : (
                  providerMix.map((entry) => (
                    <div key={entry.provider} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="capitalize text-gray-700 dark:text-gray-200">
                          {entry.provider}
                        </span>
                        <span className="font-mono text-[11px] text-gray-500">
                          {entry.count} · {entry.percent}%
                        </span>
                      </div>
                      <div
                        className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700/60 overflow-hidden"
                        role="progressbar"
                        aria-valuenow={entry.percent}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label={`${entry.provider} share`}
                      >
                        <div
                          className={`h-full ${providerBarToneClass(entry.provider)}`}
                          style={{ width: `${entry.percent}%` }}
                        />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </aside>
          </div>
        </div>
      </main>

      <RepositoryWizardDialog
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        copy={copy}
        onError={setErrorMessage}
        onSuccess={setSuccessMessage}
        onRepositoryRegistered={handleRepositoryRegistered}
        onNavigateToLinkedAccounts={handleNavigateToLinkedAccounts}
      />
    </>
  );
};

export default RepositoriesPage;

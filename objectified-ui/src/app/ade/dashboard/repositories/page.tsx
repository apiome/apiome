'use client';

import { useSession } from 'next-auth/react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FolderGit2,
  LayoutGrid,
  List,
  Plus,
  RefreshCw,
  Search,
  ArrowRight,
} from 'lucide-react';
import { Button, buttonVariants } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { EmptyState } from '@/app/components/ui/EmptyState';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { toast } from 'sonner';
import { cn } from '@lib/utils';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardTableWrapClass,
  dashboardTableTheadClass,
  dashboardThClass,
  dashboardThRightClass,
  dashboardTbodyClass,
  dashboardTrHoverClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  type DashboardRepository,
  type RepositoryProvider,
  type RepositoryStatus,
  ProviderBadge,
  RepositoryCard,
  RepositorySparkline,
  formatLastScan,
  repoInitials,
  repositoryStatusClass,
  repositoryStatusLabel,
} from '@/app/components/ade/dashboard/repositories/repositoryStoreUi';

const VIEW_STORAGE = 'objectified-dashboard-repositories-view';

function normalizeProvider(p: unknown): RepositoryProvider {
  const s = String(p ?? '').toLowerCase();
  if (s === 'gitlab') return 'gitlab';
  if (s === 'bitbucket') return 'bitbucket';
  if (s === 'public_url' || s === 'publicurl') return 'public_url';
  return 'github';
}

function normalizeStatus(s: unknown): RepositoryStatus {
  const v = String(s ?? '').toLowerCase();
  if (v === 'pending') return 'pending';
  if (v === 'scanning') return 'scanning';
  if (v === 'error') return 'error';
  if (v === 'archived') return 'archived';
  return 'ready';
}

function normalizeRepo(x: unknown): DashboardRepository | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  const id = String(o.id ?? '');
  if (!id) return null;
  return {
    id,
    name: String(o.name ?? o.full_name ?? 'Repository'),
    full_name: String(o.full_name ?? o.clone_url ?? o.name ?? ''),
    description: o.description != null ? String(o.description) : null,
    provider: normalizeProvider(o.provider),
    default_branch: String(o.default_branch ?? 'main'),
    visibility: o.visibility === 'private' ? 'private' : o.visibility === 'public' ? 'public' : undefined,
    status: normalizeStatus(o.status),
    last_scanned_at: o.last_scanned_at != null ? String(o.last_scanned_at) : null,
    total_files: typeof o.total_files === 'number' ? o.total_files : null,
    importable_count: typeof o.importable_count === 'number' ? o.importable_count : null,
  };
}

function parseList(data: unknown): DashboardRepository[] {
  if (!data || typeof data !== 'object') return [];
  const raw = (data as { repositories?: unknown }).repositories;
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizeRepo).filter((r): r is DashboardRepository => r != null);
}

export default function RepositoriesPage() {
  const { data: session } = useSession();
  const currentTenantId = (session?.user as { current_tenant_id?: string })?.current_tenant_id;

  const [repos, setRepos] = useState<DashboardRepository[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState<string>('all');
  const [visibilityFilter, setVisibilityFilter] = useState<string>('all');
  const [sortKey, setSortKey] = useState<string>('scanned');
  const [view, setView] = useState<'grid' | 'list'>(() => {
    if (typeof window === 'undefined') return 'grid';
    return window.localStorage.getItem(VIEW_STORAGE) === 'list' ? 'list' : 'grid';
  });

  const persistView = useCallback((v: 'grid' | 'list') => {
    setView(v);
    try {
      window.localStorage.setItem(VIEW_STORAGE, v);
    } catch {
      /* ignore */
    }
  }, []);

  const load = useCallback(async () => {
    if (!currentTenantId) {
      setRepos([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/repositories', { credentials: 'include' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      setRepos(parseList(data));
    } catch (e) {
      console.error(e);
      setRepos([]);
      toast.error('Could not load repositories.');
    } finally {
      setLoading(false);
    }
  }, [currentTenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    let list = repos.slice();
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) =>
          r.name.toLowerCase().includes(q) ||
          r.full_name.toLowerCase().includes(q) ||
          r.default_branch.toLowerCase().includes(q)
      );
    }
    if (providerFilter !== 'all') {
      list = list.filter((r) => r.provider === providerFilter);
    }
    if (visibilityFilter === 'public') {
      list = list.filter((r) => r.provider === 'public_url' || r.visibility === 'public');
    } else if (visibilityFilter === 'private') {
      list = list.filter((r) => r.provider !== 'public_url');
    }
    if (sortKey === 'name') {
      list.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortKey === 'importable') {
      list.sort((a, b) => (b.importable_count ?? 0) - (a.importable_count ?? 0));
    } else {
      list.sort((a, b) => {
        const ta = a.last_scanned_at ? new Date(a.last_scanned_at).getTime() : 0;
        const tb = b.last_scanned_at ? new Date(b.last_scanned_at).getTime() : 0;
        return tb - ta;
      });
    }
    return list;
  }, [repos, search, providerFilter, visibilityFilter, sortKey]);

  const kpis = useMemo(() => {
    const byProvider = { github: 0, gitlab: 0, bitbucket: 0, public_url: 0 as number };
    let files = 0;
    let importable = 0;
    let lastScanMs = 0;
    for (const r of repos) {
      byProvider[r.provider] = (byProvider[r.provider] ?? 0) + 1;
      files += r.total_files ?? 0;
      importable += r.importable_count ?? 0;
      if (r.last_scanned_at) {
        const t = new Date(r.last_scanned_at).getTime();
        if (!Number.isNaN(t)) lastScanMs = Math.max(lastScanMs, t);
      }
    }
    const providerBits = [
      byProvider.github ? `${byProvider.github} GitHub` : null,
      byProvider.gitlab ? `${byProvider.gitlab} GitLab` : null,
      byProvider.bitbucket ? `${byProvider.bitbucket} Bitbucket` : null,
      byProvider.public_url ? `${byProvider.public_url} public URL` : null,
    ].filter(Boolean);
    const hasErrors = repos.some((r) => r.status === 'error');
    const lastScanTitle =
      lastScanMs > 0 ? formatLastScan(new Date(lastScanMs).toISOString(), false) : '—';
    const lastScanSub =
      repos.length === 0
        ? 'No scans yet'
        : lastScanMs > 0
          ? `${hasErrors ? 'Some repos need attention' : 'All repos healthy'}`
          : 'No scans yet';
    return {
      count: repos.length,
      providerSubtitle: providerBits.length ? providerBits.join(' · ') : '—',
      files,
      importable,
      lastScanTitle,
      lastScanSub,
    };
  }, [repos]);

  if (!currentTenantId) {
    return (
      <div className={cn(dashboardMainClass, 'max-w-3xl')}>
        <div className="rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50 p-8 dark:border-amber-700/50 dark:from-amber-900/20 dark:to-yellow-900/20">
          <h2 className="mb-2 text-xl font-bold text-amber-900 dark:text-amber-100">No tenant selected</h2>
          <p className="mb-4 text-amber-800 dark:text-amber-200">Select a tenant to manage repositories.</p>
          <Link href="/ade/dashboard/tenants" className={cn(buttonVariants())}>
            Go to Tenants
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className={cn(dashboardMainClass, dashboardContentStackClass)}>
      <div className="border-b border-gray-200 bg-white px-6 pb-5 pt-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-4">
            <span className="inline-flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 text-white shadow-lg shadow-emerald-500/20">
              <FolderGit2 className="h-6 w-6" aria-hidden />
            </span>
            <div className="min-w-0">
              <h2 className="text-2xl font-bold tracking-tight">Repositories</h2>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Browse repositories registered to this workspace and pick one to explore its files.
              </p>
            </div>
          </div>
          <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => toast.message('Rescan all repositories will run when scan jobs are wired to the API.')}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Rescan all
            </Button>
            <Link
              href="/ade/dashboard/repositories/new"
              className={cn(buttonVariants({ size: 'sm' }), 'gap-1.5 [font-size:inherit]')}
            >
              <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Add repository
            </Link>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Repositories</p>
            <p className="mt-1 text-2xl font-bold">{kpis.count.toLocaleString()}</p>
            <p className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">{kpis.providerSubtitle}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Files indexed</p>
            <p className="mt-1 text-2xl font-bold">{kpis.files.toLocaleString()}</p>
            <p className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">Across tracked branches</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Importable</p>
            <p className="mt-1 text-2xl font-bold text-indigo-600 dark:text-indigo-400">{kpis.importable.toLocaleString()}</p>
            <p className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">OpenAPI · Arazzo · JSON Schema · …</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Imports (30d)</p>
            <p className="mt-1 text-2xl font-bold">—</p>
            <p className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">When import history is connected</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Last scan</p>
            <p className="mt-1 text-2xl font-bold">{kpis.lastScanTitle}</p>
            <p className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">{kpis.lastScanSub}</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-b border-gray-200 bg-white px-6 py-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="relative min-w-[260px] max-w-md flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, owner, or URL…"
            className="bg-gray-50 pl-9 dark:bg-gray-900/50"
          />
        </div>
        <Select value={providerFilter} onValueChange={setProviderFilter}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Provider" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All providers</SelectItem>
            <SelectItem value="github">GitHub</SelectItem>
            <SelectItem value="gitlab">GitLab</SelectItem>
            <SelectItem value="bitbucket">Bitbucket</SelectItem>
            <SelectItem value="public_url">Public URL</SelectItem>
          </SelectContent>
        </Select>
        <Select value={visibilityFilter} onValueChange={setVisibilityFilter}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Visibility" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All visibilities</SelectItem>
            <SelectItem value="public">Public</SelectItem>
            <SelectItem value="private">Private (linked account)</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sortKey} onValueChange={setSortKey}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Sort" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="scanned">Sort: Recently scanned</SelectItem>
            <SelectItem value="name">Sort: Name</SelectItem>
            <SelectItem value="importable">Sort: Importable count</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto inline-flex overflow-hidden rounded-md border border-gray-200 dark:border-gray-700">
          <button
            type="button"
            onClick={() => persistView('grid')}
            className={cn(
              'inline-flex items-center gap-1 px-3 py-2 text-sm',
              view === 'grid'
                ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300'
                : 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-700'
            )}
          >
            <LayoutGrid className="h-3.5 w-3.5" aria-hidden />
            Grid
          </button>
          <button
            type="button"
            onClick={() => persistView('list')}
            className={cn(
              'inline-flex items-center gap-1 px-3 py-2 text-sm',
              view === 'list'
                ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300'
                : 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-700'
            )}
          >
            <List className="h-3.5 w-3.5" aria-hidden />
            List
          </button>
        </div>
      </div>

      <div className="px-6 pb-8 pt-2">
        {loading ? (
          <LoadingState message="Loading repositories…" />
        ) : filtered.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<FolderGit2 className="h-10 w-10 text-white" aria-hidden />}
            title={repos.length === 0 ? 'No repositories yet' : 'No matches'}
            description={
              repos.length === 0
                ? 'Register a Git repository through a linked account or a public clone URL. After the API is enabled, scans and importable file counts appear here.'
                : 'Try adjusting search or filters.'
            }
            action={
              repos.length === 0 ? (
                <Link
                  href="/ade/dashboard/repositories/new"
                  className={cn(buttonVariants({ size: 'sm' }), '[font-size:inherit]')}
                >
                  Add repository
                </Link>
              ) : undefined
            }
          />
        ) : view === 'grid' ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((repo, i) => (
              <RepositoryCard key={repo.id} repo={repo} index={i} />
            ))}
          </div>
        ) : (
          <div className={dashboardTableWrapClass}>
            <table className="w-full text-sm">
              <thead className={dashboardTableTheadClass}>
                <tr>
                  <th className={dashboardThClass}>Repository</th>
                  <th className={dashboardThClass}>Provider</th>
                  <th className={dashboardThClass}>Branch</th>
                  <th className={dashboardThRightClass}>Files</th>
                  <th className={dashboardThRightClass}>Importable</th>
                  <th className={dashboardThClass}>Status</th>
                  <th className={dashboardThClass}>Last scan</th>
                  <th className={dashboardThClass}>Activity</th>
                  <th className={cn(dashboardThRightClass, 'pr-6')} />
                </tr>
              </thead>
              <tbody className={dashboardTbodyClass}>
                {filtered.map((repo, i) => (
                  <tr key={repo.id} className={dashboardTrHoverClass}>
                    <td className="px-6 py-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className={cn(
                            'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded bg-gradient-to-br font-mono text-[10px] font-bold text-white',
                            i % 6 === 0
                              ? 'from-emerald-500 to-teal-500'
                              : i % 6 === 1
                                ? 'from-indigo-500 to-purple-500'
                                : i % 6 === 2
                                  ? 'from-purple-500 to-pink-500'
                                  : i % 6 === 3
                                    ? 'from-amber-500 to-orange-500'
                                    : i % 6 === 4
                                      ? 'from-rose-500 to-pink-500'
                                      : 'from-cyan-500 to-blue-500'
                          )}
                        >
                          {repoInitials(repo.name)}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">{repo.name}</span>
                          <span className="block truncate font-mono text-[10px] text-gray-500 dark:text-gray-400">
                            {repo.full_name}
                          </span>
                        </span>
                      </div>
                    </td>
                    <td className="py-3">
                      <ProviderBadge provider={repo.provider} />
                    </td>
                    <td className="font-mono text-xs">{repo.default_branch}</td>
                    <td className="text-right font-mono text-xs">{(repo.total_files ?? 0).toLocaleString()}</td>
                    <td className="text-right">
                      {repo.importable_count != null ? (
                        <span className="rounded bg-indigo-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300">
                          {repo.importable_count}
                        </span>
                      ) : (
                        <span className="font-mono text-xs text-gray-400">—</span>
                      )}
                    </td>
                    <td className="py-3">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
                          repositoryStatusClass(repo.status)
                        )}
                      >
                        {repositoryStatusLabel(repo.status)}
                      </span>
                    </td>
                    <td className="text-xs text-gray-500 dark:text-gray-400">
                      {formatLastScan(repo.last_scanned_at, repo.status === 'error')}
                    </td>
                    <td className="py-3">
                      <RepositorySparkline seed={repo.id} errorTint={repo.status === 'error'} />
                    </td>
                    <td className="pr-6 text-right">
                      <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
                        Detail <ArrowRight className="h-3 w-3" aria-hidden />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
              <span>
                Showing {filtered.length} of {repos.length} repositories
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

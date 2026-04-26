'use client';

import { useSession, signIn } from 'next-auth/react';
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  GitBranchPlus,
  Hourglass,
  Link as LinkIcon,
  Link2,
  RefreshCw,
  Search,
  TimerReset,
  X as XIcon,
} from 'lucide-react';
import { SiAmazon, SiBitbucket, SiGithub, SiGitlab, SiGoogle } from 'react-icons/si';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { Label } from '../../../components/ui/Label';
import { Alert } from '../../../components/ui/Alert';
import { LoadingState } from '../../../components/ui/LoadingState';
import { EmptyState } from '../../../components/ui/EmptyState';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { getLinkedAccountsForUser, unlinkExternalAccount, updatePersonalAccessToken, removePersonalAccessToken } from '../../../../../lib/db/helper';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelClass,
  repositoryHeaderEyebrowClass,
  repositoryHeaderIconTileClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { RepositoryKpiCard } from '@/app/components/ade/dashboard/RepositoryKpiCard';
import { deriveLinkedAccountKpis } from '@/app/components/ade/dashboard/linkedAccountKpis';
import { LinkedAccountRow } from '@/app/components/ade/dashboard/LinkedAccountRow';
import {
  LinkedAccountsIdentityCard,
  LinkedAccountsProviderList,
  LinkedAccountsTipsCard,
} from '@/app/components/ade/dashboard/LinkedAccountsRightColumn';
import { LinkedAccountActivityTimeline } from '@/app/components/ade/dashboard/LinkedAccountActivityTimeline';
import { deriveLinkedAccountActivity } from '@/app/components/ade/dashboard/linkedAccountActivity';
import { LinkedAccountReconnectDialog } from '@/app/components/ade/dashboard/LinkedAccountReconnectDialog';

interface LinkedAccount {
  id: string;
  provider: string;
  provider_user_id: string;
  provider_email: string;
  provider_username: string | null;
  /** Last 6 characters of PAT when set (for display only; full token never sent to client) */
  access_token_suffix?: string | null;
  /** OAuth access-token expiry. Null for providers that don't expose one. */
  token_expires_at?: string | null;
  created_at: string;
  last_login_at: string | null;
  repository_count: number;
  health_status: 'healthy' | 'scope_missing' | 'revoked' | 'network_error' | null;
  health_checked_at: string | null;
}

interface ProviderConfig {
  name: string;
  displayName: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  color: string;
  available: boolean;
  /** Provider supports a Personal Access Token alongside OAuth. */
  patSupported: boolean;
}

const providerConfigs: Record<string, ProviderConfig> = {
  github:    { name: 'github',    displayName: 'GitHub',       icon: SiGithub,    color: '#24292e', available: true,  patSupported: true  },
  gitlab:    { name: 'gitlab',    displayName: 'GitLab',       icon: SiGitlab,    color: '#fc6d26', available: true,  patSupported: true  },
  bitbucket: { name: 'bitbucket', displayName: 'Bitbucket',    icon: SiBitbucket, color: '#0052cc', available: true,  patSupported: false },
  google:    { name: 'google',    displayName: 'Google / GCP', icon: SiGoogle,    color: '#4285f4', available: false, patSupported: false },
  aws:       { name: 'aws',       displayName: 'AWS',          icon: SiAmazon,    color: '#ff9900', available: false, patSupported: false },
};

const LinkedAccounts = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog } = useDialog();
  const [linkedAccounts, setLinkedAccounts] = useState<LinkedAccount[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [patDialogOpen, setPatDialogOpen] = useState(false);
  const [patProvider, setPatProvider] = useState<string>('');
  const [patToken, setPatToken] = useState('');
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [methodFilter, setMethodFilter] = useState<'all' | 'oauth' | 'pat'>('all');
  const [healthFilter, setHealthFilter] = useState<'all' | 'healthy' | 'attention'>('all');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const [reconnectAccount, setReconnectAccount] = useState<LinkedAccount | null>(null);

  const userId = (session?.user as any)?.user_id;

  useEffect(() => {
    if (userId) {
      loadLinkedAccounts();
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('linked') === 'true') {
        setSuccessMessage('Account linked successfully!');
        window.history.replaceState({}, '', '/ade/dashboard/linked-accounts');
      } else if (urlParams.get('error')) {
        setErrorMessage(urlParams.get('error') || 'Failed to link account');
        window.history.replaceState({}, '', '/ade/dashboard/linked-accounts');
      }
    }
  }, [userId]);

  const loadLinkedAccounts = async () => {
    if (!userId) return;
    setIsLoading(true);
    try {
      const result = await getLinkedAccountsForUser(userId);
      const parsed = JSON.parse(result) as Array<Record<string, unknown>>;
      setLinkedAccounts(
        parsed.map((account) => ({
          ...(account as unknown as LinkedAccount),
          repository_count: Number(account.repository_count ?? 0),
          health_status:
            account.health_status === 'healthy' ||
            account.health_status === 'scope_missing' ||
            account.health_status === 'revoked' ||
            account.health_status === 'network_error'
              ? account.health_status
              : null,
          health_checked_at: typeof account.health_checked_at === 'string' ? account.health_checked_at : null,
          token_expires_at: typeof account.token_expires_at === 'string' ? account.token_expires_at : null,
        }))
      );
    } catch (error: any) {
      setErrorMessage('Failed to load linked accounts');
    } finally {
      setIsLoading(false);
    }
  };

  const handleLinkAccount = async (provider: string) => {
    try {
      const response = await fetch(`/api/auth/link/${provider}`, { method: 'GET', credentials: 'include' });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ error: 'Unknown error' }));
        setErrorMessage(`Failed to initiate account linking: ${error.error || 'Unknown error'}`);
        return;
      }
      signIn(provider, { callbackUrl: '/ade/dashboard/linked-accounts' });
    } catch (error) {
      setErrorMessage('An error occurred while linking the account');
    }
  };

  const handleUnlinkAccount = async (account: LinkedAccount) => {
    const providerConfig = providerConfigs[account.provider];
    const confirmed = await confirmDialog({
      title: `Unlink ${providerConfig?.displayName || account.provider} Account`,
      message: `Are you sure you want to unlink your ${providerConfig?.displayName || account.provider} account (${account.provider_username || account.provider_email})?`,
    });
    if (!confirmed) return;

    setIsLoading(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const result = await unlinkExternalAccount(userId, account.id);
      const response = JSON.parse(result);
      if (response.success) {
        setSuccessMessage(`Successfully unlinked ${providerConfig?.displayName || account.provider} account`);
        await loadLinkedAccounts();
      } else {
        setErrorMessage(response.error || 'Failed to unlink account');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred while unlinking the account');
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenPatDialog = (provider: string, accountId?: string) => {
    setPatProvider(provider);
    setEditingAccountId(accountId || null);
    setPatToken('');
    setErrorMessage('');
    setPatDialogOpen(true);
  };

  const handleClosePatDialog = () => {
    setPatDialogOpen(false);
    setPatProvider('');
    setPatToken('');
    setEditingAccountId(null);
  };

  const handleSavePatToken = async () => {
    if (!patToken.trim()) {
      setErrorMessage('Personal Access Token is required');
      return;
    }
    if (!editingAccountId) {
      setErrorMessage('No linked account found. Please link your account first.');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const result = await updatePersonalAccessToken(userId, editingAccountId, patToken);
      const response = JSON.parse(result);
      if (response.success) {
        setSuccessMessage(`Successfully ${linkedAccounts.find(a => a.id === editingAccountId)?.access_token_suffix ? 'updated' : 'added'} Personal Access Token`);
        await loadLinkedAccounts();
        handleClosePatDialog();
      } else {
        setErrorMessage(response.error || 'Failed to save Personal Access Token');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred while saving the Personal Access Token');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemovePatToken = async (provider: string, accountId: string) => {
    const providerConfig = providerConfigs[provider];
    const account = linkedAccounts.find(a => a.id === accountId);

    const confirmed = await confirmDialog({
      title: `Remove Personal Access Token`,
      message: `Are you sure you want to remove the Personal Access Token for your ${providerConfig?.displayName || provider} account (${account?.provider_username || account?.provider_email})?`,
    });
    if (!confirmed) return;

    setIsLoading(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const result = await removePersonalAccessToken(userId, accountId);
      const response = JSON.parse(result);
      if (response.success) {
        setSuccessMessage(`Successfully removed Personal Access Token for ${providerConfig?.displayName || provider}`);
        await loadLinkedAccounts();
      } else {
        setErrorMessage(response.error || 'Failed to remove Personal Access Token');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred while removing the Personal Access Token');
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  const filteredAccounts = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return linkedAccounts.filter((account) => {
      if (methodFilter === 'pat' && !account.access_token_suffix) return false;
      if (methodFilter === 'oauth' && account.access_token_suffix) return false;
      if (healthFilter === 'healthy' && account.health_status !== 'healthy') return false;
      if (healthFilter === 'attention') {
        const needs =
          account.health_status === 'scope_missing' ||
          account.health_status === 'revoked' ||
          account.health_status === 'network_error';
        if (!needs) return false;
      }
      if (!q) return true;
      const handle = (account.provider_username || '').toLowerCase();
      const email = (account.provider_email || '').toLowerCase();
      const provider = account.provider.toLowerCase();
      return handle.includes(q) || email.includes(q) || provider.includes(q);
    });
  }, [linkedAccounts, searchQuery, methodFilter, healthFilter]);

  // Trim selection to currently-visible rows on every filter change so
  // a hidden row can't quietly be acted on by the bulk toolbar.
  useEffect(() => {
    setSelectedIds((prev) => {
      const visible = new Set(filteredAccounts.map((a) => a.id));
      let changed = false;
      const next = new Set<string>();
      prev.forEach((id) => {
        if (visible.has(id)) next.add(id);
        else changed = true;
      });
      return changed ? next : prev;
    });
  }, [filteredAccounts]);

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allVisibleSelected =
    filteredAccounts.length > 0 && filteredAccounts.every((a) => selectedIds.has(a.id));

  const toggleAllVisible = () => {
    setSelectedIds((prev) => {
      if (allVisibleSelected) {
        const next = new Set(prev);
        filteredAccounts.forEach((a) => next.delete(a.id));
        return next;
      }
      const next = new Set(prev);
      filteredAccounts.forEach((a) => next.add(a.id));
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  // No per-user "verify now" endpoint exists yet — only the admin-protected
  // health-monitor cron at /api/admin/credential-health. Refresh from the
  // cached probe results so the UI surfaces the latest known state.
  // TODO(linked-accounts/phase5): expose a user-scoped verify endpoint that
  // re-runs token-health-monitor for one or many linked-account ids.
  const handleVerifyAccounts = async (ids: string[]) => {
    setIsLoading(true);
    setErrorMessage('');
    try {
      await loadLinkedAccounts();
      const count = ids.length;
      setSuccessMessage(
        count === 0
          ? 'Refreshed health for all linked accounts.'
          : `Refreshed health for ${count} ${count === 1 ? 'account' : 'accounts'}.`,
      );
    } finally {
      setIsLoading(false);
    }
  };

  const availableProviderCount = useMemo(
    () => Object.values(providerConfigs).filter((p) => p.available).length,
    [],
  );
  const kpis = useMemo(
    () => deriveLinkedAccountKpis(linkedAccounts, availableProviderCount),
    [linkedAccounts, availableProviderCount],
  );
  const recentActivity = useMemo(
    () => deriveLinkedAccountActivity(linkedAccounts, { limit: 5 }),
    [linkedAccounts],
  );

  // Open the scope-diff modal first instead of jumping straight to OAuth.
  // Initial linking from the right column still uses `handleLinkAccount`
  // directly — there's no existing token to reconcile against on first link.
  const openReconnectDialog = (account: LinkedAccount) => {
    setReconnectAccount(account);
  };
  const confirmReconnect = () => {
    if (!reconnectAccount) return;
    handleLinkAccount(reconnectAccount.provider);
    setReconnectAccount(null);
  };

  // Eyebrow summarizes posture in one line; mirrors the repositories header.
  // Read once on render — no need to memo a string concatenation.
  const headerEyebrow = (() => {
    const parts: string[] = [];
    parts.push(`${kpis.linked} linked`);
    parts.push(`${kpis.healthy} healthy`);
    if (kpis.needsAttention > 0) parts.push(`${kpis.needsAttention} needs attention`);
    if (kpis.nextExpiryDays !== null) parts.push(`next token expires in ${kpis.nextExpiryDays} d`);
    return parts.join(' · ');
  })();

  if (!session) {
    return (
      <div className="p-6">
        <LoadingState minHeightClassName="min-h-64" message="Loading linked accounts..." />
      </div>
    );
  }

  return (
    <>
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 min-w-0">
              <span className={repositoryHeaderIconTileClass} aria-hidden="true">
                <LinkIcon className="w-5 h-5" />
              </span>
              <div className="min-w-0">
                <h2 className="text-2xl font-bold leading-tight text-gray-900 dark:text-white">
                  Linked accounts
                </h2>
                <p className={repositoryHeaderEyebrowClass}>
                  {linkedAccounts.length === 0
                    ? 'Link external accounts for single sign-on and repository access'
                    : headerEyebrow}
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>

      {/* Success / Error */}
      {successMessage && <Alert variant="success" className="mb-4" onClose={() => setSuccessMessage('')}>{successMessage}</Alert>}
      {errorMessage && <Alert variant="error" className="mb-4" onClose={() => setErrorMessage('')}>{errorMessage}</Alert>}

      {linkedAccounts.length > 0 && (
        <section
          aria-label="Linked account KPIs"
          className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4"
        >
          <RepositoryKpiCard
            label="Linked providers"
            value={
              <>
                {kpis.linked}
                <span className="text-lg font-semibold text-gray-400 dark:text-gray-500 ml-0.5">
                  /{kpis.available}
                </span>
              </>
            }
            subtitle={
              kpis.linked === 0
                ? 'No providers linked yet'
                : linkedAccounts.map((a) => a.provider).join(' · ')
            }
            tone="indigo"
            icon={<LinkIcon className="w-4 h-4" />}
          />
          <RepositoryKpiCard
            label="Healthy"
            value={kpis.healthy}
            subtitle={
              kpis.linked === 0
                ? '—'
                : `${Math.round((kpis.healthy / kpis.linked) * 100)}% of linked providers`
            }
            tone="emerald"
            icon={<CheckCircle2 className="w-4 h-4" />}
          />
          <RepositoryKpiCard
            label="Needs attention"
            value={kpis.needsAttention}
            subtitle={
              kpis.needsAttention === 0
                ? 'All linked providers passing health probes'
                : 'Scope missing, revoked, or unreachable'
            }
            subtitleTone={kpis.needsAttention > 0 ? 'warning' : 'default'}
            tone="amber"
            icon={<AlertTriangle className="w-4 h-4" />}
          />
          <RepositoryKpiCard
            label="Repos credentialed"
            value={kpis.reposCredentialed}
            subtitle={
              kpis.reposCredentialed === 0
                ? 'No repositories using these credentials yet'
                : `Across ${kpis.linked} ${kpis.linked === 1 ? 'account' : 'accounts'}`
            }
            tone="violet"
            icon={<GitBranchPlus className="w-4 h-4" />}
          />
          <RepositoryKpiCard
            label="Avg token age"
            value={
              kpis.avgTokenAgeDays === null ? (
                '—'
              ) : (
                <>
                  {kpis.avgTokenAgeDays}
                  <span className="text-lg font-semibold text-gray-400 dark:text-gray-500 ml-0.5">
                    d
                  </span>
                </>
              )
            }
            subtitle={
              kpis.linked === 0
                ? '—'
                : `${kpis.oauthOnlyCount} OAuth-only · ${kpis.patCount} with PAT`
            }
            tone="sky"
            icon={<Hourglass className="w-4 h-4" />}
          />
          <RepositoryKpiCard
            label="Next expiry"
            value={
              kpis.nextExpiryDays === null ? (
                <span className="text-gray-400 dark:text-gray-500">—</span>
              ) : (
                <>
                  {kpis.nextExpiryDays}
                  <span className="text-lg font-semibold text-rose-300 dark:text-rose-300/70 ml-0.5">
                    d
                  </span>
                </>
              )
            }
            subtitle={
              kpis.nextExpiryRow
                ? `${kpis.nextExpiryRow.provider} · ${
                    (kpis.nextExpiryRow as LinkedAccount).provider_username ||
                    (kpis.nextExpiryRow as LinkedAccount).provider_email
                  }`
                : 'No tracked expirations'
            }
            subtitleTone={
              kpis.nextExpiryDays !== null && kpis.nextExpiryDays <= 14 ? 'negative' : 'default'
            }
            tone="rose"
            icon={<TimerReset className="w-4 h-4" />}
          />
        </section>
      )}

      {/* Two-column layout: linked accounts list (2/3) + right rail (1/3) */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
        <div className="lg:col-span-2 min-w-0">
        {linkedAccounts.length === 0 ? (
          <EmptyState
            icon={<LinkIcon className="h-10 w-10" />}
            title="No Linked Accounts"
            description="Link a provider on the right to sign in with SSO and manage repository access."
            iconContainerClassName="from-cyan-500 to-blue-600 shadow-cyan-500/30"
          />
        ) : (
          <div className={`${dashboardPanelClass} overflow-hidden`}>
            {/* Card header — same shape as the right-column cards so the
                Linked accounts page reads as one consistent surface. */}
            <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center gap-3">
              <Link2 className="w-5 h-5 text-indigo-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                  Connected providers
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Sign-in identity + repository credentials. Click a row to drill into
                  the repos using it.
                </p>
              </div>
              <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 shrink-0">
                {kpis.linked} linked
              </span>
            </div>
            {selectedIds.size === 0 ? (
              <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900/30 flex items-center gap-3 flex-wrap">
                <div className="relative flex-1 min-w-[14rem] max-w-md">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Filter by provider, username, or email…"
                    className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400"
                  />
                </div>
                <select
                  value={methodFilter}
                  onChange={(e) => setMethodFilter(e.target.value as 'all' | 'oauth' | 'pat')}
                  className="text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 px-2 py-1.5"
                  aria-label="Filter by method"
                >
                  <option value="all">All methods</option>
                  <option value="oauth">OAuth only</option>
                  <option value="pat">With PAT</option>
                </select>
                <select
                  value={healthFilter}
                  onChange={(e) => setHealthFilter(e.target.value as 'all' | 'healthy' | 'attention')}
                  className="text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 px-2 py-1.5"
                  aria-label="Filter by health"
                >
                  <option value="all">All statuses</option>
                  <option value="healthy">Healthy</option>
                  <option value="attention">Needs attention</option>
                </select>
                <div className="flex-1" />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleVerifyAccounts([])}
                  disabled={isLoading}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Verify all
                </Button>
              </div>
            ) : (
              <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-950/30 flex items-center gap-3 flex-wrap">
                <label className="flex items-center gap-2 text-sm text-indigo-900 dark:text-indigo-100 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    className="h-4 w-4 rounded border-indigo-300 text-indigo-600"
                  />
                  <span>
                    {selectedIds.size} selected
                    {filteredAccounts.length !== selectedIds.size && (
                      <span className="text-indigo-700/70 dark:text-indigo-300/70">
                        {' '}
                        of {filteredAccounts.length}
                      </span>
                    )}
                  </span>
                </label>
                <div className="flex-1" />
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => handleVerifyAccounts(Array.from(selectedIds))}
                  disabled={isLoading}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Verify selected
                </Button>
                <Button variant="ghost" size="sm" onClick={clearSelection} disabled={isLoading}>
                  <XIcon className="w-3.5 h-3.5" />
                  Clear
                </Button>
              </div>
            )}

            {filteredAccounts.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-500 dark:text-gray-400">
                No accounts match the current filters.
              </div>
            ) : (
              <ul className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredAccounts.map((account) => {
                  const provider = providerConfigs[account.provider];
                  if (!provider) return null;
                  return (
                    <LinkedAccountRow
                      key={account.id}
                      account={account}
                      provider={provider}
                      selected={selectedIds.has(account.id)}
                      onToggleSelect={() => toggleSelected(account.id)}
                      onVerify={() => handleVerifyAccounts([account.id])}
                      onUpdatePat={() => handleOpenPatDialog(account.provider, account.id)}
                      onReconnect={() => openReconnectDialog(account)}
                      onUnlink={() => handleUnlinkAccount(account)}
                      reposHref={`/ade/dashboard/repositories?linkedAccountId=${account.id}`}
                      disabled={isLoading}
                      formatDate={formatDate}
                    />
                  );
                })}
              </ul>
            )}
          </div>
        )}
        </div>

        <aside className="lg:col-span-1 space-y-6">
          <LinkedAccountsIdentityCard
            displayName={session?.user?.name}
            primaryEmail={session?.user?.email}
            accounts={linkedAccounts}
            providers={providerConfigs}
          />
          <LinkedAccountsProviderList
            providers={Object.values(providerConfigs)}
            linkedProviderNames={
              new Set(linkedAccounts.map((a) => a.provider))
            }
            onLink={handleLinkAccount}
            disabled={isLoading}
          />
          <LinkedAccountsTipsCard />
        </aside>
      </section>

      {linkedAccounts.length > 0 && (
        <section className="mb-10">
          <LinkedAccountActivityTimeline events={recentActivity} />
        </section>
      )}

      <LinkedAccountReconnectDialog
        open={!!reconnectAccount}
        onOpenChange={(open) => {
          if (!open) setReconnectAccount(null);
        }}
        provider={
          reconnectAccount ? providerConfigs[reconnectAccount.provider] ?? null : null
        }
        accountHandle={
          reconnectAccount?.provider_username ?? reconnectAccount?.provider_email ?? null
        }
        healthStatus={reconnectAccount?.health_status}
        onConfirm={confirmReconnect}
        isSubmitting={isLoading}
      />

      {/* Personal Access Token Dialog */}
      <Dialog open={patDialogOpen} onOpenChange={(open) => !open && handleClosePatDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{linkedAccounts.find(a => a.id === editingAccountId)?.access_token_suffix ? 'Update' : 'Add'} Personal Access Token</DialogTitle>
            <DialogDescription>
              {patProvider && `${providerConfigs[patProvider]?.displayName} · ${linkedAccounts.find(a => a.id === editingAccountId)?.provider_username || linkedAccounts.find(a => a.id === editingAccountId)?.provider_email}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="patToken">Token</Label>
              <Input id="patToken" type="password" value={patToken} onChange={(e) => setPatToken(e.target.value)} placeholder="Paste your token" autoFocus />
              <p className="text-xs text-gray-500 dark:text-gray-400">Used to authenticate with {providerConfigs[patProvider]?.displayName || 'the provider'}'s API.</p>
            </div>
            {patProvider === 'github' && (
              <Alert variant="info">
                <strong>GitHub scopes:</strong> repo (or public_repo), read:org, read:user, user:email
              </Alert>
            )}
            {patProvider === 'gitlab' && (
              <Alert variant="info">
                <strong>GitLab scopes:</strong> read_api, read_repository, read_user
              </Alert>
            )}
          </div>
          <DialogFooter>
            {/* When editing an existing PAT, expose a destructive Remove on
                the left so removal stays one click away after we dropped
                the per-provider card grid. */}
            {linkedAccounts.find((a) => a.id === editingAccountId)?.access_token_suffix && (
              <Button
                variant="ghost"
                onClick={async () => {
                  if (!editingAccountId) return;
                  await handleRemovePatToken(patProvider, editingAccountId);
                  handleClosePatDialog();
                }}
                disabled={isLoading}
                className="mr-auto text-red-600 hover:text-red-700 dark:text-red-400"
              >
                Remove token
              </Button>
            )}
            <Button variant="outline" onClick={handleClosePatDialog}>Cancel</Button>
            <Button onClick={handleSavePatToken} disabled={isLoading}>
              {linkedAccounts.find(a => a.id === editingAccountId)?.access_token_suffix ? 'Update token' : 'Add token'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
        </div>
      </main>
    </>
  );
};

export default LinkedAccounts;


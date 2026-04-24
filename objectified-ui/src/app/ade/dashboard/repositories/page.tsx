'use client';

import { useMemo, useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { GitBranchPlus, Search, Loader2 } from 'lucide-react';
import { SiGithub } from 'react-icons/si';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Alert } from '@/app/components/ui/Alert';
import { EmptyState } from '@/app/components/ui/EmptyState';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelClass,
  dashboardTableWrapClass,
  dashboardTableTheadClass,
  dashboardTbodyClass,
  dashboardThClass,
  dashboardThRightClass,
  dashboardTrHoverClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { getRepositoriesI18nBundle } from './i18n';

interface LinkedAccount {
  id: string;
  provider: string;
  provider_username?: string;
  provider_email?: string;
}

interface RepoSummary {
  id: number;
  name: string;
  full_name: string;
  description?: string | null;
  default_branch?: string;
}

interface BranchItem {
  branch: string;
  subpathGlob: string;
  pollIntervalSec?: number;
}

interface RegisteredRepository {
  id: string;
  provider: string;
  owner: string;
  name: string;
  fullName: string;
  status: string;
  branches: string[];
}

const RepositoriesPage = () => {
  const router = useRouter();
  const copy = getRepositoriesI18nBundle('en');

  const [repositories, setRepositories] = useState<RegisteredRepository[]>([]);
  const [search, setSearch] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState(0);
  const [linkedAccounts, setLinkedAccounts] = useState<LinkedAccount[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<LinkedAccount | null>(null);
  const [githubRepos, setGithubRepos] = useState<RepoSummary[]>([]);
  const [repoSearch, setRepoSearch] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<RepoSummary | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [selectedBranches, setSelectedBranches] = useState<BranchItem[]>([]);
  const [customBranchPattern, setCustomBranchPattern] = useState('');
  const [manifest, setManifest] = useState('');
  const [isWizardBusy, setIsWizardBusy] = useState(false);

  useEffect(() => {
    const loadRepositories = async () => {
      setIsLoading(true);
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
      }
    };
    void loadRepositories();
  }, []);

  const openWizard = async () => {
    setWizardOpen(true);
    setWizardStep(0);
    setSelectedAccount(null);
    setSelectedRepo(null);
    setGithubRepos([]);
    setBranches([]);
    setSelectedBranches([]);
    setCustomBranchPattern('');
    setManifest('');
    setRepoSearch('');
    setErrorMessage('');
    try {
      const response = await fetch('/api/linked-accounts');
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load linked accounts');
      }
      setLinkedAccounts((data.accounts || []).filter((account: LinkedAccount) => account.provider === 'github'));
    } catch {
      setLinkedAccounts([]);
    }
  };

  const loadReposForAccount = async (account: LinkedAccount) => {
    setSelectedAccount(account);
    setSelectedRepo(null);
    setBranches([]);
    setSelectedBranches([]);
    setCustomBranchPattern('');
    setIsWizardBusy(true);
    try {
      const response = await fetch(`/api/sso/github/repos?accountId=${encodeURIComponent(account.id)}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Failed to load repositories');
      }
      setGithubRepos(data.repositories || []);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load repositories';
      setErrorMessage(message);
    } finally {
      setIsWizardBusy(false);
    }
  };

  const loadBranchesForRepo = async (repo: RepoSummary) => {
    if (!selectedAccount) return;
    setSelectedRepo(repo);
    setIsWizardBusy(true);
    try {
      const response = await fetch(
        `/api/sso/github/branches?accountId=${encodeURIComponent(selectedAccount.id)}&repo=${encodeURIComponent(repo.full_name)}`
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Failed to load branches');
      }
      const availableBranches = Array.isArray(data.branches) ? data.branches : [];
      const defaultBranchName =
        (typeof data.defaultBranch === 'string' && data.defaultBranch) || repo.default_branch || null;
      const defaultBranch =
        defaultBranchName && availableBranches.includes(defaultBranchName)
          ? [{ branch: defaultBranchName, subpathGlob: '**/*' }]
          : [];
      setBranches(availableBranches);
      setSelectedBranches(defaultBranch);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load branches';
      setErrorMessage(message);
    } finally {
      setIsWizardBusy(false);
    }
  };

  const filteredSourceRepos = useMemo(() => {
    const q = repoSearch.trim().toLowerCase();
    if (!q) return githubRepos;
    return githubRepos.filter(
      (repo) =>
        repo.name.toLowerCase().includes(q) || (repo.description || '').toLowerCase().includes(q)
    );
  }, [githubRepos, repoSearch]);

  const filteredRegisteredRepos = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return repositories;
    return repositories.filter((repo) => repo.fullName.toLowerCase().includes(q));
  }, [repositories, search]);

  const toggleBranch = (branchName: string) => {
    setSelectedBranches((prev) => {
      const exists = prev.some((entry) => entry.branch === branchName);
      if (exists) {
        return prev.filter((entry) => entry.branch !== branchName);
      }
      return [...prev, { branch: branchName, subpathGlob: '**/*' }];
    });
  };

  const updateSubpath = (branchName: string, value: string) => {
    setSelectedBranches((prev) =>
      prev.map((entry) =>
        entry.branch === branchName
          ? { ...entry, subpathGlob: value }
          : entry
      )
    );
  };

  const updatePollInterval = (branchName: string, value: string) => {
    const next = Number.parseInt(value, 10);
    setSelectedBranches((prev) =>
      prev.map((entry) =>
        entry.branch === branchName
          ? { ...entry, pollIntervalSec: Number.isFinite(next) ? next : undefined }
          : entry
      )
    );
  };

  const addCustomBranch = () => {
    const branchPattern = customBranchPattern.trim();
    if (!branchPattern) return;
    setSelectedBranches((prev) => {
      if (prev.some((entry) => entry.branch === branchPattern)) {
        return prev;
      }
      return [...prev, { branch: branchPattern, subpathGlob: '**/*' }];
    });
    setCustomBranchPattern('');
  };

  const goNext = () => {
    if (wizardStep === 0 && !selectedAccount) {
      setErrorMessage(copy.accountRequired);
      return;
    }
    if (wizardStep === 1 && !selectedRepo) {
      setErrorMessage(copy.repoRequired);
      return;
    }
    if (wizardStep === 2 && selectedBranches.length === 0) {
      setErrorMessage(copy.branchesRequired);
      return;
    }
    setErrorMessage('');
    setWizardStep((step) => Math.min(step + 1, 3));
  };

  const submitRegistration = async () => {
    if (!selectedAccount || !selectedRepo || selectedBranches.length === 0) return;
    setIsWizardBusy(true);
    setErrorMessage('');
    try {
      const [owner, name] = selectedRepo.full_name.split('/');
      const response = await fetch('/api/repositories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          linkedAccountId: selectedAccount.id,
          provider: 'github',
          owner,
          name,
          branches: selectedBranches.map((branch) => ({
            branch: branch.branch.trim(),
            subpathGlob: branch.subpathGlob.trim() || undefined,
            pollIntervalSec: branch.pollIntervalSec,
          })),
          manifest: manifest.trim() ? manifest : undefined,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to register repository');
      }
      const normalizedRepository = {
        ...data.repository,
        branches: Array.isArray(data.repository?.branches)
          ? data.repository.branches
              .map((branch: string | { name?: string; branch?: string }) =>
                typeof branch === 'string' ? branch : branch?.name ?? branch?.branch,
              )
              .filter((branchName: unknown): branchName is string => typeof branchName === 'string')
          : [],
      };
      setWizardOpen(false);
      setSuccessMessage(copy.successMessage);
      setRepositories((prev) => [normalizedRepository, ...prev]);
      router.push(`/ade/dashboard/repositories/${data.repository.id}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to register repository';
      setErrorMessage(message);
    } finally {
      setIsWizardBusy(false);
    }
  };

  const showNoLinkedAccountsPrompt = wizardStep === 0 && linkedAccounts.length === 0;
  const selectedCustomBranches = selectedBranches.filter(
    (entry) => !branches.includes(entry.branch)
  );

  return (
    <>
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <GitBranchPlus className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
                {copy.pageTitle}
              </h2>
              <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">{copy.pageSubtitle}</p>
            </div>
            <Button onClick={() => void openWizard()}>{copy.addRepositoryButton}</Button>
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

          <section className={`${dashboardPanelClass} p-4`}>
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={copy.searchPlaceholder}
                className="pl-8"
              />
            </div>
          </section>

          <section>
            {isLoading ? (
              <div className="flex items-center justify-center py-10 text-sm text-gray-500 dark:text-gray-400">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                {copy.loadingRepositories}
              </div>
            ) : filteredRegisteredRepos.length === 0 ? (
              <EmptyState
                icon={<GitBranchPlus className="h-10 w-10" />}
                title={copy.emptyTitle}
                description={copy.emptyDescription}
              />
            ) : (
              <div className={dashboardTableWrapClass}>
                <table className="min-w-full">
                  <thead className={dashboardTableTheadClass}>
                    <tr>
                      <th className={dashboardThClass}>{copy.tableRepo}</th>
                      <th className={dashboardThClass}>{copy.tableProvider}</th>
                      <th className={dashboardThClass}>{copy.tableBranches}</th>
                      <th className={dashboardThClass}>{copy.tableStatus}</th>
                      <th className={dashboardThRightClass} />
                    </tr>
                  </thead>
                  <tbody className={dashboardTbodyClass}>
                    {filteredRegisteredRepos.map((repo) => (
                      <tr key={repo.id} className={dashboardTrHoverClass}>
                        <td className="px-6 py-4 text-sm font-medium text-gray-900 dark:text-gray-100">
                          {repo.fullName}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300 capitalize">
                          {repo.provider}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                          {(repo.branches || []).join(', ')}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                          {repo.status}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => router.push(`/ade/dashboard/repositories/${repo.id}`)}
                          >
                            {copy.viewButton}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </main>

      <Dialog open={wizardOpen} onOpenChange={setWizardOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.wizardTitle}</DialogTitle>
            <DialogDescription>{copy.wizardDescription}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {wizardStep === 0 && (
              <div className="space-y-3">
                {!showNoLinkedAccountsPrompt ? (
                  <p className="text-sm font-medium">{copy.stepAccountTitle}</p>
                ) : null}
                {linkedAccounts.map((account) => (
                  <button
                    key={account.id}
                    type="button"
                    onClick={() => void loadReposForAccount(account)}
                    className={`w-full rounded-lg border px-3 py-2 text-left ${
                      selectedAccount?.id === account.id
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
                        : 'border-gray-200 dark:border-gray-700'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <SiGithub className="h-4 w-4" />
                      <span className="text-sm">{account.provider_username || account.provider_email}</span>
                    </div>
                  </button>
                ))}
                {linkedAccounts.length === 0 ? (
                  <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-3">
                    <p className="text-sm text-gray-600 dark:text-gray-300">
                      {copy.noLinkedAccountsQuestion}
                    </p>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => {
                          setWizardOpen(false);
                          router.push('/ade/dashboard/linked-accounts');
                        }}
                      >
                        {copy.yesButton}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setWizardOpen(false)}
                      >
                        {copy.noButton}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {wizardStep === 1 && (
              <div className="space-y-3">
                <p className="text-sm font-medium">{copy.stepRepoTitle}</p>
                <Input
                  value={repoSearch}
                  onChange={(event) => setRepoSearch(event.target.value)}
                  placeholder={copy.searchPlaceholder}
                />
                <div className="max-h-44 overflow-auto space-y-2">
                  {filteredSourceRepos.map((repo) => (
                    <button
                      key={repo.id}
                      type="button"
                      onClick={() => void loadBranchesForRepo(repo)}
                      className={`w-full rounded-lg border px-3 py-2 text-left ${
                        selectedRepo?.id === repo.id
                          ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}
                    >
                      <div className="text-sm font-medium">{repo.full_name}</div>
                      {repo.description ? (
                        <div className="text-xs text-gray-500 dark:text-gray-400">{repo.description}</div>
                      ) : null}
                    </button>
                  ))}
                </div>
                {selectedRepo?.default_branch ? (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {copy.defaultBranchLabel}: <span className="font-medium">{selectedRepo.default_branch}</span>
                  </p>
                ) : null}
              </div>
            )}

            {wizardStep === 2 && (
              <div className="space-y-3">
                <p className="text-sm font-medium">{copy.stepBranchesTitle}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">{copy.availableBranchesLabel}</p>
                <div className="max-h-52 overflow-auto space-y-2">
                  {branches.map((branchName) => {
                    const selected = selectedBranches.find((entry) => entry.branch === branchName);
                    return (
                      <div key={branchName} className="rounded-lg border border-gray-200 dark:border-gray-700 p-2">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={Boolean(selected)}
                            onChange={() => toggleBranch(branchName)}
                          />
                          {branchName}
                        </label>
                        {selected ? (
                          <div className="space-y-2 mt-2">
                            <Input
                              placeholder={copy.branchSubpathPlaceholder}
                              value={selected.subpathGlob}
                              onChange={(event) => updateSubpath(branchName, event.target.value)}
                            />
                            <Input
                              type="number"
                              min={15}
                              max={86400}
                              placeholder={copy.pollIntervalPlaceholder}
                              value={selected.pollIntervalSec ?? ''}
                              onChange={(event) => updatePollInterval(branchName, event.target.value)}
                            />
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
                  <p className="text-sm font-medium">{copy.addBranchPatternLabel}</p>
                  <div className="flex items-center gap-2">
                    <Input
                      value={customBranchPattern}
                      onChange={(event) => setCustomBranchPattern(event.target.value)}
                      placeholder={copy.branchPatternPlaceholder}
                    />
                    <Button type="button" variant="outline" onClick={addCustomBranch}>
                      {copy.addPatternButton}
                    </Button>
                  </div>
                </div>
                {selectedCustomBranches.length > 0 ? (
                  <div className="space-y-2">
                    {selectedCustomBranches.map((branch) => (
                      <div key={branch.branch} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">{branch.branch}</span>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => toggleBranch(branch.branch)}
                          >
                            {copy.removeButton}
                          </Button>
                        </div>
                        <Input
                          placeholder={copy.branchSubpathPlaceholder}
                          value={branch.subpathGlob}
                          onChange={(event) => updateSubpath(branch.branch, event.target.value)}
                        />
                        <Input
                          type="number"
                          min={15}
                          max={86400}
                          placeholder={copy.pollIntervalPlaceholder}
                          value={branch.pollIntervalSec ?? ''}
                          onChange={(event) => updatePollInterval(branch.branch, event.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            )}

            {wizardStep === 3 && (
              <div className="space-y-3">
                <p className="text-sm font-medium">{copy.stepManifestTitle}</p>
                <textarea
                  value={manifest}
                  onChange={(event) => setManifest(event.target.value)}
                  className="w-full min-h-40 rounded-lg border border-gray-200 dark:border-gray-700 p-3 text-sm bg-white dark:bg-gray-900"
                  placeholder={copy.manifestPlaceholder}
                />
              </div>
            )}
          </div>

          {!showNoLinkedAccountsPrompt ? (
            <DialogFooter>
              <Button variant="outline" onClick={() => setWizardOpen(false)} disabled={isWizardBusy}>
                {copy.wizardCancel}
              </Button>
              {wizardStep > 0 ? (
                <Button variant="outline" onClick={() => setWizardStep((step) => step - 1)} disabled={isWizardBusy}>
                  {copy.wizardBack}
                </Button>
              ) : null}
              {wizardStep < 3 ? (
                <Button onClick={goNext} disabled={isWizardBusy}>
                  {copy.wizardNext}
                </Button>
              ) : (
                <Button onClick={() => void submitRegistration()} disabled={isWizardBusy}>
                  {copy.wizardSubmit}
                </Button>
              )}
            </DialogFooter>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
};

export default RepositoriesPage;

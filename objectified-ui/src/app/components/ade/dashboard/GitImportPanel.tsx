'use client';

import { useState, useEffect } from 'react';
import { FolderOpen, File, ArrowLeft, Lock, Search, Loader2, Globe, AlertTriangle, CheckCircle2, FileCode } from 'lucide-react';
import { SiGithub, SiGitlab, SiGoogle, SiAmazon } from 'react-icons/si';
import { getLinkedAccountsForUser } from '../../../../../lib/db/helper';
import { extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import { Button } from '../../../components/ui/Button';

interface GitImportPanelProps {
  userId: string;
  onSpecificationFetched: (content: string, filename: string, metadata?: FileMetadataPreview) => void;
}

export const GitImportPanel: React.FC<GitImportPanelProps> = ({
  userId,
  onSpecificationFetched
}) => {
  // Linked accounts state
  const [linkedAccounts, setLinkedAccounts] = useState<any[]>([]);
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(true);

  // SSO Repository Browser state
  const [selectedAccount, setSelectedAccount] = useState<any>(null);
  const [repositories, setRepositories] = useState<any[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<any>(null);
  const [repoFiles, setRepoFiles] = useState<any[]>([]);
  const [currentPath, setCurrentPath] = useState<string>('');
  const [repoSearchQuery, setRepoSearchQuery] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>('');

  // Content state for preview
  const [fetchedContent, setFetchedContent] = useState<string | null>(null);
  const [fetchedFilename, setFetchedFilename] = useState<string | null>(null);
  const [fileMetadata, setFileMetadata] = useState<FileMetadataPreview | null>(null);

  // Load linked accounts when component mounts
  useEffect(() => {
    loadLinkedAccounts();
  }, [userId]);

  const loadLinkedAccounts = async () => {
    setIsLoadingAccounts(true);
    try {
      const result = await getLinkedAccountsForUser(userId);
      setLinkedAccounts(JSON.parse(result));
    } catch (error) {
      console.error('Failed to load linked accounts:', error);
      setLinkedAccounts([]);
    } finally {
      setIsLoadingAccounts(false);
    }
  };

  const getProviderIcon = (provider: string) => {
    switch (provider.toLowerCase()) {
      case 'github':
        return <SiGithub size={16} />;
      case 'gitlab':
        return <SiGitlab size={16} />;
      case 'google':
        return <SiGoogle size={16} />;
      case 'aws':
        return <SiAmazon size={16} />;
      default:
        return <Globe size={16} />;
    }
  };

  const handleSelectAccount = async (account: any) => {
    setSelectedAccount(account);
    setSelectedRepo(null);
    setRepoFiles([]);
    setCurrentPath('');
    setRepoSearchQuery('');
    setIsLoading(true);
    setErrorMessage('');
    setFetchedContent(null);
    setFetchedFilename(null);
    setFileMetadata(null);

    try {
      // Fetch repositories for the selected account
      const response = await fetch(`/api/sso/${account.provider}/repos?accountId=${account.id}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch repositories: ${response.statusText}`);
      }

      const data = await response.json();
      const sortedRepos = (data.repositories || []).sort((a: any, b: any) => {
        const nameA = (a.name || '').toLowerCase();
        const nameB = (b.name || '').toLowerCase();
        return nameA.localeCompare(nameB);
      });
      setRepositories(sortedRepos);
    } catch (error: any) {
      setErrorMessage(`Failed to load repositories: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectRepo = async (repo: any) => {
    setSelectedRepo(repo);
    setRepoFiles([]); // Clear files immediately
    setIsLoading(true);
    setErrorMessage('');
    setCurrentPath('');
    setFetchedContent(null);
    setFetchedFilename(null);
    setFileMetadata(null);

    try {
      // Fetch files from the repository root
      const response = await fetch(
        `/api/sso/${selectedAccount.provider}/files?accountId=${selectedAccount.id}&repo=${repo.full_name}&path=`
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch files: ${response.statusText}`);
      }

      const data = await response.json();
      setRepoFiles(data.files || []);
    } catch (error: any) {
      setErrorMessage(`Failed to load files: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNavigateToPath = async (path: string) => {
    setRepoFiles([]); // Clear files immediately
    setIsLoading(true);
    setErrorMessage('');
    setCurrentPath(path);

    try {
      const response = await fetch(
        `/api/sso/${selectedAccount.provider}/files?accountId=${selectedAccount.id}&repo=${selectedRepo.full_name}&path=${path}`
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch files: ${response.statusText}`);
      }

      const data = await response.json();
      setRepoFiles(data.files || []);
    } catch (error: any) {
      setErrorMessage(`Failed to load files: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectFile = async (file: any) => {
    if (file.type === 'dir') {
      // Navigate into directory
      handleNavigateToPath(file.path);
      return;
    }

    // Check if it's an OpenAPI file
    const isOpenAPIFile =
      file.name.includes('openapi') ||
      file.name.includes('swagger') ||
      file.name.endsWith('.json') ||
      file.name.endsWith('.yaml') ||
      file.name.endsWith('.yml');

    if (!isOpenAPIFile) {
      setErrorMessage('Please select an OpenAPI specification file (JSON or YAML)');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');

    try {
      // Fetch file content
      const response = await fetch(
        `/api/sso/${selectedAccount.provider}/content?accountId=${selectedAccount.id}&repo=${selectedRepo.full_name}&path=${file.path}&branch=${selectedRepo.default_branch}`
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch file content: ${response.statusText}`);
      }

      const data = await response.json();
      const content = data.content;
      const filename = file.name;

      // Extract metadata
      const metadata = extractFileMetadata(content);
      setFetchedContent(content);
      setFetchedFilename(filename);
      setFileMetadata(metadata);

      // Notify parent that content is ready
      onSpecificationFetched(content, filename, metadata);
    } catch (error: any) {
      setErrorMessage(`Failed to load file: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter repositories based on search query
  const filteredRepos = repositories.filter((repo: any) =>
    repo.name.toLowerCase().includes(repoSearchQuery.toLowerCase()) ||
    (repo.description && repo.description.toLowerCase().includes(repoSearchQuery.toLowerCase()))
  );

  if (isLoadingAccounts) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
        <span className="ml-3 text-gray-600 dark:text-gray-400">Loading linked accounts...</span>
      </div>
    );
  }

  if (linkedAccounts.length === 0) {
    return (
      <div className="p-6 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-medium text-amber-900 dark:text-amber-200">
              No Linked Accounts Found
            </div>
            <div className="text-sm text-amber-700 dark:text-amber-300 mt-1">
              Please link a GitHub or GitLab account from the{' '}
              <a
                href="/ade/dashboard/linked-accounts"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-amber-900 dark:hover:text-amber-100"
              >
                Linked Accounts
              </a>{' '}
              page to import from Git repositories.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4">
      {/* Error Message */}
      {errorMessage && (
        <div className="flex-shrink-0 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
            <div className="text-sm text-red-700 dark:text-red-300">{errorMessage}</div>
          </div>
        </div>
      )}

      {/* Three-Column Browser - fills remaining form height */}
      <div className="flex flex-1 min-h-0 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden bg-white dark:bg-gray-800">
        {/* Column 1: Accounts */}
        <div className="w-1/3 min-w-[200px] max-w-[300px] border-r border-gray-200 dark:border-gray-700 flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 flex-shrink-0">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Accounts
            </span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {linkedAccounts.map((account) => {
              const isSelected = selectedAccount?.id === account.id;

              return (
                <button
                  key={account.id}
                  onClick={() => !isLoading && handleSelectAccount(account)}
                  disabled={isLoading}
                  className={`w-full px-3 py-2 flex items-center gap-2 border-b border-gray-100 dark:border-gray-700 transition-colors ${
                    isSelected
                      ? 'bg-indigo-600 text-white'
                      : 'hover:bg-gray-50 dark:hover:bg-gray-700/50 text-gray-900 dark:text-gray-100'
                  } ${isLoading ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <span className={`flex-shrink-0 ${isSelected ? 'text-white' : 'text-gray-500 dark:text-gray-400'}`}>
                    {getProviderIcon(account.provider)}
                  </span>
                  <div className="flex-1 min-w-0 text-left">
                    <div className={`text-sm font-medium truncate ${isSelected ? 'text-white' : 'text-gray-900 dark:text-gray-100'}`}>
                      {account.provider.charAt(0).toUpperCase() + account.provider.slice(1)}
                    </div>
                    <div className={`text-xs truncate ${isSelected ? 'text-indigo-100' : 'text-gray-500 dark:text-gray-400'}`}>
                      {account.provider_username || account.provider_email}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Column 2: Repositories */}
        <div className="w-1/3 min-w-[200px] max-w-[300px] border-r border-gray-200 dark:border-gray-700 flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 flex-shrink-0">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Repositories
            </span>
          </div>

          {/* Search Box */}
          {selectedAccount && repositories.length > 0 && (
            <div className="p-2 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search repositories..."
                  value={repoSearchQuery}
                  onChange={(e) => setRepoSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto min-h-0">
            {!selectedAccount ? (
              <div className="flex items-center justify-center h-full p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  Select an account
                </span>
              </div>
            ) : isLoading && repositories.length === 0 ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
              </div>
            ) : repositories.length === 0 ? (
              <div className="flex items-center justify-center h-full p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  No repositories found
                </span>
              </div>
            ) : filteredRepos.length === 0 ? (
              <div className="flex items-center justify-center h-full p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  No repositories match &quot;{repoSearchQuery}&quot;
                </span>
              </div>
            ) : (
              filteredRepos.map((repo: any) => {
                const isSelected = selectedRepo?.id === repo.id;
                return (
                  <button
                    key={repo.id}
                    onClick={() => !isLoading && handleSelectRepo(repo)}
                    disabled={isLoading}
                    className={`w-full px-3 py-2 border-b border-gray-100 dark:border-gray-700 text-left transition-colors ${
                      isSelected
                        ? 'bg-indigo-600 text-white'
                        : 'hover:bg-gray-50 dark:hover:bg-gray-700/50 text-gray-900 dark:text-gray-100'
                    } ${isLoading ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                  >
                    <div className="flex items-center gap-1">
                      <span className={`text-sm font-medium flex-1 truncate ${isSelected ? 'text-white' : ''}`}>
                        {repo.name}
                      </span>
                      {repo.private && (
                        <Lock className={`h-3 w-3 flex-shrink-0 ${isSelected ? 'text-indigo-100' : 'text-gray-400'}`} />
                      )}
                    </div>
                    {repo.description && (
                      <div className={`text-xs truncate mt-0.5 ${isSelected ? 'text-indigo-100' : 'text-gray-500 dark:text-gray-400'}`}>
                        {repo.description}
                      </div>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Column 3: Files */}
        <div className="flex-1 min-w-[200px] flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 flex-shrink-0">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Files
            </span>
          </div>

          {/* Path breadcrumb */}
          {currentPath && (
            <div className="px-3 py-1.5 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/30 flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => {
                  const parentPath = currentPath.split('/').slice(0, -1).join('/');
                  handleNavigateToPath(parentPath);
                }}
                disabled={isLoading}
                className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                <ArrowLeft className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              </button>
              <span className="text-xs text-gray-500 dark:text-gray-400 truncate">
                /{currentPath}
              </span>
            </div>
          )}

          <div className="flex-1 overflow-y-auto min-h-0">
            {!selectedRepo ? (
              <div className="flex items-center justify-center h-full p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  Select a repository
                </span>
              </div>
            ) : isLoading ? (
              <div className="flex flex-col items-center justify-center py-8 gap-2">
                <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
                <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
              </div>
            ) : repoFiles.length === 0 ? (
              <div className="flex items-center justify-center h-full p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  No files found
                </span>
              </div>
            ) : (
              <>
                {/* Parent directory (..) entry when in a subdirectory */}
                {currentPath && (
                  <button
                    onClick={() => {
                      const parentPath = currentPath.split('/').slice(0, -1).join('/');
                      handleNavigateToPath(parentPath);
                    }}
                    disabled={isLoading}
                    className={`w-full px-3 py-2 border-b border-gray-100 dark:border-gray-700 flex items-center gap-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                      isLoading ? 'cursor-not-allowed' : 'cursor-pointer'
                    }`}
                  >
                    <ArrowLeft className="h-4 w-4 text-gray-400 flex-shrink-0" />
                    <span className="text-sm text-gray-900 dark:text-gray-100 font-medium">
                      ..
                    </span>
                  </button>
                )}

                {/* File and directory list */}
                {repoFiles.map((file: any, idx: number) => {
                const isOpenAPIFile =
                  file.name.includes('openapi') ||
                  file.name.includes('swagger') ||
                  file.name.endsWith('.json') ||
                  file.name.endsWith('.yaml') ||
                  file.name.endsWith('.yml');

                return (
                  <button
                    key={idx}
                    onClick={() => !isLoading && handleSelectFile(file)}
                    disabled={isLoading}
                    className={`w-full px-3 py-2 border-b border-gray-100 dark:border-gray-700 flex items-center gap-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                      isLoading ? 'cursor-not-allowed' : 'cursor-pointer'
                    }`}
                  >
                    {file.type === 'dir' ? (
                      <FolderOpen className="h-4 w-4 text-gray-400 flex-shrink-0" />
                    ) : (
                      <File className={`h-4 w-4 flex-shrink-0 ${isOpenAPIFile ? 'text-green-500' : 'text-gray-400'}`} />
                    )}
                    <span className="text-sm text-gray-900 dark:text-gray-100 truncate">
                      {file.name}
                    </span>
                  </button>
                );
              })}
              </>
            )}
          </div>
        </div>
      </div>

      {/* File Metadata Preview */}
      {fetchedContent && fileMetadata && (
        <div className="flex-shrink-0 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
            <FileCode className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
            File Preview: {fetchedFilename}
          </h3>

          <div className="space-y-4">
            {/* Unsupported Format Warning */}
            {!fileMetadata.formatSupported && fileMetadata.format !== 'unknown' && (
              <div className="p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-amber-900 dark:text-amber-200">
                      Format Not Available for Import
                    </div>
                    <div className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                      The detected format <span className="font-semibold">{fileMetadata.formatDisplayName}</span> is not yet supported for import.
                      Currently supported formats: OpenAPI 3.x, Swagger 2.x, JSON Schema, and Arazzo.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Parse Error */}
            {!fileMetadata.syntaxValid && (
              <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-red-900 dark:text-red-200">
                      File Parse Error
                    </div>
                    <div className="text-sm text-red-700 dark:text-red-300 mt-1">
                      {fileMetadata.parseError || 'Unable to parse file content'}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Metadata Grid */}
            <div className="grid grid-cols-3 gap-4">
              {/* Format */}
              <div className={`rounded-lg p-4 border ${fileMetadata.formatSupported ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'}`}>
                <div className="flex items-center gap-2 mb-2">
                  {fileMetadata.formatSupported ? (
                    <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                  ) : (
                    <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  )}
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Detected Format
                  </span>
                </div>
                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                  {fileMetadata.formatDisplayName}
                </div>
              </div>

              {/* Spec Version */}
              <div className="rounded-lg p-4 border bg-gray-50 dark:bg-gray-900/30 border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Version
                  </span>
                </div>
                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                  {fileMetadata.specVersion || fileMetadata.version || 'N/A'}
                </div>
              </div>

              {/* Syntax */}
              <div className={`rounded-lg p-4 border ${fileMetadata.syntaxValid ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'}`}>
                <div className="flex items-center gap-2 mb-2">
                  {fileMetadata.syntaxValid ? (
                    <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                  ) : (
                    <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
                  )}
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Syntax
                  </span>
                </div>
                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                  {fileMetadata.syntaxValid ? `Valid ${fileMetadata.syntax.toUpperCase()}` : 'Invalid'}
                </div>
              </div>
            </div>

            {/* Title */}
            {fileMetadata.title && (
              <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Title
                </span>
                <div className="text-base font-semibold text-gray-900 dark:text-white mt-1">
                  {fileMetadata.title}
                </div>
              </div>
            )}

            {/* Description */}
            {fileMetadata.description && (
              <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Description
                </span>
                <div className="text-sm text-gray-700 dark:text-gray-300 mt-1 leading-relaxed line-clamp-3">
                  {fileMetadata.description}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default GitImportPanel;


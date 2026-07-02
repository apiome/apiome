'use client';

import { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react';
import { Link2, Eye, EyeOff, CheckCircle2, AlertTriangle, FileCode, Globe } from 'lucide-react';
import { fetchSpecificationFromUrl, validateImportUrl, UrlImportOptions, UrlImportResult } from '../../../utils/url-import';
import { extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import { ImportSourceTabBar, type ImportSourceTabId } from './ImportSourceTabBar';

export interface UrlImportFooterState {
  canTestUrl: boolean;
  isTesting: boolean;
  urlTestedSuccessfully: boolean;
}

export interface UrlImportPanelHandle {
  testUrl: () => Promise<void>;
}

interface UrlImportPanelProps {
  onSpecificationFetched: (content: string, filename: string, metadata?: FileMetadataPreview) => void;
  /** Switch import source (same step, different panel). */
  onSelectSource?: (source: ImportSourceTabId) => void;
  onFooterStateChange?: (state: UrlImportFooterState) => void;
  /** Extra tabs to disable (e.g. SwaggerHub in class import). */
  tabDisabledIds?: ImportSourceTabId[];
}

type AuthType = 'none' | 'bearer' | 'apiKey' | 'basic';

const UrlImportPanel = forwardRef<UrlImportPanelHandle, UrlImportPanelProps>(function UrlImportPanel(
  { onSpecificationFetched, onSelectSource, onFooterStateChange, tabDisabledIds },
  ref
) {
  // Form state
  const [url, setUrl] = useState('');
  const [authType, setAuthType] = useState<AuthType>('none');
  const [token, setToken] = useState('');
  const [apiKeyHeader, setApiKeyHeader] = useState('X-API-Key');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [followRedirects, setFollowRedirects] = useState(true);
  const [resolveExternalRefs, setResolveExternalRefs] = useState(true);
  const [cacheFetched, setCacheFetched] = useState(false);
  const [saveCredentials, setSaveCredentials] = useState(false);

  // UI state
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [fetchResult, setFetchResult] = useState<UrlImportResult | null>(null);
  const [fileMetadata, setFileMetadata] = useState<FileMetadataPreview | null>(null);
  const [urlTested, setUrlTested] = useState(false);

  // Validate URL on change
  useEffect(() => {
    if (!url) {
      setUrlError(null);
      return;
    }

    const validation = validateImportUrl(url);
    if (!validation.valid) {
      setUrlError(validation.error || 'Invalid URL');
    } else {
      setUrlError(null);
    }
  }, [url]);

  // Test URL - fetches and validates but doesn't proceed to analysis
  const handleTestUrl = useCallback(async () => {
    if (!url.trim() || urlError) return;

    const options: UrlImportOptions = {
      url: url.trim(),
      authType,
      authToken: authType === 'bearer' || authType === 'apiKey' ? token : undefined,
      apiKeyHeader: authType === 'apiKey' ? apiKeyHeader : undefined,
      username: authType === 'basic' ? username : undefined,
      password: authType === 'basic' ? password : undefined,
      followRedirects,
      resolveExternalRefs,
      useCache: cacheFetched,
      timeout: 30000
    };

    setIsFetching(true);
    setFetchResult(null);
    setFileMetadata(null);
    setUrlTested(false);

    try {
      const result = await fetchSpecificationFromUrl(options);
      setFetchResult(result);

      if (result.success && result.content) {
        const metadata = extractFileMetadata(result.content);
        setFileMetadata(metadata);

        setUrlTested(true);

        onSpecificationFetched(result.content, result.filename || 'openapi-spec.yaml', metadata);
      }
    } catch (error) {
      setFetchResult({
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch specification'
      });
    } finally {
      setIsFetching(false);
    }
  }, [
    url,
    urlError,
    authType,
    token,
    apiKeyHeader,
    username,
    password,
    followRedirects,
    resolveExternalRefs,
    cacheFetched,
    onSpecificationFetched
  ]);

  useImperativeHandle(ref, () => ({
    testUrl: () => handleTestUrl(),
  }), [handleTestUrl]);

  useEffect(() => {
    onFooterStateChange?.({
      canTestUrl: Boolean(url.trim()) && !urlError,
      isTesting: isFetching,
      urlTestedSuccessfully: Boolean(urlTested && fetchResult?.success),
    });
  }, [url, urlError, isFetching, urlTested, fetchResult?.success, onFooterStateChange]);

  // Reset tested state when URL or auth changes
  useEffect(() => {
    setUrlTested(false);
    setFetchResult(null);
    setFileMetadata(null);
  }, [url, authType, token, apiKeyHeader, username, password]);

  return (
    <div className="space-y-6">
      <ImportSourceTabBar
        active="url"
        onSelect={(id) => onSelectSource?.(id)}
        disabledIds={tabDisabledIds}
      />

      {/* URL Input */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          Specification URL
        </label>
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <Globe className="h-5 w-5 text-gray-400" />
          </div>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://api.example.com/openapi.yaml"
            className={`block w-full pl-10 pr-4 py-3 text-sm rounded-lg border ${
              urlError
                ? 'border-red-500 dark:border-red-400 focus:ring-red-500 focus:border-red-500'
                : 'border-gray-300 dark:border-gray-600 focus:ring-indigo-500 focus:border-indigo-500'
            } bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500`}
          />
        </div>
        {urlError && (
          <p className="text-sm text-red-600 dark:text-red-400">{urlError}</p>
        )}
      </div>

      {/* Authentication Section */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-4">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
          <Link2 className="h-4 w-4" />
          Authentication (optional)
        </div>

        {/* Auth Type Selection */}
        <div className="flex flex-wrap gap-4">
          {(['none', 'bearer', 'apiKey', 'basic'] as AuthType[]).map((type) => (
            <label key={type} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="authType"
                value={type}
                checked={authType === type}
                onChange={(e) => setAuthType(e.target.value as AuthType)}
                className="text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-gray-700 dark:text-gray-300">
                {type === 'none' ? 'None' :
                 type === 'bearer' ? 'Bearer Token' :
                 type === 'apiKey' ? 'API Key' : 'Basic Auth'}
              </span>
            </label>
          ))}
        </div>

        {/* Bearer Token Input */}
        {authType === 'bearer' && (
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Token
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Enter your bearer token"
                className="block w-full pr-10 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center"
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4 text-gray-400" />
                ) : (
                  <Eye className="h-4 w-4 text-gray-400" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* API Key Input */}
        {authType === 'apiKey' && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Header Name
              </label>
              <input
                type="text"
                value={apiKeyHeader}
                onChange={(e) => setApiKeyHeader(e.target.value)}
                placeholder="X-API-Key"
                className="block w-full py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                API Key
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Enter your API key"
                  className="block w-full pr-10 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4 text-gray-400" />
                  ) : (
                    <Eye className="h-4 w-4 text-gray-400" />
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Basic Auth Input */}
        {authType === 'basic' && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Username"
                className="block w-full py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  className="block w-full pr-10 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4 text-gray-400" />
                  ) : (
                    <Eye className="h-4 w-4 text-gray-400" />
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Save credentials checkbox */}
        {authType !== 'none' && (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={saveCredentials}
              onChange={(e) => setSaveCredentials(e.target.checked)}
              className="rounded text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Save credentials for future imports
            </span>
          </label>
        )}
      </div>

      {/* URL Options */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
        <div className="text-sm font-medium text-gray-700 dark:text-gray-300">
          URL Options
        </div>

        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={followRedirects}
              onChange={(e) => setFollowRedirects(e.target.checked)}
              className="rounded text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Follow redirects
            </span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={resolveExternalRefs}
              onChange={(e) => setResolveExternalRefs(e.target.checked)}
              className="rounded text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Resolve external $ref URLs
            </span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={cacheFetched}
              onChange={(e) => setCacheFetched(e.target.checked)}
              className="rounded text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Cache fetched content
            </span>
          </label>
        </div>
      </div>

      {/* Fetch Result */}
      {fetchResult && !fetchResult.success && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
            <div>
              <div className="font-medium text-red-900 dark:text-red-200">
                Failed to Fetch Specification
              </div>
              <div className="text-sm text-red-700 dark:text-red-300 mt-1">
                {fetchResult.error}
                {fetchResult.statusCode && ` (HTTP ${fetchResult.statusCode})`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Fetched Metadata Preview */}
      {fetchResult?.success && fileMetadata && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
            <FileCode className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
            Specification Preview
          </h3>

          <div className="space-y-4">
            {/* Metadata Grid */}
            <div className="grid grid-cols-3 gap-4">
              {/* Format */}
              <div className={`rounded-lg p-4 border ${
                fileMetadata.formatSupported 
                  ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' 
                  : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'
              }`}>
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

              {/* Version */}
              <div className="rounded-lg p-4 border bg-gray-50 dark:bg-gray-900/30 border-gray-200 dark:border-gray-700">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  Version
                </div>
                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                  {fileMetadata.specVersion || fileMetadata.version || 'N/A'}
                </div>
              </div>

              {/* Syntax */}
              <div className={`rounded-lg p-4 border ${
                fileMetadata.syntaxValid 
                  ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' 
                  : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
              }`}>
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

      {/* Help text for next steps */}
      {urlTested && fetchResult?.success && fileMetadata?.formatSupported && (
        <div className="p-4 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
            <div>
              <div className="font-medium text-green-900 dark:text-green-200">
                URL verified successfully
              </div>
              <div className="text-sm text-green-700 dark:text-green-300 mt-1">
                Use the button in the dialog footer to continue to analysis.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default UrlImportPanel;


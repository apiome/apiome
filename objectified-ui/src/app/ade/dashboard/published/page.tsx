'use client';

import { useSession } from 'next-auth/react';
import { useEffect, useState } from 'react';
import { Eye, Lock, Globe, Copy, ExternalLink, Search, FileText, MoreVertical } from 'lucide-react';
import { getPublishedVersionsForTenant, updateVersionVisibility } from '../../../../../lib/db/helper';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { Badge } from '../../../components/ui/Badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/Select';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../../../components/ui/Tooltip';
import { cn } from '../../../../../lib/utils';
import { useDialog } from '../../../components/providers/DialogProvider';

interface PublishedVersion {
  id: string;
  version_id: string;
  description: string | null;
  visibility: 'public' | 'private';
  published_at: string;
  created_at: string;
  project_id: string;
  project_name: string;
  project_slug: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  creator_name: string;
  creator_email: string;
}

const PublishedVersions = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const [versions, setVersions] = useState<PublishedVersion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);
  const [changingVisibility, setChangingVisibility] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Dropdown state
  const [openVersionDropdown, setOpenVersionDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);

  const currentTenantId = (session?.user as any)?.current_tenant_id;

  useEffect(() => {
    loadPublishedVersions();
  }, [currentTenantId]);

  const loadPublishedVersions = async () => {
    if (!currentTenantId) { setVersions([]); setIsLoading(false); return; }
    try {
      setIsLoading(true);
      const result = await getPublishedVersionsForTenant(currentTenantId);
      setVersions(JSON.parse(result));
    } catch (error) {
      console.error('Failed to load published versions:', error);
      setVersions([]);
    } finally {
      setIsLoading(false);
    }
  };

  const getAccessUrl = (version: PublishedVersion) => `${version.tenant_slug}/${version.project_slug}/${version.version_id}`;
  const getFullAccessUrl = (version: PublishedVersion) => {
    const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
    return `${restApiBaseUrl}/schema/${getAccessUrl(version)}`;
  };
  const getSwaggerUrl = (version: PublishedVersion) => {
    const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
    return `${restApiBaseUrl}/swagger/${getAccessUrl(version)}`;
  };
  const getArazzoUrl = (version: PublishedVersion) => {
    const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
    return `${restApiBaseUrl}/arazzo/${getAccessUrl(version)}`;
  };
  const getJsonUrl = (version: PublishedVersion) => {
    const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
    return `${restApiBaseUrl}/json/${getAccessUrl(version)}`;
  };

  const handleCopyUrl = async (version: PublishedVersion) => {
    try {
      await navigator.clipboard.writeText(getFullAccessUrl(version));
      setCopiedUrl(version.id);
      setTimeout(() => setCopiedUrl(null), 2000);
    } catch (error) {
      console.error('Failed to copy URL:', error);
    }
  };

  const handleOpenUrl = (version: PublishedVersion) => window.open(getFullAccessUrl(version), '_blank');
  const handleOpenSwagger = (version: PublishedVersion) => window.open(getSwaggerUrl(version), '_blank');
  const handleOpenArazzo = (version: PublishedVersion) => window.open(getArazzoUrl(version), '_blank');
  const handleOpenJson = (version: PublishedVersion) => window.open(getJsonUrl(version), '_blank');

  const handleToggleVisibility = async (version: PublishedVersion) => {
    const newVisibility = version.visibility === 'public' ? 'private' : 'public';
    const confirmMessage = newVisibility === 'public'
      ? `Change visibility to PUBLIC?\n\nThis will make the OpenAPI Specification public without requiring an API Key.`
      : `Change visibility to PRIVATE?\n\nThis will restrict access by requiring an API Key.`;

    const confirmed = await confirmDialog({
      title: `Change Visibility to ${newVisibility.toUpperCase()}`,
      message: confirmMessage,
      variant: 'warning',
      confirmLabel: 'Change Visibility',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    try {
      setChangingVisibility(version.id);
      const result = await updateVersionVisibility(version.id, newVisibility);
      const response = JSON.parse(result);
      if (response.success) {
        setVersions(versions.map(v => v.id === version.id ? { ...v, visibility: newVisibility } : v));
      } else {
        await alertDialog({ message: `Failed to update visibility: ${response.error}`, variant: 'error' });
      }
    } catch (error) {
      await alertDialog({ message: 'An error occurred while updating visibility', variant: 'error' });
    } finally {
      setChangingVisibility(null);
    }
  };

  const formatDate = (dateString: string) => {
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  const filteredVersions = versions.filter(version => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return version.project_name.toLowerCase().includes(query) || version.version_id.toLowerCase().includes(query) || version.description?.toLowerCase().includes(query) || version.tenant_name.toLowerCase().includes(query);
  });

  if (!currentTenantId) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-amber-100 to-yellow-100 dark:from-amber-900/20 dark:to-yellow-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-900/20 dark:to-yellow-900/20 border border-amber-200 dark:border-amber-700/50 rounded-2xl p-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-yellow-500 flex items-center justify-center shadow-lg shadow-amber-500/25 flex-shrink-0">
                <Lock className="h-6 w-6 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-amber-900 dark:text-amber-100 mb-2">No Tenant Selected</h2>
                <p className="text-amber-800 dark:text-amber-200 mb-4">Please select a tenant before managing publications.</p>
                <Button asChild><a href="/ade/dashboard/tenants">Go to Tenants</a></Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const handleAction = async (action: string, version: PublishedVersion) => {
    switch (action) {
      case 'open': handleOpenUrl(version); break;
      case 'swagger': handleOpenSwagger(version); break;
      case 'arazzo': handleOpenArazzo(version); break;
      case 'json': handleOpenJson(version); break;
      case 'copy': await handleCopyUrl(version); break;
      case 'visibility': await handleToggleVisibility(version); break;
    }
  };

  return (
    <TooltipProvider>
      <div className="p-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/25">
            <Eye className="h-7 w-7 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">Published Versions</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">View all published and locked versions with their access URLs and visibility settings.</p>
          </div>
        </div>

        {/* Search */}
        <div className="mb-6 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search by project name, version, or description..." className="pl-10" />
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="flex flex-col items-center gap-3">
              <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
              <div className="text-gray-500 dark:text-gray-400">Loading published versions...</div>
            </div>
          </div>
        ) : versions.length === 0 ? (
          <div className="relative">
            <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-blue-100 to-indigo-100 dark:from-blue-900/20 dark:to-indigo-900/20 rounded-full blur-3xl opacity-60" />
            <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
            <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
              <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-2xl flex items-center justify-center shadow-lg shadow-blue-500/30">
                <Eye className="h-10 w-10 text-white" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No Published Versions</h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">You don't have any published versions yet. Publish a version to make it available via API.</p>
            </div>
          </div>
        ) : filteredVersions.length === 0 ? (
          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-gray-400 to-gray-500 rounded-2xl flex items-center justify-center shadow-lg shadow-gray-500/30">
              <Search className="h-10 w-10 text-white" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No Matching Versions</h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">No published versions match your search query.</p>
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100 dark:divide-gray-700">
                <thead className="bg-gradient-to-r from-gray-50 to-slate-50 dark:from-gray-900 dark:to-gray-800">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Project / Version</th>
                    <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Visibility</th>
                    <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Access URL</th>
                    <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Published</th>
                    <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
                  {filteredVersions.map((version) => (
                    <tr key={version.id} className="hover:bg-indigo-50/50 dark:hover:bg-indigo-900/10 transition-all duration-200">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex flex-col">
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">{version.project_name}</div>
                          <div className="text-sm text-gray-500 dark:text-gray-400 flex items-center gap-2 mt-0.5">
                            <span className="font-mono font-medium text-indigo-600 dark:text-indigo-400">v{version.version_id}</span>
                            <div className="p-0.5 bg-blue-100 dark:bg-blue-900/30 rounded"><Lock className="h-3 w-3 text-blue-600 dark:text-blue-400" /></div>
                          </div>
                          {version.description && <div className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 max-w-xs truncate">{version.description}</div>}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button onClick={() => handleToggleVisibility(version)} disabled={changingVisibility === version.id} className="cursor-pointer">
                              {version.visibility === 'public' ? (
                                <Badge variant="success" className="flex items-center gap-1"><Globe className="h-3 w-3" />Public</Badge>
                              ) : (
                                <Badge variant="secondary" className="flex items-center gap-1"><Lock className="h-3 w-3" />Private</Badge>
                              )}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>Click to change to {version.visibility === 'public' ? 'private' : 'public'}</TooltipContent>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4">
                        <code className="text-xs bg-gray-50 dark:bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 font-mono max-w-md truncate block">
                          schema/{getAccessUrl(version)}
                        </code>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-900 dark:text-gray-100">{formatDate(version.published_at)}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">by {version.creator_name}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <div className="relative">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                              setDropdownPosition({
                                top: rect.bottom + 4,
                                right: window.innerWidth - rect.right
                              });
                              setOpenVersionDropdown(openVersionDropdown === version.id ? null : version.id);
                            }}
                            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors text-gray-400 hover:text-gray-600 dark:hover:text-white"
                            title="Actions"
                          >
                            <MoreVertical className="h-4 w-4" />
                          </button>

                          {openVersionDropdown === version.id && dropdownPosition && (
                            <>
                              <div
                                className="fixed inset-0 z-10"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                }}
                              />
                              <div
                                className="fixed w-52 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20"
                                style={{
                                  top: `${dropdownPosition.top}px`,
                                  right: `${dropdownPosition.right}px`
                                }}>
                                <div className="py-1">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('open', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    <ExternalLink className="w-4 h-4 text-blue-500" />
                                    View OpenAPI
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('arazzo', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    <FileText className="w-4 h-4 text-orange-500" />
                                    View Arazzo
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('json', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    <FileText className="w-4 h-4 text-orange-500" />
                                    View JSON Schema
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('swagger', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    <FileText className="w-4 h-4 text-purple-500" />
                                    Swagger UI
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('copy', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    <Copy className="w-4 h-4 text-blue-500" />
                                    Copy URL
                                  </button>
                                  <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenVersionDropdown(null);
                                      handleAction('visibility', version);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                  >
                                    {version.visibility === 'public' ? (
                                      <>
                                        <Lock className="w-4 h-4 text-gray-500" />
                                        Make Private
                                      </>
                                    ) : (
                                      <>
                                        <Globe className="w-4 h-4 text-green-500" />
                                        Make Public
                                      </>
                                    )}
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {versions.length > 0 && (
          <div className="mt-4 text-sm text-gray-600 dark:text-gray-400">
            Showing {filteredVersions.length} of {versions.length} published {versions.length === 1 ? 'version' : 'versions'}
            {searchQuery && filteredVersions.length < versions.length && <span className="ml-2 text-blue-600 dark:text-blue-400">(filtered)</span>}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
};

export default PublishedVersions;


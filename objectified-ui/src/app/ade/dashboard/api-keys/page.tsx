'use client';

import { useSession } from 'next-auth/react';
import { getApiKeysForTenant, createApiKey, deleteApiKey, toggleApiKeyStatus } from '../../../../../lib/db/helper';
import { useEffect, useState } from 'react';
import { Plus, Trash2, Key, Copy, Check, AlertCircle } from 'lucide-react';
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
import { Textarea } from '../../../components/ui/Textarea';
import { Card, CardContent } from '../../../components/ui/Card';
import { Switch } from '../../../components/ui/Switch';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../../../components/ui/Tooltip';
import { cn } from '../../../../../lib/utils';
import { useDialog } from '../../../components/providers/DialogProvider';

interface ApiKey {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  key_prefix: string;
  last_used_at: string | null;
  expires_at: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

const ApiKeys = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog } = useDialog();
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [newApiKeyName, setNewApiKeyName] = useState('');
  const [newApiKeyDescription, setNewApiKeyDescription] = useState('');
  const [newApiKeyExpiry, setNewApiKeyExpiry] = useState('');
  const [generatedApiKey, setGeneratedApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [copiedKey, setCopiedKey] = useState(false);

  const currentTenantId = (session?.user as any)?.current_tenant_id;

  useEffect(() => {
    if (currentTenantId) {
      loadApiKeys();
    }
  }, [currentTenantId]);

  const loadApiKeys = async () => {
    if (!currentTenantId) return;
    const result = await getApiKeysForTenant(currentTenantId);
    setApiKeys(JSON.parse(result));
  };

  const handleCreateApiKey = () => {
    setNewApiKeyName('');
    setNewApiKeyDescription('');
    setNewApiKeyExpiry('');
    setErrorMessage('');
    setShowCreateModal(true);
  };

  const handleCreateSubmit = async () => {
    if (!newApiKeyName.trim()) {
      setErrorMessage('API key name is required');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');

    try {
      const expiresInDays = newApiKeyExpiry ? parseInt(newApiKeyExpiry) : null;
      const result = await createApiKey(currentTenantId, newApiKeyName, newApiKeyDescription, expiresInDays);
      const response = JSON.parse(result);

      if (response.success) {
        setGeneratedApiKey(response.apiKey);
        setShowCreateModal(false);
        setShowApiKeyModal(true);
        await loadApiKeys();
      } else {
        setErrorMessage(response.error || 'Failed to create API key');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'Failed to create API key');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteClick = async (apiKey: ApiKey) => {
    const confirmed = await confirmDialog({
      title: 'Delete API Key',
      message: `Are you sure you want to delete the API key "${apiKey.name}"? This action cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteApiKey(apiKey.id);
      const response = JSON.parse(result);
      if (response.success) {
        await loadApiKeys();
      }
    } catch (error: any) {
      console.error('Failed to delete API key:', error.message);
    }
  };

  const handleToggleStatus = async (apiKey: ApiKey, nextEnabled: boolean) => {
    try {
      if (!nextEnabled) {
        const confirmed = await confirmDialog({
          title: 'Disable API Key',
          message: `Are you sure you want to disable "${apiKey.name}"? This will immediately block all requests using this key.`,
          variant: 'warning',
          confirmLabel: 'Disable',
          cancelLabel: 'Cancel',
        });
        if (!confirmed) {
          setApiKeys((prev) => prev.slice());
          return;
        }
      }

      const result = await toggleApiKeyStatus(apiKey.id, nextEnabled);
      const response = JSON.parse(result);
      if (response.success) {
        await loadApiKeys();
      }
    } catch (error) {
      console.error('Failed to toggle API key status:', error);
    }
  };

  const handleCopyKey = async () => {
    try {
      await navigator.clipboard.writeText(generatedApiKey);
      setCopiedKey(true);
      setTimeout(() => setCopiedKey(false), 2000);
    } catch (error) {
      console.error('Failed to copy API key:', error);
    }
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Never';
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  const isExpired = (expiresAt: string | null) => {
    if (!expiresAt) return false;
    return new Date(expiresAt) < new Date();
  };

  if (!currentTenantId) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-amber-100 to-yellow-100 dark:from-amber-900/20 dark:to-yellow-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-900/20 dark:to-yellow-900/20 border border-amber-200 dark:border-amber-700/50 rounded-2xl p-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-yellow-500 flex items-center justify-center shadow-lg shadow-amber-500/25 flex-shrink-0">
                <AlertCircle className="h-6 w-6 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-amber-900 dark:text-amber-100 mb-2">No Tenant Selected</h2>
                <p className="text-amber-800 dark:text-amber-200 mb-4">Please select a tenant before managing API Keys.</p>
                <Button asChild>
                  <a href="/ade/dashboard/tenants" className="inline-flex items-center gap-2">
                    Go to Tenants
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </a>
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="p-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shadow-lg shadow-amber-500/25">
              <Key className="h-7 w-7 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">API Keys</h1>
              <p className="text-gray-500 dark:text-gray-300 mt-1">Manage API keys for external REST API access</p>
            </div>
          </div>
          <Button onClick={handleCreateApiKey} className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600">
            <Plus className="h-5 w-5" />
            Create API Key
          </Button>
        </div>

        {/* API Keys List */}
        <div className="space-y-4">
          {apiKeys.length === 0 ? (
            <div className="relative">
              <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/20 dark:to-orange-900/20 rounded-full blur-3xl opacity-60" />
              <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-gradient-to-br from-orange-100 to-yellow-100 dark:from-orange-900/20 dark:to-yellow-900/20 rounded-full blur-3xl opacity-60" />
              <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
                <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-amber-500 to-orange-600 rounded-2xl flex items-center justify-center shadow-lg shadow-amber-500/30">
                  <Key className="h-10 w-10 text-white" />
                </div>
                <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No API Keys Yet</h3>
                <p className="text-gray-500 dark:text-gray-300 max-w-md mx-auto">Create your first API key to access your tenant data via REST API</p>
              </div>
            </div>
          ) : (
            apiKeys.map((apiKey) => (
              <Card
                key={apiKey.id}
                className={cn(
                  'transition-all duration-200 hover:border-amber-300 hover:shadow-lg hover:shadow-amber-500/10',
                  isExpired(apiKey.expires_at) && 'border-red-200 dark:border-red-800 bg-red-50/30 dark:bg-red-900/10',
                  !apiKey.enabled && !isExpired(apiKey.expires_at) && 'bg-gray-50 dark:bg-gray-800/50'
                )}
              >
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/30 dark:to-orange-900/30 flex items-center justify-center">
                          <Key className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                        </div>
                        <h3 className="text-lg font-bold text-gray-900 dark:text-white">{apiKey.name}</h3>
                        {isExpired(apiKey.expires_at) && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300 border border-red-200 dark:border-red-700">
                            <AlertCircle className="h-3 w-3" />Expired
                          </span>
                        )}
                        {!apiKey.enabled && !isExpired(apiKey.expires_at) && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-600">
                            <span className="w-1.5 h-1.5 rounded-full bg-gray-400"></span>Disabled
                          </span>
                        )}
                        {apiKey.enabled && !isExpired(apiKey.expires_at) && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-700">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>Active
                          </span>
                        )}
                      </div>

                      {apiKey.description && (
                        <p className="text-sm text-gray-500 dark:text-gray-300 mb-4 ml-13">{apiKey.description}</p>
                      )}

                      <div className="grid grid-cols-2 gap-4 text-sm ml-13">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">Key Prefix:</span>
                          <span className="font-mono bg-gray-100 dark:bg-gray-700 px-2.5 py-1 rounded-lg text-gray-900 dark:text-gray-100 text-xs">{apiKey.key_prefix}...</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">Last Used:</span>
                          <span className="text-gray-600 dark:text-gray-300">{formatDate(apiKey.last_used_at)}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">Created:</span>
                          <span className="text-gray-600 dark:text-gray-300">{formatDate(apiKey.created_at)}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">Expires:</span>
                          <span className={isExpired(apiKey.expires_at) ? 'text-red-600 dark:text-red-400 font-semibold' : 'text-gray-600 dark:text-gray-300'}>
                            {apiKey.expires_at ? formatDate(apiKey.expires_at) : 'Never'}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4 ml-4">
                      <div className="flex items-center gap-2">
                        <Switch checked={apiKey.enabled} onCheckedChange={(checked) => handleToggleStatus(apiKey, checked)} />
                        <span className="text-sm font-medium text-gray-600 dark:text-gray-300">{apiKey.enabled ? 'Enabled' : 'Disabled'}</span>
                      </div>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button onClick={() => handleDeleteClick(apiKey)} className="p-2 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors">
                            <Trash2 className="h-4 w-4 text-gray-400 hover:text-red-500 transition-colors" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>Delete API Key</TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        {/* Create API Key Modal */}
        <Dialog open={showCreateModal} onOpenChange={setShowCreateModal}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/30 dark:to-orange-900/30">
                  <Key className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                </div>
                Create API Key
              </DialogTitle>
              <DialogDescription>Create a new API key for REST API access</DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
              <div className="space-y-2">
                <Label htmlFor="keyName">Name *</Label>
                <Input id="keyName" value={newApiKeyName} onChange={(e) => setNewApiKeyName(e.target.value)} placeholder="My API Key" autoFocus />
                <p className="text-xs text-gray-500 dark:text-gray-400">A descriptive name for this API key</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="keyDescription">Description</Label>
                <Textarea id="keyDescription" value={newApiKeyDescription} onChange={(e) => setNewApiKeyDescription(e.target.value)} placeholder="What is this key used for?" rows={3} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="keyExpiry">Expires In (Days)</Label>
                <Input id="keyExpiry" type="number" value={newApiKeyExpiry} onChange={(e) => setNewApiKeyExpiry(e.target.value)} placeholder="Leave empty for no expiration" min={1} />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowCreateModal(false)} disabled={isLoading}>Cancel</Button>
              <Button onClick={handleCreateSubmit} disabled={isLoading} className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600">
                {isLoading ? 'Creating...' : 'Create API Key'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Show Generated API Key Modal */}
        <Dialog open={showApiKeyModal} onOpenChange={(open) => { if (!open) { setShowApiKeyModal(false); setGeneratedApiKey(''); setCopiedKey(false); } }}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-gradient-to-br from-emerald-100 to-teal-100 dark:from-emerald-900/30 dark:to-teal-900/30">
                  <Check className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                API Key Created Successfully
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <Alert variant="warning">
                <strong>Important:</strong> This is the only time you'll see this API key. Please copy it now and store it securely.
              </Alert>
              <div className="p-4 rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 border border-amber-200 dark:border-amber-700">
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">Your API Key:</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-white dark:bg-gray-900 p-4 rounded-xl border border-gray-200 dark:border-gray-700 font-mono text-sm break-all text-gray-900 dark:text-gray-100">
                    {generatedApiKey}
                  </code>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button onClick={handleCopyKey} className={cn("p-3 rounded-xl transition-colors", copiedKey ? "bg-emerald-100 dark:bg-emerald-900/30" : "bg-amber-100 dark:bg-amber-900/30 hover:bg-amber-200 dark:hover:bg-amber-800/30")}>
                        {copiedKey ? <Check className="h-5 w-5 text-emerald-600" /> : <Copy className="h-5 w-5 text-amber-600" />}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>{copiedKey ? 'Copied!' : 'Copy to clipboard'}</TooltipContent>
                  </Tooltip>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="success" onClick={() => { setShowApiKeyModal(false); setGeneratedApiKey(''); setCopiedKey(false); }}>
                I've Saved My Key
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
};

export default ApiKeys;


'use client';

import { useSession } from 'next-auth/react';
import { getApiKeysForTenant, createApiKey, deleteApiKey, toggleApiKeyStatus } from '../../../../../lib/db/helper';
import { useEffect, useState } from 'react';
import { Plus, Trash2, Key, Copy, Check, AlertCircle } from 'lucide-react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Alert from '@mui/material/Alert';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';

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
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<ApiKey | null>(null);
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
      const result = await createApiKey(
        currentTenantId,
        newApiKeyName,
        newApiKeyDescription,
        expiresInDays
      );

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

  const handleDeleteClick = (apiKey: ApiKey) => {
    setSelectedApiKey(apiKey);
    setErrorMessage('');
    setShowDeleteModal(true);
  };

  const handleDeleteConfirm = async () => {
    if (!selectedApiKey) return;

    setIsLoading(true);
    setErrorMessage('');

    try {
      const result = await deleteApiKey(selectedApiKey.id);
      const response = JSON.parse(result);

      if (response.success) {
        setShowDeleteModal(false);
        await loadApiKeys();
      } else {
        setErrorMessage(response.error || 'Failed to delete API key');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'Failed to delete API key');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleStatus = async (apiKey: ApiKey) => {
    try {
      const result = await toggleApiKeyStatus(apiKey.id, !apiKey.enabled);
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
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  const isExpired = (expiresAt: string | null) => {
    if (!expiresAt) return false;
    return new Date(expiresAt) < new Date();
  };

  if (!currentTenantId) {
    return (
      <div className="p-8">
        <Alert severity="warning">
          Please select a tenant to manage API keys.
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">API Keys</h1>
          <p className="text-gray-600">
            Manage API keys for external REST API access to your tenant data
          </p>
        </div>
        <Button
          variant="contained"
          startIcon={<Plus size={20} />}
          onClick={handleCreateApiKey}
        >
          Create API Key
        </Button>
      </div>

      {/* API Keys List */}
      <div className="space-y-4">
        {apiKeys.length === 0 ? (
          <Card>
            <CardContent className="text-center py-12">
              <Key size={48} className="mx-auto mb-4 text-gray-400" />
              <Typography variant="h6" gutterBottom>
                No API Keys Yet
              </Typography>
              <Typography variant="body2" color="text.secondary" className="mb-4">
                Create your first API key to access your tenant data via REST API
              </Typography>
              <Box sx={{ mt: '20px' }}>
                <Button
                  variant="contained"
                  startIcon={<Plus size={20} />}
                  onClick={handleCreateApiKey}
                >
                  Create API Key
                </Button>
              </Box>
            </CardContent>
          </Card>
        ) : (
          apiKeys.map((apiKey) => (
            <Card key={apiKey.id} className={isExpired(apiKey.expires_at) ? 'border-red-200' : ''}>
              <CardContent>
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <Key size={20} className="text-gray-500" />
                      <h3 className="text-lg font-semibold">{apiKey.name}</h3>
                      {isExpired(apiKey.expires_at) && (
                        <span className="px-2 py-1 bg-red-100 text-red-800 text-xs rounded-full flex items-center gap-1">
                          <AlertCircle size={12} />
                          Expired
                        </span>
                      )}
                      {!apiKey.enabled && (
                        <span className="px-2 py-1 bg-gray-100 text-gray-800 text-xs rounded-full">
                          Disabled
                        </span>
                      )}
                    </div>

                    {apiKey.description && (
                      <p className="text-sm text-gray-600 mb-3">{apiKey.description}</p>
                    )}

                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-gray-500">Key Prefix:</span>
                        <span className="ml-2 font-mono bg-gray-100 px-2 py-1 rounded">
                          {apiKey.key_prefix}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-500">Last Used:</span>
                        <span className="ml-2">{formatDate(apiKey.last_used_at)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Created:</span>
                        <span className="ml-2">{formatDate(apiKey.created_at)}</span>
                      </div>
                      <div>
                        <span className="text-gray-500">Expires:</span>
                        <span className="ml-2">
                          {apiKey.expires_at ? (
                            <span className={isExpired(apiKey.expires_at) ? 'text-red-600 font-semibold' : ''}>
                              {formatDate(apiKey.expires_at)}
                            </span>
                          ) : (
                            'Never'
                          )}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <FormControlLabel
                      control={
                        <Switch
                          checked={apiKey.enabled}
                          onChange={() => handleToggleStatus(apiKey)}
                          color="primary"
                        />
                      }
                      label={apiKey.enabled ? 'Enabled' : 'Disabled'}
                    />
                    <Tooltip title="Delete API Key">
                      <IconButton
                        onClick={() => handleDeleteClick(apiKey)}
                        color="error"
                        size="small"
                      >
                        <Trash2 size={18} />
                      </IconButton>
                    </Tooltip>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Create API Key Modal */}
      <Dialog open={showCreateModal} onClose={() => setShowCreateModal(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create API Key</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" className="mb-4">
              {errorMessage}
            </Alert>
          )}

          <TextField
            autoFocus
            margin="dense"
            label="Name"
            type="text"
            fullWidth
            required
            value={newApiKeyName}
            onChange={(e) => setNewApiKeyName(e.target.value)}
            helperText="A descriptive name for this API key"
            className="mb-4"
          />

          <TextField
            margin="dense"
            label="Description"
            type="text"
            fullWidth
            multiline
            rows={3}
            value={newApiKeyDescription}
            onChange={(e) => setNewApiKeyDescription(e.target.value)}
            helperText="Optional description of what this key is used for"
            className="mb-4"
          />

          <TextField
            margin="dense"
            label="Expires In (Days)"
            type="number"
            fullWidth
            value={newApiKeyExpiry}
            onChange={(e) => setNewApiKeyExpiry(e.target.value)}
            helperText="Leave empty for no expiration"
            slotProps={{
              htmlInput: { min: 1 }
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowCreateModal(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleCreateSubmit} variant="contained" disabled={isLoading}>
            {isLoading ? 'Creating...' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Show Generated API Key Modal */}
      <Dialog
        open={showApiKeyModal}
        onClose={() => {
          setShowApiKeyModal(false);
          setGeneratedApiKey('');
          setCopiedKey(false);
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>API Key Created Successfully</DialogTitle>
        <DialogContent>
          <Alert severity="warning" className="mb-4">
            <strong>Important:</strong> This is the only time you'll see this API key. Please copy it now and store it securely.
          </Alert>

          <Box className="bg-gray-50 p-4 rounded-lg border border-gray-200">
            <Typography variant="body2" color="text.secondary" className="mb-2">
              Your API Key:
            </Typography>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-white p-3 rounded border border-gray-300 font-mono text-sm break-all">
                {generatedApiKey}
              </code>
              <Tooltip title={copiedKey ? 'Copied!' : 'Copy to clipboard'}>
                <IconButton onClick={handleCopyKey} color="primary">
                  {copiedKey ? <Check size={20} /> : <Copy size={20} />}
                </IconButton>
              </Tooltip>
            </div>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setShowApiKeyModal(false);
              setGeneratedApiKey('');
              setCopiedKey(false);
            }}
            variant="contained"
          >
            I've Saved My Key
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Modal */}
      <Dialog open={showDeleteModal} onClose={() => setShowDeleteModal(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Delete API Key</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" className="mb-4">
              {errorMessage}
            </Alert>
          )}

          <Alert severity="warning" className="mb-4">
            Are you sure you want to delete the API key "{selectedApiKey?.name}"? This action cannot be undone and will immediately revoke access for any applications using this key.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowDeleteModal(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleDeleteConfirm} variant="contained" color="error" disabled={isLoading}>
            {isLoading ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default ApiKeys;


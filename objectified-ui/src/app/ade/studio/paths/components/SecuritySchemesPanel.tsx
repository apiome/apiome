'use client';

import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import IconButton from '@mui/material/IconButton';
import { Add, Delete, Edit, Lock, VpnKey } from '@mui/icons-material';
import * as Dialog from '@radix-ui/react-dialog';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getSecuritySchemesForVersion,
  createApiKeySecurityScheme,
  updateApiKeySecurityScheme,
  createHttpSecurityScheme,
  updateHttpSecurityScheme,
  createOAuth2SecurityScheme,
  updateOAuth2SecurityScheme,
  deleteSecurityScheme,
  type SecuritySchemeRecord,
  type ApiKeySchemeInput,
  type HttpSchemeInput,
  type OAuth2SchemeInput,
  type OAuth2FlowConfig,
} from '../../../../../../lib/db/helper-security-schemes';
import { useDarkMode } from '../../../../hooks/useDarkMode';

const API_KEY_IN_OPTIONS: { value: 'header' | 'query' | 'cookie'; label: string }[] = [
  { value: 'header', label: 'Header' },
  { value: 'query', label: 'Query' },
  { value: 'cookie', label: 'Cookie' },
];

const HTTP_SCHEME_OPTIONS: { value: 'basic' | 'bearer' | 'custom'; label: string }[] = [
  { value: 'basic', label: 'Basic' },
  { value: 'bearer', label: 'Bearer' },
  { value: 'custom', label: 'Custom (e.g. Digest)' },
];

/** OAuth2 flow form entry (scopes as array for editing) */
type OAuth2FlowFormEntry = {
  enabled: boolean;
  authorizationUrl: string;
  tokenUrl: string;
  refreshUrl: string;
  scopes: { name: string; description: string }[];
};

const DEFAULT_OAUTH2_FLOW: OAuth2FlowFormEntry = {
  enabled: false,
  authorizationUrl: '',
  tokenUrl: '',
  refreshUrl: '',
  scopes: [],
};

function getDefaultOAuth2Flows(): Record<OAuth2FlowType, OAuth2FlowFormEntry> {
  return {
    authorizationCode: { ...DEFAULT_OAUTH2_FLOW, scopes: [] },
    implicit: { ...DEFAULT_OAUTH2_FLOW, scopes: [] },
    clientCredentials: { ...DEFAULT_OAUTH2_FLOW, scopes: [] },
    password: { ...DEFAULT_OAUTH2_FLOW, scopes: [] },
  };
}

function oauth2FlowFromData(flow: OAuth2FlowConfig | undefined): OAuth2FlowFormEntry {
  if (!flow) return { ...DEFAULT_OAUTH2_FLOW };
  const scopes = flow.scopes && typeof flow.scopes === 'object'
    ? Object.entries(flow.scopes).map(([name, description]) => ({ name, description: description || '' }))
    : [];
  return {
    enabled: true,
    authorizationUrl: (flow.authorizationUrl as string) || '',
    tokenUrl: (flow.tokenUrl as string) || '',
    refreshUrl: (flow.refreshUrl as string) || '',
    scopes,
  };
}

type OAuth2FlowType = 'authorizationCode' | 'implicit' | 'clientCredentials' | 'password';

function oauth2FlowToConfig(entry: OAuth2FlowFormEntry, flowType: OAuth2FlowType): OAuth2FlowConfig | undefined {
  if (!entry.enabled) return undefined;
  const scopes: Record<string, string> = {};
  entry.scopes.forEach(({ name, description }) => {
    const n = name.trim();
    if (n) scopes[n] = description.trim();
  });
  const authUrl = entry.authorizationUrl?.trim();
  const tokenUrl = entry.tokenUrl?.trim();
  const refreshUrl = entry.refreshUrl?.trim();
  if (flowType === 'authorizationCode' && authUrl && tokenUrl) {
    return { authorizationUrl: authUrl, tokenUrl, refreshUrl: refreshUrl || undefined, scopes };
  }
  if (flowType === 'implicit' && authUrl) {
    return { authorizationUrl: authUrl, refreshUrl: refreshUrl || undefined, scopes };
  }
  if ((flowType === 'clientCredentials' || flowType === 'password') && tokenUrl) {
    return { tokenUrl, refreshUrl: refreshUrl || undefined, scopes };
  }
  return undefined;
}

/** Scheme types: supported now vs coming soon. Used in Add dialog type selector. */
const SCHEME_TYPE_OPTIONS: { value: string; label: string; supported: boolean }[] = [
  { value: 'apiKey', label: 'API Key (header, query, cookie)', supported: true },
  { value: 'http', label: 'HTTP (Basic, Bearer, custom)', supported: true },
  { value: 'oauth2', label: 'OAuth 2.0', supported: true },
  { value: 'openIdConnect', label: 'OpenID Connect', supported: false },
  { value: 'mutualTLS', label: 'Mutual TLS', supported: false },
];

export default function SecuritySchemesPanel({ onRefresh }: { onRefresh?: () => void }) {
  const { selectedVersionId } = useStudio();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const isDark = useDarkMode();
  const [schemes, setSchemes] = useState<SecuritySchemeRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogSchemeType, setDialogSchemeType] = useState<string>('apiKey');
  const [editingScheme, setEditingScheme] = useState<SecuritySchemeRecord | null>(null);
  const [formData, setFormData] = useState<ApiKeySchemeInput>({
    scheme_name: '',
    in_location: 'header',
    param_name: 'X-API-Key',
    description: '',
  });
  const [httpFormData, setHttpFormData] = useState<{
    scheme_name: string;
    http_scheme: 'basic' | 'bearer' | string;
    http_scheme_kind: 'basic' | 'bearer' | 'custom';
    custom_http_scheme: string;
    bearer_format: string;
    description: string;
  }>({
    scheme_name: '',
    http_scheme: 'basic',
    http_scheme_kind: 'basic',
    custom_http_scheme: 'Digest',
    bearer_format: '',
    description: '',
  });
  const [oauth2FormData, setOAuth2FormData] = useState<{
    scheme_name: string;
    description: string;
    flows: Record<OAuth2FlowType, OAuth2FlowFormEntry>;
  }>({
    scheme_name: '',
    description: '',
    flows: getDefaultOAuth2Flows(),
  });

  const loadSchemes = async () => {
    if (!selectedVersionId) {
      setSchemes([]);
      return;
    }
    setIsLoading(true);
    try {
      const data = await getSecuritySchemesForVersion(selectedVersionId);
      setSchemes(data);
    } catch (err) {
      console.error('Error loading security schemes:', err);
      setSchemes([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSchemes();
  }, [selectedVersionId]);

  const resetForm = () => {
    setFormData({
      scheme_name: '',
      in_location: 'header',
      param_name: 'X-API-Key',
      description: '',
    });
    setHttpFormData({
      scheme_name: '',
      http_scheme: 'basic',
      http_scheme_kind: 'basic',
      custom_http_scheme: 'Digest',
      bearer_format: '',
      description: '',
    });
    setOAuth2FormData({
      scheme_name: '',
      description: '',
      flows: getDefaultOAuth2Flows(),
    });
    setEditingScheme(null);
  };

  const handleAdd = () => {
    resetForm();
    setDialogSchemeType('apiKey');
    setDialogOpen(true);
  };

  const handleEdit = (scheme: SecuritySchemeRecord) => {
    if (scheme.scheme_type === 'apiKey') {
      setFormData({
        scheme_name: scheme.scheme_name,
        in_location: (scheme.in_location as 'header' | 'query' | 'cookie') || 'header',
        param_name: scheme.param_name || 'X-API-Key',
        description: scheme.description || '',
      });
      setDialogSchemeType('apiKey');
    } else if (scheme.scheme_type === 'http') {
      const httpScheme = scheme.http_scheme || 'basic';
      const kind: 'basic' | 'bearer' | 'custom' =
        httpScheme === 'basic' ? 'basic' : httpScheme === 'bearer' ? 'bearer' : 'custom';
      const bearerFormat = (scheme.data as { bearerFormat?: string })?.bearerFormat || '';
      setHttpFormData({
        scheme_name: scheme.scheme_name,
        http_scheme: kind === 'custom' ? httpScheme : kind,
        http_scheme_kind: kind,
        custom_http_scheme: kind === 'custom' ? httpScheme : 'Digest',
        bearer_format: bearerFormat,
        description: scheme.description || '',
      });
      setDialogSchemeType('http');
    } else if (scheme.scheme_type === 'oauth2') {
      const data = scheme.data as { flows?: Record<string, OAuth2FlowConfig> };
      const flows = data?.flows || {};
      setOAuth2FormData({
        scheme_name: scheme.scheme_name,
        description: scheme.description || '',
        flows: {
          authorizationCode: oauth2FlowFromData(flows.authorizationCode),
          implicit: oauth2FlowFromData(flows.implicit),
          clientCredentials: oauth2FlowFromData(flows.clientCredentials),
          password: oauth2FlowFromData(flows.password),
        },
      });
      setDialogSchemeType('oauth2');
    } else return;
    setEditingScheme(scheme);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!selectedVersionId) return;

    if (dialogSchemeType === 'apiKey') {
      const name = formData.scheme_name.trim();
      const paramName = formData.param_name.trim();
      if (!name || !paramName) {
        await alertDialog({
          title: 'Validation Error',
          message: 'Scheme name and parameter name are required.',
          variant: 'error',
        });
        return;
      }
      try {
        if (editingScheme) {
          const result = await updateApiKeySecurityScheme(editingScheme.id, formData);
          if (result.success && result.scheme) {
            setSchemes(prev =>
              prev.map(s => (s.id === editingScheme.id ? result.scheme! : s))
            );
            setDialogOpen(false);
            resetForm();
            onRefresh?.();
          } else {
            await alertDialog({
              title: 'Error',
              message: result.error || 'Failed to update scheme',
              variant: 'error',
            });
          }
        } else {
          const result = await createApiKeySecurityScheme(selectedVersionId, formData);
          if (result.success && result.scheme) {
            setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
            setDialogOpen(false);
            resetForm();
            onRefresh?.();
          } else {
            await alertDialog({
              title: 'Error',
              message: result.error || 'Failed to create scheme',
              variant: 'error',
            });
          }
        }
      } catch (err) {
        console.error('Error saving security scheme:', err);
        await alertDialog({
          title: 'Error',
          message: err instanceof Error ? err.message : 'Failed to save',
          variant: 'error',
        });
      }
      return;
    }

    // HTTP scheme
    const name = httpFormData.scheme_name.trim();
    const httpSchemeValue =
      httpFormData.http_scheme_kind === 'custom'
        ? httpFormData.custom_http_scheme.trim()
        : httpFormData.http_scheme_kind;
    if (!name || !httpSchemeValue) {
      await alertDialog({
        title: 'Validation Error',
        message: 'Scheme name and HTTP scheme are required.',
        variant: 'error',
      });
      return;
    }
    const httpInput: HttpSchemeInput = {
      scheme_name: name,
      http_scheme: httpSchemeValue,
      description: httpFormData.description || undefined,
    };
    if (httpFormData.http_scheme_kind === 'bearer' && httpFormData.bearer_format.trim()) {
      httpInput.bearer_format = httpFormData.bearer_format.trim();
    }
    try {
      if (editingScheme) {
        const result = await updateHttpSecurityScheme(editingScheme.id, httpInput);
        if (result.success && result.scheme) {
          setSchemes(prev =>
            prev.map(s => (s.id === editingScheme.id ? result.scheme! : s))
          );
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          await alertDialog({
            title: 'Error',
            message: result.error || 'Failed to update scheme',
            variant: 'error',
          });
        }
      } else {
        const result = await createHttpSecurityScheme(selectedVersionId, httpInput);
        if (result.success && result.scheme) {
          setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          await alertDialog({
            title: 'Error',
            message: result.error || 'Failed to create scheme',
            variant: 'error',
          });
        }
      }
    } catch (err) {
      console.error('Error saving security scheme:', err);
      await alertDialog({
        title: 'Error',
        message: err instanceof Error ? err.message : 'Failed to save',
        variant: 'error',
      });
    }
    return;
  if (dialogSchemeType === 'oauth2') {
    const name = oauth2FormData.scheme_name.trim();
    if (!name) {
      await alertDialog({
        title: 'Validation Error',
        message: 'Scheme name is required.',
        variant: 'error',
      });
      return;
    }
    const flows: OAuth2SchemeInput['flows'] = {};
    const ac = oauth2FlowToConfig(oauth2FormData.flows.authorizationCode, 'authorizationCode');
    if (ac) flows.authorizationCode = ac;
    const im = oauth2FlowToConfig(oauth2FormData.flows.implicit, 'implicit');
    if (im) flows.implicit = im;
    const cc = oauth2FlowToConfig(oauth2FormData.flows.clientCredentials, 'clientCredentials');
    if (cc) flows.clientCredentials = cc;
    const pw = oauth2FlowToConfig(oauth2FormData.flows.password, 'password');
    if (pw) flows.password = pw;
    if (Object.keys(flows).length === 0) {
      await alertDialog({
        title: 'Validation Error',
        message: 'Enable at least one OAuth2 flow and fill required URLs (Authorization Code: authorization + token; Implicit: authorization; Client Credentials / Password: token).',
        variant: 'error',
      });
      return;
    }
    const oauth2Input: OAuth2SchemeInput = {
      scheme_name: name,
      description: oauth2FormData.description || undefined,
      flows,
    };
    try {
      if (editingScheme) {
        const schemeId = editingScheme!.id;
        const result = await updateOAuth2SecurityScheme(schemeId, oauth2Input);
        if (result.success && result.scheme) {
          setSchemes(prev =>
            prev.map(s => (s.id === schemeId ? result.scheme! : s))
          );
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          await alertDialog({
            title: 'Error',
            message: result.error || 'Failed to update scheme',
            variant: 'error',
          });
        }
      } else {
        if (!selectedVersionId) return;
        const result = await createOAuth2SecurityScheme(selectedVersionId as string, oauth2Input);
        if (result.success && result.scheme) {
          setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          await alertDialog({
            title: 'Error',
            message: result.error || 'Failed to create scheme',
            variant: 'error',
          });
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? (err as Error).message : String(err);
      console.error('Error saving security scheme:', msg);
      await alertDialog({
        title: 'Error',
        message: msg || 'Failed to save',
        variant: 'error',
      });
    }
  }
  };

  const handleDelete = async (scheme: SecuritySchemeRecord) => {
    const confirmed = await confirmDialog({
      title: 'Delete Security Scheme',
      message: `Are you sure you want to delete "${scheme.scheme_name}"? Operations using this scheme will need to be updated.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteSecurityScheme(scheme.id);
      if (result.success) {
        setSchemes(prev => prev.filter(s => s.id !== scheme.id));
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: result.error || 'Failed to delete scheme',
          variant: 'error',
        });
      }
    } catch (err) {
      console.error('Error deleting security scheme:', err);
      await alertDialog({
        title: 'Error',
        message: err instanceof Error ? err.message : 'Failed to delete',
        variant: 'error',
      });
    }
  };

  const getInLabel = (inLoc: string | null) => {
    const opt = API_KEY_IN_OPTIONS.find(o => o.value === inLoc);
    return opt?.label || inLoc || 'header';
  };

  if (!selectedVersionId) return null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide flex items-center gap-1.5">
          <Lock sx={{ fontSize: 14, color: '#f59e0b' }} />
          Security Schemes
        </span>
        <Button
          size="small"
          startIcon={<Add sx={{ fontSize: 14 }} />}
          onClick={handleAdd}
          sx={{
            fontSize: '0.7rem',
            textTransform: 'none',
            color: '#6366f1',
            '&:hover': {
              backgroundColor: isDark ? 'rgba(99, 102, 241, 0.1)' : 'rgba(99, 102, 241, 0.05)',
            },
          }}
        >
          Add
        </Button>
      </Box>
      <p className="text-[11px] text-gray-500 dark:text-gray-400 -mt-1">
        Add API Key, HTTP (Basic/Bearer), or other scheme types. Use scheme names when adding security to operations.
      </p>

      {isLoading ? (
        <span className="text-xs text-gray-500 dark:text-gray-400">Loading...</span>
      ) : schemes.length === 0 ? (
        <Box
          sx={{
            py: 3,
            px: 2,
            textAlign: 'center',
            border: isDark ? '1px dashed #334155' : '1px dashed #e2e8f0',
            borderRadius: 1,
          }}
        >
          <VpnKey sx={{ fontSize: 32, color: isDark ? '#475569' : '#94a3b8', mb: 1 }} />
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            No security schemes defined
          </p>
          <Button
            size="small"
            variant="outlined"
            startIcon={<Add />}
            onClick={handleAdd}
            sx={{
              fontSize: '0.7rem',
              textTransform: 'none',
              borderColor: '#6366f1',
              color: '#6366f1',
              '&:hover': {
                borderColor: '#4f46e5',
                backgroundColor: 'rgba(99, 102, 241, 0.04)',
              },
            }}
          >
            Add scheme
          </Button>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {schemes.map((scheme) => (
            <Box
              key={scheme.id}
              sx={{
                p: 1.5,
                border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                borderRadius: 1,
                backgroundColor: isDark ? '#0f172a' : '#f9fafb',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <span className="text-sm font-medium text-gray-900 dark:text-white block truncate">
                  {scheme.scheme_name}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                  {scheme.scheme_type === 'http'
                    ? `HTTP: ${scheme.http_scheme || 'basic'}${(scheme.data as { bearerFormat?: string })?.bearerFormat ? ` (${(scheme.data as { bearerFormat?: string }).bearerFormat})` : ''}`
                    : scheme.scheme_type === 'oauth2'
                    ? `OAuth2: ${Object.keys((scheme.data as { flows?: Record<string, unknown> })?.flows || {}).join(', ') || '—'}`
                    : `${getInLabel(scheme.in_location)}: ${scheme.param_name || '—'}`}
                </span>
              </Box>
              <Box sx={{ display: 'flex', gap: 0.25 }}>
                <IconButton
                  size="small"
                  onClick={() => handleEdit(scheme)}
                  sx={{ p: 0.5, color: isDark ? '#94a3b8' : '#64748b' }}
                >
                  <Edit sx={{ fontSize: 14 }} />
                </IconButton>
                <IconButton
                  size="small"
                  onClick={() => handleDelete(scheme)}
                  sx={{ p: 0.5, color: '#ef4444' }}
                >
                  <Delete sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            </Box>
          ))}
        </Box>
      )}

      {/* Add/Edit Dialog */}
      <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-40" />
          <Dialog.Content
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-sm max-h-[90vh] flex flex-col rounded-xl shadow-xl p-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 overflow-y-auto"
            onPointerDownOutside={(e) => e.preventDefault()}
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {editingScheme
                ? `Edit ${editingScheme.scheme_type === 'oauth2' ? 'OAuth2' : editingScheme.scheme_type === 'http' ? 'HTTP' : 'API Key'} Scheme`
                : 'Add Security Scheme'}
            </Dialog.Title>

            {/* Scheme type: dropdown when adding, read-only when editing */}
            <Box sx={{ mb: 2 }}>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Scheme type
              </label>
              {editingScheme ? (
                <div
                  className={`w-full px-3 py-2 text-sm rounded-md border ${
                    isDark ? 'bg-slate-800/50 border-slate-600 text-slate-300' : 'bg-gray-50 border-gray-200 text-gray-700'
                  }`}
                >
                  {SCHEME_TYPE_OPTIONS.find(o => o.value === editingScheme.scheme_type)?.label ?? editingScheme.scheme_type}
                </div>
              ) : (
                <select
                  value={dialogSchemeType}
                  onChange={(e) => setDialogSchemeType(e.target.value)}
                  className={`w-full px-3 py-2 text-sm rounded-md border ${
                    isDark
                      ? 'bg-slate-800 border-slate-600 text-slate-200'
                      : 'bg-white border-gray-300 text-gray-700'
                  }`}
                >
                  {SCHEME_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value} disabled={!opt.supported}>
                      {opt.label}{opt.supported ? '' : ' (Coming soon)'}
                    </option>
                  ))}
                </select>
              )}
            </Box>

            {!editingScheme && !SCHEME_TYPE_OPTIONS.find(o => o.value === dialogSchemeType)?.supported ? (
              <p className="text-sm text-gray-500 dark:text-gray-400 py-2">
                This scheme type is not yet supported. Use API Key, HTTP, or OAuth2 for now.
              </p>
            ) : dialogSchemeType === 'apiKey' ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    placeholder="apiKey"
                    value={formData.scheme_name}
                    onChange={(e) => setFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                    helperText={editingScheme ? 'Name cannot be changed' : 'Used in operation security (e.g., apiKey)'}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      },
                    }}
                  />
                </Box>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Location
                  </label>
                  <select
                    value={formData.in_location}
                    onChange={(e) =>
                      setFormData(d => ({
                        ...d,
                        in_location: e.target.value as 'header' | 'query' | 'cookie',
                        param_name:
                          e.target.value === 'header'
                            ? 'X-API-Key'
                            : e.target.value === 'query'
                            ? 'api_key'
                            : 'api_key',
                      }))
                    }
                    className={`w-full px-3 py-2 text-sm rounded-md border ${
                      isDark
                        ? 'bg-slate-800 border-slate-600 text-slate-200'
                        : 'bg-white border-gray-300 text-gray-700'
                    }`}
                  >
                    {API_KEY_IN_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </Box>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Parameter / Header Name
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    placeholder={formData.in_location === 'header' ? 'X-API-Key' : 'api_key'}
                    value={formData.param_name}
                    onChange={(e) => setFormData(d => ({ ...d, param_name: e.target.value }))}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      },
                    }}
                  />
                </Box>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    multiline
                    rows={2}
                    placeholder="API key for authentication"
                    value={formData.description}
                    onChange={(e) => setFormData(d => ({ ...d, description: e.target.value }))}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      },
                    }}
                  />
                </Box>
              </Box>
            ) : dialogSchemeType === 'oauth2' ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: '60vh', overflowY: 'auto' }}>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    placeholder="oauth2"
                    value={oauth2FormData.scheme_name}
                    onChange={(e) => setOAuth2FormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                    helperText={editingScheme ? 'Name cannot be changed' : 'Used in operation security (e.g., oauth2)'}
                    sx={{ '& .MuiInputBase-root': { fontSize: '0.875rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                  />
                </Box>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    multiline
                    rows={2}
                    placeholder="OAuth2 authentication"
                    value={oauth2FormData.description}
                    onChange={(e) => setOAuth2FormData(d => ({ ...d, description: e.target.value }))}
                    sx={{ '& .MuiInputBase-root': { fontSize: '0.875rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                  />
                </Box>
                {(['authorizationCode', 'implicit', 'clientCredentials', 'password'] as const).map((flowKey) => {
                  const flowLabels: Record<OAuth2FlowType, string> = {
                    authorizationCode: 'Authorization Code',
                    implicit: 'Implicit',
                    clientCredentials: 'Client Credentials',
                    password: 'Password',
                  };
                  const entry = oauth2FormData.flows[flowKey];
                  const needsAuthUrl = flowKey === 'authorizationCode' || flowKey === 'implicit';
                  const needsTokenUrl = flowKey === 'authorizationCode' || flowKey === 'clientCredentials' || flowKey === 'password';
                  return (
                    <Box
                      key={flowKey}
                      sx={{
                        p: 1.5,
                        border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                        borderRadius: 1,
                        backgroundColor: isDark ? '#0f172a' : '#f8fafc',
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: entry.enabled ? 1.5 : 0 }}>
                        <label
                          htmlFor={`oauth2-flow-${flowKey}`}
                          className="flex items-center gap-2 cursor-pointer select-none"
                          style={{ marginBottom: 0 }}
                        >
                          <input
                            id={`oauth2-flow-${flowKey}`}
                            type="checkbox"
                            checked={entry.enabled}
                            onChange={(e) =>
                              setOAuth2FormData(d => ({
                                ...d,
                                flows: {
                                  ...d.flows,
                                  [flowKey]: { ...d.flows[flowKey], enabled: e.target.checked },
                                },
                              }))
                            }
                            className="rounded border-gray-300 cursor-pointer"
                          />
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{flowLabels[flowKey]}</span>
                        </label>
                      </Box>
                      {entry.enabled && (
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pl: 2.5 }}>
                          {needsAuthUrl && (
                            <Box>
                              <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                                Authorization URL
                              </label>
                              <TextField
                                fullWidth
                                size="small"
                                placeholder="https://example.com/oauth/authorize"
                                value={entry.authorizationUrl}
                                onChange={(e) =>
                                  setOAuth2FormData(d => ({
                                    ...d,
                                    flows: {
                                      ...d.flows,
                                      [flowKey]: { ...d.flows[flowKey], authorizationUrl: e.target.value },
                                    },
                                  }))
                                }
                                sx={{ '& .MuiInputBase-root': { fontSize: '0.8rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                              />
                            </Box>
                          )}
                          {needsTokenUrl && (
                            <Box>
                              <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                                Token URL
                              </label>
                              <TextField
                                fullWidth
                                size="small"
                                placeholder="https://example.com/oauth/token"
                                value={entry.tokenUrl}
                                onChange={(e) =>
                                  setOAuth2FormData(d => ({
                                    ...d,
                                    flows: {
                                      ...d.flows,
                                      [flowKey]: { ...d.flows[flowKey], tokenUrl: e.target.value },
                                    },
                                  }))
                                }
                                sx={{ '& .MuiInputBase-root': { fontSize: '0.8rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                              />
                            </Box>
                          )}
                          <Box>
                            <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                              Refresh URL (optional)
                            </label>
                            <TextField
                              fullWidth
                              size="small"
                              placeholder="https://example.com/oauth/refresh"
                              value={entry.refreshUrl}
                              onChange={(e) =>
                                setOAuth2FormData(d => ({
                                  ...d,
                                  flows: {
                                    ...d.flows,
                                    [flowKey]: { ...d.flows[flowKey], refreshUrl: e.target.value },
                                  },
                                }))
                              }
                              sx={{ '& .MuiInputBase-root': { fontSize: '0.8rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                            />
                          </Box>
                          <Box>
                            <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                              Scopes (name : description)
                            </label>
                            {entry.scopes.map((scope, idx) => (
                              <Box key={idx} sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
                                <TextField
                                  size="small"
                                  placeholder="read"
                                  value={scope.name}
                                  onChange={(e) => {
                                    const next = [...entry.scopes];
                                    next[idx] = { ...next[idx], name: e.target.value };
                                    setOAuth2FormData(d => ({
                                      ...d,
                                      flows: { ...d.flows, [flowKey]: { ...d.flows[flowKey], scopes: next } },
                                    }));
                                  }}
                                  sx={{ flex: 1, '& .MuiInputBase-root': { fontSize: '0.8rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                                />
                                <TextField
                                  size="small"
                                  placeholder="Read access"
                                  value={scope.description}
                                  onChange={(e) => {
                                    const next = [...entry.scopes];
                                    next[idx] = { ...next[idx], description: e.target.value };
                                    setOAuth2FormData(d => ({
                                      ...d,
                                      flows: { ...d.flows, [flowKey]: { ...d.flows[flowKey], scopes: next } },
                                    }));
                                  }}
                                  sx={{ flex: 1.5, '& .MuiInputBase-root': { fontSize: '0.8rem', backgroundColor: isDark ? '#0f172a' : '#ffffff' }}}
                                />
                                <IconButton
                                  size="small"
                                  onClick={() => {
                                    const next = entry.scopes.filter((_, i) => i !== idx);
                                    setOAuth2FormData(d => ({
                                      ...d,
                                      flows: { ...d.flows, [flowKey]: { ...d.flows[flowKey], scopes: next } },
                                    }));
                                  }}
                                  sx={{ p: 0.5, color: '#ef4444' }}
                                >
                                  <Delete sx={{ fontSize: 14 }} />
                                </IconButton>
                              </Box>
                            ))}
                            <Button
                              size="small"
                              startIcon={<Add sx={{ fontSize: 12 }} />}
                              onClick={() =>
                                setOAuth2FormData(d => ({
                                  ...d,
                                  flows: {
                                    ...d.flows,
                                    [flowKey]: { ...d.flows[flowKey], scopes: [...d.flows[flowKey].scopes, { name: '', description: '' }] },
                                  },
                                }))
                              }
                              sx={{ fontSize: '0.7rem', textTransform: 'none', color: '#6366f1', mt: 0.5 }}
                            >
                              Add scope
                            </Button>
                          </Box>
                        </Box>
                      )}
                    </Box>
                  );
                })}
              </Box>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    placeholder="bearerAuth"
                    value={httpFormData.scheme_name}
                    onChange={(e) => setHttpFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                    helperText={editingScheme ? 'Name cannot be changed' : 'Used in operation security (e.g., bearerAuth)'}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      },
                    }}
                  />
                </Box>
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    HTTP Auth Type
                  </label>
                  <select
                    value={httpFormData.http_scheme_kind}
                    onChange={(e) => {
                      const v = e.target.value as 'basic' | 'bearer' | 'custom';
                      setHttpFormData(d => ({
                        ...d,
                        http_scheme_kind: v,
                        http_scheme: v === 'custom' ? d.custom_http_scheme : v,
                      }));
                    }}
                    className={`w-full px-3 py-2 text-sm rounded-md border ${
                      isDark
                        ? 'bg-slate-800 border-slate-600 text-slate-200'
                        : 'bg-white border-gray-300 text-gray-700'
                    }`}
                  >
                    {HTTP_SCHEME_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </Box>
                {httpFormData.http_scheme_kind === 'custom' && (
                  <Box>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Custom Scheme Name
                    </label>
                    <TextField
                      fullWidth
                      size="small"
                      placeholder="Digest"
                      value={httpFormData.custom_http_scheme}
                      onChange={(e) =>
                        setHttpFormData(d => ({ ...d, custom_http_scheme: e.target.value, http_scheme: e.target.value }))
                      }
                      sx={{
                        '& .MuiInputBase-root': {
                          fontSize: '0.875rem',
                          backgroundColor: isDark ? '#0f172a' : '#ffffff',
                        },
                      }}
                    />
                  </Box>
                )}
                {httpFormData.http_scheme_kind === 'bearer' && (
                  <Box>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Bearer Format (optional)
                    </label>
                    <TextField
                      fullWidth
                      size="small"
                      placeholder="JWT"
                      value={httpFormData.bearer_format}
                      onChange={(e) => setHttpFormData(d => ({ ...d, bearer_format: e.target.value }))}
                      sx={{
                        '& .MuiInputBase-root': {
                          fontSize: '0.875rem',
                          backgroundColor: isDark ? '#0f172a' : '#ffffff',
                        },
                      }}
                    />
                  </Box>
                )}
                <Box>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    multiline
                    rows={2}
                    placeholder="HTTP authentication"
                    value={httpFormData.description}
                    onChange={(e) => setHttpFormData(d => ({ ...d, description: e.target.value }))}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      },
                    }}
                  />
                </Box>
              </Box>
            )}

            <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mt: 3 }}>
              <Dialog.Close asChild>
                <button
                  className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
                  onClick={() => setDialogOpen(false)}
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleSave}
                disabled={!editingScheme && !SCHEME_TYPE_OPTIONS.find(o => o.value === dialogSchemeType)?.supported}
              >
                {editingScheme ? 'Save' : 'Add'}
              </button>
            </Box>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Box>
  );
}

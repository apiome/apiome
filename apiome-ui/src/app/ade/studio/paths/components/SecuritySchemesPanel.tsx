'use client';

import React, { useState, useEffect } from 'react';
import { Plus, X, Trash2, Pencil, Lock, Key, XCircle } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { Button } from '../../../../components/ui/Button';
import { Input } from '../../../../components/ui/Input';
import { Label } from '../../../../components/ui/Label';
import { Textarea } from '../../../../components/ui/Textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
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
  createOpenIdConnectSecurityScheme,
  updateOpenIdConnectSecurityScheme,
  createMutualTlsSecurityScheme,
  updateMutualTlsSecurityScheme,
  createCustomSecurityScheme,
  updateCustomSecurityScheme,
  deleteSecurityScheme,
  type SecuritySchemeRecord,
  type ApiKeySchemeInput,
  type HttpSchemeInput,
  type OAuth2SchemeInput,
  type OAuth2FlowConfig,
  type OpenIdConnectSchemeInput,
  type MutualTlsSchemeInput,
  type CustomSchemeInput,
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
  { value: 'openIdConnect', label: 'OpenID Connect', supported: true },
  { value: 'mutualTLS', label: 'Mutual TLS', supported: true },
  { value: 'custom', label: 'Custom', supported: true },
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
  const [openIdConnectFormData, setOpenIdConnectFormData] = useState<{
    scheme_name: string;
    open_id_connect_url: string;
    description: string;
    scopes: string[];
  }>({
    scheme_name: '',
    open_id_connect_url: 'https://example.com/.well-known/openid-configuration',
    description: '',
    scopes: [],
  });
  const [mutualTlsFormData, setMutualTlsFormData] = useState<{
    scheme_name: string;
    description: string;
  }>({
    scheme_name: '',
    description: '',
  });
  const [customFormData, setCustomFormData] = useState<{
    scheme_name: string;
    type: string;
    description: string;
    additional_properties: { name: string; value: string }[];
  }>({
    scheme_name: '',
    type: 'apiKey',
    description: '',
    additional_properties: [],
  });
  const [formError, setFormError] = useState<string | null>(null);

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
    setOpenIdConnectFormData({
      scheme_name: '',
      open_id_connect_url: 'https://example.com/.well-known/openid-configuration',
      description: '',
      scopes: [],
    });
    setMutualTlsFormData({
      scheme_name: '',
      description: '',
    });
    setCustomFormData({
      scheme_name: '',
      type: 'apiKey',
      description: '',
      additional_properties: [],
    });
    setEditingScheme(null);
    setFormError(null);
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
    } else if (scheme.scheme_type === 'openIdConnect') {
      const data = scheme.data as { openIdConnectUrl?: string; scopes?: string[] };
      setOpenIdConnectFormData({
        scheme_name: scheme.scheme_name,
        open_id_connect_url: data?.openIdConnectUrl || 'https://example.com/.well-known/openid-configuration',
        description: scheme.description || '',
        scopes: Array.isArray(data?.scopes) ? data.scopes : [],
      });
      setDialogSchemeType('openIdConnect');
    } else if (scheme.scheme_type === 'mutualTLS') {
      setMutualTlsFormData({
        scheme_name: scheme.scheme_name,
        description: scheme.description || '',
      });
      setDialogSchemeType('mutualTLS');
    } else if (scheme.scheme_type === 'custom') {
      const data = scheme.data as Record<string, unknown>;
      const typeVal = (data?.type as string) || 'apiKey';
      const additional_properties: { name: string; value: string }[] = [];
      if (data && typeof data === 'object') {
        for (const [k, v] of Object.entries(data)) {
          if (k === 'type' || k === 'description') continue;
          if (v !== undefined && v !== null) additional_properties.push({ name: k, value: String(v) });
        }
      }
      setCustomFormData({
        scheme_name: scheme.scheme_name,
        type: typeVal,
        description: scheme.description || '',
        additional_properties,
      });
      setDialogSchemeType('custom');
    } else return;
    setEditingScheme(scheme);
    setFormError(null);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!selectedVersionId) return;

    if (dialogSchemeType === 'apiKey') {
      const name = formData.scheme_name.trim();
      const paramName = formData.param_name.trim();
      if (!name || !paramName) {
        setFormError('Scheme name and parameter name are required.');
        return;
      }
      setFormError(null);
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
            setFormError(result.error || 'Failed to update scheme');
          }
        } else {
          const result = await createApiKeySecurityScheme(selectedVersionId, formData);
          if (result.success && result.scheme) {
            setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
            setDialogOpen(false);
            resetForm();
            onRefresh?.();
          } else {
            setFormError(result.error || 'Failed to create scheme');
          }
        }
      } catch (err) {
        console.error('Error saving security scheme:', err);
        setFormError(err instanceof Error ? err.message : 'Failed to save');
      }
      return;
    }

    if (dialogSchemeType === 'http') {
      const name = httpFormData.scheme_name.trim();
      const httpSchemeValue =
        httpFormData.http_scheme_kind === 'custom'
          ? httpFormData.custom_http_scheme.trim()
          : httpFormData.http_scheme_kind;
      if (!name || !httpSchemeValue) {
        setFormError('Scheme name and HTTP scheme are required.');
        return;
      }
      setFormError(null);
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
            setFormError(result.error || 'Failed to update scheme');
          }
        } else {
          const result = await createHttpSecurityScheme(selectedVersionId, httpInput);
          if (result.success && result.scheme) {
            setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
            setDialogOpen(false);
            resetForm();
            onRefresh?.();
          } else {
            setFormError(result.error || 'Failed to create scheme');
          }
        }
      } catch (err) {
        console.error('Error saving security scheme:', err);
        setFormError(err instanceof Error ? err.message : 'Failed to save');
      }
      return;
    }

    if (dialogSchemeType === 'oauth2') {
    const name = oauth2FormData.scheme_name.trim();
    if (!name) {
      setFormError('Scheme name is required.');
      return;
    }
    setFormError(null);
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
      setFormError('Enable at least one OAuth2 flow and fill required URLs (Authorization Code: authorization + token; Implicit: authorization; Client Credentials / Password: token).');
      return;
    }
    setFormError(null);
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
          setFormError(result.error || 'Failed to update scheme');
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
          setFormError(result.error || 'Failed to create scheme');
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? (err as Error).message : String(err);
      console.error('Error saving security scheme:', msg);
      setFormError(msg || 'Failed to save');
    }
  }

  if (dialogSchemeType === 'openIdConnect') {
    const name = openIdConnectFormData.scheme_name.trim();
    const url = openIdConnectFormData.open_id_connect_url.trim();
    if (!name || !url) {
      setFormError('Scheme name and OpenID Connect discovery URL are required.');
      return;
    }
    setFormError(null);
    const openIdInput: OpenIdConnectSchemeInput = {
      scheme_name: name,
      open_id_connect_url: url,
      description: openIdConnectFormData.description || undefined,
      scopes: openIdConnectFormData.scopes.filter((s) => s.trim()).length > 0 ? openIdConnectFormData.scopes.filter((s) => s.trim()) : undefined,
    };
    try {
      if (editingScheme) {
        const schemeId = editingScheme!.id;
        const result = await updateOpenIdConnectSecurityScheme(schemeId, openIdInput);
        if (result.success && result.scheme) {
          setSchemes(prev =>
            prev.map(s => (s.id === schemeId ? result.scheme! : s))
          );
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setFormError(result.error || 'Failed to update scheme');
        }
      } else {
        if (!selectedVersionId) return;
        const result = await createOpenIdConnectSecurityScheme(selectedVersionId as string, openIdInput);
        if (result.success && result.scheme) {
          setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setDialogOpen(false);
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
      setDialogOpen(false);
      await alertDialog({
        title: 'Error',
        message: msg || 'Failed to save',
        variant: 'error',
      });
    }
  }

  if (dialogSchemeType === 'mutualTLS') {
    const name = mutualTlsFormData.scheme_name.trim();
    if (!name) {
      setFormError('Scheme name is required.');
      return;
    }
    setFormError(null);
    const mutualTlsInput: MutualTlsSchemeInput = {
      scheme_name: name,
      description: mutualTlsFormData.description?.trim() || undefined,
    };
    try {
      if (editingScheme) {
        const schemeId = editingScheme!.id;
        const result = await updateMutualTlsSecurityScheme(schemeId, mutualTlsInput);
        if (result.success && result.scheme) {
          setSchemes(prev =>
            prev.map(s => (s.id === schemeId ? result.scheme! : s))
          );
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setFormError(result.error || 'Failed to update scheme');
        }
      } else {
        if (!selectedVersionId) return;
        const result = await createMutualTlsSecurityScheme(selectedVersionId as string, mutualTlsInput);
        if (result.success && result.scheme) {
          setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setFormError(result.error || 'Failed to create scheme');
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? (err as Error).message : String(err);
      console.error('Error saving security scheme:', msg);
      setFormError(msg || 'Failed to save');
    }
  }

  if (dialogSchemeType === 'custom') {
    const name = customFormData.scheme_name.trim();
    if (!name) {
      setFormError('Scheme name is required.');
      return;
    }
    setFormError(null);
    const additional_properties: Record<string, string> = {};
    customFormData.additional_properties.forEach(({ name: k, value: v }) => {
      const key = k.trim();
      if (key && v.trim()) additional_properties[key] = v.trim();
    });
    const customInput: CustomSchemeInput = {
      scheme_name: name,
      type: customFormData.type.trim() || 'apiKey',
      description: customFormData.description?.trim() || undefined,
      additional_properties: Object.keys(additional_properties).length > 0 ? additional_properties : undefined,
    };
    try {
      if (editingScheme) {
        const schemeId = editingScheme!.id;
        const result = await updateCustomSecurityScheme(schemeId, customInput);
        if (result.success && result.scheme) {
          setSchemes(prev =>
            prev.map(s => (s.id === schemeId ? result.scheme! : s))
          );
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setFormError(result.error || 'Failed to update scheme');
        }
      } else {
        if (!selectedVersionId) return;
        const result = await createCustomSecurityScheme(selectedVersionId as string, customInput);
        if (result.success && result.scheme) {
          setSchemes(prev => [...prev, result.scheme!].sort((a, b) => a.scheme_name.localeCompare(b.scheme_name)));
          setDialogOpen(false);
          resetForm();
          onRefresh?.();
        } else {
          setFormError(result.error || 'Failed to create scheme');
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? (err as Error).message : String(err);
      console.error('Error saving security scheme:', msg);
      setFormError(msg || 'Failed to save');
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
    <div className="flex flex-col gap-4">
      <div className="flex justify-between items-center">
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide flex items-center gap-1.5">
          <Lock className="w-3.5 h-3.5 text-amber-500" />
          Security Schemes
        </span>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleAdd}
          className="text-indigo-600 dark:text-indigo-400 text-xs hover:bg-indigo-500/10"
        >
          <Plus className="w-3.5 h-3.5" />
          Add
        </Button>
      </div>
      <p className="text-[11px] text-gray-500 dark:text-gray-400 -mt-1">
        Add API Key, HTTP (Basic/Bearer), or other scheme types. Drag a scheme onto a method node to apply it, or use Edit/Delete below.
      </p>

      {isLoading ? (
        <span className="text-xs text-gray-500 dark:text-gray-400">Loading...</span>
      ) : schemes.length === 0 ? (
        <div
          className={`py-6 px-4 text-center rounded border border-dashed ${
            isDark ? 'border-slate-700' : 'border-slate-200'
          }`}
        >
          <Key className={`w-8 h-8 mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`} />
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            No security schemes defined
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={handleAdd}
            className="text-indigo-600 dark:text-indigo-400 border-indigo-500 hover:bg-indigo-500/10 text-xs"
          >
            <Plus className="w-4 h-4" />
            Add scheme
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <span className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider px-0.5">
            Drag to canvas · Edit / Delete
          </span>
          {schemes.map((scheme) => {
            const handleDragStart = (e: React.DragEvent) => {
              e.dataTransfer.effectAllowed = 'copy';
              e.dataTransfer.setData(
                'application/json',
                JSON.stringify({
                  type: 'security-scheme',
                  schemeId: scheme.id,
                  schemeName: scheme.scheme_name,
                  schemeType: scheme.scheme_type,
                })
              );
            };
            return (
              <div
                key={scheme.id}
                className={`p-3 rounded border flex justify-between items-center ${
                  isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-200 bg-gray-50'
                }`}
              >
                <div
                  draggable
                  onDragStart={handleDragStart}
                  className="flex-1 min-w-0 cursor-grab active:cursor-grabbing transition-opacity"
                >
                  <span className="text-sm font-medium text-gray-900 dark:text-white block truncate">
                    {scheme.scheme_name}
                  </span>
                  <span className="text-[11px] text-gray-500 dark:text-gray-400">
                    {scheme.scheme_type === 'http'
                      ? `HTTP: ${scheme.http_scheme || 'basic'}${(scheme.data as { bearerFormat?: string })?.bearerFormat ? ` (${(scheme.data as { bearerFormat?: string }).bearerFormat})` : ''}`
                      : scheme.scheme_type === 'oauth2'
                      ? `OAuth2: ${Object.keys((scheme.data as { flows?: Record<string, unknown> })?.flows || {}).join(', ') || '—'}`
                      : scheme.scheme_type === 'openIdConnect'
                      ? `OpenID Connect: ${(scheme.data as { openIdConnectUrl?: string })?.openIdConnectUrl || '—'}`
                      : scheme.scheme_type === 'mutualTLS'
                      ? 'Mutual TLS (certificate-based)'
                      : scheme.scheme_type === 'custom'
                      ? `Custom: ${(scheme.data as Record<string, unknown>)?.type ?? '—'}`
                      : `${getInLabel(scheme.in_location)}: ${scheme.param_name || '—'}`}
                  </span>
                </div>
                <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => handleEdit(scheme)}
                    className={`p-1.5 rounded transition-colors ${
                      isDark ? 'text-slate-400 hover:bg-slate-700' : 'text-slate-500 hover:bg-slate-200'
                    }`}
                    aria-label="Edit scheme"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(scheme)}
                    className="p-1.5 rounded text-red-500 hover:bg-red-500/10 transition-colors"
                    aria-label="Delete scheme"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add/Edit Dialog */}
      <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[9999] w-full max-w-sm max-h-[90vh] flex flex-col rounded-xl shadow-xl p-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 overflow-y-auto"
            onPointerDownOutside={(e) => e.preventDefault()}
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {editingScheme
                ? `Edit ${editingScheme.scheme_type === 'oauth2' ? 'OAuth2' : editingScheme.scheme_type === 'openIdConnect' ? 'OpenID Connect' : editingScheme.scheme_type === 'mutualTLS' ? 'Mutual TLS' : editingScheme.scheme_type === 'custom' ? 'Custom' : editingScheme.scheme_type === 'http' ? 'HTTP' : 'API Key'} Scheme`
                : 'Add Security Scheme'}
            </Dialog.Title>

            {formError && (
              <div
                className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 flex items-start gap-2"
                role="alert"
              >
                <XCircle className="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-red-800 dark:text-red-200">Validation Error</p>
                  <p className="text-sm text-red-700 dark:text-red-300 mt-0.5">{formError}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setFormError(null)}
                  className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 p-1 -m-1"
                  aria-label="Dismiss"
                >
                  <X className="w-[18px] h-[18px]" />
                </button>
              </div>
            )}

            {/* Scheme type: dropdown when adding, read-only when editing */}
            <div className="mb-4">
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
            </div>

            {!editingScheme && !SCHEME_TYPE_OPTIONS.find(o => o.value === dialogSchemeType)?.supported ? (
              <p className="text-sm text-gray-500 dark:text-gray-400 py-2">
                This scheme type is not yet supported.
              </p>
            ) : dialogSchemeType === 'apiKey' ? (
              <div className="flex flex-col gap-4">
                <div>
                  <Label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </Label>
                  <Input
                    className="w-full text-sm"
                    placeholder="apiKey"
                    value={formData.scheme_name}
                    onChange={(e) => setFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                    {editingScheme ? 'Name cannot be changed' : 'Used in operation security (e.g., apiKey)'}
                  </p>
                </div>
                <div>
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
                </div>
                <div>
                  <Label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Parameter / Header Name
                  </Label>
                  <Input
                    className="w-full text-sm"
                    placeholder={formData.in_location === 'header' ? 'X-API-Key' : 'api_key'}
                    value={formData.param_name}
                    onChange={(e) => setFormData(d => ({ ...d, param_name: e.target.value }))}
                  />
                </div>
                <div>
                  <Label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </Label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="API key for authentication"
                    value={formData.description}
                    onChange={(e) => setFormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
              </div>
            ) : dialogSchemeType === 'oauth2' ? (
              <div className="flex flex-col gap-4 max-h-[60vh] overflow-y-auto">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="oauth2"
                    value={oauth2FormData.scheme_name}
                    onChange={(e) => setOAuth2FormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                  {editingScheme && (
                    <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">Name cannot be changed</p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="OAuth2 authentication"
                    value={oauth2FormData.description}
                    onChange={(e) => setOAuth2FormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
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
                    <div
                      key={flowKey}
                      className={`p-3 rounded border ${
                        isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-200 bg-slate-50'
                      }`}
                    >
                      <div className={`flex items-center gap-2 ${entry.enabled ? 'mb-3' : ''}`}>
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
                      </div>
                      {entry.enabled && (
                        <div className="flex flex-col gap-3 pl-5">
                          {needsAuthUrl && (
                            <div>
                              <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                                Authorization URL
                              </label>
                              <Input
                                className="w-full text-sm"
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
                              />
                            </div>
                          )}
                          {needsTokenUrl && (
                            <div>
                              <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                                Token URL
                              </label>
                              <Input
                                className="w-full text-sm"
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
                              />
                            </div>
                          )}
                          <div>
                            <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                              Refresh URL (optional)
                            </label>
                            <Input
                              className="w-full text-sm"
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
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
                              Scopes (name : description)
                            </label>
                            {entry.scopes.map((scope, idx) => (
                              <div key={idx} className="flex gap-1 mb-1">
                                <Input
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
                                  className="flex-1 w-full text-sm"
                                />
                                <Input
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
                                  className="flex-1 w-full text-sm"
                                />
                                <button
                                  type="button"
                                  onClick={() => {
                                    const next = entry.scopes.filter((_, i) => i !== idx);
                                    setOAuth2FormData(d => ({
                                      ...d,
                                      flows: { ...d.flows, [flowKey]: { ...d.flows[flowKey], scopes: next } },
                                    }));
                                  }}
                                  className="p-1.5 rounded text-red-500 hover:bg-red-500/10"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ))}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                setOAuth2FormData(d => ({
                                  ...d,
                                  flows: {
                                    ...d.flows,
                                    [flowKey]: { ...d.flows[flowKey], scopes: [...d.flows[flowKey].scopes, { name: '', description: '' }] },
                                  },
                                }))
                              }
                              className="text-indigo-600 dark:text-indigo-400 text-xs mt-1 hover:bg-indigo-500/10"
                            >
                              <Plus className="w-3 h-3" />
                              Add scope
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : dialogSchemeType === 'openIdConnect' ? (
              <div className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="openId"
                    value={openIdConnectFormData.scheme_name}
                    onChange={(e) => setOpenIdConnectFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    OpenID Connect Discovery URL
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="https://example.com/.well-known/openid-configuration"
                    value={openIdConnectFormData.open_id_connect_url}
                    onChange={(e) => setOpenIdConnectFormData(d => ({ ...d, open_id_connect_url: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scopes (optional, one per line or comma-separated)
                  </label>
                  <Textarea
                    rows={3}
                    className="w-full text-sm"
                    placeholder="openid, profile, email"
                    value={openIdConnectFormData.scopes.join(', ')}
                    onChange={(e) => {
                      const raw = e.target.value;
                      const scopes = raw
                        .split(/[\n,]+/)
                        .map((s) => s.trim())
                        .filter(Boolean);
                      setOpenIdConnectFormData(d => ({ ...d, scopes }));
                    }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="OpenID Connect authentication"
                    value={openIdConnectFormData.description}
                    onChange={(e) => setOpenIdConnectFormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
              </div>
            ) : dialogSchemeType === 'mutualTLS' ? (
              <div className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="mutualTLS"
                    value={mutualTlsFormData.scheme_name}
                    onChange={(e) => setMutualTlsFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="Certificate-based (mutual TLS) authentication"
                    value={mutualTlsFormData.description}
                    onChange={(e) => setMutualTlsFormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
              </div>
            ) : dialogSchemeType === 'custom' ? (
              <div className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="myCustomAuth"
                    value={customFormData.scheme_name}
                    onChange={(e) => setCustomFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Type (OpenAPI type or x- extension)
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="apiKey, http, oauth2, openIdConnect, mutualTLS, or x-custom-auth"
                    value={customFormData.type}
                    onChange={(e) => setCustomFormData(d => ({ ...d, type: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="Custom authentication"
                    value={customFormData.description}
                    onChange={(e) => setCustomFormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Additional properties (key-value, exported as-is)
                  </label>
                  {customFormData.additional_properties.map((prop, idx) => (
                    <div key={idx} className="flex gap-1 mb-1">
                      <Input
                        placeholder="name or x-extension"
                        value={prop.name}
                        onChange={(e) => {
                          const next = [...customFormData.additional_properties];
                          next[idx] = { ...next[idx], name: e.target.value };
                          setCustomFormData(d => ({ ...d, additional_properties: next }));
                        }}
                        className="flex-1 w-full text-sm"
                      />
                      <Input
                        placeholder="value"
                        value={prop.value}
                        onChange={(e) => {
                          const next = [...customFormData.additional_properties];
                          next[idx] = { ...next[idx], value: e.target.value };
                          setCustomFormData(d => ({ ...d, additional_properties: next }));
                        }}
                        className="flex-1 w-full text-sm"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const next = customFormData.additional_properties.filter((_, i) => i !== idx);
                          setCustomFormData(d => ({ ...d, additional_properties: next }));
                        }}
                        className="p-1.5 rounded text-red-500 hover:bg-red-500/10"
                        aria-label="Remove property"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  <Button
                    onClick={() =>
                      setCustomFormData(d => ({
                        ...d,
                        additional_properties: [...d.additional_properties, { name: '', value: '' }],
                      }))
                    }
                    className="text-indigo-600 dark:text-indigo-400 text-xs mt-1 hover:bg-indigo-500/10"
                  >
                    Add property
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Scheme Name
                  </label>
                  <Input
                    className="w-full text-sm"
                    placeholder="bearerAuth"
                    value={httpFormData.scheme_name}
                    onChange={(e) => setHttpFormData(d => ({ ...d, scheme_name: e.target.value }))}
                    disabled={!!editingScheme}
                  />
                </div>
                <div>
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
                </div>
                {httpFormData.http_scheme_kind === 'custom' && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Custom Scheme Name
                    </label>
                    <Input
                      className="w-full text-sm"
                      placeholder="Digest"
                      value={httpFormData.custom_http_scheme}
                      onChange={(e) =>
                        setHttpFormData(d => ({ ...d, custom_http_scheme: e.target.value, http_scheme: e.target.value }))
                      }
                    />
                  </div>
                )}
                {httpFormData.http_scheme_kind === 'bearer' && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Bearer Format (optional)
                    </label>
                    <Input
                      className="w-full text-sm"
                      placeholder="JWT"
                      value={httpFormData.bearer_format}
                      onChange={(e) => setHttpFormData(d => ({ ...d, bearer_format: e.target.value }))}
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description (optional)
                  </label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="HTTP authentication"
                    value={httpFormData.description}
                    onChange={(e) => setHttpFormData(d => ({ ...d, description: e.target.value }))}
                  />
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2 mt-6">
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
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

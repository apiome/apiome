'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import { Close, Save, Add, Delete, ArrowBack } from '@mui/icons-material';
import { Lock, ExternalLink } from 'lucide-react';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getOperationDescription,
  upsertOperationDescription,
} from '../../../../../../lib/db/helper-path-operation-descriptions';
import { generateOperationId } from '../../../../../../lib/utils/path-utils';
import {
  getLinkedParametersForOperation,
  createSharedPathParameter,
  linkParameterToOperation,
  unlinkParameterFromOperation,
  getSharedPathParameters,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import {
  getLinkedResponsesForOperation,
  createSharedPathResponse,
  linkResponseToOperation,
  unlinkResponseFromOperation,
} from '../../../../../../lib/db/helper-shared-path-responses';
import { extractPathParameters } from '../../../../../../lib/utils/path-params';
import SchemaBuilder from './SchemaBuilder';
import ResponseSection from './ResponseSection';
import { getHttpStatusDescription } from '../../../../../../lib/utils/http-status-codes';
import type { SecurityRequirement } from '../../../../../../lib/utils/openapi-paths-generator';
import { ExtensionsEditor } from '../../../../components/ade/studio/ExtensionsEditor';
import { useStudio } from '../../StudioContext';
import { getSecuritySchemesForVersion } from '../../../../../../lib/db/helper-security-schemes';

interface OperationPropertiesPanelProps {
  operationId: string | null;
  operation: string;
  pathname: string;
  versionPathId: string | null;
  onClose: () => void;
  onRefresh?: () => void;
}

// View modes for the panel
type ViewMode = 'operation' | 'add-parameter' | 'add-response';

export default function OperationPropertiesPanel({
  operationId,
  operation,
  pathname,
  versionPathId,
  onClose,
  onRefresh,
}: OperationPropertiesPanelProps) {
  const { selectedVersionId } = useStudio();
  const isDark = useDarkMode();
  const { alert: alertDialog, confirm: confirmDialog } = useDialog();

  // View mode state
  const [viewMode, setViewMode] = useState<ViewMode>('operation');

  // Operation state
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState('');
  const [operationIdName, setOperationIdName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');

  // Parameters list state
  const [parameters, setParameters] = useState<any[]>([]);
  const [parametersLoading, setParametersLoading] = useState(false);
  const [availablePathParams, setAvailablePathParams] = useState<string[]>([]);

  // Responses list state
  const [responses, setResponses] = useState<any[]>([]);

  // Security schemes (API Key + HTTP) for dropdown
  const [securitySchemes, setSecuritySchemes] = useState<
    { scheme_name: string; scheme_type: string; in_location: string | null; param_name: string | null; http_scheme: string | null }[]
  >([]);
  const [responsesLoading, setResponsesLoading] = useState(false);

  // New parameter form state
  const [newParamName, setNewParamName] = useState('');
  const [newParamLocation, setNewParamLocation] = useState<'path' | 'query' | 'header' | 'cookie'>('path');
  const [newParamSummary, setNewParamSummary] = useState('');
  const [newParamDescription, setNewParamDescription] = useState('');
  const [newParamRequired, setNewParamRequired] = useState(true);

  // New response form state
  const [newResponseStatusCode, setNewResponseStatusCode] = useState('200');
  const [newResponseDescription, setNewResponseDescription] = useState('');
  const [newResponseAutoFillDescription, setNewResponseAutoFillDescription] = useState(true);
  const [newResponseSchemaType, setNewResponseSchemaType] = useState<'object' | 'string' | 'number' | 'integer' | 'boolean' | 'array'>('object');
  const [newResponseArrayItemType, setNewResponseArrayItemType] = useState<'string' | 'number' | 'integer' | 'boolean'>('string');

  // Request body schema state
  const [requestBodySchema, setRequestBodySchema] = useState<any>(null);
  const [requestBodyRequired, setRequestBodyRequired] = useState(true);

  // Security requirements state (OpenAPI security array)
  const [security, setSecurity] = useState<SecurityRequirement[]>([]);
  const [loadedMetadata, setLoadedMetadata] = useState<Record<string, unknown>>({});

  // Deprecated flag state
  const [deprecated, setDeprecated] = useState(false);

  // Private (x-private) flag: hide operation from Swagger
  const [xPrivate, setXPrivate] = useState(false);

  // External documentation (OpenAPI externalDocs)
  const [externalDocsUrl, setExternalDocsUrl] = useState('');
  const [externalDocsDescription, setExternalDocsDescription] = useState('');

  // Custom x-* extensions (OpenAPI extension properties)
  const [extensions, setExtensions] = useState<Record<string, unknown>>({});

  // Load operation description when operationId changes
  useEffect(() => {
    if (!operationId) {
      setSummary('');
      setDescription('');
      setOperationIdName('');
      setSecurity([]);
      setLoadedMetadata({});
      setDeprecated(false);
      setXPrivate(false);
      setExternalDocsUrl('');
      setExternalDocsDescription('');
      setExtensions({});
      return;
    }

    const loadDescription = async () => {
      setIsLoading(true);
      // Clear existing values immediately when loading new operation
      setSummary('');
      setDescription('');
      setOperationIdName('');
      setSecurity([]);
      setLoadedMetadata({});
      setDeprecated(false);
      setXPrivate(false);
      setExternalDocsUrl('');
      setExternalDocsDescription('');
      setExtensions({});

      try {
        const result = await getOperationDescription(operationId);
        const desc = JSON.parse(result);

        if (desc) {
          setSummary(desc.summary || '');
          setDescription(desc.description || '');
          setOperationIdName(desc.operation_id || '');
          const meta = desc.metadata
            ? typeof desc.metadata === 'string'
              ? JSON.parse(desc.metadata)
              : desc.metadata
            : {};
          setLoadedMetadata(meta);
          const sec = meta.security;
          setSecurity(
            Array.isArray(sec) ? sec : sec ? [sec] : []
          );
          setDeprecated(meta.deprecated === true);
          setXPrivate(meta['x-private'] === true || meta.x_private === true);
          const extDocs = meta.external_docs ?? meta.externalDocs;
          if (extDocs && typeof extDocs === 'object') {
            setExternalDocsUrl(extDocs.url ?? '');
            setExternalDocsDescription(extDocs.description ?? '');
          }
          // Extract custom x-* extensions (exclude x-private which has its own UI)
          const customExtensions: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(meta)) {
            if (k.startsWith('x-') && k !== 'x-private') {
              customExtensions[k] = v;
            }
          }
          setExtensions(customExtensions);
        } else {
          const autoGenerated = generateOperationId(pathname, operation);
          setOperationIdName(autoGenerated);
        }
      } catch (error) {
        console.error('Error loading operation description:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadDescription();
  }, [operationId, pathname, operation]);

  // Load security schemes (API Key) for dropdown
  useEffect(() => {
    if (!selectedVersionId) {
      setSecuritySchemes([]);
      return;
    }
    getSecuritySchemesForVersion(selectedVersionId).then((schemes) => {
      setSecuritySchemes(
        schemes.map((s) => ({
          scheme_name: s.scheme_name,
          scheme_type: s.scheme_type,
          in_location: s.in_location,
          param_name: s.param_name,
          http_scheme: s.http_scheme,
        }))
      );
    }).catch(() => setSecuritySchemes([]));
  }, [selectedVersionId]);

  // Load parameters when operationId changes
  useEffect(() => {
    if (!operationId) {
      setParameters([]);
      return;
    }

    const loadParameters = async () => {
      setParametersLoading(true);
      try {
        const result = await getLinkedParametersForOperation(operationId);
        const data = JSON.parse(result);
        if (data.success) {
          setParameters(data.parameters || []);
        }
      } catch (error) {
        console.error('Error loading parameters:', error);
      } finally {
        setParametersLoading(false);
      }
    };

    loadParameters();
  }, [operationId]);

  // Load responses when operationId changes
  useEffect(() => {
    if (!operationId) {
      setResponses([]);
      return;
    }

    const loadResponses = async () => {
      setResponsesLoading(true);
      try {
        const result = await getLinkedResponsesForOperation(operationId);
        const data = JSON.parse(result);
        if (data.success) {
          setResponses(data.responses || []);
        }
      } catch (error) {
        console.error('Error loading responses:', error);
      } finally {
        setResponsesLoading(false);
      }
    };

    loadResponses();
  }, [operationId]);

  // Extract available path parameters from pathname
  useEffect(() => {
    if (pathname) {
      const params = extractPathParameters(pathname);
      setAvailablePathParams(params);
    }
  }, [pathname]);

  // Reset view mode when operationId changes
  useEffect(() => {
    setViewMode('operation');
    resetNewParamForm();
    resetNewResponseForm();
  }, [operationId]);

  // Compute available path parameters that are NOT already linked to this operation
  const unlinkedPathParams = useMemo(() => {
    // Get the names of parameters that are already linked
    const linkedParamNames = new Set(
      parameters
        .filter((p: any) => p.in_location === 'path')
        .map((p: any) => p.name)
    );
    // Filter out already-linked parameters
    return availablePathParams.filter((param) => !linkedParamNames.has(param));
  }, [availablePathParams, parameters]);

  const resetNewParamForm = () => {
    setNewParamName('');
    // Default to 'query' if no unlinked path parameters available, otherwise 'path'
    setNewParamLocation(unlinkedPathParams.length > 0 ? 'path' : 'query');
    setNewParamSummary('');
    setNewParamDescription('');
    setNewParamRequired(unlinkedPathParams.length > 0);
  };

  const resetNewResponseForm = () => {
    setNewResponseStatusCode('200');
    setNewResponseDescription(getHttpStatusDescription('200'));
    setNewResponseAutoFillDescription(true);
    setNewResponseSchemaType('object');
    setNewResponseArrayItemType('string');
  };

  // Handle status code change - auto-fill description if checkbox is checked
  const handleStatusCodeChange = (value: string) => {
    setNewResponseStatusCode(value);
    if (newResponseAutoFillDescription) {
      const autoDesc = getHttpStatusDescription(value);
      setNewResponseDescription(autoDesc);
    }
  };

  // Handle auto-fill checkbox toggle
  const handleAutoFillToggle = (checked: boolean) => {
    setNewResponseAutoFillDescription(checked);
    if (checked) {
      const autoDesc = getHttpStatusDescription(newResponseStatusCode);
      setNewResponseDescription(autoDesc);
    }
  };

  const handleSaveOperation = async () => {
    if (!operationId) return;

    setIsSaving(true);
    setSaveStatus('idle');
    try {
      const metadata: Record<string, unknown> = {
        security: security.length > 0 ? security : undefined,
        deprecated: deprecated ? true : false,
        'x-private': xPrivate ? true : false,
        external_docs:
          externalDocsUrl.trim()
            ? {
                url: externalDocsUrl.trim(),
                ...(externalDocsDescription.trim() && { description: externalDocsDescription.trim() }),
              }
            : undefined,
        ...extensions,
      };
      if (metadata.security === undefined) {
        delete metadata.security;
      }
      if (metadata.external_docs === undefined) {
        delete metadata.external_docs;
      }
      // Don't delete deprecated - we need to explicitly save false to remove it
      await upsertOperationDescription(
        operationId,
        summary,
        description,
        operationIdName,
        Object.keys(metadata).length > 0 ? metadata : undefined
      );
      // Update loadedMetadata to reflect the saved state
      setLoadedMetadata(metadata);
      // Show "Saved" in button briefly
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
      // Refresh canvas to reflect changes (e.g., deprecated status)
      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error saving operation description:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to save operation description. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveParameter = async () => {
    if (!operationId || !newParamName.trim() || !versionPathId) return;

    setIsSaving(true);
    try {
      // Schema with required field included
      const schemaData = {
        type: 'string',
        required: newParamRequired,
      };

      // Create or get existing shared parameter
      const paramResult = await createSharedPathParameter(
        versionPathId,
        newParamName.trim(),
        newParamLocation,
        newParamSummary.trim() || undefined,
        newParamDescription.trim() || undefined,
        schemaData
      );
      const paramParsed = JSON.parse(paramResult);

      if (paramParsed.success) {
        // Link the shared parameter to this operation
        const linkResult = await linkParameterToOperation(
          operationId,
          paramParsed.parameter.id
        );
        const linkParsed = JSON.parse(linkResult);

        if (linkParsed.success) {
          // Reload parameters list locally
          const paramsResult = await getLinkedParametersForOperation(operationId);
          const paramsData = JSON.parse(paramsResult);
          if (paramsData.success) {
            setParameters(paramsData.parameters || []);
          }

          // Switch back to operation view
          setViewMode('operation');
          resetNewParamForm();

          // Trigger canvas refresh if callback provided
          if (onRefresh) {
            onRefresh();
          }
        } else {
          await alertDialog({
            title: 'Error',
            message: linkParsed.error || 'Failed to link parameter to operation',
            variant: 'error',
          });
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: paramParsed.error || 'Failed to create parameter',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding parameter:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add parameter. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteParameter = async (paramId: string, paramName: string) => {
    if (!operationId) return;

    const confirmed = await confirmDialog({
      title: 'Unlink Parameter',
      message: `Are you sure you want to unlink the parameter "${paramName}" from this operation? The parameter will still be available for other operations.`,
      variant: 'danger',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkParameterFromOperation(operationId, paramId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Update local state
        setParameters(params => params.filter(p => p.id !== paramId));

        // Trigger canvas refresh if callback provided
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink parameter',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking parameter:', error);
    }
  };

  const handleSaveResponse = async () => {
    if (!operationId || !newResponseStatusCode.trim() || !versionPathId) return;

    setIsSaving(true);
    try {
      // Build schema data based on selected type
      let schemaData: Record<string, any> | undefined;
      if (newResponseSchemaType === 'object') {
        schemaData = { type: 'object', properties: [] };
      } else if (newResponseSchemaType === 'array') {
        schemaData = { type: 'array', items: { type: newResponseArrayItemType } };
      } else {
        // Primitive types: string, number, integer, boolean
        schemaData = { type: newResponseSchemaType };
      }

      // First, create or get the shared response
      const sharedResponseResult = await createSharedPathResponse(
        versionPathId,
        newResponseStatusCode.trim(),
        newResponseDescription.trim() || undefined,
        schemaData // Pass the schema data
      );
      const sharedResponseParsed = JSON.parse(sharedResponseResult);

      if (!sharedResponseParsed.success) {
        await alertDialog({
          title: 'Error',
          message: sharedResponseParsed.error || 'Failed to create response',
          variant: 'error',
        });
        setIsSaving(false);
        return;
      }

      // Then link it to the operation
      const linkResult = await linkResponseToOperation(
        operationId,
        sharedResponseParsed.response.id
      );
      const linkParsed = JSON.parse(linkResult);

      if (linkParsed.success) {
        // Reload responses list locally
        const responsesResult = await getLinkedResponsesForOperation(operationId);
        const responsesData = JSON.parse(responsesResult);
        if (responsesData.success) {
          setResponses(responsesData.responses || []);
        }

        // Switch back to operation view
        setViewMode('operation');
        resetNewResponseForm();

        // Trigger canvas refresh if callback provided
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: linkParsed.error || 'Failed to link response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add response. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleAddSecurity = () => {
    setSecurity((prev) => [...prev, { bearerAuth: [] }]);
  };

  const handleRemoveSecurity = (index: number) => {
    setSecurity((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUpdateSecurity = (index: number, schemeName: string, scopes: string[]) => {
    setSecurity((prev) => {
      const next = [...prev];
      const key = schemeName.trim() || 'bearerAuth';
      next[index] = { [key]: scopes };
      return next;
    });
  };

  const handleDeleteResponse = async (responseId: string, statusCode: string) => {
    if (!operationId) return;

    const confirmed = await confirmDialog({
      title: 'Unlink Response',
      message: `Are you sure you want to unlink the ${statusCode} response from this operation? The response will still be available for other operations.`,
      variant: 'danger',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkResponseFromOperation(operationId, responseId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Update local state
        setResponses(resps => resps.filter(r => r.id !== responseId));

        // Trigger canvas refresh if callback provided
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking response:', error);
    }
  };


  const handleAddParameterClick = () => {
    resetNewParamForm();
    setViewMode('add-parameter');
  };

  const handleBackToOperation = () => {
    setViewMode('operation');
    resetNewParamForm();
  };

  if (!operationId) return null;

  return (
    <Box
      sx={{
        width: 320,
        height: '100%',
        borderLeft: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
        background: isDark
          ? 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)'
          : 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 2,
          borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        {viewMode === 'add-parameter' ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <IconButton size="small" onClick={handleBackToOperation} sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
              <ArrowBack sx={{ fontSize: 18 }} />
            </IconButton>
            <Box>
              <span className="text-sm font-semibold text-gray-900 dark:text-white">
                Add Parameter
              </span>
              <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {operation} {pathname}
              </div>
            </Box>
          </Box>
        ) : (
          <Box>
            <span className="text-sm font-semibold text-gray-900 dark:text-white">
              Operation Details
            </span>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {operation} {pathname}
            </div>
          </Box>
        )}
        <IconButton size="small" onClick={onClose} sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
          <Close sx={{ fontSize: 18 }} />
        </IconButton>
      </Box>

      {/* Content */}
      {isLoading ? (
        <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
          <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
        </Box>
      ) : viewMode === 'add-response' ? (
        /* Add Response Form */
        <>
          <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* Status Code */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Status Code <span className="text-red-500">*</span>
                </label>
                <TextField
                  fullWidth
                  size="small"
                  value={newResponseStatusCode}
                  onChange={(e) => handleStatusCodeChange(e.target.value)}
                  placeholder="200, 2XX, 404, etc."
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  HTTP status code or pattern (e.g., 200, 2XX for all 2xx responses)
                </p>
              </Box>

              {/* Description */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  size="small"
                  value={newResponseDescription}
                  onChange={(e) => {
                    setNewResponseDescription(e.target.value);
                    // If user manually edits, turn off auto-fill
                    if (newResponseAutoFillDescription) {
                      setNewResponseAutoFillDescription(false);
                    }
                  }}
                  placeholder="Describe when this response is returned..."
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: newResponseAutoFillDescription
                        ? (isDark ? 'rgba(59, 130, 246, 0.1)' : 'rgba(59, 130, 246, 0.05)')
                        : (isDark ? '#0f172a' : '#ffffff'),
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={newResponseAutoFillDescription}
                      onChange={(e) => handleAutoFillToggle(e.target.checked)}
                      sx={{
                        color: isDark ? '#64748b' : '#94a3b8',
                        '&.Mui-checked': {
                          color: '#6366f1',
                        },
                      }}
                    />
                  }
                  label={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Auto-fill description from status code
                    </span>
                  }
                  sx={{ mt: 0.5 }}
                />
              </Box>

              {/* Schema Type */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Response Schema Type
                </label>
                <TextField
                  fullWidth
                  select
                  size="small"
                  value={newResponseSchemaType}
                  onChange={(e) => setNewResponseSchemaType(e.target.value as any)}
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                >
                  <MenuItem value="object">Object (default)</MenuItem>
                  <MenuItem value="string">String</MenuItem>
                  <MenuItem value="number">Number</MenuItem>
                  <MenuItem value="integer">Integer</MenuItem>
                  <MenuItem value="boolean">Boolean</MenuItem>
                  <MenuItem value="array">Array</MenuItem>
                </TextField>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  The type of data returned in the response body
                </p>
              </Box>

              {/* Array Item Type (only shown when array is selected) */}
              {newResponseSchemaType === 'array' && (
                <Box>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Array Item Type
                  </label>
                  <TextField
                    fullWidth
                    select
                    size="small"
                    value={newResponseArrayItemType}
                    onChange={(e) => setNewResponseArrayItemType(e.target.value as any)}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                        color: isDark ? '#f1f5f9' : '#0f172a',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: isDark ? '#334155' : '#e2e8f0',
                      },
                    }}
                  >
                    <MenuItem value="string">String</MenuItem>
                    <MenuItem value="number">Number</MenuItem>
                    <MenuItem value="integer">Integer</MenuItem>
                    <MenuItem value="boolean">Boolean</MenuItem>
                  </TextField>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    The type of items in the array
                  </p>
                </Box>
              )}
            </Box>
          </Box>

          {/* Footer with Save button */}
          <Box
            sx={{
              p: 2,
              borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            }}
          >
            <Button
              fullWidth
              variant="contained"
              onClick={handleSaveResponse}
              disabled={isSaving || !newResponseStatusCode.trim()}
              startIcon={<Save />}
              sx={{
                background: 'linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)',
                '&:hover': {
                  background: 'linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)',
                },
                '&:disabled': {
                  background: isDark ? '#334155' : '#e2e8f0',
                  color: isDark ? '#64748b' : '#94a3b8',
                },
              }}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </Button>
          </Box>
        </>
      ) : viewMode === 'add-parameter' ? (
        /* Add Parameter Form */
        <>
          <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* Parameter Name */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Parameter Name <span className="text-red-500">*</span>
                </label>
                {newParamLocation === 'path' && unlinkedPathParams.length > 0 ? (
                  <TextField
                    fullWidth
                    select
                    size="small"
                    value={newParamName}
                    onChange={(e) => setNewParamName(e.target.value)}
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                        color: isDark ? '#f1f5f9' : '#0f172a',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: isDark ? '#334155' : '#e2e8f0',
                      },
                    }}
                  >
                    <MenuItem value="">Select a path parameter</MenuItem>
                    {unlinkedPathParams.map((param) => (
                      <MenuItem key={param} value={param}>
                        {param}
                      </MenuItem>
                    ))}
                  </TextField>
                ) : (
                  <TextField
                    fullWidth
                    size="small"
                    value={newParamName}
                    onChange={(e) => setNewParamName(e.target.value)}
                    placeholder={
                      newParamLocation === 'query' ? 'e.g., limit, offset, filter' :
                      newParamLocation === 'header' ? 'e.g., Authorization, X-Request-ID' :
                      newParamLocation === 'cookie' ? 'e.g., session, token' :
                      'e.g., userId, groupId'
                    }
                    sx={{
                      '& .MuiInputBase-root': {
                        fontSize: '0.875rem',
                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                        color: isDark ? '#f1f5f9' : '#0f172a',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: isDark ? '#334155' : '#e2e8f0',
                      },
                    }}
                  />
                )}
                {newParamLocation === 'path' && unlinkedPathParams.length > 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Select from path parameters in: {pathname}
                  </p>
                )}
              </Box>

              {/* Location */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Location <span className="text-red-500">*</span>
                </label>
                <div className="grid grid-cols-4 gap-1">
                  {(['path', 'query', 'header', 'cookie'] as const).map((loc) => {
                    const isPathDisabled = loc === 'path' && unlinkedPathParams.length === 0;
                    return (
                      <button
                        key={loc}
                        type="button"
                        disabled={isPathDisabled}
                        onClick={() => {
                          if (!isPathDisabled) {
                            setNewParamLocation(loc);
                            setNewParamName('');
                            setNewParamRequired(loc === 'path');
                          }
                        }}
                        className={`px-2 py-1.5 rounded text-xs font-medium transition-colors ${
                          isPathDisabled
                            ? 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50'
                            : newParamLocation === loc
                              ? 'bg-purple-500 text-white'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
                        }`}
                        title={isPathDisabled ? (availablePathParams.length === 0 ? 'No path parameters in this route' : 'All path parameters are already linked') : undefined}
                      >
                        {loc}
                      </button>
                    );
                  })}
                </div>
                {availablePathParams.length === 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Path has no parameters (e.g., {'{'}userId{'}'})
                  </p>
                )}
                {availablePathParams.length > 0 && unlinkedPathParams.length === 0 && (
                  <div className="mt-2 p-2 rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                    <p className="text-xs text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
                      <span className="text-amber-500">⚠</span>
                      All path parameters are already linked to this operation
                    </p>
                  </div>
                )}
              </Box>

              {/* Required */}
              <Box>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={newParamRequired}
                    onChange={(e) => setNewParamRequired(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                  />
                  <span className="text-xs text-gray-700 dark:text-gray-300">
                    Required parameter
                  </span>
                </label>
              </Box>

              {/* Summary */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Summary
                </label>
                <TextField
                  fullWidth
                  size="small"
                  value={newParamSummary}
                  onChange={(e) => setNewParamSummary(e.target.value)}
                  placeholder="Brief description"
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
              </Box>

              {/* Description */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  size="small"
                  value={newParamDescription}
                  onChange={(e) => setNewParamDescription(e.target.value)}
                  placeholder="Detailed description..."
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
              </Box>
            </Box>
          </Box>

          {/* Footer with Save button */}
          <Box
            sx={{
              p: 2,
              borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            }}
          >
            <Button
              fullWidth
              variant="contained"
              onClick={handleSaveParameter}
              disabled={isSaving || !newParamName.trim()}
              startIcon={<Save />}
              sx={{
                background: 'linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)',
                '&:hover': {
                  background: 'linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)',
                },
                '&:disabled': {
                  background: isDark ? '#334155' : '#e2e8f0',
                  color: isDark ? '#64748b' : '#94a3b8',
                },
              }}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </Button>
          </Box>
        </>
      ) : (
        /* Operation Details Form */
        <>
          <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* Operation ID */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Operation ID
                </label>
                <TextField
                  fullWidth
                  size="small"
                  value={operationIdName}
                  onChange={(e) => setOperationIdName(e.target.value)}
                  placeholder="Auto-generated from path and verb"
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Used for code generation and API client SDKs
                </p>
              </Box>

              {/* Summary */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Summary
                </label>
                <TextField
                  fullWidth
                  size="small"
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="Brief summary of the operation"
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
              </Box>

              {/* Description */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  size="small"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Detailed description of what this operation does..."
                  sx={{
                    '& .MuiInputBase-root': {
                      fontSize: '0.875rem',
                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                      color: isDark ? '#f1f5f9' : '#0f172a',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
              </Box>

              {/* Deprecated and Hidden: side-by-side */}
              <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={deprecated}
                      onChange={(e) => setDeprecated(e.target.checked)}
                      size="small"
                      sx={{
                        color: isDark ? '#64748b' : '#94a3b8',
                        '&.Mui-checked': {
                          color: '#f59e0b',
                        },
                      }}
                    />
                  }
                  label={
                    <span className={`text-xs ${deprecated ? 'text-amber-600 dark:text-amber-400' : 'text-gray-700 dark:text-gray-300'}`}>
                      Deprecated
                    </span>
                  }
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={xPrivate}
                      onChange={(e) => setXPrivate(e.target.checked)}
                      size="small"
                      sx={{
                        color: isDark ? '#64748b' : '#94a3b8',
                        '&.Mui-checked': {
                          color: '#6366f1',
                        },
                      }}
                    />
                  }
                  label={
                    <span className={`text-xs flex items-center gap-1 ${xPrivate ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-700 dark:text-gray-300'}`}>
                      <Lock className="w-3.5 h-3.5" />
                      Hidden
                    </span>
                  }
                />
              </Box>

              {/* Custom x-* extensions */}
              <Box sx={{ mt: 2 }}>
                <ExtensionsEditor
                  value={extensions as Record<string, any>}
                  onChange={setExtensions as (v: Record<string, any>) => void}
                  size="small"
                />
              </Box>

              {/* External documentation (OpenAPI externalDocs) */}
              <Box sx={{ mt: 2 }}>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5 flex items-center gap-1.5">
                  <ExternalLink className="w-3.5 h-3.5" />
                  External documentation
                </label>
                <TextField
                  size="small"
                  fullWidth
                  type="url"
                  placeholder="https://docs.example.com/..."
                  value={externalDocsUrl}
                  onChange={(e) => setExternalDocsUrl(e.target.value)}
                  sx={{
                    mb: 1,
                    '& .MuiOutlinedInput-root': {
                      fontSize: '0.8125rem',
                      backgroundColor: isDark ? '#1e293b' : '#fff',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
                <TextField
                  size="small"
                  fullWidth
                  multiline
                  minRows={2}
                  placeholder="Brief description of external docs (optional)"
                  value={externalDocsDescription}
                  onChange={(e) => setExternalDocsDescription(e.target.value)}
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      fontSize: '0.8125rem',
                      backgroundColor: isDark ? '#1e293b' : '#fff',
                    },
                    '& .MuiOutlinedInput-notchedOutline': {
                      borderColor: isDark ? '#334155' : '#e2e8f0',
                    },
                  }}
                />
              </Box>

              {/* Parameters Section */}
              <Box sx={{ mt: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
                    Parameters
                  </label>
                  <Button
                    size="small"
                    startIcon={<Add />}
                    onClick={handleAddParameterClick}
                    sx={{
                      fontSize: '0.75rem',
                      textTransform: 'none',
                      color: '#6366f1',
                      '&:hover': {
                        backgroundColor: isDark ? 'rgba(99, 102, 241, 0.1)' : 'rgba(99, 102, 241, 0.05)',
                      },
                    }}
                  >
                    Add Parameter
                  </Button>
                </Box>

                {parametersLoading ? (
                  <Box sx={{ py: 2, textAlign: 'center' }}>
                    <span className="text-xs text-gray-500 dark:text-gray-400">Loading parameters...</span>
                  </Box>
                ) : parameters.length === 0 ? (
                  <Box
                    sx={{
                      py: 3,
                      px: 2,
                      textAlign: 'center',
                      border: isDark ? '1px dashed #334155' : '1px dashed #e2e8f0',
                      borderRadius: 1,
                    }}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No parameters defined yet
                    </span>
                  </Box>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {parameters.map((param) => (
                      <Box
                        key={param.id}
                        sx={{
                          p: 1.5,
                          border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                          borderRadius: 1,
                          backgroundColor: isDark ? '#0f172a' : '#f9fafb',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'start',
                        }}
                      >
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <div className="text-xs font-medium text-gray-900 dark:text-white truncate">
                            {param.name}
                          </div>
                          <div className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
                            {param.in_location} • {param.data?.required ? 'required' : 'optional'}
                          </div>
                        </Box>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Box
                            sx={{
                              px: 1,
                              py: 0.5,
                              borderRadius: 0.5,
                              fontSize: '0.625rem',
                              fontWeight: 600,
                              color: '#fff',
                              backgroundColor:
                                param.in_location === 'path' ? '#8b5cf6' :
                                param.in_location === 'query' ? '#3b82f6' :
                                param.in_location === 'header' ? '#f59e0b' :
                                '#10b981',
                            }}
                          >
                            {param.in_location === 'path' ? '/' :
                             param.in_location === 'query' ? '?' :
                             param.in_location === 'header' ? 'H' : 'C'}
                          </Box>
                          <IconButton
                            size="small"
                            onClick={() => handleDeleteParameter(param.id, param.name)}
                            sx={{
                              color: '#ef4444',
                              p: 0.5,
                              '&:hover': { backgroundColor: 'rgba(239, 68, 68, 0.1)' },
                            }}
                          >
                            <Delete sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Box>
                      </Box>
                    ))}
                  </Box>
                )}
              </Box>

              {/* Request Body Section (for POST/PUT/PATCH) */}
              {['POST', 'PUT', 'PATCH'].includes(operation) && (
                <Box sx={{ mt: 2, pt: 2, borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0' }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                      Request Body
                    </label>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={requestBodyRequired}
                          onChange={(e) => setRequestBodyRequired(e.target.checked)}
                          size="small"
                          sx={{
                            color: isDark ? '#64748b' : '#94a3b8',
                            '&.Mui-checked': {
                              color: '#8b5cf6',
                            },
                          }}
                        />
                      }
                      label={
                        <span className="text-[10px] text-gray-600 dark:text-gray-400">
                          Required
                        </span>
                      }
                    />
                  </Box>
                  <SchemaBuilder
                    value={requestBodySchema}
                    onChange={setRequestBodySchema}
                    label=""
                    description="Define the request body schema using existing classes or create inline schemas"
                    allowInline={true}
                  />
                </Box>
              )}

              {/* Responses Section */}
              <Box sx={{ mt: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
                    Responses
                  </label>
                  <Button
                    size="small"
                    startIcon={<Add />}
                    onClick={() => setViewMode('add-response')}
                    sx={{
                      fontSize: '0.75rem',
                      textTransform: 'none',
                      color: '#6366f1',
                      '&:hover': {
                        backgroundColor: isDark ? 'rgba(99, 102, 241, 0.1)' : 'rgba(99, 102, 241, 0.05)',
                      },
                    }}
                  >
                    Add Response
                  </Button>
                </Box>

                {responsesLoading ? (
                  <Box sx={{ py: 2, textAlign: 'center' }}>
                    <span className="text-xs text-gray-500 dark:text-gray-400">Loading responses...</span>
                  </Box>
                ) : responses.length === 0 ? (
                  <Box
                    sx={{
                      py: 3,
                      px: 2,
                      textAlign: 'center',
                      border: isDark ? '1px dashed #334155' : '1px dashed #e2e8f0',
                      borderRadius: 1,
                    }}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No responses defined yet
                    </span>
                  </Box>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {responses.map((response) => (
                      <Box
                        key={response.id}
                        sx={{
                          border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                          borderRadius: 1,
                          overflow: 'hidden',
                        }}
                      >
                        {/* Response Header */}
                        <Box
                          sx={{
                            p: 1.5,
                            backgroundColor: isDark ? '#0f172a' : '#f9fafb',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                          }}
                        >
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Box
                              sx={{
                                px: 1.5,
                                py: 0.5,
                                borderRadius: 1,
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                color: '#fff',
                                backgroundColor:
                                  response.status_code.startsWith('2') ? '#10b981' :
                                  response.status_code.startsWith('3') ? '#3b82f6' :
                                  response.status_code.startsWith('4') ? '#f59e0b' :
                                  '#ef4444',
                              }}
                            >
                              {response.status_code}
                            </Box>
                            {response.description && (
                              <Box sx={{ fontSize: '0.875rem', color: 'text.secondary' }}>
                                {response.description}
                              </Box>
                            )}
                          </Box>
                          <IconButton
                            size="small"
                            onClick={() => handleDeleteResponse(response.id, response.status_code)}
                            sx={{
                              color: '#ef4444',
                              p: 0.5,
                              '&:hover': { backgroundColor: 'rgba(239, 68, 68, 0.1)' },
                            }}
                          >
                            <Delete sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Box>

                        {/* Response Schema Section */}
                        <Box sx={{ p: 2, backgroundColor: isDark ? '#1e293b' : '#ffffff' }}>
                          <ResponseSection
                            response={response}
                            onUpdate={async () => {
                              // Reload responses when content types are updated
                              if (!operationId) return;
                              try {
                                const result = await getLinkedResponsesForOperation(operationId);
                                const data = JSON.parse(result);
                                if (data.success) {
                                  setResponses(data.responses || []);
                                }
                              } catch (error) {
                                console.error('Error reloading responses:', error);
                              }
                            }}
                            onRefresh={onRefresh}
                          />
                        </Box>
                      </Box>
                    ))}
                  </Box>
                )}
              </Box>

              {/* Security Section */}
              <Box sx={{ mt: 2, pt: 2, borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0' }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
                    <Lock size={14} className="text-amber-500" />
                    Security
                  </label>
                  <Button
                    size="small"
                    startIcon={<Add />}
                    onClick={handleAddSecurity}
                    sx={{
                      fontSize: '0.75rem',
                      textTransform: 'none',
                      color: '#6366f1',
                      '&:hover': {
                        backgroundColor: isDark ? 'rgba(99, 102, 241, 0.1)' : 'rgba(99, 102, 241, 0.05)',
                      },
                    }}
                  >
                    Add Security
                  </Button>
                </Box>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                  Authentication schemes required for this operation (e.g., bearerAuth, apiKey, oauth2)
                </p>
                {security.length === 0 ? (
                  <Box
                    sx={{
                      py: 2,
                      px: 2,
                      textAlign: 'center',
                      border: isDark ? '1px dashed #334155' : '1px dashed #e2e8f0',
                      borderRadius: 1,
                    }}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No security requirements
                    </span>
                  </Box>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {security.map((req, index) => {
                      const [schemeName, scopes] = Object.entries(req)[0] || ['bearerAuth', []];
                      return (
                        <Box
                          key={index}
                          sx={{
                            p: 1.5,
                            border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                            borderRadius: 1,
                            backgroundColor: isDark ? '#0f172a' : '#f9fafb',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 1,
                          }}
                        >
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 1 }}>
                            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                              {securitySchemes.length > 0 ? (
                                <>
                                  <TextField
                                    select
                                    size="small"
                                    value={securitySchemes.some(s => s.scheme_name === schemeName) ? schemeName : '__custom__'}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      handleUpdateSecurity(index, v === '__custom__' ? '' : v, scopes || []);
                                    }}
                                    sx={{
                                      '& .MuiInputBase-root': {
                                        fontSize: '0.875rem',
                                        backgroundColor: isDark ? '#0f172a' : '#ffffff',
                                        color: isDark ? '#f1f5f9' : '#0f172a',
                                      },
                                      '& .MuiOutlinedInput-notchedOutline': {
                                        borderColor: isDark ? '#334155' : '#e2e8f0',
                                      },
                                    }}
                                  >
                                    {securitySchemes.map((s) => (
                                      <MenuItem key={s.scheme_name} value={s.scheme_name}>
                                        {s.scheme_type === 'http'
                                          ? `${s.scheme_name} (HTTP: ${s.http_scheme || 'basic'})`
                                          : s.scheme_type === 'oauth2'
                                          ? `${s.scheme_name} (OAuth2)`
                                          : `${s.scheme_name} (${s.in_location || 'header'}: ${s.param_name || s.scheme_name})`}
                                      </MenuItem>
                                    ))}
                                    <MenuItem value="__custom__">Other (bearerAuth, oauth2...)</MenuItem>
                                  </TextField>
                                  {(!schemeName || !securitySchemes.some(s => s.scheme_name === schemeName)) && (
                                    <TextField
                                      size="small"
                                      placeholder="Custom scheme name"
                                      value={schemeName}
                                      onChange={(e) => handleUpdateSecurity(index, e.target.value, scopes || [])}
                                      sx={{
                                        '& .MuiInputBase-root': {
                                          fontSize: '0.75rem',
                                          backgroundColor: isDark ? '#0f172a' : '#ffffff',
                                          color: isDark ? '#f1f5f9' : '#0f172a',
                                        },
                                        '& .MuiOutlinedInput-notchedOutline': {
                                          borderColor: isDark ? '#334155' : '#e2e8f0',
                                        },
                                      }}
                                    />
                                  )}
                                </>
                              ) : (
                                <TextField
                                  size="small"
                                  placeholder="Scheme name (e.g., apiKey, bearerAuth)"
                                  value={schemeName}
                                  onChange={(e) =>
                                    handleUpdateSecurity(index, e.target.value, scopes || [])
                                  }
                                  sx={{
                                    '& .MuiInputBase-root': {
                                      fontSize: '0.875rem',
                                      backgroundColor: isDark ? '#0f172a' : '#ffffff',
                                      color: isDark ? '#f1f5f9' : '#0f172a',
                                    },
                                    '& .MuiOutlinedInput-notchedOutline': {
                                      borderColor: isDark ? '#334155' : '#e2e8f0',
                                    },
                                  }}
                                />
                              )}
                            </Box>
                            <IconButton
                              size="small"
                              onClick={() => handleRemoveSecurity(index)}
                              sx={{
                                color: '#ef4444',
                                p: 0.5,
                                flexShrink: 0,
                                '&:hover': { backgroundColor: 'rgba(239, 68, 68, 0.1)' },
                              }}
                            >
                              <Delete sx={{ fontSize: 14 }} />
                            </IconButton>
                          </Box>
                          {(schemeName === 'oauth2' || schemeName === 'openIdConnect') && (
                            <TextField
                              size="small"
                              placeholder="Scopes (comma-separated, e.g., read, write)"
                              value={(scopes || []).join(', ')}
                              onChange={(e) => {
                                const scopeList = e.target.value
                                  .split(',')
                                  .map((s) => s.trim())
                                  .filter(Boolean);
                                handleUpdateSecurity(index, schemeName, scopeList);
                              }}
                              sx={{
                                '& .MuiInputBase-root': {
                                  fontSize: '0.75rem',
                                  backgroundColor: isDark ? '#0f172a' : '#ffffff',
                                  color: isDark ? '#f1f5f9' : '#0f172a',
                                },
                                '& .MuiOutlinedInput-notchedOutline': {
                                  borderColor: isDark ? '#334155' : '#e2e8f0',
                                },
                              }}
                            />
                          )}
                        </Box>
                      );
                    })}
                  </Box>
                )}
              </Box>
            </Box>
          </Box>

          {/* Footer with Save button */}
          <Box
            sx={{
              p: 2,
              borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            }}
          >
            <Button
              fullWidth
              variant="contained"
              onClick={handleSaveOperation}
              disabled={isSaving}
              startIcon={<Save />}
              sx={{
                background: saveStatus === 'saved'
                  ? 'linear-gradient(135deg, #10b981 0%, #34d399 100%)'
                  : 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                '&:hover': {
                  background: saveStatus === 'saved'
                    ? 'linear-gradient(135deg, #059669 0%, #10b981 100%)'
                    : 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
                },
                '&:disabled': {
                  background: isDark ? '#334155' : '#e2e8f0',
                  color: isDark ? '#64748b' : '#94a3b8',
                },
              }}
            >
              {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved ✓' : 'Save'}
            </Button>
          </Box>
        </>
      )}
    </Box>
  );
}


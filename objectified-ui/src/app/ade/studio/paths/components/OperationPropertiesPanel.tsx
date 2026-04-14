'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { X, Save, Plus, Trash2, ArrowLeft, Lock, Unlock, ExternalLink, ListChecks } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import { Input } from '../../../../components/ui/Input';
import { Label } from '../../../../components/ui/Label';
import { Checkbox } from '../../../../components/ui/Checkbox';
import { Textarea } from '../../../../components/ui/Textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getOperationDescription,
  upsertOperationDescription,
} from '../../../../../../lib/db/helper-path-operation-descriptions';
import { generateOperationId } from '../../../../../../lib/utils/path-utils';
import {
  getLinkedParametersForOperation,
  getSharedPathParameters,
  createSharedPathParameter,
  linkParameterToOperation,
  unlinkParameterFromOperation,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import {
  getLinkedResponsesForOperation,
  getSharedPathResponses,
  createSharedPathResponse,
  linkResponseToOperation,
  unlinkResponseFromOperation,
} from '../../../../../../lib/db/helper-shared-path-responses';
import { operationHasLinkedRequestBody } from '../../../../../../lib/db/helper-shared-path-request-bodies';
import { extractPathParameters } from '../../../../../../lib/utils/path-params';
import { validateOpenApiParameterName } from '../../../../../../lib/utils/openapi-parameter-name';
import ResponseSection from './ResponseSection';
import RequestBodySection from './RequestBodySection';
import ReuseSearchCombobox from './ReuseSearchCombobox';
import { getHttpStatusDescription } from '../../../../../../lib/utils/http-status-codes';
import type { SecurityRequirement } from '../../../../../../lib/utils/openapi-paths-generator';
import { ExtensionsEditor } from '../../../../components/ade/studio/ExtensionsEditor';
import { useStudio } from '../../StudioContext';
import { getSecuritySchemesForVersion } from '../../../../../../lib/db/helper-security-schemes';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../../components/ui/Tabs';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface OperationPropertiesPanelProps {
  operationId: string | null;
  operation: string;
  pathname: string;
  versionPathId: string | null;
  onClose: () => void;
  onRefresh?: () => void;
  /** Increment to force refetch of operation description (e.g. after security scheme drag-drop). */
  refreshKey?: number;
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
  refreshKey,
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

  // Security requirements state (OpenAPI security array)
  const [security, setSecurity] = useState<SecurityRequirement[]>([]);
  /** When true, operation is explicitly public (OpenAPI security: []) */
  const [unsecured, setUnsecured] = useState(false);
  /** Optional documentation describing how security applies to this operation (emitted as x-security-description). */
  const [securityDescription, setSecurityDescription] = useState('');
  const [loadedMetadata, setLoadedMetadata] = useState<Record<string, unknown>>({});

  // Deprecated flag state
  const [deprecated, setDeprecated] = useState(false);

  // OpenAPI tags (metadata.tags)
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState('');

  // Private (x-private) flag: hide operation from Swagger
  const [xPrivate, setXPrivate] = useState(false);

  /** OPTIONS + linked request body: OpenAPI export omits requestBody; warn only. */
  const [optionsRequestBodyLinked, setOptionsRequestBodyLinked] = useState(false);

  // External documentation (OpenAPI externalDocs)
  const [externalDocsUrl, setExternalDocsUrl] = useState('');
  const [externalDocsDescription, setExternalDocsDescription] = useState('');

  // Custom x-* extensions (OpenAPI extension properties)
  const [extensions, setExtensions] = useState<Record<string, unknown>>({});

  /** Reuse library (#2652): attach existing shared parameter / response */
  const [paramAttachMode, setParamAttachMode] = useState<'create' | 'reuse'>('create');
  const [responseAttachMode, setResponseAttachMode] = useState<'create' | 'reuse'>('create');
  const [reuseParamId, setReuseParamId] = useState('');
  const [reuseResponseId, setReuseResponseId] = useState('');
  const [sharedParamsPool, setSharedParamsPool] = useState<
    { id: string; name: string; in_location: string; summary?: string | null }[]
  >([]);
  const [sharedResponsesPool, setSharedResponsesPool] = useState<
    { id: string; status_code: string; description?: string | null }[]
  >([]);

  // Load operation description when operationId changes
  useEffect(() => {
    if (!operationId) {
      setSummary('');
      setDescription('');
      setOperationIdName('');
      setSecurity([]);
      setUnsecured(false);
      setSecurityDescription('');
      setLoadedMetadata({});
      setDeprecated(false);
      setTags([]);
      setTagDraft('');
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
      setUnsecured(false);
      setSecurityDescription('');
      setLoadedMetadata({});
      setDeprecated(false);
      setTags([]);
      setTagDraft('');
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
          // Explicit security: [] = unsecured (public); undefined = inherit; array with items = secured
          if (Array.isArray(sec) && sec.length === 0) {
            setUnsecured(true);
            setSecurity([]);
          } else {
            setUnsecured(false);
            setSecurity(Array.isArray(sec) ? sec : sec ? [sec] : []);
          }
          setDeprecated(meta.deprecated === true);
          const metaTags = meta.tags;
          if (Array.isArray(metaTags)) {
            setTags([...new Set(metaTags.map((t) => String(t).trim()).filter(Boolean))]);
          } else {
            setTags([]);
          }
          setXPrivate(meta['x-private'] === true || meta.x_private === true);
          setSecurityDescription(
            (meta.security_description ?? meta.securityDescription ?? meta['x-security-description'] ?? '') as string
          );
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
  }, [operationId, pathname, operation, refreshKey]);

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

  useEffect(() => {
    if (!operationId || operation !== 'OPTIONS') {
      setOptionsRequestBodyLinked(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const raw = await operationHasLinkedRequestBody(operationId);
        const data = JSON.parse(raw) as { success?: boolean; linked?: boolean; error?: string };
        if (!data.success) {
          console.error('Error loading linked request body for OPTIONS operation:', data);
          if (!cancelled) setOptionsRequestBodyLinked(false);
          return;
        }
        if (!cancelled) {
          setOptionsRequestBodyLinked(Boolean(data.linked));
        }
      } catch (error) {
        console.error('Error loading linked request body for OPTIONS operation:', error);
        if (!cancelled) setOptionsRequestBodyLinked(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [operationId, operation, refreshKey]);

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

  const unlinkedSharedParams = useMemo(() => {
    const linkedIds = new Set(parameters.map((p: any) => p.id as string));
    return sharedParamsPool.filter((p) => !linkedIds.has(p.id));
  }, [sharedParamsPool, parameters]);

  const unlinkedSharedResponses = useMemo(() => {
    const linkedIds = new Set(responses.map((r: any) => r.id as string));
    return sharedResponsesPool.filter((r) => !linkedIds.has(r.id));
  }, [sharedResponsesPool, responses]);

  useEffect(() => {
    if (!versionPathId || viewMode === 'operation') return;
    let cancelled = false;
    void (async () => {
      try {
        if (viewMode === 'add-parameter') {
          const raw = await getSharedPathParameters(versionPathId);
          const data = JSON.parse(raw) as {
            success?: boolean;
            parameters?: {
              id: string;
              name: string;
              in_location: string;
              summary?: string | null;
            }[];
          };
          if (!cancelled && data.success && data.parameters) setSharedParamsPool(data.parameters);
        } else if (viewMode === 'add-response') {
          const raw = await getSharedPathResponses(versionPathId);
          const data = JSON.parse(raw) as {
            success?: boolean;
            responses?: { id: string; status_code: string; description?: string | null }[];
          };
          if (!cancelled && data.success && data.responses) setSharedResponsesPool(data.responses);
        }
      } catch (e) {
        console.error('Failed to load reuse pool for paths', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [versionPathId, viewMode]);

  const resetNewParamForm = () => {
    setNewParamName('');
    // Default to 'query' if no unlinked path parameters available, otherwise 'path'
    setNewParamLocation(unlinkedPathParams.length > 0 ? 'path' : 'query');
    setNewParamSummary('');
    setNewParamDescription('');
    setNewParamRequired(unlinkedPathParams.length > 0);
  };

  const resetNewResponseForm = (defaultStatusCode: string = '200') => {
    setNewResponseStatusCode(defaultStatusCode);
    setNewResponseDescription(getHttpStatusDescription(defaultStatusCode));
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
    const trimmedOperationIdName = operationIdName.trim();
    try {
      // Strip placeholder keys (__new__*) so we don't persist them
      const sanitizedSecurity =
        security.length > 0
          ? security
              .map((req) => {
                const cleaned: SecurityRequirement = {};
                for (const [name, scopes] of Object.entries(req)) {
                  if (!name.startsWith('__new__')) cleaned[name] = scopes;
                }
                return cleaned;
              })
              .filter((req) => Object.keys(req).length > 0)
          : undefined;
      // Unsecured = explicit security: [] (public); otherwise omit or set requirements
      const securityValue = unsecured ? [] : (sanitizedSecurity?.length ? sanitizedSecurity : undefined);
      const cleanedTags = tags.map((t) => t.trim()).filter(Boolean);
      const metadata: Record<string, unknown> = {
        security: securityValue,
        security_description: securityDescription.trim() || undefined,
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
        ...(cleanedTags.length > 0 ? { tags: cleanedTags } : {}),
      };
      // Keep security when explicitly [] (unsecured) or when we have requirements
      if (metadata.security === undefined) {
        delete metadata.security;
      }
      if (metadata.security_description === undefined) {
        delete metadata.security_description;
      }
      if (metadata.external_docs === undefined) {
        delete metadata.external_docs;
      }
      // Don't delete deprecated - we need to explicitly save false to remove it
      await upsertOperationDescription(
        operationId,
        summary,
        description,
        trimmedOperationIdName,
        Object.keys(metadata).length > 0 ? metadata : undefined
      );
      // Sync local state to the normalized (trimmed) value
      setOperationIdName(trimmedOperationIdName);
      // Update loadedMetadata to reflect the saved state
      setLoadedMetadata(metadata);
      // Show "Saved" in button briefly
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
      // Refresh canvas to reflect changes (e.g., deprecated status)
      if (onRefresh) {
        onRefresh();
      }
    } catch (error: unknown) {
      console.error('Error saving operation description:', error);
      const message =
        error instanceof Error ? error.message : 'Failed to save operation description. Please try again.';
      await alertDialog({
        title: 'Error',
        message,
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const addTag = () => {
    const next = tagDraft.trim();
    if (!next || tags.includes(next)) return;
    setTags((prev) => [...prev, next]);
    setTagDraft('');
  };

  const removeTag = (tag: string) => {
    setTags((prev) => prev.filter((t) => t !== tag));
  };

  const handleSaveParameter = async () => {
    if (!operationId || !newParamName.trim() || !versionPathId) return;

    if (newParamLocation === 'path') {
      const segments = extractPathParameters(pathname);
      if (!segments.includes(newParamName.trim())) {
        await alertDialog({
          title: 'Path parameter name mismatch',
          message:
            segments.length === 0
              ? 'This path template has no {segments}. Use a name that appears in the path (e.g. /users/{id}) or edit the path template first.'
              : `The name must match a segment in the path template. Expected one of: ${segments.map((s) => `{${s}}`).join(', ')}.`,
          variant: 'warning',
        });
        return;
      }
    }

    const nameErr = validateOpenApiParameterName(newParamName.trim(), newParamLocation);
    if (nameErr) {
      await alertDialog({
        title: 'Invalid parameter name',
        message: nameErr,
        variant: 'warning',
      });
      return;
    }

    setIsSaving(true);
    try {
      const schemaData: Record<string, unknown> = {
        type: 'string',
        required: newParamRequired,
        explode: false,
      };
      if (newParamLocation === 'path' || newParamLocation === 'header') {
        schemaData.style = 'simple';
      } else {
        schemaData.style = 'form';
      }

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

  const handleLinkExistingParameter = async () => {
    if (!operationId || !reuseParamId) return;

    setIsSaving(true);
    try {
      const linkResult = await linkParameterToOperation(operationId, reuseParamId);
      const linkParsed = JSON.parse(linkResult);

      if (linkParsed.success) {
        const paramsResult = await getLinkedParametersForOperation(operationId);
        const paramsData = JSON.parse(paramsResult);
        if (paramsData.success) {
          setParameters(paramsData.parameters || []);
        }
        setViewMode('operation');
        setReuseParamId('');
        setParamAttachMode('create');
        resetNewParamForm();
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: linkParsed.error || 'Failed to link parameter',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error linking shared parameter:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to link parameter. Please try again.',
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

  const handleLinkExistingResponse = async () => {
    if (!operationId || !reuseResponseId) return;

    setIsSaving(true);
    try {
      const linkResult = await linkResponseToOperation(operationId, reuseResponseId);
      const linkParsed = JSON.parse(linkResult);

      if (linkParsed.success) {
        const responsesResult = await getLinkedResponsesForOperation(operationId);
        const responsesData = JSON.parse(responsesResult);
        if (responsesData.success) {
          setResponses(responsesData.responses || []);
        }
        setViewMode('operation');
        setReuseResponseId('');
        setResponseAttachMode('create');
        resetNewResponseForm();
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
      console.error('Error linking shared response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to link response. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  /** Add default response (catch-all for error handling) to this operation in one click. */
  const handleAddDefaultResponse = async () => {
    if (!operationId || !versionPathId) return;
    const hasDefault = responses.some((r) => r.status_code === 'default');
    if (hasDefault) {
      await alertDialog({
        title: 'Already added',
        message: 'This operation already has a default (catch-all) response.',
        variant: 'warning',
      });
      return;
    }

    setIsSaving(true);
    try {
      const defaultDescription = 'Default error response (catch-all for unhandled statuses).';
      const schemaData = { type: 'object', properties: [] };
      const sharedResponseResult = await createSharedPathResponse(
        versionPathId,
        'default',
        defaultDescription,
        schemaData
      );
      const sharedResponseParsed = JSON.parse(sharedResponseResult);

      if (!sharedResponseParsed.success) {
        await alertDialog({
          title: 'Error',
          message: sharedResponseParsed.error || 'Failed to create default response',
          variant: 'error',
        });
        setIsSaving(false);
        return;
      }

      const linkResult = await linkResponseToOperation(
        operationId,
        sharedResponseParsed.response.id
      );
      const linkParsed = JSON.parse(linkResult);

      if (linkParsed.success) {
        const responsesResult = await getLinkedResponsesForOperation(operationId);
        const responsesData = JSON.parse(responsesResult);
        if (responsesData.success) {
          setResponses(responsesData.responses || []);
        }
        if (onRefresh) onRefresh();
      } else {
        await alertDialog({
          title: 'Error',
          message: linkParsed.error || 'Failed to link default response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding default response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add default response. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Add a new OR requirement (one scheme by default)
  const handleAddSecurity = () => {
    setSecurity((prev) => [...prev, { bearerAuth: [] }]);
  };

  // Remove entire OR requirement at index
  const handleRemoveSecurity = (index: number) => {
    setSecurity((prev) => prev.filter((_, i) => i !== index));
  };

  // Add another scheme (AND) to the requirement at reqIndex
  const handleAddSchemeToRequirement = (reqIndex: number) => {
    setSecurity((prev) => {
      const next = [...prev];
      const req = { ...next[reqIndex] };
      const existing = Object.keys(req);
      const availableFromList = securitySchemes.find((s) => !existing.includes(s.scheme_name))?.scheme_name;
      // Use an unused scheme from the list, or a unique placeholder so we always add a new row (user can rename)
      const newKey = availableFromList ?? `__new__${Date.now()}`;
      req[newKey] = [];
      next[reqIndex] = req;
      return next;
    });
  };

  // Remove one scheme from a requirement; remove the requirement if it becomes empty
  const handleRemoveSchemeFromRequirement = (reqIndex: number, schemeName: string) => {
    setSecurity((prev) => {
      const next = [...prev];
      const req = { ...next[reqIndex] };
      delete req[schemeName];
      if (Object.keys(req).length === 0) {
        next.splice(reqIndex, 1);
      } else {
        next[reqIndex] = req;
      }
      return next;
    });
  };

  // Update scopes for one scheme in a requirement (keep other schemes in that requirement)
  const handleUpdateSecurity = (reqIndex: number, schemeName: string, scopes: string[]) => {
    setSecurity((prev) => {
      const next = [...prev];
      const key = schemeName.trim() || 'bearerAuth';
      next[reqIndex] = { ...next[reqIndex], [key]: scopes };
      return next;
    });
  };

  // Rename a scheme in a requirement (e.g. dropdown change); keep scopes
  const handleRenameSecurityScheme = (
    reqIndex: number,
    oldName: string,
    newName: string,
    scopes: string[]
  ) => {
    setSecurity((prev) => {
      const next = [...prev];
      const req = { ...next[reqIndex] };
      delete req[oldName];
      req[newName.trim() || 'bearerAuth'] = scopes;
      next[reqIndex] = req;
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
    setParamAttachMode('create');
    setReuseParamId('');
    setViewMode('add-parameter');
  };

  const handleBackToOperation = () => {
    setViewMode('operation');
    resetNewParamForm();
    resetNewResponseForm();
    setParamAttachMode('create');
    setResponseAttachMode('create');
    setReuseParamId('');
    setReuseResponseId('');
  };

  if (!operationId) return null;

  return (
    <div
      className="w-80 h-full flex flex-col border-l"
      style={{
        borderColor: isDark ? '#334155' : '#e2e8f0',
        background: isDark
          ? 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)'
          : 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
      }}
    >
      {/* Header */}
      <div
        className={`p-4 border-b flex justify-between items-center ${
          isDark ? 'border-slate-700' : 'border-slate-200'
        }`}
      >
        {viewMode === 'add-parameter' || viewMode === 'add-response' ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleBackToOperation}
              className={`p-1 rounded transition-colors ${
                isDark ? 'text-slate-400 hover:bg-slate-700' : 'text-slate-500 hover:bg-slate-100'
              }`}
              aria-label="Back to operation"
            >
              <ArrowLeft className="w-[18px] h-[18px]" />
            </button>
            <div>
              <span className="text-sm font-semibold text-gray-900 dark:text-white">
                {viewMode === 'add-parameter' ? 'Add Parameter' : 'Add Response'}
              </span>
              <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {operation} {pathname}
              </div>
            </div>
          </div>
        ) : (
          <div>
            <span className="text-sm font-semibold text-gray-900 dark:text-white">
              Operation Details
            </span>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {operation} {pathname}
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={onClose}
          className={`p-1 rounded transition-colors ${
            isDark ? 'text-slate-400 hover:bg-slate-700' : 'text-slate-500 hover:bg-slate-100'
          }`}
          aria-label="Close panel"
        >
          <X className="w-[18px] h-[18px]" />
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="p-6 flex justify-center">
          <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
        </div>
      ) : viewMode === 'add-response' ? (
        /* Add Response Form */
        <>
          <div className="flex-1 overflow-auto p-4">
            <div className="flex flex-col gap-4">
              <div
                className={`flex rounded-lg border p-0.5 ${
                  isDark ? 'border-slate-600 bg-slate-800/80' : 'border-slate-200 bg-slate-100'
                }`}
              >
                <button
                  type="button"
                  className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                    responseAttachMode === 'create'
                      ? isDark
                        ? 'bg-slate-700 text-indigo-300 shadow-sm'
                        : 'bg-white text-indigo-600 shadow-sm'
                      : isDark
                        ? 'text-slate-400'
                        : 'text-slate-600'
                  }`}
                  onClick={() => setResponseAttachMode('create')}
                >
                  Create new
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                    responseAttachMode === 'reuse'
                      ? isDark
                        ? 'bg-slate-700 text-indigo-300 shadow-sm'
                        : 'bg-white text-indigo-600 shadow-sm'
                      : isDark
                        ? 'text-slate-400'
                        : 'text-slate-600'
                  }`}
                  onClick={() => setResponseAttachMode('reuse')}
                >
                  Reuse library
                </button>
              </div>

              {responseAttachMode === 'reuse' ? (
                <>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Attach a shared response from this path version. Operations use stable links; the schema is not duplicated.
                  </p>
                  <ReuseSearchCombobox
                    aria-label="Shared response to attach"
                    items={unlinkedSharedResponses.map((r) => ({
                      id: r.id,
                      label: String(r.status_code),
                      description: r.description?.trim() || undefined,
                    }))}
                    value={reuseResponseId}
                    onValueChange={setReuseResponseId}
                    placeholder="Search responses…"
                    searchPlaceholder="Filter by status or description…"
                    emptyText="No unlinked responses. Create one under “Create new” or unlink from another operation."
                    triggerClassName="h-9 text-sm"
                  />
                </>
              ) : (
                <>
              {/* Status Code */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Status Code <span className="text-red-500">*</span>
                </Label>
                <Input
                  className="w-full text-sm"
                  value={newResponseStatusCode}
                  onChange={(e) => handleStatusCodeChange(e.target.value)}
                  placeholder="200, 2XX, 404, etc."
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  HTTP status code or pattern (e.g., 200, 2XX for all 2xx responses)
                </p>
              </div>

              {/* Description */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </Label>
                <Textarea
                  rows={4}
                  className="w-full text-sm"
                  value={newResponseDescription}
                  onChange={(e) => {
                    setNewResponseDescription(e.target.value);
                    if (newResponseAutoFillDescription) {
                      setNewResponseAutoFillDescription(false);
                    }
                  }}
                  placeholder="Describe when this response is returned..."
                />
                <label className="flex items-center gap-2 mt-2 cursor-pointer">
                  <Checkbox
                    checked={newResponseAutoFillDescription}
                    onCheckedChange={(checked) => handleAutoFillToggle(checked === true)}
                  />
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    Auto-fill description from status code
                  </span>
                </label>
              </div>

              {/* Schema Type */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Response Schema Type
                </Label>
                <Select value={newResponseSchemaType} onValueChange={(v) => setNewResponseSchemaType(v as typeof newResponseSchemaType)}>
                  <SelectTrigger className="w-full h-9 text-sm">
                    <SelectValue placeholder="Schema type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="object">Object (default)</SelectItem>
                    <SelectItem value="string">String</SelectItem>
                    <SelectItem value="number">Number</SelectItem>
                    <SelectItem value="integer">Integer</SelectItem>
                    <SelectItem value="boolean">Boolean</SelectItem>
                    <SelectItem value="array">Array</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  The type of data returned in the response body
                </p>
              </div>

              {newResponseSchemaType === 'array' && (
                <div>
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Array Item Type
                  </Label>
                  <Select value={newResponseArrayItemType} onValueChange={(v) => setNewResponseArrayItemType(v as typeof newResponseArrayItemType)}>
                    <SelectTrigger className="w-full h-9 text-sm">
                      <SelectValue placeholder="Item type" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="string">String</SelectItem>
                      <SelectItem value="number">Number</SelectItem>
                      <SelectItem value="integer">Integer</SelectItem>
                      <SelectItem value="boolean">Boolean</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    The type of items in the array
                  </p>
                </div>
              )}
                </>
              )}
            </div>
          </div>

          {/* Footer with Save button */}
          <div
            className={`p-4 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}
          >
            {responseAttachMode === 'reuse' ? (
              <Button
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white disabled:opacity-60 disabled:cursor-not-allowed"
                onClick={handleLinkExistingResponse}
                disabled={isSaving || !reuseResponseId}
              >
                <Save className="w-4 h-4" />
                {isSaving ? 'Attaching…' : 'Attach to operation'}
              </Button>
            ) : (
              <Button
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white disabled:opacity-60 disabled:cursor-not-allowed"
                onClick={handleSaveResponse}
                disabled={isSaving || !newResponseStatusCode.trim()}
              >
                <Save className="w-4 h-4" />
                {isSaving ? 'Saving...' : 'Save'}
              </Button>
            )}
          </div>
        </>
      ) : viewMode === 'add-parameter' ? (
        /* Add Parameter Form */
        <>
          <div className="flex-1 overflow-auto p-4">
            <div className="flex flex-col gap-4">
              <div
                className={`flex rounded-lg border p-0.5 ${
                  isDark ? 'border-slate-600 bg-slate-800/80' : 'border-slate-200 bg-slate-100'
                }`}
              >
                <button
                  type="button"
                  className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                    paramAttachMode === 'create'
                      ? isDark
                        ? 'bg-slate-700 text-indigo-300 shadow-sm'
                        : 'bg-white text-indigo-600 shadow-sm'
                      : isDark
                        ? 'text-slate-400'
                        : 'text-slate-600'
                  }`}
                  onClick={() => setParamAttachMode('create')}
                >
                  Create new
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                    paramAttachMode === 'reuse'
                      ? isDark
                        ? 'bg-slate-700 text-indigo-300 shadow-sm'
                        : 'bg-white text-indigo-600 shadow-sm'
                      : isDark
                        ? 'text-slate-400'
                        : 'text-slate-600'
                  }`}
                  onClick={() => setParamAttachMode('reuse')}
                >
                  Reuse library
                </button>
              </div>

              {paramAttachMode === 'reuse' ? (
                <>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Attach a shared parameter already defined for this path version (query, header, cookie, or path).
                  </p>
                  <ReuseSearchCombobox
                    aria-label="Shared parameter to attach"
                    items={unlinkedSharedParams.map((p) => ({
                      id: p.id,
                      label: p.name,
                      description: `${p.in_location}${p.summary ? ` · ${p.summary}` : ''}`,
                    }))}
                    value={reuseParamId}
                    onValueChange={setReuseParamId}
                    placeholder="Search parameters…"
                    searchPlaceholder="Filter by name or location…"
                    emptyText="No unlinked parameters. Create one under “Create new” or unlink from another operation."
                    triggerClassName="h-9 text-sm"
                  />
                </>
              ) : (
                <>
              {/* Parameter Name */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Parameter Name <span className="text-red-500">*</span>
                </Label>
                {newParamLocation === 'path' && unlinkedPathParams.length > 0 ? (
                  <Select value={newParamName || undefined} onValueChange={setNewParamName}>
                    <SelectTrigger className="w-full h-9 text-sm">
                      <SelectValue placeholder="Select a path parameter" />
                    </SelectTrigger>
                    <SelectContent>
                      {unlinkedPathParams.map((param) => (
                        <SelectItem key={param} value={param}>
                          {param}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    className="w-full text-sm"
                    value={newParamName}
                    onChange={(e) => setNewParamName(e.target.value)}
                    placeholder={
                      newParamLocation === 'query' ? 'e.g., limit, offset, filter' :
                      newParamLocation === 'header' ? 'e.g., Authorization, X-Request-ID' :
                      newParamLocation === 'cookie' ? 'e.g., session, token' :
                      'e.g., userId, groupId'
                    }
                  />
                )}
                {newParamLocation === 'path' && unlinkedPathParams.length > 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Select from path parameters in: {pathname}
                  </p>
                )}
              </div>

              {/* Location */}
              <div>
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
              </div>

              {/* Required */}
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={newParamRequired}
                  onCheckedChange={(checked) => setNewParamRequired(checked === true)}
                />
                <span className="text-xs text-gray-700 dark:text-gray-300">
                  Required parameter
                </span>
              </label>

              {/* Summary */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Summary
                </Label>
                <Input
                  className="w-full text-sm"
                  value={newParamSummary}
                  onChange={(e) => setNewParamSummary(e.target.value)}
                  placeholder="Brief description"
                />
              </div>

              {/* Description */}
              <div>
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </Label>
                <Textarea
                  rows={4}
                  className="w-full text-sm"
                  value={newParamDescription}
                  onChange={(e) => setNewParamDescription(e.target.value)}
                  placeholder="Detailed description..."
                />
              </div>
                </>
              )}
            </div>
          </div>

          {/* Footer with Save button */}
          <div
            className={`p-4 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}
          >
            {paramAttachMode === 'reuse' ? (
              <Button
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white disabled:opacity-60 disabled:cursor-not-allowed"
                onClick={handleLinkExistingParameter}
                disabled={isSaving || !reuseParamId}
              >
                <Save className="w-4 h-4" />
                {isSaving ? 'Attaching…' : 'Attach to operation'}
              </Button>
            ) : (
              <Button
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white disabled:opacity-60 disabled:cursor-not-allowed"
                onClick={handleSaveParameter}
                disabled={isSaving || !newParamName.trim()}
              >
                <Save className="w-4 h-4" />
                {isSaving ? 'Saving...' : 'Save'}
              </Button>
            )}
          </div>
        </>
      ) : (
        /* Operation Details Form */
        <>
          <div className="flex-1 overflow-auto p-4 min-h-0">
            {optionsRequestBodyLinked && operation === 'OPTIONS' && (
              <div
                className="mb-3 p-3 rounded-md border text-xs shrink-0 bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200"
                role="status"
              >
                <span className="font-semibold">Request body linked:</span>{' '}
                OpenAPI usually documents OPTIONS without a request body (CORS preflight). Exported spec omits{' '}
                <code className="font-mono text-[11px]">requestBody</code> for this method; unlink the body if that matches
                your intent.
              </div>
            )}
            <Tabs defaultValue="general" className="flex flex-col gap-3 min-h-0">
              <TabsList className="w-full h-auto min-h-10 shrink-0 flex flex-wrap justify-start gap-1 p-1">
                <TabsTrigger value="general" className="text-xs px-2 py-1.5">
                  General
                </TabsTrigger>
                <TabsTrigger value="docs" className="text-xs px-2 py-1.5">
                  Docs
                </TabsTrigger>
                <TabsTrigger value="tags" className="text-xs px-2 py-1.5">
                  Tags
                </TabsTrigger>
                <TabsTrigger value="advanced" className="text-xs px-2 py-1.5">
                  Advanced
                </TabsTrigger>
              </TabsList>

              <TabsContent value="general" className="mt-0 flex flex-col gap-4 outline-none">
                <div>
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    operationId
                  </Label>
                  <Input
                    className="w-full text-sm font-mono"
                    value={operationIdName}
                    onChange={(e) => setOperationIdName(e.target.value)}
                    placeholder="Auto-generated from path and verb"
                    autoComplete="off"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Must be unique among all operations in this API version. Used for codegen and clients.
                  </p>
                </div>
                <label className="flex items-center gap-2 cursor-pointer w-fit">
                  <Checkbox
                    checked={deprecated}
                    onCheckedChange={(checked) => setDeprecated(checked === true)}
                  />
                  <span
                    className={`text-xs ${deprecated ? 'text-amber-600 dark:text-amber-400' : 'text-gray-700 dark:text-gray-300'}`}
                  >
                    deprecated
                  </span>
                </label>
              </TabsContent>

              <TabsContent value="docs" className="mt-0 flex flex-col gap-4 outline-none">
                <div>
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    summary
                  </Label>
                  <Input
                    className="w-full text-sm"
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    placeholder="Brief summary of the operation"
                  />
                </div>
                <div>
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    description
                  </Label>
                  <Textarea
                    rows={5}
                    className="w-full text-sm font-mono"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Detailed description (Markdown supported)"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Preview</p>
                  <div
                    className={`mt-1 max-h-40 overflow-y-auto rounded-md border p-3 text-sm ${
                      isDark ? 'border-slate-600 bg-slate-900/80' : 'border-slate-200 bg-white'
                    }`}
                  >
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {description.trim() ? description : '*No description yet.*'}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="tags" className="mt-0 flex flex-col gap-3 outline-none">
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  OpenAPI <code className="text-[11px]">tags</code> group operations in documentation UIs.
                </p>
                <div className="flex flex-wrap gap-1.5 min-h-[28px]">
                  {tags.length === 0 ? (
                    <span className="text-xs text-gray-500 dark:text-gray-400 italic">No tags</span>
                  ) : (
                    tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-gray-800 dark:text-gray-100"
                      >
                        {tag}
                        <button
                          type="button"
                          className="rounded p-0.5 text-gray-500 hover:bg-indigo-500/20 hover:text-gray-900 dark:hover:text-white"
                          onClick={() => removeTag(tag)}
                          aria-label={`Remove tag ${tag}`}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))
                  )}
                </div>
                <div className="flex gap-2">
                  <Input
                    className="flex-1 text-sm"
                    value={tagDraft}
                    onChange={(e) => setTagDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addTag();
                      }
                    }}
                    placeholder="e.g. Users"
                  />
                  <Button type="button" size="sm" variant="secondary" className="shrink-0" onClick={addTag}>
                    Add
                  </Button>
                </div>
              </TabsContent>

              <TabsContent value="advanced" className="mt-0 flex flex-col gap-4 outline-none">
                <label className="flex items-center gap-2 cursor-pointer w-fit">
                  <Checkbox
                    checked={xPrivate}
                    onCheckedChange={(checked) => setXPrivate(checked === true)}
                  />
                  <span
                    className={`text-xs flex items-center gap-1 ${xPrivate ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-700 dark:text-gray-300'}`}
                  >
                    <Lock className="w-3.5 h-3.5" />
                    Hidden from public docs (x-private)
                  </span>
                </label>

              {/* Custom x-* extensions */}
              <div className="mt-4">
                <ExtensionsEditor
                  value={extensions as Record<string, any>}
                  onChange={setExtensions as (v: Record<string, any>) => void}
                  size="small"
                />
              </div>

              {/* External documentation (OpenAPI externalDocs) */}
              <div className="mt-4">
                <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-1.5">
                  <ExternalLink className="w-3.5 h-3.5" />
                  External documentation
                </Label>
                <Input
                  type="url"
                  className="w-full text-sm mb-2"
                  placeholder="https://docs.example.com/..."
                  value={externalDocsUrl}
                  onChange={(e) => setExternalDocsUrl(e.target.value)}
                />
                <Textarea
                  rows={2}
                  className="w-full text-sm"
                  placeholder="Brief description of external docs (optional)"
                  value={externalDocsDescription}
                  onChange={(e) => setExternalDocsDescription(e.target.value)}
                />
              </div>

              {/* Parameters Section */}
              <div className="mt-4">
                <div className="flex justify-between items-center mb-2">
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
                    Parameters
                  </Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={handleAddParameterClick}
                    className="text-indigo-600 dark:text-indigo-400 text-xs hover:bg-indigo-500/10"
                  >
                    <Plus className="w-4 h-4" />
                    Add Parameter
                  </Button>
                </div>

                {parametersLoading ? (
                  <div className="py-4 text-center">
                    <span className="text-xs text-gray-500 dark:text-gray-400">Loading parameters...</span>
                  </div>
                ) : parameters.length === 0 ? (
                  <div
                    className={`py-6 px-4 text-center rounded border border-dashed ${
                      isDark ? 'border-slate-700' : 'border-slate-200'
                    }`}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No parameters defined yet
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col gap-1">
                    {parameters.map((param) => (
                      <div
                        key={param.id}
                        className={`p-3 rounded border flex justify-between items-start ${
                          isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-200 bg-gray-50'
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-gray-900 dark:text-white truncate">
                            {param.name}
                          </div>
                          <div className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
                            {param.in_location} • {param.data?.required ? 'required' : 'optional'}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <span
                            className="px-2 py-0.5 rounded text-[10px] font-semibold text-white"
                            style={{
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
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDeleteParameter(param.id, param.name)}
                            className="p-1 rounded text-red-500 hover:bg-red-500/10 transition-colors"
                            aria-label={`Delete ${param.name}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Request body: shared_path_request_body + content rows + operation link (#2648); OPTIONS optional (#2653 warn-only vs export) */}
              {['POST', 'PUT', 'PATCH', 'OPTIONS'].includes(operation) && operationId && versionPathId && (
                <div className={`mt-4 pt-4 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
                  <RequestBodySection
                    operationId={operationId}
                    versionPathId={versionPathId}
                    onRefresh={onRefresh}
                    refreshKey={refreshKey}
                  />
                </div>
              )}

              {/* Responses Section */}
              <div className="mt-4">
                <div className="flex justify-between items-center mb-2">
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
                    Responses
                  </Label>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleAddDefaultResponse}
                      disabled={isSaving || responses.some((r) => r.status_code === 'default')}
                      className="text-slate-600 dark:text-slate-400 text-xs hover:bg-slate-500/10 disabled:opacity-50"
                      title={
                        responses.some((r) => r.status_code === 'default')
                          ? 'Default (catch-all) response already added'
                          : 'Add default response for catch-all error handling'
                      }
                    >
                      <ListChecks className="w-4 h-4" />
                      Add default
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        resetNewResponseForm(operation === 'OPTIONS' ? '204' : '200');
                        setResponseAttachMode('create');
                        setReuseResponseId('');
                        setViewMode('add-response');
                      }}
                      className="text-indigo-600 dark:text-indigo-400 text-xs hover:bg-indigo-500/10"
                    >
                      <Plus className="w-4 h-4" />
                      Add Response
                    </Button>
                  </div>
                </div>

                {responsesLoading ? (
                  <div className="py-4 text-center">
                    <span className="text-xs text-gray-500 dark:text-gray-400">Loading responses...</span>
                  </div>
                ) : responses.length === 0 ? (
                  <div
                    className={`py-6 px-4 text-center rounded border border-dashed ${
                      isDark ? 'border-slate-700' : 'border-slate-200'
                    }`}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No responses defined yet
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col gap-4">
                    {responses.map((response) => (
                      <div
                        key={response.id}
                        className={`rounded border overflow-hidden ${
                          isDark ? 'border-slate-700' : 'border-slate-200'
                        }`}
                      >
                        {/* Response Header */}
                        <div
                          className={`p-3 flex justify-between items-center border-b ${
                            isDark ? 'bg-slate-900 border-slate-700' : 'bg-gray-50 border-slate-200'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <div
                              className="px-3 py-1 rounded text-xs font-bold text-white"
                              style={{
                                backgroundColor:
                                  response.status_code === 'default' ? '#64748b' :
                                  response.status_code.startsWith('2') ? '#10b981' :
                                  response.status_code.startsWith('3') ? '#3b82f6' :
                                  response.status_code.startsWith('4') ? '#f59e0b' :
                                  response.status_code.startsWith('5') ? '#ef4444' :
                                  '#64748b',
                              }}
                            >
                              {response.status_code}
                            </div>
                            {response.description && (
                              <div className="text-sm text-gray-500 dark:text-gray-400">
                                {response.description}
                              </div>
                            )}
                          </div>
                          <button
                            type="button"
                            onClick={() => handleDeleteResponse(response.id, response.status_code)}
                            className="p-1 rounded text-red-500 hover:bg-red-500/10 transition-colors"
                            aria-label={`Delete response ${response.status_code}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        {/* Response Schema Section */}
                        <div className={`p-4 ${isDark ? 'bg-slate-800' : 'bg-white'}`}>
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
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Security Section: OR = alternative requirements, AND = schemes within a requirement */}
              <div className={`mt-4 pt-4 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
                <div className="flex justify-between items-center mb-2">
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
                    <Lock size={14} className="text-amber-500" />
                    Security
                  </Label>
                  {!unsecured && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleAddSecurity}
                      className="text-indigo-600 dark:text-indigo-400 text-xs hover:bg-indigo-500/10"
                    >
                      Add requirement (OR)
                    </Button>
                  )}
                </div>
                <label className="flex items-center gap-2 mb-3 cursor-pointer">
                  <Checkbox
                    checked={unsecured}
                    onCheckedChange={(checked) => {
                      setUnsecured(checked === true);
                      if (checked) setSecurity([]);
                    }}
                  />
                  <span className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-1.5">
                    <Unlock size={12} />
                    Unsecured (public endpoint — no authentication)
                  </span>
                </label>
                <div className="mb-3">
                  <Label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Security description (documentation)
                  </Label>
                  <Textarea
                    rows={2}
                    className="w-full text-sm"
                    placeholder="Describe how security applies to this operation"
                    value={securityDescription}
                    onChange={(e) => setSecurityDescription(e.target.value)}
                  />
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                    Exported as x-security-description in OpenAPI for documentation and doc generators.
                  </p>
                </div>
                {!unsecured && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                    OR = alternative options; within an option, schemes are AND (all required).
                  </p>
                )}
                {unsecured ? (
                  <div
                    className={`py-4 px-4 text-center rounded border ${
                      isDark ? 'border-slate-700 bg-green-500/10' : 'border-slate-200 bg-green-500/10'
                    }`}
                  >
                    <span className="text-xs text-green-700 dark:text-green-400 flex items-center justify-center gap-1.5">
                      <Unlock size={14} />
                      Public endpoint — no authentication required
                    </span>
                  </div>
                ) : security.length === 0 ? (
                  <div
                    className={`py-4 px-4 text-center rounded border border-dashed ${
                      isDark ? 'border-slate-700' : 'border-slate-200'
                    }`}
                  >
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      No security requirements
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {security.map((req, reqIndex) => (
                      <div
                        key={reqIndex}
                        className={`p-3 rounded border flex flex-col gap-2 ${
                          isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-200 bg-gray-50'
                        }`}
                      >
                        <div className="flex justify-between items-center flex-wrap gap-1">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                            Option {reqIndex + 1} (OR)
                          </span>
                          <button
                            type="button"
                            onClick={() => handleRemoveSecurity(reqIndex)}
                            className="p-1 rounded text-red-500 hover:bg-red-500/10 transition-colors"
                            title="Remove this requirement (OR)"
                            aria-label="Remove requirement"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {Object.entries(req).map(([schemeName, scopes]) => (
                          <div
                            key={schemeName}
                            className={`pl-2 border-l-2 flex flex-col gap-2 ${
                              isDark ? 'border-slate-700' : 'border-slate-200'
                            }`}
                          >
                            <div className="flex items-start gap-1">
                              <div className="flex-1 flex flex-col gap-1">
                                {securitySchemes.length > 0 ? (
                                  <>
                                    <Select
                                      value={schemeName.startsWith('__new__') || !securitySchemes.some((s) => s.scheme_name === schemeName) ? '__custom__' : schemeName}
                                      onValueChange={(v) => {
                                        handleRenameSecurityScheme(
                                          reqIndex,
                                          schemeName,
                                          v === '__custom__' ? '' : v,
                                          scopes || []
                                        );
                                      }}
                                    >
                                      <SelectTrigger className="h-9 text-sm w-full">
                                        <SelectValue placeholder="Scheme" />
                                      </SelectTrigger>
                                      <SelectContent>
                                        {securitySchemes.map((s) => (
                                          <SelectItem key={s.scheme_name} value={s.scheme_name}>
                                            {s.scheme_type === 'http'
                                              ? `${s.scheme_name} (HTTP: ${s.http_scheme || 'basic'})`
                                              : s.scheme_type === 'oauth2'
                                              ? `${s.scheme_name} (OAuth2)`
                                              : s.scheme_type === 'openIdConnect'
                                              ? `${s.scheme_name} (OpenID Connect)`
                                              : s.scheme_type === 'mutualTLS'
                                              ? `${s.scheme_name} (Mutual TLS)`
                                              : s.scheme_type === 'custom'
                                              ? `${s.scheme_name} (Custom)`
                                              : `${s.scheme_name} (${s.in_location || 'header'}: ${s.param_name || s.scheme_name})`}
                                          </SelectItem>
                                        ))}
                                        <SelectItem value="__custom__">Other (bearerAuth, oauth2...)</SelectItem>
                                      </SelectContent>
                                    </Select>
                                    {(schemeName.startsWith('__new__') || !schemeName || !securitySchemes.some((s) => s.scheme_name === schemeName)) && (
                                      <Input
                                        className="w-full text-sm mt-1"
                                        placeholder="Custom scheme name"
                                        value={schemeName.startsWith('__new__') ? '' : schemeName}
                                        onChange={(e) =>
                                          handleRenameSecurityScheme(reqIndex, schemeName, e.target.value, scopes || [])
                                        }
                                      />
                                    )}
                                  </>
                                ) : (
                                  <Input
                                    className="w-full text-sm"
                                    placeholder="Scheme name (e.g., apiKey, bearerAuth)"
                                    value={schemeName.startsWith('__new__') ? '' : schemeName}
                                    onChange={(e) =>
                                      handleRenameSecurityScheme(reqIndex, schemeName, e.target.value, scopes || [])
                                    }
                                  />
                                )}
                                {(() => {
                                  const scheme = securitySchemes.find((s) => s.scheme_name === schemeName);
                                  const supportsScopes =
                                    scheme
                                      ? scheme.scheme_type === 'oauth2' || scheme.scheme_type === 'openIdConnect'
                                      : schemeName === 'oauth2' || schemeName === 'openIdConnect';
                                  return supportsScopes ? (
                                    <div className="mt-1">
                                      <Input
                                        className="w-full text-sm"
                                        placeholder="Required scopes (comma-separated)"
                                        value={(scopes || []).join(', ')}
                                        onChange={(e) => {
                                          const scopeList = e.target.value
                                            .split(',')
                                            .map((s) => s.trim())
                                            .filter(Boolean);
                                          handleUpdateSecurity(reqIndex, schemeName, scopeList);
                                        }}
                                      />
                                      <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
                                        OAuth2/OpenID Connect: scopes required for this operation
                                      </p>
                                    </div>
                                  ) : null;
                                })()}
                              </div>
                              <button
                                type="button"
                                onClick={() => handleRemoveSchemeFromRequirement(reqIndex, schemeName)}
                                className="p-1.5 rounded text-red-500 hover:bg-red-500/10 transition-colors shrink-0"
                                title="Remove this scheme (AND)"
                                aria-label="Remove scheme"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                        ))}
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleAddSchemeToRequirement(reqIndex)}
                          className="text-emerald-600 dark:text-emerald-400 text-xs self-start hover:bg-emerald-500/10"
                        >
                          <Plus className="w-4 h-4" />
                          Add scheme (AND)
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              </TabsContent>
            </Tabs>
          </div>

          {/* Footer with Save button */}
          <div
            className={`p-4 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}
          >
            <Button
              className={`w-full text-white ${
                saveStatus === 'saved'
                  ? 'bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-700 hover:to-emerald-600'
                  : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700'
              } disabled:opacity-60 disabled:cursor-not-allowed`}
              onClick={handleSaveOperation}
              disabled={isSaving}
            >
              <Save className="w-4 h-4" />
              {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved ✓' : 'Save'}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}


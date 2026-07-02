'use client';

import React, { useState, useEffect, useMemo } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Hash, Sparkles, Search, Shield, User, Loader2, Database, Save } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import PropertiesPanelShell from './PropertiesPanelShell';
import PropertiesPanelSection from './PropertiesPanelSection';
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
  getLinkedParametersForOperation,
  getSharedPathParameters,
  updateSharedPathParameter,
  unlinkParameterFromOperation,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import { getClassesWithPropertiesAndTags } from '../../../../../../lib/db/helper';
import { extractPathParameters, getPathParameterCoverageError } from '../../../../../../lib/utils/path-params';
import { propertyDataToParameterSchema } from '../../../../../../lib/utils/path-parameter-schema';
import { validateOpenApiParameterName } from '../../../../../../lib/utils/openapi-parameter-name';
import {
  PARAM_STYLE_OPTIONS,
  defaultStyleForIn,
  normalizeStyleForLocation,
  type ParamSerializationStyle,
} from '../../../../../../lib/utils/openapi-parameter-style';
import { useStudio } from '../../StudioContext';

// Simple types allowed for path parameters (no 'object')
const SCHEMA_TYPES = [
  { value: 'string', label: 'String' },
  { value: 'integer', label: 'Integer' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'array', label: 'Array' },
] as const;

// Sentinel for "no format" in Radix Select (Select.Item cannot have value="")
const FORMAT_NONE_VALUE = '__none__';

// Common string formats (empty string = none, stored in schema; use FORMAT_NONE_VALUE for Select UI only)
const STRING_FORMATS = [
  { value: '', label: 'None' },
  { value: 'date', label: 'Date (YYYY-MM-DD)' },
  { value: 'date-time', label: 'DateTime (ISO 8601)' },
  { value: 'time', label: 'Time (HH:MM:SS)' },
  { value: 'email', label: 'Email' },
  { value: 'uri', label: 'URI' },
  { value: 'uuid', label: 'UUID' },
  { value: 'hostname', label: 'Hostname' },
  { value: 'ipv4', label: 'IPv4' },
  { value: 'ipv6', label: 'IPv6' },
];

// Array item types
const ARRAY_ITEM_TYPES = [
  { value: 'string', label: 'String' },
  { value: 'integer', label: 'Integer' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
];

// Common parameter name patterns for suggestion (query, header, cookie, and path)
const COMMON_PARAM_NAMES = [
  // Path / resource
  'id', 'ids', 'slug', 'version', 'type', 'name', 'key',
  // Pagination
  'limit', 'offset', 'page', 'pageSize', 'per_page', 'size',
  // Sort / order
  'sort', 'order', 'orderBy', 'order_by', 'direction', 'asc', 'desc',
  // Filter / search
  'filter', 'q', 'query', 'search', 'keywords',
  // Field selection / expand
  'fields', 'expand', 'select', 'include', 'embed', 'with',
  // Cursor / time range
  'cursor', 'next', 'since', 'until', 'before', 'after',
  // Response format
  'format', 'callback', 'pretty',
  // Headers / common
  'Authorization', 'X-Request-ID', 'X-Correlation-ID', 'Accept', 'Content-Type',
  'include_deleted',
];

// Primitive from REST API (for Apply from primitive template)
interface PrimitiveTemplate {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  category: string;
  schema: Record<string, unknown>;
  tags: string[];
  is_system: boolean;
  usage_count: number;
}

interface DesignerPropOption {
  key: string;
  classId: string;
  className: string;
  propertyId: string;
  propertyName: string;
  data: Record<string, unknown>;
}

interface LoadedSharedParameter {
  id: string;
  name: string;
  in_location: 'path' | 'query' | 'header' | 'cookie';
  summary?: string | null;
  description?: string | null;
  data?: unknown;
}

interface ParameterPropertiesPanelProps {
  parameterId: string | null;
  operationId?: string; // Optional when opened from path variable click
  versionPathId: string | null;
  pathname: string;
  onClose: () => void;
  onRefresh?: () => void;
}

export default function ParameterPropertiesPanel({
  parameterId,
  operationId,
  versionPathId,
  pathname,
  onClose,
  onRefresh,
}: ParameterPropertiesPanelProps) {
  const isDark = useDarkMode();
  const { selectedVersionId } = useStudio();
  const { alert: alertDialog, confirm: confirmDialog } = useDialog();
  const [name, setName] = useState('');
  const [inLocation, setInLocation] = useState<'path' | 'query' | 'header' | 'cookie'>('path');
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState('');
  const [required, setRequired] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');
  const [availablePathParams, setAvailablePathParams] = useState<string[]>([]);

  // Schema state
  const [schemaType, setSchemaType] = useState<'string' | 'integer' | 'number' | 'boolean' | 'array'>('string');
  const [schemaFormat, setSchemaFormat] = useState('');
  const [schemaMinimum, setSchemaMinimum] = useState<string>('');
  const [schemaMaximum, setSchemaMaximum] = useState<string>('');
  const [schemaMinLength, setSchemaMinLength] = useState<string>('');
  const [schemaMaxLength, setSchemaMaxLength] = useState<string>('');
  const [schemaPattern, setSchemaPattern] = useState('');
  const [schemaDefault, setSchemaDefault] = useState('');
  const [schemaEnum, setSchemaEnum] = useState('');
  const [schemaArrayItemType, setSchemaArrayItemType] = useState<'string' | 'integer' | 'number' | 'boolean'>('string');
  const [paramStyle, setParamStyle] = useState<ParamSerializationStyle>(defaultStyleForIn('path'));
  const [paramExplode, setParamExplode] = useState(false);
  const [paramAllowReserved, setParamAllowReserved] = useState(false);

  const [schemaMode, setSchemaMode] = useState<'form' | 'inline'>('form');
  const [inlineSchemaText, setInlineSchemaText] = useState('{\n  "type": "string"\n}');
  const [designerProps, setDesignerProps] = useState<DesignerPropOption[]>([]);
  const [designerPropSearch, setDesignerPropSearch] = useState('');
  const [propertyRef, setPropertyRef] = useState<{
    classId: string;
    className: string;
    propertyId: string;
    propertyName: string;
  } | null>(null);

  // Primitive template dialog state (Apply from REST primitives)
  const [primitiveDialogOpen, setPrimitiveDialogOpen] = useState(false);
  const [primitives, setPrimitives] = useState<PrimitiveTemplate[]>([]);
  const [primitiveLoading, setPrimitiveLoading] = useState(false);
  const [primitiveError, setPrimitiveError] = useState<string | null>(null);
  const [primitiveSearch, setPrimitiveSearch] = useState('');
  const [showSystemPrimitives, setShowSystemPrimitives] = useState(true);
  const [showTenantPrimitives, setShowTenantPrimitives] = useState(true);
  const [selectedPrimitive, setSelectedPrimitive] = useState<PrimitiveTemplate | null>(null);

  // Load parameter details when parameterId changes (from operation link or from path variable click)
  useEffect(() => {
    if (!parameterId) {
      setName('');
      setInLocation('path');
      setSummary('');
      setDescription('');
      setRequired(true);
      // Reset schema state
      setSchemaType('string');
      setSchemaFormat('');
      setSchemaMinimum('');
      setSchemaMaximum('');
      setSchemaMinLength('');
      setSchemaMaxLength('');
      setSchemaPattern('');
      setSchemaDefault('');
      setSchemaEnum('');
      setSchemaArrayItemType('string');
      setParamStyle(defaultStyleForIn('path'));
      setParamExplode(false);
      setParamAllowReserved(false);
      setSchemaMode('form');
      setInlineSchemaText('{\n  "type": "string"\n}');
      setPropertyRef(null);
      setDesignerPropSearch('');
      return;
    }

    const loadParameter = async () => {
      setIsLoading(true);
      try {
        let param: LoadedSharedParameter | null = null;

        if (operationId) {
          const result = await getLinkedParametersForOperation(operationId);
          const data = JSON.parse(result) as {
            success?: boolean;
            parameters?: LoadedSharedParameter[];
          };
          if (data.success && data.parameters) {
            param = data.parameters.find((p) => p.id === parameterId) ?? null;
          }
        } else if (versionPathId) {
          const result = await getSharedPathParameters(versionPathId);
          const data = JSON.parse(result) as {
            success?: boolean;
            parameters?: LoadedSharedParameter[];
          };
          if (data.success && data.parameters) {
            param = data.parameters.find((p) => p.id === parameterId) ?? null;
          }
        }

        if (param) {
          setName(param.name);
          setInLocation(param.in_location);
          setSummary(param.summary || '');
          setDescription(param.description || '');

          // Load schema from param.data column (JSONB may be object or string)
          const schema = typeof param.data === 'string' ? JSON.parse(param.data) : param.data;
          if (schema && typeof schema === 'object') {
            if (schema.schemaMode === 'inline' && schema.inlineSchema && typeof schema.inlineSchema === 'object') {
              setSchemaMode('inline');
              setInlineSchemaText(JSON.stringify(schema.inlineSchema, null, 2));
            } else {
              setSchemaMode('form');
              setInlineSchemaText('{\n  "type": "string"\n}');
            }
            const pr = schema.propertyRef;
            if (pr && typeof pr === 'object' && pr.propertyId && pr.classId) {
              setPropertyRef({
                classId: String(pr.classId),
                className: String(pr.className || ''),
                propertyId: String(pr.propertyId),
                propertyName: String(pr.propertyName || ''),
              });
            } else {
              setPropertyRef(null);
            }
            const isInlineSchema =
              schema.schemaMode === 'inline' && schema.inlineSchema && typeof schema.inlineSchema === 'object';
            if (!isInlineSchema) {
              const t = String(schema.type || 'string');
              const allowed = ['string', 'integer', 'number', 'boolean', 'array'] as const;
              setSchemaType(
                (allowed as readonly string[]).includes(t)
                  ? (t as (typeof allowed)[number])
                  : 'string'
              );
              setSchemaFormat(schema.format || '');
              setSchemaMinimum(schema.minimum !== undefined ? String(schema.minimum) : '');
              setSchemaMaximum(schema.maximum !== undefined ? String(schema.maximum) : '');
              setSchemaMinLength(schema.minLength !== undefined ? String(schema.minLength) : '');
              setSchemaMaxLength(schema.maxLength !== undefined ? String(schema.maxLength) : '');
              setSchemaPattern(schema.pattern || '');
              setSchemaDefault(schema.default !== undefined ? String(schema.default) : '');
              setSchemaEnum(schema.enum ? schema.enum.join(', ') : '');
              setSchemaArrayItemType(schema.items?.type || 'string');
            }
            // Read required from data field
            setRequired(schema.required ?? (param.in_location === 'path'));
            setParamStyle(normalizeStyleForLocation(param.in_location, schema.style as string | undefined));
            setParamExplode(schema.explode === true);
            setParamAllowReserved(schema.allowReserved === true);
          } else {
            // Reset to defaults if no schema
            setSchemaMode('form');
            setInlineSchemaText('{\n  "type": "string"\n}');
            setPropertyRef(null);
            setSchemaType('string');
            setSchemaFormat('');
            setSchemaMinimum('');
            setSchemaMaximum('');
            setSchemaMinLength('');
            setSchemaMaxLength('');
            setSchemaPattern('');
            setSchemaDefault('');
            setSchemaEnum('');
            setSchemaArrayItemType('string');
            setSchemaDefault('');
            setParamStyle(defaultStyleForIn(param.in_location));
            setParamExplode(false);
            setParamAllowReserved(false);
            setRequired(param.in_location === 'path');
          }
        }
      } catch (error) {
        console.error('Error loading parameter:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadParameter();
  }, [parameterId, operationId, versionPathId]);

  // Extract available path parameters from pathname
  useEffect(() => {
    if (pathname) {
      const params = extractPathParameters(pathname);
      setAvailablePathParams(params);
    }
  }, [pathname]);

  // Designer class properties (same catalog as Schema Builder) for schema binding
  useEffect(() => {
    if (!selectedVersionId) {
      setDesignerProps([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const raw = await getClassesWithPropertiesAndTags(selectedVersionId);
        const classes: Array<{
          id: string;
          name: string;
          properties?: Array<{
            id: string;
            name: string;
            parent_id?: string | null;
            data?: Record<string, unknown> | string;
          }>;
        }> = JSON.parse(raw as string);
        const opts: DesignerPropOption[] = [];
        for (const cls of classes || []) {
          for (const p of cls.properties || []) {
            if (p.parent_id) continue;
            const pdata = typeof p.data === 'string' ? JSON.parse(p.data) : p.data || {};
            opts.push({
              key: `${cls.id}:${p.id}`,
              classId: cls.id,
              className: cls.name,
              propertyId: p.id,
              propertyName: p.name,
              data: pdata,
            });
          }
        }
        opts.sort((a, b) => a.propertyName.localeCompare(b.propertyName));
        if (!cancelled) setDesignerProps(opts);
      } catch {
        if (!cancelled) setDesignerProps([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedVersionId]);

  const filteredDesignerProps = useMemo(() => {
    const q = designerPropSearch.trim().toLowerCase();
    if (!q) return designerProps;
    return designerProps.filter(
      (o) =>
        o.propertyName.toLowerCase().includes(q) ||
        o.className.toLowerCase().includes(q)
    );
  }, [designerProps, designerPropSearch]);

  // Fetch primitives when primitive dialog opens (from REST service)
  useEffect(() => {
    if (!primitiveDialogOpen) return;
    const category = schemaType; // string | integer | number | boolean | array
    setPrimitiveLoading(true);
    setPrimitiveError(null);
    setSelectedPrimitive(null);
    setPrimitiveSearch('');
    fetch(`/api/primitives?category=${encodeURIComponent(category)}`)
      .then((res) => res.ok ? res.json() : Promise.reject(new Error('Failed to fetch primitives')))
      .then((data: { success?: boolean; primitives?: PrimitiveTemplate[]; error?: string }) => {
        if (data.success && Array.isArray(data.primitives)) {
          setPrimitives(data.primitives);
        } else {
          setPrimitiveError(data.error || 'Failed to load primitives');
          setPrimitives([]);
        }
      })
      .catch((err) => {
        setPrimitiveError(err instanceof Error ? err.message : 'Failed to load primitives');
        setPrimitives([]);
      })
      .finally(() => setPrimitiveLoading(false));
  }, [primitiveDialogOpen, schemaType]);

  // Filter primitives by search and visibility
  const filteredPrimitives = useMemo(() => {
    let list = primitives;
    if (!showSystemPrimitives) list = list.filter((p) => !p.is_system);
    if (!showTenantPrimitives) list = list.filter((p) => p.is_system);
    if (primitiveSearch.trim()) {
      const q = primitiveSearch.toLowerCase();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.description || '').toLowerCase().includes(q) ||
          p.tags.some((t) => t.toLowerCase().includes(q))
      );
    }
    return list.sort((a, b) => (a.is_system === b.is_system ? 0 : a.is_system ? 1 : -1));
  }, [primitives, primitiveSearch, showSystemPrimitives, showTenantPrimitives]);

  const applyDesignerProperty = (opt: DesignerPropOption) => {
    const mapped = propertyDataToParameterSchema(opt.data);
    const t = (mapped.type as string) || 'string';
    if (['string', 'integer', 'number', 'boolean', 'array'].includes(t)) {
      setSchemaType(t as 'string' | 'integer' | 'number' | 'boolean' | 'array');
    }
    if (mapped.format !== undefined) setSchemaFormat(String(mapped.format));
    setSchemaMinimum(mapped.minimum !== undefined ? String(mapped.minimum) : '');
    setSchemaMaximum(mapped.maximum !== undefined ? String(mapped.maximum) : '');
    setSchemaMinLength(mapped.minLength !== undefined ? String(mapped.minLength) : '');
    setSchemaMaxLength(mapped.maxLength !== undefined ? String(mapped.maxLength) : '');
    setSchemaPattern(mapped.pattern !== undefined ? String(mapped.pattern) : '');
    setSchemaEnum(mapped.enum && Array.isArray(mapped.enum) ? (mapped.enum as unknown[]).map(String).join(', ') : '');
    if (mapped.items && typeof mapped.items === 'object' && mapped.items !== null && 'type' in mapped.items) {
      setSchemaArrayItemType((mapped.items as { type: string }).type as 'string' | 'integer' | 'number' | 'boolean');
    }
    setSchemaMode('form');
    setPropertyRef({
      classId: opt.classId,
      className: opt.className,
      propertyId: opt.propertyId,
      propertyName: opt.propertyName,
    });
    setDesignerPropSearch('');
  };

  // Apply primitive schema to parameter form (type, format, pattern, constraints)
  const applyPrimitiveToParameter = (primitive: PrimitiveTemplate) => {
    const schema = primitive.schema as Record<string, unknown>;
    const type = schema.type as string | undefined;
    const pathTypes = ['string', 'integer', 'number', 'boolean', 'array'];
    if (type && pathTypes.includes(type)) setSchemaType(type as 'string' | 'integer' | 'number' | 'boolean' | 'array');
    if (schema.format !== undefined) setSchemaFormat(String(schema.format));
    if (schema.pattern !== undefined) setSchemaPattern(String(schema.pattern));
    if (schema.minimum !== undefined) setSchemaMinimum(String(schema.minimum));
    if (schema.maximum !== undefined) setSchemaMaximum(String(schema.maximum));
    if (schema.minLength !== undefined) setSchemaMinLength(String(schema.minLength));
    if (schema.maxLength !== undefined) setSchemaMaxLength(String(schema.maxLength));
    if (schema.enum !== undefined && Array.isArray(schema.enum)) setSchemaEnum((schema.enum as unknown[]).map(String).join(', '));
    if (schema.default !== undefined) setSchemaDefault(String(schema.default));
    if (schema.items && typeof schema.items === 'object' && schema.items !== null && 'type' in schema.items) {
      setSchemaArrayItemType((schema.items as { type: string }).type as 'string' | 'integer' | 'number' | 'boolean');
    }
    if (primitive.description && !description) setDescription(primitive.description);
    setPropertyRef(null);
    setPrimitiveDialogOpen(false);
    setSelectedPrimitive(null);
  };

  const handleSave = async () => {
    if (!parameterId || !name.trim() || !versionPathId) return;

    const nameValidationError = validateOpenApiParameterName(name, inLocation);
    if (nameValidationError) {
      await alertDialog({
        title: 'Invalid parameter name',
        message: nameValidationError,
        variant: 'warning',
      });
      return;
    }

    setIsSaving(true);
    setSaveStatus('idle');
    try {
      const allRaw = await getSharedPathParameters(versionPathId);
      const allParsed = JSON.parse(allRaw) as {
        success?: boolean;
        parameters?: Array<{ id: string; name: string; in_location: string }>;
      };
      if (allParsed.success && allParsed.parameters) {
        const simulated = allParsed.parameters.map((p) =>
          p.id === parameterId
            ? { name: name.trim(), in_location: inLocation }
            : { name: p.name, in_location: p.in_location }
        );
        const cov = getPathParameterCoverageError(pathname, simulated);
        if (cov) {
          await alertDialog({
            title: 'Path template mismatch',
            message: cov,
            variant: 'warning',
          });
          return;
        }
      }

      let schemaData: Record<string, unknown>;

      if (schemaMode === 'inline') {
        let parsedInline: unknown;
        try {
          parsedInline = JSON.parse(inlineSchemaText);
        } catch {
          await alertDialog({
            title: 'Invalid JSON',
            message: 'Fix the inline JSON Schema object before saving.',
            variant: 'error',
          });
          return;
        }
        if (!parsedInline || typeof parsedInline !== 'object' || Array.isArray(parsedInline)) {
          await alertDialog({
            title: 'Invalid schema',
            message: 'Inline schema must be a JSON object (for example {"type":"string"}).',
            variant: 'error',
          });
          return;
        }
        schemaData = {
          schemaMode: 'inline',
          inlineSchema: parsedInline as Record<string, unknown>,
          required: inLocation === 'path' ? true : required,
          style: paramStyle,
          explode: paramExplode,
        };
        if (inLocation === 'query' && paramAllowReserved) {
          schemaData.allowReserved = true;
        }
        if (propertyRef) {
          schemaData.propertyRef = propertyRef;
        }
      } else {
        schemaData = { type: schemaType };

        if (schemaType === 'string') {
          if (schemaFormat) schemaData.format = schemaFormat;
          if (schemaMinLength) schemaData.minLength = parseInt(schemaMinLength, 10);
          if (schemaMaxLength) schemaData.maxLength = parseInt(schemaMaxLength, 10);
          if (schemaPattern) schemaData.pattern = schemaPattern;
        } else if (schemaType === 'integer' || schemaType === 'number') {
          if (schemaMinimum) schemaData.minimum = schemaType === 'integer' ? parseInt(schemaMinimum, 10) : parseFloat(schemaMinimum);
          if (schemaMaximum) schemaData.maximum = schemaType === 'integer' ? parseInt(schemaMaximum, 10) : parseFloat(schemaMaximum);
        } else if (schemaType === 'array') {
          schemaData.items = { type: schemaArrayItemType };
        }

        if (schemaEnum.trim()) {
          schemaData.enum = schemaEnum.split(',').map((v) => v.trim()).filter(Boolean);
        }

        if (schemaDefault.trim()) {
          if (schemaType === 'integer') {
            schemaData.default = parseInt(schemaDefault, 10);
          } else if (schemaType === 'number') {
            schemaData.default = parseFloat(schemaDefault);
          } else if (schemaType === 'boolean') {
            schemaData.default = schemaDefault.toLowerCase() === 'true';
          } else {
            schemaData.default = schemaDefault;
          }
        }

        schemaData.required = inLocation === 'path' ? true : required;
        schemaData.style = paramStyle;
        schemaData.explode = paramExplode;
        if (inLocation === 'query' && paramAllowReserved) {
          schemaData.allowReserved = true;
        }
        if (propertyRef) {
          schemaData.propertyRef = propertyRef;
        }
      }

      const result = await updateSharedPathParameter(parameterId, {
        name: name.trim(),
        inLocation,
        summary: summary.trim() || undefined,
        description: description.trim() || undefined,
        data: schemaData,
      });

      const parsed = JSON.parse(result);
      if (parsed.success) {

        // Show "Saved" in button briefly
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
        // Refresh the canvas
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to update parameter',
          variant: 'error',
        });
      }
    } catch (error: unknown) {
      console.error('Error saving parameter:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to update parameter. Please try again.',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!parameterId || !operationId) return;

    const confirmed = await confirmDialog({
      title: 'Unlink Parameter',
      message: `Are you sure you want to unlink the parameter "${name}" from this operation? The parameter will still be available for other operations.`,
      variant: 'danger',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkParameterFromOperation(operationId, parameterId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Close the panel and refresh the canvas
        onClose();
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
      await alertDialog({
        title: 'Error',
        message: 'Failed to unlink parameter. Please try again.',
        variant: 'error',
      });
    }
  };

  if (!parameterId) return null;

  const parameterFooter = !isLoading ? (
    <div className="flex flex-col gap-2">
      <Button
        type="button"
        variant={saveStatus === 'saved' ? 'success' : 'default'}
        onClick={handleSave}
        disabled={isSaving || !name.trim()}
        className="w-full"
      >
        <Save className="w-4 h-4" />
        {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : 'Save Changes'}
      </Button>
      {operationId && (
        <Button
          type="button"
          variant="outline"
          onClick={handleDelete}
          className="w-full text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-950/40 border-rose-200 dark:border-rose-900/60"
        >
          Unlink Parameter
        </Button>
      )}
    </div>
  ) : undefined;

  return (
    <>
    <PropertiesPanelShell
      icon={<Hash />}
      title="Parameter Details"
      subtitle={name ? <span className="font-mono">{name}</span> : null}
      onClose={onClose}
      bodyScroll={false}
      footer={parameterFooter}
    >
      {/* Content */}
      {isLoading ? (
        <div className="p-6 flex justify-center">
          <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-auto p-4">
            <div className="flex flex-col gap-2.5">
              <PropertiesPanelSection title="Identity" defaultOpen>
                <div className="flex flex-col gap-3">
              {/* Parameter Name */}
              <div>
                <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Parameter Name
                </Label>
                {inLocation === 'path' && availablePathParams.length > 0 ? (
                  <Select value={name} onValueChange={setName}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Parameter name" />
                    </SelectTrigger>
                    <SelectContent>
                      {availablePathParams.map((param) => (
                        <SelectItem key={param} value={param}>
                          {param}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <>
                    <Input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Parameter name"
                      className="h-9 text-sm"
                      list="param-name-suggestions"
                      autoComplete="off"
                    />
                    <datalist id="param-name-suggestions">
                      {COMMON_PARAM_NAMES.map((p) => (
                        <option key={p} value={p} />
                      ))}
                    </datalist>
                  </>
                )}
                {inLocation === 'cookie' && (
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                    Cookie names in browsers follow RFC 6265; this field validates names for OpenAPI export only.
                  </p>
                )}
              </div>

              {/* Location */}
              <div>
                <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Location
                </Label>
                <Select
                  value={inLocation}
                  onValueChange={(v) => {
                    const loc = v as typeof inLocation;
                    setInLocation(loc);
                    if (loc === 'path') setRequired(true);
                    setParamStyle((prev) => normalizeStyleForLocation(loc, prev));
                    if (loc !== 'query') setParamAllowReserved(false);
                  }}
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="path">Path</SelectItem>
                    <SelectItem value="query">Query</SelectItem>
                    <SelectItem value="header">Header</SelectItem>
                    <SelectItem value="cookie">Cookie</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Required — path params are always required in OpenAPI; query/header/cookie can be optional */}
              <div className="flex flex-col gap-1.5">
                {inLocation === 'path' ? (
                  <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                    <Checkbox id="param-required" checked={true} disabled />
                    <Label htmlFor="param-required" className="cursor-default">
                      Required (path parameters are always required in OpenAPI)
                    </Label>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="param-required"
                      checked={required}
                      onCheckedChange={(checked) => setRequired(checked === true)}
                    />
                    <Label htmlFor="param-required" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                      Required parameter
                    </Label>
                  </div>
                )}
              </div>

                </div>
              </PropertiesPanelSection>

              <PropertiesPanelSection title="Serialization" defaultOpen={false}>
                <div className="flex flex-col gap-3">
              {/* Serialization style — OpenAPI Parameter Object; allowed values depend on `in` */}
              <div>
                <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Serialization style
                </Label>
                <Select
                  value={paramStyle}
                  onValueChange={(v) => setParamStyle(v as ParamSerializationStyle)}
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue placeholder="style" />
                  </SelectTrigger>
                  <SelectContent>
                    {PARAM_STYLE_OPTIONS[inLocation].map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                  {inLocation === 'query' && 'Query parameters: form, spaceDelimited, pipeDelimited, or deepObject.'}
                  {inLocation === 'path' && 'Path parameters: simple, label, or matrix.'}
                  {inLocation === 'header' && 'Header parameters use style simple.'}
                  {inLocation === 'cookie' && 'Cookie parameters use style form.'}
                </p>
              </div>

              {/* Explode — for arrays/objects (OpenAPI 3.0) */}
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="param-explode"
                    checked={paramExplode}
                    onCheckedChange={(checked) => setParamExplode(checked === true)}
                  />
                  <Label htmlFor="param-explode" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    Explode (arrays/objects)
                  </Label>
                </div>
                <p className="text-[11px] text-gray-500 dark:text-gray-400">
                  When true, array/object values are expanded (e.g. id=1&amp;id=2 for form style).
                </p>
              </div>

              {inLocation === 'query' && (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="param-allow-reserved"
                      checked={paramAllowReserved}
                      onCheckedChange={(checked) => setParamAllowReserved(checked === true)}
                    />
                    <Label htmlFor="param-allow-reserved" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                      allowReserved (query only)
                    </Label>
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400">
                    When true, reserved URI characters in query values are not encoded (OpenAPI 3.x).
                  </p>
                </div>
              )}

                </div>
              </PropertiesPanelSection>

              <PropertiesPanelSection title="Documentation" defaultOpen>
                <div className="flex flex-col gap-3">
              {/* Summary */}
              <div>
                <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Summary
                </Label>
                <Input
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="Brief summary"
                  className="h-9 text-sm"
                />
              </div>

              {/* Description */}
              <div>
                <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Description
                </Label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Detailed description of the parameter..."
                  rows={4}
                  className="text-sm resize-none"
                />
              </div>

                </div>
              </PropertiesPanelSection>

              <PropertiesPanelSection title="Schema" defaultOpen>
                <div>
                <div
                  className={`inline-flex items-center rounded-md border p-0.5 mb-3 text-xs ${
                    isDark ? 'border-slate-700 bg-slate-900/60' : 'border-slate-200 bg-slate-50'
                  }`}
                  role="group"
                  aria-label="Schema editor mode"
                >
                  <button
                    type="button"
                    className={`px-2.5 py-1 rounded-sm font-medium transition-colors ${
                      schemaMode === 'form'
                        ? isDark
                          ? 'bg-slate-800 text-indigo-300 shadow-sm'
                          : 'bg-white text-indigo-600 shadow-sm'
                        : isDark
                          ? 'text-slate-400 hover:text-slate-200'
                          : 'text-slate-600 hover:text-slate-900'
                    }`}
                    onClick={() => setSchemaMode('form')}
                  >
                    Form
                  </button>
                  <button
                    type="button"
                    className={`px-2.5 py-1 rounded-sm font-medium transition-colors ${
                      schemaMode === 'inline'
                        ? isDark
                          ? 'bg-slate-800 text-indigo-300 shadow-sm'
                          : 'bg-white text-indigo-600 shadow-sm'
                        : isDark
                          ? 'text-slate-400 hover:text-slate-200'
                          : 'text-slate-600 hover:text-slate-900'
                    }`}
                    onClick={() => {
                      setSchemaMode('inline');
                      setPropertyRef(null);
                    }}
                  >
                    JSON Schema
                  </button>
                </div>

                {propertyRef && schemaMode === 'form' && (
                  <p className="text-[11px] text-slate-600 dark:text-slate-400 mb-2">
                    Designer link:{' '}
                    <span className="font-mono">
                      {propertyRef.className}.{propertyRef.propertyName}
                    </span>
                  </p>
                )}

                {schemaMode === 'form' && selectedVersionId && designerProps.length > 0 && (
                  <div className="mb-3">
                    <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                      Apply from Designer property
                    </Label>
                    <div className="relative">
                      <Search
                        size={14}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400 pointer-events-none"
                      />
                      <Input
                        value={designerPropSearch}
                        onChange={(e) => setDesignerPropSearch(e.target.value)}
                        placeholder="Search class properties…"
                        className="h-9 text-sm pl-8"
                        autoComplete="off"
                      />
                    </div>
                    <div
                      className={`mt-1 max-h-28 overflow-y-auto rounded border text-xs ${
                        isDark ? 'border-slate-600 bg-slate-900/50' : 'border-slate-200 bg-slate-50'
                      }`}
                    >
                      {filteredDesignerProps.length === 0 ? (
                        <p className="p-2 text-gray-500 dark:text-gray-400">No matching properties</p>
                      ) : (
                        filteredDesignerProps.slice(0, 40).map((opt) => (
                          <button
                            key={opt.key}
                            type="button"
                            onClick={() => applyDesignerProperty(opt)}
                            className={`w-full text-left px-2 py-1.5 border-b last:border-b-0 transition-colors ${
                              isDark
                                ? 'border-slate-700 hover:bg-slate-800 text-slate-200'
                                : 'border-slate-100 hover:bg-white text-slate-800'
                            }`}
                          >
                            <span className="font-medium">{opt.propertyName}</span>
                            <span className="text-gray-500 dark:text-gray-400"> · {opt.className}</span>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                )}

                {schemaMode === 'form' && (
                <div className="mb-4">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setPrimitiveDialogOpen(true)}
                    className="text-xs border-violet-500 text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20"
                  >
                    <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                    Apply from primitive template
                  </Button>
                  <span
                    className="text-[10px] text-gray-500 dark:text-gray-400 ml-1.5 align-middle cursor-help"
                    title="Apply format, pattern, and constraints from a primitive defined in the REST service"
                  >
                    ⓘ
                  </span>
                </div>
                )}

                {schemaMode === 'form' && (
                <>
                {/* Schema Type */}
                <div className="mb-4">
                  <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                    Type
                  </Label>
                  <Select value={schemaType} onValueChange={(v) => setSchemaType(v as typeof schemaType)}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SCHEMA_TYPES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* String-specific options */}
                {schemaType === 'string' && (
                  <>
                    <div className="mb-4">
                      <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                        Format
                      </Label>
                      <Select
                        value={schemaFormat === '' ? FORMAT_NONE_VALUE : schemaFormat}
                        onValueChange={(v) => setSchemaFormat(v === FORMAT_NONE_VALUE ? '' : v)}
                      >
                        <SelectTrigger className="h-9 text-sm">
                          <SelectValue placeholder="None" />
                        </SelectTrigger>
                        <SelectContent>
                          {STRING_FORMATS.map((f) => (
                            <SelectItem key={f.value || FORMAT_NONE_VALUE} value={f.value === '' ? FORMAT_NONE_VALUE : f.value}>
                              {f.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex gap-2 mb-4">
                      <div className="flex-1">
                        <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                          Min Length
                        </Label>
                        <Input
                          type="number"
                          value={schemaMinLength}
                          onChange={(e) => setSchemaMinLength(e.target.value)}
                          placeholder="0"
                          className="h-9 text-sm"
                        />
                      </div>
                      <div className="flex-1">
                        <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                          Max Length
                        </Label>
                        <Input
                          type="number"
                          value={schemaMaxLength}
                          onChange={(e) => setSchemaMaxLength(e.target.value)}
                          placeholder="∞"
                          className="h-9 text-sm"
                        />
                      </div>
                    </div>

                    <div className="mb-4">
                      <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                        Pattern (Regex)
                      </Label>
                      <Input
                        value={schemaPattern}
                        onChange={(e) => setSchemaPattern(e.target.value)}
                        placeholder="e.g., ^[a-z]+$"
                        className="h-9 text-sm font-mono"
                      />
                    </div>
                  </>
                )}

                {/* Number/Integer-specific options */}
                {(schemaType === 'integer' || schemaType === 'number') && (
                  <div className="flex gap-2 mb-4">
                    <div className="flex-1">
                      <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                        Minimum
                      </Label>
                      <Input
                        type="number"
                        value={schemaMinimum}
                        onChange={(e) => setSchemaMinimum(e.target.value)}
                        placeholder="-∞"
                        className="h-9 text-sm"
                      />
                    </div>
                    <div className="flex-1">
                      <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                        Maximum
                      </Label>
                      <Input
                        type="number"
                        value={schemaMaximum}
                        onChange={(e) => setSchemaMaximum(e.target.value)}
                        placeholder="∞"
                        className="h-9 text-sm"
                      />
                    </div>
                  </div>
                )}

                {/* Array-specific options */}
                {schemaType === 'array' && (
                  <div className="mb-4">
                    <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                      Array Item Type
                    </Label>
                    <Select value={schemaArrayItemType} onValueChange={(v) => setSchemaArrayItemType(v as typeof schemaArrayItemType)}>
                      <SelectTrigger className="h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ARRAY_ITEM_TYPES.map((t) => (
                          <SelectItem key={t.value} value={t.value}>
                            {t.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {/* Enum values (for string, integer, number) */}
                {(schemaType === 'string' || schemaType === 'integer' || schemaType === 'number') && (
                  <div className="mb-4">
                    <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                      Allowed Values (comma-separated)
                    </Label>
                    <Input
                      value={schemaEnum}
                      onChange={(e) => setSchemaEnum(e.target.value)}
                      placeholder="e.g., active, pending, completed"
                      className="h-9 text-sm"
                    />
                  </div>
                )}

                {/* Default value — optional; used when the client omits this parameter */}
                <div>
                  <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                    Default Value
                  </Label>
                  <Input
                    value={schemaDefault}
                    onChange={(e) => setSchemaDefault(e.target.value)}
                    placeholder={
                      schemaType === 'boolean' ? 'true or false' :
                      schemaType === 'integer' ? 'e.g., 0' :
                      schemaType === 'number' ? 'e.g., 0.0' :
                      'e.g., default value'
                    }
                    className="h-9 text-sm"
                    title="Optional. Used when the client omits this parameter (query, header, cookie)."
                  />
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                    Optional. Used when the client omits this parameter.
                  </p>
                </div>
                </>
                )}

                {schemaMode === 'inline' && (
                  <div>
                    <Label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                      Parameter schema (JSON)
                    </Label>
                    <Textarea
                      value={inlineSchemaText}
                      onChange={(e) => setInlineSchemaText(e.target.value)}
                      rows={12}
                      spellCheck={false}
                      className="text-xs font-mono resize-y min-h-[140px]"
                    />
                    <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
                      OpenAPI Schema Object subset (e.g. type, format, enum). Required, style, and explode are saved separately.
                    </p>
                  </div>
                )}
                </div>
              </PropertiesPanelSection>
            </div>
          </div>

        </>
      )}
    </PropertiesPanelShell>

      {/* Primitive template selection dialog (REST service primitives) */}
      <Dialog.Root
        open={primitiveDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            setPrimitiveDialogOpen(false);
            setSelectedPrimitive(null);
            setPrimitiveSearch('');
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className={`fixed left-1/2 top-1/2 z-[9999] w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg shadow-xl ${
              isDark ? 'bg-slate-900 border border-slate-700' : 'bg-white border border-slate-200'
            }`}
          >
            <Dialog.Title className="flex items-center gap-2 text-base font-semibold text-gray-900 dark:text-white p-4 pb-0">
              <Sparkles size={18} className="text-violet-500" />
              Apply from primitive template
            </Dialog.Title>
            <div className="p-4 space-y-4">
              <p className="text-xs text-gray-600 dark:text-gray-400">
                Select a primitive from the REST service to apply its format, pattern, and constraints to this parameter.
              </p>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400" />
                <Input
                  placeholder="Search primitives by name, description, or tags..."
                  value={primitiveSearch}
                  onChange={(e) => setPrimitiveSearch(e.target.value)}
                  className="pl-9 h-9 text-sm"
                />
              </div>
              <div className="flex items-center gap-4 flex-wrap">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <Checkbox
                    checked={showSystemPrimitives}
                    onCheckedChange={(c) => setShowSystemPrimitives(c === true)}
                  />
                  <span className="text-xs flex items-center gap-1"><Shield size={12} /> System</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <Checkbox
                    checked={showTenantPrimitives}
                    onCheckedChange={(c) => setShowTenantPrimitives(c === true)}
                  />
                  <span className="text-xs flex items-center gap-1"><User size={12} /> Tenant</span>
                </label>
                <span className="text-[10px] text-gray-500 dark:text-gray-400 ml-auto">
                  {filteredPrimitives.length} primitive{filteredPrimitives.length !== 1 ? 's' : ''}
                </span>
              </div>
              <div className={`max-h-80 overflow-y-auto rounded border ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
                {primitiveLoading ? (
                  <div className="py-8 flex justify-center items-center">
                    <Loader2 size={24} className="animate-spin text-indigo-500" />
                  </div>
                ) : primitiveError ? (
                  <div className="p-4 text-center">
                    <p className="text-sm text-red-500 dark:text-red-400 mb-2">{primitiveError}</p>
                    <Button type="button" variant="outline" size="sm" onClick={() => setPrimitiveDialogOpen(false)}>
                      Close
                    </Button>
                  </div>
                ) : filteredPrimitives.length === 0 ? (
                  <div className="p-6 text-center">
                    <Database size={32} className={`mx-auto mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`} />
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      {primitiveSearch ? 'No primitives match your search' : `No ${schemaType} primitives available`}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {primitiveSearch ? 'Try a different search term' : 'Create primitives in the Primitives Management section'}
                    </p>
                  </div>
                ) : (
                  filteredPrimitives.map((primitive) => (
                    <button
                      key={primitive.id}
                      type="button"
                      onClick={() => setSelectedPrimitive(primitive)}
                      className={`w-full text-left px-3 py-2.5 transition-colors border-b last:border-b-0 ${
                        selectedPrimitive?.id === primitive.id
                          ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-800'
                          : 'hover:bg-gray-50 dark:hover:bg-gray-800/50 border-gray-100 dark:border-gray-800'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-0.5">
                        {primitive.is_system ? <Shield size={12} className="text-emerald-500" /> : <User size={12} className="text-violet-500" />}
                        <span className="font-medium text-sm text-gray-900 dark:text-gray-100">{primitive.name}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                          {primitive.category}
                        </span>
                        {primitive.usage_count > 0 && (
                          <span className="text-[10px] text-gray-500 ml-auto">Used {primitive.usage_count}×</span>
                        )}
                      </div>
                      {primitive.description && (
                        <p className="text-xs text-gray-600 dark:text-gray-400 truncate">{primitive.description}</p>
                      )}
                      <p className="text-[10px] text-gray-500 dark:text-gray-500 font-mono truncate mt-0.5">
                        {[
                          primitive.schema.format && `format: ${primitive.schema.format}`,
                          primitive.schema.pattern && 'pattern',
                          primitive.schema.minimum !== undefined && `min: ${primitive.schema.minimum}`,
                          primitive.schema.maximum !== undefined && `max: ${primitive.schema.maximum}`,
                          primitive.schema.enum && Array.isArray(primitive.schema.enum) && `enum(${primitive.schema.enum.length})`,
                        ].filter(Boolean).join(', ') || 'No constraints'}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </div>
            <div className={`flex justify-end gap-2 px-4 py-3 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setPrimitiveDialogOpen(false);
                  setSelectedPrimitive(null);
                  setPrimitiveSearch('');
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="default"
                size="sm"
                disabled={!selectedPrimitive}
                onClick={() => selectedPrimitive && applyPrimitiveToParameter(selectedPrimitive)}
              >
                Apply primitive
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}


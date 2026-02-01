'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import { Close, Save } from '@mui/icons-material';
import { Hash, Sparkles, Search, Shield, User, Loader2, Database } from 'lucide-react';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getLinkedParametersForOperation,
  getSharedPathParameters,
  updateSharedPathParameter,
  unlinkParameterFromOperation,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import { extractPathParameters } from '../../../../../../lib/utils/path-params';

// Simple types allowed for path parameters (no 'object')
const SCHEMA_TYPES = [
  { value: 'string', label: 'String' },
  { value: 'integer', label: 'Integer' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'array', label: 'Array' },
] as const;

// Common string formats
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
      return;
    }

    const loadParameter = async () => {
      setIsLoading(true);
      try {
        let param: any = null;

        if (operationId) {
          const result = await getLinkedParametersForOperation(operationId);
          const data = JSON.parse(result);
          if (data.success && data.parameters) {
            param = data.parameters.find((p: any) => p.id === parameterId);
          }
        } else if (versionPathId) {
          const result = await getSharedPathParameters(versionPathId);
          const data = JSON.parse(result);
          if (data.success && data.parameters) {
            param = data.parameters.find((p: any) => p.id === parameterId);
          }
        }

        if (param) {
          setName(param.name);
          setInLocation(param.in_location);
          setSummary(param.summary || '');
          setDescription(param.description || '');

          // Load schema from param.data column
          const schema = param.data;
          if (schema) {
            setSchemaType(schema.type || 'string');
            setSchemaFormat(schema.format || '');
            setSchemaMinimum(schema.minimum !== undefined ? String(schema.minimum) : '');
            setSchemaMaximum(schema.maximum !== undefined ? String(schema.maximum) : '');
            setSchemaMinLength(schema.minLength !== undefined ? String(schema.minLength) : '');
            setSchemaMaxLength(schema.maxLength !== undefined ? String(schema.maxLength) : '');
            setSchemaPattern(schema.pattern || '');
            setSchemaDefault(schema.default !== undefined ? String(schema.default) : '');
            setSchemaEnum(schema.enum ? schema.enum.join(', ') : '');
            setSchemaArrayItemType(schema.items?.type || 'string');
            // Read required from data field
            setRequired(schema.required ?? (param.in_location === 'path'));
          } else {
            // Reset to defaults if no schema
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
    setPrimitiveDialogOpen(false);
    setSelectedPrimitive(null);
  };

  const handleSave = async () => {
    if (!parameterId || !name.trim()) return;

    setIsSaving(true);
    setSaveStatus('idle');
    try {
      // Build the JSON Schema for the parameter
      const schemaData: Record<string, any> = { type: schemaType };

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

      // Handle enum values (comma-separated)
      if (schemaEnum.trim()) {
        schemaData.enum = schemaEnum.split(',').map(v => v.trim()).filter(v => v);
      }

      // Handle default value
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

      // Add required to schema data
      schemaData.required = required;

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
    } catch (error: any) {
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
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Hash size={20} color={isDark ? '#a78bfa' : '#8b5cf6'} />
          <Box>
            <span className="text-sm font-semibold text-gray-900 dark:text-white">
              Parameter Details
            </span>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {name}
            </div>
          </Box>
        </Box>
        <IconButton size="small" onClick={onClose} sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
          <Close sx={{ fontSize: 18 }} />
        </IconButton>
      </Box>

      {/* Content */}
      {isLoading ? (
        <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
          <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
        </Box>
      ) : (
        <>
          <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* Parameter Name */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Parameter Name
                </label>
                {inLocation === 'path' && availablePathParams.length > 0 ? (
                  <TextField
                    fullWidth
                    select
                    size="small"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
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
                    {availablePathParams.map((param) => (
                      <MenuItem key={param} value={param}>
                        {param}
                      </MenuItem>
                    ))}
                  </TextField>
                ) : (
                  <TextField
                    fullWidth
                    size="small"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Parameter name"
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

              {/* Location */}
              <Box>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Location
                </label>
                <TextField
                  fullWidth
                  select
                  size="small"
                  value={inLocation}
                  onChange={(e) => setInLocation(e.target.value as any)}
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
                  <MenuItem value="path">Path</MenuItem>
                  <MenuItem value="query">Query</MenuItem>
                  <MenuItem value="header">Header</MenuItem>
                  <MenuItem value="cookie">Cookie</MenuItem>
                </TextField>
              </Box>

              {/* Required */}
              <Box>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={required}
                      onChange={(e) => setRequired(e.target.checked)}
                      sx={{
                        color: isDark ? '#64748b' : '#94a3b8',
                        '&.Mui-checked': {
                          color: '#8b5cf6',
                        },
                      }}
                    />
                  }
                  label={
                    <span className="text-sm text-gray-700 dark:text-gray-300">
                      Required parameter
                    </span>
                  }
                />
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
                  placeholder="Brief summary"
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
                  placeholder="Detailed description of the parameter..."
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

              {/* Schema Section */}
              <Box sx={{ mt: 2, pt: 2, borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0' }}>
                <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                  Schema Definition
                </label>

                {/* Apply from primitive template (REST service primitives) */}
                <Box sx={{ mb: 2 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<Sparkles style={{ width: 14, height: 14 }} />}
                    onClick={() => setPrimitiveDialogOpen(true)}
                    sx={{
                      borderColor: isDark ? '#6366f1' : '#8b5cf6',
                      color: isDark ? '#a5b4fc' : '#7c3aed',
                      fontSize: '0.75rem',
                      '&:hover': {
                        borderColor: isDark ? '#818cf8' : '#7c3aed',
                        backgroundColor: isDark ? 'rgba(99, 102, 241, 0.1)' : 'rgba(139, 92, 246, 0.08)',
                      },
                    }}
                  >
                    Apply from primitive template
                  </Button>
                  <span
                    className="text-[10px] text-gray-500 dark:text-gray-400 ml-1.5 align-middle cursor-help"
                    title="Apply format, pattern, and constraints from a primitive defined in the REST service"
                  >
                    ⓘ
                  </span>
                </Box>

                {/* Schema Type */}
                <Box sx={{ mb: 2 }}>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Type
                  </label>
                  <TextField
                    fullWidth
                    select
                    size="small"
                    value={schemaType}
                    onChange={(e) => setSchemaType(e.target.value as any)}
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
                    {SCHEMA_TYPES.map((t) => (
                      <MenuItem key={t.value} value={t.value}>
                        {t.label}
                      </MenuItem>
                    ))}
                  </TextField>
                </Box>

                {/* String-specific options */}
                {schemaType === 'string' && (
                  <>
                    <Box sx={{ mb: 2 }}>
                      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Format
                      </label>
                      <TextField
                        fullWidth
                        select
                        size="small"
                        value={schemaFormat}
                        onChange={(e) => setSchemaFormat(e.target.value)}
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
                        {STRING_FORMATS.map((f) => (
                          <MenuItem key={f.value} value={f.value}>
                            {f.label}
                          </MenuItem>
                        ))}
                      </TextField>
                    </Box>

                    <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                      <Box sx={{ flex: 1 }}>
                        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                          Min Length
                        </label>
                        <TextField
                          fullWidth
                          size="small"
                          type="number"
                          value={schemaMinLength}
                          onChange={(e) => setSchemaMinLength(e.target.value)}
                          placeholder="0"
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
                      <Box sx={{ flex: 1 }}>
                        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                          Max Length
                        </label>
                        <TextField
                          fullWidth
                          size="small"
                          type="number"
                          value={schemaMaxLength}
                          onChange={(e) => setSchemaMaxLength(e.target.value)}
                          placeholder="∞"
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

                    <Box sx={{ mb: 2 }}>
                      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Pattern (Regex)
                      </label>
                      <TextField
                        fullWidth
                        size="small"
                        value={schemaPattern}
                        onChange={(e) => setSchemaPattern(e.target.value)}
                        placeholder="e.g., ^[a-z]+$"
                        sx={{
                          '& .MuiInputBase-root': {
                            fontSize: '0.875rem',
                            fontFamily: 'monospace',
                            backgroundColor: isDark ? '#0f172a' : '#ffffff',
                            color: isDark ? '#f1f5f9' : '#0f172a',
                          },
                          '& .MuiOutlinedInput-notchedOutline': {
                            borderColor: isDark ? '#334155' : '#e2e8f0',
                          },
                        }}
                      />
                    </Box>
                  </>
                )}

                {/* Number/Integer-specific options */}
                {(schemaType === 'integer' || schemaType === 'number') && (
                  <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                    <Box sx={{ flex: 1 }}>
                      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Minimum
                      </label>
                      <TextField
                        fullWidth
                        size="small"
                        type="number"
                        value={schemaMinimum}
                        onChange={(e) => setSchemaMinimum(e.target.value)}
                        placeholder="-∞"
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
                    <Box sx={{ flex: 1 }}>
                      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Maximum
                      </label>
                      <TextField
                        fullWidth
                        size="small"
                        type="number"
                        value={schemaMaximum}
                        onChange={(e) => setSchemaMaximum(e.target.value)}
                        placeholder="∞"
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
                )}

                {/* Array-specific options */}
                {schemaType === 'array' && (
                  <Box sx={{ mb: 2 }}>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Array Item Type
                    </label>
                    <TextField
                      fullWidth
                      select
                      size="small"
                      value={schemaArrayItemType}
                      onChange={(e) => setSchemaArrayItemType(e.target.value as any)}
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
                      {ARRAY_ITEM_TYPES.map((t) => (
                        <MenuItem key={t.value} value={t.value}>
                          {t.label}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Box>
                )}

                {/* Enum values (for string, integer, number) */}
                {(schemaType === 'string' || schemaType === 'integer' || schemaType === 'number') && (
                  <Box sx={{ mb: 2 }}>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Allowed Values (comma-separated)
                    </label>
                    <TextField
                      fullWidth
                      size="small"
                      value={schemaEnum}
                      onChange={(e) => setSchemaEnum(e.target.value)}
                      placeholder="e.g., active, pending, completed"
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
                )}

                {/* Default value */}
                <Box>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Default Value
                  </label>
                  <TextField
                    fullWidth
                    size="small"
                    value={schemaDefault}
                    onChange={(e) => setSchemaDefault(e.target.value)}
                    placeholder={
                      schemaType === 'boolean' ? 'true or false' :
                      schemaType === 'integer' ? 'e.g., 0' :
                      schemaType === 'number' ? 'e.g., 0.0' :
                      'e.g., default value'
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
                </Box>
              </Box>
            </Box>
          </Box>

          {/* Footer with Save and Delete buttons */}
          <Box
            sx={{
              p: 2,
              borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
            }}
          >
            <Button
              fullWidth
              variant="contained"
              onClick={handleSave}
              disabled={isSaving || !name.trim()}
              startIcon={<Save />}
              sx={{
                background: saveStatus === 'saved'
                  ? 'linear-gradient(135deg, #10b981 0%, #34d399 100%)'
                  : 'linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)',
                '&:hover': {
                  background: saveStatus === 'saved'
                    ? 'linear-gradient(135deg, #059669 0%, #10b981 100%)'
                    : 'linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)',
                },
                '&:disabled': {
                  background: isDark ? '#334155' : '#e2e8f0',
                  color: isDark ? '#64748b' : '#94a3b8',
                },
              }}
            >
              {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved ✓' : 'Save Changes'}
            </Button>
            {operationId && (
              <Button
                fullWidth
                variant="outlined"
                onClick={handleDelete}
                sx={{
                  borderColor: '#ef4444',
                  color: '#ef4444',
                  '&:hover': {
                    borderColor: '#dc2626',
                    backgroundColor: 'rgba(239, 68, 68, 0.04)',
                  },
                }}
              >
                Unlink Parameter
              </Button>
            )}
          </Box>
        </>
      )}

      {/* Primitive template selection dialog (REST service primitives) */}
      <Dialog
        open={primitiveDialogOpen}
        onClose={() => {
          setPrimitiveDialogOpen(false);
          setSelectedPrimitive(null);
          setPrimitiveSearch('');
        }}
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
            background: isDark ? 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)' : undefined,
            border: isDark ? '1px solid #334155' : undefined,
          },
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: '1rem' }}>
          <Sparkles size={18} style={{ color: '#8b5cf6' }} />
          Apply from primitive template
        </DialogTitle>
        <DialogContent dividers>
          <p className="text-xs text-gray-600 dark:text-gray-400 mb-3">
            Select a primitive from the REST service to apply its format, pattern, and constraints to this parameter.
          </p>
          <Box sx={{ mb: 2 }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Search primitives by name, description, or tags..."
              value={primitiveSearch}
              onChange={(e) => setPrimitiveSearch(e.target.value)}
              InputProps={{
                startAdornment: <Search size={14} style={{ marginRight: 8, color: isDark ? '#94a3b8' : '#64748b' }} />,
              }}
              sx={{
                '& .MuiInputBase-root': {
                  fontSize: '0.875rem',
                  backgroundColor: isDark ? '#0f172a' : '#f8fafc',
                  borderRadius: 1,
                },
              }}
            />
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, flexWrap: 'wrap' }}>
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={showSystemPrimitives}
                  onChange={(e) => setShowSystemPrimitives(e.target.checked)}
                  sx={{ color: isDark ? '#64748b' : '#94a3b8', '&.Mui-checked': { color: '#10b981' } }}
                />
              }
              label={<span className="text-xs flex items-center gap-1"><Shield size={12} /> System</span>}
            />
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={showTenantPrimitives}
                  onChange={(e) => setShowTenantPrimitives(e.target.checked)}
                  sx={{ color: isDark ? '#64748b' : '#94a3b8', '&.Mui-checked': { color: '#8b5cf6' } }}
                />
              }
              label={<span className="text-xs flex items-center gap-1"><User size={12} /> Tenant</span>}
            />
            <span className="text-[10px] text-gray-500 dark:text-gray-400 ml-auto">
              {filteredPrimitives.length} primitive{filteredPrimitives.length !== 1 ? 's' : ''}
            </span>
          </Box>
          <Box sx={{ maxHeight: 320, overflowY: 'auto', border: isDark ? '1px solid #334155' : '1px solid #e2e8f0', borderRadius: 1 }}>
            {primitiveLoading ? (
              <Box sx={{ py: 4, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                <Loader2 size={24} className="animate-spin text-indigo-500" />
              </Box>
            ) : primitiveError ? (
              <Box sx={{ p: 3, textAlign: 'center' }}>
                <p className="text-sm text-red-500 dark:text-red-400 mb-2">{primitiveError}</p>
                <Button size="small" variant="outlined" onClick={() => primitiveDialogOpen && setPrimitiveDialogOpen(false)}>
                  Close
                </Button>
              </Box>
            ) : filteredPrimitives.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center' }}>
                <Database size={32} style={{ color: isDark ? '#475569' : '#cbd5e1', marginBottom: 8 }} />
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {primitiveSearch ? 'No primitives match your search' : `No ${schemaType} primitives available`}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                  {primitiveSearch ? 'Try a different search term' : 'Create primitives in the Primitives Management section'}
                </p>
              </Box>
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
                    {primitive.is_system ? <Shield size={12} style={{ color: '#10b981' }} /> : <User size={12} style={{ color: '#8b5cf6' }} />}
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
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 2, py: 1.5, borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0' }}>
          <Button
            size="small"
            onClick={() => {
              setPrimitiveDialogOpen(false);
              setSelectedPrimitive(null);
              setPrimitiveSearch('');
            }}
          >
            Cancel
          </Button>
          <Button
            size="small"
            variant="contained"
            disabled={!selectedPrimitive}
            onClick={() => selectedPrimitive && applyPrimitiveToParameter(selectedPrimitive)}
            sx={{
              background: 'linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)',
              '&:hover': { background: 'linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)' },
            }}
          >
            Apply primitive
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}


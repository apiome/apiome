'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Checkbox } from '../../ui/Checkbox';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import { PropertyFormData } from './PropertyFormFields';
import {
  Search,
  X,
  Shield,
  User,
  Sparkles,
  Database,
  Loader2,
} from 'lucide-react';

export interface Primitive {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  category: string;
  schema: Record<string, unknown>;
  tags: string[];
  created_by: string | null;
  is_system: boolean;
  is_public: boolean;
  usage_count: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface PrimitiveSelectorProps {
  // Form data and update handler
  formData: PropertyFormData;
  onChange: (field: keyof PropertyFormData, value: any) => void;

  // Current property type (to filter primitives by category)
  propertyType: string;

  // Optional: callback when a primitive is applied
  onPrimitiveApplied?: (primitive: Primitive) => void;

  // Size variant
  size?: 'small' | 'medium';
}

// Category type mapping from property types to primitive categories
const propertyTypeToPrimitiveCategory: Record<string, string> = {
  'string': 'string',
  'number': 'number',
  'integer': 'integer',
  'boolean': 'boolean',
  'array': 'array',
  'object': 'object',
};

export const PrimitiveSelector: React.FC<PrimitiveSelectorProps> = ({
  formData,
  onChange,
  propertyType,
  onPrimitiveApplied,
  size = 'small',
}) => {
  const isDark = useDarkMode();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [primitives, setPrimitives] = useState<Primitive[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSystemPrimitives, setShowSystemPrimitives] = useState(true);
  const [showTenantPrimitives, setShowTenantPrimitives] = useState(true);
  const [selectedPrimitive, setSelectedPrimitive] = useState<Primitive | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch primitives when dialog opens
  useEffect(() => {
    if (dialogOpen) {
      fetchPrimitives();
    }
  }, [dialogOpen]);

  const fetchPrimitives = async () => {
    setLoading(true);
    setError(null);
    try {
      const category = propertyTypeToPrimitiveCategory[propertyType];
      const url = category ? `/api/primitives?category=${category}` : '/api/primitives';
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error('Failed to fetch primitives');
      }

      const data = await response.json();
      if (data.success) {
        setPrimitives(data.primitives || []);
      } else {
        setError(data.error || 'Failed to load primitives');
      }
    } catch (err) {
      console.error('Error fetching primitives:', err);
      setError(err instanceof Error ? err.message : 'Failed to load primitives');
    } finally {
      setLoading(false);
    }
  };

  // Filter primitives based on search and visibility settings
  const filteredPrimitives = useMemo(() => {
    let filtered = primitives;

    // Filter by system/tenant
    if (!showSystemPrimitives) {
      filtered = filtered.filter(p => !p.is_system);
    }
    if (!showTenantPrimitives) {
      filtered = filtered.filter(p => p.is_system);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(p =>
        p.name.toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    // Sort: tenant primitives first, then alphabetically
    return filtered.sort((a, b) => {
      if (a.is_system !== b.is_system) {
        return a.is_system ? 1 : -1; // Tenant primitives first
      }
      return a.name.localeCompare(b.name);
    });
  }, [primitives, searchQuery, showSystemPrimitives, showTenantPrimitives]);

  // Apply primitive schema to form data
  const applyPrimitive = (primitive: Primitive) => {
    const schema = primitive.schema;

    // First, clear all constraint fields (preserve title, description which are identity fields)
    // Clear string constraints
    onChange('format', '');
    onChange('pattern', '');
    onChange('minLength', '');
    onChange('maxLength', '');

    // Clear number constraints
    onChange('minimum', '');
    onChange('maximum', '');
    onChange('minimumType', undefined);
    onChange('maximumType', undefined);
    onChange('multipleOf', '');

    // Clear array constraints
    onChange('minItems', '');
    onChange('maxItems', '');
    onChange('uniqueItems', false);

    // Clear enum and default
    onChange('enum', []);
    onChange('default', '');
    onChange('const', '');

    // Now apply the primitive's constraints
    // Apply format
    if (schema.format !== undefined) {
      onChange('format', schema.format as string);
    }

    // Apply pattern (regex)
    if (schema.pattern !== undefined) {
      onChange('pattern', schema.pattern as string);
    }

    // Apply string constraints
    if (schema.minLength !== undefined) {
      onChange('minLength', String(schema.minLength));
    }
    if (schema.maxLength !== undefined) {
      onChange('maxLength', String(schema.maxLength));
    }

    // Apply number constraints
    if (schema.minimum !== undefined) {
      onChange('minimum', String(schema.minimum));
      onChange('minimumType', 'inclusive');
    }
    if (schema.exclusiveMinimum !== undefined) {
      onChange('minimum', String(schema.exclusiveMinimum));
      onChange('minimumType', 'exclusive');
    }
    if (schema.maximum !== undefined) {
      onChange('maximum', String(schema.maximum));
      onChange('maximumType', 'inclusive');
    }
    if (schema.exclusiveMaximum !== undefined) {
      onChange('maximum', String(schema.exclusiveMaximum));
      onChange('maximumType', 'exclusive');
    }
    if (schema.multipleOf !== undefined) {
      onChange('multipleOf', String(schema.multipleOf));
    }

    // Apply array constraints
    if (schema.minItems !== undefined) {
      onChange('minItems', String(schema.minItems));
    }
    if (schema.maxItems !== undefined) {
      onChange('maxItems', String(schema.maxItems));
    }
    if (schema.uniqueItems !== undefined) {
      onChange('uniqueItems', schema.uniqueItems);
    }

    // Apply enum values
    if (schema.enum !== undefined && Array.isArray(schema.enum)) {
      onChange('enum', schema.enum.map(String));
    }

    // Apply default value
    if (schema.default !== undefined) {
      onChange('default', String(schema.default));
    }

    // Apply const value
    if (schema.const !== undefined) {
      onChange('const', typeof schema.const === 'string' ? schema.const : JSON.stringify(schema.const));
    }

    // Apply description only if the form doesn't have one (don't overwrite user's description)
    if (schema.description && !formData.description) {
      onChange('description', schema.description as string);
    }

    // Notify callback
    if (onPrimitiveApplied) {
      onPrimitiveApplied(primitive);
    }

    setDialogOpen(false);
    setSelectedPrimitive(null);
    setSearchQuery('');
  };

  // Render schema preview
  const renderSchemaPreview = (schema: Record<string, unknown>) => {
    const constraints: string[] = [];

    if (schema.format) constraints.push(`format: ${schema.format}`);
    if (schema.pattern) constraints.push(`pattern: ${schema.pattern}`);
    if (schema.minLength !== undefined) constraints.push(`minLength: ${schema.minLength}`);
    if (schema.maxLength !== undefined) constraints.push(`maxLength: ${schema.maxLength}`);
    if (schema.minimum !== undefined) constraints.push(`minimum: ${schema.minimum}`);
    if (schema.maximum !== undefined) constraints.push(`maximum: ${schema.maximum}`);
    if (schema.exclusiveMinimum !== undefined) constraints.push(`exclusiveMinimum: ${schema.exclusiveMinimum}`);
    if (schema.exclusiveMaximum !== undefined) constraints.push(`exclusiveMaximum: ${schema.exclusiveMaximum}`);
    if (schema.multipleOf !== undefined) constraints.push(`multipleOf: ${schema.multipleOf}`);
    if (schema.minItems !== undefined) constraints.push(`minItems: ${schema.minItems}`);
    if (schema.maxItems !== undefined) constraints.push(`maxItems: ${schema.maxItems}`);
    if (schema.uniqueItems) constraints.push('uniqueItems: true');
    if (schema.enum && Array.isArray(schema.enum)) {
      const enumStr = (schema.enum as string[]).slice(0, 3).join(', ');
      constraints.push(`enum: [${enumStr}${(schema.enum as string[]).length > 3 ? '...' : ''}]`);
    }

    return constraints.length > 0 ? constraints.join(', ') : 'No constraints defined';
  };

  return (
    <>
      {/* Trigger Button */}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size={size === 'small' ? 'sm' : 'default'}
          onClick={() => setDialogOpen(true)}
          className="gap-2"
        >
          <Sparkles size={14} />
          Select
        </Button>
        <span
          className="text-xs text-gray-500 dark:text-gray-400 cursor-help"
          title="Apply a predefined primitive type to automatically set format, pattern, and constraints"
        >
          ⓘ
        </span>
      </div>

      {/* Selection Dialog */}
      <Dialog open={dialogOpen} onOpenChange={(isOpen) => {
        if (!isOpen) {
          setDialogOpen(false);
          setSelectedPrimitive(null);
          setSearchQuery('');
        }
      }} modal={true}>
        <DialogContent
          className="max-w-3xl h-[80vh] max-h-[700px] p-0 flex flex-col overflow-hidden"
          showCloseButton={true}
          aria-describedby={undefined}
        >
          <DialogHeader className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
            <div className="flex items-center gap-2">
              <Sparkles size={20} className="text-indigo-500" />
              <DialogTitle className="text-lg font-semibold">Apply Primitive</DialogTitle>
            </div>
          </DialogHeader>

          {/* Search and Filters */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 space-y-3">
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="Search primitives by name, description, or tags..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 pr-9"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={showSystemPrimitives}
                  onCheckedChange={(checked) => setShowSystemPrimitives(!!checked)}
                />
                <Shield size={14} className="text-emerald-500" />
                <span className="text-sm">System Primitives</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={showTenantPrimitives}
                  onCheckedChange={(checked) => setShowTenantPrimitives(!!checked)}
                />
                <User size={14} className="text-indigo-500" />
                <span className="text-sm">Tenant Primitives</span>
              </label>
              <span className="ml-auto text-xs text-gray-500 dark:text-gray-400 px-2 py-1 rounded border border-gray-200 dark:border-gray-700">
                Showing {filteredPrimitives.length} primitive{filteredPrimitives.length !== 1 ? 's' : ''}
              </span>
            </div>
          </div>

          {/* Primitives List */}
          <div className="flex-1 overflow-y-auto min-h-0">
            {loading ? (
              <div className="flex justify-center items-center py-16">
                <Loader2 size={32} className="animate-spin text-indigo-500" />
              </div>
            ) : error ? (
              <div className="p-8 text-center">
                <p className="text-red-500 mb-4">{error}</p>
                <Button onClick={fetchPrimitives} variant="outline">Retry</Button>
              </div>
            ) : filteredPrimitives.length === 0 ? (
              <div className="p-8 text-center">
                <Database size={48} className="mx-auto text-gray-300 dark:text-gray-600 mb-4" />
                <p className="text-gray-600 dark:text-gray-400">
                  {searchQuery ? 'No primitives match your search' : `No ${propertyType} primitives available`}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
                  {searchQuery ? 'Try a different search term' : 'Create primitives in the Primitives Management section'}
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-800">
                {filteredPrimitives.map((primitive) => (
                  <button
                    key={primitive.id}
                    onClick={() => setSelectedPrimitive(primitive)}
                    onDoubleClick={() => applyPrimitive(primitive)}
                    className={`w-full text-left px-4 py-3 transition-colors ${
                      selectedPrimitive?.id === primitive.id
                        ? 'bg-indigo-50 dark:bg-indigo-900/20'
                        : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {primitive.is_system ? (
                        <span title="System Primitive">
                          <Shield size={14} className="text-emerald-500" />
                        </span>
                      ) : (
                        <span title="Tenant Primitive">
                          <User size={14} className="text-indigo-500" />
                        </span>
                      )}
                      <span className="font-semibold text-gray-900 dark:text-gray-100">
                        {primitive.name}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                        {primitive.category}
                      </span>
                      {primitive.usage_count > 0 && (
                        <span className="ml-auto text-xs text-gray-500">
                          Used {primitive.usage_count}×
                        </span>
                      )}
                    </div>

                    {primitive.description && (
                      <p className="text-sm text-gray-600 dark:text-gray-400 truncate mb-1">
                        {primitive.description}
                      </p>
                    )}

                    <p className="text-xs text-gray-500 dark:text-gray-500 font-mono truncate">
                      {renderSchemaPreview(primitive.schema)}
                    </p>

                    {primitive.tags.length > 0 && (
                      <div className="flex gap-1 mt-1.5 flex-wrap">
                        {primitive.tags.slice(0, 5).map((tag) => (
                          <span
                            key={tag}
                            className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
                          >
                            {tag}
                          </span>
                        ))}
                        {primitive.tags.length > 5 && (
                          <span className="text-xs text-gray-500">
                            +{primitive.tags.length - 5} more
                          </span>
                        )}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selected Primitive Preview */}
          {selectedPrimitive && (
            <div className={`px-4 py-3 border-t border-gray-200 dark:border-gray-700 ${isDark ? 'bg-indigo-900/10' : 'bg-indigo-50/50'}`}>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-2">Schema Preview</p>
              <pre className={`text-xs font-mono p-3 rounded-lg overflow-auto max-h-32 ${isDark ? 'bg-slate-900 text-gray-300' : 'bg-gray-100 text-gray-800'}`}>
                {JSON.stringify(selectedPrimitive.schema, null, 2)}
              </pre>
            </div>
          )}

          {/* Footer */}
          <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
            <div className="flex justify-end gap-2 w-full">
              <Button
                variant="outline"
                onClick={() => {
                  setDialogOpen(false);
                  setSelectedPrimitive(null);
                  setSearchQuery('');
                }}
              >
                Cancel
              </Button>
              <Button
                disabled={!selectedPrimitive}
                onClick={() => selectedPrimitive && applyPrimitive(selectedPrimitive)}
              >
                Apply Primitive
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default PrimitiveSelector;

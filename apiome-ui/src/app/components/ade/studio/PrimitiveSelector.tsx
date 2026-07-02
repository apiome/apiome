'use client';

import React, { useState, useEffect, useMemo } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import { PropertyFormData } from './PropertyFormFields';
import { cn } from '../../../../../lib/utils';
import {
  Search,
  X,
  ShieldCheck,
  Lock,
  Download,
  Boxes,
  Database,
  Loader2,
  Link2,
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

  // JSON Schema 2020-12 type-registry columns (#3447 — extended apiome.primitives).
  // Optional so older API payloads (pre-registry) still satisfy the type.
  /** Registry namespace path, e.g. `std/v0/types` or `tenant/<slug>/types`. */
  namespace?: string | null;
  /** Import-source base URL relative `$ref` values resolve against. */
  base_uri?: string | null;
  /** Computed/stored JSON Schema `$id`. */
  schema_id?: string | null;
  /** JSON Schema dialect/draft (default `2020-12`). */
  draft?: string | null;
  /** Provenance: `human` (authored in-app) or `imported` (from a JSON Schema / bundle). */
  source?: string | null;
  /** Relative `$ref` edges recorded for this primitive. */
  refs?: Array<Record<string, unknown>>;
}

/**
 * Type-picker scope tabs. The four tabs map onto `apiome.primitives` rows by
 * `is_system` / `tenant_id` / `source`:
 *   - standard → system rows in a `.../primitives` namespace (the JSON base types)
 *   - core     → all other system rows (the `std/v0/types` derived/composite types)
 *   - tenant   → tenant-owned rows authored in-app (`source !== 'imported'`)
 *   - custom   → tenant-owned rows that were imported (`source === 'imported'`)
 */
export type TypePickerTab = 'standard' | 'core' | 'tenant' | 'custom';

export interface TypeBinding {
  /** Stable registry `$ref`, e.g. `std/v0/types/date`. */
  ref: string;
  /** The primitive the property was bound to. */
  primitive: Primitive;
}

export interface PrimitiveSelectorProps {
  // Form data and update handler
  formData: PropertyFormData;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- value spans every PropertyFormData field type
  onChange: (field: keyof PropertyFormData, value: any) => void;

  // Current property type (to filter primitives by category)
  propertyType: string;

  // Optional: callback when a primitive is applied
  onPrimitiveApplied?: (primitive: Primitive) => void;

  // Optional: callback when a registry type is bound (emits the stable `$ref`).
  // Fires only when the selected primitive resolves to a registry `$ref`.
  onTypeBound?: (binding: TypeBinding) => void;

  // Optional: callback when the selection dialog opens or closes (e.g. to dim parent form)
  onOpenChange?: (open: boolean) => void;

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

interface TabMeta {
  id: TypePickerTab;
  label: string;
  icon: React.ReactNode;
  /** Short scope description shown under the tab strip. */
  scope: string;
}

const TABS: TabMeta[] = [
  { id: 'standard', label: 'Standard', icon: <Boxes size={14} />, scope: 'JSON Schema base types · available to all tenants' },
  { id: 'core', label: 'Core System Types', icon: <ShieldCheck size={14} />, scope: 'System · core — visible to every tenant' },
  { id: 'tenant', label: 'Tenant Types', icon: <Lock size={14} />, scope: 'Private to your tenant' },
  { id: 'custom', label: 'Custom · Imported', icon: <Download size={14} />, scope: 'Imported into your tenant from a JSON Schema or bundle' },
];

/**
 * Classify a primitive into one of the four type-picker tabs based on its scope
 * columns. System rows in a `.../primitives` namespace are the JSON base types
 * ("Standard"); all other system rows are "Core". Tenant rows split on
 * provenance: imported rows are "Custom", everything else is "Tenant".
 */
export function classifyPrimitive(p: Primitive): TypePickerTab {
  if (p.is_system) {
    return p.namespace && p.namespace.replace(/\/+$/, '').endsWith('/primitives')
      ? 'standard'
      : 'core';
  }
  return p.source === 'imported' ? 'custom' : 'tenant';
}

/**
 * Build the stable registry `$ref` for a primitive, e.g.
 * `std/v0/types` + `date` → `std/v0/types/date`. Returns `null` for legacy flat
 * primitives that have no namespace (those bind by inline schema only).
 */
export function buildTypeRef(p: Primitive): string | null {
  if (p.namespace && p.namespace.trim()) {
    const ns = p.namespace.replace(/\/+$/, '');
    return `${ns}/${p.name}`;
  }
  return null;
}

export const PrimitiveSelector: React.FC<PrimitiveSelectorProps> = ({
  formData,
  onChange,
  propertyType,
  onPrimitiveApplied,
  onTypeBound,
  onOpenChange,
  size = 'small',
}) => {
  const isDark = useDarkMode();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [primitives, setPrimitives] = useState<Primitive[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<TypePickerTab>('core');
  const [selectedPrimitive, setSelectedPrimitive] = useState<Primitive | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch primitives when dialog opens
  useEffect(() => {
    if (dialogOpen) {
      fetchPrimitives();
    }
  }, [dialogOpen]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Group primitives by tab once per fetch.
  const grouped = useMemo(() => {
    const buckets: Record<TypePickerTab, Primitive[]> = {
      standard: [],
      core: [],
      tenant: [],
      custom: [],
    };
    for (const p of primitives) {
      buckets[classifyPrimitive(p)].push(p);
    }
    return buckets;
  }, [primitives]);

  // When the dialog opens, land on the first tab that actually has types so the
  // user is not greeted with an empty list.
  useEffect(() => {
    if (!dialogOpen) return;
    if (grouped[activeTab].length > 0) return;
    const firstNonEmpty = TABS.find((t) => grouped[t.id].length > 0);
    if (firstNonEmpty) {
      setActiveTab(firstNonEmpty.id);
    }
  }, [dialogOpen, grouped]); // eslint-disable-line react-hooks/exhaustive-deps

  // Filter the active tab by the search query. Search spans name, namespace,
  // description and tags so namespaces are searchable ("search across namespaces").
  const filteredPrimitives = useMemo(() => {
    let filtered = grouped[activeTab];

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(p =>
        p.name.toLowerCase().includes(query) ||
        (p.namespace || '').toLowerCase().includes(query) ||
        (buildTypeRef(p) || '').toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    // Sort alphabetically by ref (falls back to name) for a stable order.
    return [...filtered].sort((a, b) =>
      (buildTypeRef(a) || a.name).localeCompare(buildTypeRef(b) || b.name)
    );
  }, [grouped, activeTab, searchQuery]);

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

    // Persist the stable registry `$ref` binding plus the resolved target
    // (the primitive's id) so the binding survives reload (#3475). Legacy
    // primitives have no namespace and thus no stable ref — clear both so they
    // fall back to inline-schema merge (the migration path for existing props).
    const ref = buildTypeRef(primitive);
    onChange('$ref', ref || '');
    onChange('primitive_id', ref ? primitive.id : '');
    if (ref && onTypeBound) {
      onTypeBound({ ref, primitive });
    }

    // Notify callback
    if (onPrimitiveApplied) {
      onPrimitiveApplied(primitive);
    }

    closeDialog();
  };

  const closeDialog = () => {
    setDialogOpen(false);
    setSelectedPrimitive(null);
    setSearchQuery('');
    onOpenChange?.(false);
  };

  // Clear the current registry binding without opening the picker. Drops both
  // the stored `$ref` and the resolved primitive id (#3475).
  const clearBinding = () => {
    onChange('$ref', '');
    onChange('primitive_id', '');
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

  const activeScope = TABS.find((t) => t.id === activeTab)?.scope ?? '';
  const boundRef = formData.$ref;

  return (
    <>
      {/* Trigger Button + current binding chip */}
      <div className="flex items-center gap-2 flex-wrap justify-end">
        {boundRef && (
          <span
            className="inline-flex items-center gap-1.5 rounded-md border border-teal-200 bg-teal-50 px-2 py-1 text-xs font-mono text-teal-700 dark:border-teal-800 dark:bg-teal-900/30 dark:text-teal-300"
            title={`Bound to registry type ${boundRef}`}
          >
            <Link2 size={12} />
            {boundRef}
            <button
              type="button"
              onClick={clearBinding}
              aria-label="Clear type binding"
              className="ml-0.5 rounded-sm opacity-70 hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
            >
              <X size={12} />
            </button>
          </span>
        )}
        <Button
          variant="outline"
          size={size === 'small' ? 'sm' : 'default'}
          onClick={() => {
            setDialogOpen(true);
            onOpenChange?.(true);
          }}
          className="gap-2"
        >
          <Boxes size={14} />
          {boundRef ? 'Change Type' : 'Select Type'}
        </Button>
        <span
          className="text-xs text-gray-500 dark:text-gray-400 cursor-help"
          title="Bind this property to a Standard, Core, Tenant, or Custom registry type. A registry type writes a stable $ref; constraints are applied from the type's schema."
        >
          ⓘ
        </span>
      </div>

      {/* Selection Dialog — uses z-[10000]/[10001] to sit above any parent Dialog (z-9999) */}
      <Dialog open={dialogOpen} onOpenChange={(isOpen) => {
        if (!isOpen) {
          closeDialog();
        }
      }} modal={true}>
        <DialogPortal>
          <DialogOverlay className="z-[10000]" />
          <DialogPrimitive.Content
            className={cn(
              'fixed left-[50%] top-[50%] z-[10001] w-full translate-x-[-50%] translate-y-[-50%]',
              'max-w-3xl h-[80vh] max-h-[700px] p-0 flex flex-col overflow-hidden',
              'border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl rounded-xl',
            )}
            aria-describedby={undefined}
          >
          <DialogHeader className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Boxes size={20} className="text-indigo-500" />
                <DialogTitle className="text-lg font-semibold">Select Type</DialogTitle>
              </div>
              <DialogPrimitive.Close className="rounded-sm opacity-70 ring-offset-white transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:pointer-events-none dark:ring-offset-gray-800">
                <X className="h-4 w-4 text-gray-500 dark:text-gray-400" />
                <span className="sr-only">Close</span>
              </DialogPrimitive.Close>
            </div>
          </DialogHeader>

          {/* Search */}
          <div className="px-4 pt-3 border-b border-gray-200 dark:border-gray-700">
            <div className="relative mb-3">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="Search standard & custom types by name, namespace, or tag..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 pr-9"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  aria-label="Clear search"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Tabs */}
            <div role="tablist" aria-label="Type scope" className="flex items-center gap-1 overflow-x-auto">
              {TABS.map((tab) => {
                const count = grouped[tab.id].length;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => { setActiveTab(tab.id); setSelectedPrimitive(null); }}
                    className={cn(
                      'flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors',
                      isActive
                        ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400 font-medium'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-indigo-500',
                    )}
                  >
                    {tab.icon}
                    {tab.label}
                    <span className={cn(
                      'ml-1 rounded-full px-1.5 py-0.5 text-[10px]',
                      isActive
                        ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400',
                    )}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Scope chip + count */}
          <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-gray-200 dark:border-gray-700">
            <span className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
              {TABS.find((t) => t.id === activeTab)?.icon}
              {activeScope}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-1 rounded border border-gray-200 dark:border-gray-700">
              Showing {filteredPrimitives.length} type{filteredPrimitives.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Types List */}
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
                  {searchQuery ? 'No types match your search' : `No ${propertyType} types in this scope`}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
                  {searchQuery ? 'Try a different search term' : 'Try another tab, or create types in the Primitives section'}
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-800">
                {filteredPrimitives.map((primitive) => {
                  const ref = buildTypeRef(primitive);
                  const tab = classifyPrimitive(primitive);
                  return (
                    <button
                      key={primitive.id}
                      onClick={() => setSelectedPrimitive(primitive)}
                      onDoubleClick={() => applyPrimitive(primitive)}
                      className={cn(
                        'w-full text-left px-4 py-3 transition-colors',
                        selectedPrimitive?.id === primitive.id
                          ? 'bg-indigo-50 dark:bg-indigo-900/20'
                          : 'hover:bg-gray-50 dark:hover:bg-gray-800/50',
                      )}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <ScopeIcon tab={tab} />
                        <span className="font-semibold text-gray-900 dark:text-gray-100 font-mono text-sm truncate">
                          {ref || primitive.name}
                        </span>
                        <ScopeBadge tab={tab} />
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

                      {ref ? (
                        <p className="text-xs text-gray-500 dark:text-gray-500 font-mono truncate">
                          $ref {ref}
                        </p>
                      ) : (
                        <p className="text-xs text-gray-500 dark:text-gray-500 font-mono truncate">
                          {renderSchemaPreview(primitive.schema)}
                        </p>
                      )}

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
                  );
                })}
              </div>
            )}
          </div>

          {/* Selected Type Preview */}
          {selectedPrimitive && (
            <div className={`px-4 py-3 border-t border-gray-200 dark:border-gray-700 ${isDark ? 'bg-indigo-900/10' : 'bg-indigo-50/50'}`}>
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Schema Preview</p>
                {buildTypeRef(selectedPrimitive) && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-mono text-teal-700 dark:text-teal-300">
                    <Link2 size={12} />
                    $ref {buildTypeRef(selectedPrimitive)}
                  </span>
                )}
              </div>
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
                onClick={closeDialog}
              >
                Cancel
              </Button>
              <Button
                disabled={!selectedPrimitive}
                onClick={() => selectedPrimitive && applyPrimitive(selectedPrimitive)}
              >
                Apply Type
              </Button>
            </div>
          </DialogFooter>
          </DialogPrimitive.Content>
        </DialogPortal>
      </Dialog>
    </>
  );
};

/** Per-scope leading icon for a type row. */
const ScopeIcon: React.FC<{ tab: TypePickerTab }> = ({ tab }) => {
  switch (tab) {
    case 'standard':
      return <span title="Standard JSON type"><Boxes size={14} className="text-sky-500" /></span>;
    case 'core':
      return <span title="System · core type"><ShieldCheck size={14} className="text-teal-500" /></span>;
    case 'tenant':
      return <span title="Tenant type"><Lock size={14} className="text-indigo-500" /></span>;
    case 'custom':
      return <span title="Imported type"><Download size={14} className="text-amber-500" /></span>;
  }
};

/** Per-scope text badge for a type row. */
const ScopeBadge: React.FC<{ tab: TypePickerTab }> = ({ tab }) => {
  const styles: Record<TypePickerTab, string> = {
    standard: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
    core: 'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
    tenant: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
    custom: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  };
  const labels: Record<TypePickerTab, string> = {
    standard: 'Standard',
    core: 'System · core',
    tenant: 'Tenant',
    custom: 'Imported',
  };
  return (
    <span className={cn('text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap', styles[tab])}>
      {labels[tab]}
    </span>
  );
};

export default PrimitiveSelector;

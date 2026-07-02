// SideNav.tsx
'use client';

import React, { useMemo, useState } from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import { Search, Plus, Pencil, Trash2, FileX, Upload, Library, ChevronDown, ChevronUp, ChevronRight, Eye, EyeOff, Boxes, ListTree, Layers, Bot } from 'lucide-react';
import { getPropertiesForClassesBatch } from '../../../../../lib/db/helper';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import SidebarDensityToggle from '@/app/components/sidebar/SidebarDensityToggle';
import { sidebarTheme, useSidebarTokens } from '@/app/components/sidebar/sidebar-theme';

export interface ClassItem {
  id: string;
  name: string;
  description?: string;
  schema?: any; // JSON Schema object stored in database
}

export interface PropertyItem {
  id: string;
  name: string;
  type?: string;
  $ref?: string; // Reference to another class schema
  title?: string;
  description?: string;
  format?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number; // OpenAPI 3.1: numeric value, not boolean
  exclusiveMaximum?: number; // OpenAPI 3.1: numeric value, not boolean
  multipleOf?: number;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  enum?: string[];
  default?: any;
  required?: boolean;
  // Metadata fields
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  deprecationMessage?: string;
  example?: any;
  additionalProperties?: boolean | any;
  // Tuple mode (OpenAPI 3.1)
  tupleMode?: boolean;
  prefixItems?: any[]; // OpenAPI 3.1: Array of schemas for specific positions
  items?: any; // Schema for items beyond prefix positions
}

export interface StudioSideNavCallbacks {
  // Classes callbacks
  onClassAdd?: () => void;
  onClassEdit?: (classItem: ClassItem) => void;
  onClassDelete?: (classId: string) => void;
  onClassSelect?: (classItem: ClassItem) => void;
  onClassVisibilityToggle?: (classId: string, visible?: boolean) => void;
  onClassImport?: () => void;
  onClassTemplates?: () => void;

  // Properties callbacks
  onPropertyAdd?: () => void;
  onPropertyEdit?: (propertyItem: PropertyItem) => void;
  onPropertyDelete?: (propertyId: string) => void;
  onPropertySelect?: (propertyItem: PropertyItem) => void;
  onPropertyTemplates?: () => void;
  /** Open AI-assisted property suggestions (#609) */
  onPropertyAiSuggest?: () => void;

  // Groups callbacks
  onGroupAdd?: () => void;
  onGroupSelect?: (groupId: string) => void;
  onGroupDelete?: (groupId: string) => void;
  onGroupDeleteAllClasses?: (groupId: string) => void;
}

export interface GroupItem {
  id: string;
  name: string;
  color: string;
  nodeIds: string[];
}

interface StudioSideNavProps {
  classes?: ClassItem[];
  properties?: PropertyItem[];
  groups?: GroupItem[];
  callbacks?: StudioSideNavCallbacks;
  refreshKey?: number; // Used to trigger refresh from parent
  selectedProjectId?: string | null; // Currently selected project from canvas
  selectedVersionId?: string | null; // Currently selected version from canvas
  isReadOnly?: boolean; // Whether the current version is published (read-only)
  hiddenClassIds?: string[];
  /** #2595: Data Designer Code tab keeps /editor URL — block group row delete actions during layout/pointer transitions */
  suppressGroupDestructiveActions?: boolean;
  // classWarnings?: Record<string, boolean>; // removed, computed locally
  [key: string]: any; // allow future, non-breaking props from parent
}

const StudioSideNav: React.FC<StudioSideNavProps> = ({
  classes = [],
  properties = [],
  groups = [],
  callbacks = {},
  refreshKey = 0,
  selectedProjectId = null,
  selectedVersionId = null,
  isReadOnly = false,
  hiddenClassIds = [],
  suppressGroupDestructiveActions = false,
}) => {
  // Dark mode detection using shared hook
  const isDark = useDarkMode();
  const tokens = useSidebarTokens();

  const [currentTab, setCurrentTab] = useState<'classes' | 'properties' | 'groups'>('classes');
  const [classesSearchQuery, setClassesSearchQuery] = useState('');
  const [propertiesSearchQuery, setPropertiesSearchQuery] = useState('');
  const [groupsSearchQuery, setGroupsSearchQuery] = useState('');
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);
  const [selectedPropertyId, setSelectedPropertyId] = useState<string | null>(null);
  const [classWarnings, setClassWarnings] = useState<Record<string, boolean>>({});
  const [expandedPropertyIds, setExpandedPropertyIds] = useState<Set<string>>(new Set());
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(new Set());

  // Helper to check if a property has inline properties (type: 'object' with properties, or array of objects)
  const hasInlineProperties = (prop: PropertyItem): boolean => {
    // Check for object type with nested properties
    if (prop.type === 'object' && (prop as any).properties && Object.keys((prop as any).properties).length > 0) {
      return true;
    }
    // Check for array type with object items that have properties
    if (prop.type === 'array' && prop.items?.type === 'object' && prop.items?.properties && Object.keys(prop.items.properties).length > 0) {
      return true;
    }
    return false;
  };

  // Helper to extract inline properties from a property
  const getInlineProperties = (prop: PropertyItem): { name: string; type: string; description?: string; required?: boolean }[] => {
    const children: { name: string; type: string; description?: string; required?: boolean }[] = [];

    // Handle object type with nested properties
    if (prop.type === 'object' && (prop as any).properties) {
      const requiredFields = Array.isArray((prop as any).required) ? (prop as any).required : [];
      for (const [name, schema] of Object.entries<any>((prop as any).properties)) {
        children.push({
          name,
          type: schema.type || 'object',
          description: schema.description,
          required: requiredFields.includes(name),
        });
      }
    }

    // Handle array type with object items
    if (prop.type === 'array' && prop.items?.type === 'object' && prop.items?.properties) {
      const requiredFields = Array.isArray(prop.items.required) ? prop.items.required : [];
      for (const [name, schema] of Object.entries<any>(prop.items.properties)) {
        children.push({
          name,
          type: schema.type || 'object',
          description: schema.description,
          required: requiredFields.includes(name),
        });
      }
    }

    return children;
  };

  const toggleGroupExpanded = (groupId: string) => {
    setExpandedGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  // Toggle expanded state for a property
  const togglePropertyExpanded = (propertyId: string) => {
    setExpandedPropertyIds((prev) => {
      const next = new Set(prev);
      if (next.has(propertyId)) {
        next.delete(propertyId);
      } else {
        next.add(propertyId);
      }
      return next;
    });
  };

  /** Stable across parent re-renders that replace the `classes` array reference without semantic change. */
  const classListFingerprint = useMemo(
    () =>
      `${selectedVersionId ?? ''}\n${classes.map((c) => `${c.id}\t${c.name}`).sort().join('\n')}`,
    [classes, selectedVersionId]
  );

  // Compute dangling $ref warnings when classes change (one batched server action per update).
  React.useEffect(() => {
    const computeWarnings = async () => {
      if (!selectedVersionId || classes.length === 0) {
        setClassWarnings({});
        return;
      }
      const nameSet = new Set(classes.map((c) => c.name));
      const warnings: Record<string, boolean> = {};
      try {
        const res = await getPropertiesForClassesBatch(classes.map((c) => c.id));
        const byClass = JSON.parse(res) as Record<string, Array<{ data?: unknown }> | undefined>;
        for (const cls of classes) {
          try {
            const props = byClass[cls.id] ?? [];
            let hasDangling = false;
            for (const p of props) {
              const d = typeof p.data === 'string' ? JSON.parse(p.data) : p.data;
              if (!d) continue;
              const ref = d.$ref || (d.type === 'array' && d.items?.$ref);
              if (ref) {
                const parts = String(ref).split('/');
                const refName = parts[parts.length - 1] || String(ref);
                if (!nameSet.has(refName)) {
                  hasDangling = true;
                  break;
                }
              }
            }
            warnings[cls.id] = hasDangling;
          } catch {
            warnings[cls.id] = false;
          }
        }
        setClassWarnings(warnings);
      } catch {
        setClassWarnings({});
      }
    };
    void computeWarnings();
    // `classListFingerprint` encodes `selectedVersionId` and class id/name lines; listing `classes`
    // would re-run whenever the parent passes a new array reference (same canvas), restoring POST spam.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional fingerprint-based deps
  }, [classListFingerprint, refreshKey]);

  const handleTabChange = (newValue: string) => {
    setCurrentTab(newValue as 'classes' | 'properties' | 'groups');
  };

  // Filter classes based on search query
  const filteredClasses = classes.filter(cls =>
    cls.name.toLowerCase().includes(classesSearchQuery.toLowerCase()) ||
    (cls.description?.toLowerCase().includes(classesSearchQuery.toLowerCase()) ?? false)
  );

  // Filter properties based on search query
  const filteredProperties = properties.filter(prop => {
    const searchLower = propertiesSearchQuery.toLowerCase();
    const nameMatch = prop.name.toLowerCase().includes(searchLower);

    // Handle type which could be string, array, or undefined
    let typeMatch = false;
    if (prop.type) {
      const typeStr = typeof prop.type === 'string' ? prop.type : JSON.stringify(prop.type);
      typeMatch = typeStr.toLowerCase().includes(searchLower);
    }

    const descMatch = prop.description?.toLowerCase().includes(searchLower) ?? false;

    return nameMatch || typeMatch || descMatch;
  });

  // Filter groups based on search query
  const filteredGroups = groups.filter(group =>
    group.name.toLowerCase().includes(groupsSearchQuery.toLowerCase())
  );

  const handleClassSelect = (classItem: ClassItem) => {
    setSelectedClassId(classItem.id);
    callbacks.onClassSelect?.(classItem);
  };

  const handlePropertySelect = (propertyItem: PropertyItem) => {
    setSelectedPropertyId(propertyItem.id);
    callbacks.onPropertySelect?.(propertyItem);
  };

  /**
   * VSCode/Cursor-style activity rail (~48px) + content layout. The rail
   * lives flush-left inside the drawer; content fills the remaining width.
   */
  const ACTIVITY_RAIL_WIDTH = 40;
  const DRAWER_WIDTH = 320;

  const drawerStyle = {
    width: DRAWER_WIDTH,
    flexShrink: 0,
    boxSizing: 'border-box' as const,
    top: 102,
    /* 102px = top app bar + studio subheader; 22px = StudioFooterBar reserve. */
    height: 'calc(100vh - 124px)',
    borderRight: 'none',
    background: isDark
      ? 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)'
      : 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
    boxShadow: isDark ? '4px 0 24px rgba(0, 0, 0, 0.3)' : '4px 0 24px rgba(0, 0, 0, 0.06)',
  };

  /**
   * Single icon button on the activity rail. Rendered as a Radix
   * Tabs.Trigger so it keeps role="tab" semantics (consumed by tests and
   * assistive tech). The aria-label preserves the previous human-readable
   * label even though the visible content is now an icon.
   */
  const railTriggerClass = [
    'relative flex items-center justify-center w-9 h-9 rounded-md transition-colors',
    'text-slate-500 dark:text-slate-400 hover:text-indigo-500 hover:bg-indigo-500/5',
    'data-[state=active]:text-indigo-500 data-[state=active]:bg-indigo-500/10',
    /* Left accent bar (VSCode pattern) shown only when active. */
    'before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[2px] before:rounded-r',
    'before:bg-transparent data-[state=active]:before:bg-indigo-500',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
  ].join(' ');

  return (
    <aside className="flex-shrink-0" style={drawerStyle}>
      <Tabs.Root
        value={currentTab}
        onValueChange={handleTabChange}
        orientation="vertical"
        className="flex h-full"
      >
        {/* Activity rail (icons left) */}
        <Tabs.List
          aria-label="Studio sidebar sections"
          className={[
            'flex flex-col items-center gap-0.5 py-1.5 shrink-0 border-r',
            sidebarTheme.borderSoft,
          ].join(' ')}
          style={{ width: ACTIVITY_RAIL_WIDTH }}
        >
          <Tabs.Trigger
            value="classes"
            aria-label="Classes"
            title="Classes"
            className={railTriggerClass}
          >
            <Boxes className="w-4 h-4" aria-hidden />
          </Tabs.Trigger>
          <Tabs.Trigger
            value="properties"
            aria-label="Properties"
            title="Properties"
            className={railTriggerClass}
          >
            <ListTree className="w-4 h-4" aria-hidden />
          </Tabs.Trigger>
          <Tabs.Trigger
            value="groups"
            aria-label="Groups"
            title="Groups"
            className={railTriggerClass}
          >
            <Layers className="w-4 h-4" aria-hidden />
          </Tabs.Trigger>
        </Tabs.List>

        {/* Content panel (right of rail) */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Section header shows the active label so users still see
              "Classes / Properties / Groups" in plain text. */}
          <div
            className={[
              'flex items-center px-3 shrink-0 border-b',
              tokens.headerHeight,
              sidebarTheme.borderSoft,
            ].join(' ')}
          >
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-300">
              {currentTab === 'classes' ? 'Classes' : currentTab === 'properties' ? 'Properties' : 'Groups'}
            </span>
          </div>

          {/* Version/Project Status Indicator */}
          {((currentTab === 'classes' && !selectedVersionId) || (currentTab === 'properties' && !selectedProjectId)) && (
            <div className="p-4 text-center text-xs font-semibold border-b border-amber-300/30 flex items-center justify-center gap-2 bg-gradient-to-br from-amber-100 to-amber-200 text-amber-800 dark:from-amber-900/30 dark:to-amber-800/30 dark:text-amber-200">
              <span className="text-base">⚠️</span>
              {currentTab === 'classes'
                ? 'Select a version from the canvas to manage classes'
                : 'Select a project from the canvas to manage properties'}
            </div>
          )}

          <Tabs.Content value="classes" className="flex flex-col flex-1 min-h-0 mt-0 data-[state=inactive]:hidden">
            <div className="relative flex flex-col h-full">
              {/* Search Bar */}
              <div className="p-4 pb-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search classes..."
                    value={classesSearchQuery}
                    onChange={(e) => setClassesSearchQuery(e.target.value)}
                    className={['w-full pl-9 pr-3 rounded-lg text-sm border focus:bg-white dark:focus:bg-slate-800', tokens.inputPaddingY, sidebarTheme.inputBase].join(' ')}
                  />
                </div>
              </div>

              {/* Classes List */}
              <div className="flex-1 overflow-auto px-2 py-1">
                {filteredClasses.length === 0 ? (
                  <div className="text-center mt-8 px-4">
                    <div className="w-12 h-12 rounded-full bg-indigo-500/10 flex items-center justify-center mx-auto mb-4">
                      <Plus className="w-6 h-6 text-indigo-500" />
                    </div>
                    <p className="text-sm font-medium mb-1" style={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                      {classes.length === 0 ? 'No classes yet' : 'No classes match your search'}
                    </p>
                    {classes.length === 0 && (
                      <p className="text-xs" style={{ color: isDark ? '#64748b' : '#94a3b8' }}>
                        Click the + button to add one
                      </p>
                    )}
                  </div>
                ) : (
                  <ul className="py-1 space-y-1 list-none p-0 m-0">
                    {filteredClasses.map((classItem) => {
                      const isHidden = hiddenClassIds.includes(classItem.id);
                      return (
                      <li key={classItem.id} className={['mb-1 flex items-stretch rounded-lg group', tokens.rowText].join(' ')}>
                        <button
                          type="button"
                          onClick={() => handleClassSelect(classItem)}
                          className={`flex-1 text-left rounded-lg transition-all min-w-0 ${tokens.rowPaddingX} ${tokens.rowPaddingY} ${
                            selectedClassId === classItem.id
                              ? 'bg-indigo-500/10 border-l-[3px] border-indigo-500 hover:bg-indigo-500/15'
                              : 'hover:bg-indigo-500/5 border-l-[3px] border-transparent'
                          } ${isHidden ? 'opacity-60' : ''}`}
                        >
                          <span className="flex items-center gap-1.5 min-w-0">
                            <span
                              className="truncate block"
                              style={{
                                textDecoration: classItem.schema?.deprecated ? 'line-through' : 'none',
                                color: classItem.schema?.deprecated ? '#9ca3af' : 'inherit',
                              }}
                            >
                              {classItem.name}
                            </span>
                            {classWarnings[classItem.id] && (
                              <span title="This class has properties referencing missing classes" className="text-red-700 text-xs">⚠️</span>
                            )}
                          </span>
                          {classItem.description && (
                            <span className="block text-xs truncate mt-0.5 text-slate-500 dark:text-slate-400">{classItem.description}</span>
                          )}
                          {isHidden && (
                            <span className="block text-[10px] mt-0.5 text-slate-500 dark:text-slate-400">Hidden on canvas</span>
                          )}
                        </button>
                        <div className="flex items-center gap-0.5 opacity-60 group-hover:opacity-100">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); callbacks.onClassVisibilityToggle?.(classItem.id, isHidden); }}
                            title={isHidden ? 'Show class on canvas' : 'Hide class on canvas'}
                            className="p-1.5 rounded hover:bg-slate-500/10 hover:text-slate-600 dark:hover:text-slate-300"
                          >
                            {isHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                          </button>
                          <button
                            type="button"
                            disabled={!selectedVersionId || isReadOnly}
                            onClick={(e) => { e.stopPropagation(); callbacks.onClassEdit?.(classItem); }}
                            title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Edit class'}
                            className="p-1.5 rounded hover:bg-indigo-500/10 hover:text-indigo-500 disabled:opacity-50 disabled:pointer-events-none"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            disabled={!selectedVersionId || isReadOnly}
                            onClick={(e) => { e.stopPropagation(); callbacks.onClassDelete?.(classItem.id); }}
                            title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Delete class'}
                            className="p-1.5 rounded hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50 disabled:pointer-events-none"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </li>
                      );
                    })}
                  </ul>
                )}
              </div>

            </div>
          </Tabs.Content>
          <Tabs.Content value="properties" className="flex flex-col flex-1 min-h-0 mt-0 data-[state=inactive]:hidden">
            <div className="relative flex flex-col h-full">
              {/* Search Bar */}
              <div className="p-4 pb-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search properties..."
                    value={propertiesSearchQuery}
                    onChange={(e) => setPropertiesSearchQuery(e.target.value)}
                    className={['w-full pl-9 pr-3 rounded-lg text-sm border focus:bg-white dark:focus:bg-slate-800', tokens.inputPaddingY, sidebarTheme.inputBase].join(' ')}
                  />
                </div>
              </div>

              {/* New Reference draggable */}
              {!isReadOnly && (
                <div className="px-4 pb-3">
                  <div
                    role="button"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = 'copy';
                      e.dataTransfer.setData('application/json', JSON.stringify({ type: 'new-reference' }));
                    }}
                    className={['flex items-center justify-between rounded-lg border-2 border-dashed border-green-500/40 bg-green-500/10 cursor-grab hover:border-green-500 hover:bg-green-500/15 hover:-translate-y-px hover:shadow-lg hover:shadow-green-500/20 active:cursor-grabbing active:scale-[0.98] transition-all', tokens.rowPaddingX, tokens.rowPaddingY].join(' ')}
                    title="Drag to create a new reference on a class or inside an object"
                  >
                    <span className="text-sm font-semibold text-green-700 dark:text-green-400">+ New Reference</span>
                    <span className="text-xs text-green-600 dark:text-green-500">drag to class</span>
                  </div>
                </div>
              )}

              {/* Properties List */}
              <div className="flex-1 overflow-auto px-2 py-1">
                {filteredProperties.length === 0 ? (
                  <div className="text-center mt-8 px-4">
                    <div className="w-12 h-12 rounded-full bg-indigo-500/10 flex items-center justify-center mx-auto mb-4">
                      <Plus className="w-6 h-6 text-indigo-500" />
                    </div>
                    <p className="text-sm font-medium mb-1" style={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                      {properties.length === 0 ? 'No properties yet' : 'No properties match your search'}
                    </p>
                    {properties.length === 0 && (
                      <p className="text-xs" style={{ color: isDark ? '#64748b' : '#94a3b8' }}>
                        Click the + button to add one
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="py-1">
                    {filteredProperties.map((propertyItem) => {
                      const hasChildren = hasInlineProperties(propertyItem);
                      const isExpanded = expandedPropertyIds.has(propertyItem.id);
                      const inlineProps = hasChildren ? getInlineProperties(propertyItem) : [];

                      return (
                        <React.Fragment key={propertyItem.id}>
                          <div
                            draggable={!isReadOnly}
                            onDragStart={(e) => {
                              if (isReadOnly) { e.preventDefault(); return; }
                              e.dataTransfer.effectAllowed = 'copy';
                              e.dataTransfer.setData('application/json', JSON.stringify({ type: 'property', property: propertyItem }));
                            }}
                            onClick={() => handlePropertySelect(propertyItem)}
                            className={`flex items-center gap-2 ${tokens.rowPaddingX} ${tokens.rowPaddingY} mb-1 mx-1 rounded-lg transition-all ${tokens.rowText} cursor-${isReadOnly ? 'default' : 'grab'} active:cursor-grabbing active:scale-[0.98] ${
                              selectedPropertyId === propertyItem.id ? 'bg-indigo-500/10 border-l-[3px] border-indigo-500 hover:bg-indigo-500/15' : 'border-l-[3px] border-transparent hover:bg-indigo-500/5 hover:translate-x-0.5'
                            }`}
                          >
                            {hasChildren ? (
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); togglePropertyExpanded(propertyItem.id); }}
                                title={isExpanded ? 'Collapse nested properties' : 'Expand nested properties'}
                                className="p-1 rounded text-slate-500 hover:text-indigo-500 hover:bg-indigo-500/10"
                              >
                                {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                              </button>
                            ) : (
                              <div className="w-6" />
                            )}
                            <div className="flex-1 min-w-0">
                              <p
                                className="text-sm font-semibold truncate"
                                style={{
                                  textDecoration: propertyItem.deprecated ? 'line-through' : 'none',
                                  color: propertyItem.deprecated ? '#94a3b8' : (isDark ? '#e2e8f0' : '#334155'),
                                }}
                                title={propertyItem.deprecated ? ((propertyItem as any).deprecationMessage || 'Deprecated') : undefined}
                              >
                                <span className="flex items-center gap-2">
                                  <span className="truncate">{propertyItem.name}</span>
                                  {hasChildren && (
                                    <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-500 flex-shrink-0">
                                      {inlineProps.length}
                                    </span>
                                  )}
                                  {propertyItem.enum && Array.isArray(propertyItem.enum) && propertyItem.enum.length > 0 && (
                                    <span title={`Enumeration: ${propertyItem.enum.join(', ')}`} className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-indigo-700 dark:text-indigo-300 uppercase tracking-wide flex-shrink-0">
                                      ENUM
                                    </span>
                                  )}
                                </span>
                              </p>
                              <p className="text-xs truncate mt-0.5 text-slate-500 dark:text-slate-400">
                                {propertyItem.type && (Array.isArray(propertyItem.type) ? `${propertyItem.type[0]}${propertyItem.type[1] === 'null' ? ' [nullable]' : ''}` : propertyItem.type) || propertyItem.description}
                              </p>
                            </div>
                            <div className="flex gap-0.5 opacity-60 hover:opacity-100">
                              <button
                                type="button"
                                disabled={!selectedProjectId || isReadOnly}
                                onClick={(e) => { e.stopPropagation(); callbacks.onPropertyEdit?.(propertyItem); }}
                                title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Edit property'}
                                className="p-1.5 rounded hover:bg-indigo-500/10 hover:text-indigo-500 disabled:opacity-50 disabled:pointer-events-none"
                              >
                                <Pencil className="w-4 h-4" />
                              </button>
                              <button
                                type="button"
                                disabled={!selectedProjectId || isReadOnly}
                                onClick={(e) => { e.stopPropagation(); callbacks.onPropertyDelete?.(propertyItem.id); }}
                                title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Delete property'}
                                className="p-1.5 rounded hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50 disabled:pointer-events-none"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>

                          {/* Nested Properties (shown when expanded) */}
                          {hasChildren && isExpanded && (
                            <div
                              className="ml-4 mr-2 mb-2 pl-4 rounded-r-lg border-l-2 border-indigo-500/30 bg-indigo-500/5"
                            >
                              <span className="block text-[10px] font-semibold uppercase tracking-wider py-2 px-2 text-indigo-400 dark:text-indigo-300">
                                Nested Properties
                              </span>
                              {inlineProps.map((child, idx) => (
                                <div
                                  key={`${propertyItem.id}-${child.name}-${idx}`}
                                  className="flex items-center gap-2 py-2 px-2 rounded hover:bg-white/5 dark:hover:bg-white/5"
                                >
                                  <div className="flex-1 min-w-0">
                                    <p className="text-xs font-medium text-slate-800 dark:text-slate-200 truncate flex items-center gap-1">
                                      {child.required && <span className="text-red-500 font-bold">*</span>}
                                      {child.name}
                                    </p>
                                    <p className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
                                      {child.type}{child.description ? ` — ${child.description}` : ''}
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>
                )}
              </div>

            </div>
          </Tabs.Content>

          <Tabs.Content value="groups" className="flex flex-col flex-1 min-h-0 mt-0 data-[state=inactive]:hidden">
            <div className="relative flex flex-col h-full">
              {/* Search Bar */}
              <div className="p-4 pb-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search groups..."
                    value={groupsSearchQuery}
                    onChange={(e) => setGroupsSearchQuery(e.target.value)}
                    className={['w-full pl-9 pr-3 rounded-lg text-sm border focus:bg-white dark:focus:bg-slate-800', tokens.inputPaddingY, sidebarTheme.inputBase].join(' ')}
                  />
                </div>
              </div>

              {/* New Group draggable */}
              {!isReadOnly && selectedVersionId && (
                <div className="px-4 pb-3">
                  <div
                    role="button"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = 'copy';
                      e.dataTransfer.setData('application/json', JSON.stringify({ type: 'new-group' }));
                      e.dataTransfer.setData('application/x-apiome-drag-type', 'new-group');
                    }}
                    className={['flex items-center justify-between rounded-lg border-2 border-dashed border-violet-500/40 bg-violet-500/10 cursor-grab hover:border-violet-500 hover:bg-violet-500/15 hover:-translate-y-px hover:shadow-lg hover:shadow-violet-500/20 active:cursor-grabbing active:scale-[0.98] transition-all', tokens.rowPaddingX, tokens.rowPaddingY].join(' ')}
                    title="Drag to create a new group on the canvas"
                  >
                    <span className="text-sm font-semibold text-violet-600 dark:text-violet-400">+ New Group</span>
                    <span className="text-xs text-violet-500 dark:text-violet-400">drag to canvas</span>
                  </div>
                </div>
              )}

              {/* Groups List */}
              <div className="flex-1 overflow-auto px-2 py-1">
                {filteredGroups.length === 0 ? (
                  <div className="text-center mt-6 px-4">
                    <p className="text-sm font-medium mb-1" style={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                      {groups.length === 0 ? 'No groups yet' : 'No groups match your search'}
                    </p>
                    {groups.length === 0 && (
                      <p className="text-xs block" style={{ color: isDark ? '#64748b' : '#94a3b8' }}>
                        Drag &quot;+ New Group&quot; above onto the canvas to create one
                      </p>
                    )}
                  </div>
                ) : (
                  <ul className="py-1 space-y-1 list-none p-0 m-0">
                    {filteredGroups.map((group) => {
                      const nodeCount = group.nodeIds?.length ?? 0;
                      const isGroupExpanded = expandedGroupIds.has(group.id);
                      return (
                        <li key={group.id} className="mb-1 rounded-lg group">
                          <div className="flex flex-col rounded-lg">
                            <div className="flex items-stretch">
                              <button
                                type="button"
                                data-testid={`group-expand-${group.id}`}
                                aria-expanded={isGroupExpanded}
                                aria-label={isGroupExpanded ? 'Collapse group' : 'Expand group'}
                                title={isGroupExpanded ? 'Collapse group' : 'Expand group'}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleGroupExpanded(group.id);
                                }}
                                className="shrink-0 flex w-8 items-center justify-center rounded-l-lg text-slate-500 hover:bg-violet-500/10 hover:text-violet-600 dark:hover:text-violet-400"
                              >
                                {isGroupExpanded ? (
                                  <ChevronDown className="h-4 w-4" aria-hidden />
                                ) : (
                                  <ChevronRight className="h-4 w-4" aria-hidden />
                                )}
                              </button>
                              <button
                                type="button"
                                onClick={() => callbacks.onGroupSelect?.(group.id)}
                                className={['flex min-w-0 flex-1 items-center gap-3 rounded-r-lg text-left transition-all hover:bg-violet-500/5', tokens.rowPaddingY, tokens.rowPaddingX, tokens.rowText].join(' ')}
                              >
                                <span
                                  className="h-3 w-3 shrink-0 rounded"
                                  style={{ backgroundColor: group.color || '#8b5cf6' }}
                                />
                                <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
                                  <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                                    {group.name}
                                  </span>
                                  <span className="shrink-0 text-xs text-slate-500 tabular-nums dark:text-slate-400">
                                    ({nodeCount})
                                  </span>
                                </div>
                              </button>
                              {!isReadOnly && (
                                <div
                                  className={`flex items-center ${
                                    suppressGroupDestructiveActions
                                      ? 'pointer-events-none opacity-30'
                                      : 'opacity-60 group-hover:opacity-100'
                                  }`}
                                >
                                  {nodeCount > 0 && (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        callbacks.onGroupDeleteAllClasses?.(group.id);
                                      }}
                                      title="Delete all classes in group"
                                      className="rounded p-1.5 hover:bg-amber-500/10 hover:text-amber-500"
                                    >
                                      <FileX className="h-4 w-4" />
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      callbacks.onGroupDelete?.(group.id);
                                    }}
                                    title="Delete group"
                                    className="rounded p-1.5 hover:bg-red-500/10 hover:text-red-500"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </button>
                                </div>
                              )}
                            </div>
                            {isGroupExpanded && (
                              <ul className="ml-8 mr-2 mb-2 mt-0.5 list-none space-y-0.5 border-l border-slate-200 py-0.5 pl-2 dark:border-slate-600">
                                {nodeCount === 0 ? (
                                  <li className="px-1 py-0.5 text-xs italic text-slate-500 dark:text-slate-400">
                                    No classes in this group
                                  </li>
                                ) : (
                                  group.nodeIds.map((nodeId) => {
                                    const classItem = classes.find((c) => c.id === nodeId);
                                    const label = classItem?.name ?? nodeId;
                                    return (
                                      <li key={nodeId}>
                                        <button
                                          type="button"
                                          data-testid={`group-class-${group.id}-${nodeId}`}
                                          onClick={() => {
                                            if (classItem) {
                                              handleClassSelect(classItem);
                                            }
                                          }}
                                          disabled={!classItem}
                                          title={classItem ? `Focus ${classItem.name}` : 'Unknown class'}
                                          className="w-full truncate rounded px-1 py-0.5 text-left text-xs text-slate-600 hover:bg-violet-500/10 disabled:cursor-default disabled:opacity-60 dark:text-slate-300"
                                        >
                                          {label}
                                        </button>
                                      </li>
                                    );
                                  })
                                )}
                              </ul>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          </Tabs.Content>
          <div className={['border-t px-3 py-2 flex items-center justify-between gap-2', sidebarTheme.borderSoft].join(' ')}>
            <SidebarDensityToggle />
            {currentTab === 'classes' && (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => callbacks.onClassImport?.()}
                  disabled={!selectedVersionId || isReadOnly}
                  aria-label="Import classes"
                  title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot import to published version' : 'Import classes from file'}
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-emerald-500 to-emerald-600 text-white hover:shadow-emerald-500/40"
                >
                  <Upload className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => callbacks.onClassTemplates?.()}
                  disabled={!selectedVersionId || isReadOnly}
                  aria-label="Class templates"
                  title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Browse class templates'}
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-amber-500 to-amber-600 text-white hover:shadow-amber-500/40"
                >
                  <Library className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => callbacks.onClassAdd?.()}
                  disabled={!selectedVersionId || isReadOnly}
                  aria-label="Add class"
                  title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Add class'}
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-indigo-500 to-purple-600 text-white hover:shadow-indigo-500/40"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            )}
            {currentTab === 'properties' && (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => callbacks.onPropertyTemplates?.()}
                  disabled={!selectedProjectId || isReadOnly}
                  aria-label="Browse property templates"
                  title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Browse property templates'}
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-emerald-500 to-emerald-600 text-white hover:shadow-emerald-500/40"
                >
                  <Library className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  data-testid="studio-sidebar-ai-property-suggestions"
                  onClick={() => callbacks.onPropertyAiSuggest?.()}
                  disabled={!selectedProjectId || isReadOnly}
                  aria-label="Suggest properties with AI"
                  title={
                    !selectedProjectId
                      ? 'Select a project first'
                      : isReadOnly
                        ? 'Cannot edit published version'
                        : 'Suggest reusable properties with AI'
                  }
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-violet-500 to-purple-600 text-white hover:shadow-violet-500/40"
                >
                  <Bot className="w-4 h-4" aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => callbacks.onPropertyAdd?.()}
                  disabled={!selectedProjectId || isReadOnly}
                  aria-label="Add property"
                  title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Add property'}
                  className="w-8 h-8 rounded-full flex items-center justify-center shadow-sm transition-all hover:-translate-y-0.5 hover:scale-105 disabled:opacity-50 disabled:pointer-events-none disabled:transform-none bg-gradient-to-br from-indigo-500 to-purple-600 text-white hover:shadow-indigo-500/40"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      </Tabs.Root>
    </aside>
  );
};

export default StudioSideNav;

'use client';

import React, { useState, useEffect } from 'react';
import { Plus, Pencil, Trash2, AlertTriangle, FileUp, ChevronRight, ChevronDown, Route, Search, Boxes, ListTree, ShieldCheck, Server, Zap } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import * as Tabs from '@radix-ui/react-tabs';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getClassesWithPropertiesAndTags,
} from '../../../../../../lib/db/helper';
import SecuritySchemesPanel from './SecuritySchemesPanel';
import ServersPanel from './ServersPanel';
import {
  getPathsForVersion as getPathsForVersionRest,
  createPath as createPathRest,
  updatePath as updatePathRest,
  deletePath as deletePathRest,
  createOperation as createOperationRest,
  getOperationsForPath,
  type OperationData,
} from '../../../../../../lib/api/paths-client';
import { getSharedPathParameters } from '../../../../../../lib/db/helper-shared-path-parameters';
import { getPathSaveValidationError, isValidPath } from '../../../../../../lib/utils/path-params';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { AVAILABLE_OPERATIONS, OPERATION_COLORS } from './paths-operation-colors';
import type { ParameterLocation } from './paths-theme';
import { parseOpenAPISpec } from '../../../../utils/openapi-import';
import { importPathsFromOpenAPIForVersion } from '../../../../../../lib/db/import-openapi-paths-security';
import SidebarShell, { SidebarSectionLabel } from '../../../../components/sidebar/SidebarShell';
import SidebarDensityToggle from '../../../../components/sidebar/SidebarDensityToggle';
import { sidebarTheme, useSidebarTokens } from '../../../../components/sidebar/sidebar-theme';

/**
 * Draggable parameter chips shown in the Operations tab. Dropping one onto an
 * operation node creates a shared path parameter and links it to that
 * operation; the user can rename and fine-tune in the Parameter Properties
 * panel. `dot` is a Tailwind bg class that matches the location role color in
 * `PARAM_LOCATION_CHIP` for visual consistency across the Paths surface.
 */
const PARAMETER_CHIPS: {
  inLocation: ParameterLocation;
  label: string;
  suggestedName: string;
  dot: string;
  hint: string;
}[] = [
  {
    inLocation: 'query',
    label: 'Query',
    suggestedName: 'q',
    dot: 'bg-sky-500 dark:bg-sky-400',
    hint: 'Querystring parameter (e.g. ?page=1). Drop onto an operation.',
  },
  {
    inLocation: 'path',
    label: 'Path',
    suggestedName: 'id',
    dot: 'bg-indigo-500 dark:bg-indigo-400',
    hint: 'Path parameter. Typically derived from /{placeholder} in the pathname — drop onto an operation to add one manually.',
  },
  {
    inLocation: 'header',
    label: 'Header',
    suggestedName: 'Authorization',
    dot: 'bg-violet-500 dark:bg-violet-400',
    hint: 'Header parameter (e.g. Authorization, X-Request-ID). Drop onto an operation.',
  },
  {
    inLocation: 'cookie',
    label: 'Cookie',
    suggestedName: 'session',
    dot: 'bg-amber-500 dark:bg-amber-400',
    hint: 'Cookie parameter (e.g. session). Drop onto an operation. Browser cookie rules may differ from the exported spec.',
  },
];

interface ClassItem {
  id: string;
  name: string;
}

interface PropertyItem {
  id: string;
  name: string;
  description?: string;
  data?: Record<string, any>; // Contains type, constraints, format, enum values, etc.
}

interface PathItem {
  id: string;
  version_id: string;
  pathname: string;
  metadata?: any;
  created_at: string;
  updated_at: string;
}

export default function PathsSidebar({
  activeTab,
  onTabChange,
  selectedPathId,
  onPathSelect,
  onOperationFocus,
  onSecurityRefresh,
}: {
  activeTab: 'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers';
  onTabChange: (tab: 'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers') => void;
  selectedPathId: string | null;
  onPathSelect: (pathId: string | null, pathname?: string) => void;
  /** Select path, open operation panel, and zoom the Paths canvas to this operation. */
  onOperationFocus?: (pathId: string, pathname: string, operation: { id: string; operation: string }) => void;
  onSecurityRefresh?: () => void;
}) {
  const { selectedVersionId, selectedProjectId } = useStudio();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const isDark = useDarkMode();
  const tokens = useSidebarTokens();
  const [paths, setPaths] = useState<PathItem[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [properties, setProperties] = useState<PropertyItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [pathSearch, setPathSearch] = useState('');
  const [classSearch, setClassSearch] = useState('');
  const [propertySearch, setPropertySearch] = useState('');

  // Dialog state for adding/editing paths
  const [pathDialogOpen, setPathDialogOpen] = useState(false);
  const [editingPath, setEditingPath] = useState<PathItem | null>(null);
  const [pathNameInput, setPathNameInput] = useState('');
  const [autoCreateCrud, setAutoCreateCrud] = useState(false);

  // Import from OpenAPI dialog (#566)
  const [importOpenAPIOpen, setImportOpenAPIOpen] = useState(false);
  const [importOpenAPIContent, setImportOpenAPIContent] = useState('');
  const [importOpenAPIError, setImportOpenAPIError] = useState('');
  const [importOpenAPILoading, setImportOpenAPILoading] = useState(false);

  /** Paths tab: which path rows are expanded to show operations. */
  const [expandedPathIds, setExpandedPathIds] = useState<Record<string, boolean>>({});
  const [operationsByPathId, setOperationsByPathId] = useState<Record<string, OperationData[]>>({});
  const [operationsLoadingPathId, setOperationsLoadingPathId] = useState<string | null>(null);

  const togglePathExpanded = React.useCallback(
    (pathId: string) => {
      setExpandedPathIds((prev) => {
        const willOpen = !prev[pathId];
        if (willOpen && selectedVersionId) {
          void (async () => {
            setOperationsLoadingPathId(pathId);
            try {
              const res = await getOperationsForPath(selectedVersionId, pathId);
              if (res.success && res.data) {
                setOperationsByPathId((p) => ({ ...p, [pathId]: res.data! }));
              } else {
                setOperationsByPathId((p) => ({ ...p, [pathId]: [] }));
              }
            } catch {
              setOperationsByPathId((p) => ({ ...p, [pathId]: [] }));
            } finally {
              setOperationsLoadingPathId((cur) => (cur === pathId ? null : cur));
            }
          })();
        }
        return { ...prev, [pathId]: willOpen };
      });
    },
    [selectedVersionId]
  );

  // Load paths
  useEffect(() => {
    if (!selectedVersionId) {
      setPaths([]);
      return;
    }

    const loadPaths = async () => {
      setIsLoading(true);
      try {
        const result = await getPathsForVersionRest(selectedVersionId);
        if (result.success && result.data) {
          setPaths(result.data as PathItem[]);
        } else {
          console.error('Error loading paths:', result.error);
        }
      } catch (error) {
        console.error('Error loading paths:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadPaths();
  }, [selectedVersionId]);

  useEffect(() => {
    setExpandedPathIds({});
    setOperationsByPathId({});
    setOperationsLoadingPathId(null);
  }, [selectedVersionId]);

  // Load classes and properties
  useEffect(() => {
    if (!selectedVersionId) {
      setClasses([]);
      return;
    }

    const loadClasses = async () => {
      setIsLoading(true);
      try {
        const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId);
        const classesData: any[] = JSON.parse(classesResponse as string);

        // Extract unique classes
        const uniqueClasses = classesData.reduce((acc: ClassItem[], cls: any) => {
          if (!acc.find((c) => c.id === cls.id)) {
            acc.push({ id: cls.id, name: cls.name });
          }
          return acc;
        }, []);

        setClasses(uniqueClasses);
      } catch (error) {
        console.error('Error loading classes:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadClasses();
  }, [selectedVersionId]);

  // Load properties separately using REST API
  useEffect(() => {
    if (!selectedProjectId) {
      setProperties([]);
      return;
    }

    const loadProperties = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`/api/properties/${selectedProjectId}`);
        const result = await response.json();
        if (!result.success) {
          throw new Error(result.error || 'Failed to load properties');
        }
        const data = result.properties || [];

        // Transform to PropertyItem format
        const transformedProperties: PropertyItem[] = data.map((prop: any) => {
          // Parse data if it's a string
          let propData = prop.data;
          if (typeof propData === 'string') {
            try {
              propData = JSON.parse(propData);
            } catch {
              propData = { type: 'string' };
            }
          }

          return {
            id: prop.id,
            name: prop.name,
            description: prop.description || undefined,
            data: propData || { type: 'string' },
          };
        });

        // Sort properties A-Z by name
        const sortedProperties = transformedProperties.sort((a, b) =>
          a.name.localeCompare(b.name)
        );

        setProperties(sortedProperties);
      } catch (error) {
        console.error('Error loading properties:', error);
        setProperties([]);
      } finally {
        setIsLoading(false);
      }
    };

    loadProperties();
  }, [selectedProjectId]);

  // Handle opening add path dialog
  const handleAddPath = () => {
    setEditingPath(null);
    setPathNameInput('');
    setAutoCreateCrud(false);
    setPathDialogOpen(true);
  };

  // Handle opening edit path dialog
  const handleEditPath = (path: PathItem) => {
    setEditingPath(path);
    setPathNameInput(path.pathname);
    setPathDialogOpen(true);
  };

  // Handle saving path (create or update)
  const handleSavePath = async () => {
    if (!selectedVersionId || !pathNameInput.trim()) return;

    const trimmedPath = pathNameInput.trim();
    let paramsForCoverage: { name: string; in_location: string }[] = [];
    if (editingPath) {
      const paramsRaw = await getSharedPathParameters(editingPath.id);
      const paramsParsed = JSON.parse(paramsRaw) as {
        success?: boolean;
        parameters?: { name: string; in_location: string }[];
      };
      if (paramsParsed.success && paramsParsed.parameters) {
        paramsForCoverage = paramsParsed.parameters;
      }
    }
    const validationError = getPathSaveValidationError(trimmedPath, paramsForCoverage, {
      enforceCoverage: Boolean(editingPath),
    });
    if (validationError) {
      await alertDialog({
        title: editingPath ? 'Path parameters do not match template' : 'Invalid path template',
        message: validationError,
        variant: 'warning',
      });
      return;
    }

    try {
      if (editingPath) {
        // Update existing path
        const result = await updatePathRest(selectedVersionId, editingPath.id, { pathname: trimmedPath });
        if (result.success && result.data) {
          const updatedPath = result.data as PathItem;
          setPaths(prevPaths =>
            prevPaths.map(p => p.id === updatedPath.id ? updatedPath : p)
          );
        } else {
          throw new Error(result.error || 'Failed to update path');
        }
      } else {
        // Create new path
        const result = await createPathRest(selectedVersionId, trimmedPath);
        if (result.success && result.data) {
          const newPath = result.data as PathItem;
          setPaths(prevPaths => [...prevPaths, newPath].sort((a, b) => a.pathname.localeCompare(b.pathname)));

          // Auto-create CRUD operations if checkbox is selected
          if (autoCreateCrud) {
            const crudOperations = ['GET', 'POST', 'PUT', 'DELETE'];
            for (const operation of crudOperations) {
              try {
                await createOperationRest(selectedVersionId, newPath.id, operation);
              } catch (opError) {
                console.error(`Error creating ${operation} operation:`, opError);
              }
            }
          }
        } else {
          throw new Error(result.error || 'Failed to create path');
        }
      }
      setPathDialogOpen(false);
      setPathNameInput('');
      setEditingPath(null);
      setAutoCreateCrud(false);
    } catch (error) {
      console.error('Error saving path:', error);
      await alertDialog({
        title: 'Error',
        message: 'Error saving path. Please try again.',
        variant: 'error',
      });
    }
  };

  // Handle deleting a path
  const handleDeletePath = async (path: PathItem) => {
    if (!selectedVersionId) return;

    const confirmed = await confirmDialog({
      title: 'Delete Path',
      message: `Deleting a path will also delete all of the associated actions and all of the associated schemas for responses and requests. Are you sure you want to delete "${path.pathname}"?`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deletePathRest(selectedVersionId, path.id);
      if (result.success) {
        setPaths(prevPaths => prevPaths.filter(p => p.id !== path.id));
        if (selectedPathId === path.id) {
          // Clear canvas/panels when deleting the currently selected path.
          onPathSelect(null);
        }
      } else {
        throw new Error(result.error || 'Failed to delete path');
      }
    } catch (error) {
      console.error('Error deleting path:', error);
      await alertDialog({
        title: 'Error',
        message: 'Error deleting path. Please try again.',
        variant: 'error',
      });
    }
  };

  // Handle dragging an operation to the canvas
  const handleOperationDragStart = (event: React.DragEvent, operation: typeof AVAILABLE_OPERATIONS[0]) => {
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData('application/json', JSON.stringify({
      type: 'operation',
      operation: operation.id,
      color: operation.color,
      label: operation.label,
    }));
  };

  // Handle dragging a parameter chip to the canvas. The drop target (operation
  // node) wires the parameter up server-side; suggestedName is a sensible
  // default that the Parameter Properties panel lets the user rename.
  const handleParameterDragStart = (
    event: React.DragEvent,
    chip: typeof PARAMETER_CHIPS[0],
  ) => {
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData('application/json', JSON.stringify({
      type: 'parameter',
      inLocation: chip.inLocation,
      suggestedName: chip.suggestedName,
    }));
  };

  const handleTabChange = (value: string) => {
    onTabChange(value as 'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers');
  };

  const handleImportFromOpenAPI = () => {
    setImportOpenAPIError('');
    setImportOpenAPIContent('');
    setImportOpenAPIOpen(true);
  };

  const handleImportOpenAPIFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith('.json') && !name.endsWith('.yaml') && !name.endsWith('.yml')) {
      setImportOpenAPIError('Please choose a JSON or YAML file.');
      return;
    }
    setImportOpenAPIError('');
    try {
      const text = await file.text();
      setImportOpenAPIContent(text);
    } catch (err: unknown) {
      setImportOpenAPIError(err instanceof Error ? err.message : 'Failed to read file.');
    }
    e.target.value = '';
  };

  const handleImportOpenAPISubmit = async () => {
    if (!selectedVersionId) {
      setImportOpenAPIError('No version selected.');
      return;
    }
    const content = importOpenAPIContent.trim();
    if (!content) {
      setImportOpenAPIError('Paste or upload an OpenAPI spec (JSON or YAML).');
      return;
    }
    setImportOpenAPIError('');
    setImportOpenAPILoading(true);
    try {
      const parseResult = parseOpenAPISpec(content);
      if (!parseResult.success) {
        setImportOpenAPIError(parseResult.error || 'Failed to parse OpenAPI specification.');
        return;
      }
      const paths = parseResult.paths ?? [];
      const securitySchemes = parseResult.securitySchemes ?? [];
      if (!paths.length && !securitySchemes.length) {
        setImportOpenAPIError('Spec has no paths or security schemes to import.');
        return;
      }
      const result = await importPathsFromOpenAPIForVersion(selectedVersionId, paths, securitySchemes);
      if (!result.success) {
        setImportOpenAPIError(result.error || 'Import failed.');
        return;
      }
      setImportOpenAPIOpen(false);
      setImportOpenAPIContent('');
      const listResult = await getPathsForVersionRest(selectedVersionId);
      if (listResult.success && listResult.data) {
        setPaths(listResult.data as PathItem[]);
      }
      onSecurityRefresh?.();
    } catch (err: unknown) {
      setImportOpenAPIError(err instanceof Error ? err.message : 'Import failed.');
    } finally {
      setImportOpenAPILoading(false);
    }
  };

  /**
   * Sections rendered as a vertical activity rail (VSCode/Cursor style).
   * Order = top-to-bottom in the rail. Each Lucide icon was picked to read
   * at 16px without a label since the tooltip carries the long-form name.
   */
  const TAB_OPTIONS: { value: typeof activeTab; label: string; Icon: React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }> }[] = [
    { value: 'paths', label: 'Paths', Icon: Route },
    { value: 'operations', label: 'Operations', Icon: Zap },
    { value: 'classes', label: 'Classes', Icon: Boxes },
    { value: 'properties', label: 'Properties', Icon: ListTree },
    { value: 'security', label: 'Security', Icon: ShieldCheck },
    { value: 'servers', label: 'Servers', Icon: Server },
  ];

  const activeTabLabel = TAB_OPTIONS.find((opt) => opt.value === activeTab)?.label ?? 'Section';

  /** VSCode-style trigger: indigo accent bar on the left when active. */
  const railTriggerClass = [
    'relative flex items-center justify-center w-9 h-9 rounded-md transition-colors',
    'text-slate-500 dark:text-slate-400 hover:text-indigo-500 hover:bg-indigo-500/5',
    'data-[state=active]:text-indigo-500 data-[state=active]:bg-indigo-500/10',
    'before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[2px] before:rounded-r',
    'before:bg-transparent data-[state=active]:before:bg-indigo-500',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
  ].join(' ');

  return (
    <Tabs.Root
      value={activeTab}
      onValueChange={handleTabChange}
      orientation="vertical"
      className="contents"
    >
      <SidebarShell
      icon={<Route />}
      title="API Designer"
      subtitle={activeTabLabel}
      width={280}
      bodyScroll={activeTab !== 'properties'}
      rail={
        <Tabs.List
          aria-label="API Designer sections"
          className="flex flex-col items-center gap-0.5 py-1.5"
        >
          {TAB_OPTIONS.map(({ value, label, Icon }) => (
            <Tabs.Trigger
              key={value}
              value={value}
              aria-label={label}
              title={label}
              className={railTriggerClass}
            >
              <Icon className="w-4 h-4" aria-hidden />
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      }
      footer={
        <div className="flex items-center justify-between gap-2">
          <SidebarDensityToggle />
          {activeTab === 'paths' && (
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleImportFromOpenAPI}
                className={[
                  'flex items-center gap-1.5 rounded-md text-[12px] font-medium transition-colors',
                  'px-2.5 py-1.5 border',
                  isDark
                    ? 'text-slate-200 bg-slate-900 hover:bg-slate-800 border-slate-700'
                    : 'text-slate-700 bg-white hover:bg-slate-50 border-slate-200',
                ].join(' ')}
                aria-label="Import from OpenAPI"
                title="Import paths from an OpenAPI specification"
              >
                <FileUp className="w-3.5 h-3.5" />
                Import
              </button>
              <button
                type="button"
                onClick={handleAddPath}
                className="flex items-center justify-center w-8 h-8 rounded-md text-white transition-colors bg-indigo-600 hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:ring-offset-2 dark:focus:ring-offset-slate-950"
                aria-label="Add path"
                title="Add a new path"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      }
    >
        {/* Content Area */}
        <div
          className={`flex-1 ${tokens.sectionPadding} flex flex-col ${activeTab === 'properties' ? 'overflow-hidden' : ''}`}
        >
          {isLoading ? (
            <div className="flex justify-center py-8">
              <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
            </div>
          ) : (
            <>
              {/* Operations Tab Content */}
              {activeTab === 'operations' && (
                <div className="flex flex-col gap-5">
                  <div className="flex flex-col gap-3">
                    <SidebarSectionLabel>HTTP Operations</SidebarSectionLabel>
                    <p className={['text-[11px] -mt-1 px-1', sidebarTheme.textSecondary].join(' ')}>
                      Drag any operation onto a path on the canvas to attach it.
                    </p>
                    <div className={['flex flex-col', tokens.rowGap].join(' ')}>
                      {AVAILABLE_OPERATIONS.map((operation) => (
                        <div
                          key={operation.id}
                          draggable
                          onDragStart={(e) => handleOperationDragStart(e, operation)}
                          className={[
                            'group flex items-center gap-2.5 rounded-md border cursor-grab transition-colors active:cursor-grabbing',
                            tokens.rowPaddingX,
                            tokens.rowPaddingY,
                            sidebarTheme.borderSoft,
                            sidebarTheme.hover,
                            'hover:border-slate-300 dark:hover:border-slate-700',
                          ].join(' ')}
                        >
                          <span
                            className="shrink-0 w-2 h-2 rounded-full"
                            style={{ backgroundColor: operation.color }}
                            aria-hidden
                          />
                          <span
                            className={['font-semibold tracking-wide', tokens.rowText].join(' ')}
                            style={{ color: operation.color }}
                          >
                            {operation.label}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-col gap-3">
                    <SidebarSectionLabel>Parameters</SidebarSectionLabel>
                    <p className={['text-[11px] -mt-1 px-1', sidebarTheme.textSecondary].join(' ')}>
                      Drag a parameter chip onto an operation to attach it. Edit name, type, and rules in the Parameter panel.
                    </p>
                    <div className={['flex flex-col', tokens.rowGap].join(' ')}>
                      {PARAMETER_CHIPS.map((chip) => (
                        <div
                          key={chip.inLocation}
                          draggable
                          onDragStart={(e) => handleParameterDragStart(e, chip)}
                          title={chip.hint}
                          className={[
                            'group flex items-center gap-2.5 rounded-md border cursor-grab transition-colors active:cursor-grabbing',
                            tokens.rowPaddingX,
                            tokens.rowPaddingY,
                            sidebarTheme.borderSoft,
                            sidebarTheme.hover,
                            'hover:border-slate-300 dark:hover:border-slate-700',
                          ].join(' ')}
                        >
                          <span
                            className={['shrink-0 w-2 h-2 rounded-full', chip.dot].join(' ')}
                            aria-hidden
                          />
                          <span
                            className={['font-semibold tracking-wide uppercase', tokens.rowText, sidebarTheme.textPrimary].join(' ')}
                          >
                            {chip.label}
                          </span>
                          <span
                            className={['ml-auto truncate text-[11px]', sidebarTheme.textTertiary].join(' ')}
                          >
                            in: {chip.inLocation}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Paths Tab Content */}
              {activeTab === 'paths' && (
                <div className="flex flex-col gap-3">
                  <div>
                    <SidebarSectionLabel trailing={`${paths.length} total`}>
                      Paths
                    </SidebarSectionLabel>

                    {/* Search Input */}
                    <div className="mb-3 relative">
                      <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                      <input
                        type="text"
                        value={pathSearch}
                        onChange={(e) => setPathSearch(e.target.value)}
                        placeholder="Filter paths…"
                        className={[
                          'w-full pl-7 pr-2 text-[12.5px] rounded-md border transition-colors',
                          tokens.inputPaddingY,
                          sidebarTheme.inputBase,
                        ].join(' ')}
                      />
                    </div>

                    {(() => {
                      // Filter paths based on search
                      const filteredPaths = pathSearch.trim()
                        ? paths.filter(path =>
                            path.pathname.toLowerCase().includes(pathSearch.toLowerCase())
                          )
                        : paths;

                      if (paths.length === 0) {
                        return (
                          <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-1">
                            No paths yet. Use the + button below to create one.
                          </span>
                        );
                      }

                      if (filteredPaths.length === 0) {
                        return (
                          <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-1">
                            No paths match &quot;{pathSearch}&quot;
                          </span>
                        );
                      }

                      return (
                        <ul className={['flex flex-col', tokens.rowGap].join(' ')}>
                          {filteredPaths.map((path) => {
                        const invalid = !isValidPath(path.pathname);
                        const expanded = Boolean(expandedPathIds[path.id]);
                        const pathOps = operationsByPathId[path.id] ?? [];
                        const loadingOps = operationsLoadingPathId === path.id;
                        const selected = selectedPathId === path.id;
                        return (
                      <li key={path.id}>
                      <div
                        className={[
                          'group relative flex flex-col rounded-md transition-colors',
                          invalid
                            ? 'border border-rose-300 dark:border-rose-900/70 bg-rose-50/60 dark:bg-rose-950/30'
                            : selected
                              ? `${sidebarTheme.rowSelected} ${sidebarTheme.rowSelectedRing}`
                              : `border ${sidebarTheme.borderSoft} ${sidebarTheme.hover}`,
                        ].join(' ')}
                        title={invalid ? 'Invalid path: must start with / and use valid {param} placeholders' : undefined}
                      >
                        {selected && !invalid && (
                          <span
                            className="absolute left-0 top-1/2 -translate-y-1/2 h-4 w-0.5 rounded-r bg-indigo-500"
                            aria-hidden
                          />
                        )}
                        <div className={['flex items-center gap-0.5', tokens.rowPaddingX, tokens.rowPaddingY].join(' ')}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              togglePathExpanded(path.id);
                            }}
                            className={[
                              'shrink-0 rounded p-1 transition-colors',
                              sidebarTheme.textTertiary,
                              'hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800/60',
                            ].join(' ')}
                            aria-expanded={expanded}
                            aria-label={expanded ? 'Collapse operations' : 'Expand operations'}
                          >
                            {expanded ? <ChevronDown className="h-3.5 w-3.5" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5" aria-hidden />}
                          </button>
                          <div
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                onPathSelect(path.id, path.pathname);
                              }
                            }}
                            onClick={() => onPathSelect(path.id, path.pathname)}
                            className={[
                              'min-w-0 flex-1 cursor-pointer rounded px-1 py-0.5 text-left font-mono',
                              tokens.rowText,
                              selected ? 'font-semibold' : sidebarTheme.textPrimary,
                            ].join(' ')}
                          >
                            <span className="block truncate">{path.pathname}</span>
                          </div>
                          {invalid && (
                            <span className="shrink-0 inline-flex items-center justify-center w-5 h-5 rounded text-rose-600 dark:text-rose-400" title="Path is misconfigured">
                              <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.25} aria-hidden />
                            </span>
                          )}
                          <div className="flex shrink-0 gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleEditPath(path);
                              }}
                              className="rounded p-1 transition-colors text-slate-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/40"
                              aria-label="Edit path"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeletePath(path);
                              }}
                              className="rounded p-1 transition-colors text-slate-400 dark:text-slate-500 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40"
                              aria-label="Delete path"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                        {expanded && (
                          <div
                            className={['border-t px-2 pb-2 pt-1.5', sidebarTheme.borderSoft].join(' ')}
                          >
                            {loadingOps && (
                              <p className="px-2 py-1 text-[10px] text-gray-500 dark:text-gray-400">Loading operations…</p>
                            )}
                            {!loadingOps && pathOps.length === 0 && (
                              <p className="px-2 py-1 text-[10px] text-gray-500 dark:text-gray-400">No operations yet</p>
                            )}
                            {!loadingOps &&
                              pathOps.map((op) => {
                                const method = op.operation.toUpperCase();
                                const color = OPERATION_COLORS[method] ?? '#64748b';
                                return (
                                  <button
                                    key={op.id}
                                    type="button"
                                    disabled={!onOperationFocus}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onOperationFocus?.(path.id, path.pathname, {
                                        id: op.id,
                                        operation: op.operation,
                                      });
                                    }}
                                    className={[
                                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                                      tokens.rowText,
                                      sidebarTheme.textPrimary,
                                      sidebarTheme.hover,
                                    ].join(' ')}
                                    title={`Focus ${method} on canvas`}
                                  >
                                    <span
                                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold text-white"
                                      style={{ backgroundColor: color }}
                                    >
                                      {method}
                                    </span>
                                  </button>
                                );
                              })}
                          </div>
                        )}
                      </div>
                      </li>
                    ); })}
                        </ul>
                      );
                    })()}
                  </div>
                </div>
              )}

              {/* Classes Tab Content */}
              {activeTab === 'classes' && (
                <div className="flex flex-col h-full gap-0">
                  {/* Search Input */}
                  <div className="shrink-0 mb-3 relative">
                    <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                    <input
                      type="text"
                      value={classSearch}
                      onChange={(e) => setClassSearch(e.target.value)}
                      placeholder="Filter classes…"
                      className={[
                        'w-full pl-7 pr-2 text-[12.5px] rounded-md border transition-colors',
                        tokens.inputPaddingY,
                        sidebarTheme.inputBase,
                      ].join(' ')}
                    />
                  </div>

                  {/* Scrollable classes list */}
                  <div className={['flex-1 overflow-y-auto flex flex-col', tokens.rowGap].join(' ')}>
                    {(() => {
                      const filteredClasses = classSearch.trim()
                        ? classes.filter(cls =>
                            cls.name.toLowerCase().includes(classSearch.toLowerCase())
                          )
                        : classes;

                      if (classes.length === 0) {
                        return (
                          <div
                            className={[
                              'py-6 px-3 text-center rounded-md border border-dashed',
                              sidebarTheme.borderSoft,
                              sidebarTheme.textSecondary,
                              'text-[12px]',
                            ].join(' ')}
                          >
                            No classes found. Create classes in the main Studio editor.
                          </div>
                        );
                      }

                      if (filteredClasses.length === 0) {
                        return (
                          <span className={['text-[12px] px-2 py-1', sidebarTheme.textSecondary].join(' ')}>
                            No classes match &quot;{classSearch}&quot;
                          </span>
                        );
                      }

                      return (
                        <>
                          <SidebarSectionLabel
                            trailing={classSearch.trim() ? `${filteredClasses.length} / ${classes.length}` : 'Drag to canvas'}
                          >
                            Classes
                          </SidebarSectionLabel>
                          {filteredClasses.map((cls) => {
                            const handleClassDragStart = (e: React.DragEvent) => {
                              e.dataTransfer.effectAllowed = 'copy';
                              e.dataTransfer.setData('application/json', JSON.stringify({
                                type: 'class',
                                classId: cls.id,
                                className: cls.name,
                              }));
                            };

                            return (
                              <div
                                key={cls.id}
                                draggable
                                onDragStart={handleClassDragStart}
                                className={[
                                  'group flex items-center gap-2.5 rounded-md border cursor-grab transition-colors active:cursor-grabbing',
                                  tokens.rowPaddingX,
                                  tokens.rowPaddingY,
                                  sidebarTheme.borderSoft,
                                  sidebarTheme.surface,
                                  sidebarTheme.hover,
                                  'hover:border-indigo-300 dark:hover:border-indigo-800',
                                ].join(' ')}
                              >
                                <span
                                  className="shrink-0 w-1.5 h-1.5 rounded-full bg-indigo-500"
                                  aria-hidden
                                />
                                <div className="flex-1 min-w-0">
                                  <div className={['font-medium truncate', tokens.rowText, sidebarTheme.textPrimary].join(' ')}>
                                    {cls.name}
                                  </div>
                                  <div className={['text-[10.5px] mt-0.5', sidebarTheme.textTertiary].join(' ')}>
                                    Class schema
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </>
                      );
                    })()}
                  </div>
                </div>
              )}

              {/* Properties Tab Content */}
              {activeTab === 'properties' && (
                <div className="flex flex-col h-full gap-0">
                  {/* Search Input - Fixed at top */}
                  <div className="shrink-0 mb-3 relative">
                    <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                    <input
                      type="text"
                      placeholder="Search properties…"
                      value={propertySearch}
                      onChange={(e) => setPropertySearch(e.target.value)}
                      className={[
                        'w-full pl-7 pr-2 text-[12.5px] rounded-md border transition-colors',
                        tokens.inputPaddingY,
                        sidebarTheme.inputBase,
                      ].join(' ')}
                    />
                  </div>

                  {/* Scrollable properties list */}
                  <div className={['flex-1 overflow-y-auto flex flex-col', tokens.rowGap].join(' ')}>
                    {properties.length === 0 ? (
                      <div
                        className={[
                          'py-6 px-3 text-center rounded-md border border-dashed',
                          sidebarTheme.borderSoft,
                          sidebarTheme.textSecondary,
                          'text-[12px]',
                        ].join(' ')}
                      >
                        No properties found. Create properties in the main Studio editor.
                      </div>
                    ) : (
                      <>
                        <SidebarSectionLabel
                          trailing={`${properties.filter(p =>
                            p.name.toLowerCase().includes(propertySearch.toLowerCase()) ||
                            (p.data?.type && p.data.type.toLowerCase().includes(propertySearch.toLowerCase()))
                          ).length} / ${properties.length}`}
                        >
                          <span title="Drag to canvas or onto path variables for type binding">Properties</span>
                        </SidebarSectionLabel>
                        {properties
                          .filter(prop =>
                            prop.name.toLowerCase().includes(propertySearch.toLowerCase()) ||
                            (prop.data?.type && prop.data.type.toLowerCase().includes(propertySearch.toLowerCase()))
                          )
                          .map((prop) => {
                        const handlePropertyDragStart = (e: React.DragEvent) => {
                          e.dataTransfer.effectAllowed = 'copy';
                          e.dataTransfer.setData('application/json', JSON.stringify({
                            type: 'property',
                            propertyId: prop.id,
                            propertyName: prop.name,
                            description: prop.description,
                            data: prop.data || { type: 'string' },
                          }));
                        };

                        const isOptional = (() => {
                          if (!prop.data) return false;
                          const { type, nullable } = prop.data;
                          if (nullable === true) return true;
                          const typeArr = Array.isArray(type) ? type : type != null ? [type] : [];
                          return typeArr.some((t: unknown) => t === 'null' || t == null);
                        })();

                        const getTypeDisplay = () => {
                          if (!prop.data) return 'string';
                          const { type, format, enum: enumValues, items } = prop.data;
                          const typeArr = Array.isArray(type) ? type : type != null ? [type] : [];
                          const primaryTypes = typeArr.filter((t: unknown) => t != null && t !== 'null');
                          const baseType = primaryTypes[0] ?? 'string';

                          if (enumValues && Array.isArray(enumValues) && enumValues.length > 0) {
                            return `enum (${enumValues.length})`;
                          }
                          if (baseType === 'array' && items) {
                            const raw = (items && typeof items === 'object' && 'type' in items && (items as { type?: unknown }).type);
                            const itemType = raw != null && raw !== 'null' ? String(raw) : 'any';
                            return `${itemType}[]`;
                          }
                          if (format) {
                            return `${baseType} (${format})`;
                          }
                          return baseType || 'string';
                        };

                        const typeDisplay = getTypeDisplay();

                        return (
                          <div
                            key={prop.id}
                            draggable
                            onDragStart={handlePropertyDragStart}
                            className={[
                              'group flex items-center gap-2.5 rounded-md border cursor-grab transition-colors active:cursor-grabbing',
                              tokens.rowPaddingX,
                              tokens.rowPaddingY,
                              sidebarTheme.borderSoft,
                              sidebarTheme.surface,
                              sidebarTheme.hover,
                              'hover:border-violet-300 dark:hover:border-violet-800',
                            ].join(' ')}
                          >
                            <span
                              className="shrink-0 w-1.5 h-1.5 rounded-full bg-violet-500"
                              aria-hidden
                            />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className={['font-medium truncate', tokens.rowText, sidebarTheme.textPrimary].join(' ')}>
                                  {prop.name}
                                </span>
                                {isOptional && (
                                  <span
                                    className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400"
                                  >
                                    optional
                                  </span>
                                )}
                              </div>
                              <div className={['text-[10.5px] mt-0.5 font-mono', sidebarTheme.textTertiary].join(' ')}>
                                {typeDisplay}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              </div>
            )}

              {/* Security Tab Content */}
              {activeTab === 'security' && (
                <SecuritySchemesPanel onRefresh={onSecurityRefresh} />
              )}

              {/* Servers Tab Content */}
              {activeTab === 'servers' && (
                <ServersPanel onRefresh={onSecurityRefresh} />
              )}
            </>
          )}
        </div>

      {/* Add/Edit Path Dialog */}
      <Dialog.Root open={pathDialogOpen} onOpenChange={setPathDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999]" />
          <Dialog.Content
            aria-describedby={undefined}
            className={`fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10000] w-full max-w-md rounded-lg shadow-lg ${
              isDark ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
            }`}
          >
            <Dialog.Title
              className={`px-6 py-4 text-lg font-semibold border-b ${
                isDark
                  ? 'text-gray-100 border-gray-700'
                  : 'text-gray-900 border-gray-200'
              }`}
            >
              {editingPath ? 'Edit Path' : 'Add New Path'}
            </Dialog.Title>

            <div className="px-6 py-4">
              <label
                htmlFor="pathname"
                className={`block text-sm font-medium mb-2 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}
              >
                Path Name
              </label>
              <input
                id="pathname"
                type="text"
                autoFocus
                placeholder="/api/users"
                value={pathNameInput}
                onChange={(e) => setPathNameInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && pathNameInput.trim()) {
                    handleSavePath();
                  }
                }}
                className={`w-full px-3 py-2 rounded-md border text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  isDark
                    ? 'bg-gray-900 border-gray-600 text-gray-100 placeholder-gray-500'
                    : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                }`}
              />
              <p
                className={`mt-2 text-xs ${
                  isDark ? 'text-gray-400' : 'text-gray-500'
                }`}
              >
                Enter the path (e.g., /api/users, /v1/products/{'{'}id{'}'})
              </p>

              {/* Auto-create CRUD operations checkbox - only shown when adding new path */}
              {!editingPath && (
                <label className="flex items-center gap-3 mt-4 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoCreateCrud}
                    onChange={(e) => setAutoCreateCrud(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 focus:ring-2 cursor-pointer"
                  />
                  <span
                    className={`text-sm ${
                      isDark ? 'text-gray-300' : 'text-gray-700'
                    }`}
                  >
                    Auto-create CRUD operations (GET, POST, PUT, DELETE)
                  </span>
                </label>
              )}
            </div>

            <div
              className={`px-6 py-4 flex justify-end gap-3 border-t ${
                isDark ? 'border-gray-700' : 'border-gray-200'
              }`}
            >
              <Dialog.Close asChild>
                <button
                  type="button"
                  className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                    isDark
                      ? 'text-gray-300 hover:bg-gray-700'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="button"
                onClick={handleSavePath}
                disabled={!pathNameInput.trim()}
                className={`px-4 py-2 text-sm font-medium text-white rounded-md transition-colors ${
                  pathNameInput.trim()
                    ? 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700'
                    : 'bg-gray-400 cursor-not-allowed'
                }`}
              >
                {editingPath ? 'Save' : 'Add'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Import from OpenAPI Dialog (#566) */}
      <Dialog.Root open={importOpenAPIOpen} onOpenChange={(open) => { setImportOpenAPIOpen(open); if (!open) setImportOpenAPIError(''); setImportOpenAPIContent(''); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999]" />
          <Dialog.Content
            aria-describedby={undefined}
            className={`fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10000] w-full max-w-lg rounded-lg shadow-lg ${
              isDark ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
            }`}
          >
            <Dialog.Title
              className={`px-6 py-4 text-lg font-semibold border-b ${
                isDark ? 'text-gray-100 border-gray-700' : 'text-gray-900 border-gray-200'
              }`}
            >
              Import paths from OpenAPI
            </Dialog.Title>
            <div className="px-6 py-4 space-y-3">
              <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                Paste or upload an OpenAPI 3.x spec to add paths and security schemes to this version.
              </p>
              <div className="flex gap-2">
                <label
                  className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm cursor-pointer ${
                    isDark ? 'border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600' : 'border-gray-300 bg-gray-50 text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <FileUp className="w-4 h-4" />
                  Upload file
                  <input
                    type="file"
                    accept=".json,.yaml,.yml"
                    className="sr-only"
                    onChange={handleImportOpenAPIFile}
                  />
                </label>
              </div>
              <textarea
                placeholder="Paste OpenAPI JSON or YAML here..."
                value={importOpenAPIContent}
                onChange={(e) => { setImportOpenAPIContent(e.target.value); setImportOpenAPIError(''); }}
                rows={10}
                className={`w-full px-3 py-2 rounded-md border text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  isDark ? 'bg-gray-900 border-gray-600 text-gray-100 placeholder-gray-500' : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                }`}
              />
              {importOpenAPIError && (
                <p className="text-sm text-red-600 dark:text-red-400" role="alert">
                  {importOpenAPIError}
                </p>
              )}
            </div>
            <div
              className={`px-6 py-4 flex justify-end gap-3 border-t ${
                isDark ? 'border-gray-700' : 'border-gray-200'
              }`}
            >
              <Dialog.Close asChild>
                <button
                  type="button"
                  disabled={importOpenAPILoading}
                  className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                    isDark ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="button"
                onClick={handleImportOpenAPISubmit}
                disabled={importOpenAPILoading || !importOpenAPIContent.trim()}
                className={`px-4 py-2 text-sm font-medium text-white rounded-md transition-colors ${
                  importOpenAPILoading || !importOpenAPIContent.trim()
                    ? 'bg-gray-400 cursor-not-allowed'
                    : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700'
                }`}
              >
                {importOpenAPILoading ? 'Importing…' : 'Import'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      </SidebarShell>
    </Tabs.Root>
  );
}


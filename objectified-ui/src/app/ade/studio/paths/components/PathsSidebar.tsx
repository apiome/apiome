'use client';

import React, { useState, useEffect } from 'react';
import { Plus, Pencil, Trash2, AlertTriangle, FileUp } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
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
} from '../../../../../../lib/api/paths-client';
import { getSharedPathParameters } from '../../../../../../lib/db/helper-shared-path-parameters';
import { getPathParameterCoverageError, getPathTemplateValidationError, isValidPath } from '../../../../../../lib/utils/path-params';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { AVAILABLE_OPERATIONS } from './paths-operation-colors';
import { parseOpenAPISpec } from '../../../../utils/openapi-import';
import { importPathsFromOpenAPIForVersion } from '../../../../../../lib/db/import-openapi-paths-security';

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
  onSecurityRefresh,
}: {
  activeTab: 'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers';
  onTabChange: (tab: 'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers') => void;
  selectedPathId: string | null;
  onPathSelect: (pathId: string | null, pathname?: string) => void;
  onSecurityRefresh?: () => void;
}) {
  const { selectedVersionId, selectedProjectId } = useStudio();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const isDark = useDarkMode();
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
    const templateError = getPathTemplateValidationError(trimmedPath);
    if (templateError) {
      await alertDialog({
        title: 'Invalid path template',
        message: templateError,
        variant: 'warning',
      });
      return;
    }

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
    const coverageError = getPathParameterCoverageError(trimmedPath, paramsForCoverage);
    if (coverageError) {
      await alertDialog({
        title: 'Path parameters do not match template',
        message: coverageError,
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

  const TAB_OPTIONS = [
    { value: 'paths' as const, label: 'Paths' },
    { value: 'operations' as const, label: 'Operations' },
    { value: 'classes' as const, label: 'Classes' },
    { value: 'properties' as const, label: 'Properties' },
    { value: 'security' as const, label: 'Security' },
    { value: 'servers' as const, label: 'Servers' },
  ];

  return (
    <div
      className={`w-[280px] h-full shrink-0 flex flex-col relative border-r ${
        isDark ? 'border-slate-700' : 'border-slate-200'
      }`}
      style={{
        background: isDark
          ? 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)'
          : 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
        boxShadow: isDark
          ? '4px 0 24px rgba(0, 0, 0, 0.3)'
          : '4px 0 24px rgba(0, 0, 0, 0.06)',
      }}
    >
      {/* Section Dropdown */}
        <div
          className={`px-4 py-3 border-b ${isDark ? 'border-slate-700' : 'border-slate-200'}`}
        >
          <Select value={activeTab} onValueChange={handleTabChange}>
            <SelectTrigger className="h-9 text-[0.8125rem] w-full">
              <SelectValue placeholder="Section" />
            </SelectTrigger>
            <SelectContent>
              {TAB_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Content Area */}
        <div
          className={`flex-1 p-4 flex flex-col ${activeTab === 'properties' ? 'overflow-hidden' : 'overflow-auto'}`}
        >
          {isLoading ? (
            <div className="flex justify-center py-8">
              <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
            </div>
          ) : (
            <>
              {/* Operations Tab Content */}
              {activeTab === 'operations' && (
                <div className="flex flex-col gap-4">
                  <div className="mb-2 px-1">
                    <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
                      Drag to Canvas
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 -mt-1 px-1">
                    Drag an operation onto a path on the canvas to add it.
                  </p>
                  <div className="flex flex-col gap-1">
                    {AVAILABLE_OPERATIONS.map((operation) => (
                      <div
                        key={operation.id}
                        draggable
                        onDragStart={(e) => handleOperationDragStart(e, operation)}
                        className={`px-3 py-2 rounded border cursor-grab transition-all duration-150 hover:-translate-y-px hover:shadow active:cursor-grabbing ${
                          isDark
                            ? 'border-gray-700 bg-gray-700/30 hover:bg-gray-700/50'
                            : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className="w-3 h-3 rounded-full shrink-0"
                            style={{ backgroundColor: operation.color }}
                          />
                          <span className="text-sm font-medium" style={{ color: operation.color }}>
                            {operation.label}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Paths Tab Content */}
              {activeTab === 'paths' && (
                <div className="flex flex-col gap-4">
                  {/* Paths List Section */}
                  <div>
                    <div className="mb-2 px-1 flex justify-between items-center">
                      <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
                        Paths
                      </span>
                      <span className="text-[10px] text-gray-400 dark:text-gray-500">
                        {paths.length} total
                      </span>
                    </div>

                    {/* Search Input */}
                    <div className="mb-3">
                      <input
                        type="text"
                        value={pathSearch}
                        onChange={(e) => setPathSearch(e.target.value)}
                        placeholder="Filter paths..."
                        className={`w-full px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                          isDark
                            ? 'bg-slate-800 border-slate-600 text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500'
                            : 'bg-white border-gray-300 text-gray-700 placeholder-gray-400 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500'
                        }`}
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

                      return filteredPaths.map((path) => {
                        const invalid = !isValidPath(path.pathname);
                        return (
                      <div
                        key={path.id}
                        onClick={() => onPathSelect(path.id, path.pathname)}
                        className={`relative flex items-center justify-between px-3 py-2 rounded border cursor-pointer transition-all duration-150 ${
                          invalid
                            ? 'border-2 border-red-600 ring-2 ring-red-500/60 bg-red-500/15 dark:bg-red-500/20 dark:ring-red-400/50'
                            : selectedPathId === path.id
                              ? 'border-2 border-indigo-500 bg-indigo-500/20 hover:bg-indigo-500/30'
                              : isDark
                                ? 'border-gray-700 bg-gray-700/30 hover:bg-gray-700/50'
                                : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
                        }`}
                        title={invalid ? 'Invalid path: must start with / and use valid {param} placeholders' : undefined}
                      >
                        {invalid && (
                          <div className="absolute top-1 right-1 flex items-center justify-center w-5 h-5 rounded-full bg-red-600 text-white shadow ring-2 ring-red-400/80" title="Path is misconfigured">
                            <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.5} aria-hidden />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <span className={`text-sm truncate block ${
                            selectedPathId === path.id 
                              ? 'text-indigo-600 dark:text-indigo-400 font-semibold' 
                              : 'text-gray-700 dark:text-gray-300'
                          }`}>
                            {path.pathname}
                          </span>
                        </div>
                        <div className={`flex gap-1 shrink-0 ${invalid ? 'pl-6' : ''}`}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleEditPath(path);
                            }}
                            className={`p-1 rounded transition-colors ${
                              isDark ? 'text-slate-400 hover:text-indigo-400 hover:bg-indigo-500/10' : 'text-slate-500 hover:text-indigo-600 hover:bg-indigo-500/10'
                            }`}
                            aria-label="Edit path"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeletePath(path);
                            }}
                            className={`p-1 rounded transition-colors ${
                              isDark ? 'text-slate-400 hover:text-red-400 hover:bg-red-500/10' : 'text-slate-500 hover:text-red-600 hover:bg-red-500/10'
                            }`}
                            aria-label="Delete path"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    ); });
                    })()}
                  </div>
                </div>
              )}

              {/* Classes Tab Content */}
              {activeTab === 'classes' && (
                <div className="flex flex-col h-full gap-0">
                  {/* Search Input */}
                  <div className="shrink-0 mb-3">
                    <input
                      type="text"
                      value={classSearch}
                      onChange={(e) => setClassSearch(e.target.value)}
                      placeholder="Filter classes..."
                      className={`w-full px-3 py-2 text-sm rounded-lg border focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                        isDark
                          ? 'bg-gray-800 border-gray-600 text-gray-100 placeholder-gray-500'
                          : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                      }`}
                    />
                  </div>

                  {/* Scrollable classes list */}
                  <div className="flex-1 overflow-y-auto flex flex-col gap-3">
                    {(() => {
                      const filteredClasses = classSearch.trim()
                        ? classes.filter(cls =>
                            cls.name.toLowerCase().includes(classSearch.toLowerCase())
                          )
                        : classes;

                      if (classes.length === 0) {
                        return (
                          <div
                            className={`py-6 px-4 text-center rounded border border-dashed ${
                              isDark ? 'border-slate-700' : 'border-slate-200'
                            }`}
                          >
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              No classes found. Create classes in the main Studio editor.
                            </span>
                          </div>
                        );
                      }

                      if (filteredClasses.length === 0) {
                        return (
                          <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-1">
                            No classes match &quot;{classSearch}&quot;
                          </span>
                        );
                      }

                      return (
                        <>
                          <div className="px-1 mb-1 flex justify-between items-center shrink-0">
                            <span className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Classes
                            </span>
                            {classSearch.trim() && (
                              <span className="text-[10px] text-gray-400 dark:text-gray-500">
                                {filteredClasses.length} / {classes.length}
                              </span>
                            )}
                          </div>
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
                                className={`px-4 py-3 rounded-lg border text-sm cursor-grab transition-all duration-200 relative ${
                                  isDark
                                    ? 'border-slate-600 bg-slate-800/80 text-slate-200 shadow shadow-black/30 hover:bg-slate-700/60 hover:-translate-y-px hover:shadow-lg hover:border-indigo-500 active:cursor-grabbing active:translate-y-0'
                                    : 'border-slate-300 bg-white/90 text-slate-800 shadow hover:bg-slate-50 hover:-translate-y-px hover:shadow-md hover:border-indigo-400 active:cursor-grabbing active:translate-y-0'
                                }`}
                                style={{
                                  background: isDark
                                    ? 'linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.8) 100%)'
                                    : 'linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%)',
                                }}
                              >
                                <div className="flex items-center gap-3">
                                  <div
                                    className="w-2 h-2 rounded-full shrink-0 shadow-[0_0_8px_rgba(99,102,241,0.4)]"
                                    style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }}
                                  />
                                  <div className="flex-1 min-w-0">
                                    <div className="font-semibold text-sm truncate">{cls.name}</div>
                                    <div className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
                                      Class Schema
                                    </div>
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
                  <div className="shrink-0 mb-3">
                    <input
                      type="text"
                      placeholder="Search properties..."
                      value={propertySearch}
                      onChange={(e) => setPropertySearch(e.target.value)}
                      className={`w-full px-3 py-2 text-sm rounded-lg border focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                        isDark
                          ? 'bg-gray-800 border-gray-600 text-gray-100 placeholder-gray-500'
                          : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                      }`}
                    />
                  </div>

                  {/* Scrollable properties list */}
                  <div className="flex-1 overflow-y-auto flex flex-col gap-3">
                    {properties.length === 0 ? (
                      <div
                        className={`py-6 px-4 text-center rounded border border-dashed ${
                          isDark ? 'border-slate-700' : 'border-slate-200'
                        }`}
                      >
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          No properties found. Create properties in the main Studio editor.
                        </span>
                      </div>
                    ) : (
                      <>
                        <div className="px-1 mb-1 flex justify-between items-center shrink-0">
                          <span className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider" title="Drag to canvas or onto path variables for type binding">
                            Drag to Canvas / Path Variables
                          </span>
                          <span className="text-[10px] text-gray-400 dark:text-gray-500">
                            {properties.filter(p =>
                              p.name.toLowerCase().includes(propertySearch.toLowerCase()) ||
                              (p.data?.type && p.data.type.toLowerCase().includes(propertySearch.toLowerCase()))
                            ).length} / {properties.length}
                          </span>
                        </div>
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
                            className={`px-4 py-3 rounded-lg border text-sm cursor-grab transition-all duration-200 relative ${
                              isDark
                                ? 'border-slate-600 hover:border-violet-500 active:cursor-grabbing active:translate-y-0'
                                : 'border-slate-300 hover:border-violet-400 active:cursor-grabbing active:translate-y-0'
                            } hover:-translate-y-px hover:shadow-md`}
                            style={{
                              background: isDark
                                ? 'linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.8) 100%)'
                                : 'linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%)',
                              color: isDark ? '#e2e8f0' : '#1e293b',
                              boxShadow: isDark ? '0 1px 3px rgba(0, 0, 0, 0.3)' : '0 1px 3px rgba(0, 0, 0, 0.1)',
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <div
                                className="w-1.5 h-1.5 rounded shrink-0 shadow-[0_0_6px_rgba(139,92,246,0.4)]"
                                style={{ background: 'linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)' }}
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 min-w-0">
                                  <span className="font-medium text-sm truncate">{prop.name}</span>
                                  {isOptional && (
                                    <span
                                      className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded ${
                                        isDark ? 'bg-slate-400/25 text-slate-400' : 'bg-slate-400/20 text-slate-500'
                                      }`}
                                    >
                                      optional
                                    </span>
                                  )}
                                </div>
                                <div className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                                  {typeDisplay}
                                </div>
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

        {/* Paths actions (Paths Tab Only) - Bottom */}
        {activeTab === 'paths' && (
          <div className="absolute bottom-4 left-4 right-4 flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={handleImportFromOpenAPI}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                isDark
                  ? 'text-slate-200 bg-slate-700 hover:bg-slate-600 border border-slate-600'
                  : 'text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-200'
              }`}
              aria-label="Import from OpenAPI"
            >
              <FileUp className="w-4 h-4" />
              Import from OpenAPI
            </button>
            <button
              type="button"
              onClick={handleAddPath}
              className="flex items-center justify-center w-10 h-10 rounded-full text-white shadow-lg transition-all hover:shadow-xl bg-gradient-to-br from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
              aria-label="Add path"
            >
              <Plus className="w-5 h-5" />
            </button>
          </div>
        )}

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
    </div>
  );
}


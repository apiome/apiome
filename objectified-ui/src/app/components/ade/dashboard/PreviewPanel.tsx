'use client';

import { useState } from 'react';
import { Package, Search, Check, FileJson, FileCode2, List, ChevronRight, ArrowUpAZ, ArrowDownAZ } from 'lucide-react';
import * as Checkbox from '@radix-ui/react-checkbox';
import { AnalysisResult } from '../../../utils/openapi-analyzer';
import YAML from 'yaml';
import Editor from '@monaco-editor/react';

interface PreviewPanelProps {
  analysis: AnalysisResult;
  onImportOptionsChange?: (options: ImportOptions) => void;
}

export interface ImportOptions {
  projectName: string;
  versionSource: 'spec' | 'manual';
  targetVersion: string;
  autoLayout: boolean;
  createRelationships: boolean;
  applyNamingConvention: boolean;
  generateDocumentation: boolean;
  selectedSchemas: string[];
}

interface SchemaInfo {
  name: string;
  properties: number;
  selected: boolean;
  required: boolean;
}

const MAX_ENUM_DISPLAY = 4;

export function PreviewPanel({ analysis, onImportOptionsChange }: PreviewPanelProps) {
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedSchemaName, setSelectedSchemaName] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'summary' | 'json' | 'yaml'>('summary');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const [schemas, setSchemas] = useState<SchemaInfo[]>(() => {
    const schemaObj = analysis.document?.components?.schemas || analysis.document?.definitions || {};
    return Object.keys(schemaObj).map(name => ({
      name,
      properties: Object.keys(schemaObj[name]?.properties || {}).length,
      selected: true,
      required: false
    }));
  });

  const [importOptions, setImportOptions] = useState<ImportOptions>({
    projectName: analysis.document?.info?.title || 'New Project',
    versionSource: 'spec',
    targetVersion: analysis.document?.info?.version || '1.0.0',
    autoLayout: true,
    createRelationships: true,
    applyNamingConvention: true,
    generateDocumentation: false,
    selectedSchemas: schemas.map(s => s.name)
  });


  const selectedSchema = selectedSchemaName
    ? (analysis.document?.components?.schemas?.[selectedSchemaName] ||
       analysis.document?.definitions?.[selectedSchemaName])
    : null;

  const filteredSchemas = schemas
    .filter(schema => schema.name.toLowerCase().includes(searchFilter.toLowerCase()))
    .sort((a, b) => {
      if (sortOrder === 'asc') return a.name.localeCompare(b.name);
      if (sortOrder === 'desc') return b.name.localeCompare(a.name);
      return 0; // Keep original order if no sort applied
    });

  const selectedCount = schemas.filter(s => s.selected).length;

  const handleSelectAll = () => {
    const newSchemas = schemas.map(s => ({ ...s, selected: true }));
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const handleSelectNone = () => {
    const newSchemas = schemas.map(s => ({ ...s, selected: s.required }));
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const handleToggleSchema = (name: string) => {
    const newSchemas = schemas.map(s =>
      s.name === name ? { ...s, selected: !s.selected } : s
    );
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const updateSelectedSchemas = (schemaList: SchemaInfo[]) => {
    const selected = schemaList.filter(s => s.selected).map(s => s.name);
    const newOptions = { ...importOptions, selectedSchemas: selected };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleOptionChange = (key: keyof ImportOptions, value: any) => {
    const newOptions = { ...importOptions, [key]: value };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleVersionSourceChange = (source: 'spec' | 'manual') => {
    const specVersion = analysis.document?.info?.version || '1.0.0';
    const newOptions = {
      ...importOptions,
      versionSource: source,
      targetVersion: source === 'spec' ? specVersion : ''
    };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleVersionChange = (version: string) => {
    // Only allow: 0-9, A-Z, a-z, ., -
    const sanitized = version.replace(/[^0-9A-Za-z.\-]/g, '');
    const newOptions = { ...importOptions, targetVersion: sanitized };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const getPropertyType = (prop: any): string => {
    if (prop.$ref) {
      const refName = prop.$ref.split('/').pop();
      return `$ref → ${refName}`;
    }

    if (prop.type === 'array') {
      if (prop.items?.$ref) {
        const refName = prop.items.$ref.split('/').pop();
        return `array<$ref → ${refName}>`;
      }
      return `array<${prop.items?.type || 'any'}>`;
    }
    
    if (prop.enum) {
      const enumValues = prop.enum.slice(0, MAX_ENUM_DISPLAY).join(', ');
      const remaining = prop.enum.length - MAX_ENUM_DISPLAY;

      if (remaining > 0) {
        return `enum (${enumValues}, ... ${remaining} more)`;
      }

      return `enum (${enumValues})`;
    }
    return prop.type || 'any';
  };

  return (
    <div className="space-y-6">
      {/* Schema Selection Controls */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={handleSelectAll}
              className="px-3 py-1.5 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
            >
              Select All
            </button>
            <button
              onClick={handleSelectNone}
              className="px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Select None
            </button>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {selectedCount} of {schemas.length} selected
            </span>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Filter schemas..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="pl-9 pr-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
        </div>
      </div>

      {/* Schema Selection and Preview */}
      <div className="grid grid-cols-3 gap-6">
        {/* Left: Schema List - 1/3 width */}
        <div className="col-span-1 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="border-b border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Schemas to Import
              </h3>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setSortOrder(sortOrder === 'asc' ? null : 'asc')}
                  className={`p-1.5 rounded transition-colors ${
                    sortOrder === 'asc'
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                      : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                  title="Sort A → Z"
                >
                  <ArrowUpAZ className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setSortOrder(sortOrder === 'desc' ? null : 'desc')}
                  className={`p-1.5 rounded transition-colors ${
                    sortOrder === 'desc'
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                      : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                  title="Sort Z → A"
                >
                  <ArrowDownAZ className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
          <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
            {filteredSchemas.map((schema) => (
              <div
                key={schema.name}
                className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                  selectedSchemaName === schema.name
                    ? 'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800'
                    : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                }`}
                onClick={() => setSelectedSchemaName(schema.name)}
              >
                <Checkbox.Root
                  checked={schema.selected}
                  onCheckedChange={() => handleToggleSchema(schema.name)}
                  onClick={(e) => e.stopPropagation()}
                  className="w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
                >
                  <Checkbox.Indicator>
                    <Check className="w-4 h-4 text-white" />
                  </Checkbox.Indicator>
                </Checkbox.Root>
                <Package className="h-5 w-5 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-900 dark:text-white truncate">
                    {schema.name}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {schema.properties} properties
                  </div>
                </div>
                {selectedSchemaName === schema.name && (
                  <ChevronRight className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right: Schema Preview - 2/3 width */}
        <div className="col-span-2 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="border-b border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Schema Preview
              </h3>
              {selectedSchema && selectedSchemaName && (
                <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
                  <button
                    onClick={() => setViewMode('summary')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'summary'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                    title="Summary view"
                  >
                    <List className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setViewMode('json')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'json'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                    title="JSON view"
                  >
                    <FileJson className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setViewMode('yaml')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'yaml'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                    title="YAML view"
                  >
                    <FileCode2 className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="p-4 max-h-[400px] overflow-y-auto">
            {selectedSchema && selectedSchemaName ? (
              <div className="space-y-4">
                {viewMode === 'summary' ? (
                  <>
                    <div>
                      <h4 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
                        {selectedSchemaName}
                      </h4>
                      {selectedSchema.description && (
                        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                          {selectedSchema.description}
                        </p>
                      )}
                    </div>

                    {selectedSchema.properties && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Properties:
                        </h5>
                        <div className="space-y-2 pl-4 border-l-2 border-gray-200 dark:border-gray-700">
                          {Object.entries(selectedSchema.properties).map(([propName, propValue]: [string, any]) => (
                            <div key={propName} className="text-sm">
                              <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                {propName}
                              </span>
                              <span className="text-gray-500 dark:text-gray-400">: </span>
                              <span className="text-gray-700 dark:text-gray-300">
                                {getPropertyType(propValue)}
                              </span>
                              {selectedSchema.required?.includes(propName) && (
                                <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                                  (required)
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Show relationships from $ref in properties */}
                    {selectedSchema.properties && (
                      (() => {
                        const relationships: { name: string; type: string }[] = [];
                        Object.entries(selectedSchema.properties).forEach(([propName, propValue]: [string, any]) => {
                          if (propValue.$ref) {
                            const refName = propValue.$ref.split('/').pop();
                            relationships.push({ name: refName, type: 'composition' });
                          } else if (propValue.type === 'array' && propValue.items?.$ref) {
                            const refName = propValue.items.$ref.split('/').pop();
                            relationships.push({ name: refName, type: 'aggregation' });
                          }
                        });

                        if (relationships.length > 0) {
                          return (
                            <div>
                              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                                Relationships:
                              </h5>
                              <div className="space-y-1 pl-4 border-l-2 border-green-200 dark:border-green-700">
                                {relationships.map((rel, idx) => (
                                  <div key={idx} className="text-sm flex items-center gap-2">
                                    <span className="text-green-600 dark:text-green-400">→</span>
                                    <span className="font-mono text-gray-900 dark:text-white">{rel.name}</span>
                                    <span className="text-xs px-2 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
                                      {rel.type}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        }
                        return null;
                      })()
                    )}

                    {/* Show inheritance from allOf */}
                    {selectedSchema.allOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Inherits From (allOf):
                        </h5>
                        <div className="space-y-2 pl-4 border-l-2 border-blue-200 dark:border-blue-700">
                          {selectedSchema.allOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-blue-600 dark:text-blue-400">↑</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                                    extends
                                  </span>
                                </div>
                              );
                            } else if (item.type === 'object' && item.properties) {
                              const propEntries = Object.entries(item.properties || {});
                              return (
                                <div key={idx} className="space-y-1">
                                  <div className="text-sm flex items-center gap-2">
                                    <span className="text-blue-600 dark:text-blue-400">+</span>
                                    <span className="text-gray-700 dark:text-gray-300 font-medium">
                                      inline properties:
                                    </span>
                                  </div>
                                  <div className="ml-6 space-y-1 pl-3 border-l border-blue-100 dark:border-blue-800">
                                    {propEntries.map(([propName, propValue]: [string, any]) => (
                                      <div key={propName} className="text-sm">
                                        <span className="font-mono text-blue-600 dark:text-blue-400">
                                          {propName}
                                        </span>
                                        <span className="text-gray-500 dark:text-gray-400">: </span>
                                        <span className="text-gray-700 dark:text-gray-300">
                                          {getPropertyType(propValue)}
                                        </span>
                                        {item.required?.includes(propName) && (
                                          <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                                            (required)
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            }
                            return null;
                          })}
                        </div>
                      </div>
                    )}

                    {/* Show polymorphism from oneOf */}
                    {selectedSchema.oneOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Variants (oneOf):
                        </h5>
                        <div className="space-y-1 pl-4 border-l-2 border-purple-200 dark:border-purple-700">
                          {selectedSchema.oneOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-purple-600 dark:text-purple-400">◇</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                                    variant
                                  </span>
                                </div>
                              );
                            }
                            return (
                              <div key={idx} className="text-sm flex items-center gap-2">
                                <span className="text-purple-600 dark:text-purple-400">◇</span>
                                <span className="text-gray-700 dark:text-gray-300">inline schema</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Show flexible matching from anyOf */}
                    {selectedSchema.anyOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Options (anyOf):
                        </h5>
                        <div className="space-y-1 pl-4 border-l-2 border-indigo-200 dark:border-indigo-700">
                          {selectedSchema.anyOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-indigo-600 dark:text-indigo-400">○</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                                    option
                                  </span>
                                </div>
                              );
                            }
                            return (
                              <div key={idx} className="text-sm flex items-center gap-2">
                                <span className="text-indigo-600 dark:text-indigo-400">○</span>
                                <span className="text-gray-700 dark:text-gray-300">inline schema</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </>
                ) : viewMode === 'json' ? (
                  <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                    <Editor
                      height="350px"
                      defaultLanguage="json"
                      value={JSON.stringify(selectedSchema, null, 2)}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 12,
                        lineNumbers: 'on',
                        folding: true,
                        wordWrap: 'on',
                        wrappingIndent: 'indent',
                      }}
                    />
                  </div>
                ) : (
                  <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                    <Editor
                      height="350px"
                      defaultLanguage="yaml"
                      value={YAML.stringify(selectedSchema, null, 2)}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 12,
                        lineNumbers: 'on',
                        folding: true,
                        wordWrap: 'on',
                        wrappingIndent: 'indent',
                      }}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400 dark:text-gray-500">
                Select a schema to preview
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Import Options */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Import Options
        </h3>

        <div className="space-y-4">
          {/* Project Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Project Name
            </label>
            <input
              type="text"
              value={importOptions.projectName}
              onChange={(e) => handleOptionChange('projectName', e.target.value)}
              placeholder="Enter project name"
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              A new project will be created with this name
            </div>
          </div>

          {/* Version Source Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Version
            </label>
            <div className="space-y-3">
              {/* Radio buttons for version source */}
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="versionSource"
                    value="spec"
                    checked={importOptions.versionSource === 'spec'}
                    onChange={() => handleVersionSourceChange('spec')}
                    className="w-4 h-4 text-indigo-600 focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Use version from specification
                  </span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="versionSource"
                    value="manual"
                    checked={importOptions.versionSource === 'manual'}
                    onChange={() => handleVersionSourceChange('manual')}
                    className="w-4 h-4 text-indigo-600 focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Manually enter version
                  </span>
                </label>
              </div>

              {/* Version Input */}
              <div>
                <input
                  type="text"
                  value={importOptions.targetVersion}
                  onChange={(e) => handleVersionChange(e.target.value)}
                  placeholder={importOptions.versionSource === 'spec' ? 'Version from spec' : 'Enter version (e.g., 1.0.0)'}
                  disabled={importOptions.versionSource === 'spec'}
                  className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-gray-50 dark:disabled:bg-gray-800"
                />
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {importOptions.versionSource === 'spec'
                    ? `Using version "${analysis.document?.info?.version || '1.0.0'}" from specification`
                    : 'Allowed characters: 0-9, A-Z, a-z, . (dot), - (dash)'}
                </div>
              </div>
            </div>
          </div>

          {/* Import Options Checkboxes */}
          <div className="space-y-3 pt-4 border-t border-gray-200 dark:border-gray-700">
            <label className="flex items-start gap-3 cursor-pointer group">
              <Checkbox.Root
                checked={importOptions.autoLayout}
                onCheckedChange={(checked) => handleOptionChange('autoLayout', checked)}
                className="mt-0.5 w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
              >
                <Checkbox.Indicator>
                  <Check className="w-4 h-4 text-white" />
                </Checkbox.Indicator>
              </Checkbox.Root>
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  Auto-layout imported schemas on canvas
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Automatically arrange schemas using the selected layout algorithm
                </div>
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer group">
              <Checkbox.Root
                checked={importOptions.createRelationships}
                onCheckedChange={(checked) => handleOptionChange('createRelationships', checked)}
                className="mt-0.5 w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
              >
                <Checkbox.Indicator>
                  <Check className="w-4 h-4 text-white" />
                </Checkbox.Indicator>
              </Checkbox.Root>
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  Create relationships from $ref
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Automatically create relationships based on schema references
                </div>
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer group">
              <Checkbox.Root
                checked={importOptions.applyNamingConvention}
                onCheckedChange={(checked) => handleOptionChange('applyNamingConvention', checked)}
                className="mt-0.5 w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
              >
                <Checkbox.Indicator>
                  <Check className="w-4 h-4 text-white" />
                </Checkbox.Indicator>
              </Checkbox.Root>
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  Apply naming convention (PascalCase)
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Convert schema names to PascalCase format
                </div>
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer group">
              <Checkbox.Root
                checked={importOptions.generateDocumentation}
                onCheckedChange={(checked) => handleOptionChange('generateDocumentation', checked)}
                className="mt-0.5 w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
              >
                <Checkbox.Indicator>
                  <Check className="w-4 h-4 text-white" />
                </Checkbox.Indicator>
              </Checkbox.Root>
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  Generate documentation from descriptions
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Create documentation based on schema descriptions
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}


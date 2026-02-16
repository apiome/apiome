'use client';

import { useState, useCallback, useRef } from 'react';
import { Upload, AlertCircle, CheckCircle, FileCode, FileJson, X, Link } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Label } from '@/app/components/ui/Label';
import { Input } from '@/app/components/ui/Input';
import { Alert } from '@/app/components/ui/Alert';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/app/components/ui/Dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/app/components/ui/Tabs';
import dynamic from 'next/dynamic';
import yaml from 'yaml';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

interface Props {
  onClose: () => void;
  onComplete: () => void;
  onMessage: (type: 'success' | 'error', message: string) => void;
}

export default function PrimitiveImportDialog({ onClose, onComplete, onMessage }: Props) {
  const [schemaJson, setSchemaJson] = useState('');
  const [importing, setImporting] = useState(false);
  const [definitions, setDefinitions] = useState<Record<string, Record<string, unknown>>>({});
  const [selectedDefs, setSelectedDefs] = useState<Set<string>>(new Set());
  const [parseError, setParseError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [importMethod, setImportMethod] = useState<'fileOrUrl' | 'paste'>('fileOrUrl');
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSchemaChange = (value: string | undefined) => {
    const newValue = value || '';
    setSchemaJson(newValue);
    setParseError(null);
    setShowPreview(false);
    setDefinitions({});
    setSelectedDefs(new Set());
  };

  const parseSchemaContent = (content: string): Record<string, unknown> | null => {
    // First try to parse as JSON
    try {
      return JSON.parse(content);
    } catch {
      // If JSON parsing fails, try YAML
      try {
        const parsed = yaml.parse(content);
        if (typeof parsed === 'object' && parsed !== null) {
          return parsed as Record<string, unknown>;
        }
        return null;
      } catch {
        return null;
      }
    }
  };

  /**
   * Extract a primitive name from a standalone JSON Schema.
   * Priority: $id (last path segment) > title (slugified) > filename (without extension)
   */
  const extractPrimitiveNameFromSchema = (
    schema: Record<string, unknown>,
    filename?: string
  ): string => {
    // Try to extract from $id
    if (schema.$id && typeof schema.$id === 'string') {
      const idPath = schema.$id.split('/');
      const lastSegment = idPath[idPath.length - 1];
      if (lastSegment) {
        // Convert to snake_case/camelCase if needed
        return lastSegment.replace(/-/g, '_');
      }
    }

    // Try to extract from title
    if (schema.title && typeof schema.title === 'string') {
      // Convert title to a valid identifier (snake_case)
      return schema.title
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, '')
        .replace(/\s+/g, '_')
        .replace(/^_+|_+$/g, '');
    }

    // Fall back to filename
    if (filename) {
      const baseName = filename.replace(/\.(json|yaml|yml)$/i, '');
      return baseName.replace(/-/g, '_').replace(/\s+/g, '_');
    }

    return 'imported_primitive';
  };

  /**
   * Check if a schema is a standalone primitive schema (not a container with $defs)
   * Handles schemas with: type, anyOf, oneOf, allOf, enum, or const
   */
  const isStandalonePrimitiveSchema = (schema: Record<string, unknown>): boolean => {
    // If it has $defs or definitions, it's a container schema
    const hasDefs = schema.$defs || schema.definitions;
    if (hasDefs) {
      return false;
    }

    // Check for various JSON Schema type indicators
    const hasType = 'type' in schema;
    const hasAnyOf = 'anyOf' in schema;
    const hasOneOf = 'oneOf' in schema;
    const hasAllOf = 'allOf' in schema;
    const hasEnum = 'enum' in schema;
    const hasConst = 'const' in schema;

    return hasType || hasAnyOf || hasOneOf || hasAllOf || hasEnum || hasConst;
  };

  /**
   * Determine the category for a schema (for primitives)
   */
  const determineCategoryFromSchema = (schema: Record<string, unknown>): string => {
    // If type is explicitly set, use it
    if (schema.type) {
      const schemaType = schema.type;
      if (typeof schemaType === 'string') {
        return schemaType;
      }
      if (Array.isArray(schemaType) && schemaType.length > 0) {
        return schemaType[0];
      }
    }

    // For anyOf/oneOf with const values, it's typically a string enum
    if (schema.anyOf || schema.oneOf) {
      const options = (schema.anyOf || schema.oneOf) as Record<string, unknown>[];
      if (options.length > 0 && 'const' in options[0]) {
        const firstConst = options[0].const;
        return typeof firstConst === 'string' ? 'string' : typeof firstConst;
      }
    }

    // For enum, check the type of the first value
    if (schema.enum && Array.isArray(schema.enum) && schema.enum.length > 0) {
      return typeof schema.enum[0];
    }

    // For const, check its type
    if ('const' in schema) {
      return typeof schema.const;
    }

    // Default to object
    return 'object';
  };

  const handleFileSelect = useCallback(async (selectedFile: File) => {
    const fileName = selectedFile.name.toLowerCase();
    if (!fileName.endsWith('.json') && !fileName.endsWith('.yaml') && !fileName.endsWith('.yml')) {
      setParseError('Please select a JSON or YAML file');
      return;
    }

    setFile(selectedFile);
    setIsLoadingFile(true);
    setParseError(null);

    try {
      const content = await selectedFile.text();
      const parsed = parseSchemaContent(content);

      if (!parsed) {
        setParseError('Failed to parse file. Please ensure it contains valid JSON or YAML.');
        setFile(null);
        return;
      }

      // Convert to formatted JSON for the editor
      const jsonString = JSON.stringify(parsed, null, 2);
      setSchemaJson(jsonString);

      // Check if this is a standalone primitive schema
      if (isStandalonePrimitiveSchema(parsed)) {
        // Extract a name for this primitive
        const primitiveName = extractPrimitiveNameFromSchema(parsed, selectedFile.name);

        // Use the entire schema as the definition
        const defs = {
          [primitiveName]: parsed
        };

        setDefinitions(defs as Record<string, Record<string, unknown>>);
        setSelectedDefs(new Set([primitiveName]));
        setShowPreview(true);
        return;
      }

      // Otherwise, look for $defs or definitions
      const defs = {
        ...((parsed.$defs as Record<string, unknown>) || {}),
        ...((parsed.definitions as Record<string, unknown>) || {})
      };

      if (Object.keys(defs).length === 0) {
        setParseError('No definitions found. Schema must contain $defs, definitions, or be a standalone type definition.');
        return;
      }

      setDefinitions(defs as Record<string, Record<string, unknown>>);
      setSelectedDefs(new Set(Object.keys(defs)));
      setShowPreview(true);
    } catch (err) {
      const error = err as Error;
      setParseError(`Error reading file: ${error.message}`);
      setFile(null);
    } finally {
      setIsLoadingFile(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileSelect(files[0]);
    }
  }, [handleFileSelect]);

  const clearFile = () => {
    setFile(null);
    setSchemaJson('');
    setDefinitions({});
    setSelectedDefs(new Set());
    setShowPreview(false);
    setParseError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleUrlFetch = async () => {
    if (!urlInput.trim()) {
      setParseError('Please enter a URL');
      return;
    }

    // Basic URL validation
    try {
      new URL(urlInput);
    } catch {
      setParseError('Please enter a valid URL');
      return;
    }

    setIsLoadingUrl(true);
    setParseError(null);

    try {
      const response = await fetch(urlInput);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const content = await response.text();
      const parsed = parseSchemaContent(content);

      if (!parsed) {
        setParseError('Failed to parse response. Please ensure the URL returns valid JSON or YAML.');
        return;
      }

      // Convert to formatted JSON for the editor
      const jsonString = JSON.stringify(parsed, null, 2);
      setSchemaJson(jsonString);

      // Check if this is a standalone primitive schema
      if (isStandalonePrimitiveSchema(parsed)) {
        // Extract a name for this primitive from the URL or schema
        const urlPath = new URL(urlInput).pathname;
        const urlFilename = urlPath.split('/').pop() || '';
        const primitiveName = extractPrimitiveNameFromSchema(parsed, urlFilename);

        // Use the entire schema as the definition
        const defs = {
          [primitiveName]: parsed
        };

        setDefinitions(defs as Record<string, Record<string, unknown>>);
        setSelectedDefs(new Set([primitiveName]));
        setShowPreview(true);
        return;
      }

      // Otherwise, look for $defs or definitions
      const defs = {
        ...((parsed.$defs as Record<string, unknown>) || {}),
        ...((parsed.definitions as Record<string, unknown>) || {})
      };

      if (Object.keys(defs).length === 0) {
        setParseError('No definitions found. The URL must return a schema with $defs, definitions, or be a standalone type definition.');
        return;
      }

      setDefinitions(defs as Record<string, Record<string, unknown>>);
      setSelectedDefs(new Set(Object.keys(defs)));
      setShowPreview(true);
    } catch (err) {
      const error = err as Error;
      setParseError(`Failed to fetch from URL: ${error.message}`);
    } finally {
      setIsLoadingUrl(false);
    }
  };

  const handleParseSchema = () => {
    try {
      const parsed = JSON.parse(schemaJson);

      // Check if this is a standalone primitive schema
      if (isStandalonePrimitiveSchema(parsed)) {
        // Extract a name for this primitive
        const primitiveName = extractPrimitiveNameFromSchema(parsed);

        // Use the entire schema as the definition
        const defs = {
          [primitiveName]: parsed
        };

        setDefinitions(defs);
        setSelectedDefs(new Set([primitiveName]));
        setShowPreview(true);
        setParseError(null);
        return;
      }

      // Extract $defs or definitions
      const defs = {
        ...(parsed.$defs || {}),
        ...(parsed.definitions || {})
      };

      if (Object.keys(defs).length === 0) {
        setParseError('No definitions found. Schema must contain $defs, definitions, or be a standalone type definition.');
        return;
      }

      setDefinitions(defs);
      setSelectedDefs(new Set(Object.keys(defs))); // Select all by default
      setShowPreview(true);
      setParseError(null);
    } catch (err) {
      const error = err as Error;
      setParseError(`Invalid JSON: ${error.message}`);
    }
  };

  const toggleDefinition = (defName: string) => {
    const newSelected = new Set(selectedDefs);
    if (newSelected.has(defName)) {
      newSelected.delete(defName);
    } else {
      newSelected.add(defName);
    }
    setSelectedDefs(newSelected);
  };

  const handleImport = async () => {
    if (selectedDefs.size === 0) {
      onMessage('error', 'Please select at least one definition to import');
      return;
    }

    setImporting(true);

    try {
      // Construct a schema with $defs from our definitions
      // This handles both standalone schemas (which we've already converted to definitions)
      // and schemas that already had $defs/definitions
      const schemaForApi = {
        $defs: Object.fromEntries(
          Array.from(selectedDefs).map(defName => [defName, definitions[defName]])
        )
      };

      const response = await fetch('/api/primitives/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schema: schemaForApi,
          selected_definitions: Array.from(selectedDefs),
        }),
      });

      const data = await response.json();

      if (data.success) {
        const imported = data.imported || [];
        const skipped = data.skipped || [];
        const errors = data.errors || [];

        let message = `Imported ${imported.length} primitive(s)`;
        if (skipped.length > 0) {
          message += `, skipped ${skipped.length}`;
        }
        if (errors.length > 0) {
          message += `, ${errors.length} error(s)`;
        }

        onMessage('success', message);
        onComplete();
      } else {
        onMessage('error', data.error || 'Failed to import primitives');
      }
    } catch (error) {
      console.error('Error importing primitives:', error);
      onMessage('error', 'Failed to import primitives');
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-5xl h-[70vh] min-h-[70vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="w-5 h-5" />
            Import Primitives from JSON Schema
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4 flex-1 min-h-0 overflow-y-auto">
          {!showPreview ? (
            <Tabs value={importMethod} onValueChange={(v) => setImportMethod(v as 'fileOrUrl' | 'paste')}>
              <TabsList className="w-full h-auto p-0 rounded-none bg-transparent border-b border-gray-200 dark:border-gray-700 justify-start gap-0 mb-4">
                <TabsTrigger
                  value="fileOrUrl"
                  className="flex items-center gap-2 rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
                >
                  <Upload className="w-4 h-4" />
                  File or URL
                </TabsTrigger>
                <TabsTrigger
                  value="paste"
                  className="flex items-center gap-2 rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
                >
                  <FileCode className="w-4 h-4" />
                  Paste JSON
                </TabsTrigger>
              </TabsList>

              <TabsContent value="fileOrUrl" className="mt-0">
                <div className="space-y-6">
                  <div className="space-y-4">
                    <Label className="text-base">Upload file</Label>
                    {!file ? (
                      <div
                        className={`
                          border-2 border-dashed rounded-lg p-8 text-center cursor-pointer
                          transition-colors duration-200
                          ${isDragging
                            ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                            : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-500'
                          }
                        `}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <Upload className="w-12 h-12 mx-auto mb-4 text-gray-400 dark:text-gray-500" />
                        <p className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                          Drag & Drop or Click to Select
                        </p>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          JSON Schema file (.json, .yaml, .yml) with $defs or definitions
                        </p>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept=".json,.yaml,.yml"
                          className="hidden"
                          onChange={(e) => {
                            const selectedFile = e.target.files?.[0];
                            if (selectedFile) {
                              handleFileSelect(selectedFile);
                            }
                          }}
                        />
                      </div>
                    ) : (
                      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-3">
                            <FileJson className="w-8 h-8 text-green-500" />
                            <div>
                              <p className="font-medium text-gray-900 dark:text-white">{file.name}</p>
                              <p className="text-sm text-gray-500 dark:text-gray-400">
                                {(file.size / 1024).toFixed(1)} KB
                              </p>
                            </div>
                          </div>
                          <Button variant="ghost" size="icon" onClick={clearFile}>
                            <X className="w-4 h-4" />
                          </Button>
                        </div>
                        {isLoadingFile && (
                          <p className="text-sm text-indigo-600 dark:text-indigo-400">
                            Processing file...
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="relative">
                    <div className="absolute inset-0 flex items-center" aria-hidden="true">
                      <div className="w-full border-t border-gray-200 dark:border-gray-600" />
                    </div>
                    <div className="relative flex justify-center text-sm">
                      <span className="bg-white dark:bg-gray-800 px-2 text-gray-500 dark:text-gray-400">or</span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <Label htmlFor="schema-url" className="text-base">Fetch from URL</Label>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Enter the URL of a JSON Schema file to import primitives from
                    </p>
                    <div className="flex gap-2">
                      <Input
                        id="schema-url"
                        type="url"
                        placeholder="https://example.com/schema.json"
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        className="flex-1"
                        disabled={isLoadingUrl}
                      />
                      <Button
                        onClick={handleUrlFetch}
                        disabled={!urlInput.trim() || isLoadingUrl}
                      >
                        {isLoadingUrl ? 'Fetching...' : 'Fetch'}
                      </Button>
                    </div>
                  </div>

                  {parseError && (
                    <Alert variant="error">
                      <AlertCircle className="h-4 w-4" />
                      <span>{parseError}</span>
                    </Alert>
                  )}

                  <div className="text-sm text-gray-500 dark:text-gray-400 space-y-1">
                    <p className="font-medium">Supported formats:</p>
                    <ul className="list-disc list-inside pl-2">
                      <li>JSON Schema with $defs or definitions</li>
                      <li>Standalone type definitions (e.g., ISO primitives)</li>
                      <li>JSON or YAML format</li>
                    </ul>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="paste" className="mt-0">
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>JSON Schema with $defs or definitions</Label>
                    <div className="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden">
                      <MonacoEditor
                        height="400px"
                        language="json"
                        theme="vs-dark"
                        value={schemaJson}
                        onChange={handleSchemaChange}
                        options={{
                          minimap: { enabled: false },
                          scrollBeyondLastLine: false,
                          fontSize: 13,
                        }}
                      />
                    </div>
                    {parseError && (
                      <Alert variant="error">
                        <AlertCircle className="h-4 w-4" />
                        <span>{parseError}</span>
                      </Alert>
                    )}
                  </div>

                  <div className="flex justify-end">
                    <Button onClick={handleParseSchema} disabled={!schemaJson.trim()}>
                      Parse Schema
                    </Button>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          ) : (
            <>
              <Alert variant="default">
                <CheckCircle className="h-4 w-4" />
                <span>Found {Object.keys(definitions).length} definition(s). Select which ones to import:</span>
              </Alert>

              <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                <div className="max-h-96 overflow-y-auto">
                  {Object.entries(definitions).map(([defName, defSchema]) => {
                    const schema = defSchema as Record<string, unknown>;
                    const schemaType = determineCategoryFromSchema(schema);
                    const schemaDescription = schema.description as string | undefined;
                    const schemaTitle = schema.title as string | undefined;

                    return (
                      <div
                        key={defName}
                        className="border-b border-gray-200 dark:border-gray-700 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-900/50"
                      >
                        <label className="flex items-start gap-3 p-4 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={selectedDefs.has(defName)}
                            onChange={() => toggleDefinition(defName)}
                            className="mt-1 w-4 h-4 text-indigo-600 rounded"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <FileCode className="w-4 h-4 text-indigo-600" />
                              <span className="font-medium text-gray-900 dark:text-white">{defName}</span>
                              <span className="text-xs text-gray-500 dark:text-gray-400">
                                ({schemaType})
                              </span>
                            </div>
                            {schemaTitle && schemaTitle !== defName && (
                              <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{schemaTitle}</p>
                            )}
                            {schemaDescription && (
                              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{schemaDescription}</p>
                            )}
                            <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded overflow-x-auto max-h-48 overflow-y-auto">
                              {JSON.stringify(defSchema, null, 2)}
                            </pre>
                          </div>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                <span>{selectedDefs.size} of {Object.keys(definitions).length} selected</span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    if (selectedDefs.size === Object.keys(definitions).length) {
                      setSelectedDefs(new Set());
                    } else {
                      setSelectedDefs(new Set(Object.keys(definitions)));
                    }
                  }}
                >
                  {selectedDefs.size === Object.keys(definitions).length ? 'Deselect All' : 'Select All'}
                </Button>
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          {showPreview && (
            <Button
              variant="secondary"
              onClick={() => {
                setShowPreview(false);
                setDefinitions({});
                setSelectedDefs(new Set());
                setParseError(null);
                if (importMethod === 'fileOrUrl') {
                  clearFile();
                  setUrlInput('');
                  setSchemaJson('');
                } else {
                  setSchemaJson('');
                }
              }}
            >
              Back
            </Button>
          )}
          <Button variant="secondary" onClick={onClose} disabled={importing}>
            Cancel
          </Button>
          {showPreview && (
            <Button onClick={handleImport} disabled={importing || selectedDefs.size === 0}>
              {importing ? 'Importing...' : `Import ${selectedDefs.size} Selected`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

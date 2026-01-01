'use client';

import React, { useState, useEffect } from 'react';
import { X, Trash2, Check, ChevronDown } from 'lucide-react';
import * as ScrollArea from '@radix-ui/react-scroll-area';
import * as Popover from '@radix-ui/react-popover';
import Editor from '@monaco-editor/react';
import { extractPathVariables, PathVariable, PathNodeData } from '@/app/components/ade/paths/PathNode';
import { updatePathAction, deletePathAction, getTagsForProjectAction } from '../actions';
import { useStudio } from '../../StudioContext';

interface Tag {
  id: string;
  name: string;
  color: string;
  description?: string;
}

interface PropertiesPanelProps {
  selectedNode: any | null;
  onClose: () => void;
}

export default function PropertiesPanel({ selectedNode, onClose }: PropertiesPanelProps) {
  const { selectedProjectId } = useStudio();
  const [pathPattern, setPathPattern] = useState('');
  const [pathVariables, setPathVariables] = useState<PathVariable[]>([]);
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]); // Array of tag IDs
  const [deprecated, setDeprecated] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [isTagDropdownOpen, setIsTagDropdownOpen] = useState(false);

  // Store original values for cancel functionality
  const [originalValues, setOriginalValues] = useState({
    pathPattern: '',
    pathVariables: [] as PathVariable[],
    summary: '',
    description: '',
    selectedTags: [] as string[],
    deprecated: false,
  });

  // Load available tags for the project
  useEffect(() => {
    if (!selectedProjectId) {
      setAvailableTags([]);
      return;
    }

    const loadTags = async () => {
      try {
        const result = await getTagsForProjectAction(selectedProjectId);
        const tags = JSON.parse(result);
        setAvailableTags(tags);
      } catch (error) {
        console.error('Error loading tags:', error);
        setAvailableTags([]);
      }
    };

    loadTags();
  }, [selectedProjectId]);

  // Detect dark mode from system preferences
  useEffect(() => {
    const darkModeMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    setIsDarkMode(darkModeMediaQuery.matches);

    const handleChange = (e: MediaQueryListEvent) => {
      setIsDarkMode(e.matches);
    };

    darkModeMediaQuery.addEventListener('change', handleChange);
    return () => darkModeMediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Initialize state when node is selected
  useEffect(() => {
    if (selectedNode?.data) {
      const data = selectedNode.data as PathNodeData;
      const newPathPattern = data.path || '';
      const newPathVariables = data.pathVariables || [];
      const newSummary = data.summary || '';
      const newDescription = data.description || '';
      const newSelectedTags = data.tags || []; // Array of tag IDs
      const newDeprecated = data.deprecated || false;

      setPathPattern(newPathPattern);
      setPathVariables(newPathVariables);
      setSummary(newSummary);
      setDescription(newDescription);
      setSelectedTags(newSelectedTags);
      setDeprecated(newDeprecated);

      // Store original values
      setOriginalValues({
        pathPattern: newPathPattern,
        pathVariables: JSON.parse(JSON.stringify(newPathVariables)), // Deep copy
        summary: newSummary,
        description: newDescription,
        selectedTags: [...newSelectedTags],
        deprecated: newDeprecated,
      });

      // Reset unsaved changes flag
      setHasUnsavedChanges(false);
    }
  }, [selectedNode?.id]);

  // Dynamically extract and update path variables when path pattern changes
  useEffect(() => {
    if (selectedNode?.data?.nodeType === 'path') {
      const extractedVarNames = extractPathVariables(pathPattern);

      // Create new variables for any that don't exist, preserve existing ones
      const updatedVariables: PathVariable[] = extractedVarNames.map(varName => {
        const existing = pathVariables.find(v => v.name === varName);
        return existing || {
          name: varName,
          description: '',
          type: 'string',
          required: true,
          example: '',
        };
      });

      // Only update if the variables have actually changed
      const hasChanged =
        updatedVariables.length !== pathVariables.length ||
        updatedVariables.some((v, i) => v.name !== pathVariables[i]?.name);

      if (hasChanged) {
        setPathVariables(updatedVariables);

        // Update the node data
        if (selectedNode?.updateData) {
          selectedNode.updateData({
            path: pathPattern,
            pathVariables: updatedVariables,
          });
        }
      }
    }
  }, [pathPattern, selectedNode?.data?.nodeType]);

  // Handle path pattern change
  const handlePathPatternChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newPath = e.target.value;
    setPathPattern(newPath);
    setHasUnsavedChanges(true);
  };

  // Handle variable field changes
  const handleVariableChange = (index: number, field: keyof PathVariable, value: any) => {
    const updatedVariables = [...pathVariables];
    updatedVariables[index] = { ...updatedVariables[index], [field]: value };
    setPathVariables(updatedVariables);
    setHasUnsavedChanges(true);
  };

  // Handle other field changes
  const handleFieldChange = (field: keyof PathNodeData, value: any) => {
    setHasUnsavedChanges(true);
  };

  // Cancel changes - revert to original values
  const handleCancel = () => {
    setPathPattern(originalValues.pathPattern);
    setPathVariables(JSON.parse(JSON.stringify(originalValues.pathVariables)));
    setSummary(originalValues.summary);
    setDescription(originalValues.description);
    setSelectedTags([...originalValues.selectedTags]);
    setDeprecated(originalValues.deprecated);
    setHasUnsavedChanges(false);
  };

  // Save changes to database
  const handleSave = async () => {
    if (!selectedNode?.data?.dbPathId || selectedNode?.data?.nodeType !== 'path') {
      return;
    }

    setIsSaving(true);
    try {
      // Update node data in canvas
      if (selectedNode?.updateData) {
        selectedNode.updateData({
          path: pathPattern,
          pathVariables: pathVariables,
          summary: summary,
          description: description,
          tags: selectedTags,
          deprecated: deprecated,
        });
      }

      // Save to database
      const updates: any = {
        path: pathPattern,
        summary: summary,
        description: description,
      };

      await updatePathAction(selectedNode.data.dbPathId, updates);

      // Update original values to match saved values
      setOriginalValues({
        pathPattern,
        pathVariables: JSON.parse(JSON.stringify(pathVariables)),
        summary,
        description,
        selectedTags: [...selectedTags],
        deprecated,
      });

      setHasUnsavedChanges(false);
    } catch (error) {
      console.error('Error saving path changes:', error);
    } finally {
      setIsSaving(false);
    }
  };
  if (!selectedNode) {
    return (
      <div className="w-80 h-full border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-center">
        <div className="text-center px-6">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
            <svg className="w-8 h-8 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Select a node to view its properties
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 h-full border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wide">
          {selectedNode.type || 'Node'} Properties
        </h3>
        <button
          onClick={onClose}
          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
        >
          <X className="h-4 w-4 text-gray-500 dark:text-gray-400" />
        </button>
      </div>

      {/* Content */}
      <ScrollArea.Root className="flex-1 overflow-hidden">
        <ScrollArea.Viewport className="h-full w-full">
          <div className="p-4 space-y-6">
            {/* Path Pattern Section */}
            {selectedNode?.data?.nodeType === 'path' && (
              <>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                    Path Pattern
                  </label>
                  <input
                    type="text"
                    value={pathPattern}
                    onChange={handlePathPatternChange}
                    placeholder="/api/v1/{userId}/orders/{orderId}"
                    className="w-full px-3 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400 font-mono"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    Use {'{'}variable{'}'} syntax for path parameters
                  </p>
                </div>

                {/* Path Variables Section - Auto-extracted */}
                {pathVariables.length > 0 && (
                  <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                    <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide flex items-center justify-between">
                      <span>Path Variables ({pathVariables.length})</span>
                      <span className="text-xs font-normal text-gray-500 dark:text-gray-400 normal-case">Auto-detected</span>
                    </h4>
                    <div className="space-y-4">
                      {pathVariables.map((variable, index) => (
                        <div key={variable.name} className="p-3 bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 space-y-3">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-mono font-semibold text-indigo-600 dark:text-indigo-400">
                              {'{' + variable.name + '}'}
                            </span>
                            <span className={`px-2 py-0.5 text-xs rounded ${variable.required ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300' : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>
                              {variable.required ? 'Required' : 'Optional'}
                            </span>
                          </div>

                          <div>
                            <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                              Description
                            </label>
                            <input
                              type="text"
                              value={variable.description}
                              onChange={(e) => handleVariableChange(index, 'description', e.target.value)}
                              placeholder="Describe this parameter..."
                              className="w-full px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-xs text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
                            />
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Type
                              </label>
                              <select
                                value={variable.type}
                                onChange={(e) => handleVariableChange(index, 'type', e.target.value)}
                                className="w-full px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-xs text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
                              >
                                <option value="string">string</option>
                                <option value="integer">integer</option>
                                <option value="number">number</option>
                                <option value="boolean">boolean</option>
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Example
                              </label>
                              <input
                                type="text"
                                value={variable.example || ''}
                                onChange={(e) => handleVariableChange(index, 'example', e.target.value)}
                                placeholder="e.g., 12345"
                                className="w-full px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-xs text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
                              />
                            </div>
                          </div>

                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={variable.required}
                              onChange={(e) => handleVariableChange(index, 'required', e.target.checked)}
                              className="w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                            />
                            <span className="text-xs text-gray-700 dark:text-gray-300">Required parameter</span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
                    Metadata
                  </h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                        Summary
                      </label>
                      <input
                        type="text"
                        value={summary}
                        onChange={(e) => {
                          setSummary(e.target.value);
                          handleFieldChange('summary', e.target.value);
                        }}
                        placeholder="Brief description"
                        className="w-full px-3 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                        Description (Markdown supported)
                      </label>
                      <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                        <Editor
                          height="200px"
                          language="markdown"
                          value={description}
                          onChange={(value) => {
                            const newValue = value || '';
                            setDescription(newValue);
                            handleFieldChange('description', newValue);
                          }}
                          theme={isDarkMode ? 'vs-dark' : 'light'}
                          options={{
                            minimap: { enabled: false },
                            scrollBeyondLastLine: false,
                            fontSize: 12,
                            lineNumbers: 'off',
                            wordWrap: 'on',
                            wrappingStrategy: 'advanced',
                            padding: { top: 8, bottom: 8 },
                            folding: false,
                            glyphMargin: false,
                            lineDecorationsWidth: 0,
                            lineNumbersMinChars: 0,
                            renderLineHighlight: 'none',
                            contextmenu: true,
                            automaticLayout: true,
                          }}
                        />
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Supports Markdown formatting (bold, italic, lists, links, etc.)
                      </p>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                        Tags
                      </label>
                      <Popover.Root open={isTagDropdownOpen} onOpenChange={setIsTagDropdownOpen}>
                        <Popover.Trigger asChild>
                          <button
                            type="button"
                            className="w-full px-3 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-left flex items-center justify-between hover:border-gray-300 dark:hover:border-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
                          >
                            <div className="flex-1 flex flex-wrap gap-1">
                              {selectedTags.length === 0 ? (
                                <span className="text-gray-400 dark:text-gray-500">Select tags...</span>
                              ) : (
                                selectedTags.map(tagId => {
                                  const tag = availableTags.find(t => t.id === tagId);
                                  return tag ? (
                                    <span
                                      key={tagId}
                                      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                                      style={{
                                        backgroundColor: `${tag.color}20`,
                                        color: tag.color,
                                        border: `1px solid ${tag.color}40`
                                      }}
                                    >
                                      {tag.name}
                                    </span>
                                  ) : null;
                                })
                              )}
                            </div>
                            <ChevronDown className="h-4 w-4 text-gray-400 shrink-0 ml-2" />
                          </button>
                        </Popover.Trigger>
                        <Popover.Portal>
                          <Popover.Content
                            className="z-[9999] w-[260px] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl overflow-hidden"
                            sideOffset={4}
                            align="start"
                          >
                            <div className="max-h-[200px] overflow-y-auto p-1">
                              {availableTags.length === 0 ? (
                                <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400 text-center">
                                  No tags defined for this project
                                </div>
                              ) : (
                                availableTags.map(tag => {
                                  const isSelected = selectedTags.includes(tag.id);
                                  return (
                                    <button
                                      key={tag.id}
                                      type="button"
                                      onClick={() => {
                                        const newTags = isSelected
                                          ? selectedTags.filter(id => id !== tag.id)
                                          : [...selectedTags, tag.id];
                                        setSelectedTags(newTags);
                                        setHasUnsavedChanges(true);
                                      }}
                                      className={`w-full px-3 py-2 flex items-center gap-2 text-left text-sm rounded transition-colors ${
                                        isSelected 
                                          ? 'bg-indigo-50 dark:bg-indigo-900/30' 
                                          : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                                      }`}
                                    >
                                      <div
                                        className="w-3 h-3 rounded-full shrink-0"
                                        style={{ backgroundColor: tag.color }}
                                      />
                                      <span className="flex-1 text-gray-900 dark:text-white truncate">
                                        {tag.name}
                                      </span>
                                      {isSelected && (
                                        <Check className="h-4 w-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
                                      )}
                                    </button>
                                  );
                                })
                              )}
                            </div>
                          </Popover.Content>
                        </Popover.Portal>
                      </Popover.Root>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Select tags to group this path logically
                      </p>
                    </div>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
                    Options
                  </h4>
                  <div className="space-y-2">
                    <label className={`flex items-start gap-3 cursor-pointer p-3 rounded-lg border-2 transition-colors ${
                      deprecated 
                        ? 'border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-900/20' 
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}>
                      <input
                        type="checkbox"
                        checked={deprecated}
                        onChange={(e) => {
                          setDeprecated(e.target.checked);
                          handleFieldChange('deprecated', e.target.checked);
                        }}
                        className="w-5 h-5 text-red-600 border-gray-300 rounded focus:ring-red-500 mt-0.5"
                      />
                      <div className="flex-1">
                        <span className={`text-sm font-medium ${deprecated ? 'text-red-700 dark:text-red-300' : 'text-gray-700 dark:text-gray-300'}`}>
                          Mark as Deprecated
                        </span>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          Deprecated paths will be displayed with a strikethrough and warning badge
                        </p>
                      </div>
                    </label>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <button className="w-full px-4 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm font-medium text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors flex items-center justify-center gap-2">
                    <Trash2 className="h-4 w-4" />
                    Delete Path
                  </button>
                </div>
              </>
            )}

            {/* Method Node Properties */}
            {selectedNode?.data?.nodeType === 'method' && (
              <>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                    Operation ID
                  </label>
                  <input
                    type="text"
                    defaultValue="operationName"
                    className="w-full px-3 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
                  />
                  <button className="mt-1 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300">
                    💡 Auto-generate
                  </button>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
                    Request
                  </h4>
                  <div className="space-y-2">
                    <button className="w-full px-3 py-2 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-500 dark:text-gray-400 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors">
                      + Add Query Param
                    </button>
                    <button className="w-full px-3 py-2 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-500 dark:text-gray-400 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors">
                      + Add Header Param
                    </button>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
                    Responses
                  </h4>
                  <div className="space-y-2">
                    <button className="w-full px-3 py-2 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-500 dark:text-gray-400 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors">
                      + Add Response
                    </button>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <button className="w-full px-4 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm font-medium text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors">
                    🗑️ Delete Operation
                  </button>
                </div>
              </>
            )}

            {/* Generic Node Info */}
            {!['path', 'method'].includes(selectedNode?.data?.nodeType) && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                <p>Node ID: {selectedNode?.id}</p>
                <p className="mt-2">Type: {selectedNode?.data?.nodeType}</p>
              </div>
            )}
          </div>
        </ScrollArea.Viewport>
        <ScrollArea.Scrollbar
          className="flex touch-none select-none p-0.5 bg-gray-100 dark:bg-gray-900 transition-colors hover:bg-gray-200 dark:hover:bg-gray-800"
          orientation="vertical"
        >
          <ScrollArea.Thumb className="flex-1 bg-gray-400 dark:bg-gray-600 rounded-full relative before:content-[''] before:absolute before:top-1/2 before:left-1/2 before:-translate-x-1/2 before:-translate-y-1/2 before:w-full before:h-full before:min-w-11 before:min-h-11" />
        </ScrollArea.Scrollbar>
      </ScrollArea.Root>

      {/* Footer with Cancel/Save buttons - only show for path nodes with unsaved changes */}
      {selectedNode?.data?.nodeType === 'path' && (
        <div className="border-t border-gray-200 dark:border-gray-700 px-4 py-3 bg-gray-50 dark:bg-gray-900/50">
          <div className="flex gap-2">
            <button
              onClick={handleCancel}
              disabled={!hasUnsavedChanges}
              className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!hasUnsavedChanges || isSaving}
              className="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isSaving ? (
                <>
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Saving...
                </>
              ) : (
                'Save Changes'
              )}
            </button>
          </div>
          {hasUnsavedChanges && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2 text-center">
              You have unsaved changes
            </p>
          )}
        </div>
      )}
    </div>
  );
}


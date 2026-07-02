'use client';

import React, { useState, useEffect } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, Search, Package, Clock, Star, ChevronRight, Plus, Filter, Tag } from 'lucide-react';
import { Button } from '../../ui/Button';
import { getPropertyTemplates, getPropertyTemplateCategories, searchPropertyTemplates, usePropertyTemplate } from '../../../../../lib/db/helper';

interface PropertyTemplate {
  id: string;
  name: string;
  description: string | null;
  category: string;
  schema: any;
  tags: string[];
  is_system: boolean;
  is_public: boolean;
  usage_count: number;
  created_at: string;
}

interface PropertyTemplateCategory {
  category: string;
  count: number;
}

interface PropertyTemplateBrowserDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (property: any) => void;
  projectId: string;
  tenantId?: string | null;
}

// Category display configuration
const categoryConfig: Record<string, { label: string; icon: string; color: string }> = {
  identifiers: { label: 'Identifiers', icon: '🔑', color: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' },
  timestamps: { label: 'Timestamps', icon: '⏰', color: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300' },
  audit: { label: 'Audit Fields', icon: '📋', color: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300' },
  status: { label: 'Status Fields', icon: '🚦', color: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' },
  contact: { label: 'Contact Info', icon: '📧', color: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300' },
  address: { label: 'Address Fields', icon: '📍', color: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300' },
  money: { label: 'Money & Currency', icon: '💰', color: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300' },
  geolocation: { label: 'Geolocation', icon: '🌍', color: 'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300' },
  i18n: { label: 'Internationalization', icon: '🌐', color: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300' },
  pagination: { label: 'Pagination', icon: '📄', color: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300' },
  search: { label: 'Search & Filter', icon: '🔍', color: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300' },
};

const getCategoryConfig = (category: string) => {
  return categoryConfig[category] || {
    label: category.charAt(0).toUpperCase() + category.slice(1),
    icon: '📦',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300'
  };
};

const PropertyTemplateBrowserDialog: React.FC<PropertyTemplateBrowserDialogProps> = ({
  open,
  onClose,
  onSuccess,
  projectId,
  tenantId,
}) => {
  const [templates, setTemplates] = useState<PropertyTemplate[]>([]);
  const [categories, setCategories] = useState<PropertyTemplateCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<PropertyTemplate | null>(null);
  const [customName, setCustomName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load templates and categories when dialog opens
  useEffect(() => {
    if (open) {
      loadCategories();
      loadTemplates();
    }
  }, [open, tenantId]);

  // Reload templates when category changes
  useEffect(() => {
    if (open) {
      if (searchQuery.trim()) {
        handleSearch();
      } else {
        loadTemplates();
      }
    }
  }, [selectedCategory]);

  const loadCategories = async () => {
    try {
      const result = JSON.parse(await getPropertyTemplateCategories(tenantId));
      if (result.success) {
        setCategories(result.categories);
      }
    } catch (error) {
      console.error('Error loading categories:', error);
    }
  };

  const loadTemplates = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = JSON.parse(await getPropertyTemplates(tenantId, selectedCategory));
      if (result.success) {
        // Sort templates alphabetically by name
        const sortedTemplates = result.templates.sort((a: PropertyTemplate, b: PropertyTemplate) =>
          a.name.localeCompare(b.name)
        );
        setTemplates(sortedTemplates);
      } else {
        setError(result.error || 'Failed to load templates');
      }
    } catch (error: any) {
      setError(error.message || 'Failed to load templates');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadTemplates();
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const result = JSON.parse(await searchPropertyTemplates(searchQuery.trim(), tenantId, selectedCategory));
      if (result.success) {
        // Sort search results alphabetically by name
        const sortedTemplates = result.templates.sort((a: PropertyTemplate, b: PropertyTemplate) =>
          a.name.localeCompare(b.name)
        );
        setTemplates(sortedTemplates);
      } else {
        setError(result.error || 'Search failed');
      }
    } catch (error: any) {
      setError(error.message || 'Search failed');
    } finally {
      setIsLoading(false);
    }
  };

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (open) {
        handleSearch();
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleAddTemplate = async () => {
    if (!selectedTemplate || !projectId) return;

    setIsAdding(true);
    setError(null);
    try {
      const result = JSON.parse(await usePropertyTemplate(
        selectedTemplate.id,
        projectId,
        customName.trim() || null
      ));

      if (result.success) {
        onSuccess?.(result.property);
        // Don't close dialog - allow adding more properties
        // Reset the custom name to the template's default name for next addition
        setCustomName(selectedTemplate.name);
        // Show success message briefly
        setError(`✓ Property "${result.property.name}" added successfully!`);
        setTimeout(() => setError(null), 3000);
      } else {
        setError(result.error || 'Failed to add property');
      }
    } catch (error: any) {
      setError(error.message || 'Failed to add property');
    } finally {
      setIsAdding(false);
    }
  };

  const handleClose = () => {
    setSelectedTemplate(null);
    setCustomName('');
    setSearchQuery('');
    setSelectedCategory(null);
    setError(null);
    onClose();
  };

  const handleSelectTemplate = (template: PropertyTemplate) => {
    setSelectedTemplate(template);
    setCustomName(template.name);
  };

  // Format schema for preview
  const formatSchemaPreview = (schema: any) => {
    if (!schema) return 'No schema';

    const parts: string[] = [];

    if (schema.type) {
      if (Array.isArray(schema.type)) {
        parts.push(`Type: ${schema.type.join(' | ')}`);
      } else {
        parts.push(`Type: ${schema.type}`);
      }
    }

    if (schema.format) parts.push(`Format: ${schema.format}`);
    if (schema.pattern) parts.push(`Pattern: ${schema.pattern}`);
    if (schema.enum) parts.push(`Enum: ${schema.enum.join(', ')}`);
    if (schema.minimum !== undefined) parts.push(`Min: ${schema.minimum}`);
    if (schema.maximum !== undefined) parts.push(`Max: ${schema.maximum}`);
    if (schema.minLength !== undefined) parts.push(`Min length: ${schema.minLength}`);
    if (schema.maxLength !== undefined) parts.push(`Max length: ${schema.maxLength}`);
    if (schema.default !== undefined) parts.push(`Default: ${JSON.stringify(schema.default)}`);
    if (schema.readOnly) parts.push('Read-only');

    return parts.length > 0 ? parts.join(' • ') : 'No constraints';
  };

  return (
    <Dialog.Root open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10000] w-[80%] h-[90vh] min-h-[90vh] bg-white dark:bg-gray-900 rounded-xl shadow-2xl flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-gray-800 dark:to-gray-800">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-indigo-100 dark:bg-indigo-900/50 rounded-lg">
                <Package className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white">
                  Property Template Library
                </Dialog.Title>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Browse and add pre-built property templates to your project
                </p>
              </div>
            </div>
            <Dialog.Close asChild>
              <button className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <X className="h-5 w-5 text-gray-500 dark:text-gray-400" />
              </button>
            </Dialog.Close>
          </div>

          {/* Content */}
          <div className="flex flex-1 overflow-hidden">
            {/* Sidebar - its own column */}
            <div className="w-56 shrink-0 border-r border-gray-200 dark:border-gray-700 flex flex-col bg-gray-50 dark:bg-gray-800/50">
              <div className="p-3 border-b border-gray-200 dark:border-gray-700">
                <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Categories
                </h3>
              </div>
              <div className="flex-1 overflow-y-auto p-2">
                <button
                  onClick={() => setSelectedCategory(null)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    selectedCategory === null
                      ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 font-medium'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                  }`}
                >
                  <Filter className="h-4 w-4" />
                  <span>All Categories</span>
                  <span className="ml-auto text-xs text-gray-500 dark:text-gray-500">
                    {templates.length}
                  </span>
                </button>

                {categories.map((cat) => {
                  const config = getCategoryConfig(cat.category);
                  return (
                    <button
                      key={cat.category}
                      onClick={() => setSelectedCategory(cat.category)}
                      className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                        selectedCategory === cat.category
                          ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 font-medium'
                          : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                      }`}
                    >
                      <span>{config.icon}</span>
                      <span className="truncate">{config.label}</span>
                      <span className="ml-auto text-xs text-gray-500 dark:text-gray-500">
                        {cat.count}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Templates List - 50% of remaining space */}
            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
              {/* Search Bar */}
              <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search templates by name, description, or tags..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
                  />
                </div>
              </div>

              {/* Template List */}
              <div className="flex-1 overflow-y-auto p-4">
                {isLoading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                  </div>
                ) : error ? (
                  <div className="text-center py-8 text-red-500 dark:text-red-400">
                    {error}
                  </div>
                ) : templates.length === 0 ? (
                  <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                    No templates found
                  </div>
                ) : (
                  // Show all templates alphabetically (works for both single category and all categories)
                  <div className="space-y-2">
                    {templates.map((template) => (
                      <TemplateCard
                        key={template.id}
                        template={template}
                        isSelected={selectedTemplate?.id === template.id}
                        onClick={() => handleSelectTemplate(template)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Detail panel - 50% of remaining space */}
            <div className="flex-1 min-w-0 border-l border-gray-200 dark:border-gray-700 flex flex-col bg-gray-50 dark:bg-gray-800/50">
              {selectedTemplate ? (
                <>
                  <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">
                      Template Preview
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      Customize and add to your project
                    </p>
                  </div>

                  <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {/* Template Info */}
                    <div>
                      <h4 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                        {selectedTemplate.name}
                      </h4>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getCategoryConfig(selectedTemplate.category).color}`}>
                        {getCategoryConfig(selectedTemplate.category).icon} {getCategoryConfig(selectedTemplate.category).label}
                      </span>
                    </div>

                    {selectedTemplate.description && (
                      <p className="text-sm text-gray-600 dark:text-gray-400">
                        {selectedTemplate.description}
                      </p>
                    )}

                    {/* Properties Preview (for object types) */}
                    {selectedTemplate.schema?.type === 'object' && selectedTemplate.schema?.properties && (
                      <div>
                        <h5 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                          Properties
                        </h5>
                        <div className="space-y-2">
                          {Object.entries(selectedTemplate.schema.properties).map(([name, prop]: [string, any]) => {
                            const isRequired = selectedTemplate.schema.required?.includes(name);
                            const typeArr = Array.isArray(prop.type) ? prop.type : (prop.type ? [prop.type] : []);
                            const hasNull = typeArr.includes('null');
                            const isOptional = hasNull;
                            const nonNull = typeArr.filter((t: string) => t !== 'null');
                            const displayType = nonNull.length
                              ? nonNull.join(' | ')
                              : (hasNull ? 'null' : (typeof prop.type === 'string' ? prop.type : '—'));
                            return (
                              <div
                                key={name}
                                className="px-3 py-2 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700"
                              >
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                                    {name}
                                  </span>
                                  {isRequired && (
                                    <span className="text-xs text-red-500">*</span>
                                  )}
                                  {isOptional && (
                                    <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
                                      optional
                                    </span>
                                  )}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                  {displayType}
                                  {prop.format && ` (${prop.format})`}
                                </div>
                                {prop.description && (
                                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    {prop.description}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Schema Preview */}
                    <div>
                      <h5 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                        Schema Definition
                      </h5>
                      <pre className="text-xs bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-auto max-h-40 text-gray-700 dark:text-gray-300">
                        {JSON.stringify(selectedTemplate.schema, null, 2)}
                      </pre>
                    </div>

                    {/* Tags */}
                    {selectedTemplate.tags && selectedTemplate.tags.length > 0 && (
                      <div>
                        <h5 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                          Tags
                        </h5>
                        <div className="flex flex-wrap gap-1">
                          {selectedTemplate.tags.map((tag, index) => (
                            <span
                              key={index}
                              className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                            >
                              <Tag className="h-3 w-3 mr-1" />
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Usage Stats */}
                    <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                      {selectedTemplate.is_system && (
                        <span className="flex items-center gap-1">
                          <Star className="h-3 w-3 text-amber-500" />
                          System Template
                        </span>
                      )}
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Used {selectedTemplate.usage_count} times
                      </span>
                    </div>

                    {/* Custom Name Input */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                        Property Name
                      </label>
                      <input
                        type="text"
                        value={customName}
                        onChange={(e) => setCustomName(e.target.value)}
                        placeholder={selectedTemplate.name}
                        className="w-full px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400 text-sm"
                      />
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Enter a custom name or use the default
                      </p>
                    </div>
                  </div>

                  {/* Add Button */}
                  <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                    {error && (
                      <p className={`text-sm mb-3 ${error.startsWith('✓') ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                        {error}
                      </p>
                    )}
                    <Button
                      onClick={handleAddTemplate}
                      disabled={isAdding}
                      className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white"
                    >
                      {isAdding ? (
                        <>
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                          Adding...
                        </>
                      ) : (
                        <>
                          <Plus className="h-4 w-4" />
                          Add to Project
                        </>
                      )}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center p-4">
                  <div className="text-center text-gray-500 dark:text-gray-400">
                    <Package className="h-12 w-12 mx-auto mb-3 opacity-50" />
                    <p className="text-sm">Select a template to preview</p>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Bottom Bar */}
          <div className="flex items-center justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
            <Button
              onClick={handleClose}
              variant="outline"
              className="px-6"
            >
              Close
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

// Template Card Component
const TemplateCard: React.FC<{
  template: PropertyTemplate;
  isSelected: boolean;
  onClick: () => void;
}> = ({ template, isSelected, onClick }) => {
  const config = getCategoryConfig(template.category);

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-3 rounded-lg border transition-all ${
        isSelected
          ? 'border-indigo-500 dark:border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 ring-2 ring-indigo-500/20'
          : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900 dark:text-white truncate">
              {template.name}
            </span>
            {template.is_system && (
              <Star className="h-3 w-3 text-amber-500 flex-shrink-0" />
            )}
          </div>
          {template.description && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
              {template.description}
            </p>
          )}
          <div className="flex items-center gap-2 mt-1.5">
            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs ${config.color}`}>
              {config.icon}
            </span>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {(() => {
                const schemaType = template.schema?.type;
                let displayType = 'object';
                let isOptional = false;

                if (Array.isArray(schemaType)) {
                  // Filter out 'null' to get the actual type(s)
                  const nonNullTypes = schemaType.filter((t: string) => t !== 'null');
                  isOptional = schemaType.includes('null');
                  displayType = nonNullTypes.join(' | ') || 'object';
                } else if (schemaType) {
                  displayType = schemaType;
                }

                return (
                  <>
                    {displayType}
                    {template.schema?.format && ` (${template.schema.format})`}
                    {isOptional && <span className="ml-1 text-amber-500 dark:text-amber-400">[optional]</span>}
                  </>
                );
              })()}
            </span>
          </div>
        </div>
        <ChevronRight className={`h-4 w-4 flex-shrink-0 transition-colors ${
          isSelected ? 'text-indigo-500 dark:text-indigo-400' : 'text-gray-400'
        }`} />
      </div>
    </button>
  );
};

export default PropertyTemplateBrowserDialog;


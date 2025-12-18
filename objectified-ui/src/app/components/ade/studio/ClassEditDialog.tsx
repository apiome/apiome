'use client';

import { useState, useEffect, useRef } from 'react';
import dynamic from 'next/dynamic';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Textarea } from '../../ui/Textarea';
import { Alert } from '../../ui/Alert';
import { Badge } from '../../ui/Badge';
import { Checkbox } from '../../ui/Checkbox';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../ui/Tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import { Copy, Download, RefreshCw, Check, Tag as TagIcon, ExternalLink, Settings, Layers, FileText, AlertTriangle, Code, Plus, Trash2, Regex, Link, ListChecks, X, ChevronDown } from 'lucide-react';
import YAML from 'yaml';
import jsf from 'json-schema-faker';
import { generateClassOpenApiSpec } from '../../../utils/openapi';
import { createClass, updateClass, assignTagToClass, removeTagFromClass, getTagsForClass } from '../../../../../lib/db/helper';
import { ExtensionsEditor } from './ExtensionsEditor';
import ConditionalSchemaBuilder, {
  ConditionalRule,
  conditionalRulesToJsonSchema,
  jsonSchemaToConditionalRules
} from './ConditionalSchemaBuilder';

// Custom hook for dark mode detection
const useDarkMode = () => {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark') ||
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', checkDarkMode);
    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener('change', checkDarkMode);
    };
  }, []);
  return isDark;
};

// Multi-select component for class references
interface MultiSelectProps {
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  colorScheme?: 'indigo' | 'amber' | 'purple';
}

const MultiSelect = ({ options, value, onChange, placeholder = 'Select...', disabled = false, colorScheme = 'indigo' }: MultiSelectProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const colorClasses: Record<string, string> = {
    indigo: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200',
    amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
    purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900/50 dark:text-purple-200',
  };

  const availableOptions = options.filter(opt => !value.includes(opt));

  return (
    <div ref={ref} className="relative">
      <div
        onClick={() => !disabled && setIsOpen(!isOpen)}
        className={`min-h-[38px] w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm cursor-pointer flex flex-wrap gap-1 items-center ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        {value.length === 0 ? (
          <span className="text-gray-400">{placeholder}</span>
        ) : (
          value.map((v) => (
            <span key={v} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${colorClasses[colorScheme]}`}>
              {v}
              {!disabled && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onChange(value.filter(item => item !== v));
                  }}
                  className="hover:bg-black/10 rounded"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </span>
          ))
        )}
        <ChevronDown className="h-4 w-4 ml-auto text-gray-400 shrink-0" />
      </div>
      {isOpen && availableOptions.length > 0 && (
        <div className="absolute z-50 mt-1 w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg max-h-48 overflow-auto">
          {availableOptions.map((opt) => (
            <div
              key={opt}
              onClick={() => onChange([...value, opt])}
              className="px-3 py-2 text-sm cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// Dynamically import Monaco Editor with SSR disabled
const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading editor...</div>
    </div>
  ),
});

interface ClassEditDialogProps {
  open: boolean;
  onClose: () => void;
  editingClassData: any;
  nodes: any[];
  isReadOnly?: boolean;
  onSave?: () => void;
  projectId?: string;
  versionId?: string;
  projectTags?: any[];
  projectMetadata?: {
    summary?: string;
    termsOfService?: string;
    contact?: {
      name?: string;
      url?: string;
      email?: string;
    };
    license?: {
      name?: string;
      identifier?: string;
      url?: string;
    };
  };
}

const ClassEditDialog = ({ open, onClose, editingClassData, nodes, isReadOnly = false, onSave, projectId = '', versionId = '', projectTags = [], projectMetadata }: ClassEditDialogProps) => {
  const isDark = useDarkMode();

  const [activeTab, setActiveTab] = useState('edit');
  const [exampleRefreshKey, setExampleRefreshKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openApiDoc, setOpenApiDoc] = useState<any>(null);
  const [loadingOpenApiDoc, setLoadingOpenApiDoc] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    allOf: [] as string[],
    anyOf: [] as string[],
    oneOf: [] as string[],
    discriminatorProperty: '',
    discriminatorUseAuto: true,
    discriminatorMapping: {} as Record<string, string>, // Maps property value to schema name
    additionalProperties: null as boolean | null,
    additionalPropertiesType: 'default' as 'default' | 'allow' | 'disallow' | 'schema',
    additionalPropertiesSchema: '', // Class name reference for "Must Match Schema" option
    patternProperties: [] as Array<{ pattern: string; schemaType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' | 'ref'; schemaRef: string }>,
    dependentSchemas: [] as Array<{ triggerProperty: string; schemaRef: string }>, // When triggerProperty is present, apply the referenced schema
    dependentRequired: [] as Array<{ triggerProperty: string; requiredProperties: string[] }>, // When triggerProperty is present, these properties become required
    deprecated: false,
    deprecationMessage: '',
    selectedTags: [] as string[],
    extensions: {} as Record<string, any>,
    externalDocsUrl: '',
    externalDocsDescription: '',
    conditionalRules: [] as ConditionalRule[],
    error: ''
  });

  // Reset view and form when dialog opens
  useEffect(() => {
    if (open) {
      setActiveTab('edit');
      setExampleRefreshKey(0);

      if (editingClassData) {
        // Edit mode - populate form with existing class data
        const schema = typeof editingClassData.schema === 'string'
          ? JSON.parse(editingClassData.schema)
          : editingClassData.schema || {};

        const allOf = schema.allOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];
        const anyOf = schema.anyOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];
        const oneOf = schema.oneOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];

        // Extract discriminator mapping if present
        const discriminatorMapping: Record<string, string> = {};
        if (schema.discriminator?.mapping) {
          Object.entries(schema.discriminator.mapping).forEach(([key, value]) => {
            // Extract schema name from reference (e.g., "#/components/schemas/Dog" -> "Dog")
            const schemaName = typeof value === 'string' ? value.split('/').pop() || '' : '';
            if (schemaName) {
              discriminatorMapping[key] = schemaName;
            }
          });
        }

        // Extract extensions (x- prefixed properties)
        const extensions: Record<string, any> = {};
        Object.keys(schema).forEach(key => {
          if (key.startsWith('x-')) {
            extensions[key] = schema[key];
          }
        });

        // Extract conditional rules (if/then/else) from schema
        let conditionalRules: ConditionalRule[] = [];
        // Check for if/then/else in allOf array
        if (schema.allOf && Array.isArray(schema.allOf)) {
          conditionalRules = jsonSchemaToConditionalRules(schema.allOf);
        }
        // Also check for top-level if/then/else
        if (schema.if) {
          const topLevelRules = jsonSchemaToConditionalRules([{
            if: schema.if,
            then: schema.then,
            else: schema.else
          }]);
          conditionalRules.push(...topLevelRules);
        }

        // Load tags for this class
        const loadTags = async () => {
          try {
            const result = await getTagsForClass(editingClassData.id);
            const classTags = JSON.parse(result);
            const tagIds = classTags.map((ct: any) => ct.tag_id);

            // Determine additionalProperties type and schema
            let additionalPropsType: 'default' | 'allow' | 'disallow' | 'schema' = 'default';
            let additionalPropsSchema = '';
            if (schema.additionalProperties !== undefined) {
              if (schema.additionalProperties === true) {
                additionalPropsType = 'allow';
              } else if (schema.additionalProperties === false) {
                additionalPropsType = 'disallow';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.$ref) {
                additionalPropsType = 'schema';
                additionalPropsSchema = schema.additionalProperties.$ref.split('/').pop() || '';
              }
            }

            // Extract patternProperties
            const patternPropsArray: Array<{ pattern: string; schemaType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' | 'ref'; schemaRef: string }> = [];
            if (schema.patternProperties && typeof schema.patternProperties === 'object') {
              Object.entries(schema.patternProperties).forEach(([pattern, schemaValue]: [string, any]) => {
                if (schemaValue.$ref) {
                  patternPropsArray.push({ pattern, schemaType: 'ref', schemaRef: schemaValue.$ref.split('/').pop() || '' });
                } else if (schemaValue.type) {
                  patternPropsArray.push({ pattern, schemaType: schemaValue.type, schemaRef: '' });
                } else {
                  patternPropsArray.push({ pattern, schemaType: 'string', schemaRef: '' });
                }
              });
            }

            // Extract dependentSchemas
            const dependentSchemasArray: Array<{ triggerProperty: string; schemaRef: string }> = [];
            if (schema.dependentSchemas && typeof schema.dependentSchemas === 'object') {
              Object.entries(schema.dependentSchemas).forEach(([triggerProperty, schemaValue]: [string, any]) => {
                if (schemaValue.$ref) {
                  dependentSchemasArray.push({ triggerProperty, schemaRef: schemaValue.$ref.split('/').pop() || '' });
                }
              });
            }

            // Extract dependentRequired
            const dependentRequiredArray: Array<{ triggerProperty: string; requiredProperties: string[] }> = [];
            if (schema.dependentRequired && typeof schema.dependentRequired === 'object') {
              Object.entries(schema.dependentRequired).forEach(([triggerProperty, requiredProps]: [string, any]) => {
                if (Array.isArray(requiredProps)) {
                  dependentRequiredArray.push({ triggerProperty, requiredProperties: requiredProps });
                }
              });
            }

            setFormData({
              name: editingClassData.name || '',
              description: editingClassData.description || '',
              allOf,
              anyOf,
              oneOf,
              discriminatorProperty: schema.discriminator?.propertyName || '',
              discriminatorUseAuto: !schema.discriminator?.mapping,
              discriminatorMapping,
              additionalProperties: schema.additionalProperties !== undefined ? schema.additionalProperties : null,
              additionalPropertiesType: additionalPropsType,
              additionalPropertiesSchema: additionalPropsSchema,
              patternProperties: patternPropsArray,
              dependentSchemas: dependentSchemasArray,
              dependentRequired: dependentRequiredArray,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: tagIds,
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              conditionalRules,
              error: ''
            });
          } catch (error) {
            console.error('Error loading tags:', error);
            // Determine additionalProperties type and schema for error case
            let additionalPropsType: 'default' | 'allow' | 'disallow' | 'schema' = 'default';
            let additionalPropsSchema = '';
            if (schema.additionalProperties !== undefined) {
              if (schema.additionalProperties === true) {
                additionalPropsType = 'allow';
              } else if (schema.additionalProperties === false) {
                additionalPropsType = 'disallow';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.$ref) {
                additionalPropsType = 'schema';
                additionalPropsSchema = schema.additionalProperties.$ref.split('/').pop() || '';
              }
            }
            // Extract patternProperties for error case
            const patternPropsArrayError: Array<{ pattern: string; schemaType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' | 'ref'; schemaRef: string }> = [];
            if (schema.patternProperties && typeof schema.patternProperties === 'object') {
              Object.entries(schema.patternProperties).forEach(([pattern, schemaValue]: [string, any]) => {
                if (schemaValue.$ref) {
                  patternPropsArrayError.push({ pattern, schemaType: 'ref', schemaRef: schemaValue.$ref.split('/').pop() || '' });
                } else if (schemaValue.type) {
                  patternPropsArrayError.push({ pattern, schemaType: schemaValue.type, schemaRef: '' });
                } else {
                  patternPropsArrayError.push({ pattern, schemaType: 'string', schemaRef: '' });
                }
              });
            }
            // Extract dependentSchemas for error case
            const dependentSchemasArrayError: Array<{ triggerProperty: string; schemaRef: string }> = [];
            if (schema.dependentSchemas && typeof schema.dependentSchemas === 'object') {
              Object.entries(schema.dependentSchemas).forEach(([triggerProperty, schemaValue]: [string, any]) => {
                if (schemaValue.$ref) {
                  dependentSchemasArrayError.push({ triggerProperty, schemaRef: schemaValue.$ref.split('/').pop() || '' });
                }
              });
            }
            // Extract dependentRequired for error case
            const dependentRequiredArrayError: Array<{ triggerProperty: string; requiredProperties: string[] }> = [];
            if (schema.dependentRequired && typeof schema.dependentRequired === 'object') {
              Object.entries(schema.dependentRequired).forEach(([triggerProperty, requiredProps]: [string, any]) => {
                if (Array.isArray(requiredProps)) {
                  dependentRequiredArrayError.push({ triggerProperty, requiredProperties: requiredProps });
                }
              });
            }
            setFormData({
              name: editingClassData.name || '',
              description: editingClassData.description || '',
              allOf,
              anyOf,
              oneOf,
              discriminatorProperty: schema.discriminator?.propertyName || '',
              discriminatorUseAuto: !schema.discriminator?.mapping,
              discriminatorMapping,
              additionalProperties: schema.additionalProperties !== undefined ? schema.additionalProperties : null,
              additionalPropertiesType: additionalPropsType,
              additionalPropertiesSchema: additionalPropsSchema,
              patternProperties: patternPropsArrayError,
              dependentSchemas: dependentSchemasArrayError,
              dependentRequired: dependentRequiredArrayError,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: [],
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              conditionalRules,
              error: ''
            });
          }
        };

        loadTags();
      } else {
        // Add mode - reset form to empty state
        setFormData({
          name: '',
          description: '',
          allOf: [],
          anyOf: [],
          oneOf: [],
          discriminatorProperty: '',
          discriminatorUseAuto: true,
          discriminatorMapping: {},
          additionalProperties: null,
          additionalPropertiesType: 'default',
          additionalPropertiesSchema: '',
          patternProperties: [],
          dependentSchemas: [],
          dependentRequired: [],
          deprecated: false,
          deprecationMessage: '',
          selectedTags: [],
          extensions: {},
          externalDocsUrl: '',
          externalDocsDescription: '',
          conditionalRules: [],
          error: ''
        });
      }
    }
  }, [open, editingClassData]);

  // Helper function to build schema from form data
  const buildSchemaFromFormData = () => {
    const schema: any = { type: 'object', properties: {} };

    // Add composition types
    if (formData.allOf.length > 0) {
      schema.allOf = formData.allOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }
    if (formData.anyOf.length > 0) {
      schema.anyOf = formData.anyOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }
    if (formData.oneOf.length > 0) {
      schema.oneOf = formData.oneOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }

    // Add discriminator if specified
    if (formData.discriminatorProperty && (formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0)) {
      schema.discriminator = { propertyName: formData.discriminatorProperty };
      if (!formData.discriminatorUseAuto && Object.keys(formData.discriminatorMapping).length > 0) {
        // Use custom mapping
        schema.discriminator.mapping = {};
        Object.entries(formData.discriminatorMapping).forEach(([propertyValue, schemaName]) => {
          schema.discriminator.mapping[propertyValue] = `#/components/schemas/${schemaName}`;
        });
      }
    }

    // Add additionalProperties based on the selected type
    if (formData.additionalPropertiesType === 'allow') {
      schema.additionalProperties = true;
    } else if (formData.additionalPropertiesType === 'disallow') {
      schema.additionalProperties = false;
    } else if (formData.additionalPropertiesType === 'schema' && formData.additionalPropertiesSchema) {
      schema.additionalProperties = { $ref: `#/components/schemas/${formData.additionalPropertiesSchema}` };
    }
    // 'default' means no additionalProperties field is added

    // Add patternProperties if defined
    if (formData.patternProperties.length > 0) {
      schema.patternProperties = {};
      formData.patternProperties.forEach(({ pattern, schemaType, schemaRef }) => {
        if (pattern.trim()) {
          if (schemaType === 'ref' && schemaRef) {
            schema.patternProperties[pattern] = { $ref: `#/components/schemas/${schemaRef}` };
          } else {
            schema.patternProperties[pattern] = { type: schemaType };
          }
        }
      });
      // Remove patternProperties if empty after filtering
      if (Object.keys(schema.patternProperties).length === 0) {
        delete schema.patternProperties;
      }
    }

    // Add dependentSchemas if defined
    if (formData.dependentSchemas.length > 0) {
      schema.dependentSchemas = {};
      formData.dependentSchemas.forEach(({ triggerProperty, schemaRef }) => {
        if (triggerProperty.trim() && schemaRef) {
          schema.dependentSchemas[triggerProperty] = { $ref: `#/components/schemas/${schemaRef}` };
        }
      });
      // Remove dependentSchemas if empty after filtering
      if (Object.keys(schema.dependentSchemas).length === 0) {
        delete schema.dependentSchemas;
      }
    }

    // Add dependentRequired if defined
    if (formData.dependentRequired.length > 0) {
      schema.dependentRequired = {};
      formData.dependentRequired.forEach(({ triggerProperty, requiredProperties }) => {
        if (triggerProperty.trim() && requiredProperties.length > 0) {
          schema.dependentRequired[triggerProperty] = requiredProperties;
        }
      });
      // Remove dependentRequired if empty after filtering
      if (Object.keys(schema.dependentRequired).length === 0) {
        delete schema.dependentRequired;
      }
    }

    // Add deprecated if true
    if (formData.deprecated) {
      schema.deprecated = true;
      if (formData.deprecationMessage.trim()) {
        schema.deprecationMessage = formData.deprecationMessage.trim();
      }
    }

    // Add externalDocs if URL is provided
    if (formData.externalDocsUrl.trim()) {
      schema.externalDocs = {
        url: formData.externalDocsUrl.trim()
      };
      if (formData.externalDocsDescription.trim()) {
        schema.externalDocs.description = formData.externalDocsDescription.trim();
      }
    }

    // Add extensions (x- prefixed properties)
    Object.keys(formData.extensions).forEach(key => {
      if (key.startsWith('x-')) {
        schema[key] = formData.extensions[key];
      }
    });

    // Add conditional rules (if/then/else)
    if (formData.conditionalRules.length > 0) {
      const conditionalSchemas = conditionalRulesToJsonSchema(formData.conditionalRules);
      if (conditionalSchemas.length === 1) {
        // Single rule: add at top level
        schema.if = conditionalSchemas[0].if;
        schema.then = conditionalSchemas[0].then;
        if (conditionalSchemas[0].else) {
          schema.else = conditionalSchemas[0].else;
        }
      } else if (conditionalSchemas.length > 1) {
        // Multiple rules: add to allOf array
        if (!schema.allOf) {
          schema.allOf = [];
        }
        schema.allOf.push(...conditionalSchemas);
      }
    }

    return schema;
  };

  // Generate OpenAPI doc asynchronously
  useEffect(() => {
    const generateOpenApiDocAsync = async () => {
      if (!open) return;

      setLoadingOpenApiDoc(true);
      try {
        const allClasses = nodes.map(node => node.data).filter(data => data && data.name);

        const previewClassData = editingClassData || {
          name: formData.name || 'NewClass',
          description: formData.description,
          schema: buildSchemaFromFormData()
        };

        const doc = await generateClassOpenApiSpec(previewClassData, allClasses, {
          title: `${previewClassData.name} Schema`,
          version: '1.0.0',
          description: 'OpenAPI 3.1.0 schema definition',
          metadata: projectMetadata
        });

        setOpenApiDoc(doc);
      } catch (error) {
        console.error('Failed to generate OpenAPI doc:', error);
        setOpenApiDoc(null);
      } finally {
        setLoadingOpenApiDoc(false);
      }
    };

    generateOpenApiDocAsync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editingClassData, formData.name, formData.description, formData.allOf, formData.anyOf, formData.oneOf, formData.discriminatorProperty, formData.discriminatorUseAuto, formData.additionalProperties, nodes]);

  // Get all available class names for composition selectors (excluding current class)
  const availableClasses = nodes
    .map(node => node.data)
    .filter(data => data && data.name && (!editingClassData || data.name !== editingClassData.name))
    .map(data => data.name);

  // Save handler
  const handleSave = async () => {
    if (!formData.name.trim()) {
      setFormData(prev => ({ ...prev, error: 'Class name is required' }));
      return;
    }

    // For create mode, versionId is required
    if (!editingClassData && !versionId) {
      setFormData(prev => ({ ...prev, error: 'Version ID is required to create a class' }));
      return;
    }

    setSaving(true);
    setFormData(prev => ({ ...prev, error: '' }));

    try {
      // Build schema from form data
      const schema = buildSchemaFromFormData();

      let result: string;
      let classId: string;

      if (editingClassData) {
        // Update existing class
        result = await updateClass(
          editingClassData.id,
          formData.name,
          formData.description || null,
          schema
        );
        classId = editingClassData.id;
      } else {
        // Create new class
        result = await createClass(
          versionId!,
          formData.name,
          formData.description || null,
          schema
        );
        const response = JSON.parse(result);
        if (response.success && response.class) {
          classId = response.class.id;
        } else {
          setFormData(prev => ({ ...prev, error: response.error || 'Failed to create class' }));
          setSaving(false);
          return;
        }
      }

      const response = JSON.parse(result);
      if (!response.success) {
        setFormData(prev => ({ ...prev, error: response.error || 'Failed to save class' }));
        setSaving(false);
        return;
      }

      // Update tag assignments
      if (projectId && classId!) {
        try {
          // Get current tags
          const currentTagsResult = await getTagsForClass(classId);
          const currentTags = JSON.parse(currentTagsResult);
          const currentTagIds = currentTags.map((ct: any) => ct.tag_id);

          // Find tags to add and remove
          const tagsToAdd = formData.selectedTags.filter(id => !currentTagIds.includes(id));
          const tagsToRemove = currentTagIds.filter((id: string) => !formData.selectedTags.includes(id));

          // Add new tags
          for (const tagId of tagsToAdd) {
            await assignTagToClass(classId, tagId);
          }

          // Remove old tags
          for (const tagId of tagsToRemove) {
            await removeTagFromClass(classId, tagId);
          }
        } catch (error) {
          console.error('Error updating tags:', error);
          // Don't fail the whole save if tag update fails
        }
      }

      // Success - call onSave callback and close
      if (onSave) {
        onSave();
      }
      onClose();
    } catch (error) {
      console.error('Error saving class:', error);
      setFormData(prev => ({ ...prev, error: 'An error occurred while saving the class' }));
    } finally {
      setSaving(false);
    }
  };

  // Get the preview class data for display
  const previewClassData = editingClassData || {
    name: formData.name || 'NewClass',
    description: formData.description,
    schema: { type: 'object', properties: {} }
  };

  // Get the class schema from the generated OpenAPI doc (with null check)
  const classSchema = openApiDoc?.components?.schemas?.[previewClassData.name];

  // Helper function to resolve $ref references in a schema
  const resolveRefs = (schema: any, schemas: any, visited: Set<string> = new Set(), path: string = ''): any => {
    if (!schema || typeof schema !== 'object') return schema;

    // Preprocess: Convert prefixItems to items array format for json-schema-faker compatibility
    // json-schema-faker doesn't support prefixItems (JSON Schema 2020-12), so we convert it
    if (schema.prefixItems && Array.isArray(schema.prefixItems)) {
      const processedSchema = { ...schema };

      // If items is true or an empty object, it means "allow any additional items"
      // For json-schema-faker, we'll use the prefixItems as a tuple
      if (schema.items === true || (schema.items && Object.keys(schema.items).length === 0)) {
        // Use prefixItems as items for tuple generation
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;

        // Set minItems and maxItems to match prefixItems length for consistent generation
        if (!processedSchema.minItems) {
          processedSchema.minItems = schema.prefixItems.length;
        }
        if (!processedSchema.maxItems) {
          processedSchema.maxItems = schema.prefixItems.length;
        }
      } else if (schema.items) {
        // If there's both prefixItems and items, merge them
        // This is tricky - for now, just use prefixItems as the tuple
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;
        processedSchema.minItems = schema.prefixItems.length;
        processedSchema.maxItems = schema.prefixItems.length;
      } else {
        // No items specified, use prefixItems as items
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;
        processedSchema.minItems = schema.prefixItems.length;
        processedSchema.maxItems = schema.prefixItems.length;
      }

      schema = processedSchema;
    }

    // Handle $ref
    if (schema.$ref && typeof schema.$ref === 'string') {
      const refPath = schema.$ref.split('/');
      const refName = refPath[refPath.length - 1];

      // Prevent circular references
      if (visited.has(refName)) {
        return { type: 'object', description: `Circular reference to ${refName}` };
      }

      const referencedSchema = schemas[refName];
      if (referencedSchema) {
        const newVisited = new Set(visited);
        newVisited.add(refName);
        return resolveRefs(referencedSchema, schemas, newVisited, `${path}/${refName}`);
      }
      return schema; // Can't resolve, return as-is
    }

    // Handle allOf by merging schemas
    if (Array.isArray(schema.allOf)) {
      const merged: any = {};
      const requiredSet = new Set<string>();

      schema.allOf.forEach((subSchema: any, index: number) => {
        const resolved = resolveRefs(subSchema, schemas, visited, `${path}/allOf[${index}]`);

        // Extract required before merging to handle it separately
        const { required: resolvedRequired, properties: resolvedProperties, ...resolvedRest } = resolved;

        // Merge non-properties/required fields
        Object.assign(merged, resolvedRest);

        // Merge properties
        if (resolvedProperties) {
          merged.properties = { ...merged.properties, ...resolvedProperties };
        }

        // Merge required arrays (use Set to avoid duplicates)
        if (resolvedRequired) {
          resolvedRequired.forEach((field: string) => requiredSet.add(field));
        }
      });

      // Convert Set back to array if there are required fields
      if (requiredSet.size > 0) {
        merged.required = Array.from(requiredSet);
      }

      // Keep other properties from the original schema
      const { allOf, required: restRequired, properties: restProperties, ...rest } = schema;

      // Merge properties from original schema (these are additional properties)
      if (restProperties) {
        merged.properties = { ...merged.properties, ...restProperties };
      }

      // Merge required from original schema
      if (restRequired) {
        restRequired.forEach((field: string) => requiredSet.add(field));
        merged.required = Array.from(requiredSet);
      }

      return { ...merged, ...rest };
    }

    // Handle anyOf and oneOf
    if (Array.isArray(schema.anyOf)) {
      return {
        ...schema,
        anyOf: schema.anyOf.map((s: any, index: number) =>
          resolveRefs(s, schemas, visited, `${path}/anyOf[${index}]`)
        )
      };
    }

    if (Array.isArray(schema.oneOf)) {
      return {
        ...schema,
        oneOf: schema.oneOf.map((s: any, index: number) =>
          resolveRefs(s, schemas, visited, `${path}/oneOf[${index}]`)
        )
      };
    }

    // Recursively resolve nested objects and arrays
    const resolved: any = Array.isArray(schema) ? [] : {};
    for (const key in schema) {
      if (schema.hasOwnProperty(key)) {
        // Don't recursively resolve primitive values or strings that aren't schemas
        const value = schema[key];
        if (value && typeof value === 'object') {
          resolved[key] = resolveRefs(value, schemas, visited, `${path}/${key}`);
        } else {
          resolved[key] = value;
        }
      }
    }
    return resolved;
  };

  // Generate schema content based on current tab
  let schemaContent: string = '';

  if (loadingOpenApiDoc || !openApiDoc) {
    schemaContent = '// Loading schema...';
  } else if (activeTab === 'json') {
    schemaContent = JSON.stringify(openApiDoc, null, 2);
  } else if (activeTab === 'yaml') {
    schemaContent = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false } as any);
  } else if (activeTab === 'example') {
    // Example view - regenerate when exampleRefreshKey changes
    try {
      // Resolve all $ref references for json-schema-faker
      const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);

      // Debug: Log the resolved schema to verify allOf merging
      console.log('Original schema:', classSchema);
      console.log('Resolved schema for example generation:', resolvedSchema);
      console.log('Resolved schema properties:', resolvedSchema.properties);

      // Use exampleRefreshKey in random seed to force regeneration
      jsf.option({
        random: () => {
          // Mix in exampleRefreshKey to ensure different results on each refresh
          const seed = Math.random() * (exampleRefreshKey + 1);
          return seed - Math.floor(seed);
        }
      });

      const fakeData = jsf.generate(resolvedSchema);
      schemaContent = JSON.stringify(fakeData, null, 2);
    } catch (error) {
      console.error('Error generating fake data:', error);
      schemaContent = JSON.stringify({
        error: 'Could not generate example data',
        message: error instanceof Error ? error.message : String(error)
      }, null, 2);
    }
  }

  const handleCopy = () => {
    if (!openApiDoc) return;

    let content: string;
    if (activeTab === 'example') {
      try {
        const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);
        const fakeData = jsf.generate(resolvedSchema);
        content = JSON.stringify(fakeData, null, 2);
      } catch (error) {
        console.error('Error generating fake data:', error);
        content = JSON.stringify({ error: 'Could not generate example data' }, null, 2);
      }
    } else if (activeTab === 'yaml') {
      content = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false } as any);
    } else {
      content = JSON.stringify(openApiDoc, null, 2);
    }

    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = () => {
    if (!openApiDoc) return;

    let content: string;
    let filenameSuffix: string;
    let mimeType: string;
    let extension: string;

    if (activeTab === 'example') {
      try {
        const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);
        const fakeData = jsf.generate(resolvedSchema);
        content = JSON.stringify(fakeData, null, 2);
      } catch (error) {
        console.error('Error generating fake data:', error);
        content = JSON.stringify({ error: 'Could not generate example data' }, null, 2);
      }
      filenameSuffix = 'example';
      mimeType = 'application/json';
      extension = 'json';
    } else if (activeTab === 'yaml') {
      content = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false } as any);
      filenameSuffix = 'schema';
      mimeType = 'text/yaml';
      extension = 'yaml';
    } else {
      content = JSON.stringify(openApiDoc, null, 2);
      filenameSuffix = 'schema';
      mimeType = 'application/json';
      extension = 'json';
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${previewClassData.name.toLowerCase()}-${filenameSuffix}.${extension}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()} modal={true}>
      <DialogContent
        className="max-w-4xl h-[90vh] max-h-[900px] p-0 flex flex-col overflow-hidden"
        showCloseButton={true}
        aria-describedby={undefined}
      >
        <DialogHeader className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <DialogTitle className="text-lg font-semibold">
                {!editingClassData ? 'Add Class' : isReadOnly ? `View Class: ${formData.name || editingClassData.name}` : `Edit Class: ${formData.name || editingClassData.name}`}
              </DialogTitle>
              {isReadOnly && (
                <span className="px-2 py-0.5 bg-amber-400 text-black text-xs font-semibold rounded">
                  Read Only
                </span>
              )}
            </div>
          </div>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="px-6 border-b border-gray-200 dark:border-gray-700 rounded-none justify-start bg-transparent shrink-0">
            <TabsTrigger value="edit">Edit</TabsTrigger>
            <TabsTrigger value="json">JSON</TabsTrigger>
            <TabsTrigger value="yaml">YAML</TabsTrigger>
            <TabsTrigger value="example">Example</TabsTrigger>
          </TabsList>

          {/* Edit Tab */}
          <TabsContent value="edit" className="flex-1 overflow-auto mt-0 p-0">
            <div className="flex flex-col">
              {formData.error && <Alert variant="error" className="m-4 mb-0">{formData.error}</Alert>}

              {/* SECTION 1: Basic Information */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 mb-4">
                  <FileText size={18} className="text-indigo-500" />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Basic Information</h3>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="className">Class Name *</Label>
                    <Input
                      id="className"
                      autoFocus
                      value={formData.name}
                      onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value.replace(/[^A-Za-z0-9_]/g, '') }))}
                      placeholder="e.g., UserAccount"
                      disabled={isReadOnly}
                    />
                    <p className="text-xs text-gray-500">PascalCase recommended</p>
                  </div>
                  <div className="md:col-span-2 space-y-2">
                    <Label htmlFor="description">Description</Label>
                    <Textarea
                      id="description"
                      value={formData.description}
                      onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="Brief description of what this class represents"
                      disabled={isReadOnly}
                      rows={2}
                    />
                  </div>
                </div>

                {/* Tags */}
                {projectId && projectTags && projectTags.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <Label>Tags</Label>
                    <div className="flex flex-wrap gap-2 p-2 border border-gray-200 dark:border-gray-700 rounded-md min-h-[38px]">
                      {formData.selectedTags.map((tagId) => {
                        const tag = projectTags.find((t: any) => t.id === tagId);
                        return tag ? (
                          <Badge key={tagId} variant="secondary" className="gap-1">
                            <span style={{ color: tag.color }}>●</span>
                            {tag.name}
                            {!isReadOnly && (
                              <button type="button" onClick={() => setFormData(prev => ({ ...prev, selectedTags: prev.selectedTags.filter(id => id !== tagId) }))}>
                                <X className="h-3 w-3" />
                              </button>
                            )}
                          </Badge>
                        ) : null;
                      })}
                      {!isReadOnly && projectTags.filter((t: any) => !formData.selectedTags.includes(t.id)).length > 0 && (
                        <Select
                          value=""
                          onValueChange={(tagId) => {
                            if (tagId && !formData.selectedTags.includes(tagId)) {
                              setFormData(prev => ({ ...prev, selectedTags: [...prev.selectedTags, tagId] }));
                            }
                          }}
                        >
                          <SelectTrigger className="w-auto h-7 text-xs border-dashed">
                            <TagIcon className="h-3 w-3 mr-1" />
                            Add Tag
                          </SelectTrigger>
                          <SelectContent>
                            {projectTags.filter((t: any) => !formData.selectedTags.includes(t.id)).map((tag: any) => (
                              <SelectItem key={tag.id} value={tag.id}>
                                <span className="flex items-center gap-2">
                                  <span style={{ color: tag.color }}>●</span>
                                  {tag.name}
                                </span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION 2: Schema Settings */}
              <div className={`p-6 border-b border-gray-200 dark:border-gray-700 ${isDark ? 'bg-slate-900' : 'bg-gray-50'}`}>
                <div className="flex items-center gap-2 mb-4">
                  <Settings size={18} className="text-indigo-500" />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Schema Settings</h3>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Additional Properties */}
                  <div className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <h4 className="text-sm font-semibold mb-3 text-gray-900 dark:text-gray-100">Additional Properties</h4>
                    <div className="space-y-2">
                      {(['default', 'allow', 'disallow', 'schema'] as const).map((value) => (
                        <label key={value} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio"
                            name="additionalPropertiesType"
                            value={value}
                            checked={formData.additionalPropertiesType === value}
                            onChange={(e) => {
                              const val = e.target.value as typeof value;
                              setFormData(prev => ({
                                ...prev,
                                additionalPropertiesType: val,
                                additionalProperties: val === 'default' ? null : val === 'allow' ? true : val === 'disallow' ? false : null,
                                additionalPropertiesSchema: val === 'schema' ? prev.additionalPropertiesSchema : ''
                              }));
                            }}
                            disabled={isReadOnly}
                            className="w-4 h-4 text-indigo-600"
                          />
                          <span className="text-sm text-gray-700 dark:text-gray-300">
                            {value === 'default' && 'Not specified (default)'}
                            {value === 'allow' && 'Allow Any (true)'}
                            {value === 'disallow' && 'Disallow (false)'}
                            {value === 'schema' && 'Must Match Schema'}
                          </span>
                        </label>
                      ))}
                      {formData.additionalPropertiesType === 'schema' && (
                        <div className="mt-2 pl-6">
                          <Select
                            value={formData.additionalPropertiesSchema || '__none__'}
                            onValueChange={(val) => setFormData(prev => ({ ...prev, additionalPropertiesSchema: val === '__none__' ? '' : val }))}
                            disabled={isReadOnly}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Select a class..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none__">Select a class...</SelectItem>
                              {availableClasses.map((cls) => (
                                <SelectItem key={cls} value={cls}>{cls}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Deprecation Status */}
                  <div className={`p-4 rounded-lg border transition-all ${formData.deprecated ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                    <div className="flex items-center gap-2 mb-3">
                      <Checkbox
                        id="deprecated"
                        checked={formData.deprecated}
                        onCheckedChange={(checked) => setFormData(prev => ({ ...prev, deprecated: !!checked }))}
                        disabled={isReadOnly}
                      />
                      <label htmlFor="deprecated" className="text-sm font-semibold text-gray-900 dark:text-gray-100 cursor-pointer flex items-center gap-2">
                        <AlertTriangle size={16} className={formData.deprecated ? 'text-amber-600' : 'text-gray-400'} />
                        Mark as Deprecated
                      </label>
                    </div>
                    {formData.deprecated && (
                      <Textarea
                        value={formData.deprecationMessage}
                        onChange={(e) => setFormData(prev => ({ ...prev, deprecationMessage: e.target.value }))}
                        placeholder="e.g., Use NewClass instead. Will be removed in v2.0."
                        disabled={isReadOnly}
                        rows={2}
                        className="mt-2"
                      />
                    )}
                  </div>
                </div>
              </div>

              {/* SECTION 2.5: Pattern Properties */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Regex size={18} className="text-indigo-500" />
                    <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Pattern Properties</h3>
                    <span className="text-xs text-gray-500">(Optional)</span>
                  </div>
                  {!isReadOnly && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setFormData(prev => ({
                        ...prev,
                        patternProperties: [...prev.patternProperties, { pattern: '', schemaType: 'string', schemaRef: '' }]
                      }))}
                    >
                      <Plus size={14} className="mr-1" /> Add Pattern
                    </Button>
                  )}
                </div>
                <p className="text-xs text-gray-500 mb-4">Define regex patterns that map dynamic property names to schemas.</p>

                {formData.patternProperties.length === 0 ? (
                  <div className="p-6 text-center bg-gray-50 dark:bg-slate-800 rounded-lg border border-dashed border-gray-300 dark:border-gray-600">
                    <p className="text-sm text-gray-500">No pattern properties defined.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {formData.patternProperties.map((patternProp, index) => (
                      <div key={index} className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700 flex gap-3 items-end">
                        <div className="flex-1 flex flex-col md:flex-row gap-3">
                          <div className="flex-1 space-y-1">
                            <Label>Regex Pattern</Label>
                            <Input
                              value={patternProp.pattern}
                              onChange={(e) => {
                                const newPatternProps = [...formData.patternProperties];
                                newPatternProps[index] = { ...newPatternProps[index], pattern: e.target.value };
                                setFormData(prev => ({ ...prev, patternProperties: newPatternProps }));
                              }}
                              disabled={isReadOnly}
                              placeholder="^x-.*$"
                              className="font-mono"
                            />
                          </div>
                          <div className="flex-1 space-y-1">
                            <Label>Type</Label>
                            <Select
                              value={patternProp.schemaType}
                              onValueChange={(val) => {
                                const newPatternProps = [...formData.patternProperties];
                                newPatternProps[index] = { ...newPatternProps[index], schemaType: val as any, schemaRef: val === 'ref' ? patternProp.schemaRef : '' };
                                setFormData(prev => ({ ...prev, patternProperties: newPatternProps }));
                              }}
                              disabled={isReadOnly}
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="string">String</SelectItem>
                                <SelectItem value="number">Number</SelectItem>
                                <SelectItem value="integer">Integer</SelectItem>
                                <SelectItem value="boolean">Boolean</SelectItem>
                                <SelectItem value="object">Object</SelectItem>
                                <SelectItem value="array">Array</SelectItem>
                                <SelectItem value="ref">Schema Reference</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {patternProp.schemaType === 'ref' && (
                            <div className="flex-1 space-y-1">
                              <Label>Schema</Label>
                              <Select
                                value={patternProp.schemaRef || '__none__'}
                                onValueChange={(val) => {
                                  const newPatternProps = [...formData.patternProperties];
                                  newPatternProps[index] = { ...newPatternProps[index], schemaRef: val === '__none__' ? '' : val };
                                  setFormData(prev => ({ ...prev, patternProperties: newPatternProps }));
                                }}
                                disabled={isReadOnly}
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="Select..." />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="__none__">Select...</SelectItem>
                                  {availableClasses.map((cls) => (
                                    <SelectItem key={cls} value={cls}>{cls}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          )}
                        </div>
                        {!isReadOnly && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 shrink-0 h-9 w-9"
                            onClick={() => {
                              const newPatternProps = formData.patternProperties.filter((_, i) => i !== index);
                              setFormData(prev => ({ ...prev, patternProperties: newPatternProps }));
                            }}
                          >
                            <Trash2 size={16} />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* SECTION 2.6: Dependent Schemas */}
              <div className={`p-6 border-b border-gray-200 dark:border-gray-700 ${isDark ? 'bg-slate-900' : 'bg-gray-50'}`}>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Link size={18} className="text-indigo-500" />
                    <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Dependent Schemas</h3>
                    <span className="text-xs text-gray-500">(Optional)</span>
                  </div>
                  {!isReadOnly && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setFormData(prev => ({
                        ...prev,
                        dependentSchemas: [...prev.dependentSchemas, { triggerProperty: '', schemaRef: '' }]
                      }))}
                    >
                      <Plus size={14} className="mr-1" /> Add Dependency
                    </Button>
                  )}
                </div>
                <p className="text-xs text-gray-500 mb-4">When a trigger property is present, apply additional schema constraints.</p>

                {formData.dependentSchemas.length === 0 ? (
                  <div className="p-6 text-center bg-white dark:bg-slate-800 rounded-lg border border-dashed border-gray-300 dark:border-gray-600">
                    <p className="text-sm text-gray-500">No dependent schemas defined.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {formData.dependentSchemas.map((depSchema, index) => (
                      <div key={index} className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700 flex gap-3 items-end">
                        <div className="flex-1 flex flex-col md:flex-row gap-3">
                          <div className="flex-1 space-y-1">
                            <Label>Trigger Property</Label>
                            <Input
                              value={depSchema.triggerProperty}
                              onChange={(e) => {
                                const newDeps = [...formData.dependentSchemas];
                                newDeps[index] = { ...newDeps[index], triggerProperty: e.target.value };
                                setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                              }}
                              disabled={isReadOnly}
                              placeholder="e.g., paymentMethod"
                            />
                          </div>
                          <div className="flex-1 space-y-1">
                            <Label>Required Schema</Label>
                            <Select
                              value={depSchema.schemaRef || '__none__'}
                              onValueChange={(val) => {
                                const newDeps = [...formData.dependentSchemas];
                                newDeps[index] = { ...newDeps[index], schemaRef: val === '__none__' ? '' : val };
                                setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                              }}
                              disabled={isReadOnly}
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="Select class..." />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__none__">Select class...</SelectItem>
                                {availableClasses.map((cls) => (
                                  <SelectItem key={cls} value={cls}>{cls}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                        {!isReadOnly && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 shrink-0 h-9 w-9"
                            onClick={() => {
                              const newDeps = formData.dependentSchemas.filter((_, i) => i !== index);
                              setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                            }}
                          >
                            <Trash2 size={16} />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* SECTION 2.7: Dependent Required */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <ListChecks size={18} className="text-indigo-500" />
                    <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Dependent Required</h3>
                    <span className="text-xs text-gray-500">(Optional)</span>
                  </div>
                  {!isReadOnly && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setFormData(prev => ({
                        ...prev,
                        dependentRequired: [...prev.dependentRequired, { triggerProperty: '', requiredProperties: [] }]
                      }))}
                    >
                      <Plus size={14} className="mr-1" /> Add Rule
                    </Button>
                  )}
                </div>
                <p className="text-xs text-gray-500 mb-4">When a trigger property is present, other properties become required.</p>

                {formData.dependentRequired.length === 0 ? (
                  <div className="p-6 text-center bg-gray-50 dark:bg-slate-800 rounded-lg border border-dashed border-gray-300 dark:border-gray-600">
                    <p className="text-sm text-gray-500">No dependent required rules defined.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {formData.dependentRequired.map((depReq, index) => (
                      <div key={index} className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700 flex gap-3 items-end">
                        <div className="flex-1 flex flex-col md:flex-row gap-3">
                          <div className="flex-1 space-y-1">
                            <Label>Trigger Property</Label>
                            <Input
                              value={depReq.triggerProperty}
                              onChange={(e) => {
                                const newDeps = [...formData.dependentRequired];
                                newDeps[index] = { ...newDeps[index], triggerProperty: e.target.value };
                                setFormData(prev => ({ ...prev, dependentRequired: newDeps }));
                              }}
                              disabled={isReadOnly}
                              placeholder="e.g., billingAddress"
                            />
                          </div>
                          <div className="flex-1 space-y-1">
                            <Label>Required Properties (comma-separated)</Label>
                            <Input
                              value={depReq.requiredProperties.join(', ')}
                              onChange={(e) => {
                                const newDeps = [...formData.dependentRequired];
                                const props = e.target.value.split(',').map(p => p.trim()).filter(p => p);
                                newDeps[index] = { ...newDeps[index], requiredProperties: props };
                                setFormData(prev => ({ ...prev, dependentRequired: newDeps }));
                              }}
                              disabled={isReadOnly}
                              placeholder="e.g., billingCity, billingZip"
                            />
                          </div>
                        </div>
                        {!isReadOnly && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 shrink-0 h-9 w-9"
                            onClick={() => {
                              const newDeps = formData.dependentRequired.filter((_, i) => i !== index);
                              setFormData(prev => ({ ...prev, dependentRequired: newDeps }));
                            }}
                          >
                            <Trash2 size={16} />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* SECTION 3: Composition & Inheritance */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 mb-2">
                  <Layers size={18} className="text-indigo-500" />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Composition & Inheritance</h3>
                  <span className="text-xs text-gray-500">(Optional)</span>
                </div>
                <p className="text-xs text-gray-500 mb-4">Define relationships with other classes using OpenAPI composition keywords</p>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {/* allOf */}
                  <div className={`p-4 rounded-lg border ${isDark ? 'bg-indigo-900/30 border-indigo-700' : 'bg-indigo-50 border-indigo-200'}`}>
                    <h4 className={`text-sm font-semibold mb-2 ${isDark ? 'text-indigo-300' : 'text-indigo-700'}`}>allOf (Inheritance)</h4>
                    <MultiSelect
                      options={availableClasses}
                      value={formData.allOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, allOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="indigo"
                    />
                    <p className="text-xs text-gray-500 mt-2">Must match ALL listed schemas</p>
                  </div>

                  {/* anyOf */}
                  <div className={`p-4 rounded-lg border ${isDark ? 'bg-amber-900/30 border-amber-700' : 'bg-amber-50 border-amber-200'}`}>
                    <h4 className={`text-sm font-semibold mb-2 ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>anyOf (Alternatives)</h4>
                    <MultiSelect
                      options={availableClasses}
                      value={formData.anyOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, anyOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="amber"
                    />
                    <p className="text-xs text-gray-500 mt-2">Must match AT LEAST one schema</p>
                  </div>

                  {/* oneOf */}
                  <div className={`p-4 rounded-lg border ${isDark ? 'bg-purple-900/30 border-purple-700' : 'bg-purple-50 border-purple-200'}`}>
                    <h4 className={`text-sm font-semibold mb-2 ${isDark ? 'text-purple-300' : 'text-purple-700'}`}>oneOf (Exclusive)</h4>
                    <MultiSelect
                      options={availableClasses}
                      value={formData.oneOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, oneOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="purple"
                    />
                    <p className="text-xs text-gray-500 mt-2">Must match EXACTLY one schema</p>
                  </div>
                </div>

                {/* Discriminator */}
                {(formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0) && (
                  <div className="mt-4 p-4 bg-gray-50 dark:bg-slate-800 rounded-lg border border-dashed border-gray-300 dark:border-gray-600">
                    <h4 className="text-sm font-semibold mb-2 text-gray-900 dark:text-gray-100">Discriminator Configuration</h4>
                    <p className="text-xs text-gray-500 mb-3">Helps tools understand which schema variant to use for polymorphic types</p>
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <Label>Discriminator Property</Label>
                        <Input
                          value={formData.discriminatorProperty}
                          onChange={(e) => setFormData(prev => ({ ...prev, discriminatorProperty: e.target.value }))}
                          placeholder="e.g., type, petType, kind"
                          disabled={isReadOnly}
                        />
                      </div>
                      {formData.discriminatorProperty && (
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="discriminatorUseAuto"
                            checked={formData.discriminatorUseAuto}
                            onCheckedChange={(checked) => setFormData(prev => ({
                              ...prev,
                              discriminatorUseAuto: !!checked,
                              discriminatorMapping: checked ? {} : prev.discriminatorMapping
                            }))}
                            disabled={isReadOnly}
                          />
                          <label htmlFor="discriminatorUseAuto" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                            Use automatic mapping (based on schema names)
                          </label>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION 3.5: Conditional Schema */}
              <div className={`p-6 border-b border-gray-200 dark:border-gray-700 ${isDark ? 'bg-slate-900' : 'bg-gray-50'}`}>
                <ConditionalSchemaBuilder
                  rules={formData.conditionalRules}
                  onChange={(rules) => setFormData(prev => ({ ...prev, conditionalRules: rules }))}
                  availableProperties={editingClassData?.properties?.map((p: any) => p.name) || []}
                  disabled={isReadOnly}
                />
              </div>

              {/* SECTION 4: Documentation & Extensions */}
              <div className={`p-6 ${isDark ? 'bg-slate-900' : 'bg-gray-50'}`}>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* External Documentation */}
                  <div className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <div className="flex items-center gap-2 mb-3">
                      <ExternalLink size={16} className="text-indigo-500" />
                      <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">External Documentation</h4>
                    </div>
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <Label>Documentation URL</Label>
                        <Input
                          type="url"
                          value={formData.externalDocsUrl}
                          onChange={(e) => setFormData(prev => ({ ...prev, externalDocsUrl: e.target.value }))}
                          placeholder="https://docs.example.com/..."
                          disabled={isReadOnly}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label>Description</Label>
                        <Textarea
                          value={formData.externalDocsDescription}
                          onChange={(e) => setFormData(prev => ({ ...prev, externalDocsDescription: e.target.value }))}
                          placeholder="Brief description of external docs"
                          disabled={isReadOnly}
                          rows={2}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Extensions */}
                  <div className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <div className="flex items-center gap-2 mb-3">
                      <Code size={16} className="text-indigo-500" />
                      <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Custom Extensions</h4>
                    </div>
                    <ExtensionsEditor
                      value={formData.extensions}
                      onChange={(extensions) => setFormData(prev => ({ ...prev, extensions }))}
                      disabled={isReadOnly}
                    />
                  </div>
                </div>
              </div>
            </div>
          </TabsContent>

          {/* JSON Tab */}
          <TabsContent value="json" className="flex-1 flex flex-col mt-0 overflow-hidden">
            <div className="flex gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
              <Button size="sm" variant="outline" onClick={handleCopy} disabled={copied || loadingOpenApiDoc || !openApiDoc}>
                {copied ? <Check size={16} className="mr-1" /> : <Copy size={16} className="mr-1" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button size="sm" onClick={handleExport} disabled={loadingOpenApiDoc || !openApiDoc}>
                <Download size={16} className="mr-1" /> Export
              </Button>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                language="json"
                value={schemaContent}
                theme={isDark ? 'vs-dark' : 'light'}
                options={{ readOnly: true, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13, wordWrap: 'on' }}
              />
            </div>
          </TabsContent>

          {/* YAML Tab */}
          <TabsContent value="yaml" className="flex-1 flex flex-col mt-0 overflow-hidden">
            <div className="flex gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
              <Button size="sm" variant="outline" onClick={handleCopy} disabled={copied || loadingOpenApiDoc || !openApiDoc}>
                {copied ? <Check size={16} className="mr-1" /> : <Copy size={16} className="mr-1" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button size="sm" onClick={handleExport} disabled={loadingOpenApiDoc || !openApiDoc}>
                <Download size={16} className="mr-1" /> Export
              </Button>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                language="yaml"
                value={schemaContent}
                theme={isDark ? 'vs-dark' : 'light'}
                options={{ readOnly: true, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13, wordWrap: 'on' }}
              />
            </div>
          </TabsContent>

          {/* Example Tab */}
          <TabsContent value="example" className="flex-1 flex flex-col mt-0 overflow-hidden">
            <div className="flex gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
              <Button size="sm" variant="outline" onClick={() => setExampleRefreshKey(prev => prev + 1)} disabled={loadingOpenApiDoc || !openApiDoc}>
                <RefreshCw size={16} className="mr-1" /> Refresh
              </Button>
              <Button size="sm" variant="outline" onClick={handleCopy} disabled={copied || loadingOpenApiDoc || !openApiDoc}>
                {copied ? <Check size={16} className="mr-1" /> : <Copy size={16} className="mr-1" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button size="sm" onClick={handleExport} disabled={loadingOpenApiDoc || !openApiDoc}>
                <Download size={16} className="mr-1" /> Export
              </Button>
            </div>
            <div className="flex-1">
              <Editor
                key={`example-${exampleRefreshKey}`}
                height="100%"
                language="json"
                value={schemaContent}
                theme={isDark ? 'vs-dark' : 'light'}
                options={{ readOnly: true, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13, wordWrap: 'on' }}
              />
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          {!isReadOnly && activeTab === 'edit' && (
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </Button>
          )}
          {activeTab !== 'edit' && (
            <Button onClick={onClose}>Close</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ClassEditDialog;

'use client';

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import dynamic from 'next/dynamic';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Markdown } from '../../ui/Markdown';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Textarea } from '../../ui/Textarea';
import { Alert } from '../../ui/Alert';
import { Badge } from '../../ui/Badge';
import { Checkbox } from '../../ui/Checkbox';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../ui/Tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import { Copy, Download, RefreshCw, Check, Tag as TagIcon, ExternalLink, Settings, Layers, FileText, AlertTriangle, Code, Plus, Trash2, Regex, Link, ListChecks, X, ChevronDown, GitBranch, ArrowRight, Sparkles, Bot, User, Send, Loader2, ArrowLeft } from 'lucide-react';
import * as SelectRadix from '@radix-ui/react-select';
import YAML from 'yaml';
import jsf from 'json-schema-faker';
import { generateClassOpenApiSpec } from '../../../utils/openapi';
import { assignTagToClass, removeTagFromClass, getTagsForClass } from '../../../../../lib/db/helper';
import { createClassWithSession, updateClassWithSession, getClassWithPropertiesAndTagsWithSession } from '../../../../../lib/api/rest-client';
import { ExtensionsEditor } from './ExtensionsEditor';
import ConditionalSchemaBuilder, {
  ConditionalRule,
  conditionalRulesToJsonSchema,
  jsonSchemaToConditionalRules
} from './ConditionalSchemaBuilder';
import {
  FormSection,
  FormSubsection,
  FormFieldGroup,
  FormGrid,
  FormEmptyState,
  FormToggleCard,
  FormViewModeToggle,
  FormSectionNav,
  FormWizardStepper,
  FormWizardControls,
  useFormScrollSpy,
  scrollToSection,
  useFormViewMode,
} from './form';
import { AiClassCreatePreviewDialog } from '@/app/ade/studio/components/chatbot/AiClassCreatePreviewDialog';
import { parseClassDefinitionFromAssistantMarkdown } from '@/app/ade/studio/components/chatbot/assistant-action-detection';
import type { PropertyDialogAiContext } from './PropertyDialog';
import { ClassDescriptionAiButton } from './ClassDescriptionAiButton';
import { buildClassDescriptionAiPayload } from '@lib/ai-property-description';

// Custom hook for dark mode detection - prioritizes localStorage, then system preference
const useDarkMode = () => {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const initTheme = () => {
      const savedTheme = localStorage.getItem('theme');
      if (savedTheme === 'dark') {
        setIsDark(true);
      } else if (savedTheme === 'light') {
        setIsDark(false);
      } else {
        // No saved preference - check class or system preference
        setIsDark(document.documentElement.classList.contains('dark') ||
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      }
    };
    initTheme();
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => {
      observer.disconnect();
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

/**
 * Canonical ordering of class-edit sections.
 * Each entry maps a stable section `id` (used by the scroll-spy, sidebar
 * nav, and changed-indicator) to its wizard step. Keep this list in sync
 * with both the render order and the `CLASS_WIZARD_STEPS` below.
 */
const CLASS_SECTION_ORDER = [
  'basics',
  'object-constraints',
  'additional-props',
  'unevaluated-props',
  'composition',
  'pattern-props',
  'dependent-schemas',
  'dependent-required',
  'conditional',
  'examples',
  'xml',
  'schema-metadata',
  'external-docs',
  'extensions',
] as const;

type ClassSectionId = typeof CLASS_SECTION_ORDER[number];

const CLASS_WIZARD_STEPS: Array<{ id: string; label: string; sections: ClassSectionId[] }> = [
  { id: 'basics', label: 'Basics', sections: ['basics'] },
  {
    id: 'validation',
    label: 'Validation',
    sections: ['object-constraints', 'additional-props', 'unevaluated-props'],
  },
  { id: 'composition', label: 'Composition', sections: ['composition'] },
  {
    id: 'dynamic',
    label: 'Dynamic Properties',
    sections: ['pattern-props', 'dependent-schemas', 'dependent-required', 'conditional'],
  },
  {
    id: 'documentation',
    label: 'Documentation',
    sections: ['examples', 'xml', 'schema-metadata', 'external-docs', 'extensions'],
  },
];

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
  /** When opening Add Class from chat (#528), seed AI mode with this assistant markdown. */
  aiAssistantSeedMarkdown?: string | null;
  onAiAssistantSeedConsumed?: () => void;
  /** Fires once per Add Class session when the class name reaches 2+ characters (#275). */
  onClassNameEnteredForPropertySuggestions?: () => void;
  /** When set, class **Description** supports **Generate with AI** (#620). */
  classDescriptionAiContext?: PropertyDialogAiContext;
}

const ClassEditDialog = ({
  open,
  onClose,
  editingClassData,
  nodes,
  isReadOnly = false,
  onSave,
  projectId = '',
  versionId = '',
  projectTags = [],
  projectMetadata,
  aiAssistantSeedMarkdown = null,
  onAiAssistantSeedConsumed,
  onClassNameEnteredForPropertySuggestions,
  classDescriptionAiContext,
}: ClassEditDialogProps) => {
  const isDark = useDarkMode();

  const [activeTab, setActiveTab] = useState('edit');
  const [exampleRefreshKey, setExampleRefreshKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openApiDoc, setOpenApiDoc] = useState<any>(null);
  const [loadingOpenApiDoc, setLoadingOpenApiDoc] = useState(false);

  // View-mode state: `guided` shows one wizard step at a time, `advanced`
  // shows all sections with a sticky sidebar nav. Preference is persisted
  // per-user in sessionStorage so power users stay in Advanced mode.
  const [viewMode, setViewMode] = useFormViewMode(
    'ade.class-edit.view-mode',
    editingClassData ? 'advanced' : 'guided',
  );
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const advancedScrollRef = useRef<HTMLDivElement | null>(null);

  // Scroll-spy follows the user's position in Advanced mode so the sidebar
  // highlights the section currently in view. Disabled in Guided mode where
  // only one step's sections are rendered at a time.
  const { activeId: activeSectionId } = useFormScrollSpy({
    sectionIds: CLASS_SECTION_ORDER as unknown as string[],
    containerRef: advancedScrollRef,
    disabled: viewMode !== 'advanced',
    rootMarginTop: 24,
  });

  // AI Assistant (Create Class) chat mode
  const [showAIChatMode, setShowAIChatMode] = useState(false);
  const [aiMessages, setAiMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
  const [aiInput, setAiInput] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiStreamingContent, setAiStreamingContent] = useState('');
  const [aiSelectedModel, setAiSelectedModel] = useState('');
  const [aiModels, setAiModels] = useState<Array<{ name: string; model: string; modified_at: string; size: number }>>([]);
  const [aiLoadingModels, setAiLoadingModels] = useState(true);
  const [aiCreateError, setAiCreateError] = useState('');
  const [aiProjectProperties, setAiProjectProperties] = useState<Array<{ id: string; name: string; description?: string | null; data: any }>>([]);
  const [aiCreatePreviewContent, setAiCreatePreviewContent] = useState<string | null>(null);
  const [newDependentSchemaProperty, setNewDependentSchemaProperty] = useState('');
  const aiMessagesEndRef = useRef<HTMLDivElement>(null);
  const aiAbortControllerRef = useRef<AbortController | null>(null);
  const classNamePropertySuggestGateRef = useRef(false);

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
    additionalPropertiesType: 'default' as 'default' | 'allow' | 'disallow' | 'schema' | 'type',
    additionalPropertiesSchema: '', // Class name reference for "Must Match Schema" option
    additionalPropertiesInlineType: 'string' as 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array', // For inline type schema
    unevaluatedProperties: null as boolean | null,
    unevaluatedPropertiesType: 'default' as 'default' | 'allow' | 'disallow' | 'schema' | 'type',
    unevaluatedPropertiesSchema: '', // Class name reference for "Must Match Schema" option
    unevaluatedPropertiesInlineType: 'string' as 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array', // For inline type schema
    patternProperties: [] as Array<{ pattern: string; schemaType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' | 'ref'; schemaRef: string }>,
    dependentSchemas: {} as Record<string, any>, // Full dependent schemas objects (if/then/else, not just refs)
    dependentRequired: [] as Array<{ triggerProperty: string; requiredProperties: string[] }>, // When triggerProperty is present, these properties become required
    deprecated: false,
    deprecationMessage: '',
    selectedTags: [] as string[],
    extensions: {} as Record<string, any>,
    externalDocsUrl: '',
    externalDocsDescription: '',
    conditionalRules: [] as ConditionalRule[],
    // Object constraints (OpenAPI 3.1)
    minProperties: '',
    maxProperties: '',
    examples: [] as string[], // JSON Schema examples at class level
    // XML Object (OpenAPI 3.1) - class-level defaults
    xmlName: '',
    xmlNamespace: '',
    xmlPrefix: '',
    // Schema metadata (JSON Schema 2020-12)
    schemaId: '', // $id
    schemaAnchor: '', // $anchor
    schemaComment: '', // $comment
    error: ''
  });

  /**
   * Per-section "changed" indicator used by the sidebar nav dot and the
   * FormSection edge stripe. Keys map 1:1 to CLASS_SECTION_ORDER.
   */
  const changedSections = useMemo<Record<ClassSectionId, boolean>>(() => {
    const d = formData;
    const apType = d.additionalPropertiesType;
    const upType = d.unevaluatedPropertiesType;
    const apNonDefaultType = apType === 'type' && d.additionalPropertiesInlineType !== 'string';
    const upNonDefaultType = upType === 'type' && d.unevaluatedPropertiesInlineType !== 'string';
    const apChanged = apType !== 'default' || d.additionalPropertiesSchema !== '' || apNonDefaultType;
    const upChanged = upType !== 'default' || d.unevaluatedPropertiesSchema !== '' || upNonDefaultType;
    return {
      basics:
        d.description.trim() !== '' ||
        d.deprecated ||
        d.deprecationMessage.trim() !== '' ||
        d.selectedTags.length > 0,
      'object-constraints': d.minProperties.trim() !== '' || d.maxProperties.trim() !== '',
      'additional-props': apChanged,
      'unevaluated-props': upChanged,
      composition:
        d.allOf.length > 0 ||
        d.anyOf.length > 0 ||
        d.oneOf.length > 0 ||
        d.discriminatorProperty.trim() !== '' ||
        !d.discriminatorUseAuto ||
        Object.keys(d.discriminatorMapping).length > 0,
      'pattern-props': d.patternProperties.length > 0,
      'dependent-schemas': Object.keys(d.dependentSchemas).length > 0,
      'dependent-required': d.dependentRequired.length > 0,
      conditional: d.conditionalRules.length > 0,
      examples: d.examples.length > 0,
      xml: d.xmlName.trim() !== '' || d.xmlNamespace.trim() !== '' || d.xmlPrefix.trim() !== '',
      'schema-metadata':
        d.schemaId.trim() !== '' || d.schemaAnchor.trim() !== '' || d.schemaComment.trim() !== '',
      'external-docs': d.externalDocsUrl.trim() !== '' || d.externalDocsDescription.trim() !== '',
      extensions: Object.keys(d.extensions).length > 0,
    };
  }, [formData]);

  const classDescriptionAiPayload = useMemo(() => {
    const members = Array.isArray(editingClassData?.properties) ? editingClassData.properties : [];
    return buildClassDescriptionAiPayload({
      members,
      composition: {
        allOf: formData.allOf,
        anyOf: formData.anyOf,
        oneOf: formData.oneOf,
      },
    });
  }, [editingClassData?.properties, formData.allOf, formData.anyOf, formData.oneOf]);

  const handleClassDescriptionAiGenerated = useCallback((text: string) => {
    setFormData((prev) => ({ ...prev, description: text }));
  }, []);

  const classDescriptionAiSlot =
    open && classDescriptionAiContext && classDescriptionAiContext.projectId.trim() ? (
      <ClassDescriptionAiButton
        tenantId={classDescriptionAiContext.tenantId}
        projectId={classDescriptionAiContext.projectId}
        versionId={classDescriptionAiContext.versionId}
        studioClassName={formData.name}
        classShape={classDescriptionAiPayload}
        existingClasses={classDescriptionAiContext.existingClasses}
        existingProperties={classDescriptionAiContext.existingProperties}
        studioContext={classDescriptionAiContext.studioContext}
        onGenerated={handleClassDescriptionAiGenerated}
        disabled={isReadOnly || !formData.name.trim()}
      />
    ) : null;

  // Reset view and form when dialog opens
  useEffect(() => {
    if (open) {
      setActiveTab('edit');
      setExampleRefreshKey(0);
      setShowAIChatMode(false);
      setAiMessages([]);
      setAiInput('');
      setAiCreateError('');
      setNewDependentSchemaProperty('');
      setCurrentStepIndex(0);

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
            let additionalPropsType: 'default' | 'allow' | 'disallow' | 'schema' | 'type' = 'default';
            let additionalPropsSchema = '';
            let additionalPropsInlineType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
            if (schema.additionalProperties !== undefined) {
              if (schema.additionalProperties === true) {
                additionalPropsType = 'allow';
              } else if (schema.additionalProperties === false) {
                additionalPropsType = 'disallow';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.$ref) {
                additionalPropsType = 'schema';
                additionalPropsSchema = schema.additionalProperties.$ref.split('/').pop() || '';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.type) {
                // Inline type schema like { type: 'string' }
                additionalPropsType = 'type';
                additionalPropsInlineType = schema.additionalProperties.type;
              } else if (typeof schema.additionalProperties === 'object') {
                // Other inline schema - default to 'type' with string
                additionalPropsType = 'type';
              }
            }

            // Determine unevaluatedProperties type and schema
            let unevaluatedPropsType: 'default' | 'allow' | 'disallow' | 'schema' | 'type' = 'default';
            let unevaluatedPropsSchema = '';
            let unevaluatedPropsInlineType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
            if (schema.unevaluatedProperties !== undefined) {
              if (schema.unevaluatedProperties === true) {
                unevaluatedPropsType = 'allow';
              } else if (schema.unevaluatedProperties === false) {
                unevaluatedPropsType = 'disallow';
              } else if (typeof schema.unevaluatedProperties === 'object' && schema.unevaluatedProperties.$ref) {
                unevaluatedPropsType = 'schema';
                unevaluatedPropsSchema = schema.unevaluatedProperties.$ref.split('/').pop() || '';
              } else if (typeof schema.unevaluatedProperties === 'object' && schema.unevaluatedProperties.type) {
                // Inline type schema like { type: 'string' }
                unevaluatedPropsType = 'type';
                unevaluatedPropsInlineType = schema.unevaluatedProperties.type;
              } else if (typeof schema.unevaluatedProperties === 'object') {
                // Other inline schema - default to 'type' with string
                unevaluatedPropsType = 'type';
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

            // Extract dependentSchemas - preserve full objects (if/then/else, not just refs)
            const dependentSchemasObj: Record<string, any> = {};
            if (schema.dependentSchemas && typeof schema.dependentSchemas === 'object') {
              Object.entries(schema.dependentSchemas).forEach(([key, value]) => {
                dependentSchemasObj[key] = value;
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
              additionalPropertiesInlineType: additionalPropsInlineType,
              unevaluatedProperties: schema.unevaluatedProperties !== undefined ? schema.unevaluatedProperties : null,
              unevaluatedPropertiesType: unevaluatedPropsType,
              unevaluatedPropertiesSchema: unevaluatedPropsSchema,
              unevaluatedPropertiesInlineType: unevaluatedPropsInlineType,
              patternProperties: patternPropsArray,
              dependentSchemas: dependentSchemasObj,
              dependentRequired: dependentRequiredArray,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: tagIds,
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              conditionalRules,
              // Object constraints
              minProperties: schema.minProperties?.toString() || '',
              maxProperties: schema.maxProperties?.toString() || '',
              examples: schema.examples ? schema.examples.map((ex: any) => JSON.stringify(ex)) : [],
              // XML Object
              xmlName: schema.xml?.name || '',
              xmlNamespace: schema.xml?.namespace || '',
              xmlPrefix: schema.xml?.prefix || '',
              // Schema metadata
              schemaId: schema.$id || '',
              schemaAnchor: schema.$anchor || '',
              schemaComment: schema.$comment || '',
              error: ''
            });
          } catch (error) {
            console.error('Error loading tags:', error);
            // Determine additionalProperties type and schema for error case
            let additionalPropsType: 'default' | 'allow' | 'disallow' | 'schema' | 'type' = 'default';
            let additionalPropsSchema = '';
            let additionalPropsInlineType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
            if (schema.additionalProperties !== undefined) {
              if (schema.additionalProperties === true) {
                additionalPropsType = 'allow';
              } else if (schema.additionalProperties === false) {
                additionalPropsType = 'disallow';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.$ref) {
                additionalPropsType = 'schema';
                additionalPropsSchema = schema.additionalProperties.$ref.split('/').pop() || '';
              } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.type) {
                additionalPropsType = 'type';
                additionalPropsInlineType = schema.additionalProperties.type;
              } else if (typeof schema.additionalProperties === 'object') {
                additionalPropsType = 'type';
              }
            }
            // Determine unevaluatedProperties type and schema for error case
            let unevaluatedPropsType: 'default' | 'allow' | 'disallow' | 'schema' | 'type' = 'default';
            let unevaluatedPropsSchema = '';
            let unevaluatedPropsInlineType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
            if (schema.unevaluatedProperties !== undefined) {
              if (schema.unevaluatedProperties === true) {
                unevaluatedPropsType = 'allow';
              } else if (schema.unevaluatedProperties === false) {
                unevaluatedPropsType = 'disallow';
              } else if (typeof schema.unevaluatedProperties === 'object' && schema.unevaluatedProperties.$ref) {
                unevaluatedPropsType = 'schema';
                unevaluatedPropsSchema = schema.unevaluatedProperties.$ref.split('/').pop() || '';
              } else if (typeof schema.unevaluatedProperties === 'object' && schema.unevaluatedProperties.type) {
                unevaluatedPropsType = 'type';
                unevaluatedPropsInlineType = schema.unevaluatedProperties.type;
              } else if (typeof schema.unevaluatedProperties === 'object') {
                unevaluatedPropsType = 'type';
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
            // Extract dependentSchemas for error case - preserve full objects
            const dependentSchemasObjError: Record<string, any> = {};
            if (schema.dependentSchemas && typeof schema.dependentSchemas === 'object') {
              Object.entries(schema.dependentSchemas).forEach(([key, value]) => {
                dependentSchemasObjError[key] = value;
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
              additionalPropertiesInlineType: additionalPropsInlineType,
              unevaluatedProperties: schema.unevaluatedProperties !== undefined ? schema.unevaluatedProperties : null,
              unevaluatedPropertiesType: unevaluatedPropsType,
              unevaluatedPropertiesSchema: unevaluatedPropsSchema,
              unevaluatedPropertiesInlineType: unevaluatedPropsInlineType,
              patternProperties: patternPropsArrayError,
              dependentSchemas: dependentSchemasObjError,
              dependentRequired: dependentRequiredArrayError,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: [],
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              conditionalRules,
              // Object constraints
              minProperties: schema.minProperties?.toString() || '',
              maxProperties: schema.maxProperties?.toString() || '',
              examples: schema.examples ? schema.examples.map((ex: any) => JSON.stringify(ex)) : [],
              // XML Object
              xmlName: schema.xml?.name || '',
              xmlNamespace: schema.xml?.namespace || '',
              xmlPrefix: schema.xml?.prefix || '',
              // Schema metadata
              schemaId: schema.$id || '',
              schemaAnchor: schema.$anchor || '',
              schemaComment: schema.$comment || '',
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
          additionalPropertiesInlineType: 'string',
          unevaluatedProperties: null,
          unevaluatedPropertiesType: 'default',
          unevaluatedPropertiesSchema: '',
          unevaluatedPropertiesInlineType: 'string',
          patternProperties: [],
          dependentSchemas: {},
          dependentRequired: [],
          deprecated: false,
          deprecationMessage: '',
          selectedTags: [],
          extensions: {},
          externalDocsUrl: '',
          externalDocsDescription: '',
          conditionalRules: [],
          // Object constraints
          minProperties: '',
          maxProperties: '',
          examples: [],
          // XML Object
          xmlName: '',
          xmlNamespace: '',
          xmlPrefix: '',
          // Schema metadata
          schemaId: '',
          schemaAnchor: '',
          schemaComment: '',
          error: ''
        });
      }
    }
  }, [open, editingClassData]);

  // Load Ollama models and project properties when AI chat mode is shown
  useEffect(() => {
    if (open && showAIChatMode) {
      let cancelled = false;
      (async () => {
        setAiLoadingModels(true);
        try {
          const [modelsRes, propsRes] = await Promise.all([
            fetch('/api/ollama/models'),
            projectId ? fetch(`/api/properties/${projectId}`) : Promise.resolve(null),
          ]);
          if (cancelled) return;
          const modelsData = await modelsRes.json();
          if (modelsData.success && modelsData.models?.length) {
            setAiModels(modelsData.models);
            if (!aiSelectedModel) setAiSelectedModel(modelsData.models[0].name);
          }
          if (propsRes?.ok) {
            const propsData = await propsRes.json();
            if (propsData.success && Array.isArray(propsData.properties)) {
              setAiProjectProperties(propsData.properties);
            }
          }
        } catch (e) {
          console.error('Failed to load Ollama models or properties', e);
        } finally {
          if (!cancelled) setAiLoadingModels(false);
        }
      })();
      return () => { cancelled = true; };
    }
  }, [open, showAIChatMode, projectId]);

  useEffect(() => {
    if (!open || editingClassData || !aiAssistantSeedMarkdown?.trim()) return;
    const md = aiAssistantSeedMarkdown.trim();
    setShowAIChatMode(true);
    setAiMessages([{ role: 'assistant', content: md }]);
    onAiAssistantSeedConsumed?.();
  }, [open, editingClassData, aiAssistantSeedMarkdown, onAiAssistantSeedConsumed]);

  useEffect(() => {
    if (!open) {
      classNamePropertySuggestGateRef.current = false;
      return;
    }
    if (editingClassData || isReadOnly || !onClassNameEnteredForPropertySuggestions) return;
    const t = formData.name.trim();
    if (t.length >= 2 && !classNamePropertySuggestGateRef.current) {
      classNamePropertySuggestGateRef.current = true;
      onClassNameEnteredForPropertySuggestions();
    }
  }, [open, editingClassData, isReadOnly, formData.name, onClassNameEnteredForPropertySuggestions]);

  useEffect(() => {
    aiMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [aiMessages, aiStreamingContent]);

  const handleAiSendMessage = async () => {
    if (!aiInput.trim() || !aiSelectedModel || aiLoading) return;
    const userMessage = { role: 'user' as const, content: aiInput.trim() };
    setAiMessages(prev => [...prev, userMessage]);
    setAiInput('');
    setAiLoading(true);
    setAiStreamingContent('');
    setAiCreateError('');
    aiAbortControllerRef.current = new AbortController();
    try {
      const existingClassNames = nodes.map((n: any) => n.data?.name).filter(Boolean);
      const existingProperties = aiProjectProperties.map((p) => ({
        name: p.name,
        description: p.description ?? null,
        data: p.data,
      }));

      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: aiSelectedModel,
          messages: [...aiMessages, userMessage],
          task: 'class_skeleton',
          existingClassNames,
          existingProperties,
        }),
        signal: aiAbortControllerRef.current.signal,
      });
      if (!response.ok) throw new Error('Failed to get response from LLM');
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulated = '';
      let messageAdded = false;
      if (reader) {
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.trim() || !line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') {
              setAiMessages(prev => [...prev, { role: 'assistant', content: accumulated }]);
              setAiStreamingContent('');
              messageAdded = true;
              break;
            }
            try {
              const event = JSON.parse(data);
              if (event.content) {
                accumulated += event.content;
                setAiStreamingContent(accumulated);
              }
            } catch (_) {}
          }
        }
        if (accumulated && !messageAdded && !aiAbortControllerRef.current?.signal.aborted) {
          setAiMessages(prev => [...prev, { role: 'assistant', content: accumulated }]);
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        console.error('AI chat error', err);
        setAiMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
      }
    } finally {
      setAiLoading(false);
      setAiStreamingContent('');
      aiAbortControllerRef.current = null;
    }
  };

  const handleAiCreateClass = async (content: string) => {
    const def = parseClassDefinitionFromAssistantMarkdown(content);
    if (!def || !versionId) {
      setAiCreateError(def ? 'No version selected.' : 'No valid class definition in this message.');
      return;
    }
    if (!/^[A-Za-z0-9_]+$/.test(def.name)) {
      setAiCreateError('Class name can only contain letters, numbers, and underscores.');
      return;
    }
    setAiCreateError('');
    const rawSchema = def.schema;
    if (!rawSchema || typeof rawSchema !== 'object' || Array.isArray(rawSchema)) {
      setAiCreateError('Invalid schema in class definition.');
      return;
    }
    const schema: Record<string, any> = { ...(rawSchema as Record<string, any>) };
    if (schema.type !== 'object') schema.type = 'object';
    if (typeof schema.properties !== 'object') schema.properties = {};
    try {
      const response = await createClassWithSession(versionId, def.name, def.description, schema);
      if (!response.success || !response.class) {
        setAiCreateError(response.error || 'Failed to create class');
        return;
      }
      const classId = response.class.id as string;
      const props = schema.properties as Record<string, any>;
      const propNames = Object.keys(props || {});
      for (const propName of propNames) {
        const propSchema = props[propName];
        if (!propSchema || typeof propSchema !== 'object') continue;
        const description = typeof propSchema.description === 'string' ? propSchema.description : null;
        const hasRef = !!(propSchema.$ref || (propSchema.type === 'array' && propSchema.items?.$ref));
        let propertyId: string | null = null;
        if (!hasRef && projectId) {
          const existing = aiProjectProperties.find((p) => p.name === propName);
          if (existing) {
            propertyId = existing.id;
          } else {
            const createRes = await fetch(`/api/properties/${projectId}`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: propName, description, data: propSchema }),
            });
            const createData = await createRes.json();
            if (createData.success && createData.property?.id) {
              propertyId = createData.property.id;
            } else {
              console.warn(`Could not create library property "${propName}": ${createData.error}`);
              continue;
            }
          }
        }
        if (!hasRef && !propertyId) continue;
        const addRes = await fetch(`/api/classes/${classId}/properties`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            property_id: propertyId,
            name: propName,
            description,
            data: propSchema,
          }),
        });
        const addData = await addRes.json();
        if (!addData.success) {
          console.warn(`Could not add property "${propName}" to class: ${addData.error}`);
        }
      }
      onSave?.();
      onClose();
    } catch (e: any) {
      setAiCreateError(e?.message || 'Failed to create class');
    }
  };

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

    // Add discriminator if specified (can be used on base classes or with composition)
    if (formData.discriminatorProperty) {
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
    } else if (formData.additionalPropertiesType === 'type') {
      schema.additionalProperties = { type: formData.additionalPropertiesInlineType };
    }
    // 'default' means no additionalProperties field is added

    // Add unevaluatedProperties based on the selected type
    if (formData.unevaluatedPropertiesType === 'allow') {
      schema.unevaluatedProperties = true;
    } else if (formData.unevaluatedPropertiesType === 'disallow') {
      schema.unevaluatedProperties = false;
    } else if (formData.unevaluatedPropertiesType === 'schema' && formData.unevaluatedPropertiesSchema) {
      schema.unevaluatedProperties = { $ref: `#/components/schemas/${formData.unevaluatedPropertiesSchema}` };
    } else if (formData.unevaluatedPropertiesType === 'type') {
      schema.unevaluatedProperties = { type: formData.unevaluatedPropertiesInlineType };
    }
    // 'default' means no unevaluatedProperties field is added

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
    // Add dependentSchemas if defined - preserve full schema objects
    if (Object.keys(formData.dependentSchemas).length > 0) {
      schema.dependentSchemas = formData.dependentSchemas;
    } else {
      delete schema.dependentSchemas;
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

    // Add object constraints (OpenAPI 3.1)
    if (formData.minProperties.trim()) {
      const val = parseInt(formData.minProperties.trim(), 10);
      if (!isNaN(val) && val >= 0) {
        schema.minProperties = val;
      }
    }
    if (formData.maxProperties.trim()) {
      const val = parseInt(formData.maxProperties.trim(), 10);
      if (!isNaN(val) && val >= 0) {
        schema.maxProperties = val;
      }
    }

    // Add examples array (JSON Schema)
    if (formData.examples.length > 0) {
      schema.examples = formData.examples.map((ex: string) => {
        try {
          return JSON.parse(ex);
        } catch {
          return ex;
        }
      });
    }

    // Add XML Object (OpenAPI 3.1)
    const hasXml = formData.xmlName.trim() || formData.xmlNamespace.trim() || formData.xmlPrefix.trim();
    if (hasXml) {
      schema.xml = {};
      if (formData.xmlName.trim()) schema.xml.name = formData.xmlName.trim();
      if (formData.xmlNamespace.trim()) schema.xml.namespace = formData.xmlNamespace.trim();
      if (formData.xmlPrefix.trim()) schema.xml.prefix = formData.xmlPrefix.trim();
    }

    // Add schema metadata (JSON Schema 2020-12)
    if (formData.schemaId.trim()) {
      schema.$id = formData.schemaId.trim();
    }
    if (formData.schemaAnchor.trim()) {
      schema.$anchor = formData.schemaAnchor.trim();
    }
    if (formData.schemaComment.trim()) {
      schema.$comment = formData.schemaComment.trim();
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

  // Create a stable stringified version of formData for dependency tracking
  const formDataString = useMemo(() => JSON.stringify(formData), [formData]);

  // Memoize the built schema from current form so Example/JSON/YAML tabs stay in sync
  const builtSchema = useMemo(() => {
    if (editingClassData && !formData.name) {
      // Form not yet initialized (first frame after open) – use class schema
      return typeof editingClassData.schema === 'string'
        ? JSON.parse(editingClassData.schema)
        : editingClassData.schema || {};
    }
    return buildSchemaFromFormData();
  }, [editingClassData, formDataString, formData.name]);

  // Memoize all classes array to prevent reference changes
  const allClasses = useMemo(() => {
    return nodes.map(node => node.data).filter(data => data && data.name);
  }, [nodes]);

  // Generate OpenAPI doc asynchronously with debouncing
  useEffect(() => {
    if (!open) return;

    // Debounce the generation to prevent rapid successive calls
    const timeoutId = setTimeout(() => {
      const generateOpenApiDocAsync = async () => {
        setLoadingOpenApiDoc(true);
        try {
          // Use current form schema so Example tab reflects latest edits
          let previewClassData = editingClassData
            ? { ...editingClassData, schema: builtSchema }
            : {
                name: formData.name || 'NewClass',
                description: formData.description,
                schema: builtSchema
              };

          // When opened from sidebar, class data may lack properties – fetch full class for example generation
          if (
            previewClassData.id &&
            (!previewClassData.properties || previewClassData.properties.length === 0)
          ) {
            const res = await getClassWithPropertiesAndTagsWithSession(previewClassData.id);
            if (res.success && res.class) {
              previewClassData = { ...res.class, schema: builtSchema };
            }
          }

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
    }, 300); // 300ms debounce

    return () => clearTimeout(timeoutId);
  }, [open, builtSchema, allClasses, editingClassData, projectMetadata]);

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

      let response: { success: boolean; class?: any; error?: string };
      let classId: string;

      if (editingClassData) {
        // Update existing class via REST API
        response = await updateClassWithSession(
          editingClassData.id,
          formData.name,
          formData.description || null,
          schema
        );
        classId = editingClassData.id;
      } else {
        // Create new class via REST API
        response = await createClassWithSession(
          versionId!,
          formData.name,
          formData.description || null,
          schema
        );
        if (response.success && response.class) {
          classId = response.class.id;
        } else {
          setFormData(prev => ({ ...prev, error: response.error || 'Failed to create class' }));
          setSaving(false);
          return;
        }
      }

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
  const openApiClassSchema = openApiDoc?.components?.schemas?.[previewClassData.name];

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
      const resolvedSchema = resolveRefs(openApiClassSchema, openApiDoc.components.schemas);

      // Debug: Log the resolved schema to verify allOf merging
      console.log('Original schema:', openApiClassSchema);
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
        const resolvedSchema = resolveRefs(openApiClassSchema, openApiDoc.components.schemas);
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
        const resolvedSchema = resolveRefs(openApiClassSchema, openApiDoc.components.schemas);
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
    <>
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()} modal={true}>
      <DialogContent
        className="max-w-7xl h-[90vh] max-h-[900px] p-0 flex flex-col overflow-hidden"
        showCloseButton={true}
        aria-describedby={undefined}
      >
        <DialogHeader className="pl-6 pr-10 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="flex items-center gap-3 flex-wrap min-w-0">
              {showAIChatMode ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowAIChatMode(false)}
                    className="flex items-center gap-1 text-gray-600 dark:text-gray-400"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Back to form
                  </Button>
                  <DialogTitle className="text-lg font-semibold">
                    Create Class with AI
                  </DialogTitle>
                </>
              ) : (
                <>
                  <DialogTitle className="text-lg font-semibold">
                    {!editingClassData ? 'Add Class' : isReadOnly ? `View Class: ${formData.name || editingClassData.name}` : `Edit Class: ${formData.name || editingClassData.name}`}
                  </DialogTitle>
                  {!editingClassData && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setShowAIChatMode(true)}
                      className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 border-indigo-200 dark:border-indigo-800"
                    >
                      <Sparkles className="h-4 w-4" />
                      Use AI Assistant
                    </Button>
                  )}
                </>
              )}
              {isReadOnly && !showAIChatMode && (
                <span className="px-2 py-0.5 bg-amber-400 text-black text-xs font-semibold rounded">
                  Read Only
                </span>
              )}
            </div>
          </div>
        </DialogHeader>

        {showAIChatMode ? (
          <>
            <div className="px-6 py-3 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Model:</label>
              <SelectRadix.Root value={aiSelectedModel} onValueChange={setAiSelectedModel} disabled={aiLoadingModels || aiLoading}>
                <SelectRadix.Trigger className="flex items-center gap-2 px-3 py-1.5 text-sm bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors">
                  <SelectRadix.Value placeholder={aiLoadingModels ? 'Loading models...' : 'Select a model'} />
                  <SelectRadix.Icon>
                    <ChevronDown className="h-4 w-4" />
                  </SelectRadix.Icon>
                </SelectRadix.Trigger>
                <SelectRadix.Portal>
                  <SelectRadix.Content className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-1 z-[10000]">
                    <SelectRadix.Viewport>
                      {aiModels.map(m => (
                        <SelectRadix.Item key={m.name} value={m.name} className="px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <SelectRadix.ItemText>{m.name}</SelectRadix.ItemText>
                        </SelectRadix.Item>
                      ))}
                    </SelectRadix.Viewport>
                  </SelectRadix.Content>
                </SelectRadix.Portal>
              </SelectRadix.Root>
              {aiMessages.length > 0 && (
                <button type="button" onClick={() => { setAiMessages([]); setAiInput(''); setAiCreateError(''); }} className="ml-auto px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
                  Reset conversation
                </button>
              )}
            </div>
            {aiCreateError && <Alert variant="error" className="m-4 mb-0">{aiCreateError}</Alert>}
            <div className="flex-1 overflow-y-auto p-6 space-y-4 min-h-0">
              {aiMessages.length === 0 && !aiStreamingContent && (
                <div className="flex flex-col items-center justify-center text-center py-8">
                  <div className="w-16 h-16 mb-4 bg-gradient-to-br from-purple-100 to-indigo-100 dark:from-purple-900/30 dark:to-indigo-900/30 rounded-2xl flex items-center justify-center">
                    <Bot className="h-8 w-8 text-purple-600 dark:text-purple-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Describe the class you want</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mb-6">
                    Tell me what the class should represent and which properties it should have. I'll generate a JSON Schema class definition you can create in one click.
                  </p>
                  <div className="grid grid-cols-1 gap-2 w-full max-w-lg">
                    <button type="button" onClick={() => setAiInput('Create a User class with email, displayName, and createdAt')} className="px-4 py-3 text-sm text-left text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors border border-gray-200 dark:border-gray-700">
                      👤 User with email, displayName, and createdAt
                    </button>
                    <button type="button" onClick={() => setAiInput('Create an Order class with orderId, items array, totalAmount, and status')} className="px-4 py-3 text-sm text-left text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors border border-gray-200 dark:border-gray-700">
                      🛒 Order with items, totalAmount, and status
                    </button>
                    <button type="button" onClick={() => setAiInput('Create a Product class with name, sku, price, and optional description')} className="px-4 py-3 text-sm text-left text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors border border-gray-200 dark:border-gray-700">
                      📦 Product with name, sku, price, description
                    </button>
                    <button type="button" onClick={() => setAiInput('Create an Address class with street, city, postalCode, and country')} className="px-4 py-3 text-sm text-left text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors border border-gray-200 dark:border-gray-700">
                      📍 Address with street, city, postalCode, country
                    </button>
                  </div>
                </div>
              )}
              {aiMessages.map((message, index) => {
                const classDef =
                  message.role === 'assistant' ? parseClassDefinitionFromAssistantMarkdown(message.content) : null;
                const hasClassDef = classDef !== null;
                return (
                  <div key={index} className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    {message.role === 'assistant' && (
                      <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-full flex items-center justify-center">
                        <Bot className="h-5 w-5 text-white" />
                      </div>
                    )}
                    <div className={`flex flex-col max-w-[80%] ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                      <div className={`px-4 py-3 rounded-lg ${message.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'}`}>
                        {message.role === 'assistant' && hasClassDef && classDef ? (
                          <div className="rounded-lg overflow-hidden border border-gray-300 dark:border-gray-600">
                            <div className="bg-gray-800 dark:bg-gray-900 px-3 py-1.5 border-b border-gray-700">
                              <span className="text-xs font-mono text-gray-300">JSON Schema</span>
                            </div>
                            <div className="bg-gray-900 dark:bg-black px-4 py-2 border-b border-gray-800 space-y-1 text-xs">
                              <div>
                                <span className="text-gray-500 dark:text-gray-500">Class name</span>{' '}
                                <span className="font-mono text-gray-200">{classDef.name}</span>
                              </div>
                              <div>
                                <span className="text-gray-500 dark:text-gray-500">Description</span>{' '}
                                <span className="text-gray-300">
                                  {classDef.description?.trim() ? classDef.description : '—'}
                                </span>
                              </div>
                            </div>
                            <pre className="bg-gray-900 dark:bg-black p-4 overflow-x-auto m-0 text-left">
                              <code className="text-sm font-mono text-green-400 dark:text-green-300 whitespace-pre">
                                {JSON.stringify(classDef.schema, null, 2)}
                              </code>
                            </pre>
                          </div>
                        ) : (
                          <Markdown variant="default" fallback={null}>
                            {message.content}
                          </Markdown>
                        )}
                      </div>
                      {message.role === 'assistant' && hasClassDef && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="mt-2 gap-2 text-indigo-600 dark:text-indigo-400"
                          onClick={() => setAiCreatePreviewContent(message.content)}
                        >
                          <Plus className="h-4 w-4" />
                          Preview & create
                        </Button>
                      )}
                    </div>
                    {message.role === 'user' && (
                      <div className="flex-shrink-0 w-8 h-8 bg-indigo-600 rounded-full flex items-center justify-center">
                        <User className="h-5 w-5 text-white" />
                      </div>
                    )}
                  </div>
                );
              })}
              {aiLoading && !aiStreamingContent && (
                <div className="flex gap-3 justify-start">
                  <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-full flex items-center justify-center">
                    <Bot className="h-5 w-5 text-white" />
                  </div>
                  <div className="px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center gap-2">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                    <span className="text-sm text-gray-600 dark:text-gray-400">Thinking...</span>
                  </div>
                </div>
              )}
              {aiStreamingContent && (
                <div className="flex gap-3 justify-start">
                  <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-full flex items-center justify-center">
                    <Bot className="h-5 w-5 text-white" />
                  </div>
                  <div className="px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white">
                    <Markdown variant="default" fallback={null}>
                      {aiStreamingContent}
                    </Markdown>
                    <span className="inline-block w-2 h-4 ml-1 bg-gray-900 dark:bg-white animate-pulse align-middle" />
                  </div>
                </div>
              )}
              <div ref={aiMessagesEndRef} />
            </div>
            <div className="border-t border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={aiInput}
                  onChange={e => setAiInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleAiSendMessage()}
                  placeholder="Describe the class you want to create..."
                  disabled={aiLoading || !aiSelectedModel}
                  className="flex-1 px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50"
                />
                <Button onClick={handleAiSendMessage} disabled={aiLoading || !aiInput.trim() || !aiSelectedModel} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg flex items-center gap-2">
                  {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Send
                </Button>
              </div>
              <p className="mt-2 mb-0 text-xs text-gray-500 dark:text-gray-400 text-center">
                AI can make mistakes — use Preview & create to review the schema before it is saved.
              </p>
            </div>
          </>
        ) : (
        <>
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
          <div className="flex flex-nowrap items-center border-b border-gray-200 dark:border-gray-700 px-6 shrink-0">
            <TabsList className="h-auto p-0 rounded-none bg-transparent justify-start gap-0 -ml-2 shrink-0">
              <TabsTrigger
              value="edit"
              className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
            >
              Edit
            </TabsTrigger>
            <TabsTrigger
              value="json"
              className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
            >
              JSON
            </TabsTrigger>
            <TabsTrigger
              value="yaml"
              className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
            >
              YAML
            </TabsTrigger>
            <TabsTrigger
              value="example"
              className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
            >
              Example
            </TabsTrigger>
            </TabsList>
          </div>

          {/* Edit Tab */}
          <TabsContent value="edit" className="flex-1 flex flex-col overflow-hidden mt-0 p-0">
            {formData.error && <Alert variant="error" className="m-4 mb-0">{formData.error}</Alert>}

            {/* View-mode toolbar — the toggle is intentionally the only
                control here; guided mode's stepper renders immediately below
                and advanced mode uses the sidebar nav for context. */}
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/60 px-6 py-2.5 dark:border-slate-800 dark:bg-slate-900/40 shrink-0">
              <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                {viewMode === 'guided' ? 'Wizard' : 'All sections'}
              </span>
              <FormViewModeToggle value={viewMode} onChange={setViewMode} />
            </div>
            {viewMode === 'guided' && (
              <FormWizardStepper
                steps={CLASS_WIZARD_STEPS.map((step, idx) => ({
                  id: step.id,
                  label: step.label,
                  complete: idx < currentStepIndex,
                }))}
                currentIndex={currentStepIndex}
                onStepSelect={setCurrentStepIndex}
              />
            )}

            {/* Body: sidebar nav + scrolling sections (advanced), or single-pane (guided) */}
            <div className="flex-1 flex overflow-hidden min-h-0">
              {viewMode === 'advanced' && (
                <FormSectionNav
                  title="Sections"
                  items={[
                    { id: 'basics', label: 'Basic Information', icon: <FileText className="h-3.5 w-3.5" />, group: 'Basics', changed: changedSections.basics },
                    { id: 'object-constraints', label: 'Object Constraints', icon: <Settings className="h-3.5 w-3.5" />, group: 'Validation', changed: changedSections['object-constraints'] },
                    { id: 'additional-props', label: 'Additional Properties', icon: <Layers className="h-3.5 w-3.5" />, group: 'Validation', changed: changedSections['additional-props'] },
                    { id: 'unevaluated-props', label: 'Unevaluated Properties', icon: <Layers className="h-3.5 w-3.5" />, group: 'Validation', changed: changedSections['unevaluated-props'] },
                    { id: 'composition', label: 'Composition', icon: <GitBranch className="h-3.5 w-3.5" />, group: 'Composition', changed: changedSections.composition },
                    { id: 'pattern-props', label: 'Pattern Properties', icon: <Regex className="h-3.5 w-3.5" />, group: 'Dynamic Properties', changed: changedSections['pattern-props'] },
                    { id: 'dependent-schemas', label: 'Dependent Schemas', icon: <Link className="h-3.5 w-3.5" />, group: 'Dynamic Properties', changed: changedSections['dependent-schemas'] },
                    { id: 'dependent-required', label: 'Dependent Required', icon: <ListChecks className="h-3.5 w-3.5" />, group: 'Dynamic Properties', changed: changedSections['dependent-required'] },
                    { id: 'conditional', label: 'Conditional Schema', icon: <GitBranch className="h-3.5 w-3.5" />, group: 'Dynamic Properties', changed: changedSections.conditional },
                    { id: 'examples', label: 'Examples', icon: <Code className="h-3.5 w-3.5" />, group: 'Documentation', changed: changedSections.examples },
                    { id: 'xml', label: 'XML Representation', icon: <Code className="h-3.5 w-3.5" />, group: 'Documentation', changed: changedSections.xml },
                    { id: 'schema-metadata', label: 'Schema Metadata', icon: <FileText className="h-3.5 w-3.5" />, group: 'Documentation', changed: changedSections['schema-metadata'] },
                    { id: 'external-docs', label: 'External Docs', icon: <ExternalLink className="h-3.5 w-3.5" />, group: 'Documentation', changed: changedSections['external-docs'] },
                    { id: 'extensions', label: 'Extensions', icon: <Code className="h-3.5 w-3.5" />, group: 'Documentation', changed: changedSections.extensions },
                  ]}
                  activeId={activeSectionId}
                  onSelect={(id) => scrollToSection(advancedScrollRef.current, id, 24)}
                  className="h-full"
                />
              )}

              <div
                ref={advancedScrollRef}
                className="flex-1 overflow-y-auto min-h-0"
              >

              {/* SECTION: Basic Information */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('basics')) && (
              <FormSection
                id="basics"
                icon={<FileText size={16} />}
                eyebrow="Identity"
                title="Basic Information"
                description="Name, description, tags, and deprecation metadata."
                changed={changedSections.basics}
              >
                <FormGrid cols={3} gap="md">
                  <FormFieldGroup label="Class Name" htmlFor="className" required helper="PascalCase recommended">
                    <Input
                      id="className"
                      autoFocus
                      value={formData.name}
                      onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value.replace(/[^A-Za-z0-9_]/g, '') }))}
                      placeholder="e.g., UserAccount"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                  <FormFieldGroup label="Description" htmlFor="description" className="md:col-span-2">
                    <Textarea
                      id="description"
                      value={formData.description}
                      onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="Brief description of what this class represents"
                      disabled={isReadOnly}
                      rows={2}
                    />
                    {classDescriptionAiSlot ? <div className="mt-2">{classDescriptionAiSlot}</div> : null}
                  </FormFieldGroup>
                </FormGrid>

                {/* Tags */}
                {projectId && projectTags && projectTags.length > 0 && (
                  <FormFieldGroup label="Tags">
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
                  </FormFieldGroup>
                )}

                <FormToggleCard
                  id="deprecated"
                  icon={<AlertTriangle className="h-3.5 w-3.5" />}
                  accent="amber"
                  label="Deprecated"
                  description="Mark this class as deprecated. Consumers will see a warning."
                  checked={formData.deprecated}
                  onCheckedChange={(checked) => setFormData(prev => ({ ...prev, deprecated: checked }))}
                  disabled={isReadOnly}
                  stack={formData.deprecated}
                  trailing={formData.deprecated ? (
                    <Input
                      value={formData.deprecationMessage}
                      onChange={(e) => setFormData(prev => ({ ...prev, deprecationMessage: e.target.value }))}
                      placeholder="Deprecation message (e.g., Use NewClass instead)"
                      disabled={isReadOnly}
                      className="h-8 text-sm"
                    />
                  ) : undefined}
                />
              </FormSection>
              )}

              {/* SECTION: Object Constraints */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('object-constraints')) && (
              <FormSection
                id="object-constraints"
                icon={<Settings size={16} />}
                eyebrow="Validation"
                title="Object Constraints"
                description="Limits on the number of properties an instance of this class may contain."
                badge={<Badge variant="secondary" className="text-xs">OpenAPI 3.1</Badge>}
                changed={changedSections['object-constraints']}
              >
                <FormGrid cols={2} gap="md">
                  <FormFieldGroup label="Min Properties" helper="Minimum number of properties required">
                    <Input
                      type="number"
                      min="0"
                      value={formData.minProperties}
                      onChange={(e) => setFormData(prev => ({ ...prev, minProperties: e.target.value }))}
                      placeholder="e.g., 1"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                  <FormFieldGroup label="Max Properties" helper="Maximum number of properties allowed">
                    <Input
                      type="number"
                      min="0"
                      value={formData.maxProperties}
                      onChange={(e) => setFormData(prev => ({ ...prev, maxProperties: e.target.value }))}
                      placeholder="e.g., 10"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                </FormGrid>
              </FormSection>
              )}

              {/* SECTION: Additional Properties */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('additional-props')) && (
              <FormSection
                id="additional-props"
                icon={<Layers size={16} />}
                eyebrow="Validation"
                title="Additional Properties"
                description="Controls validation for properties not defined in the schema."
                changed={changedSections['additional-props']}
              >
                <div className="space-y-2">
                      {(['default', 'allow', 'disallow', 'type', 'schema'] as const).map((value) => (
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
                                additionalPropertiesSchema: val === 'schema' ? prev.additionalPropertiesSchema : '',
                                additionalPropertiesInlineType: val === 'type' ? prev.additionalPropertiesInlineType : 'string'
                              }));
                            }}
                            disabled={isReadOnly}
                            className="w-4 h-4 text-indigo-600"
                          />
                          <span className="text-sm text-gray-700 dark:text-gray-300">
                            {value === 'default' && 'Not specified (default)'}
                            {value === 'allow' && 'Allow Any (true)'}
                            {value === 'disallow' && 'Disallow (false)'}
                            {value === 'type' && 'Must Be Type'}
                            {value === 'schema' && 'Must Match Schema'}
                          </span>
                        </label>
                      ))}
                      {formData.additionalPropertiesType === 'type' && (
                        <div className="mt-2 pl-6">
                          <Select
                            value={formData.additionalPropertiesInlineType}
                            onValueChange={(val) => setFormData(prev => ({ ...prev, additionalPropertiesInlineType: val as any }))}
                            disabled={isReadOnly}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Select a type..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="string">string</SelectItem>
                              <SelectItem value="number">number</SelectItem>
                              <SelectItem value="integer">integer</SelectItem>
                              <SelectItem value="boolean">boolean</SelectItem>
                              <SelectItem value="object">object</SelectItem>
                              <SelectItem value="array">array</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      )}
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
              </FormSection>
              )}

              {/* SECTION: Unevaluated Properties */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('unevaluated-props')) && (
              <FormSection
                id="unevaluated-props"
                icon={<Layers size={16} />}
                eyebrow="Validation"
                title="Unevaluated Properties"
                description="For properties not matched by allOf / oneOf / anyOf subschemas."
                changed={changedSections['unevaluated-props']}
              >
                <div className="space-y-2">
                      {(['default', 'allow', 'disallow', 'type', 'schema'] as const).map((value) => (
                        <label key={value} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio"
                            name="unevaluatedPropertiesType"
                            value={value}
                            checked={formData.unevaluatedPropertiesType === value}
                            onChange={(e) => {
                              const val = e.target.value as typeof value;
                              setFormData(prev => ({
                                ...prev,
                                unevaluatedPropertiesType: val,
                                unevaluatedProperties: val === 'default' ? null : val === 'allow' ? true : val === 'disallow' ? false : null,
                                unevaluatedPropertiesSchema: val === 'schema' ? prev.unevaluatedPropertiesSchema : '',
                                unevaluatedPropertiesInlineType: val === 'type' ? prev.unevaluatedPropertiesInlineType : 'string'
                              }));
                            }}
                            disabled={isReadOnly}
                            className="w-4 h-4 text-indigo-600"
                          />
                          <span className="text-sm text-gray-700 dark:text-gray-300">
                            {value === 'default' && 'Not specified (default)'}
                            {value === 'allow' && 'Allow Any (true)'}
                            {value === 'disallow' && 'Disallow (false)'}
                            {value === 'type' && 'Must Be Type'}
                            {value === 'schema' && 'Must Match Schema'}
                          </span>
                        </label>
                      ))}
                      {formData.unevaluatedPropertiesType === 'type' && (
                        <div className="mt-2 pl-6">
                          <Select
                            value={formData.unevaluatedPropertiesInlineType}
                            onValueChange={(val) => setFormData(prev => ({ ...prev, unevaluatedPropertiesInlineType: val as any }))}
                            disabled={isReadOnly}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Select a type..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="string">string</SelectItem>
                              <SelectItem value="number">number</SelectItem>
                              <SelectItem value="integer">integer</SelectItem>
                              <SelectItem value="boolean">boolean</SelectItem>
                              <SelectItem value="object">object</SelectItem>
                              <SelectItem value="array">array</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      )}
                      {formData.unevaluatedPropertiesType === 'schema' && (
                        <div className="mt-2 pl-6">
                          <Select
                            value={formData.unevaluatedPropertiesSchema || '__none__'}
                            onValueChange={(val) => setFormData(prev => ({ ...prev, unevaluatedPropertiesSchema: val === '__none__' ? '' : val }))}
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
              </FormSection>
              )}

              {/* SECTION: Composition & Inheritance */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('composition')) && (
              <FormSection
                id="composition"
                icon={<GitBranch size={16} />}
                eyebrow="Composition"
                title="Composition & Inheritance"
                description="Define relationships with other classes using OpenAPI composition keywords."
                changed={changedSections.composition}
              >
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  <FormSubsection
                    accent="indigo"
                    icon={<Layers className="h-4 w-4" />}
                    title="allOf (Inheritance)"
                    description="Must match ALL listed schemas."
                  >
                    <MultiSelect
                      options={availableClasses}
                      value={formData.allOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, allOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="indigo"
                    />
                  </FormSubsection>

                  <FormSubsection
                    accent="amber"
                    icon={<Layers className="h-4 w-4" />}
                    title="anyOf (Alternatives)"
                    description="Must match AT LEAST one schema."
                  >
                    <MultiSelect
                      options={availableClasses}
                      value={formData.anyOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, anyOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="amber"
                    />
                  </FormSubsection>

                  <FormSubsection
                    accent="purple"
                    icon={<Layers className="h-4 w-4" />}
                    title="oneOf (Exclusive)"
                    description="Must match EXACTLY one schema."
                  >
                    <MultiSelect
                      options={availableClasses}
                      value={formData.oneOf}
                      onChange={(newValue) => setFormData(prev => ({ ...prev, oneOf: newValue }))}
                      placeholder="Select classes..."
                      disabled={isReadOnly}
                      colorScheme="purple"
                    />
                  </FormSubsection>
                </div>

                {/* Discriminator */}
                {(formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0) && (
                  <FormSubsection
                    tone="subtle"
                    accent="indigo"
                    icon={<GitBranch className="h-4 w-4" />}
                    title="Discriminator Configuration"
                    description="Helps tools understand which schema variant to use for polymorphic types."
                  >
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
                        <>
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

                          {/* Custom Mapping UI */}
                          {!formData.discriminatorUseAuto && (
                            <div className="mt-3 p-3 bg-white dark:bg-slate-900 rounded-lg border border-gray-200 dark:border-gray-600">
                              <h5 className="text-xs font-semibold mb-2 text-gray-700 dark:text-gray-300">Custom Mapping</h5>
                              <p className="text-xs text-gray-500 mb-3">Map discriminator values to schema references</p>

                              {/* Existing mappings */}
                              {Object.entries(formData.discriminatorMapping).length > 0 && (
                                <div className="space-y-2 mb-3">
                                  {Object.entries(formData.discriminatorMapping).map(([value, schemaName]) => (
                                    <div key={value} className="flex items-center gap-2 p-2 bg-gray-50 dark:bg-slate-800 rounded">
                                      <code className="text-xs px-2 py-1 bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 rounded">
                                        {value}
                                      </code>
                                      <ArrowRight size={14} className="text-gray-400" />
                                      <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">
                                        #/components/schemas/{schemaName}
                                      </span>
                                      {!isReadOnly && (
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          className="h-6 w-6 p-0 text-red-500 hover:text-red-700 hover:bg-red-50"
                                          onClick={() => {
                                            const newMapping = { ...formData.discriminatorMapping };
                                            delete newMapping[value];
                                            setFormData(prev => ({ ...prev, discriminatorMapping: newMapping }));
                                          }}
                                        >
                                          <X size={14} />
                                        </Button>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}

                              {/* Add new mapping */}
                              {!isReadOnly && (
                                <div className="flex gap-2">
                                  <Input
                                    placeholder="Value (e.g., dog)"
                                    className="flex-1 text-sm"
                                    id="newDiscriminatorValue"
                                  />
                                  <Select
                                    onValueChange={(schemaName) => {
                                      const valueInput = document.getElementById('newDiscriminatorValue') as HTMLInputElement;
                                      const value = valueInput?.value?.trim();
                                      if (value && schemaName) {
                                        setFormData(prev => ({
                                          ...prev,
                                          discriminatorMapping: {
                                            ...prev.discriminatorMapping,
                                            [value]: schemaName
                                          }
                                        }));
                                        if (valueInput) valueInput.value = '';
                                      }
                                    }}
                                  >
                                    <SelectTrigger className="w-[180px]">
                                      <SelectValue placeholder="Select schema..." />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {availableClasses.map((cls) => (
                                        <SelectItem key={cls} value={cls}>{cls}</SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                              )}

                              {Object.entries(formData.discriminatorMapping).length === 0 && (
                                <p className="text-xs text-gray-400 italic mt-2">
                                  No mappings defined. Enter a discriminator value and select a target schema.
                                </p>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </FormSubsection>
                )}
              </FormSection>
              )}

              {/* SECTION: Pattern Properties */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('pattern-props')) && (
              <FormSection
                id="pattern-props"
                icon={<Regex size={16} />}
                eyebrow="Dynamic Properties"
                title="Pattern Properties"
                description="Define regex patterns that map dynamic property names to schemas."
                changed={changedSections['pattern-props']}
                action={!isReadOnly ? (
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
                ) : undefined}
              >
                {formData.patternProperties.length === 0 ? (
                  <FormEmptyState
                    icon={<Regex className="h-5 w-5" />}
                    title="No pattern properties defined"
                    description="Add a regex pattern to validate properties whose names are not known in advance."
                  />
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
              </FormSection>
              )}

              {/* SECTION: Dependent Schemas */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('dependent-schemas')) && (
              <FormSection
                id="dependent-schemas"
                icon={<Link size={16} />}
                eyebrow="Dynamic Properties"
                title="Dependent Schemas"
                description="Apply additional constraints conditionally when a property has a specific value."
                changed={changedSections['dependent-schemas']}
              >
                {!isReadOnly && (
                  <div className="flex gap-2 mb-4 w-full">
                    <Input
                      value={newDependentSchemaProperty}
                      onChange={(e) => setNewDependentSchemaProperty(e.target.value)}
                      placeholder="Trigger property name"
                      className="flex-1 min-w-0 font-mono"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          const name = newDependentSchemaProperty.trim();
                          if (name && !formData.dependentSchemas[name]) {
                            setFormData(prev => ({
                              ...prev,
                              dependentSchemas: {
                                ...prev.dependentSchemas,
                                [name]: {
                                  if: { properties: { [name]: {} } },
                                  then: { required: [] },
                                  else: { required: [] }
                                }
                              }
                            }));
                            setNewDependentSchemaProperty('');
                          }
                        }
                      }}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const name = newDependentSchemaProperty.trim();
                        if (!name) return;
                        if (formData.dependentSchemas[name]) return;
                        setFormData(prev => ({
                          ...prev,
                          dependentSchemas: {
                            ...prev.dependentSchemas,
                            [name]: {
                              if: { properties: { [name]: {} } },
                              then: { required: [] },
                              else: { required: [] }
                            }
                          }
                        }));
                        setNewDependentSchemaProperty('');
                      }}
                      disabled={!newDependentSchemaProperty.trim() || !!formData.dependentSchemas[newDependentSchemaProperty.trim()]}
                    >
                      <Plus size={14} className="mr-1" /> Add
                    </Button>
                  </div>
                )}

                {Object.keys(formData.dependentSchemas).length === 0 ? (
                  <FormEmptyState
                    icon={<Link className="h-5 w-5" />}
                    title="No dependent schemas defined"
                    description="Add conditional validation rules based on property values."
                  />
                ) : (
                  <div className="space-y-4">
                    {Object.entries(formData.dependentSchemas).map(([triggerProp, depSchema]: [string, any]) => {
                      // Extract values from the schema structure
                      const ifCondition = depSchema?.if?.properties?.[triggerProp] || depSchema?.if || {};
                      const thenRequired = depSchema?.then?.required || [];
                      const elseRequired = depSchema?.else?.required || [];
                      const conditionValue = ifCondition?.const || ifCondition?.enum?.[0] || '';
                      const conditionType = ifCondition?.const !== undefined ? 'const' : (ifCondition?.enum ? 'enum' : 'present');

                      return (
                        <div key={triggerProp} className="p-4 bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-gray-700">
                          {/* Header with delete button */}
                          <div className="flex gap-3 items-center justify-between mb-4">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-1 bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 rounded text-sm font-mono font-semibold">
                                {triggerProp}
                              </span>
                              <span className="text-sm text-gray-500">triggers conditional validation</span>
                            </div>
                            {!isReadOnly && (
                              <Button
                                size="icon"
                                variant="ghost"
                                className="text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 shrink-0 h-8 w-8"
                                onClick={() => {
                                  const newDeps = { ...formData.dependentSchemas };
                                  delete newDeps[triggerProp];
                                  setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                }}
                              >
                                <Trash2 size={14} />
                              </Button>
                            )}
                          </div>

                          {/* IF Condition */}
                          <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="px-2 py-0.5 bg-blue-500 text-white text-xs font-bold rounded">IF</span>
                              <span className="text-sm text-blue-700 dark:text-blue-300 font-medium">{triggerProp}</span>
                            </div>
                            <div className="flex flex-wrap gap-2 items-center">
                              <Select
                                value={conditionType}
                                onValueChange={(val) => {
                                  const newDeps = { ...formData.dependentSchemas };
                                  const newSchema = { ...depSchema };
                                  if (val === 'const') {
                                    newSchema.if = { properties: { [triggerProp]: { const: conditionValue || '' } } };
                                  } else if (val === 'enum') {
                                    newSchema.if = { properties: { [triggerProp]: { enum: conditionValue ? [conditionValue] : [] } } };
                                  } else {
                                    newSchema.if = { properties: { [triggerProp]: {} }, required: [triggerProp] };
                                  }
                                  newDeps[triggerProp] = newSchema;
                                  setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                }}
                                disabled={isReadOnly}
                              >
                                <SelectTrigger className="w-[140px] h-8 text-sm">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="present">is present</SelectItem>
                                  <SelectItem value="const">equals</SelectItem>
                                  <SelectItem value="enum">is one of</SelectItem>
                                </SelectContent>
                              </Select>
                              {(conditionType === 'const' || conditionType === 'enum') && (
                                <Input
                                  className="flex-1 min-w-[150px] h-8 text-sm"
                                  value={conditionValue}
                                  onChange={(e) => {
                                    const newDeps = { ...formData.dependentSchemas };
                                    const newSchema = { ...depSchema };
                                    if (conditionType === 'const') {
                                      newSchema.if = { properties: { [triggerProp]: { const: e.target.value } } };
                                    } else {
                                      newSchema.if = { properties: { [triggerProp]: { enum: e.target.value.split(',').map(s => s.trim()).filter(Boolean) } } };
                                    }
                                    newDeps[triggerProp] = newSchema;
                                    setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                  }}
                                  placeholder={conditionType === 'enum' ? 'value1, value2, ...' : 'value'}
                                  disabled={isReadOnly}
                                />
                              )}
                            </div>
                          </div>

                          {/* THEN - Required Properties */}
                          <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="px-2 py-0.5 bg-green-500 text-white text-xs font-bold rounded">THEN</span>
                              <span className="text-sm text-green-700 dark:text-green-300">require these properties:</span>
                            </div>
                            <div className="flex flex-wrap gap-2 items-center">
                              {thenRequired.map((prop: string, idx: number) => (
                                <span key={idx} className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 dark:bg-green-800/50 text-green-800 dark:text-green-200 rounded text-sm">
                                  {prop}
                                  {!isReadOnly && (
                                    <button
                                      className="ml-1 hover:text-red-500"
                                      onClick={() => {
                                        const newDeps = { ...formData.dependentSchemas };
                                        const newSchema = { ...depSchema, then: { ...depSchema.then, required: thenRequired.filter((_: any, i: number) => i !== idx) } };
                                        newDeps[triggerProp] = newSchema;
                                        setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                      }}
                                    >
                                      <X size={12} />
                                    </button>
                                  )}
                                </span>
                              ))}
                              {!isReadOnly && (
                                <Select
                                  value=""
                                  onValueChange={(val) => {
                                    if (val && !thenRequired.includes(val)) {
                                      const newDeps = { ...formData.dependentSchemas };
                                      const newSchema = { ...depSchema, then: { ...depSchema.then, required: [...thenRequired, val] } };
                                      newDeps[triggerProp] = newSchema;
                                      setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                    }
                                  }}
                                >
                                  <SelectTrigger className="w-[150px] h-8 text-sm">
                                    <SelectValue placeholder="+ Add property" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(editingClassData?.properties || [])
                                      .filter((p: any) => !thenRequired.includes(p.name))
                                      .map((p: any) => (
                                        <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>
                                      ))}
                                  </SelectContent>
                                </Select>
                              )}
                            </div>
                          </div>

                          {/* ELSE - Required Properties (Optional) */}
                          <div className="p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="px-2 py-0.5 bg-amber-500 text-white text-xs font-bold rounded">ELSE</span>
                              <span className="text-sm text-amber-700 dark:text-amber-300">require these properties instead:</span>
                              <span className="text-xs text-amber-600 dark:text-amber-400">(optional)</span>
                            </div>
                            <div className="flex flex-wrap gap-2 items-center">
                              {elseRequired.map((prop: string, idx: number) => (
                                <span key={idx} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 dark:bg-amber-800/50 text-amber-800 dark:text-amber-200 rounded text-sm">
                                  {prop}
                                  {!isReadOnly && (
                                    <button
                                      className="ml-1 hover:text-red-500"
                                      onClick={() => {
                                        const newDeps = { ...formData.dependentSchemas };
                                        const newSchema = { ...depSchema, else: { ...depSchema.else, required: elseRequired.filter((_: any, i: number) => i !== idx) } };
                                        newDeps[triggerProp] = newSchema;
                                        setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                      }}
                                    >
                                      <X size={12} />
                                    </button>
                                  )}
                                </span>
                              ))}
                              {!isReadOnly && (
                                <Select
                                  value=""
                                  onValueChange={(val) => {
                                    if (val && !elseRequired.includes(val)) {
                                      const newDeps = { ...formData.dependentSchemas };
                                      const newSchema = { ...depSchema, else: { ...(depSchema.else || {}), required: [...elseRequired, val] } };
                                      newDeps[triggerProp] = newSchema;
                                      setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                    }
                                  }}
                                >
                                  <SelectTrigger className="w-[150px] h-8 text-sm">
                                    <SelectValue placeholder="+ Add property" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(editingClassData?.properties || [])
                                      .filter((p: any) => !elseRequired.includes(p.name))
                                      .map((p: any) => (
                                        <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>
                                      ))}
                                  </SelectContent>
                                </Select>
                              )}
                            </div>
                          </div>

                          {/* Show raw JSON toggle */}
                          <details className="mt-3">
                            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
                              View/Edit Raw JSON
                            </summary>
                            <Textarea
                              className="mt-2 font-mono text-xs"
                              rows={6}
                              value={JSON.stringify(depSchema, null, 2)}
                              onChange={(e) => {
                                try {
                                  const parsed = JSON.parse(e.target.value);
                                  const newDeps = { ...formData.dependentSchemas };
                                  newDeps[triggerProp] = parsed;
                                  setFormData(prev => ({ ...prev, dependentSchemas: newDeps }));
                                } catch {
                                  // Invalid JSON, don't update
                                }
                              }}
                              disabled={isReadOnly}
                            />
                          </details>
                        </div>
                      );
                    })}
                  </div>
                )}
              </FormSection>
              )}

              {/* SECTION: Dependent Required */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('dependent-required')) && (
              <FormSection
                id="dependent-required"
                icon={<ListChecks size={16} />}
                eyebrow="Dynamic Properties"
                title="Dependent Required"
                description="When a trigger property is present, other properties become required."
                changed={changedSections['dependent-required']}
                action={!isReadOnly ? (
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
                ) : undefined}
              >
                {formData.dependentRequired.length === 0 ? (
                  <FormEmptyState
                    icon={<ListChecks className="h-5 w-5" />}
                    title="No dependent required rules defined"
                    description="Add a rule to make additional properties required when a trigger property is present."
                  />
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
              </FormSection>
              )}

              {/* SECTION: Conditional Schema */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('conditional')) && (
              <FormSection
                id="conditional"
                icon={<GitBranch size={16} />}
                eyebrow="Dynamic Properties"
                title="Conditional Schema"
                description="Apply branching validation rules using if / then / else."
                changed={changedSections.conditional}
              >
                <ConditionalSchemaBuilder
                  rules={formData.conditionalRules}
                  onChange={(rules) => setFormData(prev => ({ ...prev, conditionalRules: rules }))}
                  availableProperties={editingClassData?.properties?.map((p: any) => p.name) || []}
                  disabled={isReadOnly}
                  renderHeader={(addRule) => (
                    <div className="flex items-center justify-end mb-3">
                      <Button type="button" variant="outline" size="sm" onClick={addRule} disabled={isReadOnly}>
                        <Plus size={14} className="mr-1" /> Add Rule
                      </Button>
                    </div>
                  )}
                />
              </FormSection>
              )}

              {/* SECTION: Examples */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('examples')) && (
              <FormSection
                id="examples"
                icon={<Code size={16} />}
                eyebrow="Documentation"
                title="Examples"
                description="Add example instances of this class schema (JSON format)."
                badge={<Badge variant="secondary" className="text-xs">JSON Schema</Badge>}
                changed={changedSections.examples}
              >
                <div className="space-y-2">
                      {formData.examples.map((example, index) => (
                        <div key={index} className="flex gap-2">
                          <Input
                            value={example}
                            onChange={(e) => {
                              const newExamples = [...formData.examples];
                              newExamples[index] = e.target.value;
                              setFormData(prev => ({ ...prev, examples: newExamples }));
                            }}
                            placeholder='{"id": 1, "name": "Example"}'
                            disabled={isReadOnly}
                            className="font-mono text-sm"
                          />
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              const newExamples = formData.examples.filter((_, i) => i !== index);
                              setFormData(prev => ({ ...prev, examples: newExamples }));
                            }}
                            disabled={isReadOnly}
                          >
                            <Trash2 size={16} />
                          </Button>
                        </div>
                      ))}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setFormData(prev => ({ ...prev, examples: [...prev.examples, ''] }))}
                        disabled={isReadOnly}
                      >
                        <Plus size={16} className="mr-1" /> Add Example
                      </Button>
                </div>
              </FormSection>
              )}

              {/* SECTION: XML Representation */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('xml')) && (
              <FormSection
                id="xml"
                icon={<Code size={16} />}
                eyebrow="Documentation"
                title="XML Representation"
                description="Configure how this class is serialized to XML."
                badge={<Badge variant="secondary" className="text-xs bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300">OpenAPI 3.1</Badge>}
                accent="orange"
                changed={changedSections.xml}
              >
                <FormGrid cols={3} gap="md">
                  <FormFieldGroup label="XML Name">
                    <Input
                      value={formData.xmlName}
                      onChange={(e) => setFormData(prev => ({ ...prev, xmlName: e.target.value }))}
                      placeholder="e.g., CustomName"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                  <FormFieldGroup label="Namespace">
                    <Input
                      value={formData.xmlNamespace}
                      onChange={(e) => setFormData(prev => ({ ...prev, xmlNamespace: e.target.value }))}
                      placeholder="http://example.com/ns"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                  <FormFieldGroup label="Prefix">
                    <Input
                      value={formData.xmlPrefix}
                      onChange={(e) => setFormData(prev => ({ ...prev, xmlPrefix: e.target.value }))}
                      placeholder="e.g., ns1"
                      disabled={isReadOnly}
                    />
                  </FormFieldGroup>
                </FormGrid>
              </FormSection>
              )}

              {/* SECTION: Schema Metadata */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('schema-metadata')) && (
              <FormSection
                id="schema-metadata"
                icon={<FileText size={16} />}
                eyebrow="Documentation"
                title="Schema Metadata"
                description="Advanced schema identification and authoring metadata."
                badge={<Badge variant="secondary" className="text-xs">JSON Schema 2020-12</Badge>}
                changed={changedSections['schema-metadata']}
              >
                <FormFieldGroup label="$id" helper="Unique identifier URI for this schema">
                  <Input
                    value={formData.schemaId}
                    onChange={(e) => setFormData(prev => ({ ...prev, schemaId: e.target.value }))}
                    placeholder="https://example.com/schemas/myschema.json"
                    disabled={isReadOnly}
                  />
                </FormFieldGroup>
                <FormFieldGroup label="$anchor" helper="Define a reusable anchor within the schema">
                  <Input
                    value={formData.schemaAnchor}
                    onChange={(e) => setFormData(prev => ({ ...prev, schemaAnchor: e.target.value }))}
                    placeholder="e.g., myAnchor"
                    disabled={isReadOnly}
                  />
                </FormFieldGroup>
                <FormFieldGroup label="$comment" helper="Comments for schema authors (not shown to API consumers)">
                  <Textarea
                    value={formData.schemaComment}
                    onChange={(e) => setFormData(prev => ({ ...prev, schemaComment: e.target.value }))}
                    placeholder="Internal notes for schema authors..."
                    disabled={isReadOnly}
                    rows={2}
                  />
                </FormFieldGroup>
              </FormSection>
              )}

              {/* SECTION: External Documentation */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('external-docs')) && (
              <FormSection
                id="external-docs"
                icon={<ExternalLink size={16} />}
                eyebrow="Documentation"
                title="External Documentation"
                description="Link out to human-readable docs, tutorials, or spec references."
                changed={changedSections['external-docs']}
              >
                <FormFieldGroup label="Documentation URL">
                  <Input
                    type="url"
                    value={formData.externalDocsUrl}
                    onChange={(e) => setFormData(prev => ({ ...prev, externalDocsUrl: e.target.value }))}
                    placeholder="https://docs.example.com/..."
                    disabled={isReadOnly}
                  />
                </FormFieldGroup>
                <FormFieldGroup label="Description">
                  <Textarea
                    value={formData.externalDocsDescription}
                    onChange={(e) => setFormData(prev => ({ ...prev, externalDocsDescription: e.target.value }))}
                    placeholder="Brief description of external docs"
                    disabled={isReadOnly}
                    rows={2}
                  />
                </FormFieldGroup>
              </FormSection>
              )}

              {/* SECTION: Custom Extensions */}
              {(viewMode === 'advanced' || CLASS_WIZARD_STEPS[currentStepIndex].sections.includes('extensions')) && (
              <FormSection
                id="extensions"
                icon={<Code size={16} />}
                eyebrow="Documentation"
                title="Custom Extensions"
                description="Add x- prefixed vendor extensions for tooling and codegen."
                changed={changedSections.extensions}
              >
                <ExtensionsEditor
                  value={formData.extensions}
                  onChange={(extensions) => setFormData(prev => ({ ...prev, extensions }))}
                  disabled={isReadOnly}
                />
              </FormSection>
              )}

              {/* Guided-mode wizard controls, rendered inside the scroll pane */}
              {viewMode === 'guided' && (
                <div className="sticky bottom-0 z-10 border-t border-slate-200 bg-white/95 px-8 py-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
                  <FormWizardControls
                    currentIndex={currentStepIndex}
                    stepCount={CLASS_WIZARD_STEPS.length}
                    onBack={() => setCurrentStepIndex((i) => Math.max(0, i - 1))}
                    onNext={() => setCurrentStepIndex((i) => Math.min(CLASS_WIZARD_STEPS.length - 1, i + 1))}
                    onCancel={onClose}
                    onFinish={handleSave}
                    finishBusy={saving}
                    finishDisabled={isReadOnly || !formData.name.trim()}
                    finishLabel={editingClassData ? 'Save Changes' : 'Create Class'}
                  />
                </div>
              )}
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

        {/* Hide the dialog footer on the Edit tab in guided mode — wizard
            controls live inside the scroll pane so the Back/Next buttons are
            always adjacent to the current step. Other tabs keep the familiar
            Cancel/Close footer. */}
        {!(activeTab === 'edit' && viewMode === 'guided') && (
          <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            {!isReadOnly && activeTab === 'edit' && (
              <Button onClick={handleSave} disabled={saving || !formData.name.trim()}>
                {saving ? 'Saving...' : (editingClassData ? 'Save Changes' : 'Create Class')}
              </Button>
            )}
            {activeTab !== 'edit' && (
              <Button onClick={onClose}>Close</Button>
            )}
          </DialogFooter>
        )}
        </>
        )}
      </DialogContent>
    </Dialog>

    <AiClassCreatePreviewDialog
      open={aiCreatePreviewContent !== null}
      assistantMarkdown={aiCreatePreviewContent}
      onOpenChange={(next) => !next && setAiCreatePreviewContent(null)}
      onConfirmCreate={() => {
        const c = aiCreatePreviewContent;
        if (!c) return;
        setAiCreatePreviewContent(null);
        void handleAiCreateClass(c);
      }}
    />
    </>
  );
};

export default ClassEditDialog;

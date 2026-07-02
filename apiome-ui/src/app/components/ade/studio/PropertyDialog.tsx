'use client';

import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
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
import { Textarea } from '../../ui/Textarea';
import { Alert } from '../../ui/Alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../ui/Tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import { PropertyFormFields, PropertyFormData } from './PropertyFormFields';
import { PrimitiveSelector } from './PrimitiveSelector';
import {
  FileText,
  Settings,
  Code,
  AlertTriangle,
  ExternalLink,
  Sparkles,
  ListChecks,
  BookOpenText,
  Wand2,
  Bot,
} from 'lucide-react';
import type { ChatStudioContext } from '@/app/ade/studio/components/chatbot/chat-context';
import { AiPropertyTypeSuggestionsDialog } from './AiPropertyTypeSuggestionsDialog';
import type { AiPropertySuggestion } from '@lib/ai-property-suggestions';
import { draftPropertySchemaFromDialogForm } from '@lib/ai-property-description';
import { PropertyDescriptionAiButton } from './PropertyDescriptionAiButton';
import { PropertyExampleAiButton } from './PropertyExampleAiButton';
import type { PropertyItem as LibraryPropertyItem } from './StudioSideNav';
import {
  FormSection,
  FormFieldGroup,
  FormGrid,
  FormToggleCard,
  FormViewModeToggle,
  FormSectionNav,
  FormWizardStepper,
  FormWizardControls,
  useFormScrollSpy,
  scrollToSection,
  useFormViewMode,
  type FormSectionNavItem,
  type FormWizardStep,
} from './form';

// Dynamically import Monaco Editor with SSR disabled
const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: '#666' }}>Loading editor...</div>
    </div>
  ),
});

export interface PropertyItem {
  id: string;
  name: string;
  type?: string;
  $ref?: string;
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
  /** OpenAPI extension; prefer editing via the Owner field in the form */
  'x-owner'?: string;
  examples?: any[];
  additionalProperties?: boolean | any;
  minProperties?: number;
  maxProperties?: number;
  patternProperties?: Record<string, any>;
  dependentSchemas?: Record<string, any>;
  // Tuple mode (OpenAPI 3.1)
  tupleMode?: boolean;
  prefixItems?: any[]; // OpenAPI 3.1: Array of schemas for specific positions
  items?: any; // Schema for items beyond prefix positions
}

export interface PropertyDialogAiContext {
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  existingClasses: string[];
  existingProperties: LibraryPropertyItem[];
  studioContext: ChatStudioContext;
  contextClassName?: string | null;
}

interface PropertyDialogProps {
  open: boolean;
  onClose: () => void;
  mode: 'add' | 'edit';
  property: PropertyItem | null;
  onSubmit: (propertyData: {
    name: string;
    description: string | null;
    data: any;
  }) => Promise<void>;
  // Available class names for schema references
  availableClasses?: string[];
  /** When set, Add Property shows AI type suggestions (Ollama). */
  propertyAiContext?: PropertyDialogAiContext;
  onApplyAiTypeSchema?: (payload: {
    name: string;
    description: string | null;
    schema: Record<string, unknown>;
  }) => void;
  /** Opens the AI property suggestions dialog (same as sidebar / chat; #276). */
  onOpenAiPropertySuggestions?: () => void;
}

// ────────────────────────────────────────────────────────────────────────────
// Section renderers. Kept as module-level components so they can be reused by
// both the Guided wizard and the Advanced scrolling pane without re-creating
// React subtrees on every render of the parent dialog.
// ────────────────────────────────────────────────────────────────────────────

interface BasicsSectionProps {
  mode: 'add' | 'edit';
  propertyName: string;
  setPropertyName: (next: string) => void;
  propertyType: string;
  setPropertyType: (next: string) => void;
  propertyIsArray: boolean;
  setPropertyIsArray: (next: boolean) => void;
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  primitiveAvailable: boolean;
  setPrimitiveDialogOpen: (next: boolean) => void;
  addModeAiTypeSuggest?: { onOpen: () => void } | null;
  onOpenAiPropertySuggestions?: () => void;
  descriptionAiSlot?: React.ReactNode;
  changed?: boolean;
  eyebrow?: string;
}

const BasicsSection: React.FC<BasicsSectionProps> = ({
  mode,
  propertyName,
  setPropertyName,
  propertyType,
  setPropertyType,
  propertyIsArray,
  setPropertyIsArray,
  formData,
  setFormData,
  primitiveAvailable,
  setPrimitiveDialogOpen,
  addModeAiTypeSuggest,
  onOpenAiPropertySuggestions,
  descriptionAiSlot,
  changed,
  eyebrow = 'Basics',
}) => (
  <FormSection
    id="basics"
    icon={<FileText className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Basics"
    description="Identify and describe this property. Name and type are locked once the property exists."
    changed={changed}
  >
    <FormFieldGroup
      label="Property Name"
      required
      htmlFor="propertyName"
      helper="Only letters, numbers, and underscores. camelCase recommended."
    >
      <Input
        id="propertyName"
        autoFocus
        value={propertyName}
        onChange={(e) => {
          const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
          setPropertyName(filteredValue);
        }}
        placeholder="e.g., userName"
        disabled={mode === 'edit'}
      />
    </FormFieldGroup>

    <FormGrid cols={2} gap="md">
      <FormToggleCard
        id="isArray"
        label="Array"
        description="An array of the selected base type."
        checked={propertyIsArray}
        onCheckedChange={setPropertyIsArray}
        disabled={mode === 'edit'}
      />
      <FormFieldGroup
        label="Type"
        required
        htmlFor="propertyType"
        helper={mode === 'edit' ? 'Type cannot be changed after creation.' : undefined}
      >
        <Select value={propertyType} onValueChange={setPropertyType} disabled={mode === 'edit'}>
          <SelectTrigger id="propertyType" className="w-full">
            <SelectValue placeholder="Select type..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="string">string</SelectItem>
            <SelectItem value="number">number</SelectItem>
            <SelectItem value="integer">integer</SelectItem>
            <SelectItem value="boolean">boolean</SelectItem>
            <SelectItem value="object">object</SelectItem>
            <SelectItem value="null">null</SelectItem>
          </SelectContent>
        </Select>
      </FormFieldGroup>
    </FormGrid>

    {onOpenAiPropertySuggestions && (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-900/50 dark:bg-emerald-950/30">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300">
              <Bot className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">AI property suggestions</h4>
              <p className="mt-0.5 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Brainstorm reusable property names and schemas from a short prompt. Uses the same flow as the properties sidebar. Requires Ollama when connected.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="property-dialog-analyze-ai-properties"
            onClick={onOpenAiPropertySuggestions}
            className="shrink-0 border-emerald-300 text-emerald-800 hover:bg-emerald-100 dark:border-emerald-700 dark:text-emerald-200 dark:hover:bg-emerald-950/50"
          >
            Analyze
          </Button>
        </div>
      </div>
    )}

    {mode === 'add' && addModeAiTypeSuggest && (
      <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-4 dark:border-violet-900/50 dark:bg-violet-950/30">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-100 text-violet-600 dark:bg-violet-900/40 dark:text-violet-300">
              <Wand2 className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Suggest types with AI</h4>
              <p className="mt-0.5 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Get several JSON Schema options for this property name (formats, refs, arrays). Requires Ollama.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="property-dialog-ai-type-suggest"
            disabled={!propertyName.trim()}
            onClick={addModeAiTypeSuggest.onOpen}
            className="shrink-0 border-violet-300 text-violet-800 hover:bg-violet-100 dark:border-violet-700 dark:text-violet-200 dark:hover:bg-violet-950/50"
          >
            Suggest types…
          </Button>
        </div>
      </div>
    )}

    <FormFieldGroup
      label="Title"
      htmlFor="title"
      helper="A human-readable title for documentation."
    >
      <Input
        id="title"
        value={formData.title || ''}
        onChange={(e) => setFormData((prev) => ({ ...prev, title: e.target.value }))}
        placeholder="Human-readable title"
      />
    </FormFieldGroup>

    <FormFieldGroup label="Description" htmlFor="description">
      <Textarea
        id="description"
        value={formData.description || ''}
        onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))}
        placeholder="Brief description of this property"
        rows={3}
      />
      {descriptionAiSlot ? <div className="mt-2">{descriptionAiSlot}</div> : null}
    </FormFieldGroup>

    {primitiveAvailable && (
      <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-900/50 dark:bg-indigo-950/30">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100 text-indigo-500 dark:bg-indigo-900/40 dark:text-indigo-300">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Bind to a Type
              </h4>
              <p className="mt-0.5 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Bind this property to a Standard, Core, Tenant, or Custom registry type. The type&apos;s constraints are applied and a stable <code>$ref</code> is recorded.
              </p>
            </div>
          </div>
          <PrimitiveSelector
            formData={formData}
            onChange={(field, value) => setFormData((prev) => ({ ...prev, [field]: value }))}
            propertyType={propertyType}
            size="small"
            onOpenChange={setPrimitiveDialogOpen}
          />
        </div>
      </div>
    )}
  </FormSection>
);

interface FlagsSectionProps {
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  changed?: boolean;
  eyebrow?: string;
}

const FlagsSection: React.FC<FlagsSectionProps> = ({ formData, setFormData, changed, eyebrow = 'Flags & Ownership' }) => (
  <FormSection
    id="flags"
    icon={<Settings className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Flags & Ownership"
    description="Declare runtime behavior and ownership metadata."
    changed={changed}
  >
    <FormGrid cols={4} gap="md">
      <FormToggleCard
        id="required"
        label="Required"
        description="Must be provided"
        accent="emerald"
        checked={formData.required || false}
        onCheckedChange={(v) => setFormData((prev) => ({ ...prev, required: v }))}
      />
      <FormToggleCard
        id="nullable"
        label="Nullable"
        description="Can be null"
        accent="amber"
        checked={formData.nullable || false}
        onCheckedChange={(v) => setFormData((prev) => ({ ...prev, nullable: v }))}
      />
      <FormToggleCard
        id="readOnly"
        label="Read Only"
        description="Only in responses"
        accent="blue"
        checked={formData.readOnly || false}
        onCheckedChange={(v) => setFormData((prev) => ({ ...prev, readOnly: v }))}
      />
      <FormToggleCard
        id="writeOnly"
        label="Write Only"
        description="Only in requests"
        accent="purple"
        checked={formData.writeOnly || false}
        onCheckedChange={(v) => setFormData((prev) => ({ ...prev, writeOnly: v }))}
      />
    </FormGrid>

    <FormToggleCard
      id="deprecated"
      label="Deprecated"
      icon={<AlertTriangle className="h-3.5 w-3.5" />}
      accent="amber"
      description="Signal consumers to migrate off this property."
      checked={formData.deprecated || false}
      onCheckedChange={(v) => setFormData((prev) => ({ ...prev, deprecated: v }))}
      stack={!!formData.deprecated}
      trailing={
        formData.deprecated ? (
          <Input
            value={formData.deprecationMessage || ''}
            onChange={(e) => setFormData((prev) => ({ ...prev, deprecationMessage: e.target.value }))}
            placeholder="Deprecation message (e.g., Use newProperty instead)"
            className="text-sm"
          />
        ) : undefined
      }
    />

    <FormFieldGroup
      label="Owner"
      htmlFor="owner"
      helper={
        <>
          Stored as <code className="font-mono text-[11px]">x-owner</code> on this property schema
          (team or person responsible).
        </>
      }
    >
      <Input
        id="owner"
        value={formData.owner || ''}
        onChange={(e) => setFormData((prev) => ({ ...prev, owner: e.target.value }))}
        placeholder="e.g. platform-team or @handle"
      />
    </FormFieldGroup>
  </FormSection>
);

interface DefaultsSectionProps {
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  changed?: boolean;
  eyebrow?: string;
}

const DefaultsSection: React.FC<DefaultsSectionProps> = ({ formData, setFormData, changed, eyebrow = 'Defaults & Constants' }) => (
  <FormSection
    id="defaults"
    icon={<Code className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Defaults & Constants"
    description="Optional default and constant values for this property. Constant is mutually exclusive with enum."
    changed={changed}
  >
    <FormGrid cols={2} gap="md">
      <FormFieldGroup
        label="Default Value"
        htmlFor="defaultValue"
        helper="Used when no value is provided."
      >
        <Input
          id="defaultValue"
          value={formData.default || ''}
          onChange={(e) => setFormData((prev) => ({ ...prev, default: e.target.value }))}
          placeholder='JSON value (e.g., "hello", 123, true)'
          className="font-mono text-sm"
        />
      </FormFieldGroup>
      <FormFieldGroup
        label="Constant Value"
        htmlFor="constValue"
        helper="Must always equal this value."
      >
        <Input
          id="constValue"
          value={formData.const || ''}
          onChange={(e) => setFormData((prev) => ({ ...prev, const: e.target.value }))}
          placeholder="Fixed value (mutually exclusive with enum)"
          className="font-mono text-sm"
        />
      </FormFieldGroup>
    </FormGrid>
  </FormSection>
);

interface ConstraintsSectionProps {
  propertyType: string;
  propertyIsArray: boolean;
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  availableClasses: string[];
  examplesAiSlot?: React.ReactNode;
  eyebrow?: string;
}

const ConstraintsSection: React.FC<ConstraintsSectionProps> = ({
  propertyType,
  propertyIsArray,
  formData,
  setFormData,
  availableClasses,
  examplesAiSlot,
  eyebrow = 'Advanced Constraints',
}) => (
  <FormSection
    id="constraints"
    icon={<ListChecks className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Advanced Constraints"
    description="Type-specific validation rules, values, and advanced schema options."
    className="px-0 py-0"
    headerClassName="mx-8 mt-7 mb-0"
    bodyClassName="space-y-0"
  >
    <PropertyFormFields
      baseType={propertyType}
      isArray={propertyIsArray}
      data={formData}
      onChange={(field, value) => {
        setFormData((prev) => ({ ...prev, [field]: value }));
      }}
      showMetadata={false}
      showTitle={false}
      showPrimitiveSelector={false}
      showHint={false}
      size="small"
      availableClasses={availableClasses}
      examplesAiSlot={examplesAiSlot}
    />
  </FormSection>
);

interface DocsSectionProps {
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  changed?: boolean;
  eyebrow?: string;
}

const DocsSection: React.FC<DocsSectionProps> = ({ formData, setFormData, changed, eyebrow = 'Documentation' }) => (
  <FormSection
    id="docs"
    icon={<BookOpenText className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Documentation"
    description="External documentation links surfaced in generated specs."
    changed={changed}
  >
    <FormGrid cols={1} gap="md">
      <FormFieldGroup label="URL" htmlFor="externalDocsUrl">
        <Input
          id="externalDocsUrl"
          type="url"
          value={formData.externalDocsUrl || ''}
          onChange={(e) => setFormData((prev) => ({ ...prev, externalDocsUrl: e.target.value }))}
          placeholder="https://docs.example.com/property"
        />
      </FormFieldGroup>
      <FormFieldGroup
        label="Description"
        htmlFor="externalDocsDescription"
        helper="Optional label describing what the link points to."
      >
        <Input
          id="externalDocsDescription"
          value={formData.externalDocsDescription || ''}
          onChange={(e) =>
            setFormData((prev) => ({ ...prev, externalDocsDescription: e.target.value }))
          }
          placeholder="Link to property documentation"
        />
      </FormFieldGroup>
    </FormGrid>

    <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
      <ExternalLink className="h-3.5 w-3.5" />
      Shown inline with generated API documentation.
    </div>
  </FormSection>
);

export const PropertyDialog: React.FC<PropertyDialogProps> = ({
  open,
  onClose,
  mode,
  property,
  onSubmit,
  availableClasses = [],
  propertyAiContext,
  onApplyAiTypeSchema,
  onOpenAiPropertySuggestions,
}) => {
  const isDark = useDarkMode();

  const [tabMode, setTabMode] = useState<'form' | 'json'>('form');
  const [viewMode, setViewMode] = useFormViewMode('property-dialog-view-mode');
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [propertyName, setPropertyName] = useState('');
  const [propertyType, setPropertyType] = useState('string');
  const [propertyIsArray, setPropertyIsArray] = useState(false);
  const [propertyError, setPropertyError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [primitiveDialogOpen, setPrimitiveDialogOpen] = useState(false);
  const [aiTypeSuggestOpen, setAiTypeSuggestOpen] = useState(false);

  // Use shared form data structure
  const [formData, setFormData] = useState<PropertyFormData>({});

  const advancedScrollRef = useRef<HTMLDivElement>(null);

  // Reset nested dialog state when the parent PropertyDialog closes.
  useEffect(() => {
    if (!open) {
      setAiTypeSuggestOpen(false);
    }
  }, [open]);

  // Load property data when dialog opens in edit mode, or when adding with an AI/template seed (#609).
  useEffect(() => {
    if (open && property && (mode === 'edit' || mode === 'add')) {
      setPropertyName(property.name);

      // Check if property type is an array (for nullable detection)
      // Type can be 'array', ['array', 'null'], 'string', ['string', 'null'], etc.
      const typeValue = property.type;
      let isNullable = false;
      let actualType = typeValue;

      if (Array.isArray(typeValue)) {
        // Type is an array like ['string', 'null'] or ['array', 'null']
        isNullable = typeValue.includes('null');
        actualType = typeValue.find((t: string) => t !== 'null') || 'string';
      }

      // Check if property is an array type
      const isArray = actualType === 'array';
      setPropertyIsArray(isArray);

      // Check if tuple mode is active (prefixItems exists)
      const hasTupleMode = (property as any).prefixItems && Array.isArray((property as any).prefixItems);

      // Determine the actual type
      // Note: Actual $ref values (class references) are managed via canvas connections
      if (isArray && hasTupleMode) {
        // Tuple mode: set a default type (constraints are per-position in prefixItems)
        setPropertyType('string');
      } else if (isArray && (property as any).items && typeof (property as any).items === 'object') {
        const items = (property as any).items;
        if (items.$ref) {
          // Has a $ref - this is a reference type
          setPropertyType('$ref');
        } else {
          setPropertyType(items.type || 'string');
        }
      } else if (property.$ref) {
        // Has a direct $ref - this is a reference type
        setPropertyType('$ref');
      } else {
        // Handle nullable type arrays - extract base type
        let baseType = actualType;
        if (!baseType && property.type) {
          baseType = property.type;
        }
        setPropertyType(baseType || 'string');
      }

      // Determine minimum type (inclusive vs exclusive)
      // For array types with tuple mode, skip item constraints (defined per-position)
      // For regular arrays, check inside items; for non-array, check at root level
      let minimumValue = '';
      let minimumType: 'inclusive' | 'exclusive' | undefined;
      const minMaxSource = (isArray && !hasTupleMode && (property as any).items && typeof (property as any).items === 'object')
        ? (property as any).items
        : property;

      if (minMaxSource.exclusiveMinimum !== undefined) {
        minimumValue = minMaxSource.exclusiveMinimum.toString();
        minimumType = 'exclusive';
      } else if (minMaxSource.minimum !== undefined) {
        minimumValue = minMaxSource.minimum.toString();
        minimumType = 'inclusive';
      }

      // Determine maximum type (inclusive vs exclusive)
      let maximumValue = '';
      let maximumType: 'inclusive' | 'exclusive' | undefined;
      if (minMaxSource.exclusiveMaximum !== undefined) {
        maximumValue = minMaxSource.exclusiveMaximum.toString();
        maximumType = 'exclusive';
      } else if (minMaxSource.maximum !== undefined) {
        maximumValue = minMaxSource.maximum.toString();
        maximumType = 'inclusive';
      }

      // Determine additionalProperties value
      let additionalPropsValue: 'default' | 'true' | 'false' | 'type' | 'schema' = 'default';
      let additionalPropsType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
      let additionalPropsSchema = '';
      if (minMaxSource.hasOwnProperty('additionalProperties')) {
        if (minMaxSource.additionalProperties === true) {
          additionalPropsValue = 'true';
        } else if (minMaxSource.additionalProperties === false) {
          additionalPropsValue = 'false';
        } else if (typeof minMaxSource.additionalProperties === 'object' && minMaxSource.additionalProperties.$ref) {
          additionalPropsValue = 'schema';
          // Extract just the class name from the $ref path (e.g., "#/components/schemas/ClassName" -> "ClassName")
          const refPath = minMaxSource.additionalProperties.$ref;
          additionalPropsSchema = refPath.split('/').pop() || refPath;
        } else if (typeof minMaxSource.additionalProperties === 'object' && minMaxSource.additionalProperties.type) {
          additionalPropsValue = 'type';
          additionalPropsType = minMaxSource.additionalProperties.type;
        } else if (typeof minMaxSource.additionalProperties === 'object') {
          // Other object schema - treat as schema
          additionalPropsValue = 'schema';
          additionalPropsSchema = JSON.stringify(minMaxSource.additionalProperties);
        }
      }

      // Extract extensions (x- prefixed properties); x-owner uses dedicated Owner field
      const extensions: Record<string, any> = {};
      Object.keys(property as any).forEach(key => {
        if (key.startsWith('x-') && key !== 'x-owner') {
          extensions[key] = (property as any)[key];
        }
      });

      setFormData({
        title: property.title || '',
        description: property.description || '',
        // For array types, these come from items; for non-array, from root
        format: minMaxSource.format || '',
        pattern: minMaxSource.pattern || '',
        minLength: minMaxSource.minLength?.toString() || '',
        maxLength: minMaxSource.maxLength?.toString() || '',
        minimum: minimumValue,
        maximum: maximumValue,
        minimumType: minimumType,
        maximumType: maximumType,
        multipleOf: minMaxSource.multipleOf?.toString() || '',
        // Array-specific constraints come from root
        minItems: property.minItems?.toString() || '',
        maxItems: property.maxItems?.toString() || '',
        uniqueItems: property.uniqueItems || false,
        contains: (property as any).contains ? JSON.stringify((property as any).contains, null, 2) : '',
        minContains: (property as any).minContains?.toString() || '',
        maxContains: (property as any).maxContains?.toString() || '',
        // Tuple mode (OpenAPI 3.1)
        tupleMode: hasTupleMode,
        prefixItems: (property as any).prefixItems || [],
        itemsSchema: hasTupleMode && (property as any).items !== undefined ?
          (typeof (property as any).items === 'object' ?
            JSON.stringify((property as any).items, null, 2) :
            String((property as any).items)) : '',
        // unevaluatedItems (OpenAPI 3.1/JSON Schema 2020-12)
        unevaluatedItems: (property as any).unevaluatedItems === true ? 'allow' :
          (property as any).unevaluatedItems === false ? 'disallow' :
            (typeof (property as any).unevaluatedItems === 'object' ? 'schema' : 'default'),
        unevaluatedItemsSchema: typeof (property as any).unevaluatedItems === 'object' ?
          JSON.stringify((property as any).unevaluatedItems, null, 2) : '',
        // Enum and default come from items for array types
        enum: minMaxSource.enum || [],
        const: minMaxSource.const !== undefined ? (typeof minMaxSource.const === 'string' ? minMaxSource.const : JSON.stringify(minMaxSource.const)) : '',
        default: minMaxSource.default?.toString() || '',
        required: property.required || false,
        // Nullable (OpenAPI 3.1 - type array with 'null')
        nullable: isNullable,
        // Metadata fields
        readOnly: property.readOnly || false,
        writeOnly: property.writeOnly || false,
        deprecated: property.deprecated || false,
        deprecationMessage: property.deprecationMessage || '',
        owner: (property as any)['x-owner'] != null && String((property as any)['x-owner']).trim() !== ''
          ? String((property as any)['x-owner'])
          : '',
        examples: property.examples ? property.examples.map((ex: any) => JSON.stringify(ex)) : [],
        // Object constraints
        additionalProperties: additionalPropsValue,
        additionalPropertiesType: additionalPropsType,
        additionalPropertiesSchema: additionalPropsSchema,
        minProperties: minMaxSource.minProperties?.toString() || '',
        maxProperties: minMaxSource.maxProperties?.toString() || '',
        patternProperties: minMaxSource.patternProperties || undefined,
        // Property Name Constraints (OpenAPI 3.1)
        propertyNamesPattern: minMaxSource.propertyNames?.pattern || '',
        propertyNamesMinLength: minMaxSource.propertyNames?.minLength?.toString() || '',
        propertyNamesMaxLength: minMaxSource.propertyNames?.maxLength?.toString() || '',
        propertyNamesFormat: minMaxSource.propertyNames?.format || '',
        propertyNamesDescription: minMaxSource.propertyNames?.description || '',
        // Dependent Schemas (JSON Schema 2019-09+)
        dependentSchemas: minMaxSource.dependentSchemas || undefined,
        // NOT composition (OpenAPI 3.1)
        not: minMaxSource.not ? JSON.stringify(minMaxSource.not, null, 2) : '',
        // Extensions (x- prefixed properties)
        extensions: extensions,
        // External Documentation
        externalDocsUrl: (property as any).externalDocs?.url || '',
        externalDocsDescription: (property as any).externalDocs?.description || '',
        // XML Object (OpenAPI 3.1)
        xmlName: (property as any).xml?.name || '',
        xmlNamespace: (property as any).xml?.namespace || '',
        xmlPrefix: (property as any).xml?.prefix || '',
        xmlAttribute: (property as any).xml?.attribute || false,
        xmlWrapped: (property as any).xml?.wrapped || false,
        // Content Media Type (for binary/byte strings)
        contentMediaType: (property as any).contentMediaType || '',
        contentEncoding: (property as any).contentEncoding || '',
        contentSchema: (property as any).contentSchema ? JSON.stringify((property as any).contentSchema, null, 2) : '',
        // Schema Metadata
        $comment: (property as any).$comment || '',
      });
      setPropertyError('');
    } else if (open && mode === 'add') {
      // Reset all fields for add mode
      setTabMode('form');
      setCurrentStepIndex(0);
      setPropertyName('');
      setPropertyType('string');
      setPropertyIsArray(false);
      setFormData({});
      setPropertyError('');
    }
  }, [open, property, mode]);

  // Helper function to build JSON Schema definition from current form state
  const buildPropertyJsonSchema = () => {
    const schema: any = {};

    if (formData.title) schema.title = formData.title;
    if (formData.description) schema.description = formData.description;
    if (formData.readOnly) schema.readOnly = formData.readOnly;
    if (formData.writeOnly) schema.writeOnly = formData.writeOnly;
    if (formData.deprecated) {
      schema.deprecated = formData.deprecated;
      if (formData.deprecationMessage && formData.deprecationMessage.trim()) {
        schema.deprecationMessage = formData.deprecationMessage.trim();
      }
    }
    if (formData.examples && formData.examples.length > 0) {
      try {
        schema.examples = formData.examples.map(ex => JSON.parse(ex));
      } catch (e) {
        // If parsing fails, use as-is
        schema.examples = formData.examples;
      }
    }
    if (formData.required) schema.required = formData.required;

    if (propertyIsArray) {
      // Handle nullable for arrays (OpenAPI 3.1 style)
      schema.type = formData.nullable ? ['array', 'null'] : 'array';
      if (formData.minItems) schema.minItems = parseInt(formData.minItems);
      if (formData.maxItems) schema.maxItems = parseInt(formData.maxItems);
      if (formData.uniqueItems) schema.uniqueItems = true;

      // Handle contains schema (OpenAPI 3.1)
      if (formData.contains && formData.contains.trim()) {
        try {
          schema.contains = JSON.parse(formData.contains);
        } catch (e) {
          schema.contains = { type: formData.contains };
        }

        // Add minContains and maxContains if set
        if (formData.minContains) {
          const minContainsValue = parseInt(formData.minContains);
          if (!isNaN(minContainsValue) && minContainsValue >= 1) {
            schema.minContains = minContainsValue;
          }
        }
        if (formData.maxContains) {
          const maxContainsValue = parseInt(formData.maxContains);
          if (!isNaN(maxContainsValue) && maxContainsValue >= 1) {
            schema.maxContains = maxContainsValue;
          }
        }
      }

      // Handle Tuple Mode (OpenAPI 3.1 prefixItems)
      if (formData.tupleMode && formData.prefixItems && formData.prefixItems.length > 0) {
        schema.prefixItems = formData.prefixItems;

        // Handle items schema for positions beyond prefix
        if (formData.itemsSchema && formData.itemsSchema.trim()) {
          try {
            schema.items = JSON.parse(formData.itemsSchema);
          } catch (e) {
            schema.items = { type: formData.itemsSchema };
          }
        } else {
          schema.items = true;
        }
      } else {
        // Not in tuple mode - use regular items schema
        const itemsSchema: any = {
          type: propertyType
        };
        if (formData.format) itemsSchema.format = formData.format;
        if (formData.pattern) itemsSchema.pattern = formData.pattern;
        if (formData.minLength) itemsSchema.minLength = parseInt(formData.minLength);
        if (formData.maxLength) itemsSchema.maxLength = parseInt(formData.maxLength);
        if (formData.minimum && formData.minimum.trim()) {
          const minValue = parseFloat(formData.minimum);
          if (!isNaN(minValue)) {
            if (formData.minimumType === 'exclusive') {
              itemsSchema.exclusiveMinimum = minValue;
            } else {
              itemsSchema.minimum = minValue;
            }
          }
        }
        if (formData.maximum && formData.maximum.trim()) {
          const maxValue = parseFloat(formData.maximum);
          if (!isNaN(maxValue)) {
            if (formData.maximumType === 'exclusive') {
              itemsSchema.exclusiveMaximum = maxValue;
            } else {
              itemsSchema.maximum = maxValue;
            }
          }
        }
        if (formData.multipleOf && formData.multipleOf.trim()) {
          const multipleOfValue = parseFloat(formData.multipleOf);
          if (!isNaN(multipleOfValue) && multipleOfValue > 0) {
            itemsSchema.multipleOf = multipleOfValue;
          }
        }
        // Handle const (mutually exclusive with enum)
        if (formData.const && formData.const.trim()) {
          try {
            itemsSchema.const = JSON.parse(formData.const);
          } catch (e) {
            // If not valid JSON, use as string
            itemsSchema.const = formData.const;
          }
        } else if (formData.enum && formData.enum.length > 0) {
          itemsSchema.enum = formData.enum;
        }
        if (formData.default) itemsSchema.default = formData.default;

        // Handle additionalProperties for array items that are objects
        if (propertyType === 'object') {
          if (formData.additionalProperties === 'true') {
            itemsSchema.additionalProperties = true;
          } else if (formData.additionalProperties === 'false') {
            itemsSchema.additionalProperties = false;
          } else if (formData.additionalProperties === 'type' && formData.additionalPropertiesType) {
            itemsSchema.additionalProperties = { type: formData.additionalPropertiesType };
          } else if (formData.additionalProperties === 'schema' && formData.additionalPropertiesSchema) {
            const schemaValue = formData.additionalPropertiesSchema.trim();
            if (schemaValue.startsWith('{')) {
              try {
                itemsSchema.additionalProperties = JSON.parse(schemaValue);
              } catch {
                itemsSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
              }
            } else if (schemaValue.startsWith('#/') || schemaValue.startsWith('$ref')) {
              itemsSchema.additionalProperties = { $ref: schemaValue };
            } else {
              itemsSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
            }
          }

          // Handle minProperties and maxProperties for object items
          if (formData.minProperties) itemsSchema.minProperties = parseInt(formData.minProperties);
          if (formData.maxProperties) itemsSchema.maxProperties = parseInt(formData.maxProperties);

          // Handle propertyNames constraints for object items (OpenAPI 3.1)
          const hasPropertyNamesConstraints = formData.propertyNamesPattern || formData.propertyNamesMinLength || formData.propertyNamesMaxLength || formData.propertyNamesFormat || formData.propertyNamesDescription;
          if (hasPropertyNamesConstraints) {
            itemsSchema.propertyNames = { type: 'string' };
            if (formData.propertyNamesPattern) itemsSchema.propertyNames.pattern = formData.propertyNamesPattern;
            if (formData.propertyNamesMinLength) itemsSchema.propertyNames.minLength = parseInt(formData.propertyNamesMinLength);
            if (formData.propertyNamesMaxLength) itemsSchema.propertyNames.maxLength = parseInt(formData.propertyNamesMaxLength);
            if (formData.propertyNamesFormat) itemsSchema.propertyNames.format = formData.propertyNamesFormat;
            if (formData.propertyNamesDescription) itemsSchema.propertyNames.description = formData.propertyNamesDescription;
          }
        }

        // Handle NOT composition (OpenAPI 3.1)
        if (formData.not && formData.not.trim()) {
          try {
            itemsSchema.not = JSON.parse(formData.not);
          } catch (e) {
            // If not valid JSON, treat as a simple type
            itemsSchema.not = { type: formData.not };
          }
        }

        schema.items = itemsSchema;
      }
    } else {
      // Handle nullable for non-array types (OpenAPI 3.1 style)
      schema.type = formData.nullable ? [propertyType, 'null'] : propertyType;
      if (formData.format) schema.format = formData.format;
      if (formData.pattern) schema.pattern = formData.pattern;
      if (formData.minLength) schema.minLength = parseInt(formData.minLength);
      if (formData.maxLength) schema.maxLength = parseInt(formData.maxLength);
      if (formData.minimum && formData.minimum.trim()) {
        const minValue = parseFloat(formData.minimum);
        if (!isNaN(minValue)) {
          if (formData.minimumType === 'exclusive') {
            schema.exclusiveMinimum = minValue;
          } else {
            schema.minimum = minValue;
          }
        }
      }
      if (formData.maximum && formData.maximum.trim()) {
        const maxValue = parseFloat(formData.maximum);
        if (!isNaN(maxValue)) {
          if (formData.maximumType === 'exclusive') {
            schema.exclusiveMaximum = maxValue;
          } else {
            schema.maximum = maxValue;
          }
        }
      }
      if (formData.multipleOf && formData.multipleOf.trim()) {
        const multipleOfValue = parseFloat(formData.multipleOf);
        if (!isNaN(multipleOfValue) && multipleOfValue > 0) {
          schema.multipleOf = multipleOfValue;
        }
      }
      // Handle const (mutually exclusive with enum)
      if (formData.const && formData.const.trim()) {
        try {
          schema.const = JSON.parse(formData.const);
        } catch (e) {
          // If not valid JSON, use as string
          schema.const = formData.const;
        }
      } else if (formData.enum && formData.enum.length > 0) {
        schema.enum = formData.enum;
      }
      if (formData.default) schema.default = formData.default;

      // Handle additionalProperties for object types
      if (propertyType === 'object') {
        if (formData.additionalProperties === 'true') {
          schema.additionalProperties = true;
        } else if (formData.additionalProperties === 'false') {
          schema.additionalProperties = false;
        } else if (formData.additionalProperties === 'type' && formData.additionalPropertiesType) {
          schema.additionalProperties = { type: formData.additionalPropertiesType };
        } else if (formData.additionalProperties === 'schema' && formData.additionalPropertiesSchema) {
          // Check if it's already a $ref or JSON, or just a class name
          const schemaValue = formData.additionalPropertiesSchema.trim();
          if (schemaValue.startsWith('{')) {
            try {
              schema.additionalProperties = JSON.parse(schemaValue);
            } catch {
              schema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
            }
          } else if (schemaValue.startsWith('#/') || schemaValue.startsWith('$ref')) {
            schema.additionalProperties = { $ref: schemaValue };
          } else {
            schema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
          }
        }

        // Handle minProperties and maxProperties
        if (formData.minProperties) schema.minProperties = parseInt(formData.minProperties);
        if (formData.maxProperties) schema.maxProperties = parseInt(formData.maxProperties);

        // Handle propertyNames constraints (OpenAPI 3.1)
        const hasPropertyNamesConstraints = formData.propertyNamesPattern || formData.propertyNamesMinLength || formData.propertyNamesMaxLength || formData.propertyNamesFormat || formData.propertyNamesDescription;
        if (hasPropertyNamesConstraints) {
          schema.propertyNames = { type: 'string' };
          if (formData.propertyNamesPattern) schema.propertyNames.pattern = formData.propertyNamesPattern;
          if (formData.propertyNamesMinLength) schema.propertyNames.minLength = parseInt(formData.propertyNamesMinLength);
          if (formData.propertyNamesMaxLength) schema.propertyNames.maxLength = parseInt(formData.propertyNamesMaxLength);
          if (formData.propertyNamesFormat) schema.propertyNames.format = formData.propertyNamesFormat;
          if (formData.propertyNamesDescription) schema.propertyNames.description = formData.propertyNamesDescription;
        }
      }

      // Handle NOT composition (OpenAPI 3.1)
      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          // If not valid JSON, treat as a simple type
          schema.not = { type: formData.not };
        }
      }
    }

    if (formData.owner?.trim()) {
      schema['x-owner'] = formData.owner.trim();
    }

    return schema;
  };

  const handleSubmit = async () => {
    if (!propertyName.trim()) {
      setPropertyError('Property name is required');
      return;
    }

    // Validate property name contains only A-Za-z0-9_
    if (!/^[A-Za-z0-9_]+$/.test(propertyName)) {
      setPropertyError('Property name can only contain letters, numbers, and underscores');
      return;
    }

    setIsSubmitting(true);
    setPropertyError('');

    try {
      // Start with original property data in edit mode, or empty object in add mode
      const originalData = (mode === 'edit' && property) ?
        (typeof (property as any).data === 'string' ? JSON.parse((property as any).data) : ((property as any).data || {}))
        : {};

      const dataObject: any = {
        ...originalData, // Preserve ALL original fields
        required: formData.required || false,
        readOnly: formData.readOnly || false,
        writeOnly: formData.writeOnly || false,
        deprecated: formData.deprecated || false,
      };

      // Handle deprecationMessage
      if (formData.deprecated && formData.deprecationMessage && formData.deprecationMessage.trim()) {
        dataObject.deprecationMessage = formData.deprecationMessage.trim();
      } else {
        delete dataObject.deprecationMessage;
      }

      if (formData.title) dataObject.title = formData.title;
      else delete dataObject.title;

      if (formData.examples && formData.examples.length > 0) {
        try {
          dataObject.examples = formData.examples.map(ex => JSON.parse(ex));
        } catch (e) {
          dataObject.examples = formData.examples;
        }
      } else {
        delete dataObject.examples;
      }

      if (propertyIsArray) {
        // Handle nullable for arrays (OpenAPI 3.1 style)
        dataObject.type = formData.nullable ? ['array', 'null'] : 'array';
        if (formData.minItems) dataObject.minItems = parseInt(formData.minItems);
        else delete dataObject.minItems;
        if (formData.maxItems) dataObject.maxItems = parseInt(formData.maxItems);
        else delete dataObject.maxItems;
        if (formData.uniqueItems) dataObject.uniqueItems = true;
        else delete dataObject.uniqueItems;

        // Handle contains schema (OpenAPI 3.1)
        if (formData.contains && formData.contains.trim()) {
          try {
            dataObject.contains = JSON.parse(formData.contains);
          } catch (e) {
            // If not valid JSON, treat as a simple type string
            dataObject.contains = { type: formData.contains };
          }

          // Handle minContains and maxContains (only valid when contains is set)
          if (formData.minContains) {
            const minContainsValue = parseInt(formData.minContains);
            if (!isNaN(minContainsValue) && minContainsValue >= 1) {
              dataObject.minContains = minContainsValue;
            }
          }
          if (formData.maxContains) {
            const maxContainsValue = parseInt(formData.maxContains);
            if (!isNaN(maxContainsValue) && maxContainsValue >= 1) {
              dataObject.maxContains = maxContainsValue;
            }
          }
        } else {
          delete dataObject.contains;
          delete dataObject.minContains;
          delete dataObject.maxContains;
        }

        // Handle unevaluatedItems (OpenAPI 3.1/JSON Schema 2020-12)
        if (formData.unevaluatedItems === 'allow') {
          dataObject.unevaluatedItems = true;
        } else if (formData.unevaluatedItems === 'disallow') {
          dataObject.unevaluatedItems = false;
        } else if (formData.unevaluatedItems === 'schema' && formData.unevaluatedItemsSchema?.trim()) {
          try {
            dataObject.unevaluatedItems = JSON.parse(formData.unevaluatedItemsSchema);
          } catch (e) {
            // If not valid JSON, treat as a simple type
            dataObject.unevaluatedItems = { type: formData.unevaluatedItemsSchema };
          }
        } else {
          delete dataObject.unevaluatedItems;
        }

        // Handle Tuple Mode (OpenAPI 3.1 prefixItems)
        if (formData.tupleMode && formData.prefixItems && formData.prefixItems.length > 0) {
          dataObject.prefixItems = formData.prefixItems;

          // Handle items schema for positions beyond prefix
          if (formData.itemsSchema && formData.itemsSchema.trim()) {
            try {
              dataObject.items = JSON.parse(formData.itemsSchema);
            } catch (e) {
              // If not valid JSON, treat as a simple type
              dataObject.items = { type: formData.itemsSchema };
            }
          } else {
            // Default to allowing any type for items beyond prefix
            dataObject.items = true;
          }
        } else {
          // Not in tuple mode - use regular items schema
          delete dataObject.prefixItems;

          // Preserve original items schema if it exists
          const originalItems = originalData.items || {};
          const itemsSchema: any = {
            ...originalItems, // Preserve ALL original item fields
            type: propertyType
          };
          if (formData.format) itemsSchema.format = formData.format;
          else delete itemsSchema.format;
          if (formData.pattern) itemsSchema.pattern = formData.pattern;
          else delete itemsSchema.pattern;
          if (formData.minLength) itemsSchema.minLength = parseInt(formData.minLength);
          else delete itemsSchema.minLength;
          if (formData.maxLength) itemsSchema.maxLength = parseInt(formData.maxLength);
          else delete itemsSchema.maxLength;

          // Handle minimum/maximum with exclusive support
          if (formData.minimum && formData.minimum.trim()) {
            const minValue = parseFloat(formData.minimum);
            if (!isNaN(minValue)) {
              if (formData.minimumType === 'exclusive') {
                itemsSchema.exclusiveMinimum = minValue;
                delete itemsSchema.minimum;
              } else {
                itemsSchema.minimum = minValue;
                delete itemsSchema.exclusiveMinimum;
              }
            }
          } else {
            delete itemsSchema.minimum;
            delete itemsSchema.exclusiveMinimum;
          }

          if (formData.maximum && formData.maximum.trim()) {
            const maxValue = parseFloat(formData.maximum);
            if (!isNaN(maxValue)) {
              if (formData.maximumType === 'exclusive') {
                itemsSchema.exclusiveMaximum = maxValue;
                delete itemsSchema.maximum;
              } else {
                itemsSchema.maximum = maxValue;
                delete itemsSchema.exclusiveMaximum;
              }
            }
          } else {
            delete itemsSchema.maximum;
            delete itemsSchema.exclusiveMaximum;
          }

          if (formData.multipleOf && formData.multipleOf.trim()) {
            const multipleOfValue = parseFloat(formData.multipleOf);
            if (!isNaN(multipleOfValue) && multipleOfValue > 0) {
              itemsSchema.multipleOf = multipleOfValue;
            }
          } else {
            delete itemsSchema.multipleOf;
          }

          // Handle const (mutually exclusive with enum)
          if (formData.const && formData.const.trim()) {
            try {
              itemsSchema.const = JSON.parse(formData.const);
            } catch (e) {
              // If not valid JSON, use as string
              itemsSchema.const = formData.const;
            }
            delete itemsSchema.enum;
          } else {
            delete itemsSchema.const;
            if (formData.enum && formData.enum.length > 0) {
              itemsSchema.enum = formData.enum;
            } else {
              delete itemsSchema.enum;
            }
          }

          if (formData.default) itemsSchema.default = formData.default;
          else delete itemsSchema.default;

          // Handle additionalProperties for array items that are objects
          if (propertyType === 'object') {
            if (formData.additionalProperties === 'true') {
              itemsSchema.additionalProperties = true;
            } else if (formData.additionalProperties === 'false') {
              itemsSchema.additionalProperties = false;
            } else if (formData.additionalProperties === 'type' && formData.additionalPropertiesType) {
              itemsSchema.additionalProperties = { type: formData.additionalPropertiesType };
            } else if (formData.additionalProperties === 'schema' && formData.additionalPropertiesSchema) {
              const schemaValue = formData.additionalPropertiesSchema.trim();
              if (schemaValue.startsWith('{')) {
                try {
                  itemsSchema.additionalProperties = JSON.parse(schemaValue);
                } catch {
                  itemsSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
                }
              } else if (schemaValue.startsWith('#/') || schemaValue.startsWith('$ref')) {
                itemsSchema.additionalProperties = { $ref: schemaValue };
              } else {
                itemsSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
              }
            } else {
              delete itemsSchema.additionalProperties;
            }

            // Handle minProperties and maxProperties for object items
            if (formData.minProperties) {
              itemsSchema.minProperties = parseInt(formData.minProperties);
            } else {
              delete itemsSchema.minProperties;
            }
            if (formData.maxProperties) {
              itemsSchema.maxProperties = parseInt(formData.maxProperties);
            } else {
              delete itemsSchema.maxProperties;
            }

            // Handle patternProperties
            if (formData.patternProperties && Object.keys(formData.patternProperties).length > 0) {
              itemsSchema.patternProperties = formData.patternProperties;
            } else {
              delete itemsSchema.patternProperties;
            }

            // Handle dependentSchemas (JSON Schema 2019-09+)
            if (formData.dependentSchemas && Object.keys(formData.dependentSchemas).length > 0) {
              itemsSchema.dependentSchemas = formData.dependentSchemas;
            } else {
              delete itemsSchema.dependentSchemas;
            }

            // Handle propertyNames constraints for object items (OpenAPI 3.1)
            const hasPropertyNamesConstraints = formData.propertyNamesPattern || formData.propertyNamesMinLength || formData.propertyNamesMaxLength || formData.propertyNamesFormat || formData.propertyNamesDescription;
            if (hasPropertyNamesConstraints) {
              itemsSchema.propertyNames = { type: 'string' };
              if (formData.propertyNamesPattern) {
                itemsSchema.propertyNames.pattern = formData.propertyNamesPattern;
              }
              if (formData.propertyNamesMinLength) {
                itemsSchema.propertyNames.minLength = parseInt(formData.propertyNamesMinLength);
              }
              if (formData.propertyNamesMaxLength) {
                itemsSchema.propertyNames.maxLength = parseInt(formData.propertyNamesMaxLength);
              }
              if (formData.propertyNamesFormat) {
                itemsSchema.propertyNames.format = formData.propertyNamesFormat;
              }
              if (formData.propertyNamesDescription) {
                itemsSchema.propertyNames.description = formData.propertyNamesDescription;
              }
            } else {
              delete itemsSchema.propertyNames;
            }
          }

          // Handle NOT composition (OpenAPI 3.1)
          if (formData.not && formData.not.trim()) {
            try {
              itemsSchema.not = JSON.parse(formData.not);
            } catch (e) {
              // If not valid JSON, treat as a simple type
              itemsSchema.not = { type: formData.not };
            }
          } else {
            delete itemsSchema.not;
          }

          dataObject.items = itemsSchema;
        }
      } else {
        // Handle nullable for non-array types (OpenAPI 3.1 style)
        dataObject.type = formData.nullable ? [propertyType, 'null'] : propertyType;
        if (formData.format) dataObject.format = formData.format;
        else delete dataObject.format;
        if (formData.pattern) dataObject.pattern = formData.pattern;
        else delete dataObject.pattern;
        if (formData.minLength) dataObject.minLength = parseInt(formData.minLength);
        else delete dataObject.minLength;
        if (formData.maxLength) dataObject.maxLength = parseInt(formData.maxLength);
        else delete dataObject.maxLength;

        // Handle minimum/maximum with exclusive support
        if (formData.minimum && formData.minimum.trim()) {
          const minValue = parseFloat(formData.minimum);
          if (!isNaN(minValue)) {
            if (formData.minimumType === 'exclusive') {
              dataObject.exclusiveMinimum = minValue;
              delete dataObject.minimum;
            } else {
              dataObject.minimum = minValue;
              delete dataObject.exclusiveMinimum;
            }
          }
        } else {
          delete dataObject.minimum;
          delete dataObject.exclusiveMinimum;
        }

        if (formData.maximum && formData.maximum.trim()) {
          const maxValue = parseFloat(formData.maximum);
          if (!isNaN(maxValue)) {
            if (formData.maximumType === 'exclusive') {
              dataObject.exclusiveMaximum = maxValue;
              delete dataObject.maximum;
            } else {
              dataObject.maximum = maxValue;
              delete dataObject.exclusiveMaximum;
            }
          }
        } else {
          delete dataObject.maximum;
          delete dataObject.exclusiveMaximum;
        }

        if (formData.multipleOf && formData.multipleOf.trim()) {
          const multipleOfValue = parseFloat(formData.multipleOf);
          if (!isNaN(multipleOfValue) && multipleOfValue > 0) {
            dataObject.multipleOf = multipleOfValue;
          }
        } else {
          delete dataObject.multipleOf;
        }

        // Handle const (mutually exclusive with enum)
        if (formData.const && formData.const.trim()) {
          try {
            dataObject.const = JSON.parse(formData.const);
          } catch (e) {
            // If not valid JSON, use as string
            dataObject.const = formData.const;
          }
          delete dataObject.enum;
        } else {
          delete dataObject.const;
          if (formData.enum && formData.enum.length > 0) {
            dataObject.enum = formData.enum;
          } else {
            delete dataObject.enum;
          }
        }

        if (formData.default) dataObject.default = formData.default;
        else delete dataObject.default;

        // Handle additionalProperties for object types
        if (propertyType === 'object') {
          if (formData.additionalProperties === 'true') {
            dataObject.additionalProperties = true;
          } else if (formData.additionalProperties === 'false') {
            dataObject.additionalProperties = false;
          } else {
            delete dataObject.additionalProperties;
          }

          // Handle minProperties and maxProperties
          if (formData.minProperties) {
            dataObject.minProperties = parseInt(formData.minProperties);
          } else {
            delete dataObject.minProperties;
          }
          if (formData.maxProperties) {
            dataObject.maxProperties = parseInt(formData.maxProperties);
          } else {
            delete dataObject.maxProperties;
          }

          // Handle patternProperties
          if (formData.patternProperties && Object.keys(formData.patternProperties).length > 0) {
            dataObject.patternProperties = formData.patternProperties;
          } else {
            delete dataObject.patternProperties;
          }

          // Handle dependentSchemas (JSON Schema 2019-09+)
          if (formData.dependentSchemas && Object.keys(formData.dependentSchemas).length > 0) {
            dataObject.dependentSchemas = formData.dependentSchemas;
          } else {
            delete dataObject.dependentSchemas;
          }

          // Handle propertyNames constraints (OpenAPI 3.1)
          const hasPropertyNamesConstraints = formData.propertyNamesPattern || formData.propertyNamesMinLength || formData.propertyNamesMaxLength;
          if (hasPropertyNamesConstraints) {
            dataObject.propertyNames = { type: 'string' };
            if (formData.propertyNamesPattern) {
              dataObject.propertyNames.pattern = formData.propertyNamesPattern;
            }
            if (formData.propertyNamesMinLength) {
              dataObject.propertyNames.minLength = parseInt(formData.propertyNamesMinLength);
            }
            if (formData.propertyNamesMaxLength) {
              dataObject.propertyNames.maxLength = parseInt(formData.propertyNamesMaxLength);
            }
          } else {
            delete dataObject.propertyNames;
          }
        }

        // Handle NOT composition (OpenAPI 3.1)
        if (formData.not && formData.not.trim()) {
          try {
            dataObject.not = JSON.parse(formData.not);
          } catch (e) {
            // If not valid JSON, treat as a simple type
            dataObject.not = { type: formData.not };
          }
        } else {
          delete dataObject.not;
        }
      }

      // Handle XML Object (OpenAPI 3.1)
      const hasXml = formData.xmlName || formData.xmlNamespace || formData.xmlPrefix || formData.xmlAttribute || formData.xmlWrapped;
      if (hasXml) {
        dataObject.xml = {};
        if (formData.xmlName) dataObject.xml.name = formData.xmlName;
        if (formData.xmlNamespace) dataObject.xml.namespace = formData.xmlNamespace;
        if (formData.xmlPrefix) dataObject.xml.prefix = formData.xmlPrefix;
        if (formData.xmlAttribute) dataObject.xml.attribute = formData.xmlAttribute;
        if (formData.xmlWrapped) dataObject.xml.wrapped = formData.xmlWrapped;
      } else {
        delete dataObject.xml;
      }

      // Handle Content Media Type fields (for binary/byte strings)
      if (formData.contentMediaType) {
        dataObject.contentMediaType = formData.contentMediaType;
      } else {
        delete dataObject.contentMediaType;
      }
      if (formData.contentEncoding) {
        dataObject.contentEncoding = formData.contentEncoding;
      } else {
        delete dataObject.contentEncoding;
      }
      if (formData.contentSchema && formData.contentSchema.trim()) {
        try {
          dataObject.contentSchema = JSON.parse(formData.contentSchema);
        } catch (e) {
          dataObject.contentSchema = { type: formData.contentSchema };
        }
      } else {
        delete dataObject.contentSchema;
      }

      // Handle $comment (JSON Schema 2020-12)
      if (formData.$comment) {
        dataObject.$comment = formData.$comment;
      } else {
        delete dataObject.$comment;
      }

      // Handle extensions (x- prefixed properties)
      // First, remove any existing x- properties from dataObject
      Object.keys(dataObject).forEach(key => {
        if (key.startsWith('x-')) {
          delete dataObject[key];
        }
      });
      // Then merge in the current extensions
      if (formData.extensions && Object.keys(formData.extensions).length > 0) {
        Object.assign(dataObject, formData.extensions);
      }

      if (formData.owner?.trim()) {
        dataObject['x-owner'] = formData.owner.trim();
      } else {
        delete dataObject['x-owner'];
      }

      // Handle externalDocs
      if (formData.externalDocsUrl?.trim()) {
        dataObject.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription?.trim()) {
          dataObject.externalDocs.description = formData.externalDocsDescription.trim();
        }
      } else {
        delete dataObject.externalDocs;
      }

      await onSubmit({
        name: propertyName,
        description: formData.description || null,
        data: dataObject,
      });
      // The parent onSubmit is responsible for closing or advancing the dialog
      // (e.g. stepping through pendingBulkSeeds). Do not call onClose() here.
    } catch (error) {
      console.error('Error submitting property:', error);
      setPropertyError(error instanceof Error ? error.message : 'An error occurred while saving the property');
    } finally {
      setIsSubmitting(false);
    }
  };

  const primitiveAvailable =
    (propertyType === 'string' ||
      propertyType === 'number' ||
      propertyType === 'integer' ||
      propertyType === 'array') &&
    !formData.tupleMode;

  const changedBasics =
    Boolean(formData.description?.trim()) || Boolean(formData.title?.trim());
  const changedFlags =
    Boolean(formData.required) ||
    Boolean(formData.nullable) ||
    Boolean(formData.readOnly) ||
    Boolean(formData.writeOnly) ||
    Boolean(formData.deprecated) ||
    Boolean(formData.deprecationMessage?.trim()) ||
    Boolean(formData.owner?.trim());
  const changedDefaults =
    Boolean(formData.default?.trim()) || Boolean(formData.const?.trim());
  const changedDocs =
    Boolean(formData.externalDocsUrl?.trim()) ||
    Boolean(formData.externalDocsDescription?.trim());

  const sectionChanged: Record<string, boolean> = {
    basics: changedBasics,
    flags: changedFlags,
    defaults: changedDefaults,
    constraints: false,
    docs: changedDocs,
  };

  const navItems: FormSectionNavItem[] = [
    { id: 'basics', label: 'Basics', icon: <FileText className="h-3.5 w-3.5" />, changed: sectionChanged.basics },
    { id: 'flags', label: 'Flags & Ownership', icon: <Settings className="h-3.5 w-3.5" />, changed: sectionChanged.flags },
    { id: 'defaults', label: 'Defaults & Constants', icon: <Code className="h-3.5 w-3.5" />, changed: sectionChanged.defaults },
    { id: 'constraints', label: 'Advanced Constraints', icon: <ListChecks className="h-3.5 w-3.5" /> },
    { id: 'docs', label: 'Documentation', icon: <BookOpenText className="h-3.5 w-3.5" />, changed: sectionChanged.docs },
  ];

  const wizardSteps: FormWizardStep[] = useMemo(
    () => [
      { id: 'basics', label: 'Basics', icon: <FileText className="h-4 w-4" /> },
      { id: 'flags', label: 'Flags', icon: <Settings className="h-4 w-4" /> },
      { id: 'defaults', label: 'Defaults', icon: <Code className="h-4 w-4" /> },
      { id: 'constraints', label: 'Constraints', icon: <ListChecks className="h-4 w-4" /> },
      { id: 'docs', label: 'Docs', icon: <BookOpenText className="h-4 w-4" /> },
    ],
    [],
  );
  const currentWizardSection = wizardSteps[currentStepIndex]?.id ?? 'basics';

  const sectionOrder = useMemo(
    () => ['basics', 'flags', 'defaults', 'constraints', 'docs'],
    [],
  );
  const { activeId } = useFormScrollSpy({
    sectionIds: sectionOrder,
    containerRef: advancedScrollRef,
    disabled: tabMode !== 'form' || viewMode !== 'advanced',
  });

  const handleNextStep = () => {
    setCurrentStepIndex((i) => Math.min(i + 1, wizardSteps.length - 1));
  };
  const handlePrevStep = () => {
    setCurrentStepIndex((i) => Math.max(i - 1, 0));
  };

  const addModeAiTypeSuggest =
    mode === 'add' && propertyAiContext && onApplyAiTypeSchema
      ? { onOpen: () => setAiTypeSuggestOpen(true) }
      : null;

  const propertySchemaForAi = useMemo(
    () =>
      draftPropertySchemaFromDialogForm({
        propertyType,
        propertyIsArray,
        formData,
        seedProperty: property,
      }),
    [propertyType, propertyIsArray, formData, property],
  );

  const applyAiDescription = useCallback((text: string) => {
    setFormData((prev) => ({ ...prev, description: text }));
  }, []);

  const applyAiExample = useCallback((jsonLine: string) => {
    setFormData((prev) => ({
      ...prev,
      examples: [...(prev.examples || []), jsonLine],
    }));
  }, []);

  const descriptionAiSlot =
    open && propertyAiContext ? (
      <PropertyDescriptionAiButton
        tenantId={propertyAiContext.tenantId}
        projectId={propertyAiContext.projectId}
        versionId={propertyAiContext.versionId}
        propertyName={propertyName}
        propertySchema={propertySchemaForAi}
        contextClassName={propertyAiContext.contextClassName}
        existingClasses={propertyAiContext.existingClasses}
        existingProperties={propertyAiContext.existingProperties}
        studioContext={propertyAiContext.studioContext}
        onGenerated={applyAiDescription}
        disabled={!propertyName.trim()}
      />
    ) : null;

  const exampleAiSlot =
    open && propertyAiContext ? (
      <PropertyExampleAiButton
        tenantId={propertyAiContext.tenantId}
        projectId={propertyAiContext.projectId}
        versionId={propertyAiContext.versionId}
        propertyName={propertyName}
        propertySchema={propertySchemaForAi}
        propertyDescription={formData.description}
        contextClassName={propertyAiContext.contextClassName}
        existingClasses={propertyAiContext.existingClasses}
        existingProperties={propertyAiContext.existingProperties}
        studioContext={propertyAiContext.studioContext}
        onGenerated={applyAiExample}
        disabled={!propertyName.trim()}
      />
    ) : null;

  const handleApplyAiTypeSuggestion = (s: AiPropertySuggestion) => {
    if (!onApplyAiTypeSchema) return;
    onApplyAiTypeSchema({
      name: propertyName.trim(),
      description: (formData.description || '').trim() || null,
      schema: s.schema as Record<string, unknown>,
    });
  };

  return (
    <>
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()} modal={true}>
      <DialogContent
        className="max-w-6xl h-[90vh] max-h-[900px] p-0 flex flex-col overflow-hidden"
        showCloseButton={true}
        aria-describedby={undefined}
      >
        <DialogHeader className="pl-6 pr-10 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex min-w-0 items-center gap-3">
            <DialogTitle className="text-lg font-semibold">
              {mode === 'add' ? 'Add Property' : 'Edit Property'}
            </DialogTitle>
            {propertyName && mode === 'edit' && (
              <code className="truncate rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                {propertyName}
              </code>
            )}
          </div>
        </DialogHeader>

        <Tabs value={tabMode} onValueChange={(v) => setTabMode(v as 'form' | 'json')} className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-6 shrink-0 gap-4">
            <TabsList className="h-auto p-0 rounded-none bg-transparent justify-start gap-0 -ml-2">
              <TabsTrigger
                value="form"
                className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
              >
                Form
              </TabsTrigger>
              <TabsTrigger
                value="json"
                className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
              >
                JSON
              </TabsTrigger>
            </TabsList>
            {tabMode === 'form' && (
              <FormViewModeToggle value={viewMode} onChange={setViewMode} />
            )}
          </div>

          {/* Form Tab */}
          <TabsContent value="form" className="flex-1 flex flex-col overflow-hidden mt-0 p-0">
            {propertyError && <Alert variant="error" className="m-4 mb-0">{propertyError}</Alert>}

            {viewMode === 'guided' ? (
              <div className="flex flex-1 flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
                <FormWizardStepper
                  steps={wizardSteps}
                  currentIndex={currentStepIndex}
                  onStepSelect={setCurrentStepIndex}
                />
                <div
                  className={`flex-1 overflow-y-auto min-h-0 transition-opacity duration-200 ${primitiveDialogOpen ? 'opacity-30 pointer-events-none select-none' : 'opacity-100'}`}
                >
                  <div className="mx-auto max-w-4xl">
                    {currentWizardSection === 'basics' && (
                      <BasicsSection
                        mode={mode}
                        propertyName={propertyName}
                        setPropertyName={setPropertyName}
                        propertyType={propertyType}
                        setPropertyType={setPropertyType}
                        propertyIsArray={propertyIsArray}
                        setPropertyIsArray={setPropertyIsArray}
                        formData={formData}
                        setFormData={setFormData}
                        primitiveAvailable={primitiveAvailable}
                        setPrimitiveDialogOpen={setPrimitiveDialogOpen}
                        addModeAiTypeSuggest={addModeAiTypeSuggest}
                        onOpenAiPropertySuggestions={onOpenAiPropertySuggestions}
                        descriptionAiSlot={descriptionAiSlot}
                        changed={changedBasics}
                        eyebrow="Step 1 of 5"
                      />
                    )}
                    {currentWizardSection === 'flags' && (
                      <FlagsSection
                        formData={formData}
                        setFormData={setFormData}
                        changed={changedFlags}
                        eyebrow="Step 2 of 5"
                      />
                    )}
                    {currentWizardSection === 'defaults' && (
                      <DefaultsSection
                        formData={formData}
                        setFormData={setFormData}
                        changed={changedDefaults}
                        eyebrow="Step 3 of 5"
                      />
                    )}
                    {currentWizardSection === 'constraints' && (
                      <ConstraintsSection
                        propertyType={propertyType}
                        propertyIsArray={propertyIsArray}
                        formData={formData}
                        setFormData={setFormData}
                        availableClasses={availableClasses}
                        examplesAiSlot={exampleAiSlot}
                        eyebrow="Step 4 of 5"
                      />
                    )}
                    {currentWizardSection === 'docs' && (
                      <DocsSection
                        formData={formData}
                        setFormData={setFormData}
                        changed={changedDocs}
                        eyebrow="Step 5 of 5"
                      />
                    )}
                  </div>
                </div>
                <div className="border-t border-slate-200 bg-white px-6 py-3 dark:border-slate-800 dark:bg-slate-900">
                  <FormWizardControls
                    currentIndex={currentStepIndex}
                    stepCount={wizardSteps.length}
                    onBack={handlePrevStep}
                    onNext={handleNextStep}
                    onCancel={onClose}
                    onFinish={handleSubmit}
                    finishLabel={mode === 'add' ? 'Add Property' : 'Save'}
                    finishBusy={isSubmitting}
                    finishDisabled={!propertyName.trim() || isSubmitting}
                  />
                </div>
              </div>
            ) : (
              <div className="flex flex-1 overflow-hidden min-h-0 bg-slate-50 dark:bg-slate-950">
                <FormSectionNav
                  items={navItems}
                  activeId={activeId}
                  onSelect={(id) => scrollToSection(advancedScrollRef.current, id, 16)}
                  title="Property"
                />
                <div
                  ref={advancedScrollRef}
                  className={`flex-1 overflow-y-auto min-h-0 transition-opacity duration-200 ${primitiveDialogOpen ? 'opacity-30 pointer-events-none select-none' : 'opacity-100'}`}
                >
                  <div className="mx-auto max-w-4xl divide-y divide-slate-200 dark:divide-slate-800">
                    <BasicsSection
                      mode={mode}
                      propertyName={propertyName}
                      setPropertyName={setPropertyName}
                      propertyType={propertyType}
                      setPropertyType={setPropertyType}
                      propertyIsArray={propertyIsArray}
                      setPropertyIsArray={setPropertyIsArray}
                      formData={formData}
                      setFormData={setFormData}
                      primitiveAvailable={primitiveAvailable}
                      setPrimitiveDialogOpen={setPrimitiveDialogOpen}
                      addModeAiTypeSuggest={addModeAiTypeSuggest}
                      onOpenAiPropertySuggestions={onOpenAiPropertySuggestions}
                      descriptionAiSlot={descriptionAiSlot}
                      changed={changedBasics}
                    />
                    <FlagsSection formData={formData} setFormData={setFormData} changed={changedFlags} />
                    <DefaultsSection formData={formData} setFormData={setFormData} changed={changedDefaults} />
                    <ConstraintsSection
                      propertyType={propertyType}
                      propertyIsArray={propertyIsArray}
                      formData={formData}
                      setFormData={setFormData}
                      availableClasses={availableClasses}
                      examplesAiSlot={exampleAiSlot}
                    />
                    <DocsSection formData={formData} setFormData={setFormData} changed={changedDocs} />
                  </div>
                </div>
              </div>
            )}
          </TabsContent>

          {/* JSON Tab */}
          <TabsContent value="json" className="flex-1 flex flex-col overflow-hidden mt-0 p-6">
            <div className="mb-2">
              <p className="text-sm text-gray-500 dark:text-gray-400">JSON Schema 2020-12 Definition</p>
            </div>
            <div className="flex-1 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden min-h-[300px]">
              <Editor
                height="100%"
                defaultLanguage="json"
                value={JSON.stringify(buildPropertyJsonSchema(), null, 2)}
                theme={isDark ? 'vs-dark' : 'vs-light'}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  lineNumbers: 'on',
                  renderWhitespace: 'none',
                  automaticLayout: true,
                  wordWrap: 'on',
                  folding: true,
                  contextmenu: false,
                  selectOnLineNumbers: true,
                  roundedSelection: false,
                  cursorStyle: 'line',
                  scrollbar: {
                    vertical: 'auto',
                    horizontal: 'auto',
                  },
                }}
              />
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
              This is the JSON Schema representation of your property definition. Switch back to Form view to make changes.
            </p>
          </TabsContent>
        </Tabs>

        {/* Footer - hidden in guided-form mode because the wizard provides its own controls */}
        {!(tabMode === 'form' && viewMode === 'guided') && (
          <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
            <div className="flex justify-end w-full gap-2">
              <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={isSubmitting || !propertyName.trim()}>
                {isSubmitting ? 'Saving…' : mode === 'add' ? 'Add Property' : 'Save'}
              </Button>
            </div>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>

    {propertyAiContext && onApplyAiTypeSchema && (
      <AiPropertyTypeSuggestionsDialog
        open={aiTypeSuggestOpen}
        onClose={() => setAiTypeSuggestOpen(false)}
        tenantId={propertyAiContext.tenantId}
        projectId={propertyAiContext.projectId}
        versionId={propertyAiContext.versionId}
        targetPropertyName={propertyName}
        targetPropertyDescription={formData.description}
        contextClassName={propertyAiContext.contextClassName}
        existingClasses={propertyAiContext.existingClasses}
        existingProperties={propertyAiContext.existingProperties}
        studioContext={propertyAiContext.studioContext}
        onApplyTypeSuggestion={handleApplyAiTypeSuggestion}
      />
    )}
    </>
  );
};

export default PropertyDialog;
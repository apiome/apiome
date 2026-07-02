'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
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
import { Badge } from '../../ui/Badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import { PropertyFormFields, PropertyFormData } from './PropertyFormFields';
import { PrimitiveSelector } from './PrimitiveSelector';
import { ResolvedTypePreview } from './ResolvedTypePreview';
import ExtractToClassDialog from './ExtractToClassDialog';
import {
  GitBranch,
  FileText,
  Settings,
  Code,
  AlertTriangle,
  Info,
  ExternalLink,
  Sparkles,
  ListChecks,
  BookOpenText,
} from 'lucide-react';
import {
  FormSection,
  FormSubsection,
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
import type { PropertyDialogAiContext } from './PropertyDialog';
import { PropertyDescriptionAiButton } from './PropertyDescriptionAiButton';
import { PropertyExampleAiButton } from './PropertyExampleAiButton';
import { summarizeStoredPropertyData } from '@lib/ai-property-description';

interface Props {
  open: boolean;
  onClose: () => void;
  editingClassProperty: any | null;
  // Callback to reload classes after a successful save
  // applyLayout: optional parameter to trigger layout recalculation after reload
  onSaved?: (applyLayout?: boolean) => Promise<void> | void;
  // All properties from the parent class (to show nested properties)
  allClassProperties?: Array<{
    id: string;
    name: string;
    data: any;
    description?: string;
    parent_id?: string | null;
  }>;
  // For extract to class feature
  existingClassNames?: string[];
  // Available classes for reference selection (id, name pairs)
  availableClasses?: Array<{ id: string; name: string }>;
  /** Ollama-backed description generation (#619); same shape as Property dialog AI context. */
  propertyAiContext?: PropertyDialogAiContext;
}

// ────────────────────────────────────────────────────────────────────────────
// Section renderers for the non-reference (scalar / object / array) editor.
// Kept at module level so the same subtree renders in both Guided (wizard)
// and Advanced (scroll-spy) modes without re-mounting.
// ────────────────────────────────────────────────────────────────────────────

interface BasicsSectionProps {
  editPropName: string;
  setEditPropName: (v: string) => void;
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  typeInfoLabel: string;
  hasRef: boolean;
  propertyType: string;
  primitiveAvailable: boolean;
  descriptionAiSlot?: React.ReactNode;
  changed?: boolean;
  eyebrow?: string;
}

const BasicsSection: React.FC<BasicsSectionProps> = ({
  editPropName,
  setEditPropName,
  formData,
  setFormData,
  typeInfoLabel,
  hasRef,
  propertyType,
  primitiveAvailable,
  descriptionAiSlot,
  changed,
  eyebrow = 'Basics',
}) => (
  <FormSection
    id="basics"
    icon={<FileText className="h-4 w-4" />}
    eyebrow={eyebrow}
    title="Basics"
    description="Identify this class member. Only the name and constraints can be modified — the type is fixed."
    changed={changed}
  >
    <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-900/50 dark:bg-blue-950/30">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
      <p className="text-sm leading-5 text-blue-800 dark:text-blue-200">
        Class-member properties can only have their name and validation constraints modified. The
        underlying type is locked by the enclosing class.
      </p>
    </div>

    <FormFieldGroup label="Property Type (Read-Only)">
      <div className="flex items-center gap-2">
        <Badge variant="secondary" className="px-3 py-1 font-mono text-sm">
          {typeInfoLabel}
        </Badge>
        {hasRef && (
          <span className="text-xs text-slate-500 dark:text-slate-400">(References another class)</span>
        )}
      </div>
    </FormFieldGroup>

    <FormFieldGroup
      label="Property Name"
      required
      htmlFor="propertyName"
      helper="camelCase recommended."
    >
      <Input
        id="propertyName"
        autoFocus
        value={editPropName}
        onChange={(e) => setEditPropName(e.target.value)}
        placeholder="e.g., userName"
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
          />
        </div>
        {/* Resolve the bound registry type to its effective schema and let the
            author validate an example value against it (#3476). */}
        {formData.$ref && (
          <ResolvedTypePreview
            className="mt-4"
            propertyRef={formData.$ref}
            primitiveId={formData.primitive_id}
          />
        )}
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
      <FormFieldGroup label="Default Value" htmlFor="defaultValue" helper="Used when no value is provided.">
        <Input
          id="defaultValue"
          value={formData.default || ''}
          onChange={(e) => setFormData((prev) => ({ ...prev, default: e.target.value }))}
          placeholder='JSON value (e.g., "hello", 123, true)'
          className="font-mono text-sm"
        />
      </FormFieldGroup>
      <FormFieldGroup label="Constant Value" htmlFor="constValue" helper="Must always equal this value.">
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
  baseType: string;
  isArray: boolean;
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  nestedProperties?: Array<{ id: string; name: string; data: any; description?: string; parent_id?: string | null }>;
  availableClasses: string[];
  examplesAiSlot?: React.ReactNode;
  eyebrow?: string;
}

const ConstraintsSection: React.FC<ConstraintsSectionProps> = ({
  baseType,
  isArray,
  formData,
  setFormData,
  nestedProperties,
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
      baseType={baseType}
      isArray={isArray}
      data={formData}
      onChange={(field, value) => {
        setFormData((prev) => ({ ...prev, [field]: value }));
      }}
      showMetadata={false}
      showTitle={false}
      showPrimitiveSelector={false}
      showHint={false}
      size="small"
      nestedProperties={nestedProperties}
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
          onChange={(e) => setFormData((prev) => ({ ...prev, externalDocsDescription: e.target.value }))}
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

// Reference-configuration body (renders as a single FormSection with subsections).
interface ReferenceSectionProps {
  refDescription: string;
  setRefDescription: (v: string) => void;
  refIsArray: boolean;
  setRefIsArray: (v: boolean) => void;
  refCompositionType: 'none' | 'allOf' | 'anyOf' | 'oneOf';
  setRefCompositionType: (v: 'none' | 'allOf' | 'anyOf' | 'oneOf') => void;
  refTargetClassId: string;
  setRefTargetClassId: (v: string) => void;
  refTargetClassIds: string[];
  setRefTargetClassIds: (v: string[]) => void;
  refMinItems: string;
  setRefMinItems: (v: string) => void;
  refMaxItems: string;
  setRefMaxItems: (v: string) => void;
  refUniqueItems: boolean;
  setRefUniqueItems: (v: boolean) => void;
  formData: PropertyFormData;
  setFormData: React.Dispatch<React.SetStateAction<PropertyFormData>>;
  availableClasses: Array<{ id: string; name: string }>;
}

const COMPOSITION_OPTIONS: Array<{
  value: 'none' | 'allOf' | 'anyOf' | 'oneOf';
  title: string;
  description: string;
}> = [
  { value: 'none', title: 'Single Reference', description: 'Reference a single class.' },
  { value: 'allOf', title: 'allOf (Composition)', description: 'Must satisfy all referenced schemas.' },
  { value: 'anyOf', title: 'anyOf (Union)', description: 'Can satisfy any of the referenced schemas.' },
  { value: 'oneOf', title: 'oneOf (Exclusive)', description: 'Must satisfy exactly one referenced schema.' },
];

const ReferenceSection: React.FC<ReferenceSectionProps> = ({
  refDescription,
  setRefDescription,
  refIsArray,
  setRefIsArray,
  refCompositionType,
  setRefCompositionType,
  refTargetClassId,
  setRefTargetClassId,
  refTargetClassIds,
  setRefTargetClassIds,
  refMinItems,
  setRefMinItems,
  refMaxItems,
  setRefMaxItems,
  refUniqueItems,
  setRefUniqueItems,
  formData,
  setFormData,
  availableClasses,
}) => {
  const changed =
    Boolean(refDescription.trim()) ||
    refIsArray ||
    refCompositionType !== 'none' ||
    Boolean(refTargetClassId) ||
    refTargetClassIds.length > 0 ||
    Boolean(formData.nullable);

  return (
    <FormSection
      id="reference"
      icon={<GitBranch className="h-4 w-4" />}
      eyebrow="Reference"
      title="Reference Configuration"
      description="Link this property to one or more other classes, optionally composed via allOf, anyOf, or oneOf."
      accent="purple"
      changed={changed}
    >
      <FormFieldGroup label="Description" htmlFor="refDescription">
        <Textarea
          id="refDescription"
          value={refDescription}
          onChange={(e) => setRefDescription(e.target.value)}
          placeholder="Description of this reference property"
          rows={3}
        />
      </FormFieldGroup>

      <FormToggleCard
        id="refIsArray"
        label="Array of references"
        description="Check to model a list of referenced values."
        accent="indigo"
        checked={refIsArray}
        onCheckedChange={setRefIsArray}
      />

      {refIsArray && (
        <FormSubsection
          tone="subtle"
          icon={<Settings className="h-3.5 w-3.5" />}
          title="Array constraints"
          description="Apply size and uniqueness rules to the reference array."
        >
          <FormGrid cols={2} gap="md">
            <FormFieldGroup label="Min Items" htmlFor="refMinItems">
              <Input
                id="refMinItems"
                type="number"
                value={refMinItems}
                onChange={(e) => setRefMinItems(e.target.value)}
                placeholder="0"
              />
            </FormFieldGroup>
            <FormFieldGroup label="Max Items" htmlFor="refMaxItems">
              <Input
                id="refMaxItems"
                type="number"
                value={refMaxItems}
                onChange={(e) => setRefMaxItems(e.target.value)}
                placeholder="No limit"
              />
            </FormFieldGroup>
          </FormGrid>
          <FormToggleCard
            id="refUniqueItems"
            label="Unique items"
            description="All elements must be distinct."
            checked={refUniqueItems}
            onCheckedChange={setRefUniqueItems}
          />
        </FormSubsection>
      )}

      <FormSubsection
        tone="card"
        icon={<GitBranch className="h-3.5 w-3.5" />}
        title="Reference type"
        description="Pick how the referenced classes combine."
        accent="purple"
      >
        <div role="radiogroup" aria-label="Reference type" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {COMPOSITION_OPTIONS.map((opt) => {
            const active = refCompositionType === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => {
                  setRefCompositionType(opt.value);
                  if (opt.value === 'none') {
                    setRefTargetClassIds([]);
                  } else {
                    setRefTargetClassId('');
                  }
                }}
                className={
                  'flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ' +
                  (active
                    ? 'border-indigo-300 bg-indigo-50 text-slate-900 dark:border-indigo-700 dark:bg-indigo-900/30 dark:text-slate-100'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-700')
                }
              >
                <span className="font-medium">{opt.title}</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{opt.description}</span>
              </button>
            );
          })}
        </div>
      </FormSubsection>

      {refCompositionType === 'none' ? (
        <FormFieldGroup
          label="Target Class"
          htmlFor="targetClass"
          helper="Select the class this property references."
        >
          <Select value={refTargetClassId} onValueChange={setRefTargetClassId}>
            <SelectTrigger id="targetClass" className="w-full">
              <SelectValue placeholder="Select a class..." />
            </SelectTrigger>
            <SelectContent>
              {availableClasses.map((cls) => (
                <SelectItem key={cls.id} value={cls.id}>
                  {cls.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormFieldGroup>
      ) : (
        <FormFieldGroup label={`Classes for ${refCompositionType}`} htmlFor="targetClassMulti">
          <Select
            value=""
            onValueChange={(classId) => {
              if (classId && !refTargetClassIds.includes(classId)) {
                setRefTargetClassIds([...refTargetClassIds, classId]);
              }
            }}
          >
            <SelectTrigger id="targetClassMulti" className="w-full">
              <SelectValue placeholder="Add a class..." />
            </SelectTrigger>
            <SelectContent>
              {availableClasses
                .filter((cls) => !refTargetClassIds.includes(cls.id))
                .map((cls) => (
                  <SelectItem key={cls.id} value={cls.id}>
                    {cls.name}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          {refTargetClassIds.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {refTargetClassIds.map((classId) => {
                const cls = availableClasses.find((c) => c.id === classId);
                return cls ? (
                  <Badge key={classId} variant="secondary" className="flex items-center gap-1">
                    {cls.name}
                    <button
                      type="button"
                      onClick={() =>
                        setRefTargetClassIds(refTargetClassIds.filter((id) => id !== classId))
                      }
                      className="ml-1 rounded-sm px-0.5 text-slate-500 hover:text-red-500"
                      aria-label={`Remove ${cls.name}`}
                    >
                      ×
                    </button>
                  </Badge>
                ) : null;
              })}
            </div>
          ) : (
            <Alert variant="default" className="mt-2 border-blue-200 bg-blue-50 dark:border-blue-900/50 dark:bg-blue-950/30">
              <Info className="h-4 w-4" />
              <span className="ml-2 text-sm">Add at least one class for {refCompositionType}.</span>
            </Alert>
          )}
        </FormFieldGroup>
      )}

      <FormToggleCard
        id="refNullable"
        label="Nullable"
        description="The reference can be null."
        accent="amber"
        checked={formData.nullable || false}
        onCheckedChange={(v) => setFormData((prev) => ({ ...prev, nullable: v }))}
      />
    </FormSection>
  );
};

export default function ClassPropertyEditDialog({
  open,
  onClose,
  editingClassProperty,
  onSaved,
  allClassProperties,
  existingClassNames = [],
  availableClasses = [],
  propertyAiContext,
}: Props) {
  const [editPropName, setEditPropName] = useState('');
  const [editPropertyError, setEditPropertyError] = useState('');
  const [extractDialogOpen, setExtractDialogOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Form layout state
  const [viewMode, setViewMode] = useFormViewMode('class-property-edit-view-mode');
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const advancedScrollRef = useRef<HTMLDivElement>(null);

  // Use shared form data structure
  const [formData, setFormData] = useState<PropertyFormData>({});

  // Reference-specific state
  type CompositionType = 'none' | 'allOf' | 'anyOf' | 'oneOf';
  const [refDescription, setRefDescription] = useState('');
  const [refIsArray, setRefIsArray] = useState(false);
  const [refCompositionType, setRefCompositionType] = useState<CompositionType>('none');
  const [refTargetClassId, setRefTargetClassId] = useState<string>('');
  const [refTargetClassIds, setRefTargetClassIds] = useState<string[]>([]);
  const [refMinItems, setRefMinItems] = useState('');
  const [refMaxItems, setRefMaxItems] = useState('');
  const [refUniqueItems, setRefUniqueItems] = useState(false);

  // Helper to get property type display
  const getPropertyTypeInfo = () => {
    if (!editingClassProperty) return { type: 'unknown', baseType: 'unknown', isArray: false, isNullable: false };

    const propData = typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {});

    // Handle nullable type arrays (OpenAPI 3.1 style)
    let actualType = propData.type;
    let isNullable = false;
    if (Array.isArray(propData.type)) {
      isNullable = propData.type.includes('null');
      actualType = propData.type.find((t: string) => t !== 'null') || 'string';
    }

    // Also check for oneOf pattern with null (used for nullable references)
    if (propData.oneOf && Array.isArray(propData.oneOf)) {
      const hasNullType = propData.oneOf.some((item: any) => item.type === 'null');
      const hasRef = propData.oneOf.some((item: any) => item.$ref);
      if (hasNullType && hasRef) {
        isNullable = true;
      }
    }

    const isArray = actualType === 'array';
    const schema = isArray ? (propData.items || {}) : propData;

    let baseType = 'unknown';
    if (schema.$ref) {
      const refParts = schema.$ref.split('/');
      baseType = refParts[refParts.length - 1] || schema.$ref;
    } else {
      baseType = schema.type || 'object';
    }

    const nullableSuffix = isNullable ? '?' : '';
    return {
      type: isArray ? `${baseType}[]${nullableSuffix}` : `${baseType}${nullableSuffix}`,
      baseType,
      isArray,
      isNullable,
      hasRef: !!schema.$ref
    };
  };

  // Check if property can be extracted to a class
  const canExtractToClass = () => {
    if (!editingClassProperty) return false;

    const propData = typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {});

    const isDirectObject = propData.type === 'object' && !propData.$ref;
    const isArrayOfObjects = propData.type === 'array' && propData.items?.type === 'object' && !propData.items?.$ref;

    return isDirectObject || isArrayOfObjects;
  };

  const handleExtractSuccess = async (newClassId: string, newClassName: string) => {
    setExtractDialogOpen(false);
    // Reload classes with layout applied to properly position the new class
    if (onSaved) await onSaved(true); // Pass true to apply layout
    onClose();
  };

  // Reset wizard to the first step whenever the dialog reopens with a new property
  useEffect(() => {
    if (open) setCurrentStepIndex(0);
  }, [open, editingClassProperty?.id]);

  // Initialize form when editingClassProperty changes
  useEffect(() => {
    if (!editingClassProperty) return;

    setEditPropName(editingClassProperty.name || '');

    const propData = typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {});

    // Detect nullable - can be from:
    // 1. Type array like ['string', 'null']
    // 2. oneOf pattern like [{ $ref: '...' }, { type: 'null' }] for references
    let isNullable = false;
    let actualType = propData.type;

    // Check for type array pattern
    if (Array.isArray(propData.type)) {
      isNullable = propData.type.includes('null');
      actualType = propData.type.find((t: string) => t !== 'null');
    }

    // Check for oneOf pattern with null (used for nullable references)
    if (propData.oneOf && Array.isArray(propData.oneOf)) {
      const hasNullType = propData.oneOf.some((item: any) => item.type === 'null');
      const hasRef = propData.oneOf.some((item: any) => item.$ref);
      if (hasNullType && hasRef) {
        isNullable = true;
      }
    }

    // Get the actual schema (handle array types)
    const schema = actualType === 'array' ? (propData.items || {}) : propData;


    // Determine additionalProperties value
    let additionalPropsValue: 'default' | 'true' | 'false' | 'type' | 'schema' = 'default';
    let additionalPropsType: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' = 'string';
    let additionalPropsSchema = '';
    if (schema.hasOwnProperty('additionalProperties')) {
      if (schema.additionalProperties === true) {
        additionalPropsValue = 'true';
      } else if (schema.additionalProperties === false) {
        additionalPropsValue = 'false';
      } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.$ref) {
        additionalPropsValue = 'schema';
        // Extract just the class name from the $ref path (e.g., "#/components/schemas/ClassName" -> "ClassName")
        const refPath = schema.additionalProperties.$ref;
        additionalPropsSchema = refPath.split('/').pop() || refPath;
      } else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties.type) {
        additionalPropsValue = 'type';
        additionalPropsType = schema.additionalProperties.type;
      } else if (typeof schema.additionalProperties === 'object') {
        additionalPropsValue = 'schema';
        additionalPropsSchema = JSON.stringify(schema.additionalProperties);
      }
    }

    // Extract extensions (x- prefixed properties) from the property data (x-owner uses dedicated Owner field)
    const extensions: Record<string, any> = {};
    Object.keys(propData).forEach(key => {
      if (key.startsWith('x-') && key !== 'x-owner') {
        extensions[key] = propData[key];
      }
    });

    // Populate form data
    setFormData({
      description: editingClassProperty.description || '',
      // Rehydrate the persisted type-registry binding (#3475) so the bound-type
      // chip and resolved target survive a reload. These live in dedicated
      // class_properties columns, not in the property's JSON Schema `data`.
      $ref: editingClassProperty.primitive_ref || '',
      primitive_id: editingClassProperty.primitive_id || '',
      required: !!propData.required,
      nullable: isNullable,
      deprecated: !!propData.deprecated,
      deprecationMessage: propData.deprecationMessage || '',
      owner: propData['x-owner'] != null && String(propData['x-owner']).trim() !== '' ? String(propData['x-owner']) : '',
      readOnly: !!propData.readOnly,
      writeOnly: !!propData.writeOnly,
      examples: propData.examples ? propData.examples.map((ex: any) => JSON.stringify(ex)) : [],

      // String constraints
      minLength: schema.minLength?.toString() || '',
      maxLength: schema.maxLength?.toString() || '',
      pattern: schema.pattern || '',
      format: schema.format || '',

      // Number constraints - detect inclusive vs exclusive
      minimum: (schema.exclusiveMinimum !== undefined ? schema.exclusiveMinimum : schema.minimum)?.toString() || '',
      maximum: (schema.exclusiveMaximum !== undefined ? schema.exclusiveMaximum : schema.maximum)?.toString() || '',
      minimumType: schema.exclusiveMinimum !== undefined ? 'exclusive' as const : (schema.minimum !== undefined ? 'inclusive' as const : undefined),
      maximumType: schema.exclusiveMaximum !== undefined ? 'exclusive' as const : (schema.maximum !== undefined ? 'inclusive' as const : undefined),
      multipleOf: schema.multipleOf?.toString() || '',

      // Array constraints
      minItems: propData.minItems?.toString() || '',
      maxItems: propData.maxItems?.toString() || '',
      uniqueItems: !!propData.uniqueItems,
      contains: propData.contains ? JSON.stringify(propData.contains, null, 2) : '',
      minContains: propData.minContains?.toString() || '',
      maxContains: propData.maxContains?.toString() || '',

      // Tuple mode (OpenAPI 3.1)
      tupleMode: propData.prefixItems && Array.isArray(propData.prefixItems) ? true : false,
      prefixItems: propData.prefixItems || [],
      itemsSchema: propData.prefixItems && propData.items !== undefined ?
        (typeof propData.items === 'object' ?
          JSON.stringify(propData.items, null, 2) :
          String(propData.items)) : '',

      // unevaluatedItems (OpenAPI 3.1/JSON Schema 2020-12)
      unevaluatedItems: propData.unevaluatedItems === true ? 'allow' :
        propData.unevaluatedItems === false ? 'disallow' :
        (typeof propData.unevaluatedItems === 'object' ? 'schema' : 'default'),
      unevaluatedItemsSchema: typeof propData.unevaluatedItems === 'object' ?
        JSON.stringify(propData.unevaluatedItems, null, 2) : '',

      // Common constraints
      default: schema.default !== undefined ? JSON.stringify(schema.default) : '',
      const: schema.const !== undefined ? (typeof schema.const === 'string' ? schema.const : JSON.stringify(schema.const)) : '',
      enum: schema.enum || [],

      // Object constraints
      additionalProperties: additionalPropsValue,
      additionalPropertiesType: additionalPropsType,
      additionalPropertiesSchema: additionalPropsSchema,
      minProperties: schema.minProperties?.toString() || '',
      maxProperties: schema.maxProperties?.toString() || '',
      patternProperties: schema.patternProperties || undefined,

      // unevaluatedProperties (OpenAPI 3.1/JSON Schema 2020-12) - for objects
      unevaluatedProperties: schema.unevaluatedProperties === true ? 'allow' :
        schema.unevaluatedProperties === false ? 'disallow' :
        (typeof schema.unevaluatedProperties === 'object' ? 'schema' : 'default'),
      unevaluatedPropertiesSchema: typeof schema.unevaluatedProperties === 'object' ?
        JSON.stringify(schema.unevaluatedProperties, null, 2) : '',

      // Property Name Constraints (OpenAPI 3.1)
      propertyNamesPattern: schema.propertyNames?.pattern || '',
      propertyNamesMinLength: schema.propertyNames?.minLength?.toString() || '',
      propertyNamesMaxLength: schema.propertyNames?.maxLength?.toString() || '',
      propertyNamesFormat: schema.propertyNames?.format || '',
      propertyNamesDescription: schema.propertyNames?.description || '',

      // Dependent Schemas (JSON Schema 2019-09+)
      dependentSchemas: schema.dependentSchemas || undefined,

      // NOT composition (OpenAPI 3.1)
      not: schema.not ? JSON.stringify(schema.not, null, 2) : '',

      // Extensions (x- prefixed properties)
      extensions: extensions,

      // External Documentation
      externalDocsUrl: propData.externalDocs?.url || '',
      externalDocsDescription: propData.externalDocs?.description || '',

      // XML Object (OpenAPI 3.1)
      xmlName: propData.xml?.name || '',
      xmlNamespace: propData.xml?.namespace || '',
      xmlPrefix: propData.xml?.prefix || '',
      xmlAttribute: propData.xml?.attribute || false,
      xmlWrapped: propData.xml?.wrapped || false,

      // Content Media Type (for binary/byte strings)
      contentMediaType: propData.contentMediaType || '',
      contentEncoding: propData.contentEncoding || '',
      contentSchema: propData.contentSchema ? JSON.stringify(propData.contentSchema, null, 2) : '',

      // Schema Metadata
      $comment: propData.$comment || '',
    });

    // Initialize reference-specific fields
    const isArrayType = actualType === 'array';
    const refSchema = isArrayType ? (propData.items || {}) : propData;

    // Set description for references
    setRefDescription(editingClassProperty.description || propData.description || '');

    // Set array state
    setRefIsArray(isArrayType);
    setRefMinItems(propData.minItems?.toString() || '');
    setRefMaxItems(propData.maxItems?.toString() || '');
    setRefUniqueItems(!!propData.uniqueItems);

    // Determine composition type and target classes
    if (refSchema.$ref) {
      // Single reference
      setRefCompositionType('none');
      // Extract class name from $ref
      const refClassName = refSchema.$ref.split('/').pop() || '';
      // Find matching class ID from availableClasses
      const matchingClass = availableClasses.find(c => c.name === refClassName);
      setRefTargetClassId(matchingClass?.id || '');
      setRefTargetClassIds([]);
    } else if (refSchema.allOf && Array.isArray(refSchema.allOf)) {
      setRefCompositionType('allOf');
      setRefTargetClassId('');
      // Extract all class IDs from allOf refs
      const classIds = refSchema.allOf
        .filter((item: any) => item.$ref)
        .map((item: any) => {
          const className = item.$ref.split('/').pop() || '';
          const matchingClass = availableClasses.find(c => c.name === className);
          return matchingClass?.id;
        })
        .filter(Boolean);
      setRefTargetClassIds(classIds);
    } else if (refSchema.anyOf && Array.isArray(refSchema.anyOf)) {
      // Check if this is a nullable reference (anyOf with null type)
      const hasNullType = refSchema.anyOf.some((item: any) => item.type === 'null');
      const refItems = refSchema.anyOf.filter((item: any) => item.$ref);
      if (hasNullType && refItems.length === 1) {
        // This is a nullable single reference
        setRefCompositionType('none');
        const refClassName = refItems[0].$ref.split('/').pop() || '';
        const matchingClass = availableClasses.find(c => c.name === refClassName);
        setRefTargetClassId(matchingClass?.id || '');
        setRefTargetClassIds([]);
      } else {
        setRefCompositionType('anyOf');
        setRefTargetClassId('');
        const classIds = refItems
          .map((item: any) => {
            const className = item.$ref.split('/').pop() || '';
            const matchingClass = availableClasses.find(c => c.name === className);
            return matchingClass?.id;
          })
          .filter(Boolean);
        setRefTargetClassIds(classIds);
      }
    } else if (refSchema.oneOf && Array.isArray(refSchema.oneOf)) {
      // Check if this is a nullable reference (oneOf with null type)
      const hasNullType = refSchema.oneOf.some((item: any) => item.type === 'null');
      const refItems = refSchema.oneOf.filter((item: any) => item.$ref);
      if (hasNullType && refItems.length === 1) {
        // This is a nullable single reference
        setRefCompositionType('none');
        const refClassName = refItems[0].$ref.split('/').pop() || '';
        const matchingClass = availableClasses.find(c => c.name === refClassName);
        setRefTargetClassId(matchingClass?.id || '');
        setRefTargetClassIds([]);
      } else {
        setRefCompositionType('oneOf');
        setRefTargetClassId('');
        const classIds = refItems
          .map((item: any) => {
            const className = item.$ref.split('/').pop() || '';
            const matchingClass = availableClasses.find(c => c.name === className);
            return matchingClass?.id;
          })
          .filter(Boolean);
        setRefTargetClassIds(classIds);
      }
    } else {
      // Default - no reference
      setRefCompositionType('none');
      setRefTargetClassId('');
      setRefTargetClassIds([]);
    }

    setEditPropertyError('');
  }, [editingClassProperty, availableClasses]);

  const handleSave = async () => {
    if (!editingClassProperty) {
      setEditPropertyError('No property selected for editing');
      return;
    }

    if (!editPropName.trim()) {
      setEditPropertyError('Property name is required');
      return;
    }

    setIsSaving(true);
    try {
      const originalData = typeof editingClassProperty.data === 'string'
        ? JSON.parse(editingClassProperty.data)
        : (editingClassProperty.data || {});

      const updatedData: any = {
        ...originalData,
        required: formData.required,
        deprecated: formData.deprecated,
        readOnly: formData.readOnly,
        writeOnly: formData.writeOnly,
      };

      // Handle deprecationMessage
      if (formData.deprecated && formData.deprecationMessage?.trim()) {
        updatedData.deprecationMessage = formData.deprecationMessage.trim();
      } else {
        delete updatedData.deprecationMessage;
      }

      if (formData.examples && formData.examples.length > 0) {
        try {
          updatedData.examples = formData.examples.map((ex: string) => JSON.parse(ex));
        } catch (e) {
          updatedData.examples = formData.examples;
        }
      } else {
        delete updatedData.examples;
      }

      // Handle nullable - update type to be an array with 'null' (OpenAPI 3.1 style)
      // For properties with $ref, we need to use oneOf with null instead
      // For properties with type, we use type array like ['string', 'null']

      // Check if this is a reference type (has $ref at top level or in items for arrays)
      const hasDirectRef = updatedData.$ref && !updatedData.type;

      if (hasDirectRef) {
        // For direct references like { $ref: '...' }, use oneOf pattern for nullable
        if (formData.nullable) {
          // Convert to oneOf: [{ $ref: '...' }, { type: 'null' }]
          const refValue = updatedData.$ref;
          delete updatedData.$ref;
          updatedData.oneOf = [
            { $ref: refValue },
            { type: 'null' }
          ];
        } else {
          // If there's a oneOf with null, convert back to simple $ref
          if (updatedData.oneOf && Array.isArray(updatedData.oneOf)) {
            const refItem = updatedData.oneOf.find((item: any) => item.$ref);
            if (refItem) {
              delete updatedData.oneOf;
              updatedData.$ref = refItem.$ref;
            }
          }
        }
      } else {
        // For regular types (string, number, object, array, etc.)
        let currentBaseType = updatedData.type;
        if (Array.isArray(updatedData.type)) {
          currentBaseType = updatedData.type.find((t: string) => t !== 'null');
        }

        // Only set type if we have a valid base type
        if (currentBaseType) {
          if (formData.nullable) {
            updatedData.type = [currentBaseType, 'null'];
          } else {
            updatedData.type = currentBaseType;
          }
        }
      }

      // Determine where to apply constraints (array items vs direct)
      let currentBaseType = updatedData.type;
      if (Array.isArray(updatedData.type)) {
        currentBaseType = updatedData.type.find((t: string) => t !== 'null');
      }
      const isArray = currentBaseType === 'array';
      const targetSchema = isArray ? (updatedData.items || {}) : updatedData;

      // Handle additionalProperties field (apply to direct object or array items object)
      if (formData.additionalProperties === 'true') {
        targetSchema.additionalProperties = true;
      } else if (formData.additionalProperties === 'false') {
        targetSchema.additionalProperties = false;
      } else if (formData.additionalProperties === 'type' && formData.additionalPropertiesType) {
        targetSchema.additionalProperties = { type: formData.additionalPropertiesType };
      } else if (formData.additionalProperties === 'schema' && formData.additionalPropertiesSchema) {
        const schemaValue = formData.additionalPropertiesSchema.trim();
        if (schemaValue.startsWith('{')) {
          try {
            targetSchema.additionalProperties = JSON.parse(schemaValue);
          } catch {
            targetSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
          }
        } else if (schemaValue.startsWith('#/') || schemaValue.startsWith('$ref')) {
          targetSchema.additionalProperties = { $ref: schemaValue };
        } else {
          targetSchema.additionalProperties = { $ref: `#/components/schemas/${schemaValue}` };
        }
      } else {
        delete targetSchema.additionalProperties;
      }

      // Handle minProperties and maxProperties for objects
      if (formData.minProperties) {
        targetSchema.minProperties = parseInt(formData.minProperties);
      } else {
        delete targetSchema.minProperties;
      }
      if (formData.maxProperties) {
        targetSchema.maxProperties = parseInt(formData.maxProperties);
      } else {
        delete targetSchema.maxProperties;
      }

      // Handle patternProperties
      if (formData.patternProperties && Object.keys(formData.patternProperties).length > 0) {
        targetSchema.patternProperties = formData.patternProperties;
      } else {
        delete targetSchema.patternProperties;
      }

      // Handle dependentSchemas (JSON Schema 2019-09+)
      if (formData.dependentSchemas && Object.keys(formData.dependentSchemas).length > 0) {
        targetSchema.dependentSchemas = formData.dependentSchemas;
      } else {
        delete targetSchema.dependentSchemas;
      }

      // Handle unevaluatedProperties (OpenAPI 3.1/JSON Schema 2020-12) - for objects
      if (formData.unevaluatedProperties === 'allow') {
        targetSchema.unevaluatedProperties = true;
      } else if (formData.unevaluatedProperties === 'disallow') {
        targetSchema.unevaluatedProperties = false;
      } else if (formData.unevaluatedProperties === 'schema' && formData.unevaluatedPropertiesSchema?.trim()) {
        try {
          targetSchema.unevaluatedProperties = JSON.parse(formData.unevaluatedPropertiesSchema);
        } catch (e) {
          // If not valid JSON, treat as a simple type
          targetSchema.unevaluatedProperties = { type: formData.unevaluatedPropertiesSchema };
        }
      } else {
        delete targetSchema.unevaluatedProperties;
      }

      // Handle propertyNames constraints (OpenAPI 3.1)
      const hasPropertyNamesConstraints = formData.propertyNamesPattern || formData.propertyNamesMinLength || formData.propertyNamesMaxLength || formData.propertyNamesFormat || formData.propertyNamesDescription;
      if (hasPropertyNamesConstraints) {
        targetSchema.propertyNames = { type: 'string' };
        if (formData.propertyNamesPattern) {
          targetSchema.propertyNames.pattern = formData.propertyNamesPattern;
        }
        if (formData.propertyNamesMinLength) {
          targetSchema.propertyNames.minLength = parseInt(formData.propertyNamesMinLength);
        }
        if (formData.propertyNamesMaxLength) {
          targetSchema.propertyNames.maxLength = parseInt(formData.propertyNamesMaxLength);
        }
        if (formData.propertyNamesFormat) {
          targetSchema.propertyNames.format = formData.propertyNamesFormat;
        }
        if (formData.propertyNamesDescription) {
          targetSchema.propertyNames.description = formData.propertyNamesDescription;
        }
      } else {
        delete targetSchema.propertyNames;
      }

      // String constraints
      if (formData.minLength) targetSchema.minLength = parseInt(formData.minLength);
      else delete targetSchema.minLength;

      if (formData.maxLength) targetSchema.maxLength = parseInt(formData.maxLength);
      else delete targetSchema.maxLength;

      if (formData.pattern) targetSchema.pattern = formData.pattern;
      else delete targetSchema.pattern;

      if (formData.format) targetSchema.format = formData.format;
      else delete targetSchema.format;

      // Number constraints - OpenAPI 3.1 style (numeric exclusive values)
      if (formData.minimum && formData.minimum.trim()) {
        const minValue = parseFloat(formData.minimum);
        if (!isNaN(minValue)) {
          if (formData.minimumType === 'exclusive') {
            targetSchema.exclusiveMinimum = minValue;
            delete targetSchema.minimum;
          } else {
            targetSchema.minimum = minValue;
            delete targetSchema.exclusiveMinimum;
          }
        }
      } else {
        delete targetSchema.minimum;
        delete targetSchema.exclusiveMinimum;
      }

      if (formData.maximum && formData.maximum.trim()) {
        const maxValue = parseFloat(formData.maximum);
        if (!isNaN(maxValue)) {
          if (formData.maximumType === 'exclusive') {
            targetSchema.exclusiveMaximum = maxValue;
            delete targetSchema.maximum;
          } else {
            targetSchema.maximum = maxValue;
            delete targetSchema.exclusiveMaximum;
          }
        }
      } else {
        delete targetSchema.maximum;
        delete targetSchema.exclusiveMaximum;
      }

      if (formData.multipleOf && formData.multipleOf.trim()) {
        const multipleOfValue = parseFloat(formData.multipleOf);
        if (!isNaN(multipleOfValue) && multipleOfValue > 0) {
          targetSchema.multipleOf = multipleOfValue;
        }
      } else {
        delete targetSchema.multipleOf;
      }

      // Array constraints (on array itself, not items)
      if (isArray) {
        if (formData.minItems) updatedData.minItems = parseInt(formData.minItems);
        else delete updatedData.minItems;

        if (formData.maxItems) updatedData.maxItems = parseInt(formData.maxItems);
        else delete updatedData.maxItems;

        if (formData.uniqueItems) updatedData.uniqueItems = true;
        else delete updatedData.uniqueItems;

        // Handle contains schema (OpenAPI 3.1)
        if (formData.contains && formData.contains.trim()) {
          try {
            updatedData.contains = JSON.parse(formData.contains);
          } catch (e) {
            // If not valid JSON, treat as a simple type string
            updatedData.contains = { type: formData.contains };
          }

          // Handle minContains and maxContains (only valid when contains is set)
          if (formData.minContains) {
            const minContainsValue = parseInt(formData.minContains);
            if (!isNaN(minContainsValue) && minContainsValue >= 1) {
              updatedData.minContains = minContainsValue;
            }
          } else {
            delete updatedData.minContains;
          }

          if (formData.maxContains) {
            const maxContainsValue = parseInt(formData.maxContains);
            if (!isNaN(maxContainsValue) && maxContainsValue >= 1) {
              updatedData.maxContains = maxContainsValue;
            }
          } else {
            delete updatedData.maxContains;
          }
        } else {
          delete updatedData.contains;
          delete updatedData.minContains;
          delete updatedData.maxContains;
        }

        // Handle Tuple Mode (OpenAPI 3.1 prefixItems)
        if (formData.tupleMode && formData.prefixItems && formData.prefixItems.length > 0) {
          updatedData.prefixItems = formData.prefixItems;

          // Handle items schema for positions beyond prefix
          if (formData.itemsSchema && formData.itemsSchema.trim()) {
            try {
              updatedData.items = JSON.parse(formData.itemsSchema);
            } catch (e) {
              // If not valid JSON, treat as boolean or simple type
              updatedData.items = formData.itemsSchema === 'true' ? true :
                                  formData.itemsSchema === 'false' ? false :
                                  { type: formData.itemsSchema };
            }
          } else {
            // Default to allowing any type for items beyond prefix
            updatedData.items = true;
          }
        } else {
          // Not in tuple mode - delete prefixItems if present
          delete updatedData.prefixItems;
        }

        // Handle unevaluatedItems (OpenAPI 3.1/JSON Schema 2020-12)
        if (formData.unevaluatedItems === 'allow') {
          updatedData.unevaluatedItems = true;
        } else if (formData.unevaluatedItems === 'disallow') {
          updatedData.unevaluatedItems = false;
        } else if (formData.unevaluatedItems === 'schema' && formData.unevaluatedItemsSchema?.trim()) {
          try {
            updatedData.unevaluatedItems = JSON.parse(formData.unevaluatedItemsSchema);
          } catch (e) {
            // If not valid JSON, treat as a simple type
            updatedData.unevaluatedItems = { type: formData.unevaluatedItemsSchema };
          }
        } else {
          delete updatedData.unevaluatedItems;
        }
      }

      // Enum values and const (mutually exclusive)
      if (formData.const && formData.const.trim()) {
        try {
          targetSchema.const = JSON.parse(formData.const);
        } catch (e) {
          // If not valid JSON, use as string
          targetSchema.const = formData.const;
        }
        delete targetSchema.enum;
      } else {
        delete targetSchema.const;
        if (formData.enum && formData.enum.length > 0) {
          targetSchema.enum = formData.enum;
        } else {
          delete targetSchema.enum;
        }
      }

      // Default value
      if (formData.default?.trim()) {
        try {
          targetSchema.default = JSON.parse(formData.default);
        } catch (e) {
          targetSchema.default = formData.default;
        }
      } else {
        delete targetSchema.default;
      }

      // NOT composition (OpenAPI 3.1)
      if (formData.not && formData.not.trim()) {
        try {
          targetSchema.not = JSON.parse(formData.not);
        } catch (e) {
          // If not valid JSON, treat as a simple type
          targetSchema.not = { type: formData.not };
        }
      } else {
        delete targetSchema.not;
      }

      // Update items if it's an array (but not if tuple mode is active - already set above)
      if (isArray && !formData.tupleMode) {
        updatedData.items = targetSchema;
        // Ensure additionalProperties isn't left on the array level
        delete updatedData.additionalProperties;
      }

      // Handle XML Object (OpenAPI 3.1)
      const hasXml = formData.xmlName || formData.xmlNamespace || formData.xmlPrefix || formData.xmlAttribute || formData.xmlWrapped;
      if (hasXml) {
        updatedData.xml = {};
        if (formData.xmlName) updatedData.xml.name = formData.xmlName;
        if (formData.xmlNamespace) updatedData.xml.namespace = formData.xmlNamespace;
        if (formData.xmlPrefix) updatedData.xml.prefix = formData.xmlPrefix;
        if (formData.xmlAttribute) updatedData.xml.attribute = formData.xmlAttribute;
        if (formData.xmlWrapped) updatedData.xml.wrapped = formData.xmlWrapped;
      } else {
        delete updatedData.xml;
      }

      // Handle Content Media Type fields (for binary/byte strings)
      if (formData.contentMediaType) {
        updatedData.contentMediaType = formData.contentMediaType;
      } else {
        delete updatedData.contentMediaType;
      }
      if (formData.contentEncoding) {
        updatedData.contentEncoding = formData.contentEncoding;
      } else {
        delete updatedData.contentEncoding;
      }
      if (formData.contentSchema && formData.contentSchema.trim()) {
        try {
          updatedData.contentSchema = JSON.parse(formData.contentSchema);
        } catch (e) {
          updatedData.contentSchema = { type: formData.contentSchema };
        }
      } else {
        delete updatedData.contentSchema;
      }

      // Handle $comment (JSON Schema 2020-12)
      if (formData.$comment) {
        updatedData.$comment = formData.$comment;
      } else {
        delete updatedData.$comment;
      }

      // Handle extensions (x- prefixed properties)
      // First, remove any existing x- properties from updatedData
      Object.keys(updatedData).forEach(key => {
        if (key.startsWith('x-')) {
          delete updatedData[key];
        }
      });
      // Then merge in the current extensions
      if (formData.extensions && Object.keys(formData.extensions).length > 0) {
        Object.assign(updatedData, formData.extensions);
      }

      if (formData.owner?.trim()) {
        updatedData['x-owner'] = formData.owner.trim();
      } else {
        delete updatedData['x-owner'];
      }

      // Handle externalDocs
      if (formData.externalDocsUrl?.trim()) {
        updatedData.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription?.trim()) {
          updatedData.externalDocs.description = formData.externalDocsDescription.trim();
        }
      } else {
        delete updatedData.externalDocs;
      }

      // Handle reference properties specially
      const originalSchema = isArray ? (originalData.items || {}) : originalData;
      const isReferenceType = originalSchema.$ref ||
        (originalSchema.allOf && Array.isArray(originalSchema.allOf) && originalSchema.allOf.some((item: any) => item.$ref)) ||
        (originalSchema.anyOf && Array.isArray(originalSchema.anyOf) && originalSchema.anyOf.some((item: any) => item.$ref)) ||
        (originalSchema.oneOf && Array.isArray(originalSchema.oneOf) && originalSchema.oneOf.some((item: any) => item.$ref));

      if (isReferenceType) {
        // Build the reference schema based on user selections
        let newRefSchema: any = {};

        if (refCompositionType === 'none') {
          // Single reference
          if (refTargetClassId) {
            const targetClass = availableClasses.find(c => c.id === refTargetClassId);
            if (targetClass) {
              newRefSchema = { $ref: `#/components/schemas/${targetClass.name}` };
            }
          } else {
            // Keep existing $ref if no new class selected
            if (originalSchema.$ref) {
              newRefSchema = { $ref: originalSchema.$ref };
            } else if (originalSchema.oneOf) {
              const refItem = originalSchema.oneOf.find((item: any) => item.$ref);
              if (refItem) {
                newRefSchema = { $ref: refItem.$ref };
              }
            }
          }
        } else {
          // Composition type (allOf, anyOf, oneOf)
          const refs = refTargetClassIds
            .map(classId => {
              const targetClass = availableClasses.find(c => c.id === classId);
              return targetClass ? { $ref: `#/components/schemas/${targetClass.name}` } : null;
            })
            .filter(Boolean);

          if (refs.length > 0) {
            newRefSchema = { [refCompositionType]: refs };
          } else {
            // Keep existing composition if no classes selected
            if (originalSchema[refCompositionType]) {
              newRefSchema = { [refCompositionType]: originalSchema[refCompositionType] };
            }
          }
        }

        // Handle nullable for references
        if (formData.nullable && newRefSchema.$ref) {
          // Convert single ref to oneOf with null
          newRefSchema = {
            oneOf: [
              { $ref: newRefSchema.$ref },
              { type: 'null' }
            ]
          };
        }

        // Build the final updated data for references
        if (refIsArray) {
          // Array of references
          updatedData.type = 'array';
          updatedData.items = newRefSchema;

          // Array constraints
          if (refMinItems) updatedData.minItems = parseInt(refMinItems);
          else delete updatedData.minItems;

          if (refMaxItems) updatedData.maxItems = parseInt(refMaxItems);
          else delete updatedData.maxItems;

          if (refUniqueItems) updatedData.uniqueItems = true;
          else delete updatedData.uniqueItems;

          // Clean up top-level ref properties
          delete updatedData.$ref;
          delete updatedData.allOf;
          delete updatedData.anyOf;
          delete updatedData.oneOf;
        } else {
          // Single reference (not array)
          delete updatedData.type;
          delete updatedData.items;
          delete updatedData.minItems;
          delete updatedData.maxItems;
          delete updatedData.uniqueItems;

          // Apply the reference schema
          Object.assign(updatedData, newRefSchema);
        }

        // Set description for reference
        if (refDescription?.trim()) {
          updatedData.description = refDescription.trim();
        }
      }

      // Update via REST API
      const response = await fetch(`/api/classes/${editingClassProperty.class_id}/properties/${editingClassProperty.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editPropName.trim(),
          description: formData.description || null,
          data: updatedData,
          // Persist the type-registry binding (#3475) as dedicated columns: the
          // resolved primitive id (FK) and the stored registry $ref. Sent as
          // null when unbound/cleared so the binding can be removed.
          primitive_id: formData.primitive_id || null,
          primitive_ref: formData.$ref || null,
        }),
      });

      const result = await response.json();
      if (result.success) {
        // Notify parent to reload
        if (onSaved) await onSaved();
        onClose();
      } else {
        setEditPropertyError(result.error || 'Failed to update property');
      }
    } catch (error) {
      console.error('Error updating class property:', error);
      setEditPropertyError('An error occurred while updating the property');
    } finally {
      setIsSaving(false);
    }
  };

  // ─── Derived state for the rewritten render ─────────────────────────────
  const typeInfo = getPropertyTypeInfo();
  const propData = editingClassProperty
    ? typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {})
    : {};
  const schema = typeInfo.isArray ? (propData.items || {}) : propData;
  const baseType = schema.$ref ? 'reference' : (schema.type || 'object');
  const isReferenceType = Boolean(
    schema.$ref ||
      (schema.allOf && Array.isArray(schema.allOf) && schema.allOf.some((item: any) => item.$ref)) ||
      (schema.anyOf && Array.isArray(schema.anyOf) && schema.anyOf.some((item: any) => item.$ref)) ||
      (schema.oneOf && Array.isArray(schema.oneOf) && schema.oneOf.some((item: any) => item.$ref)),
  );
  const primitiveAvailable =
    !isReferenceType &&
    ['string', 'number', 'integer', 'array'].includes(baseType) &&
    !formData.tupleMode;

  const changedBasics = Boolean((formData.description || '').trim()) || editPropName.trim() !== (editingClassProperty?.name || '').trim();
  const changedFlags =
    Boolean(formData.required) ||
    Boolean(formData.nullable) ||
    Boolean(formData.readOnly) ||
    Boolean(formData.writeOnly) ||
    Boolean(formData.deprecated) ||
    Boolean(formData.deprecationMessage?.trim()) ||
    Boolean(formData.owner?.trim());
  const changedDefaults = Boolean(formData.default?.trim()) || Boolean(formData.const?.trim());
  const changedDocs =
    Boolean(formData.externalDocsUrl?.trim()) || Boolean(formData.externalDocsDescription?.trim());

  const navItems: FormSectionNavItem[] = [
    { id: 'basics', label: 'Basics', icon: <FileText className="h-3.5 w-3.5" />, changed: changedBasics },
    { id: 'flags', label: 'Flags & Ownership', icon: <Settings className="h-3.5 w-3.5" />, changed: changedFlags },
    { id: 'defaults', label: 'Defaults & Constants', icon: <Code className="h-3.5 w-3.5" />, changed: changedDefaults },
    { id: 'constraints', label: 'Advanced Constraints', icon: <ListChecks className="h-3.5 w-3.5" /> },
    { id: 'docs', label: 'Documentation', icon: <BookOpenText className="h-3.5 w-3.5" />, changed: changedDocs },
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
    disabled: isReferenceType || viewMode !== 'advanced',
  });

  const handleNextStep = () => {
    setCurrentStepIndex((i) => Math.min(i + 1, wizardSteps.length - 1));
  };
  const handlePrevStep = () => {
    setCurrentStepIndex((i) => Math.max(i - 1, 0));
  };

  const propertySchemaForAiDescription = useMemo(() => {
    if (!editingClassProperty?.data) return {};
    try {
      const raw =
        typeof editingClassProperty.data === 'string'
          ? JSON.parse(editingClassProperty.data)
          : editingClassProperty.data;
      return summarizeStoredPropertyData(raw);
    } catch {
      return {};
    }
  }, [editingClassProperty?.data]);

  const nestedMembersForExampleAi = useMemo(() => {
    if (!editingClassProperty?.id || baseType !== 'object') return undefined;
    return (allClassProperties || [])
      .filter((p) => p.parent_id === editingClassProperty.id)
      .map((p) => ({
        name: p.name,
        description: p.description ?? null,
      }));
  }, [allClassProperties, editingClassProperty?.id, baseType]);

  const classMemberDescriptionAiSlot =
    open && propertyAiContext && editingClassProperty ? (
      <PropertyDescriptionAiButton
        tenantId={propertyAiContext.tenantId}
        projectId={propertyAiContext.projectId}
        versionId={propertyAiContext.versionId}
        propertyName={editPropName}
        propertySchema={propertySchemaForAiDescription}
        contextClassName={propertyAiContext.contextClassName}
        existingClasses={propertyAiContext.existingClasses}
        existingProperties={propertyAiContext.existingProperties}
        studioContext={propertyAiContext.studioContext}
        onGenerated={(text) => setFormData((prev) => ({ ...prev, description: text }))}
        disabled={!editPropName.trim()}
      />
    ) : null;

  const classMemberExampleAiSlot =
    open && propertyAiContext && editingClassProperty ? (
      <PropertyExampleAiButton
        tenantId={propertyAiContext.tenantId}
        projectId={propertyAiContext.projectId}
        versionId={propertyAiContext.versionId}
        propertyName={editPropName}
        propertySchema={propertySchemaForAiDescription}
        propertyDescription={formData.description}
        nestedMembers={nestedMembersForExampleAi}
        contextClassName={propertyAiContext.contextClassName}
        existingClasses={propertyAiContext.existingClasses}
        existingProperties={propertyAiContext.existingProperties}
        studioContext={propertyAiContext.studioContext}
        onGenerated={(jsonLine) =>
          setFormData((prev) => ({
            ...prev,
            examples: [...(prev.examples || []), jsonLine],
          }))
        }
        disabled={!editPropName.trim()}
      />
    ) : null;

  const guidedSection = (id: string) => {
    switch (id) {
      case 'basics':
        return (
          <BasicsSection
            editPropName={editPropName}
            setEditPropName={setEditPropName}
            formData={formData}
            setFormData={setFormData}
            typeInfoLabel={typeInfo.type}
            hasRef={!!typeInfo.hasRef}
            propertyType={baseType}
            primitiveAvailable={primitiveAvailable}
            descriptionAiSlot={classMemberDescriptionAiSlot}
            changed={changedBasics}
            eyebrow="Step 1 · Basics"
          />
        );
      case 'flags':
        return (
          <FlagsSection
            formData={formData}
            setFormData={setFormData}
            changed={changedFlags}
            eyebrow="Step 2 · Flags & Ownership"
          />
        );
      case 'defaults':
        return (
          <DefaultsSection
            formData={formData}
            setFormData={setFormData}
            changed={changedDefaults}
            eyebrow="Step 3 · Defaults"
          />
        );
      case 'constraints':
        return (
          <ConstraintsSection
            baseType={baseType}
            isArray={typeInfo.isArray}
            formData={formData}
            setFormData={setFormData}
            nestedProperties={
              baseType === 'object' && editingClassProperty
                ? (allClassProperties || []).filter((p) => p.parent_id === editingClassProperty.id)
                : undefined
            }
            availableClasses={existingClassNames}
            examplesAiSlot={classMemberExampleAiSlot}
            eyebrow="Step 4 · Constraints"
          />
        );
      case 'docs':
        return (
          <DocsSection
            formData={formData}
            setFormData={setFormData}
            changed={changedDocs}
            eyebrow="Step 5 · Documentation"
          />
        );
      default:
        return null;
    }
  };

  const allSections = (
    <>
      <BasicsSection
        editPropName={editPropName}
        setEditPropName={setEditPropName}
        formData={formData}
        setFormData={setFormData}
        typeInfoLabel={typeInfo.type}
        hasRef={!!typeInfo.hasRef}
        propertyType={baseType}
        primitiveAvailable={primitiveAvailable}
        descriptionAiSlot={classMemberDescriptionAiSlot}
        changed={changedBasics}
      />
      <FlagsSection formData={formData} setFormData={setFormData} changed={changedFlags} />
      <DefaultsSection formData={formData} setFormData={setFormData} changed={changedDefaults} />
      <ConstraintsSection
        baseType={baseType}
        isArray={typeInfo.isArray}
        formData={formData}
        setFormData={setFormData}
        nestedProperties={
          baseType === 'object' && editingClassProperty
            ? (allClassProperties || []).filter((p) => p.parent_id === editingClassProperty.id)
            : undefined
        }
        availableClasses={existingClassNames}
        examplesAiSlot={classMemberExampleAiSlot}
      />
      <DocsSection formData={formData} setFormData={setFormData} changed={changedDocs} />
    </>
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()} modal={true}>
      <DialogContent
        className="max-w-6xl h-[90vh] max-h-[900px] p-0 flex flex-col overflow-hidden"
        showCloseButton={true}
        aria-describedby={undefined}
      >
        <DialogHeader className="shrink-0 border-b border-slate-200 bg-slate-50/60 px-6 py-4 dark:border-slate-800 dark:bg-slate-900/60">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="flex min-w-0 items-center gap-3">
              <span
                className={
                  'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ' +
                  (isReferenceType
                    ? 'bg-purple-100 text-purple-500 dark:bg-purple-900/40 dark:text-purple-300'
                    : 'bg-indigo-100 text-indigo-500 dark:bg-indigo-900/40 dark:text-indigo-300')
                }
              >
                {isReferenceType ? <GitBranch className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
              </span>
              <div className="min-w-0">
                <DialogTitle className="text-base font-semibold leading-5">
                  Edit Property in Class
                </DialogTitle>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {isReferenceType
                    ? 'Configure how this property references other classes.'
                    : 'Update identity, flags, and validation rules for this member.'}
                </p>
              </div>
              {editingClassProperty?.name && (
                <code className="ml-1 hidden rounded bg-slate-200/70 px-2 py-0.5 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300 sm:inline-flex">
                  {editingClassProperty.name}
                </code>
              )}
            </div>
            {!isReferenceType && (
              <FormViewModeToggle value={viewMode} onChange={setViewMode} />
            )}
          </div>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col">
          {editPropertyError && (
            <Alert variant="error" className="m-4 mb-0">
              {editPropertyError}
            </Alert>
          )}

          {isReferenceType ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <ReferenceSection
                refDescription={refDescription}
                setRefDescription={setRefDescription}
                refIsArray={refIsArray}
                setRefIsArray={setRefIsArray}
                refCompositionType={refCompositionType}
                setRefCompositionType={setRefCompositionType}
                refTargetClassId={refTargetClassId}
                setRefTargetClassId={setRefTargetClassId}
                refTargetClassIds={refTargetClassIds}
                setRefTargetClassIds={setRefTargetClassIds}
                refMinItems={refMinItems}
                setRefMinItems={setRefMinItems}
                refMaxItems={refMaxItems}
                setRefMaxItems={setRefMaxItems}
                refUniqueItems={refUniqueItems}
                setRefUniqueItems={setRefUniqueItems}
                formData={formData}
                setFormData={setFormData}
                availableClasses={availableClasses}
              />
            </div>
          ) : viewMode === 'guided' ? (
            <>
              <FormWizardStepper
                steps={wizardSteps}
                currentIndex={currentStepIndex}
                onStepSelect={setCurrentStepIndex}
              />
              <div className="min-h-0 flex-1 overflow-y-auto">{guidedSection(currentWizardSection)}</div>
              <FormWizardControls
                currentIndex={currentStepIndex}
                stepCount={wizardSteps.length}
                onBack={handlePrevStep}
                onNext={handleNextStep}
                onCancel={onClose}
                onFinish={handleSave}
                finishLabel="Save"
                finishBusy={isSaving}
                leading={
                  canExtractToClass() ? (
                    <Button
                      onClick={() => setExtractDialogOpen(true)}
                      variant="outline"
                      size="sm"
                      className="gap-2"
                    >
                      <GitBranch size={14} />
                      Extract to Class
                    </Button>
                  ) : undefined
                }
              />
            </>
          ) : (
            <div className="flex min-h-0 flex-1">
              <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-900/40 lg:block">
                <FormSectionNav
                  items={navItems}
                  activeId={activeId}
                  onSelect={(id) => scrollToSection(advancedScrollRef.current, id)}
                />
              </aside>
              <div ref={advancedScrollRef} className="min-h-0 flex-1 overflow-y-auto">
                {allSections}
              </div>
            </div>
          )}
        </div>

        {!(viewMode === 'guided' && !isReferenceType) && (
          <DialogFooter className="shrink-0 border-t border-slate-200 px-6 py-4 dark:border-slate-800">
            <div className="flex w-full items-center justify-between gap-3">
              <div>
                {canExtractToClass() && (
                  <Button
                    onClick={() => setExtractDialogOpen(true)}
                    variant="outline"
                    className="gap-2"
                  >
                    <GitBranch size={16} />
                    Extract to Class
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button onClick={handleSave} disabled={isSaving}>
                  {isSaving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
          </DialogFooter>
        )}
      </DialogContent>

      {/* Extract to Class Dialog */}
      <ExtractToClassDialog
        open={extractDialogOpen}
        onClose={() => setExtractDialogOpen(false)}
        classProperty={editingClassProperty}
        existingClassNames={existingClassNames}
        onSuccess={handleExtractSuccess}
      />
    </Dialog>
  );
}

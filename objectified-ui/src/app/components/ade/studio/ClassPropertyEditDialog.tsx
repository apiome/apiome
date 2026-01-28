'use client';

import { useEffect, useState } from 'react';
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
import { PropertyFormFields, PropertyFormData } from './PropertyFormFields';
import { PrimitiveSelector } from './PrimitiveSelector';
import ExtractToClassDialog from './ExtractToClassDialog';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import {
  GitBranch,
  FileText,
  Settings,
  Code,
  AlertTriangle,
  Info,
  ExternalLink,
  Sparkles,
} from 'lucide-react';

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
}

export default function ClassPropertyEditDialog({ open, onClose, editingClassProperty, onSaved, allClassProperties, existingClassNames = [], availableClasses = [] }: Props) {
  const isDark = useDarkMode();
  const [editPropName, setEditPropName] = useState('');
  const [editPropertyError, setEditPropertyError] = useState('');
  const [extractDialogOpen, setExtractDialogOpen] = useState(false);

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

    // Extract extensions (x- prefixed properties) from the property data
    const extensions: Record<string, any> = {};
    Object.keys(propData).forEach(key => {
      if (key.startsWith('x-')) {
        extensions[key] = propData[key];
      }
    });

    // Populate form data
    setFormData({
      description: editingClassProperty.description || '',
      required: !!propData.required,
      nullable: isNullable,
      deprecated: !!propData.deprecated,
      deprecationMessage: propData.deprecationMessage || '',
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
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()} modal={true}>
      <DialogContent
        className="max-w-6xl h-[90vh] max-h-[900px] p-0 flex flex-col overflow-hidden"
        showCloseButton={true}
        aria-describedby={undefined}
      >
        <DialogHeader className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <DialogTitle className="text-lg font-semibold">
                Edit Property in Class
              </DialogTitle>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 flex flex-col overflow-hidden">
          {editPropertyError && (
            <Alert variant="error" className="m-4 mb-0">
              {editPropertyError}
            </Alert>
          )}

          <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-0 divide-x divide-gray-200 dark:divide-gray-700 overflow-hidden min-h-0">
            {/* LEFT COLUMN - Basic Configuration */}
            <div className="flex flex-col overflow-y-auto min-h-0">
              {/* SECTION 1: Property Information */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 mb-4">
                  <FileText size={18} className="text-indigo-500" />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Property Information</h3>
                </div>

                {/* Info Alert */}
                <div className="mb-4 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
                  <div className="flex items-start gap-2">
                    <Info size={16} className="text-blue-500 mt-0.5 shrink-0" />
                    <p className="text-sm text-blue-700 dark:text-blue-300">
                      When editing a property that is a member of a class, only the name and constraints can be modified. The type is read-only.
                    </p>
                  </div>
                </div>

                {/* Type Information - Read Only */}
                {editingClassProperty && (
                  <div className={`mb-4 p-4 rounded-lg border ${isDark ? 'bg-slate-800 border-gray-700' : 'bg-gray-50 border-gray-200'}`}>
                    <Label className="text-sm font-semibold mb-2 block">Property Type (Read-Only)</Label>
                    <div className="flex gap-2 items-center">
                      <Badge variant="secondary" className="font-mono text-sm px-3 py-1">
                        {getPropertyTypeInfo().type}
                      </Badge>
                      {getPropertyTypeInfo().hasRef && (
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          (References another class)
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* Property Name */}
                <div className="space-y-2">
                  <Label htmlFor="propertyName">Property Name *</Label>
                  <Input
                    id="propertyName"
                    autoFocus
                    value={editPropName}
                    onChange={(e) => setEditPropName(e.target.value)}
                    placeholder="e.g., userName"
                  />
                  <p className="text-xs text-gray-500">camelCase recommended</p>
                </div>

                {/* Description */}
                {editingClassProperty && (() => {
                  const typeInfo = getPropertyTypeInfo();
                  const propData = typeof editingClassProperty.data === 'string'
                    ? JSON.parse(editingClassProperty.data)
                    : (editingClassProperty.data || {});
                  const schema = typeInfo.isArray ? (propData.items || {}) : propData;

                  // Only show for non-reference types
                  if (schema.$ref) return null;

                  return (
                    <div className="mt-4 space-y-2">
                      <Label htmlFor="description">Description</Label>
                      <Textarea
                        id="description"
                        value={formData.description || ''}
                        onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                        placeholder="Brief description of this property"
                        rows={2}
                      />
                    </div>
                  );
                })()}
              </div>

              {/* Apply from Primitive - Only show for applicable types */}
              {editingClassProperty && (() => {
                const typeInfo = getPropertyTypeInfo();
                const propData = typeof editingClassProperty.data === 'string'
                  ? JSON.parse(editingClassProperty.data)
                  : (editingClassProperty.data || {});
                const schema = typeInfo.isArray ? (propData.items || {}) : propData;
                const baseType = schema.$ref ? 'reference' : (schema.type || 'object');

                // Only show for applicable types (string, number, integer, array) and non-reference
                if (schema.$ref) return null;
                if (!['string', 'number', 'integer', 'array'].includes(baseType)) return null;
                if (formData.tupleMode) return null;

                return (
                  <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                    <div className={`p-4 rounded-lg border ${isDark ? 'bg-indigo-900/10 border-indigo-700/30' : 'bg-indigo-50/50 border-indigo-200'}`}>
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-start gap-3">
                          <div className={`p-2 rounded-lg ${isDark ? 'bg-indigo-900/30' : 'bg-indigo-100'}`}>
                            <Sparkles size={18} className="text-indigo-500" />
                          </div>
                          <div>
                            <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-0.5">
                              Apply from Primitive
                            </h4>
                            <p className="text-xs text-gray-500 dark:text-gray-400">
                              Quickly apply format, pattern, and constraints from a predefined primitive type
                            </p>
                          </div>
                        </div>
                        <PrimitiveSelector
                          formData={formData}
                          onChange={(field, value) => setFormData(prev => ({ ...prev, [field]: value }))}
                          propertyType={baseType}
                          size="small"
                        />
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* SECTION 2: Property Flags */}
              {editingClassProperty && (() => {
                const typeInfo = getPropertyTypeInfo();
                const propData = typeof editingClassProperty.data === 'string'
                  ? JSON.parse(editingClassProperty.data)
                  : (editingClassProperty.data || {});
                const schema = typeInfo.isArray ? (propData.items || {}) : propData;

                // Only show for non-reference types
                if (schema.$ref) return null;

                return (
                  <div className={`p-6 border-b border-gray-200 dark:border-gray-700 ${isDark ? 'bg-slate-900' : 'bg-gray-50'}`}>
                    <div className="flex items-center gap-2 mb-4">
                      <Settings size={18} className="text-indigo-500" />
                      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Property Flags</h3>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      {/* Required */}
                      <div className={`p-3 rounded-lg border ${formData.required ? 'bg-green-50 dark:bg-green-900/20 border-green-300 dark:border-green-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="required"
                            checked={formData.required || false}
                            onCheckedChange={(checked) => setFormData(prev => ({ ...prev, required: !!checked }))}
                          />
                          <label htmlFor="required" className="text-sm font-medium cursor-pointer">
                            Required
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 mt-1 ml-6">Must be provided</p>
                      </div>

                      {/* Nullable */}
                      <div className={`p-3 rounded-lg border ${formData.nullable ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="nullable"
                            checked={formData.nullable || false}
                            onCheckedChange={(checked) => setFormData(prev => ({ ...prev, nullable: !!checked }))}
                          />
                          <label htmlFor="nullable" className="text-sm font-medium cursor-pointer">
                            Nullable
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 mt-1 ml-6">Can be null</p>
                      </div>

                      {/* Read Only */}
                      <div className={`p-3 rounded-lg border ${formData.readOnly ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="readOnly"
                            checked={formData.readOnly || false}
                            onCheckedChange={(checked) => setFormData(prev => ({ ...prev, readOnly: !!checked }))}
                          />
                          <label htmlFor="readOnly" className="text-sm font-medium cursor-pointer">
                            Read Only
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 mt-1 ml-6">Only in responses</p>
                      </div>

                      {/* Write Only */}
                      <div className={`p-3 rounded-lg border ${formData.writeOnly ? 'bg-purple-50 dark:bg-purple-900/20 border-purple-300 dark:border-purple-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="writeOnly"
                            checked={formData.writeOnly || false}
                            onCheckedChange={(checked) => setFormData(prev => ({ ...prev, writeOnly: !!checked }))}
                          />
                          <label htmlFor="writeOnly" className="text-sm font-medium cursor-pointer">
                            Write Only
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 mt-1 ml-6">Only in requests</p>
                      </div>
                    </div>

                    {/* Deprecation */}
                    <div className={`mt-4 p-3 rounded-lg border flex flex-col gap-3 ${formData.deprecated ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="deprecated"
                          checked={formData.deprecated || false}
                          onCheckedChange={(checked) => setFormData(prev => ({ ...prev, deprecated: !!checked }))}
                        />
                        <label htmlFor="deprecated" className="text-sm font-medium cursor-pointer flex items-center gap-1">
                          <AlertTriangle size={14} className={formData.deprecated ? 'text-amber-500' : 'text-gray-400'} />
                          Deprecated
                        </label>
                      </div>
                      {formData.deprecated && (
                        <Input
                          value={formData.deprecationMessage || ''}
                          onChange={(e) => setFormData(prev => ({ ...prev, deprecationMessage: e.target.value }))}
                          placeholder="Deprecation message (e.g., Use newProperty instead)"
                          className="text-sm"
                        />
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* SECTION 3: Default & Constant Values */}
              {editingClassProperty && (() => {
                const typeInfo = getPropertyTypeInfo();
                const propData = typeof editingClassProperty.data === 'string'
                  ? JSON.parse(editingClassProperty.data)
                  : (editingClassProperty.data || {});
                const schema = typeInfo.isArray ? (propData.items || {}) : propData;

                // Only show for non-reference types
                if (schema.$ref) return null;

                return (
                  <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                    <div className="flex items-center gap-2 mb-4">
                      <Code size={18} className="text-indigo-500" />
                      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Default & Constant Values</h3>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Default Value */}
                      <div className="space-y-2">
                        <Label htmlFor="defaultValue">Default Value</Label>
                        <Input
                          id="defaultValue"
                          value={formData.default || ''}
                          onChange={(e) => setFormData(prev => ({ ...prev, default: e.target.value }))}
                          placeholder="JSON value (e.g., &quot;hello&quot;, 123, true)"
                          className="font-mono text-sm"
                        />
                        <p className="text-xs text-gray-500">Used when no value is provided</p>
                      </div>

                      {/* Constant Value */}
                      <div className="space-y-2">
                        <Label htmlFor="constValue">Constant Value</Label>
                        <Input
                          id="constValue"
                          value={formData.const || ''}
                          onChange={(e) => setFormData(prev => ({ ...prev, const: e.target.value }))}
                          placeholder="Fixed value (mutually exclusive with enum)"
                          className="font-mono text-sm"
                        />
                        <p className="text-xs text-gray-500">Must always equal this value</p>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* RIGHT COLUMN - Advanced Configuration */}
            <div className="flex flex-col overflow-y-auto min-h-0">
              {/* Advanced Header */}
              <div className="p-6 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                <div className="flex items-center gap-3 mb-2">
                  <Settings size={20} className="text-purple-500" />
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Advanced Constraints</h3>
                  <span className="px-2 py-0.5 rounded text-xs bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300">Optional</span>
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Configure type-specific validation rules and advanced constraints.</p>
              </div>

              {/* Property Constraints Section */}
              {editingClassProperty && (() => {
                const typeInfo = getPropertyTypeInfo();
                const propData = typeof editingClassProperty.data === 'string'
                  ? JSON.parse(editingClassProperty.data)
                  : (editingClassProperty.data || {});
                const schema = typeInfo.isArray ? (propData.items || {}) : propData;
                const baseType = schema.$ref ? 'reference' : (schema.type || 'object');

                // Check if this is a reference type (single $ref, allOf, anyOf, or oneOf with refs)
                const isReferenceType = schema.$ref ||
                  (schema.allOf && Array.isArray(schema.allOf) && schema.allOf.some((item: any) => item.$ref)) ||
                  (schema.anyOf && Array.isArray(schema.anyOf) && schema.anyOf.some((item: any) => item.$ref)) ||
                  (schema.oneOf && Array.isArray(schema.oneOf) && schema.oneOf.some((item: any) => item.$ref));

                // Show reference editing UI for reference types
                if (isReferenceType) {
                  return (
                    <div className="p-6 flex-1 overflow-y-auto space-y-6">
                      {/* Reference Type Header */}
                      <div className="flex items-center gap-2 text-purple-600 dark:text-purple-400">
                        <GitBranch size={20} />
                        <span className="font-medium">Reference Configuration</span>
                      </div>

                      {/* Description */}
                      <div className="space-y-2">
                        <Label htmlFor="refDescription">Description</Label>
                        <Textarea
                          id="refDescription"
                          value={refDescription}
                          onChange={(e) => setRefDescription(e.target.value)}
                          placeholder="Description of this reference property"
                          rows={2}
                        />
                      </div>

                      {/* Array Toggle */}
                      <div className="flex items-center space-x-2">
                        <Checkbox
                          id="refIsArray"
                          checked={refIsArray}
                          onCheckedChange={(checked) => setRefIsArray(checked === true)}
                        />
                        <Label htmlFor="refIsArray" className="cursor-pointer">
                          Array of references
                        </Label>
                      </div>

                      {/* Array Constraints */}
                      {refIsArray && (
                        <div className="pl-6 space-y-4 border-l-2 border-gray-200 dark:border-gray-700">
                          <p className="text-xs text-gray-500 dark:text-gray-400">Array constraints:</p>
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label htmlFor="refMinItems">Min Items</Label>
                              <Input
                                id="refMinItems"
                                type="number"
                                value={refMinItems}
                                onChange={(e) => setRefMinItems(e.target.value)}
                                placeholder="0"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label htmlFor="refMaxItems">Max Items</Label>
                              <Input
                                id="refMaxItems"
                                type="number"
                                value={refMaxItems}
                                onChange={(e) => setRefMaxItems(e.target.value)}
                                placeholder="No limit"
                              />
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            <Checkbox
                              id="refUniqueItems"
                              checked={refUniqueItems}
                              onCheckedChange={(checked) => setRefUniqueItems(checked === true)}
                            />
                            <Label htmlFor="refUniqueItems" className="cursor-pointer text-sm">
                              Unique items (all elements must be distinct)
                            </Label>
                          </div>
                        </div>
                      )}

                      {/* Reference Type Selection */}
                      <div className="space-y-3 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
                        <Label className="font-medium">Reference Type</Label>
                        <div className="space-y-2">
                          <label className="flex items-start gap-3 cursor-pointer">
                            <input
                              type="radio"
                              name="refType"
                              value="none"
                              checked={refCompositionType === 'none'}
                              onChange={() => {
                                setRefCompositionType('none');
                                setRefTargetClassIds([]);
                              }}
                              className="mt-1"
                            />
                            <div>
                              <span className="font-medium text-sm">Single Reference</span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">Reference a single class</p>
                            </div>
                          </label>
                          <label className="flex items-start gap-3 cursor-pointer">
                            <input
                              type="radio"
                              name="refType"
                              value="allOf"
                              checked={refCompositionType === 'allOf'}
                              onChange={() => {
                                setRefCompositionType('allOf');
                                setRefTargetClassId('');
                              }}
                              className="mt-1"
                            />
                            <div>
                              <span className="font-medium text-sm">allOf (Composition)</span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">Must satisfy all referenced schemas</p>
                            </div>
                          </label>
                          <label className="flex items-start gap-3 cursor-pointer">
                            <input
                              type="radio"
                              name="refType"
                              value="anyOf"
                              checked={refCompositionType === 'anyOf'}
                              onChange={() => {
                                setRefCompositionType('anyOf');
                                setRefTargetClassId('');
                              }}
                              className="mt-1"
                            />
                            <div>
                              <span className="font-medium text-sm">anyOf (Union)</span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">Can satisfy any of the referenced schemas</p>
                            </div>
                          </label>
                          <label className="flex items-start gap-3 cursor-pointer">
                            <input
                              type="radio"
                              name="refType"
                              value="oneOf"
                              checked={refCompositionType === 'oneOf'}
                              onChange={() => {
                                setRefCompositionType('oneOf');
                                setRefTargetClassId('');
                              }}
                              className="mt-1"
                            />
                            <div>
                              <span className="font-medium text-sm">oneOf (Exclusive)</span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">Must satisfy exactly one referenced schema</p>
                            </div>
                          </label>
                        </div>
                      </div>

                      {/* Target Class Selection */}
                      {refCompositionType === 'none' ? (
                        <div className="space-y-2">
                          <Label htmlFor="targetClass">Target Class</Label>
                          <select
                            id="targetClass"
                            value={refTargetClassId}
                            onChange={(e) => setRefTargetClassId(e.target.value)}
                            className="w-full px-3 py-2 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                          >
                            <option value="">Select a class...</option>
                            {availableClasses.map((cls) => (
                              <option key={cls.id} value={cls.id}>
                                {cls.name}
                              </option>
                            ))}
                          </select>
                          <p className="text-xs text-gray-500">Select the class this property references</p>
                        </div>
                      ) : (
                        <div className="space-y-3">
                          <Label>Select Classes for {refCompositionType}</Label>
                          <select
                            value=""
                            onChange={(e) => {
                              const classId = e.target.value;
                              if (classId && !refTargetClassIds.includes(classId)) {
                                setRefTargetClassIds([...refTargetClassIds, classId]);
                              }
                            }}
                            className="w-full px-3 py-2 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                          >
                            <option value="">Add a class...</option>
                            {availableClasses
                              .filter(cls => !refTargetClassIds.includes(cls.id))
                              .map((cls) => (
                                <option key={cls.id} value={cls.id}>
                                  {cls.name}
                                </option>
                              ))}
                          </select>
                          {refTargetClassIds.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {refTargetClassIds.map((classId) => {
                                const cls = availableClasses.find(c => c.id === classId);
                                return cls ? (
                                  <Badge
                                    key={classId}
                                    variant="secondary"
                                    className="flex items-center gap-1"
                                  >
                                    {cls.name}
                                    <button
                                      type="button"
                                      onClick={() => setRefTargetClassIds(refTargetClassIds.filter(id => id !== classId))}
                                      className="ml-1 hover:text-red-500"
                                    >
                                      ×
                                    </button>
                                  </Badge>
                                ) : null;
                              })}
                            </div>
                          )}
                          {refTargetClassIds.length === 0 && (
                            <Alert variant="default" className="bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
                              <Info className="h-4 w-4" />
                              <span className="ml-2 text-sm">Add at least one class for {refCompositionType}</span>
                            </Alert>
                          )}
                        </div>
                      )}

                      {/* Nullable Option */}
                      <div className="flex items-center space-x-2 pt-4 border-t border-gray-200 dark:border-gray-700">
                        <Checkbox
                          id="refNullable"
                          checked={formData.nullable || false}
                          onCheckedChange={(checked) => setFormData(prev => ({ ...prev, nullable: checked === true }))}
                        />
                        <Label htmlFor="refNullable" className="cursor-pointer">
                          Nullable (can be null)
                        </Label>
                      </div>
                    </div>
                  );
                }

                return (
                  <div className="p-6 flex-1 overflow-y-auto">
                    <PropertyFormFields
                      baseType={baseType}
                      isArray={typeInfo.isArray}
                      data={formData}
                      onChange={(field, value) => {
                        setFormData(prev => ({ ...prev, [field]: value }));
                      }}
                      showMetadata={false}
                      showTitle={false}
                      size="small"
                      nestedProperties={
                        baseType === 'object'
                          ? (allClassProperties || []).filter(p => p.parent_id === editingClassProperty.id)
                          : undefined
                      }
                      availableClasses={existingClassNames}
                    />

                    {/* External Documentation - inside scrollable area */}
                    <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
                      <div className="flex items-center gap-2 mb-4">
                        <ExternalLink size={18} className="text-purple-500" />
                        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">External Documentation</h3>
                      </div>

                      <div className="grid grid-cols-1 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="externalDocsUrl">URL</Label>
                          <Input
                            id="externalDocsUrl"
                            value={formData.externalDocsUrl || ''}
                            onChange={(e) => setFormData(prev => ({ ...prev, externalDocsUrl: e.target.value }))}
                            placeholder="https://docs.example.com/property"
                            type="url"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="externalDocsDescription">Description</Label>
                          <Input
                            id="externalDocsDescription"
                            value={formData.externalDocsDescription || ''}
                            onChange={(e) => setFormData(prev => ({ ...prev, externalDocsDescription: e.target.value }))}
                            placeholder="Link to property documentation"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>

        {/* Footer */}
        <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex justify-between w-full items-center">
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
              <Button onClick={handleSave}>
                Save
              </Button>
            </div>
          </div>
        </DialogFooter>
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

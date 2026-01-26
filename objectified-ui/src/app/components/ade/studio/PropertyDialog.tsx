'use client';

import React, { useState, useEffect } from 'react';
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
import { Checkbox } from '../../ui/Checkbox';
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
} from 'lucide-react';

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
}

export const PropertyDialog: React.FC<PropertyDialogProps> = ({
                                                                open,
                                                                onClose,
                                                                mode,
                                                                property,
                                                                onSubmit,
                                                                availableClasses = [],
                                                              }) => {
  const isDark = useDarkMode();

  const [viewMode, setViewMode] = useState<'form' | 'json'>('form');
  const [propertyName, setPropertyName] = useState('');
  const [propertyType, setPropertyType] = useState('string');
  const [propertyIsArray, setPropertyIsArray] = useState(false);
  const [propertyError, setPropertyError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Use shared form data structure
  const [formData, setFormData] = useState<PropertyFormData>({});

  // Load property data when dialog opens in edit mode
  useEffect(() => {
    if (open && property && mode === 'edit') {
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

      // Extract extensions (x- prefixed properties)
      const extensions: Record<string, any> = {};
      Object.keys(property as any).forEach(key => {
        if (key.startsWith('x-')) {
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
      });
      setPropertyError('');
    } else if (open && mode === 'add') {
      // Reset all fields for add mode
      setViewMode('form');
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

      onClose();
    } catch (error) {
      console.error('Error submitting property:', error);
      setPropertyError(error instanceof Error ? error.message : 'An error occurred while saving the property');
    } finally {
      setIsSubmitting(false);
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
                {mode === 'add' ? 'Add Property' : 'Edit Property'}
              </DialogTitle>
            </div>
          </div>
        </DialogHeader>

        <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as 'form' | 'json')} className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="px-6 border-b border-gray-200 dark:border-gray-700 rounded-none justify-start bg-transparent shrink-0">
            <TabsTrigger value="form">Form</TabsTrigger>
            <TabsTrigger value="json">JSON</TabsTrigger>
          </TabsList>

          {/* Form Tab */}
          <TabsContent value="form" className="flex-1 flex flex-col overflow-hidden mt-0 p-0">
            {propertyError && <Alert variant="error" className="m-4 mb-0">{propertyError}</Alert>}

            <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-0 divide-x divide-gray-200 dark:divide-gray-700 overflow-hidden min-h-0">
              {/* LEFT COLUMN - Basic Configuration */}
              <div className="flex flex-col overflow-y-auto min-h-0">
                {/* SECTION 1: Property Information */}
                <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                  <div className="flex items-center gap-2 mb-4">
                    <FileText size={18} className="text-indigo-500" />
                    <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Property Information</h3>
                  </div>

                  {/* Property Name */}
                  <div className="space-y-2 mb-4">
                    <Label htmlFor="propertyName">Property Name *</Label>
                    <Input
                      id="propertyName"
                      autoFocus
                      value={propertyName}
                      onChange={(e) => {
                        const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
                        setPropertyName(filteredValue);
                      }}
                      placeholder="e.g., userName"
                    />
                    <p className="text-xs text-gray-500">Only letters, numbers, and underscores. camelCase recommended.</p>
                  </div>

                  {/* Type Selector */}
                  <div className="grid grid-cols-2 gap-4 mb-4">
                    <div className={`p-3 rounded-lg border ${propertyIsArray ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-300 dark:border-indigo-700' : 'bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700'}`}>
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="isArray"
                          checked={propertyIsArray}
                          onCheckedChange={(checked) => setPropertyIsArray(!!checked)}
                          disabled={mode === 'edit'}
                        />
                        <label htmlFor="isArray" className="text-sm font-medium cursor-pointer">
                          Array
                        </label>
                      </div>
                      <p className="text-xs text-gray-500 mt-1 ml-6">An array of...</p>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="propertyType">Type *</Label>
                      <Select
                        value={propertyType}
                        onValueChange={setPropertyType}
                        disabled={mode === 'edit'}
                      >
                        <SelectTrigger className="w-full">
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
                      {mode === 'edit' && (
                        <p className="text-xs text-gray-500">Type cannot be changed after creation</p>
                      )}
                    </div>
                  </div>

                  {/* Description */}
                  <div className="space-y-2">
                    <Label htmlFor="description">Description</Label>
                    <Textarea
                      id="description"
                      value={formData.description || ''}
                      onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="Brief description of this property"
                      rows={2}
                    />
                  </div>

                  {/* Title (optional) */}
                  <div className="mt-4 space-y-2">
                    <Label htmlFor="title">Title (Optional)</Label>
                    <Input
                      id="title"
                      value={formData.title || ''}
                      onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                      placeholder="Human-readable title"
                    />
                    <p className="text-xs text-gray-500">A human-readable title for documentation</p>
                  </div>
                </div>

                {/* Apply from Primitive - Only show for applicable types */}
                {(propertyType === 'string' || propertyType === 'number' || propertyType === 'integer' || propertyType === 'array') && !formData.tupleMode && (
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
                          propertyType={propertyType}
                          size="small"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* SECTION 2: Property Flags */}
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

                {/* SECTION 3: Default & Constant Values */}
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
                        placeholder='JSON value (e.g., "hello", 123, true)'
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
                <div className="p-6 flex-1 overflow-y-auto">
                  <PropertyFormFields
                    baseType={propertyType}
                    isArray={propertyIsArray}
                    data={formData}
                    onChange={(field, value) => {
                      setFormData(prev => ({ ...prev, [field]: value }));
                    }}
                    showMetadata={false}
                    showTitle={false}
                    showPrimitiveSelector={false}
                    size="small"
                    availableClasses={availableClasses}
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
              </div>
            </div>
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

        {/* Footer */}
        <DialogFooter className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex justify-end w-full gap-2">
            <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={isSubmitting}>
              {mode === 'add' ? 'Add' : 'Save'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PropertyDialog;
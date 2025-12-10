'use client';

import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Alert from '@mui/material/Alert';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import { PropertyFormFields, PropertyFormData } from './PropertyFormFields';

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
  example?: any;
  additionalProperties?: boolean | any;
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
}

export const PropertyDialog: React.FC<PropertyDialogProps> = ({
  open,
  onClose,
  mode,
  property,
  onSubmit,
}) => {
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

      // Check if property is an array type
      const isArray = property.type === 'array';
      setPropertyIsArray(isArray);

      // Determine the actual type
      // Note: Actual $ref values (class references) are managed via canvas connections
      if (isArray && (property as any).items) {
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
        setPropertyType(property.type || 'string');
      }

      // Determine minimum type (inclusive vs exclusive)
      // For array types, check inside items; for non-array, check at root level
      let minimumValue = '';
      let minimumType: 'inclusive' | 'exclusive' | undefined;
      const minMaxSource = isArray && (property as any).items ? (property as any).items : property;

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
      let additionalPropsValue: 'default' | 'true' | 'false' = 'default';
      if (minMaxSource.hasOwnProperty('additionalProperties')) {
        additionalPropsValue = minMaxSource.additionalProperties === false ? 'false' : 'true';
      }

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
        // Enum and default come from items for array types
        enum: minMaxSource.enum || [],
        default: minMaxSource.default?.toString() || '',
        required: property.required || false,
        // Metadata fields
        readOnly: property.readOnly || false,
        writeOnly: property.writeOnly || false,
        deprecated: property.deprecated || false,
        example: property.example ? JSON.stringify(property.example) : '',
        // Object constraints
        additionalProperties: additionalPropsValue,
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
    if (formData.deprecated) schema.deprecated = formData.deprecated;
    if (formData.example) {
      try {
        schema.example = JSON.parse(formData.example);
      } catch (e) {
        schema.example = formData.example;
      }
    }
    if (formData.required) schema.required = formData.required;

    if (propertyIsArray) {
      schema.type = 'array';
      if (formData.minItems) schema.minItems = parseInt(formData.minItems);
      if (formData.maxItems) schema.maxItems = parseInt(formData.maxItems);
      if (formData.uniqueItems) schema.uniqueItems = true;

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
      if (formData.enum && formData.enum.length > 0) itemsSchema.enum = formData.enum;
      if (formData.default) itemsSchema.default = formData.default;

      // Handle additionalProperties for array items that are objects
      if (propertyType === 'object') {
        if (formData.additionalProperties === 'true') {
          itemsSchema.additionalProperties = true;
        } else if (formData.additionalProperties === 'false') {
          itemsSchema.additionalProperties = false;
        }
      }

      schema.items = itemsSchema;
    } else {
      schema.type = propertyType;
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
      if (formData.enum && formData.enum.length > 0) schema.enum = formData.enum;
      if (formData.default) schema.default = formData.default;

      // Handle additionalProperties for object types
      if (propertyType === 'object') {
        if (formData.additionalProperties === 'true') {
          schema.additionalProperties = true;
        } else if (formData.additionalProperties === 'false') {
          schema.additionalProperties = false;
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

      if (formData.title) dataObject.title = formData.title;
      else delete dataObject.title;

      if (formData.example) {
        try {
          dataObject.example = JSON.parse(formData.example);
        } catch (e) {
          dataObject.example = formData.example;
        }
      } else {
        delete dataObject.example;
      }

      if (propertyIsArray) {
        dataObject.type = 'array';
        if (formData.minItems) dataObject.minItems = parseInt(formData.minItems);
        else delete dataObject.minItems;
        if (formData.maxItems) dataObject.maxItems = parseInt(formData.maxItems);
        else delete dataObject.maxItems;
        if (formData.uniqueItems) dataObject.uniqueItems = true;
        else delete dataObject.uniqueItems;

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

        if (formData.enum && formData.enum.length > 0) itemsSchema.enum = formData.enum;
        else delete itemsSchema.enum;
        if (formData.default) itemsSchema.default = formData.default;
        else delete itemsSchema.default;

        // Handle additionalProperties for array items that are objects
        if (propertyType === 'object') {
          if (formData.additionalProperties === 'true') {
            itemsSchema.additionalProperties = true;
          } else if (formData.additionalProperties === 'false') {
            itemsSchema.additionalProperties = false;
          }
        }

        dataObject.items = itemsSchema;
      } else {
        dataObject.type = propertyType;
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

        if (formData.enum && formData.enum.length > 0) dataObject.enum = formData.enum;
        else delete dataObject.enum;
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
        }
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
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            height: '90vh',
            maxHeight: '90vh',
          }
        }
      }}
    >
      <DialogTitle>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{mode === 'add' ? 'Add Property' : 'Edit Property'}</span>
          <Box sx={{ display: 'flex', border: '1px solid', borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
            <Button
              size="small"
              variant={viewMode === 'form' ? 'contained' : 'text'}
              onClick={() => setViewMode('form')}
              sx={{ borderRadius: 0, minWidth: 'auto', px: 2 }}
            >
              Form
            </Button>
            <Box sx={{ width: '1px', bgcolor: 'divider' }} />
            <Button
              size="small"
              variant={viewMode === 'json' ? 'contained' : 'text'}
              onClick={() => setViewMode('json')}
              sx={{ borderRadius: 0, minWidth: 'auto', px: 2 }}
            >
              JSON
            </Button>
          </Box>
        </Box>
      </DialogTitle>
      <DialogContent
        sx={{
          display: 'flex',
          flexDirection: 'column',
          overflow: 'auto',
        }}
      >
        {propertyError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {propertyError}
          </Alert>
        )}

        {viewMode === 'form' ? (
          <>
            {/* Basic Information */}
            <TextField
              autoFocus
              margin="dense"
              label="Property Name"
              type="text"
              fullWidth
              required
              value={propertyName}
              onChange={(e) => {
                // Only allow A-Za-z0-9_ characters
                const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
                setPropertyName(filteredValue);
              }}
              helperText="Only letters, numbers, and underscores are allowed. Suggest camelCase property names."
              sx={{ mb: 2 }}
            />

            {/* Type Selector with Array Checkbox */}
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', mb: 2 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={propertyIsArray}
                    onChange={(e) => setPropertyIsArray(e.target.checked)}
                    disabled={mode === 'edit'}
                  />
                }
                label={'An array of ...'}
                sx={{ mt: 1, whiteSpace: 'nowrap' }}
              />

              <TextField
                select
                margin="dense"
                label="Type"
                required
                value={propertyType}
                onChange={(e) => {
                  const newType = e.target.value;
                  setPropertyType(newType);
                }}
                SelectProps={{ native: true }}
                disabled={mode === 'edit'}
                helperText={mode === 'edit' ? 'Type cannot be changed after creation' : ''}
                sx={{ flex: 1 }}
              >
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="integer">integer</option>
                <option value="boolean">boolean</option>
                <option value="object">object</option>
                <option value="null">null</option>
              </TextField>
            </Box>

            <PropertyFormFields
              baseType={propertyType}
              isArray={propertyIsArray}
              data={formData}
              onChange={(field, value) => {
                setFormData(prev => ({ ...prev, [field]: value }));
              }}
              showMetadata={true}
              showTitle={true}
              size="medium"
            />
          </>
        ) : (
          /* JSON View */
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              JSON Schema 2020-12 Definition
            </Typography>
            <Box
              sx={{
                flex: 1,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                overflow: 'hidden',
                minHeight: '300px',
              }}
            >
              <Editor
                height="100%"
                defaultLanguage="json"
                value={JSON.stringify(buildPropertyJsonSchema(), null, 2)}
                theme="vs-light"
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
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5 }}>
              This is the JSON Schema representation of your property definition. Switch back to Form view to make changes.
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" disabled={isSubmitting}>
          {mode === 'add' ? 'Add' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default PropertyDialog;


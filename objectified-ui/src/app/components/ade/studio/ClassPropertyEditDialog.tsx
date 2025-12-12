'use client';

import { useEffect, useState } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import { updateClassProperty } from '../../../../../lib/db/helper';
import { PropertyFormFields, PropertyFormData } from './PropertyFormFields';
import ExtractToClassDialog from './ExtractToClassDialog';
import CallSplitIcon from '@mui/icons-material/CallSplit';

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
}

export default function ClassPropertyEditDialog({ open, onClose, editingClassProperty, onSaved, allClassProperties, existingClassNames = [] }: Props) {
  const [editPropName, setEditPropName] = useState('');
  const [editPropertyError, setEditPropertyError] = useState('');
  const [extractDialogOpen, setExtractDialogOpen] = useState(false);

  // Use shared form data structure
  const [formData, setFormData] = useState<PropertyFormData>({});

  // Helper to get property type display
  const getPropertyTypeInfo = () => {
    if (!editingClassProperty) return { type: 'unknown', baseType: 'unknown', isArray: false };

    const propData = typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {});

    const isArray = propData.type === 'array';
    const schema = isArray ? (propData.items || {}) : propData;

    let baseType = 'unknown';
    if (schema.$ref) {
      const refParts = schema.$ref.split('/');
      baseType = refParts[refParts.length - 1] || schema.$ref;
    } else {
      baseType = schema.type || 'object';
    }

    return {
      type: isArray ? `${baseType}[]` : baseType,
      baseType,
      isArray,
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

    // Get the actual schema (handle array types)
    const schema = propData.type === 'array' ? (propData.items || {}) : propData;

    // Determine additionalProperties value
    let additionalPropsValue: 'default' | 'true' | 'false' = 'default';
    if (schema.hasOwnProperty('additionalProperties')) {
      additionalPropsValue = schema.additionalProperties === false ? 'false' : 'true';
    }

    // Populate form data
    setFormData({
      description: editingClassProperty.description || '',
      required: !!propData.required,
      deprecated: !!propData.deprecated,
      deprecationMessage: propData.deprecationMessage || '',
      readOnly: !!propData.readOnly,
      writeOnly: !!propData.writeOnly,
      example: propData.example ? JSON.stringify(propData.example) : '',

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

      // Common constraints
      default: schema.default !== undefined ? JSON.stringify(schema.default) : '',
      enum: schema.enum || [],

      // Object constraints
      additionalProperties: additionalPropsValue,
    });

    setEditPropertyError('');
  }, [editingClassProperty]);

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

      if (formData.example?.trim()) {
        try {
          updatedData.example = JSON.parse(formData.example);
        } catch (e) {
          updatedData.example = formData.example;
        }
      } else {
        delete updatedData.example;
      }

      // Determine where to apply constraints (array items vs direct)
      const isArray = updatedData.type === 'array';
      const targetSchema = isArray ? (updatedData.items || {}) : updatedData;

      // Handle additionalProperties field (apply to direct object or array items object)
      if (formData.additionalProperties === 'true') {
        targetSchema.additionalProperties = true;
      } else if (formData.additionalProperties === 'false') {
        targetSchema.additionalProperties = false;
      } else {
        delete targetSchema.additionalProperties;
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
      }

      // Enum values
      if (formData.enum && formData.enum.length > 0) targetSchema.enum = formData.enum;
      else delete targetSchema.enum;

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

      // Update items if it's an array (but not if tuple mode is active - already set above)
      if (isArray && !formData.tupleMode) {
        updatedData.items = targetSchema;
        // Ensure additionalProperties isn't left on the array level
        delete updatedData.additionalProperties;
      }

      const result = await updateClassProperty(
        editingClassProperty.id,
        editPropName.trim(),
        formData.description || null,
        updatedData
      );

      const response = JSON.parse(result);
      if (response.success) {
        // Notify parent to reload
        if (onSaved) await onSaved();
        onClose();
      } else {
        setEditPropertyError(response.error || 'Failed to update property');
      }
    } catch (error) {
      console.error('Error updating class property:', error);
      setEditPropertyError('An error occurred while updating the property');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Edit Property in Class</DialogTitle>
      <DialogContent>
        {editPropertyError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {editPropertyError}
          </Alert>
        )}

        <Alert severity="info" sx={{ mb: 2 }}>
          When editing a property that is a member of a class, only the name and constraints can be modified. The type and base type are read-only.
        </Alert>

        {/* Type Information - Read Only */}
        {editingClassProperty && (
          <Box sx={{ mb: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1, border: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              Property Type (Read-Only)
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Chip
                label={getPropertyTypeInfo().type}
                color="primary"
                size="small"
                sx={{ fontFamily: 'monospace' }}
              />
              {getPropertyTypeInfo().hasRef && (
                <Typography variant="caption" color="text.secondary">
                  (References another class)
                </Typography>
              )}
            </Box>
          </Box>
        )}

        <TextField
          autoFocus
          margin="dense"
          label="Property Name"
          type="text"
          fullWidth
          required
          value={editPropName}
          onChange={(e) => setEditPropName(e.target.value)}
          sx={{ mb: 2 }}
        />


        {/* Constraints Section */}
        {editingClassProperty && (() => {
          const typeInfo = getPropertyTypeInfo();
          const propData = typeof editingClassProperty.data === 'string'
            ? JSON.parse(editingClassProperty.data)
            : (editingClassProperty.data || {});
          const schema = typeInfo.isArray ? (propData.items || {}) : propData;
          const baseType = schema.$ref ? 'reference' : (schema.type || 'object');

          // Only show constraints for non-reference types
          if (schema.$ref) return null;

          return (
            <>
              <Typography variant="subtitle2" sx={{ mt: 3, mb: 1, fontWeight: 600 }}>
                Property Details
              </Typography>

              <PropertyFormFields
                baseType={baseType}
                isArray={typeInfo.isArray}
                data={formData}
                onChange={(field, value) => {
                  setFormData(prev => ({ ...prev, [field]: value }));
                }}
                showMetadata={true}
                showTitle={false}
                size="small"
                nestedProperties={
                  baseType === 'object'
                    ? (allClassProperties || []).filter(p => p.parent_id === editingClassProperty.id)
                    : undefined
                }
              />
            </>
          );
        })()}
      </DialogContent>
      <DialogActions>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
          <Box>
            {canExtractToClass() && (
              <Button
                onClick={() => setExtractDialogOpen(true)}
                startIcon={<CallSplitIcon />}
                color="secondary"
                variant="outlined"
              >
                Extract to Class
              </Button>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button onClick={onClose}>Cancel</Button>
            <Button onClick={handleSave} variant="contained">Save</Button>
          </Box>
        </Box>
      </DialogActions>

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

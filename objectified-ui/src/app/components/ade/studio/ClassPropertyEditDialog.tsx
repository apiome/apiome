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
import Checkbox from '@mui/material/Checkbox';
import Radio from '@mui/material/Radio';
import FormControlLabel from '@mui/material/FormControlLabel';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import { updateClassProperty } from '../../../../../lib/db/helper';

interface Props {
  open: boolean;
  onClose: () => void;
  editingClassProperty: any | null;
  // Callback to reload classes after a successful save
  onSaved?: () => Promise<void> | void;
}

export default function ClassPropertyEditDialog({ open, onClose, editingClassProperty, onSaved }: Props) {
  const [editPropName, setEditPropName] = useState('');
  const [editPropDescription, setEditPropDescription] = useState('');
  const [editPropRequired, setEditPropRequired] = useState(false);
  const [editPropDeprecated, setEditPropDeprecated] = useState(false);
  const [editPropReadOnly, setEditPropReadOnly] = useState(false);
  const [editPropWriteOnly, setEditPropWriteOnly] = useState(false);
  const [editPropExample, setEditPropExample] = useState('');
  const [editPropAdditionalProperties, setEditPropAdditionalProperties] = useState<'default' | 'true' | 'false'>('default');
  const [editPropertyError, setEditPropertyError] = useState('');

  // Constraint fields
  const [editPropMinLength, setEditPropMinLength] = useState('');
  const [editPropMaxLength, setEditPropMaxLength] = useState('');
  const [editPropPattern, setEditPropPattern] = useState('');
  const [editPropFormat, setEditPropFormat] = useState('');
  const [editPropMinimum, setEditPropMinimum] = useState('');
  const [editPropMaximum, setEditPropMaximum] = useState('');
  const [editPropExclusiveMinimum, setEditPropExclusiveMinimum] = useState(false);
  const [editPropExclusiveMaximum, setEditPropExclusiveMaximum] = useState(false);
  const [editPropMultipleOf, setEditPropMultipleOf] = useState('');
  const [editPropMinItems, setEditPropMinItems] = useState('');
  const [editPropMaxItems, setEditPropMaxItems] = useState('');
  const [editPropUniqueItems, setEditPropUniqueItems] = useState(false);
  const [editPropDefault, setEditPropDefault] = useState('');
  const [editPropEnum, setEditPropEnum] = useState<string[]>([]);
  const [enumInput, setEnumInput] = useState('');

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

  const handleAddEnum = () => {
    if (enumInput.trim() && !editPropEnum.includes(enumInput.trim())) {
      setEditPropEnum([...editPropEnum, enumInput.trim()]);
      setEnumInput('');
    }
  };

  const handleRemoveEnum = (value: string) => {
    setEditPropEnum(editPropEnum.filter(v => v !== value));
  };

  // Initialize form when editingClassProperty changes
  useEffect(() => {
    if (!editingClassProperty) return;

    setEditPropName(editingClassProperty.name || '');
    setEditPropDescription(editingClassProperty.description || '');

    const propData = typeof editingClassProperty.data === 'string'
      ? JSON.parse(editingClassProperty.data)
      : (editingClassProperty.data || {});

    setEditPropRequired(!!propData.required);
    setEditPropDeprecated(!!propData.deprecated);
    setEditPropReadOnly(!!propData.readOnly);
    setEditPropWriteOnly(!!propData.writeOnly);
    setEditPropExample(propData.example ? JSON.stringify(propData.example) : '');

    // Handle additionalProperties - only relevant for object types
    if (propData.hasOwnProperty('additionalProperties')) {
      setEditPropAdditionalProperties(propData.additionalProperties === false ? 'false' : 'true');
    } else {
      setEditPropAdditionalProperties('default');
    }

    // Get the actual schema (handle array types)
    const schema = propData.type === 'array' ? (propData.items || {}) : propData;

    // String constraints
    setEditPropMinLength(schema.minLength?.toString() || '');
    setEditPropMaxLength(schema.maxLength?.toString() || '');
    setEditPropPattern(schema.pattern || '');
    setEditPropFormat(schema.format || '');

    // Number constraints
    setEditPropMinimum(schema.minimum?.toString() || '');
    setEditPropMaximum(schema.maximum?.toString() || '');
    setEditPropExclusiveMinimum(!!schema.exclusiveMinimum);
    setEditPropExclusiveMaximum(!!schema.exclusiveMaximum);
    setEditPropMultipleOf(schema.multipleOf?.toString() || '');

    // Array constraints (on the array itself, not items)
    setEditPropMinItems(propData.minItems?.toString() || '');
    setEditPropMaxItems(propData.maxItems?.toString() || '');
    setEditPropUniqueItems(!!propData.uniqueItems);

    // Common constraints
    setEditPropDefault(schema.default !== undefined ? JSON.stringify(schema.default) : '');
    setEditPropEnum(schema.enum || []);
    setEnumInput('');

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
        required: editPropRequired,
        deprecated: editPropDeprecated,
        readOnly: editPropReadOnly,
        writeOnly: editPropWriteOnly,
      };

      // Handle additionalProperties field
      if (editPropAdditionalProperties === 'true') {
        updatedData.additionalProperties = true;
      } else if (editPropAdditionalProperties === 'false') {
        updatedData.additionalProperties = false;
      } else {
        // 'default' - remove the field to use JSON Schema default behavior
        delete updatedData.additionalProperties;
      }

      if (editPropExample.trim()) {
        try {
          updatedData.example = JSON.parse(editPropExample);
        } catch (e) {
          updatedData.example = editPropExample;
        }
      } else {
        delete updatedData.example;
      }

      // Determine where to apply constraints (array items vs direct)
      const isArray = updatedData.type === 'array';
      const targetSchema = isArray ? (updatedData.items || {}) : updatedData;

      // String constraints
      if (editPropMinLength) targetSchema.minLength = parseInt(editPropMinLength);
      else delete targetSchema.minLength;

      if (editPropMaxLength) targetSchema.maxLength = parseInt(editPropMaxLength);
      else delete targetSchema.maxLength;

      if (editPropPattern) targetSchema.pattern = editPropPattern;
      else delete targetSchema.pattern;

      if (editPropFormat) targetSchema.format = editPropFormat;
      else delete targetSchema.format;

      // Number constraints
      if (editPropMinimum) {
        if (editPropExclusiveMinimum) {
          targetSchema.exclusiveMinimum = parseFloat(editPropMinimum);
          delete targetSchema.minimum;
        } else {
          targetSchema.minimum = parseFloat(editPropMinimum);
          delete targetSchema.exclusiveMinimum;
        }
      } else {
        delete targetSchema.minimum;
        delete targetSchema.exclusiveMinimum;
      }

      if (editPropMaximum) {
        if (editPropExclusiveMaximum) {
          targetSchema.exclusiveMaximum = parseFloat(editPropMaximum);
          delete targetSchema.maximum;
        } else {
          targetSchema.maximum = parseFloat(editPropMaximum);
          delete targetSchema.exclusiveMaximum;
        }
      } else {
        delete targetSchema.maximum;
        delete targetSchema.exclusiveMaximum;
      }

      if (editPropMultipleOf) targetSchema.multipleOf = parseFloat(editPropMultipleOf);
      else delete targetSchema.multipleOf;

      // Array constraints (on array itself, not items)
      if (isArray) {
        if (editPropMinItems) updatedData.minItems = parseInt(editPropMinItems);
        else delete updatedData.minItems;

        if (editPropMaxItems) updatedData.maxItems = parseInt(editPropMaxItems);
        else delete updatedData.maxItems;

        if (editPropUniqueItems) updatedData.uniqueItems = true;
        else delete updatedData.uniqueItems;
      }

      // Enum values
      if (editPropEnum.length > 0) targetSchema.enum = editPropEnum;
      else delete targetSchema.enum;

      // Default value
      if (editPropDefault.trim()) {
        try {
          targetSchema.default = JSON.parse(editPropDefault);
        } catch (e) {
          targetSchema.default = editPropDefault;
        }
      } else {
        delete targetSchema.default;
      }

      // Update items if it's an array
      if (isArray) {
        updatedData.items = targetSchema;
      }

      const result = await updateClassProperty(
        editingClassProperty.id,
        editPropName.trim(),
        editPropDescription || null,
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
          <Box sx={{ mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1, border: 1, borderColor: 'grey.300' }}>
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

        <TextField
          margin="dense"
          label="Description"
          type="text"
          fullWidth
          multiline
          rows={2}
          value={editPropDescription}
          onChange={(e) => setEditPropDescription(e.target.value)}
          helperText="Optional description for this property in this class"
          sx={{ mb: 2 }}
        />

        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>
          OpenAPI 3.1.0 Extensions
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <FormControlLabel
            control={
              <Checkbox
                checked={editPropRequired}
                onChange={(e) => setEditPropRequired(e.target.checked)}
              />
            }
            label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}><span>Required</span><Typography variant="caption" color="text.secondary">- Must be present in the object</Typography></Box>}
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={editPropDeprecated}
                onChange={(e) => setEditPropDeprecated(e.target.checked)}
              />
            }
            label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}><span>Deprecated</span><Typography variant="caption" color="text.secondary">- Should be transitioned out of usage</Typography></Box>}
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={editPropReadOnly}
                onChange={(e) => {
                  setEditPropReadOnly(e.target.checked);
                  if (e.target.checked) setEditPropWriteOnly(false);
                }}
              />
            }
            label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}><span>Read Only</span><Typography variant="caption" color="text.secondary">- Only in responses (OpenAPI)</Typography></Box>}
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={editPropWriteOnly}
                onChange={(e) => {
                  setEditPropWriteOnly(e.target.checked);
                  if (e.target.checked) setEditPropReadOnly(false);
                }}
              />
            }
            label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}><span>Write Only</span><Typography variant="caption" color="text.secondary">- Only in requests (OpenAPI)</Typography></Box>}
          />
        </Box>

        {/* Show additionalProperties control only for object types */}
        {editingClassProperty && (() => {
          const propData = typeof editingClassProperty.data === 'string'
            ? JSON.parse(editingClassProperty.data)
            : (editingClassProperty.data || {});
          const isObjectType = propData.type === 'object' && !propData.$ref;

          if (isObjectType) {
            return (
              <>
                <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
                  Object Schema Settings
                </Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Additional Properties
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, ml: 2 }}>
                    <FormControlLabel
                      control={
                        <Radio
                          checked={editPropAdditionalProperties === 'default'}
                          onChange={() => setEditPropAdditionalProperties('default')}
                          value="default"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <span>Default</span>
                          <Typography variant="caption" color="text.secondary">
                            - Use JSON Schema default (allows additional properties)
                          </Typography>
                        </Box>
                      }
                    />
                    <FormControlLabel
                      control={
                        <Radio
                          checked={editPropAdditionalProperties === 'true'}
                          onChange={() => setEditPropAdditionalProperties('true')}
                          value="true"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <span>Allow Additional</span>
                          <Typography variant="caption" color="text.secondary">
                            - Explicitly allow any additional properties
                          </Typography>
                        </Box>
                      }
                    />
                    <FormControlLabel
                      control={
                        <Radio
                          checked={editPropAdditionalProperties === 'false'}
                          onChange={() => setEditPropAdditionalProperties('false')}
                          value="false"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <span>Strict Schema</span>
                          <Typography variant="caption" color="text.secondary">
                            - Only defined properties allowed (additionalProperties: false)
                          </Typography>
                        </Box>
                      }
                    />
                  </Box>
                </Box>
              </>
            );
          }
          return null;
        })()}

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
                Constraints
              </Typography>

              {/* String Constraints */}
              {baseType === 'string' && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    String Constraints
                  </Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
                    <TextField
                      label="Min Length"
                      type="number"
                      size="small"
                      value={editPropMinLength}
                      onChange={(e) => setEditPropMinLength(e.target.value)}
                      inputProps={{ min: 0 }}
                    />
                    <TextField
                      label="Max Length"
                      type="number"
                      size="small"
                      value={editPropMaxLength}
                      onChange={(e) => setEditPropMaxLength(e.target.value)}
                      inputProps={{ min: 0 }}
                    />
                  </Box>
                  <TextField
                    label="Pattern (Regex)"
                    size="small"
                    fullWidth
                    value={editPropPattern}
                    onChange={(e) => setEditPropPattern(e.target.value)}
                    helperText="Regular expression pattern for validation"
                    sx={{ mt: 2 }}
                  />
                  <TextField
                    label="Format"
                    size="small"
                    fullWidth
                    value={editPropFormat}
                    onChange={(e) => setEditPropFormat(e.target.value)}
                    helperText="e.g., date, date-time, email, uri, uuid"
                    sx={{ mt: 2 }}
                  />
                </Box>
              )}

              {/* Number Constraints */}
              {(baseType === 'number' || baseType === 'integer') && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Number Constraints
                  </Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
                    <Box>
                      <TextField
                        label="Minimum"
                        type="number"
                        size="small"
                        fullWidth
                        value={editPropMinimum}
                        onChange={(e) => setEditPropMinimum(e.target.value)}
                      />
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={editPropExclusiveMinimum}
                            onChange={(e) => setEditPropExclusiveMinimum(e.target.checked)}
                            size="small"
                          />
                        }
                        label={<Typography variant="caption">Exclusive</Typography>}
                        sx={{ mt: 0.5 }}
                      />
                    </Box>
                    <Box>
                      <TextField
                        label="Maximum"
                        type="number"
                        size="small"
                        fullWidth
                        value={editPropMaximum}
                        onChange={(e) => setEditPropMaximum(e.target.value)}
                      />
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={editPropExclusiveMaximum}
                            onChange={(e) => setEditPropExclusiveMaximum(e.target.checked)}
                            size="small"
                          />
                        }
                        label={<Typography variant="caption">Exclusive</Typography>}
                        sx={{ mt: 0.5 }}
                      />
                    </Box>
                  </Box>
                  <TextField
                    label="Multiple Of"
                    type="number"
                    size="small"
                    fullWidth
                    value={editPropMultipleOf}
                    onChange={(e) => setEditPropMultipleOf(e.target.value)}
                    helperText="Value must be a multiple of this number"
                    sx={{ mt: 2 }}
                  />
                </Box>
              )}

              {/* Array Constraints */}
              {typeInfo.isArray && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Array Constraints
                  </Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
                    <TextField
                      label="Min Items"
                      type="number"
                      size="small"
                      value={editPropMinItems}
                      onChange={(e) => setEditPropMinItems(e.target.value)}
                      inputProps={{ min: 0 }}
                    />
                    <TextField
                      label="Max Items"
                      type="number"
                      size="small"
                      value={editPropMaxItems}
                      onChange={(e) => setEditPropMaxItems(e.target.value)}
                      inputProps={{ min: 0 }}
                    />
                  </Box>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={editPropUniqueItems}
                        onChange={(e) => setEditPropUniqueItems(e.target.checked)}
                      />
                    }
                    label="Unique Items (all items must be unique)"
                    sx={{ mt: 1 }}
                  />
                </Box>
              )}

              {/* Enum Values */}
              {(baseType === 'string' || baseType === 'number' || baseType === 'integer') && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Enum Values
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                    <TextField
                      label="Add enum value"
                      size="small"
                      fullWidth
                      value={enumInput}
                      onChange={(e) => setEnumInput(e.target.value)}
                      onKeyPress={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddEnum();
                        }
                      }}
                    />
                    <IconButton onClick={handleAddEnum} color="primary" size="small">
                      <AddIcon />
                    </IconButton>
                  </Box>
                  {editPropEnum.length > 0 && (
                    <List dense sx={{ bgcolor: 'grey.50', borderRadius: 1, maxHeight: 150, overflow: 'auto' }}>
                      {editPropEnum.map((value, index) => (
                        <ListItem
                          key={index}
                          secondaryAction={
                            <IconButton edge="end" size="small" onClick={() => handleRemoveEnum(value)}>
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          }
                        >
                          <ListItemText primary={value} />
                        </ListItem>
                      ))}
                    </List>
                  )}
                </Box>
              )}

              {/* Default Value */}
              <Box sx={{ mb: 2 }}>
                <TextField
                  label="Default Value"
                  size="small"
                  fullWidth
                  value={editPropDefault}
                  onChange={(e) => setEditPropDefault(e.target.value)}
                  helperText="Default value (JSON format for objects/arrays)"
                />
              </Box>
            </>
          );
        })()}

        <TextField
          margin="dense"
          label="Example Value"
          type="text"
          fullWidth
          multiline
          rows={2}
          value={editPropExample}
          onChange={(e) => setEditPropExample(e.target.value)}
          helperText="Example value (JSON format)"
          sx={{ mt: 2 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained">Save</Button>
      </DialogActions>
    </Dialog>
  );
}


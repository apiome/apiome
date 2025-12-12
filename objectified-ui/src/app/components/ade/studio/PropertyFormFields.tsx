'use client';

import React from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Radio from '@mui/material/Radio';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import InputAdornment from '@mui/material/InputAdornment';
import Tooltip from '@mui/material/Tooltip';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import SortByAlphaIcon from '@mui/icons-material/SortByAlpha';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { RegexTester } from './RegexTester';
import { PrefixItemsEditor } from './PrefixItemsEditor';

export interface PropertyFormData {
  // Basic fields
  title?: string;
  description?: string;
  format?: string;
  pattern?: string;

  // String constraints
  minLength?: string;
  maxLength?: string;

  // Number constraints
  minimum?: string;
  maximum?: string;
  minimumType?: 'inclusive' | 'exclusive'; // OpenAPI 3.1: determines whether to use minimum or exclusiveMinimum
  maximumType?: 'inclusive' | 'exclusive'; // OpenAPI 3.1: determines whether to use maximum or exclusiveMaximum
  multipleOf?: string;

  // Array constraints
  minItems?: string;
  maxItems?: string;
  uniqueItems?: boolean;
  contains?: string; // OpenAPI 3.1: JSON Schema that at least one array item must match
  minContains?: string; // OpenAPI 3.1: Minimum number of items that must match contains schema
  maxContains?: string; // OpenAPI 3.1: Maximum number of items that must match contains schema

  // Tuple mode (OpenAPI 3.1)
  tupleMode?: boolean; // Toggle for tuple mode with prefixItems
  prefixItems?: any[]; // OpenAPI 3.1: Array of schemas for specific positions
  itemsSchema?: string; // JSON string of items schema for positions beyond prefix

  // Common constraints
  enum?: string[];
  default?: string;

  // Metadata
  required?: boolean;
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  deprecationMessage?: string;
  example?: string;

  // Object constraints
  additionalProperties?: 'default' | 'true' | 'false';
}

interface SortableEnumItemProps {
  id: string;
  value: string;
  onDelete: (value: string) => void;
}

const SortableEnumItem: React.FC<SortableEnumItemProps> = ({ id, value, onDelete }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <ListItem
      ref={setNodeRef}
      style={style}
      sx={{
        borderBottom: 1,
        borderColor: 'divider',
        backgroundColor: isDragging ? 'action.selected' : 'transparent',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        pl: 1,
        pr: 1,
      }}
    >
      <IconButton
        {...attributes}
        {...listeners}
        size="small"
        sx={{
          cursor: 'grab',
          '&:active': { cursor: 'grabbing' },
          color: 'text.secondary',
          flex: 0,
          p: 0.5,
        }}
      >
        <DragIndicatorIcon fontSize="small" />
      </IconButton>
      <ListItemText
        primary={value}
        primaryTypographyProps={{
          fontFamily: 'monospace',
          fontSize: '0.875rem',
        }}
        sx={{ flex: 1, my: 0 }}
      />
      <IconButton
        edge="end"
        onClick={() => onDelete(value)}
        size="small"
        sx={{
          flex: 0,
        }}
      >
        <DeleteIcon fontSize="small" />
      </IconButton>
    </ListItem>
  );
};

export interface PropertyFormFieldsProps {
  // Property type info
  baseType: string;
  isArray: boolean;

  // Form data
  data: PropertyFormData;

  // Change handlers
  onChange: (field: keyof PropertyFormData, value: any) => void;

  // Optional: Show/hide certain fields
  showMetadata?: boolean;
  showTitle?: boolean;
  size?: 'small' | 'medium';

  // Object type information
  nestedProperties?: Array<{
    id: string;
    name: string;
    data: any;
    description?: string;
  }>;
}

export const PropertyFormFields: React.FC<PropertyFormFieldsProps> = ({
  baseType,
  isArray,
  data,
  onChange,
  showMetadata = true,
  showTitle = true,
  size = 'medium',
  nestedProperties,
}) => {
  const [enumInput, setEnumInput] = React.useState('');
  const [enumError, setEnumError] = React.useState('');

  // DnD sensors for enum reordering
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Generate an example value based on the property schema
  const generateExample = () => {
    let exampleValue: any;

    // If enum values exist, use the first one
    if (data.enum && data.enum.length > 0) {
      exampleValue = data.enum[0];
      // Try to parse as number if baseType is number/integer
      if (baseType === 'number' || baseType === 'integer') {
        const numValue = Number(exampleValue);
        if (!isNaN(numValue)) {
          exampleValue = numValue;
        }
      }
    } else {
      // Generate based on type
      switch (baseType) {
        case 'string':
          if (data.format === 'email') {
            exampleValue = 'user@example.com';
          } else if (data.format === 'uri' || data.format === 'url') {
            exampleValue = 'https://example.com';
          } else if (data.format === 'date') {
            exampleValue = '2025-11-30';
          } else if (data.format === 'date-time') {
            exampleValue = '2025-11-30T12:00:00Z';
          } else if (data.format === 'time') {
            exampleValue = '12:00:00';
          } else if (data.format === 'uuid') {
            exampleValue = '123e4567-e89b-12d3-a456-426614174000';
          } else if (data.pattern) {
            // For patterns, provide a hint
            exampleValue = `string matching pattern: ${data.pattern}`;
          } else {
            exampleValue = data.description || 'example string';
          }
          break;

        case 'number':
          if (data.minimum) {
            exampleValue = parseFloat(data.minimum) + (data.minimumType === 'exclusive' ? 0.1 : 0);
          } else if (data.maximum) {
            exampleValue = parseFloat(data.maximum) - (data.maximumType === 'exclusive' ? 0.1 : 0);
          } else {
            exampleValue = 42.5;
          }
          break;

        case 'integer':
          if (data.minimum) {
            exampleValue = Math.ceil(parseFloat(data.minimum) + (data.minimumType === 'exclusive' ? 1 : 0));
          } else if (data.maximum) {
            exampleValue = Math.floor(parseFloat(data.maximum) - (data.maximumType === 'exclusive' ? 1 : 0));
          } else {
            exampleValue = 42;
          }
          break;

        case 'boolean':
          exampleValue = true;
          break;

        case 'object':
          exampleValue = {};
          // Add nested properties if available
          if (nestedProperties && nestedProperties.length > 0) {
            nestedProperties.forEach(prop => {
              const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
              // Generate simple example for nested properties
              if (propData.type === 'string') {
                exampleValue[prop.name] = 'example';
              } else if (propData.type === 'number') {
                exampleValue[prop.name] = 0;
              } else if (propData.type === 'boolean') {
                exampleValue[prop.name] = true;
              } else if (propData.type === 'array') {
                exampleValue[prop.name] = [];
              } else {
                exampleValue[prop.name] = {};
              }
            });
          } else {
            exampleValue = { property: 'value' };
          }
          break;

        case 'array':
          exampleValue = [];
          break;

        default:
          // For reference types (e.g., Person, Address)
          exampleValue = { id: 1, name: `example ${baseType}` };
          break;
      }
    }

    // Wrap in array if isArray
    if (isArray) {
      exampleValue = [exampleValue];
    }

    // Convert to JSON string
    const jsonString = JSON.stringify(exampleValue, null, 2);
    onChange('example', jsonString);
  };

  const handleAddEnum = () => {
    if (!enumInput.trim()) {
      setEnumError('Enum value cannot be empty');
      return;
    }

    const trimmedValue = enumInput.trim();

    // Validate based on data type
    if (baseType === 'number' || baseType === 'integer') {
      const numValue = Number(trimmedValue);
      if (isNaN(numValue)) {
        setEnumError(`Value must be a valid ${baseType}`);
        return;
      }
      if (baseType === 'integer' && !Number.isInteger(numValue)) {
        setEnumError('Value must be an integer (no decimals)');
        return;
      }
    }

    if (data.enum?.includes(trimmedValue)) {
      setEnumError('This value already exists');
      return;
    }

    onChange('enum', [...(data.enum || []), trimmedValue]);
    setEnumInput('');
    setEnumError('');
  };

  const handleRemoveEnum = (value: string) => {
    onChange('enum', (data.enum || []).filter(v => v !== value));
  };

  const handleEnumKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddEnum();
    }
  };

  const handleSortEnumAZ = () => {
    if (!data.enum || data.enum.length === 0) return;

    const sorted = [...data.enum].sort((a, b) => {
      // For numeric types, sort as numbers
      if (baseType === 'number' || baseType === 'integer') {
        return Number(a) - Number(b);
      }
      // For strings, sort alphabetically (case-insensitive)
      return a.toLowerCase().localeCompare(b.toLowerCase());
    });

    onChange('enum', sorted);
  };

  const handleSortEnumZA = () => {
    if (!data.enum || data.enum.length === 0) return;

    const sorted = [...data.enum].sort((a, b) => {
      // For numeric types, sort as numbers in descending order
      if (baseType === 'number' || baseType === 'integer') {
        return Number(b) - Number(a);
      }
      // For strings, sort alphabetically in reverse (case-insensitive)
      return b.toLowerCase().localeCompare(a.toLowerCase());
    });

    onChange('enum', sorted);
  };

  const handleEnumDragEnd = (event: any) => {
    const { active, over } = event;

    if (!over || active.id === over.id || !data.enum) {
      return;
    }

    const oldIndex = data.enum.indexOf(active.id);
    const newIndex = data.enum.indexOf(over.id);

    const newEnumArray = arrayMove(data.enum, oldIndex, newIndex);
    onChange('enum', newEnumArray);
  };

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1px 1fr', gap: 0 }}>
      {/* LEFT COLUMN: Standard Fields */}
      <Box sx={{ pr: 3 }}>
        {/* Section Header */}
        <Typography variant="h6" sx={{ mb: 3, fontWeight: 600 }}>
          Standard Fields
        </Typography>

        {/* Basic Fields */}
        {showTitle && (
          <TextField
            label="Title"
            size={size}
            fullWidth
            value={data.title || ''}
            onChange={(e) => onChange('title', e.target.value)}
            helperText="Optional display title for the property"
            sx={{ mb: 2 }}
          />
        )}

        <TextField
          label="Description"
          size={size}
          fullWidth
          multiline
          rows={3}
          value={data.description || ''}
          onChange={(e) => onChange('description', e.target.value)}
          helperText="Optional description for the property"
          sx={{ mb: 2 }}
        />

        {/* Default Value */}
        <TextField
          label="Default Value"
          size={size}
          fullWidth
          value={data.default || ''}
          onChange={(e) => onChange('default', e.target.value)}
          helperText="JSON value for default"
          sx={{ mb: 2 }}
        />

        {/* Metadata Fields */}
        {showMetadata && (
          <Box sx={{ mb: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.required || false}
                  onChange={(e) => onChange('required', e.target.checked)}
                  size={size}
                />
              }
              label="Required"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.readOnly || false}
                  onChange={(e) => {
                    onChange('readOnly', e.target.checked);
                    if (e.target.checked) onChange('writeOnly', false);
                  }}
                  size={size}
                />
              }
              label="Read Only"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.writeOnly || false}
                  onChange={(e) => {
                    onChange('writeOnly', e.target.checked);
                    if (e.target.checked) onChange('readOnly', false);
                  }}
                  size={size}
                />
              }
              label="Write Only"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.deprecated || false}
                  onChange={(e) => onChange('deprecated', e.target.checked)}
                  size={size}
                />
              }
              label="Deprecated"
            />

            {data.deprecated && (
              <TextField
                label="Deprecation Message (Optional)"
                size={size}
                fullWidth
                multiline
                rows={2}
                value={data.deprecationMessage || ''}
                onChange={(e) => onChange('deprecationMessage', e.target.value)}
                helperText="Provide context about why it's deprecated and what to use instead"
                sx={{ mt: 2, bgcolor: 'warning.lighter' }}
              />
            )}

            <TextField
              label="Example"
              size={size}
              fullWidth
              multiline
              rows={2}
              value={data.example || ''}
              onChange={(e) => onChange('example', e.target.value)}
              helperText="JSON example value"
              sx={{ mt: 2 }}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end" sx={{ alignSelf: 'flex-start', mt: 1 }}>
                    <Tooltip title="Generate example based on property schema">
                      <IconButton
                        onClick={generateExample}
                        size="small"
                        edge="end"
                        sx={{ color: 'primary.main' }}
                      >
                        <AutoAwesomeIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </InputAdornment>
                ),
              }}
            />
          </Box>
        )}
      </Box>

      {/* VERTICAL DIVIDER */}
      <Box sx={{ bgcolor: 'divider' }} />

      {/* RIGHT COLUMN: Constraints & Options */}
      <Box sx={{ pl: 3 }}>
        {/* Section Header */}
        <Typography variant="h6" sx={{ mb: 3, fontWeight: 600 }}>
          Constraints
        </Typography>

        {/* Tuple mode message - constraints are per-position */}
        {data.tupleMode && isArray && (
          <Box sx={{ mb: 2, p: 2, bgcolor: 'info.main', color: 'info.contrastText', borderRadius: 1, opacity: 0.9 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Tuple Mode Active
            </Typography>
            <Typography variant="caption" sx={{ display: 'block' }}>
              Item-level constraints are defined per-position in the Tuple Mode section below.
              Each position in the tuple can have its own type and constraints.
            </Typography>
          </Box>
        )}

        {/* No constraints message for boolean and null types */}
        {(baseType === 'boolean' || baseType === 'null') && (
          <Box sx={{ mb: 2, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              No additional constraints
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {baseType === 'boolean'
                ? 'Boolean types have no additional constraints (values are true or false)'
                : 'Null type has no additional constraints (value is always null)'}
            </Typography>
          </Box>
        )}

        {/* String Constraints */}
        {baseType === 'string' && !data.tupleMode && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              String Constraints
            </Typography>
            {isArray && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                These constraints apply to each string item in the array
              </Typography>
            )}

            <TextField
              label="Format"
              size={size}
              fullWidth
              value={data.format || ''}
              onChange={(e) => onChange('format', e.target.value)}
              helperText="e.g., date, date-time, email, uri, uuid"
              sx={{ mb: 2 }}
            />

            <TextField
              label="Pattern (Regex)"
              size={size}
              fullWidth
              value={data.pattern || ''}
              onChange={(e) => onChange('pattern', e.target.value)}
              placeholder="e.g., ^[A-Z]{3}$"
              helperText="Regular expression pattern for validation"
              sx={{ mb: 2 }}
            />

            <RegexTester pattern={data.pattern || ''} />

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 2 }}>
              <TextField
                label="Min Length"
                type="number"
                size={size}
                fullWidth
                value={data.minLength || ''}
                onChange={(e) => onChange('minLength', e.target.value)}
                inputProps={{ min: 0 }}
              />
              <TextField
                label="Max Length"
                type="number"
                size={size}
                fullWidth
                value={data.maxLength || ''}
                onChange={(e) => onChange('maxLength', e.target.value)}
                inputProps={{ min: 0 }}
              />
            </Box>
          </Box>
        )}

        {/* Number/Integer Constraints */}
        {(baseType === 'number' || baseType === 'integer') && !data.tupleMode && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Numeric Constraints
            </Typography>
            {isArray && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                These constraints apply to each {baseType} item in the array
              </Typography>
            )}

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 2 }}>
              <Box>
                <TextField
                  label="Minimum"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.minimum || ''}
                  onChange={(e) => {
                    onChange('minimum', e.target.value);
                    // Set default type if not already set, clear if value is empty
                    if (e.target.value && !data.minimumType) {
                      onChange('minimumType', 'inclusive');
                    } else if (!e.target.value) {
                      onChange('minimumType', undefined);
                    }
                  }}
                />
                <Box sx={{ ml: 1, mt: 0.5 }}>
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.minimumType === 'inclusive' || !data.minimumType}
                        onChange={() => onChange('minimumType', 'inclusive')}
                        disabled={!data.minimum}
                        size={size}
                      />
                    }
                    label={<Typography variant="body2">Inclusive (≥)</Typography>}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.minimumType === 'exclusive'}
                        onChange={() => onChange('minimumType', 'exclusive')}
                        disabled={!data.minimum}
                        size={size}
                      />
                    }
                    label={<Typography variant="body2">Exclusive (&gt;)</Typography>}
                  />
                </Box>
              </Box>
              <Box>
                <TextField
                  label="Maximum"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.maximum || ''}
                  onChange={(e) => {
                    onChange('maximum', e.target.value);
                    // Set default type if not already set, clear if value is empty
                    if (e.target.value && !data.maximumType) {
                      onChange('maximumType', 'inclusive');
                    } else if (!e.target.value) {
                      onChange('maximumType', undefined);
                    }
                  }}
                />
                <Box sx={{ ml: 1, mt: 0.5 }}>
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.maximumType === 'inclusive' || !data.maximumType}
                        onChange={() => onChange('maximumType', 'inclusive')}
                        disabled={!data.maximum}
                        size={size}
                      />
                    }
                    label={<Typography variant="body2">Inclusive (≤)</Typography>}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.maximumType === 'exclusive'}
                        onChange={() => onChange('maximumType', 'exclusive')}
                        disabled={!data.maximum}
                        size={size}
                      />
                    }
                    label={<Typography variant="body2">Exclusive (&lt;)</Typography>}
                  />
                </Box>
              </Box>
            </Box>

            <TextField
              label="Multiple Of"
              type="number"
              size={size}
              fullWidth
              value={data.multipleOf || ''}
              onChange={(e) => onChange('multipleOf', e.target.value)}
              helperText="Value must be a multiple of this number"
              sx={{ mb: 2 }}
            />
          </Box>
        )}

        {/* Array Constraints */}
        {isArray && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Array Constraints
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 2 }}>
              <TextField
                label="Min Items"
                type="number"
                size={size}
                fullWidth
                value={data.minItems || ''}
                onChange={(e) => onChange('minItems', e.target.value)}
                inputProps={{ min: 0 }}
              />
              <TextField
                label="Max Items"
                type="number"
                size={size}
                fullWidth
                value={data.maxItems || ''}
                onChange={(e) => onChange('maxItems', e.target.value)}
                inputProps={{ min: 0 }}
              />
            </Box>

            <FormControlLabel
              control={
                <Checkbox
                  checked={data.uniqueItems || false}
                  onChange={(e) => onChange('uniqueItems', e.target.checked)}
                  size={size}
                />
              }
              label="Unique Items (no duplicates)"
            />

            <TextField
              label="Contains (JSON Schema)"
              size={size}
              fullWidth
              multiline
              rows={3}
              value={data.contains || ''}
              onChange={(e) => {
                onChange('contains', e.target.value);
                // Clear minContains/maxContains if contains is cleared
                if (!e.target.value.trim()) {
                  onChange('minContains', undefined);
                  onChange('maxContains', undefined);
                }
              }}
              placeholder='{"type": "string", "minLength": 5}'
              helperText="OpenAPI 3.1: JSON Schema that at least one item must match"
              sx={{ mt: 2 }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, ml: 0.5 }}>
              Example: Require at least one item to be a string with minimum length 5
            </Typography>

            {/* minContains and maxContains - only shown when contains is set */}
            {data.contains && data.contains.trim() && (
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mt: 2 }}>
                <TextField
                  label="Min Contains"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.minContains || ''}
                  onChange={(e) => onChange('minContains', e.target.value)}
                  inputProps={{ min: 1 }}
                  helperText="Minimum matching items"
                />
                <TextField
                  label="Max Contains"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.maxContains || ''}
                  onChange={(e) => onChange('maxContains', e.target.value)}
                  inputProps={{ min: 1 }}
                  helperText="Maximum matching items"
                />
              </Box>
            )}

            {/* Tuple Mode - OpenAPI 3.1 prefixItems */}
            <Box sx={{ mt: 3, p: 2, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={data.tupleMode || false}
                    onChange={(e) => {
                      onChange('tupleMode', e.target.checked);
                      if (!e.target.checked) {
                        // Clear prefixItems when disabling tuple mode
                        onChange('prefixItems', undefined);
                      } else if (!data.prefixItems) {
                        // Initialize with empty array when enabling
                        onChange('prefixItems', []);
                      }
                    }}
                    size={size}
                  />
                }
                label={
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      Tuple Mode (prefixItems)
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      OpenAPI 3.1: Define ordered schemas for specific positions
                    </Typography>
                  </Box>
                }
              />

              {data.tupleMode && (
                <Box sx={{ mt: 2 }}>
                  <PrefixItemsEditor
                    value={data.prefixItems || []}
                    onChange={(items) => onChange('prefixItems', items)}
                  />

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      Items Schema (for positions beyond prefix)
                    </Typography>
                    <TextField
                      fullWidth
                      multiline
                      rows={4}
                      size={size}
                      value={data.itemsSchema || ''}
                      onChange={(e) => onChange('itemsSchema', e.target.value)}
                      placeholder='{"type": "string"}'
                      helperText="JSON Schema for items beyond the defined prefix positions"
                      sx={{
                        fontFamily: 'monospace',
                        '& textarea': {
                          fontFamily: 'monospace',
                          fontSize: '0.875rem',
                        },
                      }}
                    />
                  </Box>
                </Box>
              )}
            </Box>
          </Box>
        )}

        {/* Enum Values */}
        {(baseType === 'string' || baseType === 'number' || baseType === 'integer') && (
          <Box sx={{ mb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="body2" color="text.secondary">
                Allowed Values (Enum)
              </Typography>
              {data.enum && data.enum.length > 1 && (
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  <Tooltip title="Sort A-Z (ascending)">
                    <IconButton
                      onClick={handleSortEnumAZ}
                      size="small"
                      sx={{
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 0.5,
                      }}
                    >
                      <SortByAlphaIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Sort Z-A (descending)">
                    <IconButton
                      onClick={handleSortEnumZA}
                      size="small"
                      sx={{
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 0.5,
                        transform: 'scaleY(-1)',
                      }}
                    >
                      <SortByAlphaIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </Box>
              )}
            </Box>
            {isArray && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Enum values apply to each item in the array
              </Typography>
            )}

            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
              <TextField
                label="Add Enum Value"
                size={size}
                fullWidth
                type={baseType === 'string' ? 'text' : 'number'}
                value={enumInput}
                onChange={(e) => {
                  setEnumInput(e.target.value);
                  setEnumError('');
                }}
                onKeyDown={handleEnumKeyPress}
                error={!!enumError}
                helperText={enumError || `Enter a ${baseType} value and press Enter`}
                placeholder={
                  baseType === 'integer' ? 'e.g., 1, 2, 3' :
                  baseType === 'number' ? 'e.g., 1.5, 2.0, 3.14' :
                  'e.g., "active", "pending"'
                }
              />
            <IconButton
              onClick={handleAddEnum}
              color="primary"
              disabled={!enumInput.trim()}
            >
              <AddIcon />
            </IconButton>
          </Box>

          {data.enum && data.enum.length > 0 && (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleEnumDragEnd}
            >
              <List
                dense
                sx={{
                  bgcolor: 'action.hover',
                  borderRadius: 1,
                  maxHeight: 200,
                  overflow: 'auto',
                  border: 1,
                  borderColor: 'divider',
                }}
              >
                <SortableContext
                  items={data.enum}
                  strategy={verticalListSortingStrategy}
                >
                  {data.enum.map((value, index) => (
                    <SortableEnumItem
                      key={value}
                      id={value}
                      value={value}
                      onDelete={handleRemoveEnum}
                    />
                  ))}
                </SortableContext>
              </List>
            </DndContext>
          )}
          </Box>
        )}

        {/* Object Schema Settings */}
        {baseType === 'object' && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Schema Settings
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              Additional Properties
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, ml: 1 }}>
              <Box>
                <FormControlLabel
                  control={
                    <Radio
                      checked={data.additionalProperties === 'default'}
                      onChange={() => onChange('additionalProperties', 'default')}
                      value="default"
                      size={size === 'small' ? 'small' : 'medium'}
                    />
                  }
                  label="Default"
                  sx={{ mb: 0.5 }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4 }}>
                  Use JSON Schema default (allows additional properties)
                </Typography>
              </Box>
              <Box>
                <FormControlLabel
                  control={
                    <Radio
                      checked={data.additionalProperties === 'true'}
                      onChange={() => onChange('additionalProperties', 'true')}
                      value="true"
                      size={size === 'small' ? 'small' : 'medium'}
                    />
                  }
                  label="Allow Additional"
                  sx={{ mb: 0.5 }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4 }}>
                  Explicitly allow any additional properties
                </Typography>
              </Box>
              <Box>
                <FormControlLabel
                  control={
                    <Radio
                      checked={data.additionalProperties === 'false'}
                      onChange={() => onChange('additionalProperties', 'false')}
                      value="false"
                      size={size === 'small' ? 'small' : 'medium'}
                    />
                  }
                  label="Strict Schema"
                  sx={{ mb: 0.5 }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4 }}>
                  Only defined properties allowed (additionalProperties: false)
                </Typography>
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
};


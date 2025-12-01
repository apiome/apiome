'use client';

import React from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Chip from '@mui/material/Chip';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import InputAdornment from '@mui/material/InputAdornment';
import Tooltip from '@mui/material/Tooltip';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import Collapse from '@mui/material/Collapse';
import { RegexTester } from './RegexTester';

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
  exclusiveMinimum?: boolean;
  exclusiveMaximum?: boolean;
  multipleOf?: string;

  // Array constraints
  minItems?: string;
  maxItems?: string;
  uniqueItems?: boolean;

  // Common constraints
  enum?: string[];
  default?: string;

  // Metadata
  required?: boolean;
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  example?: string;
}

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
  const [objectPropsExpanded, setObjectPropsExpanded] = React.useState(false);

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
            exampleValue = parseFloat(data.minimum) + (data.exclusiveMinimum ? 0.1 : 0);
          } else if (data.maximum) {
            exampleValue = parseFloat(data.maximum) - (data.exclusiveMaximum ? 0.1 : 0);
          } else {
            exampleValue = 42.5;
          }
          break;

        case 'integer':
          if (data.minimum) {
            exampleValue = Math.ceil(parseFloat(data.minimum) + (data.exclusiveMinimum ? 1 : 0));
          } else if (data.maximum) {
            exampleValue = Math.floor(parseFloat(data.maximum) - (data.exclusiveMaximum ? 1 : 0));
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

  return (
    <Box>
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
        rows={2}
        value={data.description || ''}
        onChange={(e) => onChange('description', e.target.value)}
        helperText="Optional description for the property"
        sx={{ mb: 2 }}
      />

      {/* Object Properties Section */}
      {baseType === 'object' && (
        <Box sx={{ mb: 2 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              p: 1.5,
              bgcolor: 'action.hover',
              borderRadius: 1,
              cursor: nestedProperties && nestedProperties.length > 0 ? 'pointer' : 'default',
            }}
            onClick={() => {
              if (nestedProperties && nestedProperties.length > 0) {
                setObjectPropsExpanded(!objectPropsExpanded);
              }
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="body2" color="text.secondary" fontWeight={500}>
                Object Properties
              </Typography>
              <Chip
                label={nestedProperties ? nestedProperties.length : 0}
                size="small"
                color={nestedProperties && nestedProperties.length > 0 ? 'primary' : 'default'}
                sx={{ height: 20, fontSize: '0.75rem' }}
              />
            </Box>
            {nestedProperties && nestedProperties.length > 0 && (
              <IconButton size="small" sx={{ p: 0 }}>
                {objectPropsExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
            )}
          </Box>

          {isArray && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, ml: 1 }}>
              This object type is the item type of an array
            </Typography>
          )}

          {nestedProperties && nestedProperties.length > 0 && (
            <Collapse in={objectPropsExpanded}>
              <Box sx={{ mt: 2, pl: 2, borderLeft: 2, borderColor: 'divider' }}>
                <List dense>
                  {nestedProperties.map((prop) => {
                    const propData = typeof prop.data === 'string'
                      ? JSON.parse(prop.data)
                      : (prop.data || {});

                    // Determine type display
                    let typeDisplay = propData.type || 'any';
                    if (propData.$ref) {
                      const refParts = propData.$ref.split('/');
                      typeDisplay = refParts[refParts.length - 1] || propData.$ref;
                    } else if (propData.type === 'array' && propData.items) {
                      if (propData.items.$ref) {
                        const refParts = propData.items.$ref.split('/');
                        typeDisplay = `${refParts[refParts.length - 1] || propData.items.$ref}[]`;
                      } else {
                        typeDisplay = `${propData.items.type || 'any'}[]`;
                      }
                    }

                    return (
                      <ListItem
                        key={prop.id}
                        sx={{
                          py: 0.5,
                          px: 1,
                          bgcolor: 'background.paper',
                          borderRadius: 0.5,
                          mb: 0.5,
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography
                                variant="body2"
                                sx={{ fontFamily: 'monospace', fontWeight: 500 }}
                              >
                                {prop.name}
                              </Typography>
                              <Chip
                                label={typeDisplay}
                                size="small"
                                variant="outlined"
                                sx={{ height: 18, fontSize: '0.7rem' }}
                              />
                            </Box>
                          }
                          secondary={
                            prop.description && (
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{ display: 'block', mt: 0.5 }}
                              >
                                {prop.description}
                              </Typography>
                            )
                          }
                        />
                      </ListItem>
                    );
                  })}
                </List>
              </Box>
            </Collapse>
          )}

          {(!nestedProperties || nestedProperties.length === 0) && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, ml: 1 }}>
              No properties defined for this object
            </Typography>
          )}
        </Box>
      )}

      {/* String Constraints */}
      {baseType === 'string' && (
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
      {(baseType === 'number' || baseType === 'integer') && (
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
                onChange={(e) => onChange('minimum', e.target.value)}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={data.exclusiveMinimum || false}
                    onChange={(e) => onChange('exclusiveMinimum', e.target.checked)}
                    disabled={!data.minimum}
                    size={size}
                  />
                }
                label={<Typography>Exclusive Minimum</Typography>}
                sx={{ mt: 0.5 }}
              />
            </Box>
            <Box>
              <TextField
                label="Maximum"
                type="number"
                size={size}
                fullWidth
                value={data.maximum || ''}
                onChange={(e) => onChange('maximum', e.target.value)}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={data.exclusiveMaximum || false}
                    onChange={(e) => onChange('exclusiveMaximum', e.target.checked)}
                    disabled={!data.maximum}
                    size={size}
                  />
                }
                label={<Typography>Exclusive Maximum</Typography>}
                sx={{ mt: 0.5 }}
              />
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
        </Box>
      )}

      {/* Enum Values */}
      {(baseType === 'string' || baseType === 'number' || baseType === 'integer') && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Allowed Values (Enum)
          </Typography>
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
          <List dense sx={{ bgcolor: 'action.hover', borderRadius: 1, maxHeight: 150, overflow: 'auto' }}>
            {data.enum.map((value, index) => (
              <ListItem
                key={index}
                secondaryAction={
                  <IconButton edge="end" onClick={() => handleRemoveEnum(value)} size="small">
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                }
                sx={{
                  borderBottom: index < data.enum!.length - 1 ? 1 : 0,
                  borderColor: 'divider'
                }}
              >
                <ListItemText
                  primary={value}
                  primaryTypographyProps={{
                    fontFamily: 'monospace',
                    fontSize: '0.875rem'
                  }}
                />
              </ListItem>
            ))}
          </List>
        )}
        </Box>
      )}

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
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Metadata
          </Typography>

          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
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
          </Box>

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
  );
};


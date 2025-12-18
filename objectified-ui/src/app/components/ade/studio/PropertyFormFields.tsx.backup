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
import { useColorScheme } from '@mui/material/styles';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import SortByAlphaIcon from '@mui/icons-material/SortByAlpha';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import TuneIcon from '@mui/icons-material/Tune';
import SettingsIcon from '@mui/icons-material/Settings';
import CodeIcon from '@mui/icons-material/Code';
import Collapse from '@mui/material/Collapse';
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
import { ExtensionsEditor } from './ExtensionsEditor';

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

  // unevaluatedItems (OpenAPI 3.1/JSON Schema 2020-12)
  unevaluatedItems?: 'default' | 'allow' | 'disallow' | 'schema'; // Control for items not matched by prefixItems, items, or contains
  unevaluatedItemsSchema?: string; // JSON string of schema when unevaluatedItems is 'schema'

  // Common constraints
  enum?: string[];
  const?: string; // OpenAPI 3.1: Constant value (mutually exclusive with enum)
  default?: string;

  // Composition constraints
  not?: string; // OpenAPI 3.1: JSON Schema that the data must NOT match

  // Metadata
  required?: boolean;
  nullable?: boolean; // OpenAPI 3.1: Outputs type as array like ['string', 'null']
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  deprecationMessage?: string;
  examples?: string[]; // Array of example values (JSON strings)

  // Object constraints
  additionalProperties?: 'default' | 'true' | 'false';
  minProperties?: string;
  maxProperties?: string;
  propertyNamesPattern?: string;
  propertyNamesMinLength?: string;
  propertyNamesMaxLength?: string;

  // unevaluatedProperties (OpenAPI 3.1/JSON Schema 2020-12) - for objects
  unevaluatedProperties?: 'default' | 'allow' | 'disallow' | 'schema'; // Control for properties not matched by properties, patternProperties, or inherited schemas
  unevaluatedPropertiesSchema?: string; // JSON string of schema when unevaluatedProperties is 'schema'

  // Extensions (x- prefixed properties)
  extensions?: Record<string, any>;

  // External Documentation
  externalDocsUrl?: string;
  externalDocsDescription?: string;
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
        borderBottom: '1px solid #f1f5f9',
        backgroundColor: isDragging ? 'rgba(99, 102, 241, 0.08)' : 'transparent',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        pl: 1.5,
        pr: 1.5,
        py: 1,
        transition: 'background-color 0.2s ease',
        '&:hover': {
          backgroundColor: 'rgba(99, 102, 241, 0.04)',
        },
        '&:last-child': {
          borderBottom: 'none',
        },
      }}
    >
      <IconButton
        {...attributes}
        {...listeners}
        size="small"
        sx={{
          cursor: 'grab',
          '&:active': { cursor: 'grabbing' },
          color: '#94a3b8',
          flex: 0,
          p: 0.5,
          transition: 'color 0.2s ease',
          '&:hover': { color: '#6366f1' },
        }}
      >
        <DragIndicatorIcon fontSize="small" />
      </IconButton>
      <ListItemText
        primary={value}
        primaryTypographyProps={{
          fontFamily: '"JetBrains Mono", "Fira Code", monospace',
          fontSize: '0.875rem',
          color: '#334155',
        }}
        sx={{ flex: 1, my: 0 }}
      />
      <IconButton
        edge="end"
        onClick={() => onDelete(value)}
        size="small"
        sx={{
          flex: 0,
          color: '#94a3b8',
          transition: 'all 0.2s ease',
          '&:hover': {
            color: '#ef4444',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
          },
        }}
      >
        <DeleteIcon fontSize="small" />
      </IconButton>
    </ListItem>
  );
};

// Section header component for consistent styling across form sections
interface SectionHeaderProps {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  badge?: string;
}

const SectionHeader: React.FC<SectionHeaderProps> = ({ icon, title, subtitle, badge }) => {
  const { mode: colorMode, systemMode } = useColorScheme();
  const isDark = colorMode === 'dark' || (colorMode === 'system' && systemMode === 'dark');

  return (
    <Box sx={{
      display: 'flex',
      alignItems: 'center',
      gap: 1.5,
      mb: 2.5,
      pb: 1.5,
      borderBottom: '1px solid',
      borderColor: 'rgba(99, 102, 241, 0.1)',
    }}>
      <Box sx={{
        p: 1,
        borderRadius: 1.5,
        bgcolor: 'rgba(99, 102, 241, 0.1)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        {icon}
      </Box>
      <Box sx={{ flex: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b', letterSpacing: '-0.01em' }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {badge && (
        <Typography variant="caption" sx={{
          px: 1.5,
          py: 0.5,
          bgcolor: isDark ? 'linear-gradient(135deg, #312e81 0%, #4338ca 100%)' : 'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)',
          background: isDark ? 'linear-gradient(135deg, #312e81 0%, #4338ca 100%)' : 'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)',
          color: isDark ? '#c7d2fe' : '#4338ca',
          borderRadius: 2,
          fontWeight: 600,
          fontSize: '0.7rem',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}>
          {badge}
        </Typography>
      )}
    </Box>
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
  const { mode: colorMode, systemMode } = useColorScheme();
  const isDark = colorMode === 'dark' || (colorMode === 'system' && systemMode === 'dark');

  const [enumInput, setEnumInput] = React.useState('');
  const [enumError, setEnumError] = React.useState('');
  const [exampleInput, setExampleInput] = React.useState('');
  const [exampleError, setExampleError] = React.useState('');

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

    // Convert to JSON string and add to examples array
    const jsonString = JSON.stringify(exampleValue, null, 2);
    const currentExamples = data.examples || [];
    onChange('examples', [...currentExamples, jsonString]);
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

    // Clear const if it's set when adding enum values
    if (data.const) {
      onChange('const', undefined);
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

  const handleAddExample = () => {
    const trimmedValue = exampleInput.trim();
    if (!trimmedValue) {
      setExampleError('Example value cannot be empty');
      return;
    }

    // Validate JSON
    try {
      JSON.parse(trimmedValue);
    } catch (e) {
      setExampleError('Example must be valid JSON');
      return;
    }

    onChange('examples', [...(data.examples || []), trimmedValue]);
    setExampleInput('');
    setExampleError('');
  };

  const handleRemoveExample = (index: number) => {
    onChange('examples', (data.examples || []).filter((_, i) => i !== index));
  };

  const handleExampleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAddExample();
    }
  };

  return (
    <Box sx={{
      display: 'flex',
      flexDirection: 'column',
      gap: 0,
      bgcolor: isDark ? '#0f172a' : '#f8fafc',
      minHeight: '100%',
    }}>
      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 1: Basic Information
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box sx={{
        p: 3,
        bgcolor: isDark ? '#1e293b' : 'white',
        borderBottom: '1px solid #e2e8f0',
      }}>
        <SectionHeader
          icon={<InfoOutlinedIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Basic Information"
          subtitle="Core property details"
        />

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 2fr' }, gap: 2.5 }}>
          {showTitle && (
            <TextField
              label="Title"
              size={size}
              fullWidth
              value={data.title || ''}
              onChange={(e) => onChange('title', e.target.value)}
              helperText="Display title"
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: 2,
                  transition: 'all 0.2s ease',
                  '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.02)' },
                  '&.Mui-focused': { bgcolor: 'rgba(99, 102, 241, 0.04)' },
                },
              }}
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
            helperText="What this property represents"
            sx={{
              gridColumn: showTitle ? 'auto' : '1 / -1',
              '& .MuiOutlinedInput-root': {
                borderRadius: 2,
                transition: 'all 0.2s ease',
                '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.02)' },
                '&.Mui-focused': { bgcolor: 'rgba(99, 102, 241, 0.04)' },
              },
            }}
          />
        </Box>

        {/* Default and Example in a row */}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2.5, mt: 2.5 }}>
          <TextField
            label="Default Value"
            size={size}
            fullWidth
            value={data.default || ''}
            onChange={(e) => onChange('default', e.target.value)}
            helperText="JSON default value"
            sx={{
              '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.875rem' },
              '& .MuiOutlinedInput-root': {
                borderRadius: 2,
                transition: 'all 0.2s ease',
                '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.02)' },
              },
            }}
          />

          <Box sx={{ gridColumn: showTitle ? 'auto' : '1 / -1' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#334155' }}>
                Examples
              </Typography>
              <Tooltip title="Generate example based on schema" arrow>
                <IconButton
                  onClick={generateExample}
                  size="small"
                  sx={{
                    color: '#6366f1',
                    transition: 'all 0.2s ease',
                    '&:hover': {
                      bgcolor: 'rgba(99, 102, 241, 0.1)',
                      transform: 'scale(1.1)',
                    },
                  }}
                >
                  <AutoAwesomeIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>

            <TextField
              label="Add Example"
              size={size}
              fullWidth
              multiline
              rows={2}
              value={exampleInput}
              onChange={(e) => {
                setExampleInput(e.target.value);
                setExampleError('');
              }}
              onKeyDown={handleExampleKeyPress}
              error={!!exampleError}
              helperText={exampleError || "Enter JSON value (Shift+Enter for new line, Enter to add)"}
              sx={{
                '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.875rem' },
                '& .MuiOutlinedInput-root': {
                  borderRadius: 2,
                  transition: 'all 0.2s ease',
                  '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.02)' },
                },
              }}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <Tooltip title="Add example" arrow>
                      <IconButton
                        onClick={handleAddExample}
                        size="small"
                        disabled={!exampleInput.trim()}
                        sx={{
                          color: '#6366f1',
                          transition: 'all 0.2s ease',
                          '&:hover': {
                            bgcolor: 'rgba(99, 102, 241, 0.1)',
                          },
                        }}
                      >
                        <AddIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </InputAdornment>
                ),
              }}
            />

            {/* Examples List */}
            {data.examples && data.examples.length > 0 && (
              <Box sx={{
                mt: 2,
                p: 2,
                bgcolor: isDark ? '#1e293b' : '#f8fafc',
                borderRadius: 2,
                border: '1px solid',
                borderColor: isDark ? '#334155' : '#e2e8f0',
              }}>
                <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', mb: 1, display: 'block' }}>
                  {data.examples.length} example{data.examples.length !== 1 ? 's' : ''}
                </Typography>
                <List sx={{ p: 0 }}>
                  {data.examples.map((example, index) => (
                    <ListItem
                      key={index}
                      sx={{
                        borderBottom: index < data.examples!.length - 1 ? '1px solid' : 'none',
                        borderColor: isDark ? '#334155' : '#e2e8f0',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 1,
                        px: 0,
                        py: 1.5,
                      }}
                    >
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography
                          variant="body2"
                          sx={{
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                            fontSize: '0.75rem',
                            color: isDark ? '#cbd5e1' : '#334155',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {example}
                        </Typography>
                      </Box>
                      <IconButton
                        edge="end"
                        onClick={() => handleRemoveExample(index)}
                        size="small"
                        sx={{
                          flex: 0,
                          color: '#94a3b8',
                          transition: 'all 0.2s ease',
                          '&:hover': {
                            color: '#ef4444',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                          },
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        </Box>
      </Box>

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 2: Property Behavior (Metadata flags)
          ═══════════════════════════════════════════════════════════════════════════ */}
      {showMetadata && (
        <Box sx={{
          p: 3,
          borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
          bgcolor: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
          background: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
        }}>
          <SectionHeader
            icon={<TuneIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
            title="Property Behavior"
            subtitle="Access and visibility controls"
          />

          <Box sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(5, 1fr)' },
            gap: 2
          }}>
            {/* Required */}
            <Box
              sx={{
                p: 2,
                bgcolor: data.required ? 'rgba(239, 68, 68, 0.08)' : 'white',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: data.required ? 'rgba(239, 68, 68, 0.3)' : '#e2e8f0',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.5,
                boxShadow: data.required ? '0 4px 12px rgba(239, 68, 68, 0.15)' : '0 1px 3px rgba(0,0,0,0.05)',
                '&:hover': {
                  borderColor: data.required ? '#ef4444' : '#94a3b8',
                  transform: 'translateY(-2px)',
                  boxShadow: data.required ? '0 6px 16px rgba(239, 68, 68, 0.2)' : '0 4px 12px rgba(0,0,0,0.1)',
                }
              }}
              onClick={() => onChange('required', !data.required)}
            >
              <Checkbox
                checked={data.required || false}
                size="small"
                sx={{
                  p: 0,
                  pointerEvents: 'none',
                  color: data.required ? '#ef4444' : undefined,
                  '&.Mui-checked': { color: '#ef4444' },
                }}
                tabIndex={-1}
              />
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, color: data.required ? '#dc2626' : '#334155' }}>
                  Required
                </Typography>
                <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                  Must be provided
                </Typography>
              </Box>
            </Box>

            {/* Nullable (OpenAPI 3.1) */}
            <Box
              sx={{
                p: 2,
                bgcolor: data.nullable ? 'rgba(168, 85, 247, 0.08)' : 'white',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: data.nullable ? 'rgba(168, 85, 247, 0.3)' : '#e2e8f0',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.5,
                boxShadow: data.nullable ? '0 4px 12px rgba(168, 85, 247, 0.15)' : '0 1px 3px rgba(0,0,0,0.05)',
                '&:hover': {
                  borderColor: data.nullable ? '#a855f7' : '#94a3b8',
                  transform: 'translateY(-2px)',
                  boxShadow: data.nullable ? '0 6px 16px rgba(168, 85, 247, 0.2)' : '0 4px 12px rgba(0,0,0,0.1)',
                }
              }}
              onClick={() => onChange('nullable', !data.nullable)}
            >
              <Checkbox
                checked={data.nullable || false}
                size="small"
                sx={{
                  p: 0,
                  pointerEvents: 'none',
                  color: data.nullable ? '#a855f7' : undefined,
                  '&.Mui-checked': { color: '#a855f7' },
                }}
                tabIndex={-1}
              />
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, color: data.nullable ? '#9333ea' : '#334155' }}>
                  Nullable
                </Typography>
                <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                  Can be null
                </Typography>
              </Box>
            </Box>

            {/* Read Only */}
            <Box
              sx={{
                p: 2,
                bgcolor: data.readOnly ? 'rgba(59, 130, 246, 0.08)' : 'white',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: data.readOnly ? 'rgba(59, 130, 246, 0.3)' : '#e2e8f0',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.5,
                boxShadow: data.readOnly ? '0 4px 12px rgba(59, 130, 246, 0.15)' : '0 1px 3px rgba(0,0,0,0.05)',
                '&:hover': {
                  borderColor: data.readOnly ? '#3b82f6' : '#94a3b8',
                  transform: 'translateY(-2px)',
                  boxShadow: data.readOnly ? '0 6px 16px rgba(59, 130, 246, 0.2)' : '0 4px 12px rgba(0,0,0,0.1)',
                }
              }}
              onClick={() => {
                onChange('readOnly', !data.readOnly);
                if (!data.readOnly) onChange('writeOnly', false);
              }}
            >
              <Checkbox
                checked={data.readOnly || false}
                size="small"
                sx={{
                  p: 0,
                  pointerEvents: 'none',
                  color: data.readOnly ? '#3b82f6' : undefined,
                  '&.Mui-checked': { color: '#3b82f6' },
                }}
                tabIndex={-1}
              />
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, color: data.readOnly ? '#2563eb' : '#334155' }}>
                  Read Only
                </Typography>
                <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                  Output only
                </Typography>
              </Box>
            </Box>

            {/* Write Only */}
            <Box
              sx={{
                p: 2,
                bgcolor: data.writeOnly ? 'rgba(34, 197, 94, 0.08)' : 'white',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: data.writeOnly ? 'rgba(34, 197, 94, 0.3)' : '#e2e8f0',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.5,
                boxShadow: data.writeOnly ? '0 4px 12px rgba(34, 197, 94, 0.15)' : '0 1px 3px rgba(0,0,0,0.05)',
                '&:hover': {
                  borderColor: data.writeOnly ? '#22c55e' : '#94a3b8',
                  transform: 'translateY(-2px)',
                  boxShadow: data.writeOnly ? '0 6px 16px rgba(34, 197, 94, 0.2)' : '0 4px 12px rgba(0,0,0,0.1)',
                }
              }}
              onClick={() => {
                onChange('writeOnly', !data.writeOnly);
                if (!data.writeOnly) onChange('readOnly', false);
              }}
            >
              <Checkbox
                checked={data.writeOnly || false}
                size="small"
                sx={{
                  p: 0,
                  pointerEvents: 'none',
                  color: data.writeOnly ? '#22c55e' : undefined,
                  '&.Mui-checked': { color: '#22c55e' },
                }}
                tabIndex={-1}
              />
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, color: data.writeOnly ? '#16a34a' : '#334155' }}>
                  Write Only
                </Typography>
                <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                  Input only
                </Typography>
              </Box>
            </Box>

            {/* Deprecated */}
            <Box
              sx={{
                p: 2,
                bgcolor: data.deprecated ? 'rgba(245, 158, 11, 0.08)' : 'white',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: data.deprecated ? 'rgba(245, 158, 11, 0.3)' : '#e2e8f0',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.5,
                boxShadow: data.deprecated ? '0 4px 12px rgba(245, 158, 11, 0.15)' : '0 1px 3px rgba(0,0,0,0.05)',
                '&:hover': {
                  borderColor: data.deprecated ? '#f59e0b' : '#94a3b8',
                  transform: 'translateY(-2px)',
                  boxShadow: data.deprecated ? '0 6px 16px rgba(245, 158, 11, 0.2)' : '0 4px 12px rgba(0,0,0,0.1)',
                }
              }}
              onClick={() => onChange('deprecated', !data.deprecated)}
            >
              <Checkbox
                checked={data.deprecated || false}
                size="small"
                sx={{
                  p: 0,
                  pointerEvents: 'none',
                  color: data.deprecated ? '#f59e0b' : undefined,
                  '&.Mui-checked': { color: '#f59e0b' },
                }}
                tabIndex={-1}
              />
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, color: data.deprecated ? '#d97706' : '#334155' }}>
                  Deprecated
                </Typography>
                <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                  Avoid using
                </Typography>
              </Box>
            </Box>
          </Box>

          {/* Deprecation Message */}
          <Collapse in={data.deprecated} timeout={300}>
            <TextField
              label="Deprecation Message"
              size={size}
              fullWidth
              multiline
              rows={2}
              value={data.deprecationMessage || ''}
              onChange={(e) => onChange('deprecationMessage', e.target.value)}
              placeholder="e.g., Use newProperty instead. Will be removed in v2.0."
              sx={{
                mt: 2.5,
                bgcolor: isDark ? '#0f172a' : 'white',
                '& .MuiOutlinedInput-root': {
                  borderRadius: 2,
                  borderColor: 'rgba(245, 158, 11, 0.3)',
                },
              }}
            />
          </Collapse>
        </Box>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 3: Type-Specific Constraints
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box sx={{
        p: 3,
        borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
        bgcolor: isDark ? '#1e293b' : 'white',
      }}>
        <SectionHeader
          icon={<SettingsIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Constraints"
          subtitle="Validation rules for this property"
          badge={`${baseType}${isArray ? '[]' : ''}`}
        />

        {/* Tuple mode message */}
        {data.tupleMode && isArray && (
          <Box sx={{
            mb: 2.5,
            p: 2.5,
            bgcolor: isDark ? 'rgba(59, 130, 246, 0.15)' : 'rgba(59, 130, 246, 0.06)',
            border: '1px solid rgba(59, 130, 246, 0.2)',
            borderRadius: 2.5,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 2,
          }}>
            <Box sx={{
              p: 0.75,
              borderRadius: 1.5,
              bgcolor: isDark ? 'rgba(59, 130, 246, 0.25)' : 'rgba(59, 130, 246, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              mt: 0.25,
            }}>
              <TuneIcon sx={{ fontSize: 16, color: '#2563eb' }} />
            </Box>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5, color: '#1e40af' }}>
                Tuple Mode Active
              </Typography>
              <Typography variant="caption" sx={{ color: '#475569', lineHeight: 1.5 }}>
                Item-level constraints are defined per-position below. Each position can have its own type and constraints.
              </Typography>
            </Box>
          </Box>
        )}

        {/* No constraints message for boolean and null types */}
        {(baseType === 'boolean' || baseType === 'null') && (
          <Box sx={{
            p: 4,
            bgcolor: isDark ? '#1e293b' : '#f8fafc',
            borderRadius: 2.5,
            border: isDark ? '2px dashed #475569' : '2px dashed #e2e8f0',
            textAlign: 'center',
          }}>
            <Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#64748b', fontStyle: 'italic', mb: 0.5 }}>
              No additional constraints available
            </Typography>
            <Typography variant="caption" sx={{ color: isDark ? '#64748b' : '#94a3b8' }}>
              {baseType === 'boolean'
                ? 'Boolean values are either true or false'
                : 'Null type is always null'}
            </Typography>
          </Box>
        )}

        {/* String Constraints */}
        {baseType === 'string' && !data.tupleMode && (
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
            background: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
            borderRadius: 2.5,
            border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 2, color: isDark ? '#e2e8f0' : '#334155', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box component="span" sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#6366f1',
              }} />
              String Constraints
              {isArray && <Typography component="span" variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', ml: 1 }}>(per item)</Typography>}
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2.5, mb: 2.5 }}>
              <TextField
                label="Format"
                size={size}
                fullWidth
                value={data.format || ''}
                onChange={(e) => onChange('format', e.target.value)}
                placeholder="date, email, uri, uuid..."
                helperText="Standard format hint"
                sx={{
                  bgcolor: isDark ? '#0f172a' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />

              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
                <TextField
                  label="Min Length"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.minLength || ''}
                  onChange={(e) => onChange('minLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  sx={{
                    bgcolor: isDark ? '#0f172a' : 'white',
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                  }}
                />
                <TextField
                  label="Max Length"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.maxLength || ''}
                  onChange={(e) => onChange('maxLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  sx={{
                    bgcolor: isDark ? '#0f172a' : 'white',
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                  }}
                />
              </Box>
            </Box>

            <TextField
              label="Pattern (Regex)"
              size={size}
              fullWidth
              value={data.pattern || ''}
              onChange={(e) => onChange('pattern', e.target.value)}
              placeholder="e.g., ^[A-Z]{3}$"
              helperText="Regular expression for validation"
              sx={{
                mb: 1.5,
                bgcolor: isDark ? '#0f172a' : 'white',
                '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.875rem' },
                '& .MuiOutlinedInput-root': { borderRadius: 2 },
              }}
            />

            <RegexTester pattern={data.pattern || ''} />
          </Box>
        )}

        {/* Number/Integer Constraints */}
        {(baseType === 'number' || baseType === 'integer') && !data.tupleMode && (
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
            background: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
            borderRadius: 2.5,
            border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 2, color: isDark ? '#e2e8f0' : '#334155', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box component="span" sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#8b5cf6',
              }} />
              Numeric Constraints
              {isArray && <Typography component="span" variant="caption" sx={{ color: '#64748b', ml: 1 }}>(per item)</Typography>}
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2.5, mb: 2.5 }}>
              {/* Minimum */}
              <Box sx={{
                p: 2,
                bgcolor: isDark ? '#0f172a' : 'white',
                borderRadius: 2,
                border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
              }}>
                <TextField
                  label="Minimum"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.minimum || ''}
                  onChange={(e) => {
                    onChange('minimum', e.target.value);
                    if (e.target.value && !data.minimumType) {
                      onChange('minimumType', 'inclusive');
                    } else if (!e.target.value) {
                      onChange('minimumType', undefined);
                    }
                  }}
                  sx={{
                    mb: 1.5,
                    '& .MuiOutlinedInput-root': { borderRadius: 1.5 },
                  }}
                />
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.minimumType === 'inclusive' || !data.minimumType}
                        onChange={() => onChange('minimumType', 'inclusive')}
                        disabled={!data.minimum}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                      />
                    }
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>≥ inclusive</Typography>}
                    sx={{ m: 0 }}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.minimumType === 'exclusive'}
                        onChange={() => onChange('minimumType', 'exclusive')}
                        disabled={!data.minimum}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                      />
                    }
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>&gt; exclusive</Typography>}
                    sx={{ m: 0 }}
                  />
                </Box>
              </Box>

              {/* Maximum */}
              <Box sx={{
                p: 2,
                bgcolor: isDark ? '#0f172a' : 'white',
                borderRadius: 2,
                border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
              }}>
                <TextField
                  label="Maximum"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.maximum || ''}
                  onChange={(e) => {
                    onChange('maximum', e.target.value);
                    if (e.target.value && !data.maximumType) {
                      onChange('maximumType', 'inclusive');
                    } else if (!e.target.value) {
                      onChange('maximumType', undefined);
                    }
                  }}
                  sx={{
                    mb: 1.5,
                    '& .MuiOutlinedInput-root': { borderRadius: 1.5 },
                  }}
                />
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.maximumType === 'inclusive' || !data.maximumType}
                        onChange={() => onChange('maximumType', 'inclusive')}
                        disabled={!data.maximum}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                      />
                    }
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>≤ inclusive</Typography>}
                    sx={{ m: 0 }}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.maximumType === 'exclusive'}
                        onChange={() => onChange('maximumType', 'exclusive')}
                        disabled={!data.maximum}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                      />
                    }
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>&lt; exclusive</Typography>}
                    sx={{ m: 0 }}
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
              helperText="Value must be divisible by this number"
              sx={{
                bgcolor: isDark ? '#0f172a' : 'white',
                '& .MuiOutlinedInput-root': { borderRadius: 2 },
              }}
            />
          </Box>
        )}

        {/* Array Constraints */}
        {isArray && (
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? 'linear-gradient(135deg, #422006 0%, #713f12 100%)' : 'linear-gradient(135deg, #fefce8 0%, #fef9c3 100%)',
            background: isDark ? 'linear-gradient(135deg, #422006 0%, #713f12 100%)' : 'linear-gradient(135deg, #fefce8 0%, #fef9c3 100%)',
            borderRadius: 2.5,
            border: '1px solid rgba(250, 204, 21, 0.4)',
            mt: 2.5,
            boxShadow: '0 2px 8px rgba(250, 204, 21, 0.1)',
          }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 2, color: isDark ? '#fcd34d' : '#854d0e', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box component="span" sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#eab308',
              }} />
              Array Constraints
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' }, gap: 2, mb: 2.5 }}>
              <TextField
                label="Min Items"
                type="number"
                size={size}
                fullWidth
                value={data.minItems || ''}
                onChange={(e) => onChange('minItems', e.target.value)}
                inputProps={{ min: 0 }}
                sx={{
                  bgcolor: isDark ? '#1e293b' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
              <TextField
                label="Max Items"
                type="number"
                size={size}
                fullWidth
                value={data.maxItems || ''}
                onChange={(e) => onChange('maxItems', e.target.value)}
                inputProps={{ min: 0 }}
                sx={{
                  bgcolor: isDark ? '#1e293b' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                p: 1.5,
                bgcolor: data.uniqueItems ? 'rgba(34, 197, 94, 0.1)' : (isDark ? '#1e293b' : 'white'),
                borderRadius: 2,
                border: '1px solid',
                borderColor: data.uniqueItems ? 'rgba(34, 197, 94, 0.4)' : (isDark ? '#475569' : '#e2e8f0'),
                cursor: 'pointer',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: data.uniqueItems ? '0 2px 8px rgba(34, 197, 94, 0.15)' : 'none',
                '&:hover': {
                  borderColor: data.uniqueItems ? '#22c55e' : '#94a3b8',
                  transform: 'translateY(-1px)',
                },
              }}
              onClick={() => onChange('uniqueItems', !data.uniqueItems)}
              >
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={data.uniqueItems || false}
                      onChange={(e) => onChange('uniqueItems', e.target.checked)}
                      size="small"
                      sx={{ '&.Mui-checked': { color: '#22c55e' } }}
                    />
                  }
                  label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.uniqueItems ? '#16a34a' : (isDark ? '#94a3b8' : '#475569') }}>Unique Items</Typography>}
                  sx={{ m: 0 }}
                />
              </Box>
            </Box>

            {/* Contains Schema - collapsible advanced feature */}
            <Box sx={{
              p: 2,
              bgcolor: isDark ? '#1e293b' : 'white',
              borderRadius: 2,
              border: isDark ? '2px dashed #475569' : '2px dashed #e2e8f0',
            }}>
              <Typography variant="caption" sx={{ fontWeight: 600, color: isDark ? '#94a3b8' : '#64748b', display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                <CodeIcon sx={{ fontSize: 14 }} />
                Contains Schema (OpenAPI 3.1)
              </Typography>
              <TextField
                size={size}
                fullWidth
                multiline
                rows={2}
                value={data.contains || ''}
                onChange={(e) => {
                  onChange('contains', e.target.value);
                  if (!e.target.value.trim()) {
                    onChange('minContains', undefined);
                    onChange('maxContains', undefined);
                  }
                }}
                placeholder='{"type": "string", "minLength": 5}'
                helperText="At least one item must match this schema"
                sx={{
                  '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.8rem' },
                  '& .MuiOutlinedInput-root': { borderRadius: 1.5 },
                }}
              />

              <Collapse in={!!(data.contains && data.contains.trim())} timeout={300}>
                <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mt: 2 }}>
                  <TextField
                    label="Min Contains"
                    type="number"
                    size={size}
                    fullWidth
                    value={data.minContains || ''}
                    onChange={(e) => onChange('minContains', e.target.value)}
                    inputProps={{ min: 1 }}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: 1.5 } }}
                  />
                  <TextField
                    label="Max Contains"
                    type="number"
                    size={size}
                    fullWidth
                    value={data.maxContains || ''}
                    onChange={(e) => onChange('maxContains', e.target.value)}
                    inputProps={{ min: 1 }}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: 1.5 } }}
                  />
                </Box>
              </Collapse>
            </Box>

            {/* Tuple Mode - OpenAPI 3.1 prefixItems */}
            <Box sx={{
              mt: 2.5,
              p: 2,
              bgcolor: isDark ? '#1e293b' : 'white',
              borderRadius: 2,
              border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
            }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={data.tupleMode || false}
                    onChange={(e) => {
                      onChange('tupleMode', e.target.checked);
                      if (!e.target.checked) {
                        onChange('prefixItems', undefined);
                      } else if (!data.prefixItems) {
                        onChange('prefixItems', []);
                      }
                    }}
                    size="small"
                    sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                  />
                }
                label={
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#334155' }}>
                      Tuple Mode (prefixItems)
                    </Typography>
                    <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                      Define ordered schemas for specific array positions
                    </Typography>
                  </Box>
                }
                sx={{ m: 0 }}
              />

              <Collapse in={data.tupleMode} timeout={300}>
                <Box sx={{ mt: 2 }}>
                  <PrefixItemsEditor
                    value={data.prefixItems || []}
                    onChange={(items) => onChange('prefixItems', items)}
                  />

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600, color: '#64748b', display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <CodeIcon sx={{ fontSize: 14 }} />
                      Items Schema (beyond prefix positions)
                    </Typography>
                    <TextField
                      fullWidth
                      multiline
                      rows={3}
                      size={size}
                      value={data.itemsSchema || ''}
                      onChange={(e) => onChange('itemsSchema', e.target.value)}
                      placeholder='{"type": "string"}'
                      helperText="Schema for items beyond defined positions"
                      sx={{
                        '& textarea': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.8rem' },
                        '& .MuiOutlinedInput-root': { borderRadius: 1.5 },
                      }}
                    />
                  </Box>
                </Box>
              </Collapse>
            </Box>

            {/* Unevaluated Items - OpenAPI 3.1/JSON Schema 2020-12 advanced feature */}
            <Box sx={{
              mt: 2.5,
              p: 2,
              bgcolor: isDark ? '#1e293b' : 'white',
              borderRadius: 2,
              border: isDark ? '2px dashed #475569' : '2px dashed #e2e8f0',
            }}>
              <Typography variant="caption" sx={{ fontWeight: 600, color: isDark ? '#94a3b8' : '#64748b', display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                <TuneIcon sx={{ fontSize: 14 }} />
                Unevaluated Items (OpenAPI 3.1)
                <Tooltip title="Controls array items not matched by prefixItems, items, or contains. This is an advanced validation feature from JSON Schema 2020-12.">
                  <InfoOutlinedIcon sx={{ fontSize: 14, ml: 0.5, color: isDark ? '#64748b' : '#94a3b8', cursor: 'help' }} />
                </Tooltip>
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  <FormControlLabel
                    control={
                      <Radio
                        checked={!data.unevaluatedItems || data.unevaluatedItems === 'default'}
                        onChange={() => {
                          onChange('unevaluatedItems', 'default');
                          onChange('unevaluatedItemsSchema', undefined);
                        }}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#6366f1' } }}
                      />
                    }
                    label={<Typography variant="body2" sx={{ color: isDark ? '#cbd5e1' : '#475569' }}>Default (not set)</Typography>}
                    sx={{ m: 0 }}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.unevaluatedItems === 'allow'}
                        onChange={() => {
                          onChange('unevaluatedItems', 'allow');
                          onChange('unevaluatedItemsSchema', undefined);
                        }}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#22c55e' } }}
                      />
                    }
                    label={<Typography variant="body2" sx={{ color: isDark ? '#cbd5e1' : '#475569' }}>Allow any</Typography>}
                    sx={{ m: 0 }}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.unevaluatedItems === 'disallow'}
                        onChange={() => {
                          onChange('unevaluatedItems', 'disallow');
                          onChange('unevaluatedItemsSchema', undefined);
                        }}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#ef4444' } }}
                      />
                    }
                    label={<Typography variant="body2" sx={{ color: isDark ? '#cbd5e1' : '#475569' }}>Disallow</Typography>}
                    sx={{ m: 0 }}
                  />
                  <FormControlLabel
                    control={
                      <Radio
                        checked={data.unevaluatedItems === 'schema'}
                        onChange={() => onChange('unevaluatedItems', 'schema')}
                        size="small"
                        sx={{ '&.Mui-checked': { color: '#f59e0b' } }}
                      />
                    }
                    label={<Typography variant="body2" sx={{ color: isDark ? '#cbd5e1' : '#475569' }}>Specify schema</Typography>}
                    sx={{ m: 0 }}
                  />
                </Box>

                <Collapse in={data.unevaluatedItems === 'schema'} timeout={300}>
                  <Box sx={{ mt: 1.5 }}>
                    <TextField
                      fullWidth
                      multiline
                      rows={3}
                      size={size}
                      value={data.unevaluatedItemsSchema || ''}
                      onChange={(e) => onChange('unevaluatedItemsSchema', e.target.value)}
                      placeholder='{"type": "string", "maxLength": 100}'
                      helperText="Schema that unevaluated items must match"
                      sx={{
                        '& textarea': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.8rem' },
                        '& .MuiOutlinedInput-root': { borderRadius: 1.5 },
                      }}
                    />
                  </Box>
                </Collapse>
              </Box>
            </Box>
          </Box>
        )}

        {/* Object Constraints */}
        {baseType === 'object' && (
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? 'linear-gradient(135deg, #14532d 0%, #166534 100%)' : 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
            background: isDark ? 'linear-gradient(135deg, #14532d 0%, #166534 100%)' : 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
            borderRadius: 2.5,
            border: '1px solid rgba(34, 197, 94, 0.3)',
            boxShadow: '0 2px 8px rgba(34, 197, 94, 0.1)',
          }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 2, color: isDark ? '#86efac' : '#166534', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box component="span" sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#22c55e',
              }} />
              Object Constraints
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2.5, mb: 2.5 }}>
              <TextField
                label="Min Properties"
                type="number"
                size={size}
                fullWidth
                value={data.minProperties || ''}
                onChange={(e) => onChange('minProperties', e.target.value)}
                inputProps={{ min: 0 }}
                sx={{
                  bgcolor: isDark ? '#0f172a' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
              <TextField
                label="Max Properties"
                type="number"
                size={size}
                fullWidth
                value={data.maxProperties || ''}
                onChange={(e) => onChange('maxProperties', e.target.value)}
                inputProps={{ min: 0 }}
                sx={{
                  bgcolor: isDark ? '#0f172a' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
            </Box>

            <Box sx={{
              p: 2,
              bgcolor: isDark ? '#0f172a' : 'white',
              borderRadius: 2,
              border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
            }}>
              <Typography variant="caption" sx={{ fontWeight: 600, color: isDark ? '#94a3b8' : '#64748b', display: 'block', mb: 1.5 }}>
                Additional Properties
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'default'} onChange={() => onChange('additionalProperties', 'default')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Default (allows additional)</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'true'} onChange={() => onChange('additionalProperties', 'true')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Allow additional properties</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'false'} onChange={() => onChange('additionalProperties', 'false')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Strict (no extra properties)</Typography>}
                  sx={{ m: 0 }}
                />
              </Box>
            </Box>

            {/* Unevaluated Properties (OpenAPI 3.1 / JSON Schema 2020-12) */}
            <Box sx={{
              mt: 2.5,
              p: 2.5,
              bgcolor: isDark ? '#0f172a' : 'white',
              borderRadius: 2.5,
              border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                mb: 2,
                pb: 1.5,
                borderBottom: '1px solid rgba(99, 102, 241, 0.15)',
              }}>
                <Box sx={{
                  p: 0.75,
                  borderRadius: 1.5,
                  bgcolor: 'rgba(99, 102, 241, 0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <SettingsIcon sx={{ color: '#6366f1', fontSize: 16 }} />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
                    Unevaluated Properties
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                    Advanced control for inheritance scenarios
                  </Typography>
                </Box>
                <Typography variant="caption" sx={{
                  px: 1,
                  py: 0.25,
                  bgcolor: 'rgba(99, 102, 241, 0.1)',
                  color: '#4f46e5',
                  borderRadius: 1,
                  fontWeight: 600,
                  fontSize: '0.65rem',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  OpenAPI 3.1
                </Typography>
              </Box>

              <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', display: 'block', mb: 2 }}>
                Controls properties not matched by <code style={{ background: isDark ? '#1e293b' : '#f1f5f9', padding: '1px 4px', borderRadius: 3 }}>properties</code>, <code style={{ background: isDark ? '#1e293b' : '#f1f5f9', padding: '1px 4px', borderRadius: 3 }}>patternProperties</code>, or inherited schemas via <code style={{ background: isDark ? '#1e293b' : '#f1f5f9', padding: '1px 4px', borderRadius: 3 }}>allOf</code>.
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: data.unevaluatedProperties === 'schema' ? 2 : 0 }}>
                <FormControlLabel
                  control={<Radio checked={!data.unevaluatedProperties || data.unevaluatedProperties === 'default'} onChange={() => onChange('unevaluatedProperties', 'default')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Not specified (default)</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.unevaluatedProperties === 'allow'} onChange={() => onChange('unevaluatedProperties', 'allow')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Allow unevaluated properties</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.unevaluatedProperties === 'disallow'} onChange={() => onChange('unevaluatedProperties', 'disallow')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Disallow unevaluated properties</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.unevaluatedProperties === 'schema'} onChange={() => onChange('unevaluatedProperties', 'schema')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Must match schema</Typography>}
                  sx={{ m: 0 }}
                />
              </Box>

              {data.unevaluatedProperties === 'schema' && (
                <TextField
                  label="Schema for Unevaluated Properties"
                  size={size}
                  fullWidth
                  multiline
                  rows={3}
                  value={data.unevaluatedPropertiesSchema ?? ''}
                  onChange={(e) => onChange('unevaluatedPropertiesSchema', e.target.value)}
                  placeholder='{ "type": "string" }'
                  helperText="JSON Schema that unevaluated properties must match"
                  sx={{
                    '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.85rem' },
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                  }}
                />
              )}

              {data.unevaluatedProperties && data.unevaluatedProperties !== 'default' && (
                <Box sx={{
                  mt: 2,
                  p: 1.5,
                  bgcolor: 'rgba(99, 102, 241, 0.06)',
                  borderRadius: 1.5,
                  border: '1px solid rgba(99, 102, 241, 0.2)',
                }}>
                  <Typography variant="caption" sx={{ color: '#4f46e5', display: 'block' }}>
                    <strong>Tip:</strong> Use <code style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '1px 4px', borderRadius: 3 }}>unevaluatedProperties</code> when using schema composition (<code style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '1px 4px', borderRadius: 3 }}>allOf</code>) to control properties from all composed schemas. Unlike <code style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '1px 4px', borderRadius: 3 }}>additionalProperties</code>, it considers properties from inherited schemas.
                  </Typography>
                </Box>
              )}
            </Box>

            {/* Property Name Constraints */}
            <Box sx={{
              mt: 2.5,
              p: 2.5,
              bgcolor: isDark ? '#0f172a' : 'white',
              borderRadius: 2.5,
              border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                mb: 2,
                pb: 1.5,
                borderBottom: '1px solid rgba(139, 92, 246, 0.15)',
              }}>
                <Box sx={{
                  p: 0.75,
                  borderRadius: 1.5,
                  bgcolor: 'rgba(139, 92, 246, 0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <SortByAlphaIcon sx={{ color: '#8b5cf6', fontSize: 16 }} />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
                    Property Name Constraints
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                    Validate the names of properties, not their values
                  </Typography>
                </Box>
                <Typography variant="caption" sx={{
                  px: 1,
                  py: 0.25,
                  bgcolor: 'rgba(139, 92, 246, 0.1)',
                  color: '#7c3aed',
                  borderRadius: 1,
                  fontWeight: 600,
                  fontSize: '0.65rem',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  OpenAPI 3.1
                </Typography>
              </Box>

              <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mb: 2 }}>
                Define constraints for property names (keys) in this object. Useful for objects with dynamic keys like dictionaries or maps.
              </Typography>

              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 2 }}>
                <TextField
                  label="Min Length"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.propertyNamesMinLength ?? ''}
                  onChange={(e) => onChange('propertyNamesMinLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  placeholder="e.g., 1"
                  helperText="Minimum name length"
                  sx={{
                    bgcolor: isDark ? '#1e293b' : 'white',
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                  }}
                />
                <TextField
                  label="Max Length"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.propertyNamesMaxLength ?? ''}
                  onChange={(e) => onChange('propertyNamesMaxLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  placeholder="e.g., 50"
                  helperText="Maximum name length"
                  sx={{
                    bgcolor: isDark ? '#1e293b' : 'white',
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                  }}
                />
              </Box>

              <TextField
                label="Pattern (Regex)"
                size={size}
                fullWidth
                value={data.propertyNamesPattern ?? ''}
                onChange={(e) => onChange('propertyNamesPattern', e.target.value)}
                placeholder="e.g., ^[a-z][a-zA-Z0-9]*$"
                helperText="Regular expression that all property names must match"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Typography sx={{ fontFamily: 'monospace', color: '#94a3b8', fontSize: '0.875rem' }}>/</Typography>
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <InputAdornment position="end">
                      <Typography sx={{ fontFamily: 'monospace', color: '#94a3b8', fontSize: '0.875rem' }}>/</Typography>
                    </InputAdornment>
                  ),
                }}
                sx={{
                  '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace' },
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                  '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                }}
              />

              {(data.propertyNamesPattern ?? data.propertyNamesMinLength ?? data.propertyNamesMaxLength) && (
                <Box sx={{
                  mt: 2,
                  p: 2,
                  bgcolor: 'rgba(139, 92, 246, 0.06)',
                  borderRadius: 2,
                  border: '1px solid rgba(139, 92, 246, 0.2)',
                }}>
                  <Typography variant="caption" sx={{ color: '#6d28d9', display: 'block', fontWeight: 600, mb: 1 }}>
                    Property Name Rules:
                  </Typography>
                  <Box component="ul" sx={{ m: 0, pl: 2, '& li': { fontSize: '0.75rem', color: '#7c3aed', mb: 0.5 } }}>
                    {data.propertyNamesMinLength && (
                      <li>Names must be at least <code style={{ background: 'rgba(139, 92, 246, 0.15)', padding: '1px 4px', borderRadius: 3 }}>{data.propertyNamesMinLength}</code> characters</li>
                    )}
                    {data.propertyNamesMaxLength && (
                      <li>Names must be at most <code style={{ background: 'rgba(139, 92, 246, 0.15)', padding: '1px 4px', borderRadius: 3 }}>{data.propertyNamesMaxLength}</code> characters</li>
                    )}
                    {data.propertyNamesPattern && (
                      <li>Names must match: <code style={{ background: 'rgba(139, 92, 246, 0.15)', padding: '1px 4px', borderRadius: 3 }}>/{data.propertyNamesPattern}/</code></li>
                    )}
                  </Box>
                </Box>
              )}
            </Box>

            {/* Nested Properties Display */}
            {nestedProperties && nestedProperties.length > 0 && (
              <Box sx={{
                mt: 2.5,
                p: 2.5,
                bgcolor: isDark ? '#0f172a' : 'white',
                borderRadius: 2.5,
                border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <Box sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1.5,
                  mb: 2,
                  pb: 1.5,
                  borderBottom: '1px solid rgba(34, 197, 94, 0.15)',
                }}>
                  <Box sx={{
                    p: 0.75,
                    borderRadius: 1.5,
                    bgcolor: 'rgba(34, 197, 94, 0.1)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    <CodeIcon sx={{ color: '#22c55e', fontSize: 16 }} />
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
                      Nested Properties
                    </Typography>
                    <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                      {nestedProperties.length} propert{nestedProperties.length === 1 ? 'y' : 'ies'} defined within this object
                    </Typography>
                  </Box>
                  <Typography variant="caption" sx={{
                    px: 1,
                    py: 0.25,
                    bgcolor: 'rgba(34, 197, 94, 0.1)',
                    color: '#16a34a',
                    borderRadius: 1,
                    fontWeight: 600,
                    fontSize: '0.65rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}>
                    Read-Only
                  </Typography>
                </Box>

                <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', display: 'block', mb: 2 }}>
                  These are the nested properties contained within this object. To edit them, close this dialog and expand the object property in the class node.
                </Typography>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {nestedProperties.map((prop) => {
                    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});

                    // Handle nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
                    let baseType = propData.type;
                    let isNullable = false;
                    if (Array.isArray(propData.type)) {
                      isNullable = propData.type.includes('null');
                      baseType = propData.type.find((t: string) => t !== 'null');
                    }

                    const propType = baseType || (propData.$ref ? 'reference' : 'object');
                    const isRequired = propData.required === true;
                    const isDeprecated = propData.deprecated === true;
                    const hasRef = !!propData.$ref;
                    const refName = hasRef ? propData.$ref.split('/').pop() : null;

                    // Determine type display
                    let typeDisplay = propType;
                    if (propType === 'array') {
                      const itemType = propData.items?.type || propData.items?.$ref?.split('/').pop() || 'any';
                      typeDisplay = `${itemType}[]`;
                    } else if (hasRef && refName) {
                      typeDisplay = refName;
                    }

                    // Add nullable indicator
                    if (isNullable) {
                      typeDisplay = `${typeDisplay}?`;
                    }

                    return (
                      <Box
                        key={prop.id}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1.5,
                          p: 1.5,
                          bgcolor: isDark ? '#1e293b' : '#f8fafc',
                          borderRadius: 1.5,
                          border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                          opacity: isDeprecated ? 0.6 : 1,
                        }}
                      >
                        {/* Property Name */}
                        <Typography
                          variant="body2"
                          sx={{
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                            fontWeight: 600,
                            color: isDark ? '#e2e8f0' : '#1e293b',
                            textDecoration: isDeprecated ? 'line-through' : 'none',
                            minWidth: 120,
                          }}
                        >
                          {prop.name}
                        </Typography>

                        {/* Type Chip */}
                        <Box
                          sx={{
                            px: 1,
                            py: 0.25,
                            bgcolor: hasRef
                              ? 'rgba(139, 92, 246, 0.1)'
                              : propType === 'array'
                                ? 'rgba(59, 130, 246, 0.1)'
                                : 'rgba(100, 116, 139, 0.1)',
                            color: hasRef
                              ? '#8b5cf6'
                              : propType === 'array'
                                ? '#3b82f6'
                                : isDark ? '#94a3b8' : '#64748b',
                            borderRadius: 1,
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                            fontSize: '0.7rem',
                            fontWeight: 500,
                          }}
                        >
                          {typeDisplay}
                        </Box>

                        {/* Required Badge */}
                        {isRequired && (
                          <Box
                            sx={{
                              px: 0.75,
                              py: 0.25,
                              bgcolor: 'rgba(239, 68, 68, 0.1)',
                              color: '#ef4444',
                              borderRadius: 1,
                              fontSize: '0.6rem',
                              fontWeight: 600,
                              textTransform: 'uppercase',
                            }}
                          >
                            Required
                          </Box>
                        )}

                        {/* Deprecated Badge */}
                        {isDeprecated && (
                          <Box
                            sx={{
                              px: 0.75,
                              py: 0.25,
                              bgcolor: 'rgba(245, 158, 11, 0.1)',
                              color: '#f59e0b',
                              borderRadius: 1,
                              fontSize: '0.6rem',
                              fontWeight: 600,
                              textTransform: 'uppercase',
                            }}
                          >
                            Deprecated
                          </Box>
                        )}

                        {/* Description (if available) */}
                        {prop.description && (
                          <Tooltip title={prop.description} placement="top">
                            <InfoOutlinedIcon sx={{ fontSize: 14, color: isDark ? '#64748b' : '#94a3b8', ml: 'auto', cursor: 'help' }} />
                          </Tooltip>
                        )}
                      </Box>
                    );
                  })}
                </Box>
              </Box>
            )}
          </Box>
        )}
      </Box>

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 4: Values (Const & Enum)
          ═══════════════════════════════════════════════════════════════════════════ */}
      {(baseType === 'string' || baseType === 'number' || baseType === 'integer' || baseType === 'boolean') && (
        <Box sx={{
          p: 3,
          borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
          bgcolor: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
          background: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
        }}>
          <SectionHeader
            icon={<CodeIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
            title="Allowed Values"
            subtitle="Restrict to specific values"
          />

          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 3 }}>
            {/* Constant Value */}
            <Box sx={{
              p: 2.5,
              bgcolor: isDark ? '#0f172a' : 'white',
              borderRadius: 2.5,
              border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1, color: isDark ? '#e2e8f0' : '#334155', display: 'flex', alignItems: 'center', gap: 1 }}>
                <Box component="span" sx={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  bgcolor: '#3b82f6',
                }} />
                Constant Value
              </Typography>
              <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mb: 2 }}>
                Use when property must have exactly one specific value
              </Typography>
              <TextField
                label="Const"
                size={size}
                fullWidth
                type={baseType === 'string' || baseType === 'boolean' ? 'text' : 'number'}
                value={data.const || ''}
                onChange={(e) => {
                  onChange('const', e.target.value);
                  if (e.target.value && data.enum && data.enum.length > 0) {
                    onChange('enum', []);
                  }
                }}
                placeholder={
                  baseType === 'boolean' ? 'true or false' :
                  baseType === 'integer' ? '42' :
                  baseType === 'number' ? '3.14' : 'value'
                }
                disabled={!!data.enum && data.enum.length > 0}
                sx={{
                  '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace' },
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
              {data.const && (
                <Box sx={{
                  mt: 2,
                  p: 2,
                  bgcolor: 'rgba(59, 130, 246, 0.06)',
                  borderRadius: 2,
                  border: '1px solid rgba(59, 130, 246, 0.2)',
                }}>
                  <Typography variant="caption" sx={{ color: '#1e40af', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box component="span" sx={{ color: '#22c55e' }}>✓</Box>
                    Only accepts: <code style={{ fontWeight: 600, background: 'rgba(59, 130, 246, 0.1)', padding: '2px 6px', borderRadius: 4 }}>{data.const}</code>
                  </Typography>
                </Box>
              )}
            </Box>

            {/* Enum Values */}
            {baseType !== 'boolean' && (
              <Box sx={{
                p: 2.5,
                bgcolor: isDark ? '#0f172a' : 'white',
                borderRadius: 2.5,
                border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#334155', display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box component="span" sx={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        bgcolor: '#a855f7',
                      }} />
                      Enum Values
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#64748b' }}>
                      List of allowed values
                    </Typography>
                  </Box>
                  {data.enum && data.enum.length > 1 && (
                    <Box sx={{ display: 'flex', gap: 0.5 }}>
                      <Tooltip title="Sort A-Z" arrow>
                        <IconButton
                          onClick={handleSortEnumAZ}
                          size="small"
                          disabled={!!data.const}
                          sx={{
                            transition: 'all 0.2s',
                            '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.1)' },
                          }}
                        >
                          <SortByAlphaIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Sort Z-A" arrow>
                        <IconButton
                          onClick={handleSortEnumZA}
                          size="small"
                          disabled={!!data.const}
                          sx={{
                            transform: 'scaleY(-1)',
                            transition: 'all 0.2s',
                            '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.1)' },
                          }}
                        >
                          <SortByAlphaIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  )}
                </Box>

                {data.const && (
                  <Typography variant="caption" sx={{ color: '#d97706', display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                    <Box component="span">⚠️</Box> Disabled when const is set
                  </Typography>
                )}

                <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
                  <TextField
                    size={size}
                    fullWidth
                    type={baseType === 'string' ? 'text' : 'number'}
                    value={enumInput}
                    onChange={(e) => { setEnumInput(e.target.value); setEnumError(''); }}
                    onKeyDown={handleEnumKeyPress}
                    error={!!enumError}
                    helperText={enumError}
                    placeholder="Add value..."
                    disabled={!!data.const}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
                  />
                  <IconButton
                    onClick={handleAddEnum}
                    color="primary"
                    disabled={!enumInput.trim() || !!data.const}
                    sx={{
                      bgcolor: 'rgba(99, 102, 241, 0.1)',
                      borderRadius: 2,
                      transition: 'all 0.2s',
                      '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.2)', transform: 'scale(1.05)' },
                    }}
                  >
                    <AddIcon />
                  </IconButton>
                </Box>

                {data.enum && data.enum.length > 0 && (
                  <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleEnumDragEnd}>
                    <List dense sx={{
                      bgcolor: isDark ? '#1e293b' : '#f8fafc',
                      borderRadius: 2,
                      maxHeight: 150,
                      overflow: 'auto',
                      border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
                    }}>
                      <SortableContext items={data.enum} strategy={verticalListSortingStrategy}>
                        {data.enum.map((value) => (
                          <SortableEnumItem key={value} id={value} value={value} onDelete={handleRemoveEnum} />
                        ))}
                      </SortableContext>
                    </List>
                  </DndContext>
                )}
              </Box>
            )}
          </Box>
        </Box>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 5: Advanced (NOT Composition, External Docs, Extensions)
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box sx={{ p: 3, bgcolor: isDark ? '#1e293b' : 'white' }}>
        <SectionHeader
          icon={<SettingsIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Advanced"
          subtitle="Extended schema options"
        />

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 3 }}>
          {/* NOT Composition */}
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? 'linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%)' : 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)',
            background: isDark ? 'linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%)' : 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)',
            borderRadius: 2.5,
            border: '1px solid rgba(239, 68, 68, 0.25)',
            boxShadow: '0 2px 8px rgba(239, 68, 68, 0.08)',
          }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 1, color: isDark ? '#fecaca' : '#991b1b', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box component="span" sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#ef4444',
              }} />
              NOT Schema
            </Typography>
            <Typography variant="caption" sx={{ color: isDark ? '#fca5a5' : '#7f1d1d', display: 'block', mb: 2 }}>
              Data must NOT match this schema (exclusion rule)
            </Typography>
            <TextField
              size={size}
              fullWidth
              multiline
              rows={3}
              value={data.not || ''}
              onChange={(e) => onChange('not', e.target.value)}
              placeholder='{"type": "string", "maxLength": 0}'
              sx={{
                bgcolor: isDark ? '#1e293b' : 'white',
                '& textarea': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.8rem' },
                '& .MuiOutlinedInput-root': { borderRadius: 2 },
              }}
            />
            {data.not && data.not.trim() && (
              <Box sx={{
                mt: 2,
                p: 2,
                bgcolor: isDark ? '#1e293b' : 'white',
                borderRadius: 2,
                border: '1px solid rgba(239, 68, 68, 0.25)',
              }}>
                <Typography variant="caption" sx={{ color: isDark ? '#fca5a5' : '#991b1b', display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Box component="span" sx={{ color: '#ef4444' }}>✗</Box>
                  Values matching this schema will be rejected
                </Typography>
              </Box>
            )}
          </Box>

          {/* External Documentation */}
          <Box sx={{
            p: 2.5,
            bgcolor: isDark ? '#0f172a' : 'white',
            borderRadius: 2.5,
            border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
              <Box sx={{
                p: 0.75,
                borderRadius: 1.5,
                bgcolor: 'rgba(99, 102, 241, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <OpenInNewIcon sx={{ color: '#6366f1', fontSize: 16 }} />
              </Box>
              <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#334155' }}>
                External Documentation
              </Typography>
            </Box>

            <TextField
              label="URL"
              size={size}
              fullWidth
              type="url"
              value={data.externalDocsUrl || ''}
              onChange={(e) => onChange('externalDocsUrl', e.target.value)}
              placeholder="https://docs.example.com/..."
              sx={{
                mb: 2,
                '& .MuiOutlinedInput-root': { borderRadius: 2 },
              }}
              InputProps={{
                endAdornment: data.externalDocsUrl?.trim() && (
                  <InputAdornment position="end">
                    <Tooltip title="Open in new tab" arrow>
                      <IconButton
                        size="small"
                        onClick={() => {
                          const url = data.externalDocsUrl?.trim();
                          if (url) window.open(url, '_blank', 'noopener,noreferrer');
                        }}
                        sx={{
                          transition: 'all 0.2s',
                          '&:hover': { color: '#6366f1' },
                        }}
                      >
                        <OpenInNewIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </InputAdornment>
                ),
              }}
            />

            <TextField
              label="Description"
              size={size}
              fullWidth
              multiline
              rows={2}
              value={data.externalDocsDescription || ''}
              onChange={(e) => onChange('externalDocsDescription', e.target.value)}
              placeholder="Brief description..."
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
            />
          </Box>
        </Box>

        {/* Extensions */}
        <Box sx={{
          mt: 3,
          p: 2.5,
          bgcolor: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
          background: isDark ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
          borderRadius: 2.5,
          border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
        }}>
          <ExtensionsEditor
            value={data.extensions || {}}
            onChange={(extensions) => onChange('extensions', extensions)}
            size={size}
          />
        </Box>
      </Box>
    </Box>
  );
};


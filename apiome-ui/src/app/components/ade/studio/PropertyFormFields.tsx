'use client';
/* eslint-disable @typescript-eslint/no-explicit-any */
// Radix/native stubs replace MUI; some callback params are typed loosely for compatibility.

import React, { useMemo } from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { useDarkMode } from '@/app/hooks/useDarkMode';
import { Plus, Trash2, Sparkles, ArrowUpDown, GripVertical, ExternalLink, Info, SlidersHorizontal, Settings, Code, FileText } from 'lucide-react';
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
import { PrimitiveSelector } from './PrimitiveSelector';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Badge } from '../../ui/Badge';
import { Textarea } from '../../ui/Textarea';
import { Checkbox as ShadcnCheckbox } from '../../ui/Checkbox';

// Radix/native stubs replacing MUI (no MUI dependency)
const spacing = (n: number) => (typeof n === 'number' ? n * 8 : 0);
const sxToStyle = (sx: any): React.CSSProperties => {
  if (!sx || typeof sx !== 'object') return {};
  const style: React.CSSProperties = {};
  if (sx.p != null) style.padding = spacing(Number(sx.p));
  if (sx.px != null) { style.paddingLeft = spacing(Number(sx.px)); style.paddingRight = spacing(Number(sx.px)); }
  if (sx.py != null) { style.paddingTop = spacing(Number(sx.py)); style.paddingBottom = spacing(Number(sx.py)); }
  if (sx.m != null) style.margin = spacing(Number(sx.m));
  if (sx.mb != null) style.marginBottom = spacing(Number(sx.mb));
  if (sx.mt != null) style.marginTop = spacing(Number(sx.mt));
  if (sx.mr != null) style.marginRight = spacing(Number(sx.mr));
  if (sx.ml != null) style.marginLeft = spacing(Number(sx.ml));
  if (sx.gap != null) style.gap = spacing(Number(sx.gap));
  if (sx.display != null) style.display = sx.display;
  if (sx.flex != null) style.flex = sx.flex;
  if (sx.flexDirection != null) style.flexDirection = sx.flexDirection;
  if (sx.alignItems != null) style.alignItems = sx.alignItems;
  if (sx.justifyContent != null) style.justifyContent = sx.justifyContent;
  if (sx.borderRadius != null) style.borderRadius = typeof sx.borderRadius === 'number' ? sx.borderRadius * 8 : sx.borderRadius;
  if (sx.border != null) style.border = sx.border;
  if (sx.borderBottom != null) style.borderBottom = sx.borderBottom;
  if (sx.borderColor != null) style.borderColor = sx.borderColor;
  if (sx.borderLeft != null) style.borderLeft = sx.borderLeft;
  if (sx.bgcolor != null || sx.backgroundColor != null) style.backgroundColor = sx.bgcolor ?? sx.backgroundColor;
  if (sx.background != null) style.background = sx.background;
  if (sx.color != null) style.color = sx.color;
  if (sx.fontWeight != null) style.fontWeight = sx.fontWeight;
  if (sx.fontSize != null) style.fontSize = typeof sx.fontSize === 'number' ? sx.fontSize : sx.fontSize;
  if (sx.fontFamily != null) style.fontFamily = sx.fontFamily;
  if (sx.letterSpacing != null) style.letterSpacing = sx.letterSpacing;
  if (sx.textTransform != null) style.textTransform = sx.textTransform;
  if (sx.overflow != null) style.overflow = sx.overflow;
  if (sx.minWidth != null) style.minWidth = sx.minWidth;
  if (sx.width != null) style.width = sx.width;
  if (sx.cursor != null) style.cursor = sx.cursor;
  if (sx.transition != null) style.transition = sx.transition;
  if (sx.opacity != null) style.opacity = sx.opacity;
  if (sx.flexShrink != null) style.flexShrink = sx.flexShrink;
  if (sx.my != null) { style.marginTop = spacing(Number(sx.my)); style.marginBottom = spacing(Number(sx.my)); }
  if (sx.mx != null) { style.marginLeft = spacing(Number(sx.mx)); style.marginRight = spacing(Number(sx.mx)); }
  return style;
};
const Box = ({ sx, component: Comp = 'div', children, ...rest }: any) => <Comp style={sxToStyle(sx)} {...rest}>{children}</Comp>;
const Typography = ({ variant, sx, children, component: Comp = 'span', ...rest }: any) => <Comp style={sxToStyle(sx)} {...rest}>{children}</Comp>;
const Button = ({ sx, children, startIcon, endIcon, ...rest }: any) => (
  <button type="button" style={sxToStyle(sx)} {...rest}>{startIcon}{children}{endIcon}</button>
);
const IconButton = ({ sx, children, size, ...rest }: any) => (
  <button type="button" style={{ ...sxToStyle(sx), padding: size === 'small' ? 4 : 8, background: 'none', border: 'none', cursor: 'pointer' }} {...rest}>{children}</button>
);
const List = ({ sx, children, ...rest }: any) => <ul style={{ listStyle: 'none', padding: 0, margin: 0, ...sxToStyle(sx) }} {...rest}>{children}</ul>;
const ListItem = ({ sx, children, secondaryAction, disablePadding, ...rest }: any) => (
  <li style={{ display: 'flex', alignItems: 'center', padding: disablePadding ? 0 : '8px 0', ...sxToStyle(sx) }} {...rest}>
    <span style={{ flex: 1 }}>{children}</span>
    {secondaryAction}
  </li>
);
const ListItemText = ({ primary, secondary, primaryTypographyProps, sx, ...rest }: any) => (
  <span style={{ flex: 1, ...sxToStyle(sx), ...(primaryTypographyProps || {}) }} {...rest}>
    {typeof primary === 'string' ? primary : primary}
    {secondary && <span className="block text-xs text-slate-500 mt-0.5">{secondary}</span>}
  </span>
);
const InputAdornment = ({ position, children }: any) => <span className={position === 'start' ? 'pl-3' : 'pr-3'}>{children}</span>;
const Chip = ({ label, size, sx, color, icon, onDelete, ...rest }: any) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px', borderRadius: 16, fontSize: 12, ...sxToStyle(sx) }} {...rest}>
    {icon}{label}
    {onDelete && <button type="button" onClick={onDelete} aria-label="Remove">×</button>}
  </span>
);
const FormControl = ({ sx, children, fullWidth, ...rest }: any) => (
  <div style={{ ...(fullWidth ? { width: '100%', minWidth: 0 } : {}), ...sxToStyle(sx) }} {...rest}>{children}</div>
);
const FormControlLabel = ({ control, label, sx, ...rest }: any) => (
  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer', ...sxToStyle(sx) }} {...rest}>
    {control}
    {label}
  </label>
);
const Checkbox = ({ checked, onChange, disabled, sx, ...rest }: any) => (
  <input type="checkbox" checked={checked} onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange?.(e, e.target.checked)} disabled={disabled} {...rest} />
);
const Radio = ({ checked, onChange, value, disabled, sx, ...rest }: any) => (
  <input type="radio" checked={checked} onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange?.(e, e.target.value)} value={value} disabled={disabled} {...rest} />
);
const Collapse = ({ in: inProp, children }: any) => inProp ? <div>{children}</div> : null;
const MenuItem = ({ value, children, ...rest }: any) => <option value={value} {...rest}>{children}</option>;
const MuiSelect = ({ value, onChange, children, label, sx, size, disabled, SelectProps, ...rest }: any) => (
  <select
    value={value ?? ''}
    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const v = e.target.value;
      (onChange as any)?.(e, v);
    }}
    disabled={disabled}
    style={{ minHeight: size === 'small' ? 32 : 40, ...sxToStyle(sx) }}
    {...rest}
  >
    {children}
  </select>
);
const Tooltip = ({ title, children, arrow, ...rest }: any) => (
  <TooltipPrimitive.Provider>
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Content sideOffset={5} className="max-w-xs px-3 py-2 text-xs bg-slate-900 text-white rounded shadow-lg">
        {title}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Root>
  </TooltipPrimitive.Provider>
);
const TextField = ({ label, value, onChange, fullWidth, size, error, helperText, placeholder, disabled, multiline, rows, select, SelectProps, InputProps, inputProps: innerInputProps, slotProps, sx, children, ...rest }: any) => {
  const adornmentProps = InputProps || slotProps?.input || {};
  const startAdornment = adornmentProps.startAdornment;
  const endAdornment = adornmentProps.endAdornment;
  // MUI-style `inputProps` forwards HTML attributes (min/max/step/maxLength/...)
  // to the underlying <input>. Spreading via `...rest` would leak the prop
  // to the DOM, so we destructure it out and apply it directly here.
  const innerHtmlProps = innerInputProps || slotProps?.htmlInput || {};
  const style = { width: fullWidth ? '100%' : undefined, ...sxToStyle(sx) };
  const inputClass = `px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm ${fullWidth ? 'w-full min-w-0' : ''}`;
  const el = select ? (
    <select value={value ?? ''} onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(e)} className={inputClass} disabled={disabled} style={{ minHeight: size === 'small' ? 32 : 40 }} {...rest} {...innerHtmlProps}>
      {children}
    </select>
  ) : multiline ? (
    <textarea value={value ?? ''} onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(e)} placeholder={placeholder} disabled={disabled} rows={rows || 3} className={inputClass} {...rest} {...innerHtmlProps} />
  ) : (
    <input
      type="text"
      value={value ?? ''}
      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(e)}
      placeholder={placeholder}
      disabled={disabled}
      className={inputClass}
      {...rest}
      {...innerHtmlProps}
    />
  );
  return (
    <div style={{ marginBottom: 16, ...style }}>
      {label && <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1">{label}</label>}
      <div className={`flex items-center ${fullWidth ? 'w-full min-w-0' : ''}`}>
        {startAdornment}
        {fullWidth ? <span className="flex-1 min-w-0 flex flex-col">{el}</span> : el}
        {endAdornment}
      </div>
      {helperText && <p className="text-xs text-slate-500 mt-1">{helperText}</p>}
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  );
};
const Autocomplete = ({ options, value, onChange, freeSolo, renderInput, multiple, renderTags, ...rest }: any) => {
  const val = multiple ? (value || []) : (value ?? '');
  if (multiple) {
    const arr = Array.isArray(val) ? val : [];
    return (
      <div>
        {renderInput?.({})}
        <div className="flex flex-wrap gap-2 mt-2">
          {arr.map((opt: string, i: number) => (
            <span key={opt} className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-200 dark:bg-slate-700 text-sm">
              {opt}
              <button type="button" onClick={() => onChange?.(null, arr.filter((_: any, j: number) => j !== i))}>×</button>
            </span>
          ))}
        </div>
        <input
          list={`autocomplete-${Math.random()}`}
          className="px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm w-full mt-1"
          onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') { const v = (e.target as HTMLInputElement).value; if (v && !arr.includes(v)) onChange?.(null, [...arr, v]); (e.target as HTMLInputElement).value = ''; } }}
        />
        <datalist>{options?.map((o: string) => <option key={o} value={o} />)}</datalist>
      </div>
    );
  }
  return renderInput ? renderInput({}) : <input value={val} onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(null, e.target.value)} {...rest} />;
};
const AddIcon = (props: any) => <Plus className="w-4 h-4" {...props} />;
const DeleteIcon = (props: any) => <Trash2 className="w-4 h-4" {...props} />;
const AutoAwesomeIcon = (props: any) => <Sparkles className="w-4 h-4" {...props} />;
const SortByAlphaIcon = (props: any) => <ArrowUpDown className="w-4 h-4" {...props} />;
const DragIndicatorIcon = (props: any) => <GripVertical className="w-4 h-4" {...props} />;
const OpenInNewIcon = (props: any) => <ExternalLink className="w-4 h-4" {...props} />;
const InfoOutlinedIcon = (props: any) => <Info className="w-4 h-4" {...props} />;
const TuneIcon = (props: any) => <SlidersHorizontal className="w-4 h-4" {...props} />;
const SettingsIcon = (props: any) => <Settings className="w-4 h-4" {...props} />;
const CodeIcon = (props: any) => <Code className="w-4 h-4" {...props} />;

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
  /** Team or person responsible; persisted as OpenAPI extension `x-owner` on the property schema */
  owner?: string;
  examples?: string[]; // Array of example values (JSON strings)

  // Object constraints
  additionalProperties?: 'default' | 'true' | 'false' | 'type' | 'schema';
  additionalPropertiesType?: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array'; // For inline type schema
  additionalPropertiesSchema?: string; // Class name reference for schema option
  minProperties?: string;
  maxProperties?: string;
  patternProperties?: Record<string, any>; // Map of regex patterns to schemas
  propertyNamesPattern?: string;
  propertyNamesMinLength?: string;
  propertyNamesMaxLength?: string;
  propertyNamesFormat?: string; // Format constraint for property names (e.g., email, uuid)
  propertyNamesDescription?: string; // Description for property name constraints

  // Composition constraints
  dependentSchemas?: Record<string, any>; // Map of property names to conditional schemas

  // unevaluatedProperties (OpenAPI 3.1/JSON Schema 2020-12) - for objects
  unevaluatedProperties?: 'default' | 'allow' | 'disallow' | 'schema'; // Control for properties not matched by properties, patternProperties, or inherited schemas
  unevaluatedPropertiesSchema?: string; // JSON string of schema when unevaluatedProperties is 'schema'

  // Extensions (x- prefixed properties)
  extensions?: Record<string, any>;

  // External Documentation
  externalDocsUrl?: string;
  externalDocsDescription?: string;

  // XML Object (OpenAPI 3.1) - for XML serialization
  xmlName?: string; // Replaces element/attribute name
  xmlNamespace?: string; // URI of namespace definition
  xmlPrefix?: string; // Prefix for the name
  xmlAttribute?: boolean; // Property becomes XML attribute instead of element
  xmlWrapped?: boolean; // For arrays: wrapped vs unwrapped serialization

  // Content Media Type (OpenAPI 3.1) - for binary string properties
  contentMediaType?: string; // Media type (e.g., application/octet-stream, image/png)
  contentEncoding?: string; // Encoding (e.g., base64, base32)
  contentSchema?: string; // JSON string of schema for decoded content

  // Schema Metadata (JSON Schema 2020-12)
  $comment?: string; // Internal comments for schema authors

  // Type Registry binding (#3474 type picker / #3475 persisted binding)
  /**
   * Stable registry `$ref` to an `apiome.primitives` type selected via the type
   * picker (e.g. `std/v0/types/date`). Empty/undefined when the property is not
   * bound to a registry type. Persisted to `class_properties.primitive_ref` (#3475).
   */
  $ref?: string;
  /**
   * Resolved target of the `$ref` binding: the `id` of the `apiome.primitives` row
   * the property is bound to. Set alongside `$ref` by the type picker and
   * persisted to `class_properties.primitive_id` (#3475). Empty when unbound.
   */
  primitive_id?: string;
}

interface SortableEnumItemProps {
  id: string;
  value: string | number;
  onDelete: (value: string | number) => void;
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

// Section header component for consistent styling across form sections.
// Matches the ./form/FormSection visual contract: icon, optional eyebrow,
// title, description, optional badge, and a discrete amber "changed" dot when
// the section contains non-default values.
interface SectionHeaderProps {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  badge?: string;
  eyebrow?: string;
  changed?: boolean;
}

const SectionHeader: React.FC<SectionHeaderProps> = ({
  icon,
  title,
  subtitle,
  badge,
  eyebrow,
  changed,
}) => (
  <header className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5">
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      {eyebrow && (
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-indigo-600 dark:text-indigo-400">
          {eyebrow}
        </span>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {icon && (
          <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-indigo-500 dark:text-indigo-400">
            {icon}
          </span>
        )}
        <h3 className="text-base font-semibold leading-6 tracking-[-0.01em] text-slate-900 dark:text-slate-100">
          {title}
        </h3>
        {changed && (
          <span
            className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-400"
            aria-label="Contains non-default values"
            title="Contains non-default values"
          />
        )}
        {badge && (
          <span className="ml-1 inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200">
            {badge}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="mt-0.5 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">
          {subtitle}
        </p>
      )}
    </div>
  </header>
);

// Reusable component for editing pattern property schemas
interface PatternPropertySchemaEditorProps {
  schemaValue: any;
  onChange: (newSchema: any) => void;
  isDark: boolean;
  rows?: number;
  size?: 'small' | 'medium';
}

const PatternPropertySchemaEditor: React.FC<PatternPropertySchemaEditorProps> = ({
  schemaValue,
  onChange,
  isDark,
  rows = 5,
  size = 'small',
}) => {
  // Use local state to manage the display value
  const [localValue, setLocalValue] = React.useState(() => {
    return typeof schemaValue === 'string' ? schemaValue : JSON.stringify(schemaValue, null, 2);
  });

  // Update local value when schemaValue prop changes
  React.useEffect(() => {
    const newValue = typeof schemaValue === 'string' ? schemaValue : JSON.stringify(schemaValue, null, 2);
    setLocalValue(newValue);
  }, [schemaValue]);

  const textFieldSize = (size === 'medium' || size === 'small') ? size : 'small';

  return (
    <TextField
      label="Schema (JSON)"
      size={textFieldSize}
      fullWidth
      multiline
      rows={rows}
      value={localValue}
      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setLocalValue(e.target.value);
        try {
          const parsed = e.target.value ? JSON.parse(e.target.value) : { type: 'string' };
          onChange(parsed);
        } catch {
          // Keep editing even if JSON is invalid
          onChange(e.target.value);
        }
      }}
      placeholder='{ "type": "string" }'
      sx={{
        '& .MuiInputBase-input': {
          fontFamily: '"JetBrains Mono", "Fira Code", monospace',
          fontSize: '0.75rem',
        },
        '& .MuiOutlinedInput-root': { borderRadius: 1 },
      }}
    />
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
  showPrimitiveSelector?: boolean;
  showHint?: boolean;
  size?: 'small' | 'medium';

  // Object type information
  nestedProperties?: Array<{
    id: string;
    name: string;
    data: any;
    description?: string;
  }>;

  // Available class names for schema references
  availableClasses?: string[];

  /** Ollama-backed example generation (#622); rendered beside schema-based example control. */
  examplesAiSlot?: React.ReactNode;
}

// OpenAPI 3.1 format options by type
const FORMAT_OPTIONS: Record<string, { value: string; label: string; description: string }[]> = {
  string: [
    { value: 'date', label: 'date', description: 'Full date (RFC 3339)' },
    { value: 'date-time', label: 'date-time', description: 'Date and time (RFC 3339)' },
    { value: 'time', label: 'time', description: 'Time only (RFC 3339)' },
    { value: 'duration', label: 'duration', description: 'Duration (ISO 8601)' },
    { value: 'email', label: 'email', description: 'Email address (RFC 5321)' },
    { value: 'idn-email', label: 'idn-email', description: 'Internationalized email' },
    { value: 'hostname', label: 'hostname', description: 'Internet hostname' },
    { value: 'idn-hostname', label: 'idn-hostname', description: 'Internationalized hostname' },
    { value: 'ipv4', label: 'ipv4', description: 'IPv4 address' },
    { value: 'ipv6', label: 'ipv6', description: 'IPv6 address' },
    { value: 'uri', label: 'uri', description: 'Uniform Resource Identifier' },
    { value: 'uri-reference', label: 'uri-reference', description: 'URI or relative reference' },
    { value: 'iri', label: 'iri', description: 'Internationalized URI' },
    { value: 'iri-reference', label: 'iri-reference', description: 'IRI or relative reference' },
    { value: 'uri-template', label: 'uri-template', description: 'URI Template (RFC 6570)' },
    { value: 'uuid', label: 'uuid', description: 'UUID (RFC 4122)' },
    { value: 'json-pointer', label: 'json-pointer', description: 'JSON Pointer (RFC 6901)' },
    { value: 'relative-json-pointer', label: 'relative-json-pointer', description: 'Relative JSON Pointer' },
    { value: 'regex', label: 'regex', description: 'Regular expression' },
    { value: 'password', label: 'password', description: 'Password (UI hint to obscure)' },
    { value: 'byte', label: 'byte', description: 'Base64-encoded binary' },
    { value: 'binary', label: 'binary', description: 'Binary data (any octets)' },
  ],
  integer: [
    { value: 'int32', label: 'int32', description: 'Signed 32-bit integer' },
    { value: 'int64', label: 'int64', description: 'Signed 64-bit integer (long)' },
  ],
  number: [
    { value: 'float', label: 'float', description: 'Single-precision float' },
    { value: 'double', label: 'double', description: 'Double-precision float' },
  ],
};

export const PropertyFormFields: React.FC<PropertyFormFieldsProps> = ({
                                                                        baseType,
                                                                        isArray,
                                                                        data,
                                                                        onChange,
                                                                        showMetadata = true,
                                                                        showTitle = true,
                                                                        showPrimitiveSelector = true,
                                                                        showHint = true,
                                                                        size = 'medium',
                                                                        nestedProperties,
                                                                        availableClasses = [],
                                                                        examplesAiSlot,
                                                                      }) => {
  const isDark = useDarkMode();

  /** Sections that differ from defaults (empty/new property state) - for visual highlight */
  const changedSections = useMemo(() => {
    const d = data;
    return {
      basicInfo: (d.description || '').trim() !== '' || (d.default || '').trim() !== ''
        || (d.examples && d.examples.length > 0) || (d.title || '').trim() !== '',
      propertyFlags: d.required || d.nullable || d.readOnly || d.writeOnly || d.deprecated || (d.deprecationMessage || '').trim() !== ''
        || (d.owner || '').trim() !== '',
      stringConstraints: (d.minLength || '').trim() !== '' || (d.maxLength || '').trim() !== '' || (d.pattern || '').trim() !== '' || (d.format || '').trim() !== '',
      numberConstraints: (d.minimum || '').trim() !== '' || (d.maximum || '').trim() !== '' || (d.multipleOf || '').trim() !== '' || d.minimumType || d.maximumType,
      arrayConstraints: (d.minItems || '').trim() !== '' || (d.maxItems || '').trim() !== '' || d.uniqueItems
        || (d.contains || '').trim() !== '' || (d.minContains || '').trim() !== '' || (d.maxContains || '').trim() !== ''
        || d.tupleMode || (d.prefixItems && d.prefixItems.length > 0) || (d.itemsSchema || '').trim() !== ''
        || (d.unevaluatedItems && d.unevaluatedItems !== 'default') || (d.unevaluatedItemsSchema || '').trim() !== '',
      objectConstraints: (d.additionalProperties && d.additionalProperties !== 'default') || (d.additionalPropertiesSchema || '').trim() !== ''
        || (d.minProperties || '').trim() !== '' || (d.maxProperties || '').trim() !== ''
        || (d.patternProperties && Object.keys(d.patternProperties).length > 0)
        || (d.unevaluatedProperties && d.unevaluatedProperties !== 'default') || (d.unevaluatedPropertiesSchema || '').trim() !== ''
        || (d.propertyNamesPattern || '').trim() !== '' || (d.propertyNamesMinLength || '').trim() !== '' || (d.propertyNamesMaxLength || '').trim() !== ''
        || (d.propertyNamesFormat || '').trim() !== '' || (d.propertyNamesDescription || '').trim() !== ''
        || (d.dependentSchemas && Object.keys(d.dependentSchemas).length > 0),
      values: (d.const || '').trim() !== '' || (d.enum && d.enum.length > 0),
      advanced: (d.not || '').trim() !== '' || (d.extensions && Object.keys(d.extensions).length > 0)
        || (d.externalDocsUrl || '').trim() !== '' || (d.externalDocsDescription || '').trim() !== ''
        || (d.xmlName || '').trim() !== '' || (d.xmlNamespace || '').trim() !== '' || (d.xmlPrefix || '').trim() !== ''
        || d.xmlAttribute || d.xmlWrapped
        || (d.contentMediaType || '').trim() !== '' || (d.contentEncoding || '').trim() !== '' || (d.contentSchema || '').trim() !== ''
        || (d.$comment || '').trim() !== '',
    };
  }, [data]);

  const [enumInput, setEnumInput] = React.useState('');
  const [enumError, setEnumError] = React.useState('');
  const [exampleInput, setExampleInput] = React.useState('');
  const [exampleError, setExampleError] = React.useState('');

  // State for pattern properties form
  const [newPattern, setNewPattern] = React.useState('');
  const [newPatternSchema, setNewPatternSchema] = React.useState({ type: 'string' } as any);

  // State for dependent schemas form
  const [newDepPropName, setNewDepPropName] = React.useState('');

  // When the "Bind to a Type" picker dialog is open, dim the parent form
  const [primitiveDialogOpen, setPrimitiveDialogOpen] = React.useState(false);

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

  const handleRemoveEnum = (value: string | number) => {
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

    const safeEnum = (data.enum || []).filter((v) => v != null);
    const oldIndex = safeEnum.findIndex((v) => String(v) === active.id);
    const newIndex = safeEnum.findIndex((v) => String(v) === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const newEnumArray = arrayMove(safeEnum, oldIndex, newIndex);
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
      position: 'relative',
      minHeight: '100%',
      width: '100%',
    }}>
      <Box sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
        bgcolor: isDark ? '#0f172a' : '#f8fafc',
        minHeight: '100%',
        opacity: primitiveDialogOpen ? 0.3 : 1,
        pointerEvents: primitiveDialogOpen ? 'none' : 'auto',
        transition: 'opacity 0.2s ease',
        position: 'relative',
        zIndex: 0,
      }}>
      {showHint && (
        <div className="border-b border-amber-200/70 bg-amber-50 px-6 py-2 text-xs text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
          An amber dot next to a section title means it contains values that differ from defaults.
        </div>
      )}
      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 1: Basic Information
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box
        data-section-id="basicInfo"
        sx={{
          p: 3,
          bgcolor: isDark ? '#1e293b' : 'white',
          borderBottom: '1px solid',
          borderColor: isDark ? '#1f2937' : '#e2e8f0',
        }}
      >
        <SectionHeader
          icon={<InfoOutlinedIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Basic Information"
          subtitle="Core property details"
          changed={changedSections.basicInfo}
        />

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 2fr' }, gap: 2.5 }}>
          {showTitle && (
            <TextField
              label="Title"
              size={size}
              fullWidth
              value={data.title || ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange('title', e.target.value)}
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
            onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('description', e.target.value)}
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
            onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('default', e.target.value)}
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
            <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, mb: 1 }}>
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
              {examplesAiSlot ? <Box sx={{ flex: '1 1 auto', minWidth: 0 }}>{examplesAiSlot}</Box> : null}
            </Box>

            <TextField
              label="Add Example"
              size={size}
              fullWidth
              multiline
              rows={2}
              value={exampleInput}
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
          SECTION 2: Property Behavior (Metadata flags) - Compact Layout
          ═══════════════════════════════════════════════════════════════════════════ */}
      {showMetadata && (
        <Box
          data-section-id="propertyFlags"
          sx={{
            p: 2,
            borderBottom: isDark ? '1px solid #1f2937' : '1px solid #e2e8f0',
            bgcolor: isDark ? '#1e293b' : '#f8fafc',
          }}
        >
          <SectionHeader
            icon={<TuneIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
            title="Property Flags"
            subtitle="Metadata flags that describe how this property behaves at runtime"
            changed={changedSections.propertyFlags}
          />

          {/* Compact horizontal checkbox layout */}
          <Box sx={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: { xs: 1, sm: 2 },
            alignItems: 'center',
          }}>
            {/* Required */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.required || false}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange('required', e.target.checked)}
                  size="small"
                  sx={{ py: 0.5, '&.Mui-checked': { color: '#ef4444' } }}
                />
              }
              label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.required ? '#dc2626' : (isDark ? '#e2e8f0' : '#334155') }}>Required</Typography>}
              sx={{ m: 0 }}
            />

            {/* Nullable */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.nullable || false}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange('nullable', e.target.checked)}
                  size="small"
                  sx={{ py: 0.5, '&.Mui-checked': { color: '#a855f7' } }}
                />
              }
              label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.nullable ? '#9333ea' : (isDark ? '#e2e8f0' : '#334155') }}>Nullable</Typography>}
              sx={{ m: 0 }}
            />

            {/* Read Only */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.readOnly || false}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    onChange('readOnly', e.target.checked);
                    if (e.target.checked) onChange('writeOnly', false);
                  }}
                  size="small"
                  sx={{ py: 0.5, '&.Mui-checked': { color: '#3b82f6' } }}
                />
              }
              label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.readOnly ? '#2563eb' : (isDark ? '#e2e8f0' : '#334155') }}>Read Only</Typography>}
              sx={{ m: 0 }}
            />

            {/* Write Only */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.writeOnly || false}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    onChange('writeOnly', e.target.checked);
                    if (e.target.checked) onChange('readOnly', false);
                  }}
                  size="small"
                  sx={{ py: 0.5, '&.Mui-checked': { color: '#22c55e' } }}
                />
              }
              label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.writeOnly ? '#16a34a' : (isDark ? '#e2e8f0' : '#334155') }}>Write Only</Typography>}
              sx={{ m: 0 }}
            />

            {/* Deprecated */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={data.deprecated || false}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange('deprecated', e.target.checked)}
                  size="small"
                  sx={{ py: 0.5, '&.Mui-checked': { color: '#f59e0b' } }}
                />
              }
              label={<Typography variant="body2" sx={{ fontWeight: 500, color: data.deprecated ? '#d97706' : (isDark ? '#e2e8f0' : '#334155') }}>Deprecated</Typography>}
              sx={{ m: 0 }}
            />
          </Box>

          {/* Deprecation Message */}
          <Collapse in={data.deprecated} timeout={300}>
            <TextField
              label="Deprecation Message"
              size="small"
              fullWidth
              multiline
              rows={2}
              value={data.deprecationMessage || ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('deprecationMessage', e.target.value)}
              placeholder="e.g., Use newProperty instead. Will be removed in v2.0."
              sx={{
                mt: 1.5,
                bgcolor: isDark ? '#0f172a' : 'white',
                '& .MuiOutlinedInput-root': { borderRadius: 2 },
              }}
            />
          </Collapse>

          <TextField
            label="Owner"
            size="small"
            fullWidth
            value={data.owner || ''}
            onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('owner', e.target.value)}
            placeholder="e.g. platform-team or @handle"
            helperText="Stored as x-owner on this property schema (team or person responsible)."
            sx={{
              mt: 1.5,
              bgcolor: isDark ? '#0f172a' : 'white',
              '& .MuiOutlinedInput-root': { borderRadius: 2 },
            }}
          />
        </Box>
      )}

      </Box>

      {/* ═══════════════════════════════════════════════════════════════════════════
          APPLY FROM PRIMITIVE — sits outside faded sections so it stays prominent
          ═══════════════════════════════════════════════════════════════════════════ */}
      {showPrimitiveSelector && (baseType === 'string' || baseType === 'number' || baseType === 'integer' || baseType === 'array') && !data.tupleMode && (
        <Box sx={{
          p: 2,
          borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
          bgcolor: primitiveDialogOpen
            ? (isDark ? 'rgba(99, 102, 241, 0.18)' : 'rgba(99, 102, 241, 0.08)')
            : (isDark ? 'rgba(99, 102, 241, 0.06)' : 'rgba(99, 102, 241, 0.03)'),
          outline: primitiveDialogOpen ? `2px solid ${isDark ? 'rgba(99,102,241,0.6)' : 'rgba(99,102,241,0.5)'}` : 'none',
          outlineOffset: '-2px',
          transition: 'background-color 0.2s ease, outline 0.2s ease',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
        }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b', mb: 0.25 }}>
              Bind to a Type
            </Typography>
            <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
              Bind this property to a Standard, Core, Tenant, or Custom registry type — applies its constraints and records a stable $ref
            </Typography>
          </Box>
          <PrimitiveSelector
            formData={data}
            onChange={onChange}
            propertyType={baseType}
            size={size}
            onOpenChange={setPrimitiveDialogOpen}
          />
        </Box>
      )}

      <Box sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
        minHeight: 0,
        opacity: primitiveDialogOpen ? 0.3 : 1,
        pointerEvents: primitiveDialogOpen ? 'none' : 'auto',
        transition: 'opacity 0.2s ease',
      }}>

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 3: Type-Specific Constraints
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box
        data-section-id="constraints"
        sx={{
          p: 3,
          borderBottom: isDark ? '1px solid #1f2937' : '1px solid #e2e8f0',
          bgcolor: isDark ? '#1e293b' : 'white',
        }}
      >
        <SectionHeader
          icon={<SettingsIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Constraints"
          subtitle="Validation rules for this property"
          badge={`${baseType}${isArray ? '[]' : ''}`}
          changed={Boolean(
            changedSections.stringConstraints ||
              changedSections.numberConstraints ||
              changedSections.arrayConstraints ||
              changedSections.objectConstraints,
          )}
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

            <Box sx={{ mb: 2.5 }}>
              <Autocomplete
                freeSolo
                size={size}
value={data.format || ''}
                 onChange={(_e: unknown, newValue: string | null) => onChange('format', newValue || '')}
                 onInputChange={(_e: React.ChangeEvent<HTMLInputElement>, newInputValue: string) => onChange('format', newInputValue)}
                 options={FORMAT_OPTIONS.string?.map(opt => opt.value) || []}
                renderOption={(props: React.HTMLAttributes<HTMLLIElement>, option: string) => {
                  const formatOption = FORMAT_OPTIONS.string?.find(o => o.value === option);
                  return (
                    <li {...props} key={option}>
                      <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 500 }}>
                          {option}
                        </Typography>
                        {formatOption && (
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            {formatOption.description}
                          </Typography>
                        )}
                      </Box>
                    </li>
                  );
                }}
                renderInput={(params: any) => (
                  <TextField
                    {...params}
                    label="Format"
                    placeholder="Select or enter custom format..."
                    helperText="Standard format hint (select or type custom)"
                    sx={{
                      bgcolor: isDark ? '#0f172a' : 'white',
                      '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    }}
                  />
                )}
              />
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) minmax(0, 1fr)' }, gap: 1.5, mb: 2.5 }}>
              <TextField
                label="Min Length"
                type="number"
                size={size}
                fullWidth
                value={data.minLength || ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('minLength', e.target.value)}
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
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('maxLength', e.target.value)}
                inputProps={{ min: 0 }}
                sx={{
                  bgcolor: isDark ? '#0f172a' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                }}
              />
            </Box>

            <TextField
              label="Pattern (Regex)"
              size={size}
              fullWidth
              value={data.pattern || ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('pattern', e.target.value)}
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

            {/* Content Media Type Fields (for binary/byte strings) */}
            {(data.format === 'binary' || data.format === 'byte') && (
              <Box sx={{
                mt: 2.5,
                p: 2,
                bgcolor: isDark ? '#0f172a' : '#fefce8',
                borderRadius: 2,
                border: isDark ? '1px solid #475569' : '1px solid #fde047',
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#fde047' : '#854d0e', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box component="span" sx={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      bgcolor: '#eab308',
                    }} />
                    Binary Content Settings
                  </Typography>
                  <Typography variant="caption" sx={{
                    px: 1,
                    py: 0.25,
                    bgcolor: 'rgba(234, 179, 8, 0.2)',
                    color: '#ca8a04',
                    borderRadius: 1,
                    fontWeight: 600,
                    fontSize: '0.65rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}>
                    OpenAPI 3.1
                  </Typography>
                </Box>
                <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#713f12', display: 'block', mb: 2 }}>
                  Configure how binary content is interpreted and validated.
                </Typography>

                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2, mb: 2 }}>
                  <TextField
                    label="Content Media Type"
                    size={size}
                    fullWidth
                    value={data.contentMediaType || ''}
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('contentMediaType', e.target.value)}
                    placeholder="e.g., image/png, application/pdf"
                    helperText="MIME type of the binary content"
                    sx={{
                      bgcolor: isDark ? '#1e293b' : 'white',
                      '& .MuiOutlinedInput-root': { borderRadius: 2 },
                      '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                    }}
                  />
                  <TextField
                    label="Content Encoding"
                    size={size}
                    fullWidth
                    value={data.contentEncoding || ''}
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('contentEncoding', e.target.value)}
                    placeholder="e.g., base64, base32"
                    helperText="Encoding used for the content"
                    sx={{
                      bgcolor: isDark ? '#1e293b' : 'white',
                      '& .MuiOutlinedInput-root': { borderRadius: 2 },
                      '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                    }}
                  />
                </Box>

                <TextField
                  label="Content Schema"
                  size={size}
                  fullWidth
                  multiline
                  rows={2}
                  value={data.contentSchema || ''}
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('contentSchema', e.target.value)}
                  placeholder='{"type": "object", "properties": {...}}'
                  helperText="JSON Schema for the decoded content (optional)"
                  sx={{
                    bgcolor: isDark ? '#1e293b' : 'white',
                    '& .MuiInputBase-input': { fontFamily: '"JetBrains Mono", "Fira Code", monospace', fontSize: '0.8rem' },
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                  }}
                />
              </Box>
            )}
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

            {/* Numeric Format */}
            <Box sx={{ mb: 2.5 }}>
              <Autocomplete
                freeSolo
                size={size}
                value={data.format || ''}
                onChange={(_: any, newValue: string | null) => onChange('format', newValue || '')}
                onInputChange={(_: any, newInputValue: string) => onChange('format', newInputValue)}
                options={FORMAT_OPTIONS[baseType]?.map(opt => opt.value) || []}
                renderOption={(props: any, option: string) => {
                  const formatOption = FORMAT_OPTIONS[baseType]?.find(o => o.value === option);
                  return (
                    <li {...props} key={option}>
                      <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 500 }}>
                          {option}
                        </Typography>
                        {formatOption && (
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            {formatOption.description}
                          </Typography>
                        )}
                      </Box>
                    </li>
                  );
                }}
                renderInput={(params: any) => (
                  <TextField
                    {...params}
                    label="Format"
                    placeholder={baseType === 'integer' ? 'int32, int64' : 'float, double'}
                    helperText={`Numeric format hint (${baseType === 'integer' ? 'int32 = 32-bit, int64 = 64-bit' : 'float = single, double = double precision'})`}
                    sx={{
                      bgcolor: isDark ? '#0f172a' : 'white',
                      '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    }}
                  />
                )}
              />
            </Box>

            {/* Min/Max on separate row, 50/50 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) minmax(0, 1fr)' }, gap: 2.5, mb: 2.5 }}>
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
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>≥ incl.</Typography>}
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
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>&gt; excl.</Typography>}
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
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>≤ incl.</Typography>}
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
                    label={<Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>&lt; excl.</Typography>}
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
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('multipleOf', e.target.value)}
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
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('minItems', e.target.value)}
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
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('maxItems', e.target.value)}
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
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange('uniqueItems', e.target.checked)}
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
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('minContains', e.target.value)}
                    inputProps={{ min: 1 }}
                    sx={{ '& .MuiOutlinedInput-root': { borderRadius: 1.5 } }}
                  />
                  <TextField
                    label="Max Contains"
                    type="number"
                    size={size}
                    fullWidth
                    value={data.maxContains || ''}
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('maxContains', e.target.value)}
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
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
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
                      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('itemsSchema', e.target.value)}
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
                      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('unevaluatedItemsSchema', e.target.value)}
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
          <div className="mt-3 space-y-4 w-full min-w-0">
            <div className="p-4 rounded-lg border bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700 w-full min-w-0">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 min-w-0">
                  <Settings className="h-4 w-4 shrink-0 text-indigo-500" />
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Object Constraints</h4>
                </div>
                <Badge variant="secondary" className="text-xs shrink-0">OpenAPI 3.1</Badge>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1 min-w-0">
                  <Label htmlFor="prop-min-properties">Min Properties</Label>
                  <Input
                    id="prop-min-properties"
                    type="number"
                    min={0}
                    value={data.minProperties ?? ''}
                    onChange={(e) => onChange('minProperties', e.target.value)}
                    placeholder="e.g., 1"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400">Minimum number of properties required</p>
                </div>
                <div className="space-y-1 min-w-0">
                  <Label htmlFor="prop-max-properties">Max Properties</Label>
                  <Input
                    id="prop-max-properties"
                    type="number"
                    min={0}
                    value={data.maxProperties ?? ''}
                    onChange={(e) => onChange('maxProperties', e.target.value)}
                    placeholder="e.g., 10"
                  />
                  <p className="text-xs text-gray-500 dark:text-gray-400">Maximum number of properties allowed</p>
                </div>
              </div>
            </div>

            <Box sx={{
              p: 2,
              bgcolor: isDark ? '#0f172a' : 'white',
              borderRadius: 2,
              border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
            }}>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
                Additional Properties
              </p>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'default' || !data.additionalProperties} onChange={() => onChange('additionalProperties', 'default')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Not specified (default)</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'true'} onChange={() => onChange('additionalProperties', 'true')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Allow Any (true)</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'false'} onChange={() => onChange('additionalProperties', 'false')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Disallow (false)</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'type'} onChange={() => onChange('additionalProperties', 'type')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Must Be Type</Typography>}
                  sx={{ m: 0 }}
                />
                {data.additionalProperties === 'type' && (
                  <Box sx={{ pl: 4, mt: 0.5 }}>
                    <FormControl size="small" fullWidth>
                      <MuiSelect
                        value={data.additionalPropertiesType || 'string'}
                        onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('additionalPropertiesType', e.target.value)}
                        sx={{ fontSize: '0.85rem' }}
                      >
                        <MenuItem value="string">string</MenuItem>
                        <MenuItem value="number">number</MenuItem>
                        <MenuItem value="integer">integer</MenuItem>
                        <MenuItem value="boolean">boolean</MenuItem>
                        <MenuItem value="object">object</MenuItem>
                        <MenuItem value="array">array</MenuItem>
                      </MuiSelect>
                    </FormControl>
                  </Box>
                )}
                <FormControlLabel
                  control={<Radio checked={data.additionalProperties === 'schema'} onChange={() => onChange('additionalProperties', 'schema')} size="small" sx={{ '&.Mui-checked': { color: '#6366f1' } }} />}
                  label={<Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#475569' }}>Must Match Schema</Typography>}
                  sx={{ m: 0 }}
                />
                {data.additionalProperties === 'schema' && (
                  <Box sx={{ pl: 4, mt: 0.5 }}>
                    {availableClasses.length > 0 ? (
                      <FormControl size="small" fullWidth>
                        <MuiSelect
                          value={data.additionalPropertiesSchema || ''}
                          onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('additionalPropertiesSchema', e.target.value)}
                          displayEmpty
                          sx={{ fontSize: '0.85rem' }}
                        >
                          <MenuItem value="" disabled>
                            <em>Select a class...</em>
                          </MenuItem>
                          {availableClasses.map((cls) => (
                            <MenuItem key={cls} value={cls}>{cls}</MenuItem>
                          ))}
                        </MuiSelect>
                      </FormControl>
                    ) : (
                      <TextField
                        size="small"
                        fullWidth
                        value={data.additionalPropertiesSchema || ''}
                        onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('additionalPropertiesSchema', e.target.value)}
                        placeholder="ClassName or #/components/schemas/ClassName"
                        helperText="Enter class name or $ref path"
                        sx={{
                          '& .MuiInputBase-input': { fontSize: '0.85rem' },
                          '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                        }}
                      />
                    )}
                  </Box>
                )}
              </Box>
            </Box>

            {/* Pattern Properties */}
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
                  <CodeIcon sx={{ color: '#6366f1', fontSize: 16 }} />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
                    Pattern Properties
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                    Validate properties matching regex patterns
                  </Typography>
                </Box>
              </Box>

              <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', display: 'block', mb: 2 }}>
                Define schemas for properties that match specific patterns. Each pattern is a regular expression.
              </Typography>

              {(() => {
                const patterns = data.patternProperties || {};
                const patternEntries = Object.entries(patterns);


                return (
                  <Box>
                    {patternEntries.length > 0 && (
                      <List sx={{ mb: 2, bgcolor: isDark ? '#1e293b' : '#f8fafc', borderRadius: 2, p: 1 }}>
                        {patternEntries.map(([pattern, schema], index) => (
                          <ListItem
                            key={index}
                            sx={{
                              borderBottom: index < patternEntries.length - 1 ? '1px solid' : 'none',
                              borderColor: isDark ? '#334155' : '#e2e8f0',
                              display: 'flex',
                              flexDirection: 'column',
                              alignItems: 'stretch',
                              gap: 1,
                              py: 1.5,
                            }}
                          >
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography
                                variant="body2"
                                sx={{
                                  fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                                  fontSize: '0.85rem',
                                  color: '#6366f1',
                                  flex: 1,
                                  bgcolor: isDark ? '#0f172a' : 'white',
                                  px: 1,
                                  py: 0.5,
                                  borderRadius: 1,
                                  border: '1px solid',
                                  borderColor: isDark ? '#475569' : '#e2e8f0',
                                }}
                              >
                                {pattern}
                              </Typography>
                              <IconButton
                                size="small"
                                onClick={() => {
                                  const newPatterns = { ...patterns };
                                  delete newPatterns[pattern];
                                  onChange('patternProperties', Object.keys(newPatterns).length > 0 ? newPatterns : undefined);
                                }}
                                sx={{ color: isDark ? '#94a3b8' : '#64748b' }}
                              >
                                <DeleteIcon fontSize="small" />
                              </IconButton>
                            </Box>
                            <PatternPropertySchemaEditor
                              schemaValue={schema}
                              onChange={(newSchema) => {
                                const newPatterns = { ...patterns };
                                newPatterns[pattern] = newSchema;
                                onChange('patternProperties', newPatterns);
                              }}
                              isDark={isDark}
                              rows={5}
                              size="small"
                            />
                          </ListItem>
                        ))}
                      </List>
                    )}

                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                      <TextField
                        label="Pattern (regex)"
                        size={size}
                        fullWidth
                        value={newPattern}
                        onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setNewPattern(e.target.value)}
                        placeholder="^env_|^flag_"
                        helperText="Regular expression to match property names"
                        sx={{
                          '& .MuiInputBase-input': {
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                            fontSize: '0.85rem',
                          },
                          '& .MuiOutlinedInput-root': { borderRadius: 2 },
                          '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                        }}
                      />
                      <PatternPropertySchemaEditor
                        schemaValue={newPatternSchema}
                        onChange={(schema) => setNewPatternSchema(schema)}
                        isDark={isDark}
                        rows={5}
                        size={(size === 'medium' || size === 'small') ? size : 'small'}
                      />
                      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <IconButton
                          size="small"
                          disabled={!newPattern.trim()}
                          onClick={() => {
                            if (!newPattern.trim()) return;
                            const schemaObj = typeof newPatternSchema === 'string' ? JSON.parse(newPatternSchema) : newPatternSchema;
                            const newPatterns = { ...(patterns || {}), [newPattern]: schemaObj };
                            onChange('patternProperties', newPatterns);
                            setNewPattern('');
                            setNewPatternSchema({ type: 'string' });
                          }}
                          sx={{
                            bgcolor: '#6366f1',
                            color: 'white',
                            '&:hover': { bgcolor: '#4f46e5' },
                            '&.Mui-disabled': { bgcolor: isDark ? '#1e293b' : '#e2e8f0', color: isDark ? '#475569' : '#94a3b8' },
                          }}
                        >
                          <AddIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    </Box>

                    {patternEntries.length === 0 && (
                      <Box sx={{
                        p: 2,
                        bgcolor: 'rgba(99, 102, 241, 0.06)',
                        borderRadius: 1.5,
                        border: '1px dashed rgba(99, 102, 241, 0.3)',
                      }}>
                        <Typography variant="caption" sx={{ color: '#4f46e5' }}>
                          <strong>Example:</strong> Pattern <code style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '1px 4px', borderRadius: 3 }}>^env_</code> with schema <code style={{ background: 'rgba(99, 102, 241, 0.15)', padding: '1px 4px', borderRadius: 3 }}>{"{"}"type":"string"{"}"}</code> would validate any property starting with "env_" as a string.
                        </Typography>
                      </Box>
                    )}
                  </Box>
                );
              })()}
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
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('unevaluatedPropertiesSchema', e.target.value)}
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

              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 2, mb: 2 }}>
                <TextField
                  label="Min Length"
                  type="number"
                  size={size}
                  fullWidth
                  value={data.propertyNamesMinLength ?? ''}
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('propertyNamesMinLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  placeholder="e.g., 1"
                  helperText="Minimum"
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
                  onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('propertyNamesMaxLength', e.target.value)}
                  inputProps={{ min: 0 }}
                  placeholder="e.g., 50"
                  helperText="Maximum"
                  sx={{
                    bgcolor: isDark ? '#1e293b' : 'white',
                    '& .MuiOutlinedInput-root': { borderRadius: 2 },
                    '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                  }}
                />
                <FormControl size={size} fullWidth>
                  <Typography variant="caption" sx={{ mb: 0.5, color: isDark ? '#94a3b8' : '#64748b', fontSize: '0.7rem' }}>Format</Typography>
                  <MuiSelect
                    value={data.propertyNamesFormat ?? ''}
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('propertyNamesFormat', e.target.value)}
                    displayEmpty
                    sx={{
                      bgcolor: isDark ? '#1e293b' : 'white',
                      borderRadius: 2,
                      fontSize: '0.85rem',
                    }}
                  >
                    <MenuItem value=""><em>None</em></MenuItem>
                    <MenuItem value="email">email</MenuItem>
                    <MenuItem value="uuid">uuid</MenuItem>
                    <MenuItem value="uri">uri</MenuItem>
                    <MenuItem value="hostname">hostname</MenuItem>
                    <MenuItem value="ipv4">ipv4</MenuItem>
                    <MenuItem value="ipv6">ipv6</MenuItem>
                    <MenuItem value="date">date</MenuItem>
                    <MenuItem value="date-time">date-time</MenuItem>
                  </MuiSelect>
                </FormControl>
              </Box>

              <TextField
                label="Pattern (Regex)"
                size={size}
                fullWidth
                value={data.propertyNamesPattern ?? ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('propertyNamesPattern', e.target.value)}
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


              <TextField
                label="Description"
                size={size}
                fullWidth
                multiline
                rows={2}
                value={data.propertyNamesDescription ?? ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('propertyNamesDescription', e.target.value)}
                placeholder="e.g., Property names must be lowercase, start with letter..."
                helperText="Describe the property name requirements"
                sx={{
                  mt: 2,
                  bgcolor: isDark ? '#1e293b' : 'white',
                  '& .MuiOutlinedInput-root': { borderRadius: 2 },
                  '& .MuiFormHelperText-root': { fontSize: '0.7rem' },
                }}
              />

              {(data.propertyNamesPattern ?? data.propertyNamesMinLength ?? data.propertyNamesMaxLength ?? data.propertyNamesFormat ?? data.propertyNamesDescription) && (
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
                  {data.propertyNamesDescription && (
                    <Typography variant="caption" sx={{ color: '#7c3aed', display: 'block', mb: 1, fontStyle: 'italic' }}>
                      {data.propertyNamesDescription}
                    </Typography>
                  )}
                  <Box component="ul" sx={{ m: 0, pl: 2, '& li': { fontSize: '0.75rem', color: '#7c3aed', mb: 0.5 } }}>
                    {data.propertyNamesFormat && (
                      <li>Names must be valid <code style={{ background: 'rgba(139, 92, 246, 0.15)', padding: '1px 4px', borderRadius: 3 }}>{data.propertyNamesFormat}</code> format</li>
                    )}
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

            {/* Dependent Schemas (JSON Schema 2019-09+) */}
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
                  <CodeIcon sx={{ color: '#6366f1', fontSize: 16 }} />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
                    Dependent Schemas
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                    Conditional schemas based on property values
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
                  JSON Schema 2019-09
                </Typography>
              </Box>

              <Typography variant="caption" sx={{ color: isDark ? '#94a3b8' : '#64748b', display: 'block', mb: 2 }}>
                Define conditional validation schemas based on the value of a property. Each dependent schema applies when the property name matches.
              </Typography>

              {(() => {
                const dependentSchemas = data.dependentSchemas || {};
                const schemaEntries = Object.entries(dependentSchemas);

                return (
                  <Box>
                    {schemaEntries.length > 0 && (
                      <Box sx={{ mb: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {schemaEntries.map(([triggerProp, depSchema]: [string, any], index) => {
                          // Extract values from the schema structure (same logic as ClassEditDialog)
                          const ifCondition = depSchema?.if?.properties?.[triggerProp] || depSchema?.if || {};
                          const thenRequired = depSchema?.then?.required || [];
                          const elseRequired = depSchema?.else?.required || [];
                          const conditionValue = ifCondition?.const !== undefined ? String(ifCondition.const) : (ifCondition?.enum ? ifCondition.enum.join(', ') : '');
                          const conditionType = ifCondition?.const !== undefined ? 'const' : (ifCondition?.enum ? 'enum' : 'present');

                          return (
                            <Box
                              key={index}
                              sx={{
                                p: 2,
                                bgcolor: isDark ? '#1e293b' : '#f8fafc',
                                borderRadius: 2,
                                border: '1px solid',
                                borderColor: isDark ? '#334155' : '#e2e8f0',
                              }}
                            >
                              {/* Header with trigger property and delete button */}
                              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Typography
                                    sx={{
                                      px: 1,
                                      py: 0.5,
                                      bgcolor: isDark ? 'rgba(99, 102, 241, 0.2)' : 'rgba(99, 102, 241, 0.1)',
                                      color: '#6366f1',
                                      borderRadius: 1,
                                      fontFamily: '"JetBrains Mono", monospace',
                                      fontSize: '0.85rem',
                                      fontWeight: 600,
                                    }}
                                  >
                                    {triggerProp}
                                  </Typography>
                                  <Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
                                    triggers conditional validation
                                  </Typography>
                                </Box>
                                <IconButton
                                  size="small"
                                  onClick={() => {
                                    const newSchemas = { ...dependentSchemas };
                                    delete newSchemas[triggerProp];
                                    onChange('dependentSchemas', Object.keys(newSchemas).length > 0 ? newSchemas : undefined);
                                  }}
                                  sx={{ color: '#ef4444', '&:hover': { bgcolor: 'rgba(239, 68, 68, 0.1)' } }}
                                >
                                  <DeleteIcon fontSize="small" />
                                </IconButton>
                              </Box>

                              {/* IF Condition */}
                              <Box sx={{
                                mb: 2,
                                p: 1.5,
                                bgcolor: isDark ? 'rgba(59, 130, 246, 0.1)' : 'rgba(59, 130, 246, 0.05)',
                                borderRadius: 1.5,
                                border: '1px solid',
                                borderColor: isDark ? 'rgba(59, 130, 246, 0.3)' : 'rgba(59, 130, 246, 0.2)',
                              }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                                  <Typography sx={{ px: 1, py: 0.25, bgcolor: '#3b82f6', color: 'white', borderRadius: 0.5, fontSize: '0.7rem', fontWeight: 700 }}>
                                    IF
                                  </Typography>
                                  <Typography variant="body2" sx={{ color: isDark ? '#93c5fd' : '#2563eb', fontWeight: 500 }}>
                                    {triggerProp}
                                  </Typography>
                                </Box>
                                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                                  <FormControl size="small" sx={{ minWidth: 120 }}>
                                    <MuiSelect
                                      value={conditionType}
                                      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                                        const val = e.target.value;
                                        const newSchemas = { ...dependentSchemas };
                                        const newSchema = { ...depSchema };
                                        if (val === 'const') {
                                          newSchema.if = { properties: { [triggerProp]: { const: conditionValue || '' } } };
                                        } else if (val === 'enum') {
                                          newSchema.if = { properties: { [triggerProp]: { enum: conditionValue ? conditionValue.split(',').map((s: string) => s.trim()).filter(Boolean) : [] } } };
                                        } else {
                                          newSchema.if = { properties: { [triggerProp]: {} }, required: [triggerProp] };
                                        }
                                        newSchemas[triggerProp] = newSchema;
                                        onChange('dependentSchemas', newSchemas);
                                      }}
                                      sx={{ fontSize: '0.8rem' }}
                                    >
                                      <MenuItem value="present">is present</MenuItem>
                                      <MenuItem value="const">equals</MenuItem>
                                      <MenuItem value="enum">is one of</MenuItem>
                                    </MuiSelect>
                                  </FormControl>
                                  {(conditionType === 'const' || conditionType === 'enum') && (
                                    <TextField
                                      size="small"
                                      value={conditionValue}
                                      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                                        const newSchemas = { ...dependentSchemas };
                                        const newSchema = { ...depSchema };
                                        if (conditionType === 'const') {
                                          newSchema.if = { properties: { [triggerProp]: { const: e.target.value } } };
                                        } else {
                                          newSchema.if = { properties: { [triggerProp]: { enum: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) } } };
                                        }
                                        newSchemas[triggerProp] = newSchema;
                                        onChange('dependentSchemas', newSchemas);
                                      }}
                                      placeholder={conditionType === 'enum' ? 'value1, value2, ...' : 'value'}
                                      sx={{ flex: 1, minWidth: 150, '& .MuiInputBase-input': { fontSize: '0.8rem' } }}
                                    />
                                  )}
                                </Box>
                              </Box>

                              {/* THEN - Required Properties */}
                              <Box sx={{
                                mb: 2,
                                p: 1.5,
                                bgcolor: isDark ? 'rgba(34, 197, 94, 0.1)' : 'rgba(34, 197, 94, 0.05)',
                                borderRadius: 1.5,
                                border: '1px solid',
                                borderColor: isDark ? 'rgba(34, 197, 94, 0.3)' : 'rgba(34, 197, 94, 0.2)',
                              }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                                  <Typography sx={{ px: 1, py: 0.25, bgcolor: '#22c55e', color: 'white', borderRadius: 0.5, fontSize: '0.7rem', fontWeight: 700 }}>
                                    THEN
                                  </Typography>
                                  <Typography variant="body2" sx={{ color: isDark ? '#86efac' : '#16a34a' }}>
                                    require these properties:
                                  </Typography>
                                </Box>
                                <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'wrap' }}>
                                  {thenRequired.map((prop: string, idx: number) => (
                                    <Chip
                                      key={idx}
                                      label={prop}
                                      size="small"
                                      onDelete={() => {
                                        const newSchemas = { ...dependentSchemas };
                                        const newSchema = { ...depSchema, then: { ...depSchema.then, required: thenRequired.filter((_: any, i: number) => i !== idx) } };
                                        newSchemas[triggerProp] = newSchema;
                                        onChange('dependentSchemas', newSchemas);
                                      }}
                                      sx={{
                                        bgcolor: isDark ? 'rgba(34, 197, 94, 0.2)' : 'rgba(34, 197, 94, 0.15)',
                                        color: isDark ? '#86efac' : '#16a34a',
                                        '& .MuiChip-deleteIcon': { color: isDark ? '#86efac' : '#16a34a' },
                                      }}
                                    />
                                  ))}
                                  <TextField
                                    size="small"
                                    placeholder="+ Add property"
                                    onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                                      if (e.key === 'Enter') {
                                        const input = e.target as HTMLInputElement;
                                        const val = input.value.trim();
                                        if (val && !thenRequired.includes(val)) {
                                          const newSchemas = { ...dependentSchemas };
                                          const newSchema = { ...depSchema, then: { ...depSchema.then, required: [...thenRequired, val] } };
                                          newSchemas[triggerProp] = newSchema;
                                          onChange('dependentSchemas', newSchemas);
                                          input.value = '';
                                        }
                                      }
                                    }}
                                    sx={{ width: 130, '& .MuiInputBase-input': { fontSize: '0.75rem', py: 0.5 } }}
                                  />
                                </Box>
                              </Box>

                              {/* ELSE - Required Properties */}
                              <Box sx={{
                                p: 1.5,
                                bgcolor: isDark ? 'rgba(245, 158, 11, 0.1)' : 'rgba(245, 158, 11, 0.05)',
                                borderRadius: 1.5,
                                border: '1px solid',
                                borderColor: isDark ? 'rgba(245, 158, 11, 0.3)' : 'rgba(245, 158, 11, 0.2)',
                              }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                                  <Typography sx={{ px: 1, py: 0.25, bgcolor: '#f59e0b', color: 'white', borderRadius: 0.5, fontSize: '0.7rem', fontWeight: 700 }}>
                                    ELSE
                                  </Typography>
                                  <Typography variant="body2" sx={{ color: isDark ? '#fcd34d' : '#d97706' }}>
                                    require these properties instead:
                                  </Typography>
                                  <Typography variant="caption" sx={{ color: isDark ? '#fcd34d' : '#d97706', opacity: 0.7 }}>
                                    (optional)
                                  </Typography>
                                </Box>
                                <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'wrap' }}>
                                  {elseRequired.map((prop: string, idx: number) => (
                                    <Chip
                                      key={idx}
                                      label={prop}
                                      size="small"
                                      onDelete={() => {
                                        const newSchemas = { ...dependentSchemas };
                                        const newSchema = { ...depSchema, else: { ...depSchema.else, required: elseRequired.filter((_: any, i: number) => i !== idx) } };
                                        newSchemas[triggerProp] = newSchema;
                                        onChange('dependentSchemas', newSchemas);
                                      }}
                                      sx={{
                                        bgcolor: isDark ? 'rgba(245, 158, 11, 0.2)' : 'rgba(245, 158, 11, 0.15)',
                                        color: isDark ? '#fcd34d' : '#d97706',
                                        '& .MuiChip-deleteIcon': { color: isDark ? '#fcd34d' : '#d97706' },
                                      }}
                                    />
                                  ))}
                                  <TextField
                                    size="small"
                                    placeholder="+ Add property"
                                    onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                                      if (e.key === 'Enter') {
                                        const input = e.target as HTMLInputElement;
                                        const val = input.value.trim();
                                        if (val && !elseRequired.includes(val)) {
                                          const newSchemas = { ...dependentSchemas };
                                          const newSchema = { ...depSchema, else: { ...(depSchema.else || {}), required: [...elseRequired, val] } };
                                          newSchemas[triggerProp] = newSchema;
                                          onChange('dependentSchemas', newSchemas);
                                          input.value = '';
                                        }
                                      }
                                    }}
                                    sx={{ width: 130, '& .MuiInputBase-input': { fontSize: '0.75rem', py: 0.5 } }}
                                  />
                                </Box>
                              </Box>

                              {/* Raw JSON toggle */}
                              <Box sx={{ mt: 1.5 }}>
                                <details>
                                  <summary style={{ fontSize: '0.7rem', color: isDark ? '#94a3b8' : '#64748b', cursor: 'pointer' }}>
                                    View/Edit Raw JSON
                                  </summary>
                                  <TextField
                                    size="small"
                                    fullWidth
                                    multiline
                                    rows={4}
                                    value={JSON.stringify(depSchema, null, 2)}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                                      try {
                                        const parsed = JSON.parse(e.target.value);
                                        const newSchemas = { ...dependentSchemas };
                                        newSchemas[triggerProp] = parsed;
                                        onChange('dependentSchemas', newSchemas);
                                      } catch {
                                        // Invalid JSON, don't update
                                      }
                                    }}
                                    sx={{
                                      mt: 1,
                                      '& .MuiInputBase-input': {
                                        fontFamily: '"JetBrains Mono", monospace',
                                        fontSize: '0.7rem',
                                      },
                                    }}
                                  />
                                </details>
                              </Box>
                            </Box>
                          );
                        })}
                      </Box>
                    )}

                    {/* Add new dependent schema */}
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <TextField
                        size="small"
                        value={newDepPropName}
                        onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setNewDepPropName(e.target.value)}
                        placeholder="Enter trigger property name"
                        sx={{
                          flex: 1,
                          '& .MuiInputBase-input': {
                            fontFamily: '"JetBrains Mono", monospace',
                            fontSize: '0.85rem',
                          },
                        }}
                      />
                      <Button
                        variant="contained"
                        size="small"
                        disabled={!newDepPropName.trim()}
                        onClick={() => {
                          if (newDepPropName.trim()) {
                            const newSchemas = {
                              ...(dependentSchemas || {}),
                              [newDepPropName.trim()]: {
                                if: { properties: { [newDepPropName.trim()]: {} } },
                                then: { required: [] },
                                else: { required: [] }
                              }
                            };
                            onChange('dependentSchemas', newSchemas);
                            setNewDepPropName('');
                          }
                        }}
                        sx={{
                          bgcolor: '#6366f1',
                          '&:hover': { bgcolor: '#4f46e5' },
                          textTransform: 'none',
                        }}
                        startIcon={<AddIcon />}
                      >
                        Add
                      </Button>
                    </Box>

                    {schemaEntries.length === 0 && (
                      <Box sx={{
                        mt: 2,
                        p: 2,
                        bgcolor: 'rgba(99, 102, 241, 0.06)',
                        borderRadius: 1.5,
                        border: '1px dashed rgba(99, 102, 241, 0.3)',
                      }}>
                        <Typography variant="caption" sx={{ color: '#4f46e5' }}>
                          <strong>Tip:</strong> Add conditional validation rules. When a property has a specific value, require additional properties.
                        </Typography>
                      </Box>
                    )}
                  </Box>
                );
              })()}
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
          </div>
        )}
      </Box>

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 4: Values (Const & Enum)
          ═══════════════════════════════════════════════════════════════════════════ */}
      {(baseType === 'string' || baseType === 'number' || baseType === 'integer' || baseType === 'boolean') && (
        <Box
          data-section-id="values"
          sx={{
            p: 3,
            borderBottom: isDark ? '1px solid #1f2937' : '1px solid #e2e8f0',
            background: isDark
              ? 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)'
              : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
          }}
        >
          <SectionHeader
            icon={<CodeIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
            title="Allowed Values"
            subtitle="Restrict to specific values"
            changed={changedSections.values}
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
                onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
                helperText={data.enum && data.enum.length > 0 ? 'Cannot use const when enum values are defined (mutually exclusive)' : 'Mutually exclusive with enum values'}
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
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setEnumInput(e.target.value); setEnumError(''); }}
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

                {(() => {
                  const safeEnum = Array.isArray(data.enum) ? data.enum.filter((v) => v != null) : [];
                  if (safeEnum.length === 0) return null;
                  const sortableIds = safeEnum.map((v) => String(v));
                  return (
                    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleEnumDragEnd}>
                      <List dense sx={{
                        bgcolor: isDark ? '#1e293b' : '#f8fafc',
                        borderRadius: 2,
                        maxHeight: 150,
                        overflow: 'auto',
                        border: isDark ? '1px solid #475569' : '1px solid #e2e8f0',
                      }}>
                        <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                          {safeEnum.map((value) => (
                            <SortableEnumItem key={String(value)} id={String(value)} value={value} onDelete={handleRemoveEnum} />
                          ))}
                        </SortableContext>
                      </List>
                    </DndContext>
                  );
                })()}
              </Box>
            )}
          </Box>
        </Box>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════════
          SECTION 5: Advanced (NOT Composition, External Docs, Extensions)
          ═══════════════════════════════════════════════════════════════════════════ */}
      <Box
        data-section-id="advanced"
        sx={{
          p: 3,
          width: '100%',
          minWidth: 0,
          bgcolor: isDark ? '#1e293b' : 'white',
        }}
      >
        <SectionHeader
          icon={<SettingsIcon sx={{ color: '#6366f1', fontSize: 18 }} />}
          title="Advanced"
          subtitle="Extended schema options"
          changed={changedSections.advanced}
        />

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 3, width: '100%', minWidth: 0 }}>
          {/* NOT Composition */}
          <Box sx={{
            p: 2.5,
            minWidth: 0,
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
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('not', e.target.value)}
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
            minWidth: 0,
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
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('externalDocsUrl', e.target.value)}
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
              onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange('externalDocsDescription', e.target.value)}
              placeholder="Brief description..."
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
            />
          </Box>
        </Box>

        {/* XML Object (OpenAPI 3.1) — match ClassEditDialog section styling */}
        <div className="mt-3 w-full min-w-0 p-4 rounded-lg border bg-white dark:bg-slate-800 border-orange-200 dark:border-orange-900">
          <div className="flex items-center justify-between mb-3 gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Code className="h-4 w-4 shrink-0 text-orange-500" />
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">XML Representation</h4>
            </div>
            <Badge variant="secondary" className="text-xs shrink-0 bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300">
              OpenAPI 3.1
            </Badge>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            Configure how this property is serialized to XML format
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 w-full min-w-0">
            <div className="space-y-1 min-w-0">
              <Label htmlFor="prop-xml-name">XML Name</Label>
              <Input
                id="prop-xml-name"
                value={data.xmlName ?? ''}
                onChange={(e) => onChange('xmlName', e.target.value)}
                placeholder="e.g., CustomName"
              />
            </div>
            <div className="space-y-1 min-w-0">
              <Label htmlFor="prop-xml-namespace">Namespace</Label>
              <Input
                id="prop-xml-namespace"
                value={data.xmlNamespace ?? ''}
                onChange={(e) => onChange('xmlNamespace', e.target.value)}
                placeholder="http://example.com/ns"
              />
            </div>
            <div className="space-y-1 min-w-0">
              <Label htmlFor="prop-xml-prefix">Prefix</Label>
              <Input
                id="prop-xml-prefix"
                value={data.xmlPrefix ?? ''}
                onChange={(e) => onChange('xmlPrefix', e.target.value)}
                placeholder="e.g., ns1"
              />
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:flex-wrap gap-4 pt-3 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-start gap-2 min-w-0">
              <ShadcnCheckbox
                id="prop-xml-attribute"
                className="mt-0.5"
                checked={data.xmlAttribute || false}
                onCheckedChange={(c) => onChange('xmlAttribute', c === true)}
              />
              <div className="space-y-0.5 min-w-0">
                <Label htmlFor="prop-xml-attribute" className="text-sm font-medium cursor-pointer">
                  Attribute
                </Label>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Render as XML attribute instead of element
                </p>
              </div>
            </div>
            <div className={`flex items-start gap-2 min-w-0 ${!isArray ? 'opacity-50' : ''}`}>
              <ShadcnCheckbox
                id="prop-xml-wrapped"
                className="mt-0.5"
                checked={data.xmlWrapped || false}
                disabled={!isArray}
                onCheckedChange={(c) => onChange('xmlWrapped', c === true)}
              />
              <div className="space-y-0.5 min-w-0">
                <Label htmlFor="prop-xml-wrapped" className={`text-sm font-medium cursor-pointer ${!isArray ? 'cursor-not-allowed' : ''}`}>
                  Wrapped
                </Label>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Wrap array items in container element{!isArray ? ' (arrays only)' : ''}
                </p>
              </div>
            </div>
          </div>

          {(data.xmlName || data.xmlNamespace || data.xmlPrefix || data.xmlAttribute || data.xmlWrapped) && (
            <div className="mt-3 p-3 rounded-md border border-orange-200 dark:border-orange-800 bg-orange-50/60 dark:bg-orange-950/40">
              <p className="text-xs font-mono text-orange-700 dark:text-orange-300">XML Output Preview:</p>
              <p className="text-xs font-mono text-gray-800 dark:text-gray-200 mt-1 break-all">
                {data.xmlAttribute
                  ? `<parent ${data.xmlPrefix ? `${data.xmlPrefix}:` : ''}${data.xmlName || 'propertyName'}="value" />`
                  : data.xmlWrapped && isArray
                    ? `<${data.xmlPrefix ? `${data.xmlPrefix}:` : ''}${data.xmlName || 'propertyName'}><item>...</item></${data.xmlPrefix ? `${data.xmlPrefix}:` : ''}${data.xmlName || 'propertyName'}>`
                    : `<${data.xmlPrefix ? `${data.xmlPrefix}:` : ''}${data.xmlName || 'propertyName'}${data.xmlNamespace ? ` xmlns="${data.xmlNamespace}"` : ''}>value</${data.xmlPrefix ? `${data.xmlPrefix}:` : ''}${data.xmlName || 'propertyName'}>`
                }
              </p>
            </div>
          )}
        </div>

        {/* Schema Metadata ($comment) — match ClassEditDialog Schema Metadata card */}
        <div className="mt-3 w-full min-w-0 p-4 rounded-lg border bg-white dark:bg-slate-800 border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-3 gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <FileText className="h-4 w-4 shrink-0 text-indigo-500" />
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Schema Metadata</h4>
            </div>
            <Badge variant="secondary" className="text-xs shrink-0">JSON Schema 2020-12</Badge>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            Advanced schema identification and documentation
          </p>
          <div className="space-y-1 min-w-0">
            <Label htmlFor="prop-schema-comment">$comment</Label>
            <Textarea
              id="prop-schema-comment"
              rows={2}
              value={data.$comment || ''}
              onChange={(e) => onChange('$comment', e.target.value)}
              placeholder="Internal notes for schema authors..."
              className="resize-y min-h-[72px]"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400">Comments for schema authors (not shown to API consumers)</p>
          </div>
        </div>

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
    </Box>
  );
};
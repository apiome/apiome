import React, { memo, useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Edit, Trash2, ChevronRight, ChevronDown, Palette } from 'lucide-react';
import { useDialog } from '../../providers/DialogProvider';
import * as Popover from '@radix-ui/react-popover';

// Define custom node data type for classes
type ClassProperty = {
  id: string;
  name: string;
  type?: string;
  description?: string;
  data?: any; // JSONB data containing the property schema
  parent_id?: string | null; // Parent property ID for nested properties
};

type ClassNodeTheme = {
  backgroundColor?: string;
  borderColor?: string;
  headerGradient?: string;
  textColor?: string;
  headerTextColor?: string;
};

type ClassNodeData = {
  id: string;
  name: string;
  description?: string;
  properties?: ClassProperty[];
  schema?: any; // Schema containing allOf/anyOf/oneOf
  tags?: Array<{ id: string; tag_name: string; tag_color: string }>;
  onPropertyDrop?: (classId: string, propertyData: any, parentId?: string | null) => void;
  onPropertyEdit?: (classId: string, classProperty: ClassProperty) => void;
  onPropertyDelete?: (classId: string, classPropertyId: string) => void;
  onClassEdit?: (classData: any) => void;
  onClassDelete?: (classId: string, className: string) => void;
  onCreateReference?: (classOrCompositeId: string) => void;
  onThemeChange?: (classId: string, theme: ClassNodeTheme) => void;
  isReadOnly?: boolean;
  expandedProperties?: Set<string>; // Global expanded properties state
  onTogglePropertyExpansion?: (propertyId: string) => void; // Callback to toggle property expansion
  zoomLevel?: number; // Current zoom level for level-of-detail rendering
  lodEnabled?: boolean; // Whether LOD is enabled (defaults to true)
  theme?: ClassNodeTheme; // Custom theme from canvas_metadata
};

function ClassNode({ data, selected }: NodeProps) {
  const typedData = data as ClassNodeData;
  const { confirm: confirmDialog } = useDialog();

  const [dragTarget, setDragTarget] = useState<'node' | 'property' | null>(null);
  const [dragOverPropertyId, setDragOverPropertyId] = useState<string | null>(null);
  const [localExpandedProperties, setLocalExpandedProperties] = useState<Set<string>>(new Set());
  const [colorPickerOpen, setColorPickerOpen] = useState(false);

  // Predefined color themes (4x4 grid = 16 colors) - matching GroupNode colors
  const colorThemes = [
    { name: 'Slate', hex: '#64748b', headerGradient: 'linear-gradient(135deg, #64748b 0%, #475569 100%)', backgroundColor: '#f8fafc', borderColor: '#64748b', textColor: '#1e293b', headerTextColor: '#ffffff' },
    { name: 'Gray', hex: '#6b7280', headerGradient: 'linear-gradient(135deg, #6b7280 0%, #4b5563 100%)', backgroundColor: '#f9fafb', borderColor: '#6b7280', textColor: '#111827', headerTextColor: '#ffffff' },
    { name: 'Zinc', hex: '#71717a', headerGradient: 'linear-gradient(135deg, #71717a 0%, #52525b 100%)', backgroundColor: '#fafafa', borderColor: '#71717a', textColor: '#18181b', headerTextColor: '#ffffff' },
    { name: 'Stone', hex: '#78716c', headerGradient: 'linear-gradient(135deg, #78716c 0%, #57534e 100%)', backgroundColor: '#fafaf9', borderColor: '#78716c', textColor: '#1c1917', headerTextColor: '#ffffff' },
    { name: 'Red', hex: '#ef4444', headerGradient: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)', backgroundColor: '#fef2f2', borderColor: '#ef4444', textColor: '#991b1b', headerTextColor: '#ffffff' },
    { name: 'Orange', hex: '#f97316', headerGradient: 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)', backgroundColor: '#fff7ed', borderColor: '#f97316', textColor: '#9a3412', headerTextColor: '#ffffff' },
    { name: 'Amber', hex: '#f59e0b', headerGradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)', backgroundColor: '#fffbeb', borderColor: '#f59e0b', textColor: '#92400e', headerTextColor: '#ffffff' },
    { name: 'Yellow', hex: '#eab308', headerGradient: 'linear-gradient(135deg, #eab308 0%, #ca8a04 100%)', backgroundColor: '#fefce8', borderColor: '#eab308', textColor: '#854d0e', headerTextColor: '#ffffff' },
    { name: 'Lime', hex: '#84cc16', headerGradient: 'linear-gradient(135deg, #84cc16 0%, #65a30d 100%)', backgroundColor: '#f7fee7', borderColor: '#84cc16', textColor: '#3f6212', headerTextColor: '#ffffff' },
    { name: 'Green', hex: '#22c55e', headerGradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', backgroundColor: '#ecfdf5', borderColor: '#10b981', textColor: '#065f46', headerTextColor: '#ffffff' },
    { name: 'Emerald', hex: '#10b981', headerGradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', backgroundColor: '#ecfdf5', borderColor: '#10b981', textColor: '#065f46', headerTextColor: '#ffffff' },
    { name: 'Teal', hex: '#14b8a6', headerGradient: 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)', backgroundColor: '#f0fdfa', borderColor: '#14b8a6', textColor: '#115e59', headerTextColor: '#ffffff' },
    { name: 'Cyan', hex: '#06b6d4', headerGradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)', backgroundColor: '#ecfeff', borderColor: '#06b6d4', textColor: '#164e63', headerTextColor: '#ffffff' },
    { name: 'Sky', hex: '#0ea5e9', headerGradient: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)', backgroundColor: '#f0f9ff', borderColor: '#0ea5e9', textColor: '#0c4a6e', headerTextColor: '#ffffff' },
    { name: 'Blue', hex: '#3b82f6', headerGradient: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)', backgroundColor: '#eff6ff', borderColor: '#3b82f6', textColor: '#1e40af', headerTextColor: '#ffffff' },
    { name: 'Indigo', hex: '#6366f1', headerGradient: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)', backgroundColor: '#eef2ff', borderColor: '#6366f1', textColor: '#3730a3', headerTextColor: '#ffffff' },
  ];

  const handleThemeSelect = (theme: Omit<ClassNodeTheme, 'name'>) => {
    if (typedData.onThemeChange) {
      typedData.onThemeChange(typedData.id, theme);
    }
  };

  // Level of detail calculations based on zoom
  // At zoom < 0.5 (50% - zoomed out), show minimal detail (class name only)
  // At zoom 0.5-1.0, transition from minimal to full detail
  // At zoom >= 1.0 (zoomed in), show full detail
  const zoom = typedData.zoomLevel ?? 1;
  const lodEnabled = typedData.lodEnabled ?? true; // Default to enabled if not specified

  // Calculate opacity for different detail levels
  // Properties fade out completely when zoomed out to 50% or less
  // If LOD is disabled, always show full opacity
  const propertiesOpacity = lodEnabled ? Math.max(0, Math.min(1, (zoom - 0.5) / 0.5)) : 1;

  // Description fades out when zooming out to 75% or less
  // If LOD is disabled, always show full opacity
  const descriptionOpacity = lodEnabled ? Math.max(0, Math.min(1, (zoom - 0.75) / 0.25)) : 1;

  // Tags fade out at same rate as description
  const tagsOpacity = descriptionOpacity;

  // Show properties only when there's visible opacity (or LOD is disabled)
  const showProperties = !lodEnabled || propertiesOpacity > 0.05;
  const showDescription = !lodEnabled || descriptionOpacity > 0.05;
  const showTags = !lodEnabled || tagsOpacity > 0.05;

  // Use global expanded state if provided, otherwise use local state
  const expandedProperties = typedData.expandedProperties || localExpandedProperties;

  const togglePropertyExpansion = (propertyId: string) => {
    if (typedData.onTogglePropertyExpansion) {
      // Use global handler if provided
      typedData.onTogglePropertyExpansion(propertyId);
    } else {
      // Fall back to local state
      const next = new Set(localExpandedProperties);
      if (next.has(propertyId)) next.delete(propertyId); else next.add(propertyId);
      setLocalExpandedProperties(next);
    }
  };

  // Build hierarchical property structure
  const buildPropertyHierarchy = (): { topLevel: ClassProperty[]; childMap: Map<string, ClassProperty[]> } => {
    const all = typedData.properties || [];
    const topLevel = all.filter((p) => !p.parent_id);
    const childMap = new Map<string, ClassProperty[]>();
    all.forEach((p) => {
      if (p.parent_id) {
        if (!childMap.has(p.parent_id)) childMap.set(p.parent_id, []);
        childMap.get(p.parent_id)!.push(p);
      }
    });
    return { topLevel, childMap };
  };

  // Helpers for schema parsing
  const parseData = (prop: ClassProperty) => (typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data || {});

  // Helper to get base type from nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
  const getBaseType = (propData: any): string | undefined => {
    if (Array.isArray(propData?.type)) {
      return propData.type.find((t: string) => t !== 'null');
    }
    return propData?.type;
  };

  const hasRef = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    const baseType = getBaseType(d);
    // Check for direct $ref
    if (d?.$ref) return true;
    // Check for array items $ref
    if (baseType === 'array' && d?.items?.$ref) return true;
    // Check for composition types (allOf/anyOf/oneOf)
    if (d?.allOf || d?.anyOf || d?.oneOf) return true;
    // Check for composition types in array items
    if (baseType === 'array' && d?.items) {
      if (d.items.allOf || d.items.anyOf || d.items.oneOf) return true;
    }
    return false;
  };

  const isInlineObjectContainer = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    const baseType = getBaseType(d);
    if (baseType === 'object' && !d.$ref) return true;
    if (baseType === 'array') {
      const items = d.items || {};
      if (items.type === 'object' && !items.$ref) return true;
      // If items is missing but we have inline children attached, treat as container
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      return hasInlineChildren;
    }
    return false;
  };

  const isDescendantOfDraggedProperty = (propertyId: string, draggedParentId: string | null): boolean => {
    if (!draggedParentId) return false;
    const all = typedData.properties || [];
    let current = all.find((p) => p.id === propertyId);
    while (current && current.parent_id) {
      if (current.parent_id === draggedParentId) return true;
      current = all.find((p) => p.id === current!.parent_id);
    }
    return false;
  };

  const getPropertyType = (prop: ClassProperty): string => {
    const d = parseData(prop);

    // Handle allOf/anyOf/oneOf compositions
    if (d?.allOf && Array.isArray(d.allOf)) {
      const types = d.allOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `allOf(${types.length})` : 'allOf';
    }
    if (d?.anyOf && Array.isArray(d.anyOf)) {
      const types = d.anyOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `anyOf(${types.length})` : 'anyOf';
    }
    if (d?.oneOf && Array.isArray(d.oneOf)) {
      const types = d.oneOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `oneOf(${types.length})` : 'oneOf';
    }

    if (d?.type === 'array') {
      // Handle composition in array items
      if (d.items?.allOf && Array.isArray(d.items.allOf)) {
        const types = d.items.allOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `allOf(${types.length})[]` : 'allOf[]';
      }
      if (d.items?.anyOf && Array.isArray(d.items.anyOf)) {
        const types = d.items.anyOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `anyOf(${types.length})[]` : 'anyOf[]';
      }
      if (d.items?.oneOf && Array.isArray(d.items.oneOf)) {
        const types = d.items.oneOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `oneOf(${types.length})[]` : 'oneOf[]';
      }
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        return `${refName}[]`;
      }
      if (d.items?.type) {
        return `${d.items.type}[]`;
      }
      // Items missing or unassigned reference
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        if (refName === '__unassigned__') return '(unassigned)[]';
        return `${refName}[]`;
      }
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      return hasInlineChildren ? 'object[]' : 'any[]';
    }

    // Handle nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
    const baseType = getBaseType(d);
    const isNullable = Array.isArray(d?.type) && d.type.includes('null');

    if (baseType === 'array') {
      // Handle composition in array items
      if (d.items?.allOf && Array.isArray(d.items.allOf)) {
        const types = d.items.allOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `allOf(${types.length})[]${suffix}` : `allOf[]${suffix}`;
      }
      if (d.items?.anyOf && Array.isArray(d.items.anyOf)) {
        const types = d.items.anyOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `anyOf(${types.length})[]${suffix}` : `anyOf[]${suffix}`;
      }
      if (d.items?.oneOf && Array.isArray(d.items.oneOf)) {
        const types = d.items.oneOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `oneOf(${types.length})[]${suffix}` : `oneOf[]${suffix}`;
      }
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        const suffix = isNullable ? '?' : '';
        return `${refName}[]${suffix}`;
      }
      if (d.items?.type) {
        const suffix = isNullable ? '?' : '';
        return `${d.items.type}[]${suffix}`;
      }
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      const suffix = isNullable ? '?' : '';
      return hasInlineChildren ? `object[]${suffix}` : `any[]${suffix}`;
    }

    if (d?.$ref) {
      const refName = d.$ref.split('/').pop();
      if (refName === '__unassigned__') return '(unassigned)';
      const suffix = isNullable ? '?' : '';
      return `$ref${suffix}`;
    }

    const typeName = baseType || prop.type || 'object';
    const suffix = isNullable ? '?' : '';
    return `${typeName}${suffix}`;
  };

  // DnD Handlers (top-level)
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragTarget !== 'property') setDragTarget('node');
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    if (typedData.isReadOnly) return;
    try {
      const raw = e.dataTransfer.getData('application/json');
      if (raw) {
        const dropData = JSON.parse(raw);
        if (dropData.type === 'property' && typedData.onPropertyDrop) {
          typedData.onPropertyDrop(typedData.id, dropData.property, null);
        } else if (dropData.type === 'new-reference' && typedData.onCreateReference) {
          // Create reference at top-level on this class
          typedData.onCreateReference(typedData.id);
        }
      }
    } catch (err) {
      console.error('Error handling property drop:', err);
    }
  };

  // DnD Handlers (per-property for containers)
  const handlePropertyDragOver = (e: React.DragEvent, propertyId: string, isObject: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    if (isObject) {
      setDragTarget('property');
      setDragOverPropertyId(propertyId);
    } else {
      setDragTarget('node');
      setDragOverPropertyId(null);
    }
  };

  const handlePropertyDragLeave = (e: React.DragEvent, propertyId: string, isObject: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
  };

  const handlePropertyDrop = (e: React.DragEvent, parentPropertyId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    if (typedData.isReadOnly) return;
    try {
      const raw = e.dataTransfer.getData('application/json');
      if (raw) {
        const dropData = JSON.parse(raw);
        if (dropData.type === 'property' && typedData.onPropertyDrop) {
          typedData.onPropertyDrop(typedData.id, dropData.property, parentPropertyId);
        } else if (dropData.type === 'new-reference' && typedData.onCreateReference) {
          // Create nested reference under the given parent property (object container)
          typedData.onCreateReference(`${typedData.id}|${parentPropertyId}`);
        }
      }
    } catch (err) {
      console.error('Error handling nested property drop:', err);
    }
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (typedData.onClassEdit) {
      typedData.onClassEdit({
        id: typedData.id,
        name: typedData.name,
        description: typedData.description,
        schema: typedData.schema,
        properties: typedData.properties,
      });
    }
  };

  const { topLevel, childMap } = buildPropertyHierarchy();

  // Determine header accent color based on state and custom theme
  const getHeaderGradient = () => {
    if (typedData.theme?.headerGradient) return typedData.theme.headerGradient;
    if (dragTarget === 'node') return 'linear-gradient(135deg, #059669 0%, #047857 100%)';
    if (selected) return 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)';
    return 'linear-gradient(135deg, #64748b 0%, #475569 100%)';
  };

  // Get custom colors from theme or defaults
  const backgroundColor = typedData.theme?.backgroundColor || 'white';
  const borderColor = typedData.theme?.borderColor || (selected ? '#6366f1' : '#e2e8f0');
  const textColor = typedData.theme?.textColor || '#1e293b';
  const headerTextColor = typedData.theme?.headerTextColor || 'white';

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onDoubleClick={handleDoubleClick}
      style={{
        borderRadius: '12px',
        border: `2px solid ${borderColor}`,
        background: backgroundColor,
        minWidth: '260px',
        maxWidth: '400px',
        boxShadow: selected
          ? `0 0 0 2px ${borderColor}, 0 10px 40px -10px rgba(99, 102, 241, 0.4), 0 4px 20px -4px rgba(0, 0, 0, 0.1)`
          : dragTarget === 'node'
          ? '0 0 0 2px #10b981, 0 10px 40px -10px rgba(16, 185, 129, 0.3), 0 4px 20px -4px rgba(0, 0, 0, 0.1)'
          : '0 4px 24px -4px rgba(0, 0, 0, 0.12), 0 1px 4px rgba(0, 0, 0, 0.04)',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        overflow: 'hidden',
        cursor: 'pointer',
        color: textColor,
      }}
    >
      {/* Target handle at the top */}
      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: selected ? '#6366f1' : '#94a3b8',
          width: '10px',
          height: '10px',
          border: '2px solid white',
          borderRadius: '50%',
          boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
          transition: 'background 0.2s ease',
        }}
        isConnectable={true}
      />

      {/* Header */}
      <div
        style={{
          background: getHeaderGradient(),
          padding: '12px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '10px',
          position: 'relative',
        }}
      >
        {/* Subtle pattern overlay */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(circle at 100% 0%, rgba(255,255,255,0.1) 0%, transparent 50%)',
          pointerEvents: 'none',
        }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0, position: 'relative', zIndex: 1 }}>
          {/* Class icon */}
          <div style={{
            width: '28px',
            height: '28px',
            borderRadius: '8px',
            background: 'rgba(255, 255, 255, 0.2)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '12px',
            fontWeight: 700,
            color: headerTextColor,
            flexShrink: 0,
            letterSpacing: '-0.5px',
          }}>
            {typedData.name.substring(0, 2).toUpperCase()}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: '14px',
              fontWeight: 600,
              color: headerTextColor,
              letterSpacing: '-0.01em',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              textDecoration: typedData.schema?.deprecated ? 'line-through' : 'none',
              opacity: typedData.schema?.deprecated ? 0.7 : 1,
            }}>
              {typedData.name}
            </div>

            {/* Tags inline with name */}
            {showTags && typedData.tags && typedData.tags.length > 0 && (
              <div style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '4px',
                marginTop: '4px',
                opacity: tagsOpacity,
                transition: 'opacity 0.3s ease-in-out'
              }}>
                {typedData.tags.map((tag) => {
                  const colorMap: Record<string, { bg: string; border: string }> = {
                    default: { bg: 'rgba(255, 255, 255, 0.15)', border: 'rgba(255, 255, 255, 0.25)' },
                    primary: { bg: 'rgba(99, 102, 241, 0.3)', border: 'rgba(99, 102, 241, 0.5)' },
                    secondary: { bg: 'rgba(168, 85, 247, 0.3)', border: 'rgba(168, 85, 247, 0.5)' },
                    error: { bg: 'rgba(239, 68, 68, 0.3)', border: 'rgba(239, 68, 68, 0.5)' },
                    warning: { bg: 'rgba(245, 158, 11, 0.3)', border: 'rgba(245, 158, 11, 0.5)' },
                    info: { bg: 'rgba(59, 130, 246, 0.3)', border: 'rgba(59, 130, 246, 0.5)' },
                    success: { bg: 'rgba(16, 185, 129, 0.3)', border: 'rgba(16, 185, 129, 0.5)' },
                  };
                  const colors = colorMap[tag.tag_color] || colorMap.default;
                  return (
                    <span
                      key={tag.id}
                      style={{
                        fontSize: '9px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        background: colors.bg,
                        color: 'white',
                        fontWeight: 500,
                        border: `1px solid ${colors.border}`,
                        whiteSpace: 'nowrap',
                        backdropFilter: 'blur(4px)',
                      }}
                    >
                      {tag.tag_name}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {!typedData.isReadOnly && (
          <div style={{ display: 'flex', gap: '4px', alignItems: 'center', position: 'relative', zIndex: 1 }}>
            {/* Color picker button using Popover */}
            <Popover.Root open={colorPickerOpen} onOpenChange={setColorPickerOpen}>
              <Popover.Trigger asChild>
                <button
                  style={{
                    background: 'rgba(255, 255, 255, 0.15)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '6px',
                    padding: '6px',
                    cursor: 'pointer',
                    color: 'rgba(255, 255, 255, 0.9)',
                    fontSize: '14px',
                    lineHeight: 1,
                    transition: 'all 0.2s ease',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    backdropFilter: 'blur(4px)',
                  }}
                  onClick={(e) => e.stopPropagation()}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.25)';
                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.4)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)';
                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)';
                  }}
                  title="Change colors"
                >
                  <Palette size={14} />
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-3"
                  sideOffset={5}
                  onOpenAutoFocus={(e) => e.preventDefault()}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="grid grid-cols-4 gap-2">
                    {colorThemes.map((color) => (
                      <button
                        key={color.name}
                        onClick={() => handleThemeSelect(color)}
                        className="w-6 h-6 rounded-full border-2 transition-transform hover:scale-110"
                        style={{ backgroundColor: color.hex }}
                        title={color.name}
                      />
                    ))}
                  </div>
                  <Popover.Arrow className="fill-white dark:fill-gray-800" />
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
            {/* Delete button */}
            <button
              style={{
                background: 'rgba(255, 255, 255, 0.15)',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                borderRadius: '6px',
                padding: '6px',
                cursor: 'pointer',
                color: 'rgba(255, 255, 255, 0.9)',
                fontSize: '14px',
                lineHeight: 1,
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                backdropFilter: 'blur(4px)',
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (typedData.onClassDelete) typedData.onClassDelete(typedData.id, typedData.name);
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.8)';
                e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.9)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)';
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)';
              }}
              title="Delete class"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Description / Drop zone */}
      {showDescription && (
        <div
          style={{
            padding: '10px 16px',
            fontSize: '12px',
            color: dragTarget === 'node' ? '#059669' : '#64748b',
            lineHeight: '1.5',
            background: dragTarget === 'node'
              ? 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)'
              : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
            borderBottom: `1px solid ${dragTarget === 'node' ? '#a7f3d0' : '#e2e8f0'}`,
            textAlign: dragTarget === 'node' ? 'center' : 'left',
            fontWeight: dragTarget === 'node' ? 500 : 400,
            minHeight: '40px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: dragTarget === 'node' ? 'center' : 'flex-start',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            opacity: descriptionOpacity,
            transition: 'all 0.3s ease-in-out',
            fontStyle: typedData.description ? 'normal' : 'italic',
          }}
        >
          {dragTarget === 'node' ? '✨ Drop property here' : (typedData.description || 'No description')}
        </div>
      )}

      {/* Properties */}
      {showProperties && (
        <div style={{
          padding: '4px 0',
          opacity: propertiesOpacity,
          transition: 'opacity 0.3s ease-in-out'
        }}>
          {(topLevel.length > 0 ? topLevel : []).length > 0 ? (
          topLevel.flatMap((prop, idx) => {
            let rowIndex = 0;
            const renderProperty = (p: ClassProperty, depth: number): React.JSX.Element[] => {
              const container = isInlineObjectContainer(p);
              const children = childMap.get(p.id) || [];
              const isExpanded = expandedProperties.has(p.id);
              const draggedOver = dragOverPropertyId === p.id;
              const childOfDragged = isDescendantOfDraggedProperty(p.id, dragOverPropertyId);
              const isInDropZone = draggedOver || childOfDragged;
              const currentIndex = rowIndex++;
              const isRequired = p.data?.required;
              const isDeprecated = parseData(p)?.deprecated;

              const row: React.JSX.Element[] = [];
              row.push(
                <div
                  key={p.id}
                  onDragOver={!typedData.isReadOnly ? (e) => handlePropertyDragOver(e, p.id, container) : undefined}
                  onDragLeave={!typedData.isReadOnly ? (e) => handlePropertyDragLeave(e, p.id, container) : undefined}
                  onDrop={container && !typedData.isReadOnly ? (e) => handlePropertyDrop(e, p.id) : undefined}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '20px 1fr auto 44px',
                    alignItems: 'center',
                    padding: '8px 12px 8px 12px',
                    paddingLeft: `${12 + depth * 16}px`,
                    margin: '0 8px',
                    marginBottom: '2px',
                    borderRadius: '6px',
                    background: isInDropZone
                      ? 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)'
                      : 'transparent',
                    position: 'relative',
                    gap: '6px',
                    transition: 'all 0.15s ease',
                    cursor: 'default',
                  }}
                  onMouseEnter={(e) => {
                    if (!isInDropZone) {
                      e.currentTarget.style.background = '#f8fafc';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isInDropZone) {
                      e.currentTarget.style.background = 'transparent';
                    }
                  }}
                >
                  <div style={{ width: '16px', display: 'flex', alignItems: 'center' }}>
                    {container && (
                      <button
                        onClick={(e) => { e.stopPropagation(); togglePropertyExpansion(p.id); }}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          cursor: 'pointer',
                          padding: '2px',
                          borderRadius: '4px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#94a3b8',
                          transition: 'all 0.15s ease',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = '#e2e8f0';
                          e.currentTarget.style.color = '#475569';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'transparent';
                          e.currentTarget.style.color = '#94a3b8';
                        }}
                        title={isExpanded ? 'Collapse' : 'Expand'}
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                    )}
                  </div>

                  <div
                    style={{
                      fontWeight: 500,
                      color: isDeprecated ? '#94a3b8' : '#1e293b',
                      fontSize: '12px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      textDecoration: isDeprecated ? 'line-through' : 'none',
                      letterSpacing: '-0.01em',
                    }}
                    title={isDeprecated ? (parseData(p)?.deprecationMessage || 'Deprecated') : undefined}
                  >
                    {isRequired && (
                      <span style={{
                        color: '#ef4444',
                        fontSize: '14px',
                        fontWeight: 700,
                        lineHeight: 1,
                      }}>*</span>
                    )}
                    <span>{p.name}</span>
                    {children.length > 0 && (
                      <span style={{
                        color: '#94a3b8',
                        fontSize: '10px',
                        fontWeight: 500,
                        background: '#f1f5f9',
                        padding: '1px 5px',
                        borderRadius: '10px',
                      }}>
                        {children.length}
                      </span>
                    )}
                  </div>

                  <div style={{
                    fontSize: '10px',
                    color: '#64748b',
                    fontFamily: '"SF Mono", Monaco, "Cascadia Code", monospace',
                    whiteSpace: 'nowrap',
                    background: '#f1f5f9',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 500,
                    letterSpacing: '-0.02em',
                  }}>
                    {getPropertyType(p)}
                  </div>

                  {!typedData.isReadOnly && (
                    <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
                      {typedData.onPropertyEdit && (
                        <button
                          onClick={(e) => { e.stopPropagation(); typedData.onPropertyEdit!(typedData.id, p); }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '4px',
                            borderRadius: '4px',
                            color: '#94a3b8',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            transition: 'all 0.15s ease',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = '#e0e7ff';
                            e.currentTarget.style.color = '#6366f1';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'transparent';
                            e.currentTarget.style.color = '#94a3b8';
                          }}
                          title="Edit property"
                        >
                          <Edit size={12} />
                        </button>
                      )}
                      {typedData.onPropertyDelete && (
                        <button
                          onClick={async (e) => {
                            e.stopPropagation();
                            const confirmed = await confirmDialog({
                              title: 'Remove Property',
                              message: `Remove "${p.name}" from this class?`,
                              variant: 'warning',
                              confirmLabel: 'Remove',
                              cancelLabel: 'Cancel',
                            });
                            if (confirmed) typedData.onPropertyDelete!(typedData.id, p.id);
                          }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '4px',
                            borderRadius: '4px',
                            color: '#94a3b8',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            transition: 'all 0.15s ease',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = '#fee2e2';
                            e.currentTarget.style.color = '#ef4444';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'transparent';
                            e.currentTarget.style.color = '#94a3b8';
                          }}
                          title="Remove property from class"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  )}

                  {/* Property reference handle: only show for properties with $ref */}
                  {hasRef(p) && (
                    <Handle
                      type="source"
                      position={Position.Right}
                      id={`prop-${p.id}`}
                      style={{
                        right: '-6px',
                        background: '#6366f1',
                        width: '10px',
                        height: '10px',
                        border: '2px solid white',
                        borderRadius: '50%',
                        position: 'absolute',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        zIndex: 1000,
                        boxShadow: '0 2px 4px rgba(99, 102, 241, 0.3)',
                      }}
                      isConnectable={!typedData.isReadOnly}
                    />
                  )}
                </div>
              );

              if (container && isExpanded && children.length > 0) {
                children.forEach((c) => row.push(...renderProperty(c, depth + 1)));
              }

              return row;
            };

            return renderProperty(prop, 0);
          })
        ) : (
          <div style={{
            padding: '16px 12px',
            textAlign: 'center',
            color: '#94a3b8',
            fontSize: '12px',
            fontStyle: 'italic',
            background: 'linear-gradient(135deg, #fafafa 0%, #f5f5f5 100%)',
            borderRadius: '0 0 12px 12px',
          }}>
            No properties
          </div>
        )}
        </div>
      )}

      {/* Bottom handle for composition relationships */}
      {typedData.schema && (() => {
        const schema = typeof (typedData.schema as any) === 'string' ? JSON.parse(typedData.schema as any) : (typedData.schema as any);
        const hasComposition =
          (schema?.allOf && Array.isArray(schema.allOf) && schema.allOf.some((it: any) => it.$ref)) ||
          (schema?.anyOf && Array.isArray(schema.anyOf) && schema.anyOf.some((it: any) => it.$ref)) ||
          (schema?.oneOf && Array.isArray(schema.oneOf) && schema.oneOf.some((it: any) => it.$ref));

        let handleColor = '#94a3b8';
        let shadowColor = 'rgba(0, 0, 0, 0.1)';
        if (schema?.allOf && schema.allOf.length > 0) {
          handleColor = '#3b82f6';
          shadowColor = 'rgba(59, 130, 246, 0.3)';
        } else if (schema?.anyOf && schema.anyOf.length > 0) {
          handleColor = '#f97316';
          shadowColor = 'rgba(249, 115, 22, 0.3)';
        } else if (schema?.oneOf && schema.oneOf.length > 0) {
          handleColor = '#a855f7';
          shadowColor = 'rgba(168, 85, 247, 0.3)';
        }

        return hasComposition ? (
          <Handle
            key="comp-bottom"
            type="source"
            position={Position.Bottom}
            id="comp-bottom"
            style={{
              left: '50%',
              bottom: '-6px',
              transform: 'translateX(-50%)',
              background: handleColor,
              width: '12px',
              height: '12px',
              border: '2px solid white',
              borderRadius: '50%',
              boxShadow: `0 2px 6px ${shadowColor}`,
              transition: 'all 0.2s ease',
            }}
            isConnectable={false}
          />
        ) : null;
      })()}
    </div>
  );
}

export default memo(ClassNode);

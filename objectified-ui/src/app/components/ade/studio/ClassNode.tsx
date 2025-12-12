import React, { memo, useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Edit, Trash2, ChevronRight, ChevronDown } from 'lucide-react';
import { useDialog } from '../../providers/DialogProvider';

// Define custom node data type for classes
type ClassProperty = {
  id: string;
  name: string;
  type?: string;
  description?: string;
  data?: any; // JSONB data containing the property schema
  parent_id?: string | null; // Parent property ID for nested properties
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
  isReadOnly?: boolean;
  expandedProperties?: Set<string>; // Global expanded properties state
  onTogglePropertyExpansion?: (propertyId: string) => void; // Callback to toggle property expansion
};

function ClassNode({ data, selected }: NodeProps) {
  const typedData = data as ClassNodeData;
  const { confirm: confirmDialog } = useDialog();

  const [dragTarget, setDragTarget] = useState<'node' | 'property' | null>(null);
  const [dragOverPropertyId, setDragOverPropertyId] = useState<string | null>(null);
  const [localExpandedProperties, setLocalExpandedProperties] = useState<Set<string>>(new Set());

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

  const hasRef = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    // Check for direct $ref
    if (d?.$ref) return true;
    // Check for array items $ref
    if (d?.type === 'array' && d?.items?.$ref) return true;
    // Check for composition types (allOf/anyOf/oneOf)
    if (d?.allOf || d?.anyOf || d?.oneOf) return true;
    // Check for composition types in array items
    if (d?.type === 'array' && d?.items) {
      if (d.items.allOf || d.items.anyOf || d.items.oneOf) return true;
    }
    return false;
  };

  const isInlineObjectContainer = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    if (d?.type === 'object' && !d.$ref) return true;
    if (d?.type === 'array') {
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
    if (d?.$ref) {
      const refName = d.$ref.split('/').pop();
      if (refName === '__unassigned__') return '(unassigned)';
      return '$ref';
    }
    return d?.type || prop.type || 'object';
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
    const related = e.relatedTarget as HTMLElement | null;
    const current = e.currentTarget as HTMLElement;
    if (!related || !current.contains(related)) {
      setDragTarget(null);
      setDragOverPropertyId(null);
    }
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
    if (isObject) {
      const related = e.relatedTarget as HTMLElement | null;
      const current = e.currentTarget as HTMLElement;
      if (!related || !current.contains(related)) {
        setDragOverPropertyId(null);
        setDragTarget('node');
      }
    }
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

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onDoubleClick={handleDoubleClick}
      style={{
        borderRadius: '4px',
        border: `1px solid ${dragTarget === 'node' ? '#10b981' : selected ? '#5b68ea' : '#d1d5db'}`,
        background: 'white',
        minWidth: '240px',
        maxWidth: '380px',
        boxShadow: selected ? '0 2px 8px rgba(91, 104, 234, 0.2)' : '0 1px 3px rgba(0, 0, 0, 0.08)',
        transition: 'all 0.2s ease',
        overflow: 'hidden',
        cursor: 'pointer',
      }}
    >
      {/* Target handle at the top */}
      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: '#6b7280',
          width: '8px',
          height: '8px',
          border: '2px solid white',
          borderRadius: '50%'
        }}
        isConnectable={true}
      />

      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, #5b68ea 0%, #4751c4 100%)',
          padding: '8px 12px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: dragTarget === 'node' ? '2px solid #10b981' : 'none',
          gap: '8px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '14px', fontWeight: 600, color: 'white', wordBreak: 'break-word', textDecoration: typedData.schema?.deprecated ? 'line-through' : 'none' }}>
            {typedData.name}
          </div>
          {typedData.schema?.deprecated && (
            <span style={{ fontSize: '10px', padding: '2px 5px', borderRadius: '3px', background: '#fef3c7', color: '#92400e', fontWeight: 600, border: '1px solid #fbbf24' }} title={typedData.schema?.deprecationMessage || 'Deprecated'}>
              DEPRECATED
            </span>
          )}
          {/* Tags in header */}
          {typedData.tags && typedData.tags.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
              {typedData.tags.map((tag) => {
                const colorMap: Record<string, string> = {
                  default: 'rgba(255, 255, 255, 0.25)',
                  primary: 'rgba(255, 255, 255, 0.3)',
                  secondary: 'rgba(147, 51, 234, 0.4)',
                  error: 'rgba(239, 68, 68, 0.4)',
                  warning: 'rgba(245, 158, 11, 0.4)',
                  info: 'rgba(59, 130, 246, 0.4)',
                  success: 'rgba(16, 185, 129, 0.4)',
                };
                const bgColor = colorMap[tag.tag_color] || colorMap.default;
                return (
                  <span
                    key={tag.id}
                    style={{
                      fontSize: '9px',
                      padding: '2px 5px',
                      borderRadius: '3px',
                      background: bgColor,
                      color: 'white',
                      fontWeight: 600,
                      border: '1px solid rgba(255, 255, 255, 0.3)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {tag.tag_name}
                  </span>
                );
              })}
            </div>
          )}
        </div>
        {!typedData.isReadOnly && (
          <button
            style={{
              background: 'rgba(255, 255, 255, 0.2)',
              border: 'none',
              borderRadius: '3px',
              padding: '4px 6px',
              cursor: 'pointer',
              color: 'white',
              fontSize: '14px',
              lineHeight: 1,
              transition: 'all 0.2s',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onClick={(e) => {
              e.stopPropagation();
              if (typedData.onClassDelete) typedData.onClassDelete(typedData.id, typedData.name);
            }}
            title="Delete class"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {/* Description / Drop zone */}
      <div
        style={{
          padding: '8px 12px',
          fontSize: '11px',
          color: dragTarget === 'node' ? '#065f46' : '#9ca3af',
          lineHeight: '1.4',
          background: dragTarget === 'node' ? '#d1fae5' : '#fafafa',
          borderBottom: dragTarget === 'node' ? '1px solid #10b981' : '1px solid #e5e7eb',
          textAlign: dragTarget === 'node' ? 'center' : 'left',
          fontWeight: dragTarget === 'node' ? 500 : 'normal',
          height: '31.2px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: dragTarget === 'node' ? 'center' : 'flex-start',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          transition: 'all 0.15s ease',
        }}
      >
        {dragTarget === 'node' ? 'Drop property here' : (typedData.description || '\u00A0')}
      </div>

      {/* Properties */}
      <div style={{ padding: 0 }}>
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

              const row: React.JSX.Element[] = [];
              row.push(
                <div
                  key={p.id}
                  onDragOver={!typedData.isReadOnly ? (e) => handlePropertyDragOver(e, p.id, container) : undefined}
                  onDragLeave={!typedData.isReadOnly ? (e) => handlePropertyDragLeave(e, p.id, container) : undefined}
                  onDrop={container && !typedData.isReadOnly ? (e) => handlePropertyDrop(e, p.id) : undefined}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '20px 1fr auto 50px auto',
                    alignItems: 'center',
                    padding: '6px 4px 6px 12px',
                    paddingLeft: `${12 + depth * 16}px`,
                    borderBottom: '1px solid #e5e7eb',
                    background: isInDropZone ? '#d1fae5' : (currentIndex % 2 === 0 ? 'white' : '#fafafa'),
                    position: 'relative',
                    gap: '4px',
                    transition: 'background 0.2s',
                  }}
                >
                  <div style={{ width: '16px', display: 'flex', alignItems: 'center' }}>
                    {container && (
                      <button
                        onClick={(e) => { e.stopPropagation(); togglePropertyExpansion(p.id); }}
                        style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280' }}
                        title={isExpanded ? 'Collapse' : 'Expand'}
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                    )}
                  </div>

                  <div style={{ fontWeight: depth > 0 ? 400 : 500, color: parseData(p)?.deprecated ? '#9ca3af' : '#111827', fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '4px', textDecoration: parseData(p)?.deprecated ? 'line-through' : 'none' }} title={parseData(p)?.deprecated ? (parseData(p)?.deprecationMessage || 'Deprecated') : undefined}>
                    {p.data.required && '* '} {p.name}
                    {children.length > 0 && <span style={{ color: '#6b7280', marginLeft: 4 }}>({children.length})</span>}
                  </div>

                  <div style={{ fontSize: '11px', color: '#6b7280', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                    {getPropertyType(p)}
                  </div>

                  {!typedData.isReadOnly && (
                    <div style={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                      {typedData.onPropertyEdit && (
                        <button
                          onClick={(e) => { e.stopPropagation(); typedData.onPropertyEdit!(typedData.id, p); }}
                          style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 2, borderRadius: 2, color: '#9ca3af' }}
                          title="Edit property"
                        >
                          <Edit size={11} />
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
                          style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 2, borderRadius: 2, color: '#9ca3af' }}
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
                        background: '#5b68ea',
                        width: '10px',
                        height: '10px',
                        border: '2px solid white',
                        borderRadius: '50%',
                        position: 'absolute',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        zIndex: 1000
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
          <div style={{ padding: 12, textAlign: 'center', color: '#9ca3af', fontSize: '11px', fontStyle: 'italic' }}>
            No properties
          </div>
        )}
      </div>

      {/* Bottom handle for composition relationships */}
      {typedData.schema && (() => {
        const schema = typeof (typedData.schema as any) === 'string' ? JSON.parse(typedData.schema as any) : (typedData.schema as any);
        const hasComposition =
          (schema?.allOf && Array.isArray(schema.allOf) && schema.allOf.some((it: any) => it.$ref)) ||
          (schema?.anyOf && Array.isArray(schema.anyOf) && schema.anyOf.some((it: any) => it.$ref)) ||
          (schema?.oneOf && Array.isArray(schema.oneOf) && schema.oneOf.some((it: any) => it.$ref));

        let handleColor = '#6b7280';
        if (schema?.allOf && schema.allOf.length > 0) handleColor = '#2563eb';
        else if (schema?.anyOf && schema.anyOf.length > 0) handleColor = '#ea580c';
        else if (schema?.oneOf && schema.oneOf.length > 0) handleColor = '#9333ea';

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
              border: '3px solid white',
              borderRadius: '50%',
              boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
            }}
            isConnectable={false}
          />
        ) : null;
      })()}
    </div>
  );
}

export default memo(ClassNode);


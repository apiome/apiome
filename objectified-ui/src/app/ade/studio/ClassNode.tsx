import { memo, useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Edit, Trash2 } from 'lucide-react';

// Define custom node data type for classes
type ClassProperty = {
  id: string;
  name: string;
  type?: string;
  description?: string;
  data?: any; // JSONB data containing the property schema
};

type ClassNodeData = {
  id: string;
  name: string;
  description?: string;
  properties?: ClassProperty[];
  schema?: any; // Schema containing allOf/anyOf/oneOf
  onPropertyDrop?: (classId: string, propertyData: any) => void;
  onPropertyEdit?: (classId: string, classProperty: ClassProperty) => void;
  onPropertyDelete?: (classId: string, classPropertyId: string) => void;
  onClassEdit?: (classData: any) => void;
};

function ClassNode({ data, selected }: NodeProps) {
  const typedData = data as ClassNodeData;
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    try {
      const data = e.dataTransfer.getData('application/json');
      if (data) {
        const dropData = JSON.parse(data);
        if (dropData.type === 'property' && typedData.onPropertyDrop) {
          typedData.onPropertyDrop(typedData.id, dropData.property);
        }
      }
    } catch (error) {
      console.error('Error handling property drop:', error);
    }
  };

  // Extract type from property data
  const getPropertyType = (prop: ClassProperty): string => {
    if (!prop.data) return prop.type || 'object';

    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;

    if (propData.type === 'array') {
      if (propData.items?.$ref) {
        const refName = propData.items.$ref.split('/').pop();
        return `array[]`;
      }
      return `${propData.items?.type || 'items'}[]`;
    }

    if (propData.$ref) {
      return '$ref';
    }

    return propData.type || 'object';
  };

  // Check if property has $ref
  const hasRef = (prop: ClassProperty): boolean => {
    if (!prop.data) return false;
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
    return !!(propData?.$ref || (propData?.type === 'array' && propData?.items?.$ref));
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (typedData.onClassEdit) {
      typedData.onClassEdit({
        id: typedData.id,
        name: typedData.name,
        description: typedData.description,
        schema: typedData.schema,
        properties: typedData.properties
      });
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onDoubleClick={handleDoubleClick}
      style={{
        borderRadius: '4px',
        border: `1px solid ${isDragOver ? '#10b981' : selected ? '#5b68ea' : '#d1d5db'}`,
        background: 'white',
        minWidth: '240px',
        maxWidth: '380px',
        boxShadow: selected
          ? '0 2px 8px rgba(91, 104, 234, 0.2)'
          : '0 1px 3px rgba(0, 0, 0, 0.08)',
        transition: 'all 0.2s ease',
        overflow: 'hidden'
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

      {/* Header with class name and delete button */}
      <div style={{
        background: 'linear-gradient(135deg, #5b68ea 0%, #4751c4 100%)',
        padding: '8px 12px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: isDragOver ? '2px solid #10b981' : 'none'
      }}>
        <div style={{
          fontSize: '14px',
          fontWeight: 600,
          color: 'white',
          wordBreak: 'break-word',
          flex: 1
        }}>
          {typedData.name}
        </div>
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
            justifyContent: 'center'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(255, 255, 255, 0.3)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(255, 255, 255, 0.2)';
          }}
          title="Delete class"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Description */}
      {typedData.description && (
        <div style={{
          padding: '8px 12px',
          fontSize: '11px',
          color: '#9ca3af',
          lineHeight: '1.4',
          background: '#fafafa',
          borderBottom: '1px solid #e5e7eb'
        }}>
          {typedData.description}
        </div>
      )}

      {/* Drop zone hint when dragging */}
      {isDragOver && (
        <div style={{
          padding: '8px 16px',
          background: '#d1fae5',
          fontSize: '12px',
          color: '#065f46',
          textAlign: 'center',
          fontWeight: 500,
          borderBottom: '1px solid #10b981'
        }}>
          Drop property here
        </div>
      )}

      {/* Properties list */}
      <div style={{ padding: '0' }}>
        {typedData.properties && typedData.properties.length > 0 ? (
          typedData.properties.map((prop, index) => {
            const propertyHasRef = hasRef(prop);

            return (
              <div
                key={prop.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto 50px auto',
                  alignItems: 'center',
                  padding: '6px 4px 6px 12px',
                  borderBottom: index < typedData.properties!.length - 1 ? '1px solid #e5e7eb' : 'none',
                  background: index % 2 === 0 ? 'white' : '#fafafa',
                  position: 'relative',
                  gap: '8px'
                }}
              >
                {/* Property name */}
                <div style={{
                  fontWeight: 400,
                  color: '#111827',
                  fontSize: '12px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {prop.name}
                </div>

                {/* Type */}
                <div style={{
                  fontSize: '11px',
                  color: '#6b7280',
                  fontFamily: 'monospace',
                  whiteSpace: 'nowrap'
                }}>
                  {getPropertyType(prop)}
                </div>

                {/* Action buttons */}
                <div style={{ display: 'flex', gap: '2px', justifyContent: 'flex-end' }}>
                  {typedData.onPropertyEdit && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        typedData.onPropertyEdit!(typedData.id, prop);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: '2px',
                        color: '#9ca3af',
                        fontSize: '11px',
                        lineHeight: 1,
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = '#dbeafe';
                        e.currentTarget.style.color = '#2563eb';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = '#9ca3af';
                      }}
                      title="Edit property"
                    >
                      <Edit size={11} />
                    </button>
                  )}
                  {typedData.onPropertyDelete && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Remove "${prop.name}" from this class?`)) {
                          typedData.onPropertyDelete!(typedData.id, prop.id);
                        }
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: '2px',
                        color: '#9ca3af',
                        fontSize: '13px',
                        lineHeight: 1,
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = '#fee2e2';
                        e.currentTarget.style.color = '#dc2626';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = '#9ca3af';
                      }}
                      title="Remove property from class"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>

                {/* Handle for $ref properties */}
                {propertyHasRef && (
                  <Handle
                    type="source"
                    position={Position.Right}
                    id={`prop-${prop.id}`}
                    style={{
                      right: '-6px',
                      background: '#5b68ea',
                      width: '10px',
                      height: '10px',
                      border: '2px solid white',
                      borderRadius: '50%',
                      position: 'absolute',
                      top: '50%',
                      transform: 'translateY(-50%)'
                    }}
                    isConnectable={false}
                  />
                )}
              </div>
            );
          })
        ) : (
          <div style={{
            padding: '12px',
            textAlign: 'center',
            color: '#9ca3af',
            fontSize: '11px',
            fontStyle: 'italic'
          }}>
            No properties
          </div>
        )}
      </div>

      {/* Bottom handles for composition relationships (allOf/anyOf/oneOf) */}
      {typedData.schema && (() => {
        const schema = typeof typedData.schema === 'string' ? JSON.parse(typedData.schema) : typedData.schema;
        const compositions: Array<{ type: string; index: number; ref: string }> = [];

        // Collect all composition types
        if (schema.allOf && Array.isArray(schema.allOf)) {
          schema.allOf.forEach((item: any, index: number) => {
            if (item.$ref) {
              compositions.push({ type: 'allOf', index, ref: item.$ref });
            }
          });
        }
        if (schema.anyOf && Array.isArray(schema.anyOf)) {
          schema.anyOf.forEach((item: any, index: number) => {
            if (item.$ref) {
              compositions.push({ type: 'anyOf', index, ref: item.$ref });
            }
          });
        }
        if (schema.oneOf && Array.isArray(schema.oneOf)) {
          schema.oneOf.forEach((item: any, index: number) => {
            if (item.$ref) {
              compositions.push({ type: 'oneOf', index, ref: item.$ref });
            }
          });
        }

        // Create handles for each composition
        return compositions.map((comp, i) => (
          <Handle
            key={`${comp.type}-${comp.index}`}
            type="source"
            position={Position.Bottom}
            id={`comp-${comp.type}-${comp.index}`}
            style={{
              left: `${30 + (i * 15)}%`,
              background: comp.type === 'allOf' ? '#2563eb' : comp.type === 'anyOf' ? '#ea580c' : '#9333ea',
              width: '10px',
              height: '10px',
              border: '2px solid white',
              borderRadius: '50%'
            }}
            isConnectable={false}
          />
        ));
      })()}
    </div>
  );
}

// Memoize to prevent unnecessary re-renders
export default memo(ClassNode);


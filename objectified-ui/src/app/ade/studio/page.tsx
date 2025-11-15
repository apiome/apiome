'use client';

import { useCallback, useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { useStudio } from './StudioContext';
import { Copy, Download } from 'lucide-react';
import * as yaml from 'js-yaml';
import ClassEditDialog from '../../components/ade/studio/ClassEditDialog';
import ClassPropertyEditDialog from '../../components/ade/studio/ClassPropertyEditDialog';
import ReferenceDialog from '../../components/ade/studio/ReferenceDialog';
import { generateOpenApiSpec } from '../../utils/openapi';
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  addEdge,
  Background,
  Controls,
  MiniMap,
  Panel,
  BackgroundVariant,
  type Connection,
  type Edge,
  type Node,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import 'swagger-ui-react/swagger-ui.css';
import {
  getProjectsForTenant,
  getVersionsForProject,
  getClassesForVersion,
  getPropertiesForClass,
  addPropertyToClass,
  removePropertyFromClass,
  deleteClass,
  updateClassPropertyRef
} from '../../../../lib/db/helper';
import ClassNode from '../../components/ade/studio/ClassNode';
import { getLayoutedElements, type LayoutDirection } from './layoutUtils';

// Dynamically import Monaco Editor with SSR disabled
const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading editor...</div>
    </div>
  ),
});

// Dynamically import Swagger UI with SSR disabled
const SwaggerUI = dynamic(() => import('swagger-ui-react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading Swagger UI...</div>
    </div>
  ),
});

interface Project {
  id: string;
  name: string;
  slug: string;
}

interface Version {
  id: string;
  version_id: string;
  description: string;
  published: boolean;
}

type ViewMode = 'canvas' | 'code' | 'swagger';

const StudioContent = () => {
  const { data: session } = useSession();
  const {
    setSelectedProjectId: setContextProjectId,
    setSelectedVersionId: setContextVersionId,
    canvasRefreshKey,
    triggerSidebarRefresh,
    isReadOnly,
    setIsReadOnly
  } = useStudio();
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [selectedVersionId, setSelectedVersionId] = useState<string>('');
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('canvas');
  const [codeFormat, setCodeFormat] = useState<'json' | 'yaml'>('json');

  // Sample OpenAPI spec - will be replaced with actual data from project/version
  const [openApiSpec, setOpenApiSpec] = useState<string>('');

  const currentTenantId = (session?.user as any)?.current_tenant_id;

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>('TB');
  const { fitView } = useReactFlow();

  // Class-property edit dialog state
  const [editPropertyDialogOpen, setEditPropertyDialogOpen] = useState(false);

  // Class edit dialog state
  const [classEditDialogOpen, setClassEditDialogOpen] = useState(false);
  const [editingClassData, setEditingClassData] = useState<any>(null);
  const [editingClassProperty, setEditingClassProperty] = useState<any>(null);
  // Note: dialog-specific form state moved to ClassPropertyEditDialog component

  // Reference dialog state
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const [referenceTargetClassId, setReferenceTargetClassId] = useState<string>('');


  // Helper to reload classes for current selectedVersionId (used after edits)
  const reloadClasses = useCallback(async () => {
    if (!selectedVersionId) return;

    try {
      const classesResult = await getClassesForVersion(selectedVersionId);
      const classesData = JSON.parse(classesResult);

      const classesWithProperties = await Promise.all(
        classesData.map(async (cls: any) => {
          const propsResult = await getPropertiesForClass(cls.id);
          const properties = JSON.parse(propsResult);
          return { ...cls, properties };
        })
      );

      const newNodes = await classesToNodes(classesWithProperties);
      const newEdges = createAllEdges(classesWithProperties);
      const layoutedNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
      setNodes(layoutedNodes);
      setEdges(newEdges);

      // Regenerate OpenAPI spec
      const currentProject = projects.find(p => p.id === selectedProjectId);
      const currentVersion = versions.find(v => v.id === selectedVersionId);
      const spec = generateOpenApiSpec(classesWithProperties, {
        projectName: currentProject?.name,
        version: currentVersion?.version_id
      });
      setOpenApiSpec(spec);
    } catch (error) {
      console.error('Failed to reload classes:', error);
    }
  }, [selectedVersionId, layoutDirection, setNodes, setEdges, projects, versions, generateOpenApiSpec, isReadOnly]);

  // Apply auto-layout to current nodes and edges
  const onLayout = useCallback((direction: LayoutDirection) => {
    const layoutedNodes = getLayoutedElements(nodes, edges, { direction });
    setNodes(layoutedNodes);
    setLayoutDirection(direction);

    // Fit view after layout with a small delay to ensure layout is applied
    setTimeout(() => {
      fitView({ padding: 0.2, duration: 400 });
    }, 10);
  }, [nodes, edges, setNodes, fitView]);

  // Handle property drop on class
  const handlePropertyDrop = useCallback(async (classId: string, propertyData: any, parentId?: string | null) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    try {
      console.log('Property dropped on class:', classId, propertyData, 'parentId:', parentId);

      // Add property to class in database
      const result = await addPropertyToClass(
        classId,
        propertyData.id,
        propertyData.name,
        propertyData.description || null,
        {
          type: propertyData.type,
          $ref: propertyData.$ref,
          title: propertyData.title,
          description: propertyData.description,
          format: propertyData.format,
          pattern: propertyData.pattern,
          minLength: propertyData.minLength,
          maxLength: propertyData.maxLength,
          minimum: propertyData.minimum,
          maximum: propertyData.maximum,
          minItems: propertyData.minItems,
          maxItems: propertyData.maxItems,
          uniqueItems: propertyData.uniqueItems,
          // Preserve array item schema when present (e.g., items: { type: 'object' } or $ref)
          items: propertyData.items,
          enum: propertyData.enum,
          default: propertyData.default,
          required: propertyData.required
        },
        parentId || null
      );

      const response = JSON.parse(result);
      if (response.success) {
        // Reload classes to show updated properties
        if (selectedVersionId) {
          const classesResult = await getClassesForVersion(selectedVersionId);
          const classesData = JSON.parse(classesResult);

          // Load properties for each class
          const classesWithProperties = await Promise.all(
            classesData.map(async (cls: any) => {
              const propsResult = await getPropertiesForClass(cls.id);
              const properties = JSON.parse(propsResult);
              return { ...cls, properties };
            })
          );

          const newNodes = await classesToNodes(classesWithProperties);
          const newEdges = createAllEdges(classesWithProperties);
          const layoutedNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
          setNodes(layoutedNodes);
          setEdges(newEdges);
        }
      } else {
        alert(response.error || 'Failed to add property to class');
      }
    } catch (error) {
      console.error('Error adding property to class:', error);
      alert('An error occurred while adding the property');
    }
  }, [selectedVersionId, layoutDirection, setNodes, isReadOnly]);

  // Handle property deletion from class
  const handlePropertyDelete = useCallback(async (classId: string, classPropertyId: string) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    try {
      console.log('Removing property from class:', classId, classPropertyId);

      // Remove property from class in database
      const result = await removePropertyFromClass(classPropertyId);
      const response = JSON.parse(result);

      if (response.success) {
        // Reload classes to show updated properties
        if (selectedVersionId) {
          const classesResult = await getClassesForVersion(selectedVersionId);
          const classesData = JSON.parse(classesResult);

          // Load properties for each class
          const classesWithProperties = await Promise.all(
            classesData.map(async (cls: any) => {
              const propsResult = await getPropertiesForClass(cls.id);
              const properties = JSON.parse(propsResult);
              return { ...cls, properties };
            })
          );

          const newNodes = await classesToNodes(classesWithProperties);
          const newEdges = createAllEdges(classesWithProperties);
          const layoutedNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
          setNodes(layoutedNodes);
          setEdges(newEdges);
        }
      } else {
        alert(response.error || 'Failed to remove property from class');
      }
    } catch (error) {
      console.error('Error removing property from class:', error);
      alert('An error occurred while removing the property');
    }
  }, [selectedVersionId, layoutDirection, setNodes, isReadOnly]);

  // Handle reference creation submission
  const handleReferenceSubmit = useCallback(async (referenceData: {
    name: string;
    description: string | null;
    isArray: boolean;
    targetClassId: string | null;
    minItems?: number;
    maxItems?: number;
    uniqueItems?: boolean;
  }) => {
    if (!referenceTargetClassId) return;

    try {
      console.log('Creating reference:', referenceData);

      // Build the data object for the reference
      const data: any = {};

      if (referenceData.isArray) {
        data.type = 'array';
        if (referenceData.minItems) data.minItems = referenceData.minItems;
        if (referenceData.maxItems) data.maxItems = referenceData.maxItems;
        if (referenceData.uniqueItems) data.uniqueItems = referenceData.uniqueItems;

        // Set items.$ref if target class is specified
        if (referenceData.targetClassId) {
          const targetClass = nodes.find(n => n.id === referenceData.targetClassId);
          if (targetClass) {
            const targetClassName = (targetClass.data as any).name;
            data.items = { $ref: `#/components/schemas/${targetClassName}` };
          }
        } else {
          // Empty items placeholder - user can connect later
          data.items = {};
        }
      } else {
        // Set direct $ref if target class is specified
        if (referenceData.targetClassId) {
          const targetClass = nodes.find(n => n.id === referenceData.targetClassId);
          if (targetClass) {
            const targetClassName = (targetClass.data as any).name;
            data.$ref = `#/components/schemas/${targetClassName}`;
          }
        }
        // If no target, leave data empty - it's a placeholder reference
      }

      const parentId: string | null = (window as any).__refParentId || null;
      (window as any).__refParentId = null;

      // Add reference property to class (property_id is null since this is not from the property library)
      const result = await addPropertyToClass(
        referenceTargetClassId,
        null as any, // No property_id - direct class property
        referenceData.name,
        referenceData.description,
        data,
        parentId // Parent can be null for top-level or specific for nested
      );

      const response = JSON.parse(result);
      if (response.success) {
        await reloadClasses();
        triggerSidebarRefresh();
        setReferenceDialogOpen(false);
      } else {
        alert(response.error || 'Failed to create reference');
      }
    } catch (error) {
      console.error('Error creating reference:', error);
      throw error;
    }
  }, [referenceTargetClassId, nodes, reloadClasses, triggerSidebarRefresh]);

  // Handle class edit (double-click on node)
  const handleClassEdit = useCallback(async (classData: any) => {
    // Allow viewing in read-only mode - the dialog will handle read-only restrictions
    console.log(isReadOnly ? 'Viewing class:' : 'Editing class:', classData);
    setEditingClassData(classData);
    setClassEditDialogOpen(true);
  }, [isReadOnly]);

  // Handle property edit from class
  const handlePropertyEdit = useCallback(async (classId: string, classProperty: any) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    console.log('Editing class property:', classId, classProperty);

    // Load the full property data from the class_properties record
    setEditingClassProperty(classProperty);
    setEditPropertyDialogOpen(true);
  }, [isReadOnly]);

  // Handle create reference on class
  const handleCreateReference = useCallback((classOrCompositeId: string) => {
    if (isReadOnly) {
      return;
    }

    // Support nested context: "classId|parentPropertyId" when dropped on an object container
    const [classId, parentId] = classOrCompositeId.split('|');
    setReferenceTargetClassId(classId);
    // Temporarily stash parentId in a data-* attribute on body, or lift to state if preferred
    (window as any).__refParentId = parentId || null;
    setReferenceDialogOpen(true);
  }, [isReadOnly]);

  // Handle class delete from canvas
  const handleClassDelete = useCallback(async (classId: string, className: string) => {
    // Prevent deletes in read-only mode
    if (isReadOnly) {
      return;
    }

    if (!confirm(`Are you sure you want to delete "${className}"? This action cannot be undone.`)) {
      return;
    }

    try {
      console.log('Deleting class:', classId, className);
      const result = await deleteClass(classId);
      const response = JSON.parse(result);

      if (response.success) {
        // Reload classes to update the canvas
        await reloadClasses();
        // Trigger sidebar refresh to update the class list
        triggerSidebarRefresh();
      } else {
        alert(response.error || 'Failed to delete class');
      }
    } catch (error) {
      console.error('Error deleting class:', error);
      alert('An error occurred while deleting the class');
    }
  }, [reloadClasses, triggerSidebarRefresh, isReadOnly]);

  // Define custom node types
  const nodeTypes = {
    classNode: ClassNode,
  };

  // Helper function to convert classes to React Flow nodes
  const classesToNodes = async (classes: any[]): Promise<Node[]> => {
    return classes.map((cls, index) => ({
      id: cls.id,
      type: 'classNode',
      position: {
        x: 100 + (index % 4) * 280, // Arrange in a grid (4 columns)
        y: 100 + Math.floor(index / 4) * 180
      },
      data: {
        id: cls.id,
        name: cls.name,
        description: cls.description,
        properties: cls.properties || [],
        schema: cls.schema, // Pass schema for composition handles
        onPropertyDrop: handlePropertyDrop,
        onPropertyEdit: handlePropertyEdit,
        onPropertyDelete: handlePropertyDelete,
        onClassEdit: handleClassEdit,
        onClassDelete: handleClassDelete,
        onCreateReference: handleCreateReference,
        isReadOnly: isReadOnly
      }
    }));
  };

  // Helper function to extract class name from $ref
  const extractClassNameFromRef = (ref: string): string | null => {
    if (ref.includes('/')) {
      const parts = ref.split('/');
      return parts[parts.length - 1] || null;
    }
    return ref;
  };

  // Helper function to create edges from property $ref relationships
  const createPropertyRefEdges = (classes: any[]): Edge[] => {
    const edges: Edge[] = [];
    const classNameToId = new Map(classes.map(cls => [cls.name, cls.id]));

    classes.forEach((cls) => {
      if (!cls.properties || cls.properties.length === 0) return;

      cls.properties.forEach((prop: any) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
        let refClassName: string | null = null;
        let isSourceArray = false;

        // Direct $ref (one-to-one or many-to-one)
        if (propData.$ref) {
          refClassName = extractClassNameFromRef(propData.$ref);
          isSourceArray = false;
        }
        // $ref in items (one-to-many or many-to-many)
        else if (propData.type === 'array' && propData.items?.$ref) {
          refClassName = extractClassNameFromRef(propData.items.$ref);
          isSourceArray = true;
        }

        // Create edge if we found a reference to another class
        if (refClassName && classNameToId.has(refClassName)) {
          const targetClassId = classNameToId.get(refClassName)!;
          const targetClass = classes.find(c => c.id === targetClassId);

          // Check if target class has a reference back to this class
          let isTargetArray = false;
          let hasReverseRef = false;

          if (targetClass && targetClass.properties) {
            const sourceClassName = cls.name;
            targetClass.properties.forEach((targetProp: any) => {
              const targetPropData = typeof targetProp.data === 'string' ? JSON.parse(targetProp.data) : targetProp.data;
              const targetRefName = targetPropData.$ref
                ? extractClassNameFromRef(targetPropData.$ref)
                : (targetPropData.type === 'array' && targetPropData.items?.$ref
                    ? extractClassNameFromRef(targetPropData.items.$ref)
                    : null);

              if (targetRefName === sourceClassName) {
                hasReverseRef = true;
                isTargetArray = targetPropData.type === 'array';
              }
            });
          }

          // Determine cardinality and styling
          let cardinality: string;
          let edgeColor: string;
          let markerStart: any;
          let markerEnd: any;

          if (isSourceArray && isTargetArray) {
            // Many-to-Many
            cardinality = 'N:N';
            edgeColor = '#ec4899'; // Pink
            markerStart = { type: 'arrow', color: edgeColor, width: 20, height: 20 };
            markerEnd = { type: 'arrow', color: edgeColor, width: 20, height: 20 };
          } else if (isSourceArray && !isTargetArray) {
            // One-to-Many (from target perspective) / Many-to-One (from source perspective)
            cardinality = hasReverseRef ? '1:N' : 'N:1';
            edgeColor = '#8b5cf6'; // Purple
            markerStart = hasReverseRef ? { type: 'arrowclosed', color: edgeColor, width: 20, height: 20 } : undefined;
            markerEnd = { type: 'arrow', color: edgeColor, width: 20, height: 20 };
          } else if (!isSourceArray && isTargetArray) {
            // Many-to-One (from target back to source)
            cardinality = 'N:1';
            edgeColor = '#f59e0b'; // Amber
            markerStart = { type: 'arrow', color: edgeColor, width: 20, height: 20 };
            markerEnd = { type: 'arrowclosed', color: edgeColor, width: 20, height: 20 };
          } else {
            // One-to-One
            cardinality = hasReverseRef ? '1:1' : '1';
            edgeColor = '#3b82f6'; // Blue
            markerStart = hasReverseRef ? { type: 'arrowclosed', color: edgeColor, width: 20, height: 20 } : undefined;
            markerEnd = { type: 'arrowclosed', color: edgeColor, width: 20, height: 20 };
          }

          edges.push({
            id: `prop-${cls.id}-${prop.id}-${targetClassId}`,
            source: cls.id,
            sourceHandle: `prop-${prop.id}`,
            target: targetClassId,
            type: 'smoothstep',
            animated: false,
            label: `${prop.name} (${cardinality})`,
            style: {
              stroke: edgeColor,
              strokeWidth: 2
            },
            markerStart,
            markerEnd,
            labelStyle: {
              fill: '#6b7280',
              fontSize: 11,
              fontWeight: 500
            },
            labelBgStyle: {
              fill: 'white',
              fillOpacity: 0.9
            }
          });
        }
      });
    });

    return edges;
  };

  // Helper function to create edges from composition relationships (allOf/anyOf/oneOf)
  const createCompositionEdges = (classes: any[]): Edge[] => {
    const edges: Edge[] = [];
    const classNameToId = new Map(classes.map(cls => [cls.name, cls.id]));

    classes.forEach((cls) => {
      const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : cls.schema;
      if (!schema) return;

      // allOf - Inheritance (solid line, blue) with multiplicity indicator
      if (schema.allOf && Array.isArray(schema.allOf)) {
        schema.allOf.forEach((item: any, index: number) => {
          if (item.$ref) {
            const refClassName = extractClassNameFromRef(item.$ref);
            if (refClassName && classNameToId.has(refClassName)) {
              edges.push({
                id: `allOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: classNameToId.get(refClassName)!,
                type: 'smoothstep',
                animated: false,
                label: 'allOf',
                style: {
                  stroke: '#2563eb',
                  strokeWidth: 3,
                  strokeDasharray: '0'
                },
                markerEnd: {
                  type: 'arrowclosed',
                  color: '#2563eb',
                  width: 15,
                  height: 15
                },
                labelStyle: {
                  fill: '#2563eb',
                  fontSize: 10,
                  fontWeight: 600
                },
                labelBgStyle: {
                  fill: 'white',
                  fillOpacity: 0.95
                },
                // Add Z-index to layer multiple edges
                zIndex: 10 + index
              });
            }
          }
        });
      }

      // anyOf - Alternatives (dashed line, orange)
      if (schema.anyOf && Array.isArray(schema.anyOf)) {
        schema.anyOf.forEach((item: any, index: number) => {
          if (item.$ref) {
            const refClassName = extractClassNameFromRef(item.$ref);
            if (refClassName && classNameToId.has(refClassName)) {
              edges.push({
                id: `anyOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: classNameToId.get(refClassName)!,
                type: 'smoothstep',
                animated: false,
                label: 'anyOf',
                style: {
                  stroke: '#ea580c',
                  strokeWidth: 3,
                  strokeDasharray: '5,5'
                },
                markerEnd: {
                  type: 'arrowclosed',
                  color: '#ea580c',
                  width: 15,
                  height: 15
                },
                labelStyle: {
                  fill: '#ea580c',
                  fontSize: 10,
                  fontWeight: 600
                },
                labelBgStyle: {
                  fill: 'white',
                  fillOpacity: 0.95
                },
                zIndex: 10 + index
              });
            }
          }
        });
      }

      // oneOf - Exclusive (dotted line, purple)
      if (schema.oneOf && Array.isArray(schema.oneOf)) {
        schema.oneOf.forEach((item: any, index: number) => {
          if (item.$ref) {
            const refClassName = extractClassNameFromRef(item.$ref);
            if (refClassName && classNameToId.has(refClassName)) {
              edges.push({
                id: `oneOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: classNameToId.get(refClassName)!,
                type: 'smoothstep',
                animated: false,
                label: 'oneOf',
                style: {
                  stroke: '#9333ea',
                  strokeWidth: 3,
                  strokeDasharray: '2,3'
                },
                markerEnd: {
                  type: 'arrowclosed',
                  color: '#9333ea',
                  width: 15,
                  height: 15
                },
                labelStyle: {
                  fill: '#9333ea',
                  fontSize: 10,
                  fontWeight: 600
                },
                labelBgStyle: {
                  fill: 'white',
                  fillOpacity: 0.95
                }
              });
            }
          }
        });
      }
    });

    return edges;
  };

  // Helper function to create all edges (properties + composition)
  const createAllEdges = (classes: any[]): Edge[] => {
    const propertyEdges = createPropertyRefEdges(classes);
    const compositionEdges = createCompositionEdges(classes);
    return [...propertyEdges, ...compositionEdges];
  };

  // Helper to flag dangling $refs (referencing a class name that doesn't exist)
  const hasDanglingRefs = (classes: any[]): boolean => {
    const classNames = new Set(classes.map((c) => c.name));
    for (const cls of classes) {
      for (const prop of cls.properties || []) {
        const d = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
        if (!d) continue;
        const ref = d.$ref || (d.type === 'array' && d.items?.$ref);
        if (ref) {
          const refName = extractClassNameFromRef(ref);
          if (refName && !classNames.has(refName)) return true;
        }
      }
    }
    return false;
  };

  // Load projects on mount
  useEffect(() => {
    if (currentTenantId) {
      loadProjects();
    }
  }, [currentTenantId]);

  // Sync selected project ID to context for sidebar
  useEffect(() => {
    setContextProjectId(selectedProjectId || null);
  }, [selectedProjectId, setContextProjectId]);

  // Sync selected version ID to context for sidebar
  useEffect(() => {
    setContextVersionId(selectedVersionId || null);
  }, [selectedVersionId, setContextVersionId]);

  // Load versions when project is selected
  useEffect(() => {
    if (selectedProjectId) {
      loadVersions(selectedProjectId);
    } else {
      setVersions([]);
      setSelectedVersionId('');
      setIsReadOnly(false); // Reset read-only flag when no project is selected
    }
  }, [selectedProjectId]);

  // Load classes and render them on canvas when version changes or canvas refresh is triggered
  useEffect(() => {
    const loadClasses = async () => {
      if (!selectedVersionId) {
        setNodes([]);
        setEdges([]);
        return;
      }

      try {
        const result = await getClassesForVersion(selectedVersionId);
        const classesData = JSON.parse(result);

        // Load properties for each class
        const classesWithProperties = await Promise.all(
          classesData.map(async (cls: any) => {
            const propsResult = await getPropertiesForClass(cls.id);
            const properties = JSON.parse(propsResult);
            return { ...cls, properties };
          })
        );

        // Convert classes to React Flow nodes
        const newNodes = await classesToNodes(classesWithProperties);

        // Create edges for both property $ref and composition relationships
        const newEdges = createAllEdges(classesWithProperties);

        // Apply auto-layout
        const layoutedNodes = getLayoutedElements(newNodes, newEdges, {
          direction: layoutDirection
        });

        setNodes(layoutedNodes);
        setEdges(newEdges);

        // Generate OpenAPI specification
        const currentProject = projects.find(p => p.id === selectedProjectId);
        const currentVersion = versions.find(v => v.id === selectedVersionId);
        const spec = generateOpenApiSpec(classesWithProperties, {
          projectName: currentProject?.name,
          version: currentVersion?.version_id
        });
        setOpenApiSpec(spec);

        // Fit view after a short delay to ensure nodes are rendered
        setTimeout(() => {
          fitView({ padding: 0.2, duration: 400 });
        }, 50);

        console.log('Loaded classes for version:', selectedVersionId, 'Classes:', classesData.length);
      } catch (error) {
        console.error('Failed to load classes:', error);
        setNodes([]);
        setEdges([]);
      }
    };

    loadClasses();
  }, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, setNodes, setEdges, fitView, handlePropertyDrop, handlePropertyEdit, handlePropertyDelete, handleClassEdit, generateOpenApiSpec, projects, versions, isReadOnly]);

  const loadProjects = async () => {
    if (!currentTenantId) return;

    setIsLoadingProjects(true);
    try {
      const result = await getProjectsForTenant(currentTenantId);
      const projectsData = JSON.parse(result);
      setProjects(projectsData);
    } catch (error) {
      console.error('Failed to load projects:', error);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const loadVersions = async (projectId: string) => {
    setIsLoadingVersions(true);
    try {
      const result = await getVersionsForProject(projectId);
      const versionsData = JSON.parse(result);
      setVersions(versionsData);

      // Auto-select the first version if available
      if (versionsData.length > 0) {
        const firstVersion = versionsData[0];
        setSelectedVersionId(firstVersion.id);
        setIsReadOnly(firstVersion.published || false);
      }
    } catch (error) {
      console.error('Failed to load versions:', error);
    } finally {
      setIsLoadingVersions(false);
    }
  };

  const handleProjectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedProjectId(e.target.value);
    setSelectedVersionId(''); // Reset version when project changes
    setIsReadOnly(false); // Reset read-only flag when version is cleared
  };

  const handleVersionChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const versionId = e.target.value;
    setSelectedVersionId(versionId);

    // Update read-only status based on whether version is published
    const version = versions.find(v => v.id === versionId);
    setIsReadOnly(version?.published || false);
  };

  const onConnect = useCallback(
    async (params: Connection) => {
      // If sourceHandle is a property handle (prop-<class_property_id>) and target is a class node,
      // update the $ref of that class property to point to the target class
      try {
        if (params.sourceHandle && params.source && params.target) {
          const sourceHandle = String(params.sourceHandle);
          if (sourceHandle.startsWith('prop-')) {
            const classPropertyId = sourceHandle.replace('prop-', '');
            const targetClassId = String(params.target);
            const res = await updateClassPropertyRef(classPropertyId, targetClassId);
            const resp = JSON.parse(res);
            if (!resp.success) {
              alert(resp.error || 'Failed to update property reference');
            } else {
              await reloadClasses();
              triggerSidebarRefresh();
            }
            return;
          }
        }
        // Default behavior for other connections (e.g., composition edges if we enable manual linking)
        setEdges((eds) => addEdge(params, eds));
      } catch (e) {
        console.error('onConnect failed:', e);
      }
    },
    [setEdges, reloadClasses, triggerSidebarRefresh]
  );

  const onNodeClick = useCallback((event: React.MouseEvent, node: any) => {
    console.log('Clicked node:', node);
  }, []);

  const onEdgeClick = useCallback((event: React.MouseEvent, edge: Edge) => {
    console.log('Clicked edge:', edge);
  }, []);

  const selectedProject = projects.find(p => p.id === selectedProjectId);
  const selectedVersion = versions.find(v => v.id === selectedVersionId);

  // Show tenant selection prompt if no tenant is selected
  if (!currentTenantId) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-gray-50 dark:bg-gray-900">
        <div className="text-center max-w-md px-6">
          <svg
            className="mx-auto h-16 w-16 text-gray-400 dark:text-gray-600 mb-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
            />
          </svg>
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
            No Tenant Selected
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Please select a tenant to get started with the Studio. You'll need to choose a tenant before you can manage projects, versions, and schemas.
          </p>
          <button
            onClick={() => window.location.href = '/ade/dashboard/tenants'}
            className="inline-flex items-center px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            <svg
              className="mr-2 h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
            Go to Tenant Selection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header with Project and Version Selectors */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-2" style={{ position: 'relative', zIndex: 1000 }}>
        <div className="flex items-center gap-3">
          {/* Project Selector */}
          <div className="flex items-center gap-1.5" style={{ position: 'relative', zIndex: 1001 }}>
            <select
              value={selectedProjectId}
              onChange={handleProjectChange}
              disabled={isLoadingProjects || !currentTenantId}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px] pointer-events-auto"
            >
              <option value="">Select project...</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>

          {/* Version Selector */}
          <div className="flex items-center gap-1.5" style={{ position: 'relative', zIndex: 1001 }}>
            <select
              value={selectedVersionId}
              onChange={handleVersionChange}
              disabled={isLoadingVersions || !selectedProjectId || versions.length === 0}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px] pointer-events-auto"
            >
              <option value="">Select version...</option>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.published ? '🔒 ' : ''}{version.version_id} - {version.description}
                </option>
              ))}
            </select>
          </div>

          {/* View Switcher */}
          {selectedProjectId && selectedVersionId && (
            <div className="flex items-center border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
              <button
                onClick={() => setViewMode('canvas')}
                className={`px-3 py-1 text-xs font-medium transition-colors ${
                  viewMode === 'canvas'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                }`}
              >
                Canvas
              </button>
              <button
                onClick={() => setViewMode('code')}
                className={`px-3 py-1 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                  viewMode === 'code'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                }`}
              >
                Code
              </button>
              <button
                onClick={() => setViewMode('swagger')}
                className={`px-3 py-1 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                  viewMode === 'swagger'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                }`}
              >
                Swagger
              </button>
            </div>
          )}

          {/* Context Display */}
          {selectedProject && selectedVersion && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
              <span className="font-medium">{selectedProject.name}</span>
              <span>/</span>
              <span className="font-mono">{selectedVersion.version_id}</span>
            </div>
          )}
        </div>
      </div>

      {/* Canvas/Code Area */}
      <div className="flex-1 bg-white dark:bg-gray-900 overflow-hidden relative">
        {!selectedProjectId || !selectedVersionId ? (
          // Empty state when no project/version selected
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <svg
                className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                No Project Selected
              </h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Select a project and version to view the class diagram
              </p>
            </div>
          </div>
        ) : viewMode === 'canvas' ? (
          // React Flow Canvas View
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            fitView
            attributionPosition="bottom-left"
            className="dark:bg-gray-900"
            nodesDraggable={true}
            nodesConnectable={!isReadOnly}
            elementsSelectable={true}
            nodesFocusable={true}
            edgesFocusable={true}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={12}
              size={1}
              className="dark:bg-gray-900"
              color="currentColor"
              style={{
                color: 'rgb(156, 163, 175)',
                opacity: 0.5
              }}
            />
            <Controls />
            <MiniMap
              nodeStrokeColor={(node) => {
                if (node.type === 'input') return '#3b82f6';
                if (node.type === 'output') return '#ec4899';
                return '#6b7280';
              }}
              nodeColor={(node) => {
                if (node.type === 'input') return '#dbeafe';
                if (node.type === 'output') return '#fce7f3';
                return '#f3f4f6';
              }}
              className="dark:bg-gray-800 dark:border-gray-700"
              maskColor="rgb(0, 0, 0, 0.1)"
            />

            {/* Read Only Indicator */}
            {isReadOnly && (
              <Panel position="top-left" className="bg-yellow-100 dark:bg-yellow-900/40 text-yellow-800 dark:text-yellow-200 rounded-lg shadow-lg px-3 py-1.5 border border-yellow-300 dark:border-yellow-700">
                <div className="flex items-center gap-1.5">
                  <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                  </svg>
                  <span className="text-xs font-semibold">Read Only</span>
                </div>
              </Panel>
            )}

            {/* Dangling $ref warning */}
            {(() => {
              const warn = hasDanglingRefs(nodes.map(n => ({ id: n.id, name: (n.data as any)?.name, properties: (n.data as any)?.properties })));
              return warn ? (
                <Panel position="top-left" className="mt-8 bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200 rounded-lg shadow-lg px-3 py-1.5 border border-red-300 dark:border-red-700">
                  <div className="flex items-center gap-1.5">
                    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.72-1.36 3.485 0l6.518 11.6c.75 1.336-.213 3.001-1.742 3.001H3.48c-1.53 0-2.492-1.665-1.743-3.001l6.52-11.6zM11 13a1 1 0 10-2 0 1 1 0 002 0zm-1-2a1 1 0 01-1-1V8a1 1 0 112 0v2a1 1 0 01-1 1z" clipRule="evenodd"/></svg>
                    <span className="text-xs font-semibold">One or more properties reference missing classes. Click a property handle and connect it to a class to fix.</span>
                  </div>
                </Panel>
              ) : null;
            })()}

            {/* Layout Control Panel */}
            <Panel position="top-right" className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-2 border border-gray-200 dark:border-gray-700">
              <div className="flex flex-col gap-2">
                <div className="text-xs font-semibold text-gray-700 dark:text-gray-300 px-2 py-1">
                  Auto Layout
                </div>
                <button
                  onClick={() => onLayout('TB')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    layoutDirection === 'TB'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                  title="Top to Bottom"
                >
                  ↓ Vertical
                </button>
                <button
                  onClick={() => onLayout('LR')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    layoutDirection === 'LR'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                  title="Left to Right"
                >
                  → Horizontal
                </button>
                <button
                  onClick={() => onLayout('BT')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    layoutDirection === 'BT'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                  title="Bottom to Top"
                >
                  ↑ Vertical (Up)
                </button>
                <button
                  onClick={() => onLayout('RL')}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    layoutDirection === 'RL'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                  title="Right to Left"
                >
                  ← Horizontal (Rev)
                </button>
              </div>
            </Panel>
          </ReactFlow>
        ) : viewMode === 'code' ? (
          // Monaco Editor Code View - OpenAPI 3.1.0 Specification
          <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      OpenAPI 3.1.0 Specification
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      Complete schema definition for {selectedProject?.name} v{selectedVersion?.version_id}
                    </p>
                  </div>

                  {/* Format Toggle */}
                  <div className="flex items-center border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                    <button
                      onClick={() => setCodeFormat('json')}
                      className={`px-3 py-1 text-xs font-medium transition-colors ${
                        codeFormat === 'json'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                      }`}
                    >
                      JSON
                    </button>
                    <button
                      onClick={() => setCodeFormat('yaml')}
                      className={`px-3 py-1 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                        codeFormat === 'yaml'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                      }`}
                    >
                      YAML
                    </button>
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      const content = codeFormat === 'json'
                        ? openApiSpec
                        : yaml.dump(JSON.parse(openApiSpec), { lineWidth: -1, noRefs: true });
                      navigator.clipboard.writeText(content);
                      alert(`OpenAPI specification (${codeFormat.toUpperCase()}) copied to clipboard!`);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors"
                    title="Copy to clipboard"
                  >
                    <Copy size={14} />
                    Copy
                  </button>
                  <button
                    onClick={() => {
                      // Get content in selected format
                      const content = codeFormat === 'json'
                        ? openApiSpec
                        : yaml.dump(JSON.parse(openApiSpec), { lineWidth: -1, noRefs: true });
                      const mimeType = codeFormat === 'json' ? 'application/json' : 'text/yaml';
                      const extension = codeFormat === 'json' ? 'json' : 'yaml';

                      // Create a blob from the OpenAPI spec
                      const blob = new Blob([content], { type: mimeType });
                      const url = URL.createObjectURL(blob);

                      // Create a temporary download link
                      const link = document.createElement('a');
                      link.href = url;

                      // Generate filename from project and version
                      const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
                      const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
                      link.download = `${projectSlug}-${versionSlug}-openapi.${extension}`;

                      // Trigger download
                      document.body.appendChild(link);
                      link.click();

                      // Cleanup
                      document.body.removeChild(link);
                      URL.revokeObjectURL(url);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
                    title={`Download as ${codeFormat.toUpperCase()} file`}
                  >
                    <Download size={14} />
                    Export
                  </button>
                </div>
              </div>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                language={codeFormat}
                value={(() => {
                  if (!openApiSpec) {
                    const emptySpec = {
                      openapi: '3.1.0',
                      info: {
                        title: 'No classes defined',
                        version: '1.0.0'
                      },
                      components: {
                        schemas: {}
                      }
                    };
                    return codeFormat === 'json'
                      ? JSON.stringify(emptySpec, null, 2)
                      : yaml.dump(emptySpec, { lineWidth: -1, noRefs: true });
                  }

                  return codeFormat === 'json'
                    ? openApiSpec
                    : yaml.dump(JSON.parse(openApiSpec), { lineWidth: -1, noRefs: true });
                })()}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: true },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  lineNumbers: 'on',
                  renderWhitespace: 'selection',
                  automaticLayout: true,
                  wordWrap: 'on',
                  folding: true,
                  formatOnPaste: true,
                  formatOnType: true,
                  contextmenu: true,
                  selectOnLineNumbers: true,
                }}
              />
            </div>
          </div>
        ) : (
          // Swagger UI View - Interactive API Documentation
          <div className="h-full flex flex-col bg-white dark:bg-gray-900">
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    Swagger UI - Interactive API Documentation
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    Explore and test your API endpoints for {selectedProject?.name} v{selectedVersion?.version_id}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(openApiSpec);
                      alert('OpenAPI specification (JSON) copied to clipboard!');
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors"
                    title="Copy specification to clipboard"
                  >
                    <Copy size={14} />
                    Copy Spec
                  </button>
                  <button
                    onClick={() => {
                      const blob = new Blob([openApiSpec], { type: 'application/json' });
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement('a');
                      link.href = url;
                      const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
                      const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
                      link.download = `${projectSlug}-${versionSlug}-openapi.json`;
                      document.body.appendChild(link);
                      link.click();
                      document.body.removeChild(link);
                      URL.revokeObjectURL(url);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
                    title="Download specification"
                  >
                    <Download size={14} />
                    Export Spec
                  </button>
                </div>
              </div>
            </div>
            <div className="flex-1 overflow-auto">
              {openApiSpec ? (
                <SwaggerUI
                  spec={JSON.parse(openApiSpec)}
                  docExpansion="list"
                  defaultModelsExpandDepth={1}
                  defaultModelExpandDepth={3}
                  displayRequestDuration={true}
                  filter={true}
                  showExtensions={true}
                  showCommonExtensions={true}
                  tryItOutEnabled={true}
                />
              ) : (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <svg
                      className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      />
                    </svg>
                    <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                      No OpenAPI Specification Available
                    </h3>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      Add classes and properties to generate API documentation
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Class-Property Edit Dialog (moved to separate component) */}
      <ClassPropertyEditDialog
        open={editPropertyDialogOpen}
        onClose={() => setEditPropertyDialogOpen(false)}
        editingClassProperty={editingClassProperty}
        onSaved={reloadClasses}
      />

      {/* Reference Dialog */}
      <ReferenceDialog
        open={referenceDialogOpen}
        onClose={() => setReferenceDialogOpen(false)}
        classes={nodes.map(n => ({
          id: n.id,
          name: (n.data as any).name,
          description: (n.data as any).description
        }))}
        onSubmit={handleReferenceSubmit}
      />

      {/* Class Edit Dialog */}
      <ClassEditDialog
        open={classEditDialogOpen}
        onClose={() => setClassEditDialogOpen(false)}
        editingClassData={editingClassData}
        nodes={nodes}
        isReadOnly={isReadOnly}
      />
    </div>
  );
};

const Studio = () => {
  return (
    <ReactFlowProvider>
      <StudioContent />
    </ReactFlowProvider>
  );
};

export default Studio;

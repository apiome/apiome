'use client';

import { useCallback, useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { useStudio } from './StudioContext';
import { Copy, Download } from 'lucide-react';
import * as yaml from 'js-yaml';
import ClassEditDialog from '../../components/ade/studio/ClassEditDialog';
import ClassPropertyEditDialog from '../../components/ade/studio/ClassPropertyEditDialog';
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
import {
  getProjectsForTenant,
  getVersionsForProject,
  getClassesForVersion,
  getPropertiesForClass,
  addPropertyToClass,
  removePropertyFromClass,
  deleteClass
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

type ViewMode = 'canvas' | 'code';

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
  const handlePropertyDrop = useCallback(async (classId: string, propertyData: any) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    try {
      console.log('Property dropped on class:', classId, propertyData);

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
          enum: propertyData.enum,
          default: propertyData.default,
          required: propertyData.required
        }
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

  // Handle class edit (double-click on node)
  const handleClassEdit = useCallback(async (classData: any) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    console.log('Editing class:', classData);
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

        // Direct $ref
        if (propData.$ref) {
          refClassName = extractClassNameFromRef(propData.$ref);
        }
        // $ref in items (for array types)
        else if (propData.type === 'array' && propData.items?.$ref) {
          refClassName = extractClassNameFromRef(propData.items.$ref);
        }

        // Create edge if we found a reference to another class
        if (refClassName && classNameToId.has(refClassName)) {
          const targetClassId = classNameToId.get(refClassName)!;
          const edgeColor = propData.type === 'array' ? '#8b5cf6' : '#3b82f6';

          edges.push({
            id: `prop-${cls.id}-${prop.id}-${targetClassId}`,
            source: cls.id,
            sourceHandle: `prop-${prop.id}`,
            target: targetClassId,
            type: 'smoothstep',
            animated: false,
            label: prop.name,
            style: {
              stroke: edgeColor,
              strokeWidth: 2
            },
            markerEnd: {
              type: 'arrowclosed',
              color: edgeColor,
              width: 20,
              height: 20
            },
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
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
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
            nodesDraggable={!isReadOnly}
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
        ) : (
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
        )}
      </div>

      {/* Class-Property Edit Dialog (moved to separate component) */}
      <ClassPropertyEditDialog
        open={editPropertyDialogOpen}
        onClose={() => setEditPropertyDialogOpen(false)}
        editingClassProperty={editingClassProperty}
        onSaved={reloadClasses}
      />

      {/* Class Edit Dialog */}
      <ClassEditDialog
        open={classEditDialogOpen}
        onClose={() => setClassEditDialogOpen(false)}
        editingClassData={editingClassData}
        nodes={nodes}
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

'use client';

import { useCallback, useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { useStudio } from './StudioContext';
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
  updateClassProperty,
  removePropertyFromClass
} from '../../../../lib/db/helper';
import ClassNode from './ClassNode';
import { getLayoutedElements, type LayoutDirection } from './layoutUtils';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import Alert from '@mui/material/Alert';

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
}

type ViewMode = 'canvas' | 'code';

const StudioContent = () => {
  const { data: session } = useSession();
  const {
    setSelectedProjectId: setContextProjectId,
    setSelectedVersionId: setContextVersionId,
    canvasRefreshKey
  } = useStudio();
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [selectedVersionId, setSelectedVersionId] = useState<string>('');
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('canvas');

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>('TB');

  // Class-property edit dialog state
  const [editPropertyDialogOpen, setEditPropertyDialogOpen] = useState(false);

  // Class edit dialog state
  const [classEditDialogOpen, setClassEditDialogOpen] = useState(false);
  const [editingClassData, setEditingClassData] = useState<any>(null);
  const [editingClassProperty, setEditingClassProperty] = useState<any>(null);
  const [editPropName, setEditPropName] = useState('');
  const [editPropDescription, setEditPropDescription] = useState('');
  const [editPropRequired, setEditPropRequired] = useState(false);
  const [editPropDeprecated, setEditPropDeprecated] = useState(false);
  const [editPropReadOnly, setEditPropReadOnly] = useState(false);
  const [editPropWriteOnly, setEditPropWriteOnly] = useState(false);
  const [editPropExample, setEditPropExample] = useState('');
  const [editPropertyError, setEditPropertyError] = useState('');

  // Sample OpenAPI spec - will be replaced with actual data from project/version
  const [openApiSpec, setOpenApiSpec] = useState<string>('');

  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const { fitView } = useReactFlow();

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
  }, [selectedVersionId, layoutDirection, setNodes]);

  // Handle property deletion from class
  const handlePropertyDelete = useCallback(async (classId: string, classPropertyId: string) => {
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
  }, [selectedVersionId, layoutDirection, setNodes]);

  // Handle class edit (double-click on node)
  const handleClassEdit = useCallback(async (classData: any) => {
    console.log('Editing class:', classData);
    setEditingClassData(classData);
    setClassEditDialogOpen(true);
  }, []);

  // Handle property edit from class
  const handlePropertyEdit = useCallback(async (classId: string, classProperty: any) => {
    console.log('Editing class property:', classId, classProperty);

    // Load the full property data from the class_properties record
    setEditingClassProperty(classProperty);
    setEditPropName(classProperty.name || '');
    setEditPropDescription(classProperty.description || '');

    // Parse the data JSONB field which contains the full schema
    const propData = typeof classProperty.data === 'string'
      ? JSON.parse(classProperty.data)
      : classProperty.data;

    // Set OpenAPI 3.2.0 extension fields
    setEditPropRequired(propData.required || false);
    setEditPropDeprecated(propData.deprecated || false);
    setEditPropReadOnly(propData.readOnly || false);
    setEditPropWriteOnly(propData.writeOnly || false);
    setEditPropExample(propData.example ? JSON.stringify(propData.example) : '');

    setEditPropertyError('');
    setEditPropertyDialogOpen(true);
  }, []);

  // Handle saving edited class property
  const handleSaveEditedProperty = useCallback(async () => {
    if (!editPropName.trim()) {
      setEditPropertyError('Property name is required');
      return;
    }

    if (!editingClassProperty) {
      setEditPropertyError('No property selected for editing');
      return;
    }

    try {
      // Get the original property data and update it with new values
      const originalData = typeof editingClassProperty.data === 'string'
        ? JSON.parse(editingClassProperty.data)
        : editingClassProperty.data;

      // Build updated data with OpenAPI 3.2.0 extensions
      const updatedData = {
        ...originalData,
        required: editPropRequired,
        deprecated: editPropDeprecated,
        readOnly: editPropReadOnly,
        writeOnly: editPropWriteOnly,
      };

      // Add example if provided
      if (editPropExample.trim()) {
        try {
          updatedData.example = JSON.parse(editPropExample);
        } catch (e) {
          // If not valid JSON, store as string
          updatedData.example = editPropExample;
        }
      } else {
        delete updatedData.example;
      }

      const result = await updateClassProperty(
        editingClassProperty.id,
        editPropName.trim(),
        editPropDescription || null,
        updatedData
      );

      const response = JSON.parse(result);
      if (response.success) {
        setEditPropertyDialogOpen(false);

        // Reload classes to show updated properties
        if (selectedVersionId) {
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
        }
      } else {
        setEditPropertyError(response.error || 'Failed to update property');
      }
    } catch (error) {
      console.error('Error updating class property:', error);
      setEditPropertyError('An error occurred while updating the property');
    }
  }, [editingClassProperty, editPropName, editPropDescription, editPropRequired, editPropDeprecated, editPropReadOnly, editPropWriteOnly, editPropExample, selectedVersionId, layoutDirection, setNodes]);

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
        onClassEdit: handleClassEdit
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

      // allOf - Inheritance (solid line, blue)
      if (schema.allOf && Array.isArray(schema.allOf)) {
        schema.allOf.forEach((item: any, index: number) => {
          if (item.$ref) {
            const refClassName = extractClassNameFromRef(item.$ref);
            if (refClassName && classNameToId.has(refClassName)) {
              edges.push({
                id: `allOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: `comp-allOf-${index}`, // Use specific bottom handle
                target: classNameToId.get(refClassName)!,
                type: 'step',
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
                }
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
                sourceHandle: `comp-anyOf-${index}`, // Use specific bottom handle
                target: classNameToId.get(refClassName)!,
                type: 'step',
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
                }
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
                sourceHandle: `comp-oneOf-${index}`, // Use specific bottom handle
                target: classNameToId.get(refClassName)!,
                type: 'step',
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
  }, [selectedVersionId, canvasRefreshKey, layoutDirection, setNodes, setEdges, fitView, handlePropertyDrop, handlePropertyEdit, handlePropertyDelete, handleClassEdit]);

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
        setSelectedVersionId(versionsData[0].id);
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
  };

  const handleVersionChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedVersionId(e.target.value);
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

  return (
    <div className="flex flex-col h-full">
      {/* Header with Project and Version Selectors */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-2">
        <div className="flex items-center gap-3">
          {/* Project Selector */}
          <div className="flex items-center gap-1.5">
            <select
              value={selectedProjectId}
              onChange={handleProjectChange}
              disabled={isLoadingProjects || !currentTenantId}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px]"
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
          <div className="flex items-center gap-1.5">
            <select
              value={selectedVersionId}
              onChange={handleVersionChange}
              disabled={isLoadingVersions || !selectedProjectId || versions.length === 0}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px]"
            >
              <option value="">Select version...</option>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version_id} - {version.description}
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
      <div className="flex-1 bg-white dark:bg-gray-900">
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
            <Controls className="dark:bg-gray-800 dark:border-gray-700" />
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
          // Monaco Editor Code View
          <Editor
            height="100%"
            defaultLanguage="yaml"
            value={openApiSpec}
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
            }}
          />
        )}
      </div>

      {/* Class-Property Edit Dialog */}
      <Dialog
        open={editPropertyDialogOpen}
        onClose={() => setEditPropertyDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          Edit Property in Class
        </DialogTitle>
        <DialogContent>
          {editPropertyError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {editPropertyError}
            </Alert>
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
            OpenAPI 3.2.0 Extensions
          </Typography>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={editPropRequired}
                  onChange={(e) => setEditPropRequired(e.target.checked)}
                />
              }
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Required</span>
                  <Typography variant="caption" color="text.secondary">
                    - Must be present in the object
                  </Typography>
                </Box>
              }
            />

            <FormControlLabel
              control={
                <Checkbox
                  checked={editPropDeprecated}
                  onChange={(e) => setEditPropDeprecated(e.target.checked)}
                />
              }
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Deprecated</span>
                  <Typography variant="caption" color="text.secondary">
                    - Should be transitioned out of usage
                  </Typography>
                </Box>
              }
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
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Read Only</span>
                  <Typography variant="caption" color="text.secondary">
                    - Only in responses (OpenAPI)
                  </Typography>
                </Box>
              }
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
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Write Only</span>
                  <Typography variant="caption" color="text.secondary">
                    - Only in requests (OpenAPI)
                  </Typography>
                </Box>
              }
            />
          </Box>

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
          <Button onClick={() => setEditPropertyDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSaveEditedProperty} variant="contained">
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Class Edit Dialog */}
      <Dialog
        open={classEditDialogOpen}
        onClose={() => setClassEditDialogOpen(false)}
        maxWidth="md"
        fullWidth
        slotProps={{
          paper: {
            sx: {
              height: '80vh',
              maxHeight: '700px',
            }
          }
        }}
      >
        <DialogTitle>
          Edit Class: {editingClassData?.name}
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          {editingClassData && (() => {
            // Helper function to extract class name from $ref
            const extractClassNameFromRef = (ref: string): string | null => {
              if (ref.includes('/')) {
                const parts = ref.split('/');
                return parts[parts.length - 1] || null;
              }
              return ref;
            };

            // Helper function to find all referenced class names
            const findReferencedClasses = (obj: any, refs: Set<string>): void => {
              if (!obj || typeof obj !== 'object') return;

              if (obj.$ref && typeof obj.$ref === 'string') {
                const className = extractClassNameFromRef(obj.$ref);
                if (className) refs.add(className);
              }

              for (const key in obj) {
                if (obj.hasOwnProperty(key)) {
                  findReferencedClasses(obj[key], refs);
                }
              }
            };

            // Helper function to build schema for a class
            const buildClassSchema = (classData: any) => {
              const schema = typeof classData.schema === 'string'
                ? JSON.parse(classData.schema)
                : (classData.schema || {});

              const properties: any = {};
              const required: string[] = [];

              if (classData.properties && classData.properties.length > 0) {
                classData.properties.forEach((prop: any) => {
                  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
                  properties[prop.name] = propData;

                  if (propData.required) {
                    required.push(prop.name);
                  }
                });
              }

              const classSchema = {
                type: 'object',
                description: classData.description || undefined,
                ...schema,
                properties,
                required: required.length > 0 ? required : undefined
              };

              // Remove undefined values
              Object.keys(classSchema).forEach(key => {
                if (classSchema[key] === undefined) {
                  delete classSchema[key];
                }
              });

              return classSchema;
            };

            // Build OpenAPI 3.2.0 schema from class data
            const schema = typeof editingClassData.schema === 'string'
              ? JSON.parse(editingClassData.schema)
              : (editingClassData.schema || {});

            // Build properties object from class_properties data
            const properties: any = {};
            const required: string[] = [];
            const referencedClasses = new Set<string>();

            if (editingClassData.properties && editingClassData.properties.length > 0) {
              editingClassData.properties.forEach((prop: any) => {
                const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
                properties[prop.name] = propData;

                // Find all $ref references in this property
                findReferencedClasses(propData, referencedClasses);

                // Check if property is required
                if (propData.required) {
                  required.push(prop.name);
                }
              });
            }

            // Find references in composition keywords (allOf/anyOf/oneOf)
            findReferencedClasses(schema, referencedClasses);

            // Construct the main class schema
            const classSchema = buildClassSchema(editingClassData);

            // Get all classes from nodes to find referenced ones
            const allClasses = nodes.map(node => node.data).filter(data => data && data.name);

            // Build schemas for referenced classes
            const referencedSchemas: any = {};
            referencedClasses.forEach(className => {
              if (className !== editingClassData.name) {
                // Find the class data from nodes
                const referencedClassData = allClasses.find((cls: any) => cls.name === className);
                if (referencedClassData) {
                  referencedSchemas[className] = buildClassSchema(referencedClassData);
                } else {
                  // Fallback to placeholder if class not found
                  referencedSchemas[className] = {
                    type: 'object',
                    description: `Referenced schema: ${className} (not loaded)`,
                    properties: {}
                  };
                }
              }
            });

            // Build complete OpenAPI document with components.schemas
            const openApiDoc = {
              openapi: '3.1.0',
              info: {
                title: `${editingClassData.name} Schema`,
                version: '1.0.0',
                description: 'OpenAPI 3.1.0 schema definition'
              },
              components: {
                schemas: {
                  [editingClassData.name]: classSchema,
                  ...referencedSchemas
                }
              }
            };

            const schemaJson = JSON.stringify(openApiDoc, null, 2);

            return (
              <Editor
                height="100%"
                defaultLanguage="json"
                value={schemaJson}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  wordWrap: 'on',
                  lineNumbers: 'on',
                  renderWhitespace: 'none',
                  folding: true
                }}
              />
            );
          })()}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClassEditDialogOpen(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
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

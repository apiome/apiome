'use client';

import { useCallback, useState, useEffect, useRef } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { useStudio } from './StudioContext';
import { Copy, Download, Check, Eye, Code } from 'lucide-react';
import Switch from '@mui/material/Switch';
import YAML from 'yaml';
import ClassPropertyEditDialog from '../../components/ade/studio/ClassPropertyEditDialog';
import ReferenceDialog from '../../components/ade/studio/ReferenceDialog';
import MermaidPreview, { type MermaidPreviewRef } from '../../components/ade/studio/MermaidPreview';
import TagManager from '../../components/ade/studio/TagManager';
import ClassEditDialog from '../../components/ade/studio/ClassEditDialog';
import { generateOpenApiSpec } from '../../utils/openapi';
import { generateArazzoSpec } from '../../utils/arazzo';
import { generateJsonSchema } from '../../utils/jsonschema';
import { generatePythonDTOs } from '../../utils/python-dto';
import { generateTypeScriptDTOs } from '../../utils/typescript-dto';
import { generateSQL } from '../../utils/sql-generator';
import { generateGraphQL } from '../../utils/graphql-generator';
import { generateScala } from '../../utils/scala-generator';
import { useDialog } from '../../components/providers/DialogProvider';
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
  deleteClass,
  updateClassPropertyRef,
  getTenantsForUser,
  getTagsForProject,
  getTagsForClass
} from '../../../../lib/db/helper';
import ClassNode from '../../components/ade/studio/ClassNode';
import { getLayoutedElements, type LayoutDirection, applyAutoLayout, type LayoutAlgorithm } from './layoutUtils';
import { getLayoutAlgorithmName } from './autoLayoutAlgorithms';

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

type ViewMode = 'canvas' | 'code' | 'generate' | 'mermaid';

const StudioContent = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
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
  const [codeDisplayFormat, setCodeDisplayFormat] = useState<'openapi' | 'arazzo' | 'jsonschema'>('openapi');

  // Sample OpenAPI spec - will be replaced with actual data from project/version
  const [openApiSpec, setOpenApiSpec] = useState<string>('');
  const [arazzoSpec, setArazzoSpec] = useState<string>('');
  const [jsonSchemaSpec, setJsonSchemaSpec] = useState<string>('');
  const [mermaidCode, setMermaidCode] = useState<string>('');
  const [mermaidViewMode, setMermaidViewMode] = useState<'code' | 'preview'>('preview');
  const [mermaidSvgReady, setMermaidSvgReady] = useState(false);
  const mermaidPreviewRef = useRef<MermaidPreviewRef>(null);

  // Generate tab state
  const [generatedCode, setGeneratedCode] = useState<string>('');
  const [generatedPythonCode, setGeneratedPythonCode] = useState<string>('');
  const [generatedTypeScriptCode, setGeneratedTypeScriptCode] = useState<string>('');
  const [generatedSQLCode, setGeneratedSQLCode] = useState<string>('');
  const [generatedGraphQLCode, setGeneratedGraphQLCode] = useState<string>('');
  const [generatedScalaCode, setGeneratedScalaCode] = useState<string>('');
  const [generateLanguage, setGenerateLanguage] = useState<'python' | 'typescript' | 'sql' | 'graphql' | 'scala'>('python');
  const [sqlDialect, setSqlDialect] = useState<'postgresql' | 'mysql' | 'sqlserver' | 'oracle' | 'sqlite'>('postgresql');
  const [scalaCodecLibrary, setScalaCodecLibrary] = useState<'play-json' | 'circe' | 'none'>('play-json');

  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const [currentTenantName, setCurrentTenantName] = useState<string>('');

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>('TB');
  const [layoutAlgorithm, setLayoutAlgorithm] = useState<LayoutAlgorithm>('hierarchical-tb');
  const [autoLayoutEnabled, setAutoLayoutEnabled] = useState<boolean>(true);
  const [isAnimating, setIsAnimating] = useState<boolean>(false);
  const { fitView } = useReactFlow();

  // Class-property edit dialog state
  const [editPropertyDialogOpen, setEditPropertyDialogOpen] = useState(false);

  // Class edit dialog state
  const [editingClassProperty, setEditingClassProperty] = useState<any>(null);
  const [editingClassId, setEditingClassId] = useState<string | null>(null);
  const [classEditDialogOpen, setClassEditDialogOpen] = useState(false);
  const [editingClassData, setEditingClassData] = useState<any>(null);
  // Note: dialog-specific form state moved to ClassPropertyEditDialog component

  // Reference dialog state
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const [referenceTargetClassId, setReferenceTargetClassId] = useState<string>('');

  // Tag management state
  const [projectTags, setProjectTags] = useState<any[]>([]);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);

  // Global expanded properties state for expand/collapse all
  const [globalExpandedProperties, setGlobalExpandedProperties] = useState<Set<string>>(new Set());

  // Canvas loading state
  const [isLoadingCanvas, setIsLoadingCanvas] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [loadedClasses, setLoadedClasses] = useState<any[]>([]);

  // Copy button states
  const [codeCopied, setCodeCopied] = useState(false);
  const [mermaidCopied, setMermaidCopied] = useState(false);
  const [generateCopied, setGenerateCopied] = useState(false);

  // Create stable refs for callbacks to prevent unnecessary re-renders
  const handlePropertyDropRef = useRef<any>(null);
  const handlePropertyEditRef = useRef<any>(null);
  const handlePropertyDeleteRef = useRef<any>(null);
  const handleClassEditRef = useRef<any>(null);
  const handleClassDeleteRef = useRef<any>(null);
  const handleCreateReferenceRef = useRef<any>(null);
  const handleTogglePropertyExpansionRef = useRef<any>(null);

  // Handle toggling property expansion
  const handleTogglePropertyExpansion = useCallback((propertyId: string) => {
    setGlobalExpandedProperties((prev) => {
      const next = new Set(prev);
      if (next.has(propertyId)) {
        next.delete(propertyId);
      } else {
        next.add(propertyId);
      }
      // Immediately reflect changes into node data
      setNodes((nodes) => nodes.map((n) => ({
        ...n,
        data: { ...(n.data as any), expandedProperties: next },
      })));
      return next;
    });
  }, [setNodes]);

  // Keep ref updated
  handleTogglePropertyExpansionRef.current = handleTogglePropertyExpansion;

  // Reflect expansion/read-only state changes into node data without re-layout
  useEffect(() => {
    setNodes((prev) =>
      prev.map((node) => ({
        ...node,
        data: {
          ...(node.data as any),
          isReadOnly,
          expandedProperties: globalExpandedProperties,
          onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args),
        },
      }))
    );
  }, [globalExpandedProperties, isReadOnly, setNodes]);

  // Handle expand all properties
  const handleExpandAll = useCallback(() => {
    const allPropertyIds = new Set<string>();
    nodes.forEach((node) => {
      const properties = (node.data as any)?.properties || [];
      properties.forEach((prop: any) => {
        allPropertyIds.add(prop.id);
      });
    });
    setGlobalExpandedProperties(allPropertyIds);
    // Also reflect immediately into node data
    setNodes((prev) => prev.map((n) => ({ ...n, data: { ...(n.data as any), expandedProperties: allPropertyIds } })));
  }, [nodes, setNodes]);

  // Handle collapse all properties
  const handleCollapseAll = useCallback(() => {
    const empty = new Set<string>();
    setGlobalExpandedProperties(empty);
    // Also reflect immediately into node data
    setNodes((prev) => prev.map((n) => ({ ...n, data: { ...(n.data as any), expandedProperties: empty } })));
  }, [setNodes]);

  // Helper to reload classes for current selectedVersionId (used after edits)
  const reloadClasses = useCallback(async (applyLayout = false) => {
    if (!selectedVersionId) return;

    setIsLoadingCanvas(true);
    setLoadingMessage('Refreshing canvas...');

    try {
      const classesResult = await getClassesForVersion(selectedVersionId);
      const classesData = JSON.parse(classesResult);

      setLoadingMessage('Reloading properties...');

      const classesWithProperties = await Promise.all(
        classesData.map(async (cls: any) => {
          const propsResult = await getPropertiesForClass(cls.id);
          const properties = JSON.parse(propsResult);

          // Load tags for this class
          const tagsResult = await getTagsForClass(cls.id);
          const tags = JSON.parse(tagsResult);

          return { ...cls, properties, tags };
        })
      );

      setLoadingMessage('Updating nodes and edges...');

      let finalNodes: Node[];
      if (applyLayout && autoLayoutEnabled) {
        // Apply auto-layout for class add/delete
        const newNodes = await classesToNodes(classesWithProperties);
        const newEdges = createAllEdges(classesWithProperties);
        finalNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
        setEdges(newEdges);
      } else {
        // Preserve existing node positions when reloading (no auto-layout)
        const existingPositions = new Map(nodes.map(n => [n.id, n.position]));
        const newNodes = await classesToNodes(classesWithProperties);
        // Restore positions from existing nodes
        newNodes.forEach(node => {
          const existingPos = existingPositions.get(node.id);
          if (existingPos) {
            node.position = existingPos;
          }
        });
        finalNodes = newNodes;
        const newEdges = createAllEdges(classesWithProperties);
        setEdges(newEdges);
      }
      setNodes(finalNodes);

      // Store classes for SQL regeneration
      setLoadedClasses(classesWithProperties);

      setLoadingMessage('Regenerating OpenAPI specification...');

      // Regenerate OpenAPI spec
      const currentProject = projects.find(p => p.id === selectedProjectId);
      const currentVersion = versions.find(v => v.id === selectedVersionId);
      const spec = generateOpenApiSpec(classesWithProperties, {
        projectName: currentProject?.name,
        version: currentVersion?.version_id
      });
      setOpenApiSpec(spec);

      // Generate Arazzo spec
      const arazzoSpecContent = generateArazzoSpec(classesWithProperties, {
        projectName: currentProject?.name,
        version: currentVersion?.version_id
      });
      setArazzoSpec(arazzoSpecContent);

      // Generate JSON Schema spec
      const jsonSchemaContent = generateJsonSchema(classesWithProperties, {
        projectName: currentProject?.name,
        version: currentVersion?.version_id
      });
      setJsonSchemaSpec(jsonSchemaContent);

      // Generate DTOs for both languages
      const dtoOptions = {
        projectName: currentProject?.name,
        version: currentVersion?.version_id,
        description: `Data Type Objects for ${currentProject?.name || 'API'}`
      };
      const pythonCode = generatePythonDTOs(classesWithProperties, dtoOptions);
      const typeScriptCode = generateTypeScriptDTOs(classesWithProperties, dtoOptions);

      // Generate SQL DDL
      const sqlCode = generateSQL(classesWithProperties, sqlDialect, {
        includeComments: true,
        includeDropStatements: false,
        namingConvention: 'snake_case'
      });

      // Generate GraphQL Schema
      const graphqlCode = generateGraphQL(classesWithProperties, {
        projectName: currentProject?.name,
        version: currentVersion?.version_id,
        description: `GraphQL Schema for ${currentProject?.name || 'API'}`,
        includeQueries: true,
        includeMutations: true,
        includeInputTypes: true
      });

      // Cache all versions
      setGeneratedPythonCode(pythonCode);
      setGeneratedTypeScriptCode(typeScriptCode);
      setGeneratedSQLCode(sqlCode);
      setGeneratedGraphQLCode(graphqlCode);

      // Set generated code based on current language selection
      if (generateLanguage === 'typescript') {
        setGeneratedCode(typeScriptCode);
      } else if (generateLanguage === 'sql') {
        setGeneratedCode(sqlCode);
      } else if (generateLanguage === 'graphql') {
        setGeneratedCode(graphqlCode);
      } else {
        setGeneratedCode(pythonCode);
      }
    } catch (error) {
      console.error('Failed to reload classes:', error);
    } finally {
      setIsLoadingCanvas(false);
      setLoadingMessage('');
    }
  }, [selectedVersionId, layoutDirection, autoLayoutEnabled, setNodes, setEdges, projects, versions, nodes]);

  // Apply auto-layout to current nodes and edges with animation
  const onLayout = useCallback((direction: LayoutDirection) => {
    if (!autoLayoutEnabled) {
      // Just update the direction without applying layout
      setLayoutDirection(direction);
      return;
    }

    setIsLoadingCanvas(true);
    setLoadingMessage('Applying layout...');
    setIsAnimating(true); // Enable CSS transitions

    // First, add transition styles to all existing nodes
    const nodesWithTransition = nodes.map(node => ({
      ...node,
      style: {
        ...node.style,
        transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
      },
    }));
    setNodes(nodesWithTransition);

    // Use setTimeout to allow the transition styles to be applied
    setTimeout(() => {
      const layoutedNodes = getLayoutedElements(nodes, edges, { direction });

      // Apply new positions while keeping transition styles
      const animatedNodes = layoutedNodes.map(node => ({
        ...node,
        style: {
          ...node.style,
          transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
        },
      }));

      setNodes(animatedNodes);
      setLayoutDirection(direction);

      // Fit view after animation completes
      setTimeout(() => {
        fitView({ padding: 0.2, duration: 400 });
        setIsLoadingCanvas(false);
        setLoadingMessage('');

        // Remove transition styles using functional update
        setTimeout(() => {
          setNodes((currentNodes) =>
            currentNodes.map(node => {
              const { transition, ...restStyle } = node.style || {};
              return {
                ...node,
                style: Object.keys(restStyle).length > 0 ? restStyle : undefined,
              };
            })
          );
          setIsAnimating(false);
        }, 400);
      }, 650);
    }, 50);
  }, [nodes, edges, setNodes, fitView, autoLayoutEnabled]);

  // Apply layout algorithm with animation
  const onLayoutAlgorithm = useCallback((algorithm: LayoutAlgorithm) => {
    if (!autoLayoutEnabled) {
      setLayoutAlgorithm(algorithm);
      return;
    }

    setIsLoadingCanvas(true);
    setLoadingMessage(`Applying ${getLayoutAlgorithmName(algorithm)} layout...`);
    setIsAnimating(true); // Enable CSS transitions

    // First, add transition styles to all existing nodes
    const nodesWithTransition = nodes.map(node => ({
      ...node,
      style: {
        ...node.style,
        transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
      },
    }));
    setNodes(nodesWithTransition);

    // Use setTimeout to allow the transition styles to be applied
    setTimeout(() => {
      const layoutedNodes = applyAutoLayout(nodes, edges, { algorithm });

      // Apply new positions while keeping transition styles
      const animatedNodes = layoutedNodes.map(node => ({
        ...node,
        style: {
          ...node.style,
          transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
        },
      }));

      setNodes(animatedNodes);
      setLayoutAlgorithm(algorithm);

      // Update direction if it's a hierarchical layout
      if (algorithm.startsWith('hierarchical-')) {
        const dir = algorithm.split('-')[1].toUpperCase() as LayoutDirection;
        setLayoutDirection(dir);
      }

      // Fit view after animation completes (600ms animation + small delay)
      setTimeout(() => {
        fitView({ padding: 0.2, duration: 400 });
        setIsLoadingCanvas(false);
        setLoadingMessage('');

        // Remove transition styles to avoid interfering with manual dragging
        setTimeout(() => {
          setNodes((currentNodes) =>
            currentNodes.map(node => {
              const { transition, ...restStyle } = node.style || {};
              return {
                ...node,
                style: Object.keys(restStyle).length > 0 ? restStyle : undefined,
              };
            })
          );
          setIsAnimating(false);
        }, 400);
      }, 650);
    }, 50);
  }, [nodes, edges, setNodes, fitView, autoLayoutEnabled]);

// Handle property drop on class
  const handlePropertyDrop = useCallback(async (classId: string, propertyData: any, parentId?: string | null) => {
    if (isReadOnly) return;

    try {
      console.log('Property dropped on class:', classId, propertyData, 'parentId:', parentId);

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
          exclusiveMinimum: propertyData.exclusiveMinimum,
          exclusiveMaximum: propertyData.exclusiveMaximum,
          multipleOf: propertyData.multipleOf,
          minItems: propertyData.minItems,
          maxItems: propertyData.maxItems,
          uniqueItems: propertyData.uniqueItems,
          items: propertyData.items,
          enum: propertyData.enum,
          default: propertyData.default,
          required: propertyData.required,
          readOnly: propertyData.readOnly,
          writeOnly: propertyData.writeOnly,
          deprecated: propertyData.deprecated,
          example: propertyData.example,
          additionalProperties: propertyData.additionalProperties
        },
        parentId || null
      );

      const response = JSON.parse(result);
      if (response.success) {
        await reloadClasses(false); // Reuse existing reload function without layout
      } else {
        await alertDialog({
          message: response.error || 'Failed to add property to class',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding property to class:', error);
      await alertDialog({
        message: 'An error occurred while adding the property',
        variant: 'error',
      });
    }
  }, [isReadOnly, reloadClasses, alertDialog]);

  // Keep ref updated
  handlePropertyDropRef.current = handlePropertyDrop;

  // Handle property deletion from class
  const handlePropertyDelete = useCallback(async (classId: string, classPropertyId: string) => {
    if (isReadOnly) return;

    try {
      console.log('Removing property from class:', classId, classPropertyId);

      const result = await removePropertyFromClass(classPropertyId);
      const response = JSON.parse(result);

      if (response.success) {
        await reloadClasses(false); // Reuse existing reload function without layout
      } else {
        await alertDialog({
          message: response.error || 'Failed to remove property from class',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error removing property from class:', error);
      await alertDialog({
        message: 'An error occurred while removing the property',
        variant: 'error',
      });
    }
  }, [isReadOnly, reloadClasses, alertDialog]);

  // Keep ref updated
  handlePropertyDeleteRef.current = handlePropertyDelete;

  // Handle reference creation submission
  const handleReferenceSubmit = useCallback(async (referenceData: {
    name: string;
    description: string | null;
    isArray: boolean;
    targetClassId: string | null;
    targetClassIds?: string[];
    compositionType?: string;
    minItems?: number;
    maxItems?: number;
    uniqueItems?: boolean;
  }) => {
    if (!referenceTargetClassId) return;

    try {
      console.log('Creating reference:', referenceData);

      // Build the data object for the reference
      const data: any = {};

      // Handle composition types (allOf/anyOf/oneOf)
      if (referenceData.compositionType && referenceData.targetClassIds && referenceData.targetClassIds.length > 0) {
        const compositionRefs = referenceData.targetClassIds.map(classId => {
          const targetClass = nodes.find(n => n.id === classId);
          if (targetClass) {
            const targetClassName = (targetClass.data as any).name;
            return { $ref: `#/components/schemas/${targetClassName}` };
          }
          return null;
        }).filter(Boolean);

        if (referenceData.isArray) {
          data.type = 'array';
          if (referenceData.minItems) data.minItems = referenceData.minItems;
          if (referenceData.maxItems) data.maxItems = referenceData.maxItems;
          if (referenceData.uniqueItems) data.uniqueItems = referenceData.uniqueItems;
          data.items = {
            [referenceData.compositionType]: compositionRefs
          };
        } else {
          data[referenceData.compositionType] = compositionRefs;
        }
      }
      // Handle single reference
      else if (referenceData.isArray) {
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
          // Placeholder for unassigned reference - use special marker
          data.items = { $ref: '#/components/schemas/__unassigned__' };
        }
      } else {
        // Set direct $ref if target class is specified
        if (referenceData.targetClassId) {
          const targetClass = nodes.find(n => n.id === referenceData.targetClassId);
          if (targetClass) {
            const targetClassName = (targetClass.data as any).name;
            data.$ref = `#/components/schemas/${targetClassName}`;
          }
        } else {
          // Placeholder for unassigned reference - use special marker
          data.$ref = '#/components/schemas/__unassigned__';
        }
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
        await alertDialog({
          message: response.error || 'Failed to create reference',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error creating reference:', error);
      throw error;
    }
  }, [referenceTargetClassId, nodes, reloadClasses, triggerSidebarRefresh]);

  // Load project tags
  const loadProjectTags = useCallback(async (projectId: string) => {
    try {
      const result = await getTagsForProject(projectId);
      const tags = JSON.parse(result);
      setProjectTags(tags);
    } catch (error) {
      console.error('Failed to load project tags:', error);
      setProjectTags([]);
    }
  }, []);

  // Handle class edit (double-click on node)
  const handleClassEdit = useCallback(async (classData: any) => {
    console.log(isReadOnly ? 'Viewing class:' : 'Editing class:', classData);
    setEditingClassData(classData);
    setClassEditDialogOpen(true);
  }, [isReadOnly]);

  // Keep ref updated
  handleClassEditRef.current = handleClassEdit;

  // Handle property edit from class
  const handlePropertyEdit = useCallback(async (classId: string, classProperty: any) => {
    // Prevent edits in read-only mode
    if (isReadOnly) {
      return;
    }

    console.log('Editing class property:', classId, classProperty);

    // Load the full property data from the class_properties record
    setEditingClassProperty(classProperty);
    setEditingClassId(classId);
    setEditPropertyDialogOpen(true);
  }, [isReadOnly]);

  // Keep ref updated
  handlePropertyEditRef.current = handlePropertyEdit;

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

  // Keep ref updated
  handleCreateReferenceRef.current = handleCreateReference;

  // Handle class delete from canvas
  const handleClassDelete = useCallback(async (classId: string, className: string) => {
    // Prevent deletes in read-only mode
    if (isReadOnly) {
      return;
    }

    const confirmed = await confirmDialog({
      title: 'Delete Class',
      message: `Are you sure you want to delete "${className}"? This action cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) {
      return;
    }

    try {
      console.log('Deleting class:', classId, className);
      const result = await deleteClass(classId);
      const response = JSON.parse(result);

      if (response.success) {
        // Reload classes to update the canvas with auto-layout (class deleted)
        await reloadClasses(true);
        // Trigger sidebar refresh to update the class list
        triggerSidebarRefresh();
      } else {
        await alertDialog({
          message: response.error || 'Failed to delete class',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting class:', error);
      await alertDialog({
        message: 'An error occurred while deleting the class',
        variant: 'error',
      });
    }
  }, [reloadClasses, triggerSidebarRefresh, isReadOnly, confirmDialog, alertDialog]);

  // Keep ref updated
  handleClassDeleteRef.current = handleClassDelete;

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
        tags: cls.tags || [], // Pass tags for display
        // Use refs to avoid triggering re-renders when callbacks change
        onPropertyDrop: (...args: any[]) => handlePropertyDropRef.current?.(...args),
        onPropertyEdit: (...args: any[]) => handlePropertyEditRef.current?.(...args),
        onPropertyDelete: (...args: any[]) => handlePropertyDeleteRef.current?.(...args),
        onClassEdit: (...args: any[]) => handleClassEditRef.current?.(...args),
        onClassDelete: (...args: any[]) => handleClassDeleteRef.current?.(...args),
        onCreateReference: (...args: any[]) => handleCreateReferenceRef.current?.(...args),
        isReadOnly: isReadOnly,
        expandedProperties: globalExpandedProperties,
        onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args)
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
        const isSourceArray = propData.type === 'array';

        // Helper function to create composition edges
        const createCompositionEdges = (compositionType: 'allOf' | 'anyOf' | 'oneOf', refs: any[]) => {
          refs.forEach((item: any, index: number) => {
            if (item.$ref) {
              const refClassName = extractClassNameFromRef(item.$ref);
              if (refClassName && classNameToId.has(refClassName)) {
                const targetClassId = classNameToId.get(refClassName)!;

                // Determine edge styling based on composition type
                let edgeColor: string;
                let strokeDasharray: string;
                let label: string;

                if (compositionType === 'allOf') {
                  edgeColor = '#2563eb'; // Blue
                  strokeDasharray = '0';
                  label = 'allOf';
                } else if (compositionType === 'anyOf') {
                  edgeColor = '#ea580c'; // Orange
                  strokeDasharray = '5,5';
                  label = 'anyOf';
                } else { // oneOf
                  edgeColor = '#9333ea'; // Purple
                  strokeDasharray = '2,3';
                  label = 'oneOf';
                }

                edges.push({
                  id: `prop-${compositionType}-${cls.id}-${prop.id}-${targetClassId}-${index}`,
                  source: cls.id,
                  sourceHandle: `prop-${prop.id}`,
                  target: targetClassId,
                  type: 'smoothstep',
                  animated: false,
                  label: `${prop.name} (${label}:${refClassName}${isSourceArray ? '[]' : ''})`,
                  style: {
                    stroke: edgeColor,
                    strokeWidth: 3,
                    strokeDasharray
                  },
                  markerEnd: {
                    type: 'arrowclosed',
                    color: edgeColor,
                    width: 15,
                    height: 15
                  },
                  labelStyle: {
                    fill: edgeColor,
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
        };

        // Check for composition types at property level (direct)
        if (propData.allOf && Array.isArray(propData.allOf)) {
          createCompositionEdges('allOf', propData.allOf);
          return; // Skip normal ref handling
        }
        if (propData.anyOf && Array.isArray(propData.anyOf)) {
          createCompositionEdges('anyOf', propData.anyOf);
          return; // Skip normal ref handling
        }
        if (propData.oneOf && Array.isArray(propData.oneOf)) {
          createCompositionEdges('oneOf', propData.oneOf);
          return; // Skip normal ref handling
        }

        // Check for composition types in array items
        if (isSourceArray && propData.items) {
          if (propData.items.allOf && Array.isArray(propData.items.allOf)) {
            createCompositionEdges('allOf', propData.items.allOf);
            return;
          }
          if (propData.items.anyOf && Array.isArray(propData.items.anyOf)) {
            createCompositionEdges('anyOf', propData.items.anyOf);
            return;
          }
          if (propData.items.oneOf && Array.isArray(propData.items.oneOf)) {
            createCompositionEdges('oneOf', propData.items.oneOf);
            return;
          }
        }

        // Handle single $ref (existing logic)
        let refClassName: string | null = null;

        // Direct $ref (one-to-one or many-to-one)
        if (propData.$ref) {
          refClassName = extractClassNameFromRef(propData.$ref);
        }
        // $ref in items (one-to-many or many-to-many)
        else if (propData.type === 'array' && propData.items?.$ref) {
          refClassName = extractClassNameFromRef(propData.items.$ref);
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
                label: `allOf:${refClassName}`,
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
                label: `anyOf:${refClassName}`,
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
                label: `oneOf:${refClassName}`,
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

  // Helper function to generate Mermaid class diagram from classes
  const generateMermaidDiagram = (classes: any[]): string => {
    const lines: string[] = ['classDiagram'];
    const classNameToId = new Map(classes.map(cls => [cls.name, cls.id]));

    // Add class definitions
    classes.forEach((cls) => {
      const className = cls.name.replace(/[^a-zA-Z0-9_]/g, '_'); // Sanitize for Mermaid

      lines.push(`    class ${className} {`);

      // Add properties
      if (cls.properties && cls.properties.length > 0) {
        cls.properties.forEach((prop: any) => {
          const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
          let propType = propData.type || 'any';

          // Handle composition types (anyOf, oneOf, allOf) at property level
          if (propData.anyOf && Array.isArray(propData.anyOf)) {
            const types = propData.anyOf
              .map((item: any) => {
                if (item.$ref) return extractClassNameFromRef(item.$ref);
                if (item.type) return item.type;
                return null;
              })
              .filter(Boolean);
            propType = types.length > 0 ? types.join(' | ') : 'anyOf';
          } else if (propData.oneOf && Array.isArray(propData.oneOf)) {
            const types = propData.oneOf
              .map((item: any) => {
                if (item.$ref) return extractClassNameFromRef(item.$ref);
                if (item.type) return item.type;
                return null;
              })
              .filter(Boolean);
            propType = types.length > 0 ? types.join(' | ') : 'oneOf';
          } else if (propData.allOf && Array.isArray(propData.allOf)) {
            const types = propData.allOf
              .map((item: any) => {
                if (item.$ref) return extractClassNameFromRef(item.$ref);
                if (item.type) return item.type;
                return null;
              })
              .filter(Boolean);
            propType = types.length > 0 ? types.join(' & ') : 'allOf';
          }
          // Handle array types with composition in items
          else if (propData.type === 'array' && propData.items) {
            if (propData.items.anyOf && Array.isArray(propData.items.anyOf)) {
              const types = propData.items.anyOf
                .map((item: any) => {
                  if (item.$ref) return extractClassNameFromRef(item.$ref);
                  if (item.type) return item.type;
                  return null;
                })
                .filter(Boolean);
              propType = types.length > 0 ? `(${types.join(' | ')})[]` : 'anyOf[]';
            } else if (propData.items.oneOf && Array.isArray(propData.items.oneOf)) {
              const types = propData.items.oneOf
                .map((item: any) => {
                  if (item.$ref) return extractClassNameFromRef(item.$ref);
                  if (item.type) return item.type;
                  return null;
                })
                .filter(Boolean);
              propType = types.length > 0 ? `(${types.join(' | ')})[]` : 'oneOf[]';
            } else if (propData.items.allOf && Array.isArray(propData.items.allOf)) {
              const types = propData.items.allOf
                .map((item: any) => {
                  if (item.$ref) return extractClassNameFromRef(item.$ref);
                  if (item.type) return item.type;
                  return null;
                })
                .filter(Boolean);
              propType = types.length > 0 ? `(${types.join(' & ')})[]` : 'allOf[]';
            }
            // Handle simple array types
            else if (propData.items.$ref) {
              const refClass = extractClassNameFromRef(propData.items.$ref);
              propType = `${refClass}[]`;
            } else if (propData.items.type) {
              propType = `${propData.items.type}[]`;
            }
          }
          // Handle simple $ref types
          else if (propData.$ref) {
            propType = extractClassNameFromRef(propData.$ref) || 'Object';
          }

          lines.push(`        +${propType} ${prop.name}`);
        });
      } else {
        lines.push(`        // No properties`);
      }

      lines.push(`    }`);
    });

    // Add relationships
    classes.forEach((cls) => {
      const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : cls.schema;
      const sourceClassName = cls.name.replace(/[^a-zA-Z0-9_]/g, '_');

      // Property references (associations)
      if (cls.properties) {
        cls.properties.forEach((prop: any) => {
          const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
          const isSourceArray = propData.type === 'array';

          // Helper to add relationship for a single reference
          const addRelationship = (refClassName: string | null, relationLabel: string, compositionType?: 'anyOf' | 'oneOf' | 'allOf') => {
            if (refClassName && classNameToId.has(refClassName)) {
              const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');

              // For composition types, use dashed lines
              if (compositionType) {
                if (compositionType === 'anyOf') {
                  lines.push(`    ${sourceClassName} ..> ${targetClassName} : ${relationLabel}`);
                } else if (compositionType === 'oneOf') {
                  lines.push(`    ${sourceClassName} ..> ${targetClassName} : ${relationLabel}`);
                } else if (compositionType === 'allOf') {
                  lines.push(`    ${sourceClassName} ..> ${targetClassName} : ${relationLabel}`);
                }
              } else {
                // Regular association
                const targetClass = classes.find(c => c.id === classNameToId.get(refClassName));

                // Check for reverse reference
                let hasReverseRef = false;
                let isTargetArray = false;

                if (targetClass && targetClass.properties) {
                  targetClass.properties.forEach((targetProp: any) => {
                    const targetPropData = typeof targetProp.data === 'string' ? JSON.parse(targetProp.data) : targetProp.data;
                    const targetRefName = targetPropData.$ref
                      ? extractClassNameFromRef(targetPropData.$ref)
                      : (targetPropData.type === 'array' && targetPropData.items?.$ref
                          ? extractClassNameFromRef(targetPropData.items.$ref)
                          : null);

                    if (targetRefName === cls.name) {
                      hasReverseRef = true;
                      isTargetArray = targetPropData.type === 'array';
                    }
                  });
                }

                // Determine cardinality
                let relationship: string;
                if (isSourceArray && isTargetArray) {
                  relationship = `${sourceClassName} "*" -- "*" ${targetClassName} : ${relationLabel}`;
                } else if (isSourceArray && !isTargetArray) {
                  relationship = hasReverseRef
                    ? `${targetClassName} "1" -- "*" ${sourceClassName} : ${relationLabel}`
                    : `${sourceClassName} "*" -- "1" ${targetClassName} : ${relationLabel}`;
                } else if (!isSourceArray && isTargetArray) {
                  relationship = `${sourceClassName} "*" -- "1" ${targetClassName} : ${relationLabel}`;
                } else {
                  relationship = hasReverseRef
                    ? `${sourceClassName} "1" -- "1" ${targetClassName} : ${relationLabel}`
                    : `${sourceClassName} "1" --> ${targetClassName} : ${relationLabel}`;
                }

                lines.push(`    ${relationship}`);
              }
            }
          };

          // Handle composition types (anyOf, oneOf, allOf) at property level
          if (propData.anyOf && Array.isArray(propData.anyOf)) {
            propData.anyOf.forEach((item: any, index: number) => {
              if (item.$ref) {
                const refClassName = extractClassNameFromRef(item.$ref);
                addRelationship(refClassName, `${prop.name}[anyOf-${index}]`, 'anyOf');
              }
            });
          } else if (propData.oneOf && Array.isArray(propData.oneOf)) {
            propData.oneOf.forEach((item: any, index: number) => {
              if (item.$ref) {
                const refClassName = extractClassNameFromRef(item.$ref);
                addRelationship(refClassName, `${prop.name}[oneOf-${index}]`, 'oneOf');
              }
            });
          } else if (propData.allOf && Array.isArray(propData.allOf)) {
            propData.allOf.forEach((item: any, index: number) => {
              if (item.$ref) {
                const refClassName = extractClassNameFromRef(item.$ref);
                addRelationship(refClassName, `${prop.name}[allOf-${index}]`, 'allOf');
              }
            });
          }
          // Handle composition in array items
          else if (propData.type === 'array' && propData.items) {
            if (propData.items.anyOf && Array.isArray(propData.items.anyOf)) {
              propData.items.anyOf.forEach((item: any, index: number) => {
                if (item.$ref) {
                  const refClassName = extractClassNameFromRef(item.$ref);
                  addRelationship(refClassName, `${prop.name}[anyOf-${index}]`, 'anyOf');
                }
              });
            } else if (propData.items.oneOf && Array.isArray(propData.items.oneOf)) {
              propData.items.oneOf.forEach((item: any, index: number) => {
                if (item.$ref) {
                  const refClassName = extractClassNameFromRef(item.$ref);
                  addRelationship(refClassName, `${prop.name}[oneOf-${index}]`, 'oneOf');
                }
              });
            } else if (propData.items.allOf && Array.isArray(propData.items.allOf)) {
              propData.items.allOf.forEach((item: any, index: number) => {
                if (item.$ref) {
                  const refClassName = extractClassNameFromRef(item.$ref);
                  addRelationship(refClassName, `${prop.name}[allOf-${index}]`, 'allOf');
                }
              });
            }
            // Handle simple array $ref
            else if (propData.items.$ref) {
              const refClassName = extractClassNameFromRef(propData.items.$ref);
              addRelationship(refClassName, prop.name);
            }
          }
          // Handle simple $ref
          else if (propData.$ref) {
            const refClassName = extractClassNameFromRef(propData.$ref);
            addRelationship(refClassName, prop.name);
          }
        });
      }

      // Composition relationships (allOf, anyOf, oneOf)
      if (schema) {
        // allOf - Inheritance
        if (schema.allOf && Array.isArray(schema.allOf)) {
          schema.allOf.forEach((item: any) => {
            if (item.$ref) {
              const refClassName = extractClassNameFromRef(item.$ref);
              if (refClassName && classNameToId.has(refClassName)) {
                const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');
                lines.push(`    ${targetClassName} <|-- ${sourceClassName} : inherits`);
              }
            }
          });
        }

        // anyOf - Alternatives
        if (schema.anyOf && Array.isArray(schema.anyOf)) {
          schema.anyOf.forEach((item: any) => {
            if (item.$ref) {
              const refClassName = extractClassNameFromRef(item.$ref);
              if (refClassName && classNameToId.has(refClassName)) {
                const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');
                lines.push(`    ${targetClassName} <.. ${sourceClassName} : anyOf`);
              }
            }
          });
        }

        // oneOf - Exclusive alternatives
        if (schema.oneOf && Array.isArray(schema.oneOf)) {
          schema.oneOf.forEach((item: any) => {
            if (item.$ref) {
              const refClassName = extractClassNameFromRef(item.$ref);
              if (refClassName && classNameToId.has(refClassName)) {
                const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');
                lines.push(`    ${targetClassName} <.. ${sourceClassName} : oneOf`);
              }
            }
          });
        }
      }
    });

    return lines.join('\n');
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

  // Load current tenant name
  useEffect(() => {
    const loadTenantName = async () => {
      if (session && currentTenantId) {
        try {
          const userId = (session.user as any)?.user_id;
          const result = await getTenantsForUser(userId);
          const tenants = JSON.parse(result);
          const currentTenant = tenants.find((t: any) => t.id === currentTenantId);
          if (currentTenant) {
            setCurrentTenantName(currentTenant.name);
          }
        } catch (error) {
          console.error('Failed to load tenant name:', error);
        }
      }
    };
    loadTenantName();
  }, [session, currentTenantId]);

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

      setIsLoadingCanvas(true);
      setLoadingMessage('Loading classes from database...');

      try {
        const result = await getClassesForVersion(selectedVersionId);
        const classesData = JSON.parse(result);

        setLoadingMessage(`Loading properties for ${classesData.length} class${classesData.length !== 1 ? 'es' : ''}...`);

        // Load properties and tags for each class
        const classesWithProperties = await Promise.all(
          classesData.map(async (cls: any) => {
            const propsResult = await getPropertiesForClass(cls.id);
            const properties = JSON.parse(propsResult);

            // Load tags for this class
            const tagsResult = await getTagsForClass(cls.id);
            const tags = JSON.parse(tagsResult);

            return { ...cls, properties, tags };
          })
        );

        setLoadingMessage('Creating canvas nodes...');

        // Convert classes to React Flow nodes
        const newNodes = await classesToNodes(classesWithProperties);

        setLoadingMessage('Creating relationship edges...');

        // Create edges for both property $ref and composition relationships
        const newEdges = createAllEdges(classesWithProperties);

        setLoadingMessage('Applying auto-layout...');

        // Apply auto-layout if enabled
        let finalNodes: Node[];
        if (autoLayoutEnabled) {
          finalNodes = getLayoutedElements(newNodes, newEdges, {
            direction: layoutDirection
          });
        } else {
          finalNodes = newNodes;
        }

        setNodes(finalNodes);
        setEdges(newEdges);

        setLoadingMessage('Generating OpenAPI specification...');

        // Generate OpenAPI specification
        const currentProject = projects.find(p => p.id === selectedProjectId);
        const currentVersion = versions.find(v => v.id === selectedVersionId);
        const spec = generateOpenApiSpec(classesWithProperties, {
          projectName: currentProject?.name,
          version: currentVersion?.version_id
        });
        setOpenApiSpec(spec);

        // Generate Arazzo specification
        const arazzoSpecContent = generateArazzoSpec(classesWithProperties, {
          projectName: currentProject?.name,
          version: currentVersion?.version_id
        });
        setArazzoSpec(arazzoSpecContent);

        // Generate JSON Schema specification
        const jsonSchemaContent = generateJsonSchema(classesWithProperties, {
          projectName: currentProject?.name,
          version: currentVersion?.version_id
        });
        setJsonSchemaSpec(jsonSchemaContent);

        // Generate DTOs for both languages
        const dtoOptions = {
          projectName: currentProject?.name,
          version: currentVersion?.version_id,
          description: `Data Type Objects for ${currentProject?.name || 'API'}`
        };
        const pythonCode = generatePythonDTOs(classesWithProperties, dtoOptions);
        const typeScriptCode = generateTypeScriptDTOs(classesWithProperties, dtoOptions);

        // Cache both versions
        setGeneratedPythonCode(pythonCode);
        setGeneratedTypeScriptCode(typeScriptCode);

        // Set generated code based on current language selection
        setGeneratedCode(generateLanguage === 'typescript' ? typeScriptCode : pythonCode);

        setLoadingMessage('Generating Mermaid diagram...');

        // Generate Mermaid diagram
        const mermaid = generateMermaidDiagram(classesWithProperties);
        setMermaidCode(mermaid);

        setLoadingMessage('Fitting view to canvas...');

        // Fit view after a short delay to ensure nodes are rendered
        setTimeout(() => {
          fitView({ padding: 0.2, duration: 400 });
        }, 50);

        console.log('Loaded classes for version:', selectedVersionId, 'Classes:', classesData.length);
      } catch (error) {
        console.error('Failed to load classes:', error);
        setNodes([]);
        setEdges([]);
      } finally {
        setIsLoadingCanvas(false);
        setLoadingMessage('');
      }
    };

    loadClasses();
  }, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, autoLayoutEnabled, setNodes, setEdges, fitView, projects, versions]);

  // Regenerate OpenAPI spec, Python DTOs, and Mermaid when switching views
  useEffect(() => {
    const regenerateSpec = async () => {
      if ((viewMode === 'code' || viewMode === 'generate' || viewMode === 'mermaid') && selectedVersionId) {
        try {
          // Reload classes from database to get latest state
          const result = await getClassesForVersion(selectedVersionId);
          const classesData = JSON.parse(result);

          // Load properties and tags for each class
          const classesWithProperties = await Promise.all(
            classesData.map(async (cls: any) => {
              const propsResult = await getPropertiesForClass(cls.id);
              const properties = JSON.parse(propsResult);

              // Load tags for this class
              const tagsResult = await getTagsForClass(cls.id);
              const tags = JSON.parse(tagsResult);

              return { ...cls, properties, tags };
            })
          );

          // Get current project and version for metadata
          const currentProject = projects.find(p => p.id === selectedProjectId);
          const currentVersion = versions.find(v => v.id === selectedVersionId);

          if (viewMode === 'code') {
            // Generate fresh OpenAPI specification
            const spec = generateOpenApiSpec(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id
            });
            setOpenApiSpec(spec);

            // Generate fresh Arazzo specification
            const arazzoSpecContent = generateArazzoSpec(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id
            });
            setArazzoSpec(arazzoSpecContent);

            // Generate fresh JSON Schema specification
            const jsonSchemaContent = generateJsonSchema(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id
            });
            setJsonSchemaSpec(jsonSchemaContent);
            console.log('Regenerated OpenAPI, Arazzo, and JSON Schema specs for view mode:', viewMode);
          } else if (viewMode === 'generate') {
            // Generate fresh DTOs for all languages
            const dtoOptions = {
              projectName: currentProject?.name,
              version: currentVersion?.version_id,
              description: `Data Type Objects for ${currentProject?.name || 'API'}`
            };
            const pythonCode = generatePythonDTOs(classesWithProperties, dtoOptions);
            const typeScriptCode = generateTypeScriptDTOs(classesWithProperties, dtoOptions);
            const sqlCode = generateSQL(classesWithProperties, sqlDialect, {
              includeComments: true,
              includeDropStatements: false,
              namingConvention: 'snake_case'
            });
            const graphqlCode = generateGraphQL(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id,
              includeQueries: true,
              includeMutations: true,
              includeInputTypes: true
            });
            const scalaCode = generateScala(classesWithProperties, scalaCodecLibrary, {
              packageName: 'com.example.models',
              includeCompanionObjects: true
            });

            // Cache all versions
            setGeneratedPythonCode(pythonCode);
            setGeneratedTypeScriptCode(typeScriptCode);
            setGeneratedSQLCode(sqlCode);
            setGeneratedGraphQLCode(graphqlCode);
            setGeneratedScalaCode(scalaCode);

            // Set generated code based on current language selection
            if (generateLanguage === 'typescript') {
              setGeneratedCode(typeScriptCode);
            } else if (generateLanguage === 'sql') {
              setGeneratedCode(sqlCode);
            } else if (generateLanguage === 'graphql') {
              setGeneratedCode(graphqlCode);
            } else if (generateLanguage === 'scala') {
              setGeneratedCode(scalaCode);
            } else {
              setGeneratedCode(pythonCode);
            }
            console.log('Regenerated DTOs for view mode:', viewMode, 'language:', generateLanguage);
          } else if (viewMode === 'mermaid') {
            // Generate fresh Mermaid diagram
            const mermaid = generateMermaidDiagram(classesWithProperties);
            setMermaidCode(mermaid);
            console.log('Regenerated Mermaid diagram for view mode:', viewMode);
          }
        } catch (error) {
          console.error('Failed to regenerate content:', error);
        }
      }
    };

    regenerateSpec();
  }, [viewMode, selectedVersionId, selectedProjectId, projects, versions, generateLanguage]);

  // Update generated code when language changes (use cached versions)
  // Note: This effect only runs when switching between languages (python/typescript/sql)
  // It does NOT run when SQL dialect changes - that's handled by the dialect effect below
  const previousLanguageRef = useRef(generateLanguage);

  useEffect(() => {
    // Only switch code if language actually changed (not on initial mount or dialect changes)
    if (previousLanguageRef.current !== generateLanguage) {
      console.log('Language changed from', previousLanguageRef.current, 'to', generateLanguage);

      if (generateLanguage === 'typescript' && generatedTypeScriptCode) {
        setGeneratedCode(generatedTypeScriptCode);
      } else if (generateLanguage === 'sql' && generatedSQLCode) {
        setGeneratedCode(generatedSQLCode);
      } else if (generateLanguage === 'graphql' && generatedGraphQLCode) {
        setGeneratedCode(generatedGraphQLCode);
      } else if (generateLanguage === 'python' && generatedPythonCode) {
        setGeneratedCode(generatedPythonCode);
      }

      previousLanguageRef.current = generateLanguage;
    }
  }, [generateLanguage, generatedPythonCode, generatedTypeScriptCode, generatedSQLCode, generatedGraphQLCode]);

  // Regenerate SQL when dialect changes or when switching to SQL language
  useEffect(() => {
    const generateSQLCode = async () => {
      if (generateLanguage === 'sql' && selectedVersionId) {
        try {
          let classesToUse = loadedClasses;

          // If loadedClasses is empty, fetch classes directly
          if (classesToUse.length === 0) {
            console.log('[SQL Effect] Classes not loaded, fetching...');
            const classesResult = await getClassesForVersion(selectedVersionId);
            const classesData = JSON.parse(classesResult);

            classesToUse = await Promise.all(
              classesData.map(async (cls: any) => {
                const propsResult = await getPropertiesForClass(cls.id);
                const properties = JSON.parse(propsResult);
                return { ...cls, properties };
              })
            );
            console.log('[SQL Effect] Fetched', classesToUse.length, 'classes');
          }

          console.log('[SQL Effect] Generating with dialect:', sqlDialect, '| Classes:', classesToUse.length);
          const sqlCode = generateSQL(classesToUse, sqlDialect, {
            includeComments: true,
            includeDropStatements: false,
            namingConvention: 'snake_case'
          });
          console.log('[SQL Effect] Generated:', sqlCode.length, 'chars | Dialect:', sqlCode.substring(30, 60));
          setGeneratedSQLCode(sqlCode);
          setGeneratedCode(sqlCode);
        } catch (error) {
          console.error('[SQL Effect] Error:', error);
        }
      }
    };

    generateSQLCode();
  }, [sqlDialect, generateLanguage, loadedClasses, selectedVersionId]);

  // Regenerate Scala when codec library changes
  useEffect(() => {
    const generateScalaCode = async () => {
      if (generateLanguage === 'scala' && selectedVersionId) {
        try {
          let classesToUse = loadedClasses;

          // If loadedClasses is empty, fetch classes directly
          if (classesToUse.length === 0) {
            console.log('[Scala Effect] Classes not loaded, fetching...');
            const classesResult = await getClassesForVersion(selectedVersionId);
            const classesData = JSON.parse(classesResult);

            classesToUse = await Promise.all(
              classesData.map(async (cls: any) => {
                const propsResult = await getPropertiesForClass(cls.id);
                const properties = JSON.parse(propsResult);
                return { ...cls, properties };
              })
            );
            console.log('[Scala Effect] Fetched', classesToUse.length, 'classes');
          }

          console.log('[Scala Effect] Generating with codec:', scalaCodecLibrary, '| Classes:', classesToUse.length);
          const scalaCode = generateScala(classesToUse, scalaCodecLibrary, {
            packageName: 'com.example.models',
            includeCompanionObjects: true
          });
          console.log('[Scala Effect] Generated:', scalaCode.length, 'chars');
          setGeneratedScalaCode(scalaCode);
          setGeneratedCode(scalaCode);
        } catch (error) {
          console.error('[Scala Effect] Error:', error);
        }
      }
    };

    generateScalaCode();
  }, [scalaCodecLibrary, generateLanguage, loadedClasses, selectedVersionId]);

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
    const projectId = e.target.value;
    setSelectedProjectId(projectId);
    setSelectedVersionId(''); // Reset version when project changes
    setIsReadOnly(false); // Reset read-only flag when version is cleared
    setViewMode('canvas'); // Reset view to canvas when project changes

    // Load tags for the new project
    if (projectId) {
      loadProjectTags(projectId);
    } else {
      setProjectTags([]);
    }
  };

  const handleVersionChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const versionId = e.target.value;
    setSelectedVersionId(versionId);

    // Update read-only status based on whether version is published
    const version = versions.find(v => v.id === versionId);
    setIsReadOnly(version?.published || false);

    // Reset view to canvas when version changes
    setViewMode('canvas');
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
              await alertDialog({
                message: resp.error || 'Failed to update property reference',
                variant: 'error',
              });
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
      <style jsx>{`
        @keyframes slide {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(400%);
          }
        }
      `}</style>

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
            <>
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
                  onClick={() => setViewMode('generate')}
                  className={`px-3 py-1 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                    viewMode === 'generate'
                      ? 'bg-blue-600 text-white'
                      : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                  }`}
                >
                  Generate
                </button>
                <button
                  onClick={() => setViewMode('mermaid')}
                  className={`px-3 py-1 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                    viewMode === 'mermaid'
                      ? 'bg-blue-600 text-white'
                      : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                  }`}
                >
                  Mermaid
                </button>
              </div>

              {/* Manage Tags Button */}
              <button
                onClick={() => setTagManagerOpen(true)}
                className="px-3 py-1 text-xs font-medium rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors flex items-center gap-1.5"
                title="Manage project tags"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
                <span>Tags</span>
              </button>
            </>
          )}

          {/* Context Display - Tenant Name */}
          {currentTenantName && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
              <span className="font-medium">{currentTenantName}</span>
            </div>
          )}
        </div>
      </div>

      {/* Canvas/Code Area */}
      <div className="flex-1 bg-white dark:bg-gray-900 overflow-hidden relative">
        {!selectedProjectId || !selectedVersionId ? (
          // Empty state when no project/version selected
          <div className="h-full flex items-center justify-center">
            <div className="bg-gray-50 dark:bg-gray-800 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-16 md:p-20 text-center">
              <svg
                className="mx-auto h-20 w-20 text-gray-400 dark:text-gray-500 mb-5"
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
              <h3 className="text-2xl font-semibold text-gray-700 dark:text-gray-300 mb-3">
                No Project Selected
              </h3>
              <p className="text-gray-600 dark:text-gray-400">
                Select a project and version to view the class diagram
              </p>
            </div>
          </div>
        ) : viewMode === 'canvas' ? (
          // React Flow Canvas View
          <>
            {/* Loading Progress Bar */}
            {isLoadingCanvas && (
              <div className="absolute top-0 left-0 right-0 z-50">
                <div className="bg-blue-600 h-1 animate-pulse" style={{
                  animation: 'progress 1.5s ease-in-out infinite'
                }}>
                  <div className="bg-blue-400 h-full" style={{
                    width: '40%',
                    animation: 'slide 1.5s ease-in-out infinite'
                  }}></div>
                </div>
                <div className="bg-white dark:bg-gray-800 shadow-lg px-4 py-2 text-center border-b border-gray-200 dark:border-gray-700">
                  <div className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-4 w-4 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      {loadingMessage || 'Loading...'}
                    </span>
                  </div>
                </div>
              </div>
            )}

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
              className={`dark:bg-gray-900 ${isAnimating ? 'layout-animating' : ''}`}
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
                    <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 002 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                  </svg>
                  <span className="text-xs font-semibold">Read Only</span>
                </div>
              </Panel>
            )}

            {/* Expand/Collapse All Controls */}
            <Panel
              position="top-left"
              className={`bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 ${isReadOnly ? 'mt-12' : ''}`}
            >
              <div className="flex gap-1 p-1">
                <button
                  onClick={handleExpandAll}
                  className="px-2 py-1 text-xs font-medium rounded transition-colors bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-1"
                  title="Expand all properties"
                >
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                  <span>Expand All</span>
                </button>
                <button
                  onClick={handleCollapseAll}
                  className="px-2 py-1 text-xs font-medium rounded transition-colors bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-1"
                  title="Collapse all properties"
                >
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                  <span>Collapse All</span>
                </button>
              </div>
            </Panel>

            {/* Dangling $ref warning */}
            {(() => {
              const warn = hasDanglingRefs(nodes.map(n => ({ id: n.id, name: (n.data as any)?.name, properties: (n.data as any)?.properties })));
              return warn ? (
                <Panel position="top-left" className={`bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200 rounded-lg shadow-lg px-3 py-1.5 border border-red-300 dark:border-red-700 ${isReadOnly ? 'mt-[7.5rem]' : 'mt-[4.5rem]'}`}>
                  <div className="flex items-center gap-1.5">
                    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.72-1.36 3.485 0l6.518 11.6c.75 1.336-.213 3.001-1.742 3.001H3.48c-1.53 0-2.492-1.665-1.743-3.001l6.52-11.6zM11 13a1 1 0 10-2 0 1 1 0 002 0zm-1-2a1 1 0 01-1-1V8a1 1 0 112 0v2a1 1 0 01-1 1z" clipRule="evenodd"/></svg>
                    <span className="text-xs font-semibold">One or more properties reference missing classes. Click a property handle and connect it to a class to fix.</span>
                  </div>
                </Panel>
              ) : null;
            })()}

            {/* Layout Control Panel */}
            <Panel position="top-right" className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-3 border border-gray-200 dark:border-gray-700 min-w-[280px]">
              <div className="flex flex-col gap-3">
                {/* Auto Layout Toggle */}
                <div className="flex items-center justify-between px-1">
                  <div className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                    Auto Layout
                  </div>
                  <Switch
                    checked={autoLayoutEnabled}
                    onChange={(e) => setAutoLayoutEnabled(e.target.checked)}
                    size="small"
                    sx={{
                      '& .MuiSwitch-switchBase.Mui-checked': {
                        color: '#2563eb',
                      },
                      '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': {
                        backgroundColor: '#2563eb',
                      },
                    }}
                  />
                </div>

                {/* Algorithm Selector */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-medium text-gray-600 dark:text-gray-400 px-1">
                    Algorithm
                  </label>
                  <select
                    value={layoutAlgorithm}
                    onChange={(e) => onLayoutAlgorithm(e.target.value as LayoutAlgorithm)}
                    disabled={!autoLayoutEnabled}
                    className={`text-xs px-2 py-1.5 rounded border transition-colors ${
                      autoLayoutEnabled
                        ? 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 hover:border-blue-500 dark:hover:border-blue-500'
                        : 'bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
                    }`}
                  >
                    <option value="hierarchical-tb">📊 Hierarchical (Top-Down)</option>
                    <option value="hierarchical-lr">📊 Hierarchical (Left-Right)</option>
                    <option value="hierarchical-bt">📊 Hierarchical (Bottom-Top)</option>
                    <option value="hierarchical-rl">📊 Hierarchical (Right-Left)</option>
                    <option value="force-directed">🔄 Force-Directed</option>
                    <option value="circular">⭕ Circular</option>
                    <option value="grid">⊞ Grid</option>
                    <option value="layered">📚 Layered</option>
                  </select>
                </div>
              </div>
            </Panel>
          </ReactFlow>
          </>
        ) : viewMode === 'code' ? (
          // Monaco Editor Code View - OpenAPI 3.1.0 Specification
          <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {codeDisplayFormat === 'openapi'
                        ? 'OpenAPI 3.1.0 Specification'
                        : codeDisplayFormat === 'arazzo'
                        ? 'Arazzo Specification v1.0.1'
                        : 'JSON Schema (Draft 2020-12)'}
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      {codeDisplayFormat === 'openapi'
                        ? `Complete schema definition for ${selectedProject?.name} v${selectedVersion?.version_id}`
                        : codeDisplayFormat === 'arazzo'
                        ? `Workflow specification for ${selectedProject?.name} v${selectedVersion?.version_id}`
                        : `JSON Schema definition for ${selectedProject?.name} v${selectedVersion?.version_id}`}
                    </p>
                  </div>

                  {/* Display Format Selector */}
                  <div className="flex items-center gap-2">
                    <select
                      value={codeDisplayFormat}
                      onChange={(e) => setCodeDisplayFormat(e.target.value as 'openapi' | 'arazzo' | 'jsonschema')}
                      className="px-3 py-1.5 text-xs font-medium border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="openapi">OpenAPI Specification</option>
                      <option value="arazzo">Arazzo Specification</option>
                      <option value="jsonschema">JSON Schema</option>
                    </select>
                  </div>

                  {/* Format Toggle (JSON/YAML) */}
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
                  <>
                    <button
                      onClick={() => {
                        const specContent = codeDisplayFormat === 'openapi'
                          ? openApiSpec
                          : codeDisplayFormat === 'arazzo'
                          ? arazzoSpec
                          : jsonSchemaSpec;
                        const content = codeFormat === 'json'
                          ? specContent
                          : YAML.stringify(JSON.parse(specContent));
                        navigator.clipboard.writeText(content);
                        setCodeCopied(true);
                        setTimeout(() => setCodeCopied(false), 2000);
                      }}
                      disabled={codeCopied}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                        codeCopied
                          ? 'bg-gray-500 text-white cursor-not-allowed'
                          : 'bg-gray-600 hover:bg-gray-700 text-white'
                      }`}
                      title="Copy to clipboard"
                    >
                      {codeCopied ? <Check size={14} /> : <Copy size={14} />}
                      {codeCopied ? 'Copied' : 'Copy'}
                    </button>
                    <button
                      onClick={() => {
                        // Get content in selected format
                        const specContent = codeDisplayFormat === 'openapi'
                          ? openApiSpec
                          : codeDisplayFormat === 'arazzo'
                          ? arazzoSpec
                          : jsonSchemaSpec;
                        const content = codeFormat === 'json'
                          ? specContent
                          : YAML.stringify(JSON.parse(specContent));
                        const mimeType = codeFormat === 'json' ? 'application/json' : 'text/yaml';
                        const extension = codeFormat === 'json' ? 'json' : 'yaml';

                        // Create a blob from the spec
                        const blob = new Blob([content], { type: mimeType });
                        const url = URL.createObjectURL(blob);

                        // Create a temporary download link
                        const link = document.createElement('a');
                        link.href = url;

                        // Generate filename from project and version
                        const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
                        const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
                        const specType = codeDisplayFormat === 'openapi'
                          ? 'openapi'
                          : codeDisplayFormat === 'arazzo'
                          ? 'arazzo'
                          : 'jsonschema';
                        link.download = `${projectSlug}-${versionSlug}-${specType}.${extension}`;

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
                  </>
                </div>
              </div>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                language={codeFormat}
                value={(() => {
                  const specContent = codeDisplayFormat === 'openapi'
                    ? openApiSpec
                    : codeDisplayFormat === 'arazzo'
                    ? arazzoSpec
                    : jsonSchemaSpec;

                  if (!specContent) {
                    const emptySpec = codeDisplayFormat === 'openapi'
                      ? {
                          openapi: '3.1.0',
                          info: {
                            title: 'No classes defined',
                            version: '1.0.0'
                          },
                          components: {
                            schemas: {}
                          }
                        }
                      : codeDisplayFormat === 'arazzo'
                      ? {
                          arazzo: '1.0.1',
                          info: {
                            title: 'No workflows defined',
                            version: '1.0.0'
                          },
                          sourceDescriptions: [],
                          workflows: []
                        }
                      : {
                          $schema: 'https://json-schema.org/draft/2020-12/schema',
                          title: 'No schemas defined',
                          type: 'object',
                          $defs: {}
                        };
                    return codeFormat === 'json'
                      ? JSON.stringify(emptySpec, null, 2)
                      : YAML.stringify(emptySpec);
                  }

                  return codeFormat === 'json'
                    ? specContent
                    : YAML.stringify(JSON.parse(specContent));
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
        ) : viewMode === 'generate' ? (
          // Monaco Editor Generate View - DTO Generation
          <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {generateLanguage === 'sql'
                        ? `Generated SQL DDL - ${sqlDialect.toUpperCase()}`
                        : generateLanguage === 'graphql'
                        ? 'Generated GraphQL Schema'
                        : generateLanguage === 'scala'
                        ? `Generated Scala - ${scalaCodecLibrary === 'play-json' ? 'Play JSON' : scalaCodecLibrary === 'circe' ? 'Circe' : 'No Codec'}`
                        : `Generated DTOs - ${generateLanguage === 'python' ? 'Python' : 'TypeScript'}`
                      }
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      {generateLanguage === 'sql'
                        ? `Database schema for ${selectedProject?.name} v${selectedVersion?.version_id}`
                        : generateLanguage === 'graphql'
                        ? `GraphQL API schema for ${selectedProject?.name} v${selectedVersion?.version_id}`
                        : generateLanguage === 'scala'
                        ? `Scala case classes for ${selectedProject?.name} v${selectedVersion?.version_id}`
                        : `Data Type Objects for ${selectedProject?.name} v${selectedVersion?.version_id}`
                      }
                    </p>
                  </div>

                  {/* Language Selector */}
                  <div className="flex items-center gap-2">
                    <select
                      value={generateLanguage}
                      onChange={(e) => setGenerateLanguage(e.target.value as 'python' | 'typescript' | 'sql' | 'graphql' | 'scala')}
                      className="px-3 py-1.5 text-xs font-medium border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="python">Python</option>
                      <option value="typescript">TypeScript</option>
                      <option value="sql">SQL</option>
                      <option value="graphql">GraphQL</option>
                      <option value="scala">Scala</option>
                    </select>

                    {/* SQL Dialect Selector - only show when SQL is selected */}
                    {generateLanguage === 'sql' && (
                      <select
                        value={sqlDialect}
                        onChange={(e) => setSqlDialect(e.target.value as any)}
                        className="px-3 py-1.5 text-xs font-medium border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="postgresql">PostgreSQL</option>
                        <option value="mysql">MySQL</option>
                        <option value="sqlserver">SQL Server</option>
                        <option value="oracle">Oracle</option>
                        <option value="sqlite">SQLite</option>
                      </select>
                    )}

                    {/* Scala Codec Library Selector - only show when Scala is selected */}
                    {generateLanguage === 'scala' && (
                      <select
                        value={scalaCodecLibrary}
                        onChange={(e) => setScalaCodecLibrary(e.target.value as any)}
                        className="px-3 py-1.5 text-xs font-medium border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="play-json">Play JSON</option>
                        <option value="circe">Circe</option>
                        <option value="none">No Codec</option>
                      </select>
                    )}
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(generatedCode);
                      setGenerateCopied(true);
                      setTimeout(() => setGenerateCopied(false), 2000);
                    }}
                    disabled={generateCopied}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      generateCopied
                        ? 'bg-gray-500 text-white cursor-not-allowed'
                        : 'bg-gray-600 hover:bg-gray-700 text-white'
                    }`}
                    title="Copy to clipboard"
                  >
                    {generateCopied ? <Check size={14} /> : <Copy size={14} />}
                    {generateCopied ? 'Copied' : 'Copy'}
                  </button>
                  <button
                    onClick={() => {
                      let filename: string;

                      if (generateLanguage === 'python') {
                        filename = 'schema.py';
                      } else if (generateLanguage === 'typescript') {
                        filename = 'schema.ts';
                      } else if (generateLanguage === 'graphql') {
                        filename = 'schema.graphql';
                      } else if (generateLanguage === 'scala') {
                        filename = 'Models.scala';
                      } else {
                        filename = `schema_${sqlDialect}.sql`;
                      }

                      const mimeType = 'text/plain';

                      // Create a blob from the generated code
                      const blob = new Blob([generatedCode], { type: mimeType });
                      const url = URL.createObjectURL(blob);

                      // Create a temporary download link
                      const link = document.createElement('a');
                      link.href = url;
                      link.download = filename;

                      // Trigger download
                      document.body.appendChild(link);
                      link.click();

                      // Cleanup
                      document.body.removeChild(link);
                      URL.revokeObjectURL(url);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
                    title="Export to file"
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
                language={
                  generateLanguage === 'typescript' ? 'typescript'
                  : generateLanguage === 'sql' ? 'sql'
                  : generateLanguage === 'graphql' ? 'graphql'
                  : generateLanguage === 'scala' ? 'scala'
                  : 'python'
                }
                value={
                  generatedCode ||
                  (generateLanguage === 'typescript'
                    ? '// No classes defined\n// Add classes to the canvas to generate DTOs'
                    : generateLanguage === 'sql'
                    ? '-- No classes defined\n-- Add classes to the canvas to generate SQL DDL'
                    : generateLanguage === 'graphql'
                    ? '# No classes defined\n# Add classes to the canvas to generate GraphQL schema'
                    : generateLanguage === 'scala'
                    ? '// No classes defined\n// Add classes to the canvas to generate Scala case classes'
                    : '# No classes defined\n# Add classes to the canvas to generate DTOs')
                }
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
        ) : viewMode === 'mermaid' ? (
          // Mermaid Diagram View
          <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-900">
            <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    Mermaid Class Diagram
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    Diagram representation of {selectedProject?.name} v{selectedVersion?.version_id}
                  </p>
                </div>

                <div className="flex gap-2 items-center">
                  {/* View Mode Toggle */}
                  <div className="flex border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                    <button
                      onClick={() => setMermaidViewMode('preview')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
                        mermaidViewMode === 'preview'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                      title="Preview diagram"
                    >
                      <Eye size={14} />
                      Preview
                    </button>
                    <button
                      onClick={() => setMermaidViewMode('code')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors border-l border-gray-300 dark:border-gray-600 ${
                        mermaidViewMode === 'code'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                      title="View code"
                    >
                      <Code size={14} />
                      Code
                    </button>
                  </div>

                  {/* Mode-specific actions */}
                  {mermaidViewMode === 'preview' ? (
                    <>
                      <button
                        onClick={() => mermaidPreviewRef.current?.exportSVG()}
                        disabled={!mermaidSvgReady}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-purple-600 hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white rounded transition-colors"
                        title="Export as SVG"
                      >
                        <Download size={14} />
                        SVG
                      </button>
                      <button
                        onClick={() => mermaidPreviewRef.current?.exportPNG()}
                        disabled={!mermaidSvgReady}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white rounded transition-colors"
                        title="Export as PNG"
                      >
                        <Download size={14} />
                        PNG
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(mermaidCode);
                          setMermaidCopied(true);
                          setTimeout(() => setMermaidCopied(false), 2000);
                        }}
                        disabled={mermaidCopied}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                          mermaidCopied
                            ? 'bg-gray-500 text-white cursor-not-allowed'
                            : 'bg-gray-600 hover:bg-gray-700 text-white'
                        }`}
                        title="Copy code to clipboard"
                      >
                        {mermaidCopied ? <Check size={14} /> : <Copy size={14} />}
                        {mermaidCopied ? 'Copied' : 'Copy'}
                      </button>
                      <button
                        onClick={() => {
                          // Create a blob from the Mermaid code
                          const blob = new Blob([mermaidCode], { type: 'text/plain' });
                          const url = URL.createObjectURL(blob);

                          // Create a temporary download link
                          const link = document.createElement('a');
                          link.href = url;

                          // Generate filename from project and version
                          const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'diagram';
                          const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
                          link.download = `${projectSlug}-${versionSlug}-diagram.mmd`;

                          // Trigger download
                          document.body.appendChild(link);
                          link.click();

                          // Cleanup
                          document.body.removeChild(link);
                          URL.revokeObjectURL(url);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
                        title="Download as .mmd file"
                      >
                        <Download size={14} />
                        Export
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
            <div className="flex-1">
              {mermaidViewMode === 'preview' ? (
                <MermaidPreview
                  ref={mermaidPreviewRef}
                  code={mermaidCode}
                  projectSlug={selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'diagram'}
                  versionSlug={selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0'}
                  onSvgReady={setMermaidSvgReady}
                />
              ) : (
                <Editor
                  height="100%"
                  language="markdown"
                  value={mermaidCode || '# No classes defined'}
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
              )}
            </div>
          </div>
        ) : null}
      </div>

      {/* Class-Property Edit Dialog (moved to separate component) */}
      <ClassPropertyEditDialog
        open={editPropertyDialogOpen}
        onClose={() => setEditPropertyDialogOpen(false)}
        editingClassProperty={editingClassProperty}
        onSaved={reloadClasses}
        allClassProperties={
          editingClassId
            ? (nodes.find(n => n.id === editingClassId)?.data as any)?.properties || []
            : []
        }
        existingClassNames={nodes.map(n => (n.data as any).name).filter(Boolean)}
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
        onClose={() => {
          setClassEditDialogOpen(false);
          setEditingClassData(null);
        }}
        editingClassData={editingClassData}
        nodes={nodes}
        isReadOnly={isReadOnly}
        onSave={() => {
          reloadClasses();
          triggerSidebarRefresh();
        }}
        projectId={selectedProjectId}
        projectTags={projectTags}
      />

      {/* Tag Manager Dialog */}
      <TagManager
        open={tagManagerOpen}
        onClose={() => setTagManagerOpen(false)}
        projectId={selectedProjectId}
        tags={projectTags}
        onTagsChanged={() => {
          if (selectedProjectId) {
            loadProjectTags(selectedProjectId);
          }
        }}
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

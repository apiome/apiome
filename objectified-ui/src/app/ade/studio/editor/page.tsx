'use client';

import { useCallback, useState, useEffect, useRef } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { toPng, toSvg, toJpeg } from 'html-to-image';
import { jsPDF } from 'jspdf';
import { useStudio } from '../StudioContext';
import { Copy, Download, Check, Settings } from 'lucide-react';
import * as Switch from '@radix-ui/react-switch';
import * as Select from '@radix-ui/react-select';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import YAML from 'yaml';
import ClassPropertyEditDialog from '../../../components/ade/studio/ClassPropertyEditDialog';
import ReferenceDialog from '../../../components/ade/studio/ReferenceDialog';
import TagManager from '../../../components/ade/studio/TagManager';
import ClassEditDialog from '../../../components/ade/studio/ClassEditDialog';
import { generateOpenApiSpec } from '../../../utils/openapi';
import { generateArazzoSpec } from '../../../utils/arazzo';
import { generateJsonSchema } from '../../../utils/jsonschema';
import { useDialog } from '../../../components/providers/DialogProvider';
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
  getClassesWithPropertiesAndTags,
  addPropertyToClass,
  removePropertyFromClass,
  deleteClass,
  updateClassPropertyRef,
  getTagsForProject,
  createProperty,
  saveDefaultCanvasLayout,
  getDefaultCanvasLayout,
  getGroupsForVersion
} from '../../../../../lib/db/helper';
import ClassNode from '../../../components/ade/studio/ClassNode';
import GroupNode, { GROUP_COLORS } from '../../../components/ade/studio/GroupNode';
import { getLayoutedElements, type LayoutDirection, applyAutoLayout, type LayoutAlgorithm } from '../layoutUtils';
import { getLayoutAlgorithmName } from '../autoLayoutAlgorithms';

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

  // Custom dark mode detection
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const checkDarkMode = () => {
      const isDarkMode = document.documentElement.classList.contains('dark') ||
                         window.matchMedia('(prefers-color-scheme: dark)').matches;
      setIsDark(isDarkMode);
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', checkDarkMode);
    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener('change', checkDarkMode);
    };
  }, []);

  // Toggle theme function
  const toggleTheme = useCallback(() => {
    const html = document.documentElement;
    const isDarkMode = html.classList.contains('dark');

    if (isDarkMode) {
      html.classList.remove('dark');
      localStorage.setItem('theme', 'light');
      setIsDark(false);
    } else {
      html.classList.add('dark');
      localStorage.setItem('theme', 'dark');
      setIsDark(true);
    }
  }, []);

  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const {
    selectedProjectId: contextProjectId,
    selectedVersionId: contextVersionId,
    setSelectedProjectId: setContextProjectId,
    setSelectedVersionId: setContextVersionId,
    canvasRefreshKey,
    triggerSidebarRefresh,
    isReadOnly,
    setIsReadOnly,
    setZoomToClassFn,
    setCreateGroupFn,
    setClickToFocusEnabled: setContextClickToFocusEnabled,
    groups,
    setGroups,
    addGroup,
    updateGroup,
    deleteGroup: deleteGroupFromContext
  } = useStudio();

  // Toggle click-to-focus mode (defined after useStudio to access setContextClickToFocusEnabled)
  const toggleClickToFocus = useCallback(() => {
    setClickToFocusEnabled((prev) => {
      const newValue = !prev;
      localStorage.setItem('clickToFocusEnabled', JSON.stringify(newValue));
      setContextClickToFocusEnabled(newValue);
      return newValue;
    });
  }, [setContextClickToFocusEnabled]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);

  // Use context values directly for project/version selection
  const selectedProjectId = contextProjectId || '';
  const selectedVersionId = contextVersionId || '';
  const setSelectedProjectId = setContextProjectId;
  const setSelectedVersionId = setContextVersionId;

  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('canvas');
  const [codeFormat, setCodeFormat] = useState<'json' | 'yaml'>('json');
  const [codeDisplayFormat, setCodeDisplayFormat] = useState<'openapi' | 'arazzo' | 'jsonschema'>('openapi');

  // OpenAPI, Arazzo, and JSON Schema specs
  const [openApiSpec, setOpenApiSpec] = useState<string>('');
  const [arazzoSpec, setArazzoSpec] = useState<string>('');
  const [jsonSchemaSpec, setJsonSchemaSpec] = useState<string>('');


  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>('TB');
  const [layoutAlgorithm, setLayoutAlgorithm] = useState<LayoutAlgorithm>('hierarchical-tb');
  const [autoLayoutEnabled, setAutoLayoutEnabled] = useState<boolean>(false);
  const [isAnimating, setIsAnimating] = useState<boolean>(false);
  const { fitView, setCenter, getViewport, setViewport } = useReactFlow();

  // Zoom level state for level-of-detail rendering
  const [zoomLevel, setZoomLevel] = useState<number>(1);

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

  // Copy button states
  const [codeCopied, setCodeCopied] = useState(false);

  // Layout saved state
  const [layoutSaved, setLayoutSaved] = useState(false);

  // Track if initial layout has been applied for this version
  const initialLayoutAppliedRef = useRef<string | null>(null);

  // Export dropdown state
  const [exportDropdownOpen, setExportDropdownOpen] = useState(false);
  const [layoutDropdownOpen, setLayoutDropdownOpen] = useState(false);
  const exportDropdownRef = useRef<HTMLDivElement>(null);
  const layoutDropdownRef = useRef<HTMLDivElement>(null);

  // Click-to-focus mode state
  const [clickToFocusEnabled, setClickToFocusEnabled] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('clickToFocusEnabled');
      return saved ? JSON.parse(saved) : true; // Default to enabled
    }
    return true;
  });

  // Create stable refs for callbacks to prevent unnecessary re-renders
  const handlePropertyDropRef = useRef<any>(null);
  const handlePropertyEditRef = useRef<any>(null);
  const handlePropertyDeleteRef = useRef<any>(null);
  const handleClassEditRef = useRef<any>(null);
  const handleClassDeleteRef = useRef<any>(null);
  const handleCreateReferenceRef = useRef<any>(null);
  const handleTogglePropertyExpansionRef = useRef<any>(null);

  // Refs for group handlers - initialized here, values set later
  const handleGroupRenameRef = useRef<any>(null);
  const handleGroupDeleteRef = useRef<any>(null);
  const handleGroupColorChangeRef = useRef<any>(null);
  const handleGroupStyleChangeRef = useRef<any>(null);
  const handleGroupTagsChangeRef = useRef<any>(null);

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
          zoomLevel,
          onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args),
        },
      }))
    );
  }, [globalExpandedProperties, isReadOnly, zoomLevel, setNodes]);

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

  // Handle zoom to class when selected in sidebar
  const zoomToClass = useCallback((classId: string) => {
    const node = nodes.find(n => n.id === classId);
    if (!node) return;

    // Highlight the node by adding a temporary selected state
    setNodes((prev) => prev.map((n) => ({
      ...n,
      selected: n.id === classId,
    })));

    // Center the view on the node with smooth animation
    const x = node.position.x + (node.width || 200) / 2;
    const y = node.position.y + (node.height || 150) / 2;
    const currentZoom = getViewport().zoom;

    // Zoom to 1.5x if currently zoomed out, otherwise keep current zoom
    const targetZoom = currentZoom < 1 ? 1.5 : currentZoom;

    setCenter(x, y, { zoom: targetZoom, duration: 800 });
  }, [nodes, setNodes, setCenter, getViewport]);

  // Register zoomToClass function in context on mount
  useEffect(() => {
    setZoomToClassFn(() => zoomToClass);
    return () => setZoomToClassFn(null);
  }, [zoomToClass, setZoomToClassFn]);

  // Sync clickToFocusEnabled with context
  useEffect(() => {
    setContextClickToFocusEnabled(clickToFocusEnabled);
  }, [clickToFocusEnabled, setContextClickToFocusEnabled]);

  // Helper to reload classes for current selectedVersionId (used after edits)
  const reloadClasses = useCallback(async (applyLayout = false) => {
    if (!selectedVersionId) return;

    setIsLoadingCanvas(true);
    setLoadingMessage('Refreshing canvas...');

    try {
      // Bulk load all classes with properties and tags in 3 queries
      const result = await getClassesWithPropertiesAndTags(selectedVersionId);
      const classesWithProperties = JSON.parse(result);

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
    // Always apply the layout when a button is clicked
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

// Helper function to extract inline properties from a property schema
  const extractInlineProperties = (propData: any): { name: string; data: any; description?: string }[] => {
    const children: { name: string; data: any; description?: string }[] = [];

    // Handle inline object properties (type: 'object' with nested properties)
    if (propData.type === 'object' && propData.properties) {
      const nestedRequired = Array.isArray(propData.required) ? propData.required : [];
      for (const childName of Object.keys(propData.properties)) {
        const childSchema = propData.properties[childName];
        const childData = { ...childSchema };
        const description = childData.description;
        delete childData.description;
        if (nestedRequired.includes(childName)) {
          childData.required = true;
        }
        children.push({ name: childName, data: childData, description });
      }
    }

    // Handle arrays of objects with inline properties (type: 'array' with items.type: 'object')
    if (propData.type === 'array' && propData.items?.type === 'object' && propData.items.properties) {
      const nestedRequired = Array.isArray(propData.items.required) ? propData.items.required : [];
      for (const childName of Object.keys(propData.items.properties)) {
        const childSchema = propData.items.properties[childName];
        const childData = { ...childSchema };
        const description = childData.description;
        delete childData.description;
        if (nestedRequired.includes(childName)) {
          childData.required = true;
        }
        children.push({ name: childName, data: childData, description });
      }
    }

    return children;
  };

  // Helper function to get or create a library property for inline properties
  const getOrCreateLibraryProperty = async (
    projectId: string,
    name: string,
    description: string | null,
    data: any
  ): Promise<string | null> => {
    // Skip references - they don't need library properties
    const isReference = data.$ref || (data.type === 'array' && data.items?.$ref);
    if (isReference) {
      return null;
    }

    try {
      // Create the property in the library
      const result = await createProperty(projectId, name, description, data);
      const response = JSON.parse(result);
      if (response.success) {
        return response.property.id;
      } else {
        // Property might already exist with this name, which is fine
        console.warn(`Could not create library property "${name}": ${response.error}`);
        return null;
      }
    } catch (error) {
      console.warn(`Error creating library property "${name}":`, error);
      return null;
    }
  };

  // Helper function to recursively add a property and its inline children to a class
  const addPropertyWithChildren = async (
    classId: string,
    projectId: string,
    propertyId: string | null,
    name: string,
    description: string | null,
    data: any,
    parentId: string | null
  ): Promise<{ success: boolean; error?: string }> => {
    // Clone the data and remove inline properties (they'll be stored as children)
    const cleanedData = { ...data };
    if (cleanedData.type === 'object' && cleanedData.properties) {
      delete cleanedData.properties;
      delete cleanedData.required;
    }
    if (cleanedData.type === 'array' && cleanedData.items?.properties) {
      const cleanedItems = { ...cleanedData.items };
      delete cleanedItems.properties;
      delete cleanedItems.required;
      cleanedData.items = cleanedItems;
    }

    // Add the main property
    const result = await addPropertyToClass(
      classId,
      propertyId,
      name,
      description,
      cleanedData,
      parentId
    );

    const response = JSON.parse(result);
    if (!response.success) {
      return { success: false, error: response.error };
    }

    const newClassPropertyId = response.classProperty.id;

    // Extract and recursively add inline children
    const inlineChildren = extractInlineProperties(data);
    for (const child of inlineChildren) {
      // Check if the child property is a reference (no library property needed)
      const isReference = child.data.$ref || (child.data.type === 'array' && child.data.items?.$ref);

      let childPropertyId: string | null = null;
      if (!isReference) {
        // Create a library property for this inline property
        childPropertyId = await getOrCreateLibraryProperty(
          projectId,
          child.name,
          child.description || null,
          child.data
        );

        // Database constraint: property_id must be non-null unless it's a reference
        if (childPropertyId === null) {
          console.warn(`Skipping inline property "${child.name}" - could not create library entry`);
          continue;
        }
      }

      // Recursively add child properties
      const childResult = await addPropertyWithChildren(
        classId,
        projectId,
        childPropertyId,
        child.name,
        child.description || null,
        child.data,
        newClassPropertyId
      );
      if (!childResult.success) {
        console.warn(`Failed to add inline child property "${child.name}": ${childResult.error}`);
        // Continue with other children even if one fails
      }
    }

    return { success: true };
  };

// Handle property drop on class
  const handlePropertyDrop = useCallback(async (classId: string, propertyData: any, parentId?: string | null) => {
    if (isReadOnly) return;

    if (!selectedProjectId) {
      await alertDialog({
        message: 'No project selected. Please select a project first.',
        variant: 'error',
      });
      return;
    }

    try {
      console.log('Property dropped on class:', classId, propertyData, 'parentId:', parentId);

      const result = await addPropertyWithChildren(
        classId,
        selectedProjectId,
        propertyData.id,
        propertyData.name,
        propertyData.description || null,
        // Use spread operator to copy all fields from propertyData
        // This prevents fields from being forgotten when new ones are added
        { ...propertyData },
        parentId || null
      );

      if (result.success) {
        await reloadClasses(false); // Reuse existing reload function without layout
      } else {
        await alertDialog({
          message: result.error || 'Failed to add property to class',
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
  }, [isReadOnly, selectedProjectId, reloadClasses, alertDialog]);

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

  // ============================================================================
  // GROUP MANAGEMENT HANDLERS
  // ============================================================================

  // Generate unique group ID
  const generateGroupId = useCallback(() => {
    return `group-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }, []);

  // Handle group rename
  const handleGroupRename = useCallback(async (groupId: string, newName: string) => {
    if (isReadOnly) return;

    updateGroup(groupId, { name: newName });

    // Update the node data
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, name: newName }
        };
      }
      return node;
    }));

    // Auto-save the updated groups to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.map(node => ({
          id: node.id,
          type: node.type,
          position: node.position,
          dimensions: {
            width: node.measured?.width || node.width || node.style?.width,
            height: node.measured?.height || node.height || node.style?.height
          }
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        // Get updated groups with the new name
        const updatedGroups = groups.map(g =>
          g.id === groupId ? { ...g, name: newName } : g
        );

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group rename:', error);
      }
    }
  }, [isReadOnly, updateGroup, setNodes, selectedVersionId, currentUserId, getViewport, nodes, edges, groups]);

  // Handle group delete
  const handleGroupDelete = useCallback(async (groupId: string) => {
    if (isReadOnly) return;

    const group = groups.find(g => g.id === groupId);
    const confirmed = await confirmDialog({
      title: 'Delete Group',
      message: `Are you sure you want to delete the group "${group?.name || 'this group'}"? The classes inside will not be deleted.`,
      variant: 'warning',
      confirmLabel: 'Delete Group',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    // Remove from context
    deleteGroupFromContext(groupId);

    // Remove group node from canvas
    setNodes(prevNodes => prevNodes.filter(node => node.id !== groupId));

    // Auto-save to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.filter(n => n.id !== groupId && n.type !== 'groupNode').map(node => ({
          id: node.id,
          position: node.position,
          dimensions: node.style ? { width: node.style.width, height: node.style.height } : undefined
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        // Exclude the deleted group
        const updatedGroups = groups.filter(g => g.id !== groupId);

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group deletion:', error);
      }
    }
  }, [isReadOnly, groups, confirmDialog, deleteGroupFromContext, setNodes, selectedVersionId, currentUserId, getViewport, nodes, edges]);

  // Handle group color change
  const handleGroupColorChange = useCallback(async (groupId: string, newColor: string) => {
    if (isReadOnly) return;

    updateGroup(groupId, { color: newColor });

    // Update the node data
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, color: newColor }
        };
      }
      return node;
    }));

    // Auto-save the updated groups to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.map(node => ({
          id: node.id,
          type: node.type,
          position: node.position,
          dimensions: {
            width: node.measured?.width || node.width || node.style?.width,
            height: node.measured?.height || node.height || node.style?.height
          }
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        const updatedGroups = groups.map(g =>
          g.id === groupId ? { ...g, color: newColor } : g
        );

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group color change:', error);
      }
    }
  }, [isReadOnly, updateGroup, setNodes, selectedVersionId, currentUserId, getViewport, nodes, edges, groups]);

  // Handle group style change
  const handleGroupStyleChange = useCallback(async (groupId: string, styleOptions: any) => {
    if (isReadOnly) return;

    updateGroup(groupId, { styleOptions });

    // Update the node data
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, styleOptions }
        };
      }
      return node;
    }));

    // Auto-save the updated groups to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.map(node => ({
          id: node.id,
          type: node.type,
          position: node.position,
          dimensions: {
            width: node.measured?.width || node.width || node.style?.width,
            height: node.measured?.height || node.height || node.style?.height
          }
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        const updatedGroups = groups.map(g =>
          g.id === groupId ? { ...g, styleOptions } : g
        );

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group style change:', error);
      }
    }
  }, [isReadOnly, updateGroup, setNodes, selectedVersionId, currentUserId, getViewport, nodes, edges, groups]);

  // Handle group tags change
  const handleGroupTagsChange = useCallback(async (groupId: string, tags: any[]) => {
    if (isReadOnly) return;

    updateGroup(groupId, { tags });

    // Update the node data
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, tags }
        };
      }
      return node;
    }));

    // Auto-save the updated groups to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.map(node => ({
          id: node.id,
          type: node.type,
          position: node.position,
          dimensions: {
            width: node.measured?.width || node.width || node.style?.width,
            height: node.measured?.height || node.height || node.style?.height
          }
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        const updatedGroups = groups.map(g =>
          g.id === groupId ? { ...g, tags } : g
        );

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group tags change:', error);
      }
    }
  }, [isReadOnly, updateGroup, setNodes, selectedVersionId, currentUserId, getViewport, nodes, edges, groups]);

  // Assign current handlers to refs for use in effects
  handleGroupTagsChangeRef.current = handleGroupTagsChange;
  handleGroupRenameRef.current = handleGroupRename;
  handleGroupDeleteRef.current = handleGroupDelete;
  handleGroupColorChangeRef.current = handleGroupColorChange;
  handleGroupStyleChangeRef.current = handleGroupStyleChange;

  // State for drag-over highlighting
  const [dragOverGroupId, setDragOverGroupId] = useState<string | null>(null);
  const dragOverGroupIdRef = useRef<string | null>(null);

  // Update group highlight state when dragging nodes over groups
  useEffect(() => {
    // Only update if the dragOverGroupId actually changed
    if (dragOverGroupIdRef.current === dragOverGroupId) return;
    dragOverGroupIdRef.current = dragOverGroupId;

    setNodes((prev) =>
      prev.map((node) => {
        if (node.type === 'groupNode') {
          return {
            ...node,
            data: {
              ...(node.data as any),
              isHighlighted: node.id === dragOverGroupId,
            },
          };
        }
        return node;
      })
    );
  }, [dragOverGroupId, setNodes]);

  // Handle adding a node to a group via drag and drop
  const handleAddNodeToGroup = useCallback((groupId: string, nodeId: string, nodePosition: { x: number; y: number }) => {
    if (isReadOnly) return;

    const group = groups.find(g => g.id === groupId);
    if (!group) return;

    // Check if node is already in the group
    if (group.nodeIds.includes(nodeId)) return;

    // Add node to group's nodeIds
    const updatedNodeIds = [...group.nodeIds, nodeId];
    updateGroup(groupId, { nodeIds: updatedNodeIds });

    // Update the group node data with the new nodeIds
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, nodeIds: updatedNodeIds }
        };
      }
      return node;
    }));
  }, [isReadOnly, groups, updateGroup, setNodes]);

  // Handle removing a node from a group - returns true if confirmed, false if cancelled
  const handleRemoveNodeFromGroup = useCallback(async (groupId: string, nodeId: string): Promise<boolean> => {
    if (isReadOnly) return false;

    const group = groups.find(g => g.id === groupId);
    if (!group) return false;

    // Confirm with user
    const confirmed = await confirmDialog({
      title: 'Remove from Group',
      message: `Remove this class from "${group.name}"?`,
      variant: 'warning',
      confirmLabel: 'Remove',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return false;

    // Remove node from group's nodeIds
    const updatedNodeIds = group.nodeIds.filter(id => id !== nodeId);
    updateGroup(groupId, { nodeIds: updatedNodeIds });

    // Update the group node data
    setNodes(prevNodes => prevNodes.map(node => {
      if (node.id === groupId && node.type === 'groupNode') {
        return {
          ...node,
          data: { ...node.data, nodeIds: updatedNodeIds }
        };
      }
      return node;
    }));

    return true;
  }, [isReadOnly, groups, confirmDialog, updateGroup, setNodes]);

  // Find which group a position is inside of
  const findGroupAtPosition = useCallback((x: number, y: number, excludeGroupId?: string): string | null => {
    const groupNodes = nodes.filter(n => n.type === 'groupNode' && n.id !== excludeGroupId);

    for (const groupNode of groupNodes) {
      const groupX = groupNode.position.x;
      const groupY = groupNode.position.y;
      // Use measured dimensions first (updated after resize), then style, then default
      const groupWidth = (groupNode.measured?.width as number) || (groupNode.style?.width as number) || 400;
      const groupHeight = (groupNode.measured?.height as number) || (groupNode.style?.height as number) || 300;

      if (x >= groupX && x <= groupX + groupWidth && y >= groupY && y <= groupY + groupHeight) {
        return groupNode.id;
      }
    }
    return null;
  }, [nodes]);

  // Find which group a node currently belongs to
  const findNodeGroup = useCallback((nodeId: string): string | null => {
    for (const group of groups) {
      if (group.nodeIds.includes(nodeId)) {
        return group.id;
      }
    }
    return null;
  }, [groups]);

  // Handle node drag - check if over a group for visual feedback
  const handleNodeDrag = useCallback((event: React.MouseEvent, node: Node) => {
    if (isReadOnly || node.type === 'groupNode') {
      setDragOverGroupId(null);
      return;
    }

    // Get node center
    const nodeWidth = (node.measured?.width as number) || (node.width as number) || 260;
    const nodeHeight = (node.measured?.height as number) || (node.height as number) || 200;
    const nodeCenterX = node.position.x + nodeWidth / 2;
    const nodeCenterY = node.position.y + nodeHeight / 2;

    // Find if over any group
    const overGroupId = findGroupAtPosition(nodeCenterX, nodeCenterY);
    setDragOverGroupId(overGroupId);
  }, [isReadOnly, findGroupAtPosition]);

  // Check if a node is completely outside a group's bounds
  const isNodeCompletelyOutsideGroup = useCallback((node: Node, groupId: string): boolean => {
    const groupNode = nodes.find(n => n.id === groupId && n.type === 'groupNode');
    if (!groupNode) return true;

    const nodeWidth = (node.measured?.width as number) || (node.width as number) || 260;
    const nodeHeight = (node.measured?.height as number) || (node.height as number) || 200;
    const groupX = groupNode.position.x;
    const groupY = groupNode.position.y;
    // Use measured dimensions first (updated after resize), then style, then default
    const groupWidth = (groupNode.measured?.width as number) || (groupNode.style?.width as number) || 400;
    const groupHeight = (groupNode.measured?.height as number) || (groupNode.style?.height as number) || 300;

    // Node bounds
    const nodeLeft = node.position.x;
    const nodeRight = node.position.x + nodeWidth;
    const nodeTop = node.position.y;
    const nodeBottom = node.position.y + nodeHeight;

    // Group bounds
    const groupLeft = groupX;
    const groupRight = groupX + groupWidth;
    const groupTop = groupY;
    const groupBottom = groupY + groupHeight;

    // Check if completely outside (no overlap at all)
    return nodeRight < groupLeft || nodeLeft > groupRight || nodeBottom < groupTop || nodeTop > groupBottom;
  }, [nodes]);

  // Handle node drag stop - add to group or remove from group
  const handleNodeDragStop = useCallback(async (event: React.MouseEvent, node: Node) => {
    setDragOverGroupId(null);

    if (isReadOnly || node.type === 'groupNode') return;

    // Get node dimensions and center
    const nodeWidth = (node.measured?.width as number) || (node.width as number) || 260;
    const nodeHeight = (node.measured?.height as number) || (node.height as number) || 200;
    const nodeCenterX = node.position.x + nodeWidth / 2;
    const nodeCenterY = node.position.y + nodeHeight / 2;

    // Find current group and target group (based on center position)
    const currentGroupId = findNodeGroup(node.id);
    const targetGroupId = findGroupAtPosition(nodeCenterX, nodeCenterY);

    // Case 1: Node dropped into a new group (not currently in any group)
    if (!currentGroupId && targetGroupId) {
      handleAddNodeToGroup(targetGroupId, node.id, node.position);
    }
    // Case 2: Node moved from one group to another different group
    else if (currentGroupId && targetGroupId && currentGroupId !== targetGroupId) {
      // Check if completely outside the current group
      if (isNodeCompletelyOutsideGroup(node, currentGroupId)) {
        const group = groups.find(g => g.id === currentGroupId);
        const confirmed = await confirmDialog({
          title: 'Move to Different Group',
          message: `Move this class from "${group?.name}" to a different group?`,
          variant: 'warning',
          confirmLabel: 'Move',
          cancelLabel: 'Cancel',
        });

        if (confirmed) {
          // Remove from old group
          const oldGroup = groups.find(g => g.id === currentGroupId);
          if (oldGroup) {
            const updatedOldNodeIds = oldGroup.nodeIds.filter(id => id !== node.id);
            updateGroup(currentGroupId, { nodeIds: updatedOldNodeIds });
            setNodes(prevNodes => prevNodes.map(n => {
              if (n.id === currentGroupId && n.type === 'groupNode') {
                return { ...n, data: { ...n.data, nodeIds: updatedOldNodeIds } };
              }
              return n;
            }));
          }
          // Add to new group
          handleAddNodeToGroup(targetGroupId, node.id, node.position);
        } else {
          // Snap back to inside the group - move to center of current group
          const currentGroup = groups.find(g => g.id === currentGroupId);
          const groupNode = nodes.find(n => n.id === currentGroupId);
          if (currentGroup && groupNode) {
            const groupWidth = (groupNode.style?.width as number) || 400;
            const groupHeight = (groupNode.style?.height as number) || 300;
            setNodes(prevNodes => prevNodes.map(n => {
              if (n.id === node.id) {
                return {
                  ...n,
                  position: {
                    x: groupNode.position.x + (groupWidth - nodeWidth) / 2,
                    y: groupNode.position.y + (groupHeight - nodeHeight) / 2,
                  },
                };
              }
              return n;
            }));
          }
        }
      }
      // If not completely outside, node stays in current group at new position
    }
    // Case 3: Node dragged completely out of its group (no target group)
    else if (currentGroupId && !targetGroupId) {
      // Only ask to ungroup if completely outside the group bounds
      if (isNodeCompletelyOutsideGroup(node, currentGroupId)) {
        const removed = await handleRemoveNodeFromGroup(currentGroupId, node.id);

        // If cancelled, snap back to inside the group
        if (!removed) {
          const groupNode = nodes.find(n => n.id === currentGroupId);
          if (groupNode) {
            const groupWidth = (groupNode.measured?.width as number) || (groupNode.style?.width as number) || 400;
            const groupHeight = (groupNode.measured?.height as number) || (groupNode.style?.height as number) || 300;
            setNodes(prevNodes => prevNodes.map(n => {
              if (n.id === node.id) {
                return {
                  ...n,
                  position: {
                    x: groupNode.position.x + (groupWidth - nodeWidth) / 2,
                    y: groupNode.position.y + (groupHeight - nodeHeight) / 2,
                  },
                };
              }
              return n;
            }));
          }
        }
      }
      // If still partially inside, node stays in group at current position
    }
  }, [isReadOnly, findNodeGroup, findGroupAtPosition, handleAddNodeToGroup, handleRemoveNodeFromGroup, groups, confirmDialog, updateGroup, setNodes, nodes, isNodeCompletelyOutsideGroup]);

  // Create a new group (must be defined after handlers it references)
  const handleCreateGroup = useCallback(async () => {
    if (isReadOnly) return;

    // Get viewport center position for new empty group
    const viewport = getViewport();
    const canvasWidth = window.innerWidth;
    const canvasHeight = window.innerHeight;

    // Calculate center position in the flow coordinate system
    const centerX = (canvasWidth / 2 - viewport.x) / viewport.zoom;
    const centerY = (canvasHeight / 2 - viewport.y) / viewport.zoom;

    // Default group dimensions
    const defaultWidth = 400;
    const defaultHeight = 300;

    // Position group at center minus half its size
    const position = {
      x: centerX - defaultWidth / 2,
      y: centerY - defaultHeight / 2
    };

    // Create new empty group
    const groupId = generateGroupId();
    const newGroup = {
      id: groupId,
      name: `Group ${groups.length + 1}`,
      color: GROUP_COLORS[groups.length % GROUP_COLORS.length].name,
      nodeIds: [], // Empty group - no nodes initially
      position: position,
      dimensions: {
        width: defaultWidth,
        height: defaultHeight
      },
      styleOptions: {
        borderStyle: 'dashed' as const,
        opacity: 1,
        shadow: 'none' as const,
        icon: 'folder'
      }
    };

    // Add group to context
    addGroup(newGroup);

    // Create group node for ReactFlow
    const groupNode: Node = {
      id: groupId,
      type: 'groupNode',
      position: newGroup.position,
      width: newGroup.dimensions.width,
      height: newGroup.dimensions.height,
      style: {
        width: newGroup.dimensions.width,
        height: newGroup.dimensions.height,
        zIndex: -1 // Groups should be behind class nodes
      },
      data: {
        id: groupId,
        name: newGroup.name,
        color: newGroup.color,
        nodeIds: newGroup.nodeIds,
        styleOptions: newGroup.styleOptions,
        onRename: handleGroupRename,
        onDelete: handleGroupDelete,
        onColorChange: handleGroupColorChange,
        onStyleChange: handleGroupStyleChange,
        isReadOnly: isReadOnly
      }
    };

    // Add group node to canvas
    setNodes(prevNodes => [groupNode, ...prevNodes]);

    // Auto-save to database
    if (selectedVersionId && currentUserId) {
      try {
        // Prepare node data for saving
        const nodeData = nodes.filter(n => n.type !== 'groupNode').map(node => ({
          id: node.id,
          position: node.position,
          dimensions: node.style ? { width: node.style.width, height: node.style.height } : undefined
        }));

        // Prepare edge data for saving
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        // Include the new group in the groups array
        const updatedGroups = [...groups, newGroup];

        await saveDefaultCanvasLayout(
          selectedVersionId,
          currentUserId,
          viewport,
          nodeData,
          edgeData,
          updatedGroups
        );
      } catch (error) {
        console.error('Failed to auto-save group creation:', error);
      }
    }

  }, [groups, isReadOnly, addGroup, generateGroupId, setNodes, getViewport, handleGroupRename, handleGroupDelete, handleGroupColorChange, handleGroupStyleChange, selectedVersionId, currentUserId, nodes, edges]);

  // Register handleCreateGroup function in context for sidebar access
  useEffect(() => {
    setCreateGroupFn(() => handleCreateGroup);
    return () => setCreateGroupFn(null);
  }, [handleCreateGroup, setCreateGroupFn]);

  // Update group dimensions when nodes move
  const handleGroupResize = useCallback((groupId: string, position: { x: number; y: number }, dimensions: { width: number; height: number }) => {
    updateGroup(groupId, { position, dimensions });
  }, [updateGroup]);

  // Track previous group positions for calculating deltas
  const groupPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  // Custom onNodesChange that syncs group positions/dimensions, moves children, and constrains grouped nodes
  const handleNodesChange = useCallback((changes: any[]) => {
    // Track group position changes to move their child nodes
    const groupDeltas: Map<string, { dx: number; dy: number }> = new Map();

    // First pass: identify group position changes and process them
    changes.forEach((change: any) => {
      if (change.type === 'position' && change.position && change.dragging) {
        const node = nodes.find(n => n.id === change.id);
        if (node?.type === 'groupNode') {
          const oldPos = groupPositionsRef.current.get(change.id);
          if (oldPos) {
            const dx = change.position.x - oldPos.x;
            const dy = change.position.y - oldPos.y;
            if (dx !== 0 || dy !== 0) {
              groupDeltas.set(change.id, { dx, dy });
            }
          }
          // Update stored position
          groupPositionsRef.current.set(change.id, { x: change.position.x, y: change.position.y });
          updateGroup(change.id, { position: change.position });
        }
      } else if (change.type === 'position' && change.position && !change.dragging) {
        // Drag ended - update stored position
        const node = nodes.find(n => n.id === change.id);
        if (node?.type === 'groupNode') {
          groupPositionsRef.current.set(change.id, { x: change.position.x, y: change.position.y });
          updateGroup(change.id, { position: change.position });
        }
      } else if (change.type === 'dimensions' && change.dimensions) {
        const node = nodes.find(n => n.id === change.id);
        if (node?.type === 'groupNode') {
          updateGroup(change.id, { dimensions: change.dimensions });
          // Also update the node's style so bounds checking works correctly
          setNodes(prevNodes => prevNodes.map(n => {
            if (n.id === change.id) {
              return {
                ...n,
                style: {
                  ...n.style,
                  width: change.dimensions.width,
                  height: change.dimensions.height,
                },
              };
            }
            return n;
          }));
        }
      }
    });

    // Second pass: constrain grouped nodes within their group bounds during and after dragging
    const constrainedChanges = changes.map((change: any) => {
      if (change.type === 'position' && change.position) {
        const node = nodes.find(n => n.id === change.id);

        // Skip group nodes - they can move freely
        if (node?.type === 'groupNode') return change;

        // Check if this node belongs to a group
        const parentGroup = groups.find(g => g.nodeIds.includes(change.id));
        if (parentGroup) {
          const groupNode = nodes.find(n => n.id === parentGroup.id);
          if (groupNode) {
            const nodeWidth = (node?.measured?.width as number) || (node?.width as number) || 260;
            const nodeHeight = (node?.measured?.height as number) || (node?.height as number) || 200;
            const groupX = groupNode.position.x;
            const groupY = groupNode.position.y;
            // Use measured dimensions first (updated after resize), then style, then default
            const groupWidth = (groupNode.measured?.width as number) || (groupNode.style?.width as number) || 400;
            const groupHeight = (groupNode.measured?.height as number) || (groupNode.style?.height as number) || 300;

            // Check if node is completely outside the group
            const nodeLeft = change.position.x;
            const nodeRight = change.position.x + nodeWidth;
            const nodeTop = change.position.y;
            const nodeBottom = change.position.y + nodeHeight;
            const groupLeft = groupX;
            const groupRight = groupX + groupWidth;
            const groupTop = groupY;
            const groupBottom = groupY + groupHeight;

            const isCompletelyOutside = nodeRight < groupLeft || nodeLeft > groupRight ||
                                         nodeBottom < groupTop || nodeTop > groupBottom;

            // If completely outside during dragging, allow it (will trigger ungroup on drop)
            // But if not dragging (drag ended), we need to handle this in handleNodeDragStop
            if (isCompletelyOutside && change.dragging) {
              return change;
            }

            // If completely outside and drag just ended, let handleNodeDragStop handle it
            if (isCompletelyOutside && !change.dragging) {
              return change;
            }

            // Otherwise, constrain the node within the group bounds
            const constrainedX = Math.max(groupX, Math.min(change.position.x, groupX + groupWidth - nodeWidth));
            const constrainedY = Math.max(groupY, Math.min(change.position.y, groupY + groupHeight - nodeHeight));

            return {
              ...change,
              position: {
                x: constrainedX,
                y: constrainedY,
              },
            };
          }
        }
      }
      return change;
    });

    // Apply the constrained changes
    onNodesChange(constrainedChanges);

    // Move child nodes when their parent group moves
    if (groupDeltas.size > 0) {
      setNodes((prevNodes) => {
        return prevNodes.map((node) => {
          if (node.type === 'groupNode') return node;

          // Check if this node is in any moved group
          for (const [groupId, delta] of groupDeltas) {
            const group = groups.find(g => g.id === groupId);
            if (group && group.nodeIds.includes(node.id)) {
              return {
                ...node,
                position: {
                  x: node.position.x + delta.dx,
                  y: node.position.y + delta.dy,
                },
              };
            }
          }
          return node;
        });
      });
    }
  }, [onNodesChange, nodes, groups, updateGroup, setNodes]);

  // ============================================================================
  // END GROUP MANAGEMENT HANDLERS
  // ============================================================================

  // ============================================================================
  // LAYOUT SAVE/LOAD HANDLERS
  // ============================================================================

  // Save current canvas layout
  const handleSaveLayout = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId) return;

    try {
      setLoadingMessage('Saving canvas layout...');
      setIsLoadingCanvas(true);

      // Get current viewport
      const viewport = getViewport();

      // Extract node positions and dimensions
      const nodeData = nodes.map(node => ({
        id: node.id,
        type: node.type,
        position: node.position,
        dimensions: {
          width: node.measured?.width || node.width || node.style?.width,
          height: node.measured?.height || node.height || node.style?.height
        },
        data: node.type === 'groupNode' ? {
          name: node.data.name,
          color: node.data.color,
          nodeIds: node.data.nodeIds
        } : undefined
      }));

      // Extract edge data
      const edgeData = edges.map(edge => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle
      }));

      // Save to database
      const result = await saveDefaultCanvasLayout(
        selectedVersionId,
        currentUserId,
        viewport,
        nodeData,
        edgeData,
        groups
      );

      const response = JSON.parse(result);

      if (response.success) {
        // Show "Saved" state temporarily
        setLayoutSaved(true);
        setTimeout(() => {
          setLayoutSaved(false);
        }, 2000);
      } else {
        await alertDialog({
          message: response.error || 'Failed to save canvas layout',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error saving canvas layout:', error);
      await alertDialog({
        message: 'An error occurred while saving the canvas layout',
        variant: 'error',
      });
    } finally {
      setIsLoadingCanvas(false);
      setLoadingMessage('');
    }
  }, [isReadOnly, selectedVersionId, currentUserId, nodes, edges, groups, getViewport, alertDialog]);

  // Load saved canvas layout
  const handleLoadLayout = useCallback(async () => {
    if (!selectedVersionId || !currentUserId) return;

    try {
      setLoadingMessage('Loading canvas layout...');
      setIsLoadingCanvas(true);

      // Fetch saved layout from database
      const result = await getDefaultCanvasLayout(selectedVersionId, currentUserId);
      const response = JSON.parse(result);

      if (!response.success || !response.layout) {
        await alertDialog({
          message: 'No saved layout found for this version',
          variant: 'warning',
        });
        setIsLoadingCanvas(false);
        setLoadingMessage('');
        setLayoutDropdownOpen(false);
        return;
      }

      const layout = response.layout;

      // Restore viewport using setViewport for accurate restoration
      if (layout.viewport) {
        setViewport({ x: layout.viewport.x, y: layout.viewport.y, zoom: layout.viewport.zoom }, { duration: 800 });
      }

      // Load groups from dedicated table
      let loadedGroups: any[] = [];
      try {
        const groupsResult = await getGroupsForVersion(selectedVersionId);
        loadedGroups = JSON.parse(groupsResult);

        if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
          // Transform to CanvasGroup format
          const canvasGroups = loadedGroups.map((g: any) => ({
            id: g.id,
            name: g.name,
            description: g.description,
            color: g.color,
            position: g.position,
            dimensions: g.dimensions,
            nodeIds: g.nodeIds || [],
            tags: g.metadata?.tags || [],
            styleOptions: {
              borderStyle: g.borderStyle || 'dashed',
              opacity: g.opacity ?? 1,
              shadow: g.metadata?.shadow || 'none',
              icon: g.metadata?.icon || 'folder'
            }
          }));
          setGroups(canvasGroups);
          loadedGroups = canvasGroups;
        }
      } catch (error) {
        console.error('Error loading groups:', error);
      }

      // Restore nodes - need to reload classes and apply saved positions
      await reloadClasses(false);

      // After classes are loaded, apply saved positions and create group nodes
      setTimeout(() => {
        const availableTags = projectTags.map(t => ({ id: t.id, name: t.tag_name, color: t.tag_color }));

        // Create group nodes from loaded groups
        const groupNodes: Node[] = [];
        if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
          loadedGroups.forEach((group: any) => {
            const groupNode: Node = {
              id: group.id,
              type: 'groupNode',
              position: group.position,
              width: group.dimensions.width,
              height: group.dimensions.height,
              style: {
                width: group.dimensions.width,
                height: group.dimensions.height,
                zIndex: -1
              },
              data: {
                id: group.id,
                name: group.name,
                color: group.color,
                nodeIds: group.nodeIds || [],
                tags: group.tags || [],
                styleOptions: group.styleOptions,
                availableTags,
                onRename: (groupId: string, name: string) => handleGroupRenameRef.current?.(groupId, name),
                onDelete: (groupId: string) => handleGroupDeleteRef.current?.(groupId),
                onColorChange: (groupId: string, color: string) => handleGroupColorChangeRef.current?.(groupId, color),
                onStyleChange: (groupId: string, style: any) => handleGroupStyleChangeRef.current?.(groupId, style),
                onTagsChange: (groupId: string, tags: any[]) => handleGroupTagsChangeRef.current?.(groupId, tags),
                isReadOnly
              }
            };
            groupNodes.push(groupNode);
          });
        }

        if (layout.nodes && Array.isArray(layout.nodes)) {
          setNodes(prevNodes => {
            // Map existing nodes to update positions
            const updatedNodes = prevNodes.map(node => {
              const savedNode = layout.nodes.find((n: any) => n.id === node.id);
              if (savedNode) {
                return {
                  ...node,
                  position: savedNode.position,
                  ...(savedNode.dimensions && {
                    style: {
                      ...node.style,
                      width: savedNode.dimensions.width,
                      height: savedNode.dimensions.height
                    }
                  })
                };
              }
              return node;
            });

            // Add group nodes at the beginning (behind other nodes due to zIndex: -1)
            return [...groupNodes, ...updatedNodes];
          });
        } else {
          // If no saved nodes, just add group nodes
          setNodes(prevNodes => [...groupNodes, ...prevNodes]);
        }

        // Trigger sidebar refresh to update groups list
        triggerSidebarRefresh();

        setIsLoadingCanvas(false);
        setLoadingMessage('');
        setLayoutDropdownOpen(false);
      }, 500);

    } catch (error) {
      console.error('Error loading canvas layout:', error);
      await alertDialog({
        message: 'An error occurred while loading the canvas layout',
        variant: 'error',
      });
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setLayoutDropdownOpen(false);
    }
  }, [selectedVersionId, currentUserId, reloadClasses, setNodes, setGroups, setViewport, alertDialog, projectTags, isReadOnly, triggerSidebarRefresh]);

  // ============================================================================
  // END LAYOUT SAVE/LOAD HANDLERS
  // ============================================================================

  // Handle PNG export
  const handleExportPng = useCallback(async () => {
    try {
      // Get the ReactFlow viewport element
      const viewportElement = document.querySelector('.react-flow__viewport') as HTMLElement;

      if (!viewportElement) {
        await alertDialog({
          message: 'Canvas not found. Please try again.',
          variant: 'error',
        });
        return;
      }

      // Get project and version info for filename
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.png`;

      // Show loading state
      setLoadingMessage('Exporting canvas as PNG...');
      setIsLoadingCanvas(true);

      // Use html-to-image to convert the canvas to PNG
      const dataUrl = await toPng(viewportElement, {
        backgroundColor: isDark ? '#111827' : '#ffffff',
        quality: 1.0,
        pixelRatio: 2, // Higher quality export (2x resolution)
        filter: (node) => {
          // Exclude controls, minimap, and other UI elements
          if (node.classList) {
            return !node.classList.contains('react-flow__controls') &&
                   !node.classList.contains('react-flow__minimap') &&
                   !node.classList.contains('react-flow__attribution') &&
                   !node.classList.contains('react-flow__panel');
          }
          return true;
        },
      });

      // Create a download link and trigger download
      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message briefly
      await alertDialog({
        message: `Canvas exported as ${filename}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting PNG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as PNG. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, isDark, alertDialog]);

  // Handle SVG export
  const handleExportSvg = useCallback(async () => {
    try {
      // Get the ReactFlow viewport element
      const viewportElement = document.querySelector('.react-flow__viewport') as HTMLElement;

      if (!viewportElement) {
        await alertDialog({
          message: 'Canvas not found. Please try again.',
          variant: 'error',
        });
        return;
      }

      // Get project and version info for filename
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.svg`;

      // Show loading state
      setLoadingMessage('Exporting canvas as SVG...');
      setIsLoadingCanvas(true);

      // Use html-to-image to convert the canvas to SVG
      const dataUrl = await toSvg(viewportElement, {
        backgroundColor: isDark ? '#111827' : '#ffffff',
        quality: 1.0,
        filter: (node) => {
          // Exclude controls, minimap, and other UI elements
          if (node.classList) {
            return !node.classList.contains('react-flow__controls') &&
                   !node.classList.contains('react-flow__minimap') &&
                   !node.classList.contains('react-flow__attribution') &&
                   !node.classList.contains('react-flow__panel');
          }
          return true;
        },
      });

      // Create a download link and trigger download
      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message briefly
      await alertDialog({
        message: `Canvas exported as ${filename}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting SVG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as SVG. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, isDark, alertDialog]);

  // Handle PDF export
  const handleExportPdf = useCallback(async () => {
    try {
      // Get the ReactFlow viewport element
      const viewportElement = document.querySelector('.react-flow__viewport') as HTMLElement;

      if (!viewportElement) {
        await alertDialog({
          message: 'Canvas not found. Please try again.',
          variant: 'error',
        });
        return;
      }

      // Get project and version info for filename and metadata
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.pdf`;

      // Show loading state
      setLoadingMessage('Exporting canvas as PDF...');
      setIsLoadingCanvas(true);

      // First, convert the canvas to PNG for embedding in PDF
      const imageDataUrl = await toPng(viewportElement, {
        backgroundColor: isDark ? '#111827' : '#ffffff',
        quality: 1.0,
        pixelRatio: 2, // High quality for PDF
        filter: (node) => {
          // Exclude controls, minimap, and other UI elements
          if (node.classList) {
            return !node.classList.contains('react-flow__controls') &&
                   !node.classList.contains('react-flow__minimap') &&
                   !node.classList.contains('react-flow__attribution') &&
                   !node.classList.contains('react-flow__panel');
          }
          return true;
        },
      });

      // Get the actual dimensions of the viewport
      const viewportRect = viewportElement.getBoundingClientRect();
      const imgWidth = viewportRect.width;
      const imgHeight = viewportRect.height;

      // Calculate PDF page size to fit the canvas
      // Standard A4 is 210mm x 297mm (landscape: 297mm x 210mm)
      // We'll use landscape orientation and scale to fit
      const pdfWidth = 297; // A4 landscape width in mm
      const pdfHeight = 210; // A4 landscape height in mm

      // Calculate scaling to fit canvas in PDF while maintaining aspect ratio
      const scaleX = pdfWidth / imgWidth;
      const scaleY = pdfHeight / imgHeight;
      const scale = Math.min(scaleX, scaleY);

      const scaledWidth = imgWidth * scale;
      const scaledHeight = imgHeight * scale;

      // Center the image on the page
      const xOffset = (pdfWidth - scaledWidth) / 2;
      const yOffset = (pdfHeight - scaledHeight) / 2;

      // Create PDF document
      const pdf = new jsPDF({
        orientation: 'landscape',
        unit: 'mm',
        format: 'a4',
      });

      // Add metadata
      pdf.setProperties({
        title: `${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}`,
        subject: 'API Schema Canvas Export',
        author: 'Objectified',
        keywords: 'api, schema, openapi, canvas',
        creator: 'Objectified Studio',
      });

      // Add title at the top
      pdf.setFontSize(16);
      pdf.setTextColor(isDark ? 200 : 40);
      pdf.text(`${selectedProject?.name || 'Canvas'} - v${selectedVersion?.version_id || '1'}`, 10, 15);

      // Add timestamp
      pdf.setFontSize(10);
      pdf.setTextColor(isDark ? 150 : 100);
      pdf.text(`Exported: ${new Date().toLocaleString()}`, 10, 22);

      // Add the canvas image to PDF
      pdf.addImage(imageDataUrl, 'PNG', xOffset, yOffset + 15, scaledWidth, scaledHeight - 15);

      // Add footer with page number
      pdf.setFontSize(8);
      pdf.setTextColor(isDark ? 150 : 100);
      pdf.text('Generated by Objectified Studio', pdfWidth - 60, pdfHeight - 5);

      // Save the PDF
      pdf.save(filename);

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message
      await alertDialog({
        message: `Canvas exported as ${filename}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting PDF:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as PDF. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, isDark, alertDialog]);

  // Handle JPEG export
  const handleExportJpeg = useCallback(async () => {
    try {
      // Get the ReactFlow viewport element
      const viewportElement = document.querySelector('.react-flow__viewport') as HTMLElement;

      if (!viewportElement) {
        await alertDialog({
          message: 'Canvas not found. Please try again.',
          variant: 'error',
        });
        return;
      }

      // Get project and version info for filename
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.jpg`;

      // Show loading state
      setLoadingMessage('Exporting canvas as JPEG...');
      setIsLoadingCanvas(true);

      // Use html-to-image to convert the canvas to JPEG
      const dataUrl = await toJpeg(viewportElement, {
        backgroundColor: isDark ? '#111827' : '#ffffff',
        quality: 0.95, // High quality JPEG (0.0 to 1.0)
        pixelRatio: 2, // Higher quality export (2x resolution)
        filter: (node) => {
          // Exclude controls, minimap, and other UI elements
          if (node.classList) {
            return !node.classList.contains('react-flow__controls') &&
                   !node.classList.contains('react-flow__minimap') &&
                   !node.classList.contains('react-flow__attribution') &&
                   !node.classList.contains('react-flow__panel');
          }
          return true;
        },
      });

      // Create a download link and trigger download
      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message briefly
      await alertDialog({
        message: `Canvas exported as ${filename}`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting JPEG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as JPEG. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, isDark, alertDialog]);

  // Handle Mermaid Diagram export
  const handleExportMermaid = useCallback(async () => {
    try {
      // Get project and version info for filename
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.id === selectedVersionId);
      const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'diagram';
      const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
      const filename = `${projectSlug}-${versionSlug}-diagram.mmd`;

      // Show loading state
      setLoadingMessage('Exporting canvas as Mermaid diagram...');
      setIsLoadingCanvas(true);

      // Generate Mermaid content from nodes
      const classesWithProperties = nodes.map(node => ({
        id: node.id,
        name: (node.data as any)?.name || 'Unknown',
        description: (node.data as any)?.description,
        schema: (node.data as any)?.schema,
        properties: (node.data as any)?.properties || [],
      }));

      const mermaidContent = generateMermaidDiagram(classesWithProperties);

      // Create and download the file
      const blob = new Blob([mermaidContent], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      // Close dropdown
      setExportDropdownOpen(false);
      setIsLoadingCanvas(false);

      await alertDialog({
        message: `Canvas exported as ${filename}. You can visualize this file using Mermaid Live Editor or other Mermaid-compatible tools.`,
        variant: 'success',
      });
    } catch (error) {
      setIsLoadingCanvas(false);
      console.error('Error exporting Mermaid:', error);

      await alertDialog({
        message: 'Failed to export canvas as Mermaid diagram. Please try again.',
        variant: 'error',
      });
    }
  }, [nodes, projects, versions, selectedProjectId, selectedVersionId, alertDialog]);

  // Handle PlantUML export
  const handleExportPlantUml = useCallback(async () => {
    try {
      // Get project and version info for filename and metadata
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.puml`;

      // Show loading state
      setLoadingMessage('Exporting canvas as PlantUML...');
      setIsLoadingCanvas(true);

      // Generate PlantUML content from nodes and edges
      let plantUmlContent = '@startuml\n';
      plantUmlContent += `' ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}\n`;
      plantUmlContent += `' Generated by Objectified Studio on ${new Date().toLocaleDateString()}\n\n`;

      // Add styling
      plantUmlContent += 'skinparam classAttributeIconSize 0\n';
      plantUmlContent += 'skinparam shadowing false\n';
      plantUmlContent += 'skinparam backgroundColor transparent\n';
      plantUmlContent += 'skinparam class {\n';
      plantUmlContent += '  BackgroundColor White\n';
      plantUmlContent += '  BorderColor #4F46E5\n';
      plantUmlContent += '  ArrowColor #6366F1\n';
      plantUmlContent += '  FontColor Black\n';
      plantUmlContent += '}\n\n';

      // Process nodes (classes)
      const classMap = new Map<string, any>();
      nodes.forEach(node => {
        if (node.data) {
          classMap.set(node.id, node.data);

          const className = node.data.name || 'UnnamedClass';
          const description = node.data.description ? ` << ${node.data.description} >>` : '';

          plantUmlContent += `class ${className}${description} {\n`;

          // Add properties
          if (node.data.properties && Array.isArray(node.data.properties)) {
            node.data.properties.forEach((prop: any) => {
              const propName = prop.name || 'unnamed';
              const propType = prop.type || 'string';
              const isRequired = prop.required ? '+' : '-';
              const isArray = prop.is_array ? '[]' : '';

              plantUmlContent += `  ${isRequired} ${propName}: ${propType}${isArray}\n`;
            });
          }

          plantUmlContent += '}\n\n';
        }
      });

      // Process edges (relationships)
      edges.forEach(edge => {
        const sourceNode = classMap.get(edge.source);
        const targetNode = classMap.get(edge.target);

        if (sourceNode && targetNode) {
          const sourceName = sourceNode.name || 'UnnamedClass';
          const targetName = targetNode.name || 'UnnamedClass';

          // Determine relationship type based on edge data
          let relationshipSymbol = '-->';
          let label = '';

          if (edge.data) {
            const edgeType = edge.data.type || edge.label;

            if (edgeType === 'allOf' || edgeType === 'inheritance') {
              relationshipSymbol = '--|>';
              label = 'extends';
            } else if (edgeType === 'anyOf') {
              relationshipSymbol = '-->';
              label = 'anyOf';
            } else if (edgeType === 'oneOf') {
              relationshipSymbol = '-->';
              label = 'oneOf';
            } else if (edge.data.cardinality) {
              label = String(edge.data.cardinality);
            } else if (edge.label) {
              label = edge.label.toString();
            }
          }

          const labelText = label ? ` : ${label}` : '';
          plantUmlContent += `${sourceName} ${relationshipSymbol} ${targetName}${labelText}\n`;
        }
      });

      plantUmlContent += '\n@enduml\n';

      // Create a blob and download
      const blob = new Blob([plantUmlContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message
      await alertDialog({
        message: `Canvas exported as ${filename}. You can visualize this file using PlantUML tools or online renderers.`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting PlantUML:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as PlantUML. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, alertDialog]);

  // Handle GraphML export
  const handleExportGraphMl = useCallback(async () => {
    try {
      // Get project and version info for filename and metadata
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.graphml`;

      // Show loading state
      setLoadingMessage('Exporting canvas as GraphML...');
      setIsLoadingCanvas(true);

      // Generate GraphML content from nodes and edges
      let graphMlContent = '<?xml version="1.0" encoding="UTF-8"?>\n';
      graphMlContent += '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"\n';
      graphMlContent += '    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n';
      graphMlContent += '    xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns\n';
      graphMlContent += '    http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">\n\n';

      // Define keys (attributes/properties)
      graphMlContent += '  <!-- Node attributes -->\n';
      graphMlContent += '  <key id="d0" for="node" attr.name="name" attr.type="string"/>\n';
      graphMlContent += '  <key id="d1" for="node" attr.name="description" attr.type="string"/>\n';
      graphMlContent += '  <key id="d2" for="node" attr.name="properties" attr.type="string"/>\n';
      graphMlContent += '  <key id="d3" for="node" attr.name="x" attr.type="double"/>\n';
      graphMlContent += '  <key id="d4" for="node" attr.name="y" attr.type="double"/>\n';
      graphMlContent += '  <key id="d5" for="node" attr.name="type" attr.type="string"/>\n\n';

      // Define edge attributes
      graphMlContent += '  <!-- Edge attributes -->\n';
      graphMlContent += '  <key id="e0" for="edge" attr.name="label" attr.type="string"/>\n';
      graphMlContent += '  <key id="e1" for="edge" attr.name="type" attr.type="string"/>\n';
      graphMlContent += '  <key id="e2" for="edge" attr.name="cardinality" attr.type="string"/>\n\n';

      // Graph metadata
      graphMlContent += `  <graph id="G" edgedefault="directed">\n`;
      graphMlContent += `    <!-- ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'} -->\n`;
      graphMlContent += `    <!-- Generated by Objectified Studio on ${new Date().toLocaleDateString()} -->\n\n`;

      // Process nodes
      nodes.forEach(node => {
        if (node.data) {
          graphMlContent += `    <node id="${node.id}">\n`;

          // Add node attributes
          if (node.data.name) {
            graphMlContent += `      <data key="d0">${escapeXml(String(node.data.name))}</data>\n`;
          }

          if (node.data.description) {
            graphMlContent += `      <data key="d1">${escapeXml(String(node.data.description))}</data>\n`;
          }

          // Add properties as JSON string
          if (node.data.properties && Array.isArray(node.data.properties)) {
            const propsJson = JSON.stringify(node.data.properties.map((prop: any) => ({
              name: prop.name,
              type: prop.type,
              required: prop.required,
              is_array: prop.is_array,
              description: prop.description
            })));
            graphMlContent += `      <data key="d2">${escapeXml(propsJson)}</data>\n`;
          }

          // Add position
          if (node.position) {
            graphMlContent += `      <data key="d3">${node.position.x}</data>\n`;
            graphMlContent += `      <data key="d4">${node.position.y}</data>\n`;
          }

          // Add node type
          graphMlContent += `      <data key="d5">class</data>\n`;

          graphMlContent += `    </node>\n\n`;
        }
      });

      // Process edges
      edges.forEach((edge, index) => {
        const edgeId = `e${index}`;
        graphMlContent += `    <edge id="${edgeId}" source="${edge.source}" target="${edge.target}">\n`;

        // Add edge label
        if (edge.label) {
          graphMlContent += `      <data key="e0">${escapeXml(String(edge.label))}</data>\n`;
        }

        // Add edge type
        if (edge.data) {
          const edgeType = edge.data.type || 'reference';
          graphMlContent += `      <data key="e1">${escapeXml(String(edgeType))}</data>\n`;

          // Add cardinality if available
          if (edge.data.cardinality) {
            graphMlContent += `      <data key="e2">${escapeXml(String(edge.data.cardinality))}</data>\n`;
          }
        }

        graphMlContent += `    </edge>\n\n`;
      });

      graphMlContent += '  </graph>\n';
      graphMlContent += '</graphml>\n';

      // Helper function to escape XML special characters
      function escapeXml(unsafe: string): string {
        return unsafe
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&apos;');
      }

      // Create a blob and download
      const blob = new Blob([graphMlContent], { type: 'application/xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message
      await alertDialog({
        message: `Canvas exported as ${filename}. You can open this file in yEd, Gephi, Cytoscape, Neo4j, or other graph tools.`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting GraphML:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as GraphML. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, alertDialog]);

  // Handle DOT (GraphViz) export
  const handleExportDot = useCallback(async () => {
    try {
      // Get project and version info for filename and metadata
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}.dot`;

      // Show loading state
      setLoadingMessage('Exporting canvas as DOT...');
      setIsLoadingCanvas(true);

      // Generate DOT content from nodes and edges
      let dotContent = 'digraph {\n';
      dotContent += `  // ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}\n`;
      dotContent += `  // Generated by Objectified Studio on ${new Date().toLocaleDateString()}\n\n`;

      // Graph attributes
      dotContent += '  // Graph styling\n';
      dotContent += '  graph [rankdir=TB, nodesep=0.5, ranksep=0.8, bgcolor=transparent];\n';
      dotContent += '  node [shape=record, style=filled, fillcolor="#f8f9fa", fontname="Arial", fontsize=10];\n';
      dotContent += '  edge [color="#4F46E5", fontname="Arial", fontsize=9];\n\n';

      // Process nodes
      const nodeMap = new Map<string, string>();
      nodes.forEach(node => {
        if (node.data) {
          const nodeId = node.id.replace(/[^a-zA-Z0-9_]/g, '_');
          nodeMap.set(node.id, nodeId);

          const className = String(node.data.name || 'UnnamedClass').replace(/"/g, '\\"');

          // Build node label with properties
          let label = `{${className}|`;

          if (node.data.properties && Array.isArray(node.data.properties)) {
            const propLines = node.data.properties.map((prop: any) => {
              const propName = String(prop.name || 'unnamed').replace(/"/g, '\\"');
              const propType = String(prop.type || 'string').replace(/"/g, '\\"');
              const isRequired = prop.required ? '+' : '-';
              const isArray = prop.is_array ? '[]' : '';
              return `${isRequired} ${propName}: ${propType}${isArray}`;
            });

            if (propLines.length > 0) {
              label += propLines.join('\\l') + '\\l';
            }
          }

          label += '}';

          dotContent += `  ${nodeId} [label="${label}"];\n`;
        }
      });

      dotContent += '\n  // Relationships\n';

      // Process edges
      edges.forEach(edge => {
        const sourceId = nodeMap.get(edge.source);
        const targetId = nodeMap.get(edge.target);

        if (sourceId && targetId) {
          let edgeAttrs = [];

          // Determine edge style based on type
          if (edge.data) {
            const edgeType = edge.data.type;

            if (edgeType === 'allOf' || edgeType === 'inheritance') {
              edgeAttrs.push('arrowhead=empty');
              edgeAttrs.push('style=solid');
              if (edge.label) {
                edgeAttrs.push(`label="${String(edge.label).replace(/"/g, '\\"')}"`);
              } else {
                edgeAttrs.push('label="extends"');
              }
            } else if (edgeType === 'anyOf') {
              edgeAttrs.push('arrowhead=vee');
              edgeAttrs.push('style=dashed');
              edgeAttrs.push('label="anyOf"');
            } else if (edgeType === 'oneOf') {
              edgeAttrs.push('arrowhead=vee');
              edgeAttrs.push('style=dashed');
              edgeAttrs.push('label="oneOf"');
            } else {
              edgeAttrs.push('arrowhead=vee');
              if (edge.label) {
                edgeAttrs.push(`label="${String(edge.label).replace(/"/g, '\\"')}"`);
              }
            }

            // Add cardinality if available
            if (edge.data.cardinality) {
              const card = String(edge.data.cardinality).replace(/"/g, '\\"');
              if (!edge.label) {
                edgeAttrs.push(`label="${card}"`);
              } else {
                edgeAttrs.push(`headlabel="${card}"`);
              }
            }
          } else if (edge.label) {
            edgeAttrs.push(`label="${String(edge.label).replace(/"/g, '\\"')}"`);
          }

          const attrs = edgeAttrs.length > 0 ? ` [${edgeAttrs.join(', ')}]` : '';
          dotContent += `  ${sourceId} -> ${targetId}${attrs};\n`;
        }
      });

      dotContent += '}\n';

      // Create a blob and download
      const blob = new Blob([dotContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message
      await alertDialog({
        message: `Canvas exported as ${filename}. You can visualize this file using GraphViz tools (dot, neato, fdp, etc.) or online at https://dreampuf.github.io/GraphvizOnline/`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting DOT:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as DOT. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, alertDialog]);

  // Handle JSON export
  const handleExportJson = useCallback(async () => {
    try {
      // Get project and version info for filename
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}-canvas.json`;

      // Show loading state
      setLoadingMessage('Exporting canvas as JSON...');
      setIsLoadingCanvas(true);

      // Build the canvas data structure
      const canvasData = {
        metadata: {
          projectName: selectedProject?.name || 'Unknown',
          projectSlug: selectedProject?.slug || '',
          versionId: selectedVersion?.version_id || '',
          versionDescription: selectedVersion?.description || '',
          exportDate: new Date().toISOString(),
          exportFormat: 'objectified-canvas-v1',
        },
        nodes: nodes.map(node => ({
          id: node.id,
          type: node.type,
          position: node.position,
          data: {
            id: node.data.id,
            name: node.data.name,
            description: node.data.description,
            properties: Array.isArray(node.data.properties) ? node.data.properties.map((prop: any) => ({
              id: prop.id,
              name: prop.name,
              description: prop.description,
              data: prop.data,
              parent_id: prop.parent_id,
            })) : [],
            schema: node.data.schema,
            tags: Array.isArray(node.data.tags) ? node.data.tags.map((tag: any) => ({
              id: tag.id,
              name: tag.tag_name,
              color: tag.tag_color,
              description: tag.tag_description,
            })) : [],
          },
        })),
        edges: edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          type: edge.type,
          label: edge.label,
          data: edge.data,
        })),
        viewport: {
          x: 0,
          y: 0,
          zoom: 1,
        },
      };

      // Create a blob and download
      const jsonContent = JSON.stringify(canvasData, null, 2);
      const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      // Hide loading state
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      // Close the export dropdown
      setExportDropdownOpen(false);

      // Show success message
      await alertDialog({
        message: `Canvas exported as ${filename}. This JSON file contains the complete canvas structure including nodes, edges, and metadata.`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting JSON:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');

      await alertDialog({
        message: 'Failed to export canvas as JSON. Please try again.',
        variant: 'error',
      });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, alertDialog]);

  // Define custom node types
  const nodeTypes = {
    classNode: ClassNode,
    groupNode: GroupNode,
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
        onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args),
        zoomLevel: 1 // Initial zoom level
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
        // Handle nullable type arrays for isSourceArray check
        let sourceBaseType = propData.type;
        if (Array.isArray(propData.type)) {
          sourceBaseType = propData.type.find((t: string) => t !== 'null');
        }
        const isSourceArray = sourceBaseType === 'array';

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
        else if (sourceBaseType === 'array' && propData.items?.$ref) {
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
              // Handle nullable type arrays for target property
              let targetBaseType = targetPropData.type;
              if (Array.isArray(targetPropData.type)) {
                targetBaseType = targetPropData.type.find((t: string) => t !== 'null');
              }
              const targetRefName = targetPropData.$ref
                ? extractClassNameFromRef(targetPropData.$ref)
                : (targetBaseType === 'array' && targetPropData.items?.$ref
                    ? extractClassNameFromRef(targetPropData.items.$ref)
                    : null);

              if (targetRefName === sourceClassName) {
                hasReverseRef = true;
                isTargetArray = targetBaseType === 'array';
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

          // Handle nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
          let baseType = propData.type;
          let isNullable = false;
          if (Array.isArray(propData.type)) {
            isNullable = propData.type.includes('null');
            baseType = propData.type.find((t: string) => t !== 'null') || 'any';
          }
          let propType = baseType || 'any';

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
          else if (baseType === 'array' && propData.items) {
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

          // Add nullable indicator if the type is nullable
          const displayType = isNullable ? `${propType}?` : propType;
          lines.push(`        +${displayType} ${prop.name}`);
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
          // Handle nullable type arrays for isSourceArray check
          let sourceBaseType = propData.type;
          if (Array.isArray(propData.type)) {
            sourceBaseType = propData.type.find((t: string) => t !== 'null');
          }
          const isSourceArray = sourceBaseType === 'array';

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
          else if (sourceBaseType === 'array' && propData.items) {
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

  // Load projects on mount
  useEffect(() => {
    if (currentTenantId) {
      loadProjects();
    }
  }, [currentTenantId]);


  // Handle clicking outside export dropdown to close it
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportDropdownRef.current && !exportDropdownRef.current.contains(event.target as HTMLElement)) {
        setExportDropdownOpen(false);
      }
      if (layoutDropdownRef.current && !layoutDropdownRef.current.contains(event.target as HTMLElement)) {
        setLayoutDropdownOpen(false);
      }
    };

    if (exportDropdownOpen || layoutDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [exportDropdownOpen, layoutDropdownOpen]);

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
      setLoadingMessage('Loading classes, properties, and tags...');

      try {
        // Bulk load all classes with properties and tags in 3 queries instead of N*2+1
        const result = await getClassesWithPropertiesAndTags(selectedVersionId);
        const classesWithProperties = JSON.parse(result);

        setLoadingMessage(`Processing ${classesWithProperties.length} class${classesWithProperties.length !== 1 ? 'es' : ''}...`);

        setLoadingMessage('Creating canvas nodes...');

        // Convert classes to React Flow nodes
        const newNodes = await classesToNodes(classesWithProperties);

        setLoadingMessage('Creating relationship edges...');

        // Create edges for both property $ref and composition relationships
        const newEdges = createAllEdges(classesWithProperties);

        // Check if this is the initial load for this version and if saved layout exists
        const isInitialLoad = initialLayoutAppliedRef.current !== selectedVersionId;
        let savedLayout: any = null;

        if (isInitialLoad && currentUserId) {
          try {
            setLoadingMessage('Checking for saved layout...');
            const layoutResult = await getDefaultCanvasLayout(selectedVersionId, currentUserId);
            const layoutResponse = JSON.parse(layoutResult);
            if (layoutResponse.success && layoutResponse.layout) {
              savedLayout = layoutResponse.layout;
            }
          } catch (e) {
            console.log('No saved layout found, using default layout');
          }
        }

        let finalNodes: Node[];

        if (savedLayout && isInitialLoad) {
          setLoadingMessage('Applying saved layout...');

          // Apply saved positions to nodes
          finalNodes = newNodes.map(node => {
            const savedNode = savedLayout.nodes?.find((n: any) => n.id === node.id);
            if (savedNode) {
              return {
                ...node,
                position: savedNode.position,
                ...(savedNode.dimensions && {
                  style: {
                    ...node.style,
                    width: savedNode.dimensions.width,
                    height: savedNode.dimensions.height
                  }
                })
              };
            }
            return node;
          });

          // Load groups from dedicated table
          try {
            const groupsResult = await getGroupsForVersion(selectedVersionId);
            const loadedGroups = JSON.parse(groupsResult);

            if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
              // Transform to CanvasGroup format
              const canvasGroups = loadedGroups.map((g: any) => ({
                id: g.id,
                name: g.name,
                description: g.description,
                color: g.color,
                position: g.position,
                dimensions: g.dimensions,
                nodeIds: g.nodeIds || [],
                tags: g.metadata?.tags || [],
                styleOptions: {
                  borderStyle: g.borderStyle || 'dashed',
                  opacity: g.opacity ?? 1,
                  shadow: g.metadata?.shadow || 'none',
                  icon: g.metadata?.icon || 'folder'
                }
              }));

              setGroups(canvasGroups);

              // Create group nodes
              const availableTags = projectTags.map(t => ({ id: t.id, name: t.tag_name, color: t.tag_color }));
              const groupNodes: Node[] = canvasGroups.map((group: any) => ({
                id: group.id,
                type: 'groupNode',
                position: group.position,
                width: group.dimensions.width,
                height: group.dimensions.height,
                style: {
                  width: group.dimensions.width,
                  height: group.dimensions.height,
                  zIndex: -1
                },
                data: {
                  id: group.id,
                  name: group.name,
                  color: group.color,
                  nodeIds: group.nodeIds || [],
                  tags: group.tags || [],
                  styleOptions: group.styleOptions,
                  availableTags,
                  onRename: (groupId: string, name: string) => handleGroupRenameRef.current?.(groupId, name),
                  onDelete: (groupId: string) => handleGroupDeleteRef.current?.(groupId),
                  onColorChange: (groupId: string, color: string) => handleGroupColorChangeRef.current?.(groupId, color),
                  onStyleChange: (groupId: string, style: any) => handleGroupStyleChangeRef.current?.(groupId, style),
                  onTagsChange: (groupId: string, tags: any[]) => handleGroupTagsChangeRef.current?.(groupId, tags),
                  isReadOnly
                }
              }));

              finalNodes = [...groupNodes, ...finalNodes];

              // Trigger sidebar refresh to update groups
              triggerSidebarRefresh();
            }
          } catch (error) {
            console.error('Error loading groups:', error);
          }

          // Mark this version as having initial layout applied
          initialLayoutAppliedRef.current = selectedVersionId;

          // Restore viewport if available using setViewport for accurate restoration
          if (savedLayout.viewport) {
            setTimeout(() => {
              setViewport({ x: savedLayout.viewport.x, y: savedLayout.viewport.y, zoom: savedLayout.viewport.zoom }, { duration: 800 });
            }, 100);
          }

          // Trigger sidebar refresh to update groups
          triggerSidebarRefresh();
        } else {
          setLoadingMessage('Applying auto-layout...');

          // Load groups from dedicated table even without a saved layout
          try {
            const groupsResult = await getGroupsForVersion(selectedVersionId);
            const loadedGroups = JSON.parse(groupsResult);

            if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
              // Transform to CanvasGroup format
              const canvasGroups = loadedGroups.map((g: any) => ({
                id: g.id,
                name: g.name,
                description: g.description,
                color: g.color,
                position: g.position,
                dimensions: g.dimensions,
                nodeIds: g.nodeIds || [],
                tags: g.metadata?.tags || [],
                styleOptions: {
                  borderStyle: g.borderStyle || 'dashed',
                  opacity: g.opacity ?? 1,
                  shadow: g.metadata?.shadow || 'none',
                  icon: g.metadata?.icon || 'folder'
                }
              }));

              setGroups(canvasGroups);

              // Create group nodes
              const availableTags = projectTags.map(t => ({ id: t.id, name: t.tag_name, color: t.tag_color }));
              const groupNodes: Node[] = canvasGroups.map((group: any) => ({
                id: group.id,
                type: 'groupNode',
                position: group.position,
                width: group.dimensions.width,
                height: group.dimensions.height,
                style: {
                  width: group.dimensions.width,
                  height: group.dimensions.height,
                  zIndex: -1
                },
                data: {
                  id: group.id,
                  name: group.name,
                  color: group.color,
                  nodeIds: group.nodeIds || [],
                  tags: group.tags || [],
                  styleOptions: group.styleOptions,
                  availableTags,
                  onRename: (groupId: string, name: string) => handleGroupRenameRef.current?.(groupId, name),
                  onDelete: (groupId: string) => handleGroupDeleteRef.current?.(groupId),
                  onColorChange: (groupId: string, color: string) => handleGroupColorChangeRef.current?.(groupId, color),
                  onStyleChange: (groupId: string, style: any) => handleGroupStyleChangeRef.current?.(groupId, style),
                  onTagsChange: (groupId: string, tags: any[]) => handleGroupTagsChangeRef.current?.(groupId, tags),
                  isReadOnly
                }
              }));

              // Apply auto-layout if enabled, but only to ungrouped nodes
              if (autoLayoutEnabled) {
                // Get grouped node IDs
                const groupedNodeIds = new Set<string>();
                canvasGroups.forEach((g: any) => {
                  (g.nodeIds || []).forEach((nodeId: string) => groupedNodeIds.add(nodeId));
                });

                // Separate grouped and ungrouped nodes
                const groupedClassNodes = newNodes.filter(n => groupedNodeIds.has(n.id));
                const ungroupedNodes = newNodes.filter(n => !groupedNodeIds.has(n.id));

                // Only layout ungrouped class nodes
                const ungroupedNodeIds = new Set(ungroupedNodes.map(n => n.id));
                const ungroupedEdges = newEdges.filter(e =>
                  ungroupedNodeIds.has(e.source) && ungroupedNodeIds.has(e.target)
                );

                const layoutedUngroupedNodes = ungroupedNodes.length > 0
                  ? getLayoutedElements(ungroupedNodes, ungroupedEdges, { direction: layoutDirection })
                  : [];

                finalNodes = [...groupNodes, ...groupedClassNodes, ...layoutedUngroupedNodes];
              } else {
                finalNodes = [...groupNodes, ...newNodes];
              }

              // Trigger sidebar refresh to update groups
              triggerSidebarRefresh();
            } else {
              // No groups - just apply auto-layout if enabled
              if (autoLayoutEnabled) {
                finalNodes = getLayoutedElements(newNodes, newEdges, {
                  direction: layoutDirection
                });
              } else {
                finalNodes = newNodes;
              }
            }
          } catch (error) {
            console.error('Error loading groups:', error);
            // Fall back to auto-layout
            if (autoLayoutEnabled) {
              finalNodes = getLayoutedElements(newNodes, newEdges, {
                direction: layoutDirection
              });
            } else {
              finalNodes = newNodes;
            }
          }

          // Fit view after a short delay to ensure nodes are rendered
          setTimeout(() => {
            fitView({ padding: 0.2, duration: 400 });
          }, 50);
        }

        setNodes(finalNodes);
        setEdges(newEdges);

        console.log('Loaded classes for version:', selectedVersionId, 'Classes:', classesWithProperties.length, savedLayout ? '(with saved layout)' : '');
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
  }, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, autoLayoutEnabled, setNodes, setEdges, fitView, projects, versions, currentUserId, setGroups, setViewport, projectTags, isReadOnly, triggerSidebarRefresh]);

  // Generate specs on-demand when switching views or when canvas changes
  useEffect(() => {
    const generateSpec = async () => {
      if (!selectedVersionId) return;

      try {
        // Convert current nodes to classes format
        const classesWithProperties = nodes.map(node => ({
          id: node.id,
          name: (node.data as any).name,
          description: (node.data as any).description,
          properties: (node.data as any).properties || [],
          schema: (node.data as any).schema,
          tags: (node.data as any).tags || []
        }));

        // Get current project and version for metadata
        const currentProject = projects.find(p => p.id === selectedProjectId);
        const currentVersion = versions.find(v => v.id === selectedVersionId);

        if (viewMode === 'code') {
          // Generate only the selected spec format
          if (codeDisplayFormat === 'openapi') {
            const spec = await generateOpenApiSpec(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id,
              metadata: (currentProject as any)?.metadata
            });
            setOpenApiSpec(spec);
            console.log('Generated OpenAPI spec');
          } else if (codeDisplayFormat === 'arazzo') {
            const arazzoSpecContent = await generateArazzoSpec(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id,
              metadata: (currentProject as any)?.metadata
            });
            setArazzoSpec(arazzoSpecContent);
            console.log('Generated Arazzo spec');
          } else if (codeDisplayFormat === 'jsonschema') {
            const jsonSchemaContent = generateJsonSchema(classesWithProperties, {
              projectName: currentProject?.name,
              version: currentVersion?.version_id,
              metadata: (currentProject as any)?.metadata
            });
            setJsonSchemaSpec(jsonSchemaContent);
            console.log('Generated JSON Schema');
          }
        }
      } catch (error) {
        console.error('Failed to generate content:', error);
      }
    };

    generateSpec();
  }, [viewMode, codeDisplayFormat, selectedVersionId, selectedProjectId, projects, versions, nodes]);

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

    // If click-to-focus is enabled, zoom to the clicked node
    if (clickToFocusEnabled) {
      zoomToClass(node.id);
    }
  }, [clickToFocusEnabled, zoomToClass]);

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
    <Tooltip.Provider>
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
          @keyframes shimmer {
            0% {
              background-position: 200% 0;
            }
            100% {
              background-position: -200% 0;
            }
          }
        `}</style>

      {/* Header with Project and Version Selectors - spans full width including over sidebar */}
      <div className="bg-gradient-to-r from-white via-slate-50 to-white dark:from-gray-800 dark:via-gray-800 dark:to-gray-800 border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-1.5 shadow-sm" style={{ position: 'fixed', top: 48, left: 0, right: 0, zIndex: 1000 }}>
        <div className="flex flex-wrap items-center gap-4 w-full">
          {/* Project Selector - Radix UI Select */}
          <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
            <Select.Root
              value={selectedProjectId}
              onValueChange={(value) => {
                setSelectedProjectId(value);
                setContextProjectId(value);
                setSelectedVersionId('');
                setContextVersionId('');
                setIsReadOnly(false);
                setViewMode('canvas');
                if (value) {
                  loadProjectTags(value);
                } else {
                  setProjectTags([]);
                }
              }}
              disabled={isLoadingProjects || !currentTenantId}
            >
              <Select.Trigger className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed">
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                <Select.Value placeholder="Select project..." />
                <Select.Icon className="ml-auto">
                  <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]" position="popper" sideOffset={5}>
                  <Select.Viewport className="p-1">
                    {projects.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No projects available</div>
                    ) : (
                      projects.map((project) => (
                        <Select.Item
                          key={project.id}
                          value={project.id}
                          className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30"
                        >
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                          <Select.ItemText>{project.name}</Select.ItemText>
                        </Select.Item>
                      ))
                    )}
                  </Select.Viewport>
                </Select.Content>
              </Select.Portal>
            </Select.Root>
          </div>

          {/* Version Selector - Radix UI Select */}
          <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
            <Select.Root
              value={selectedVersionId}
              onValueChange={(value) => {
                setSelectedVersionId(value);
                setContextVersionId(value);
                const version = versions.find(v => v.id === value);
                setIsReadOnly(version?.published ?? false);
                setViewMode('canvas');
              }}
              disabled={isLoadingVersions || !selectedProjectId || versions.length === 0}
            >
              <Select.Trigger className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed">
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
                <Select.Value placeholder="Select version..." />
                <Select.Icon className="ml-auto">
                  <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]" position="popper" sideOffset={5}>
                  <Select.Viewport className="p-1">
                    {versions.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No versions available</div>
                    ) : (
                      versions.map((version) => (
                        <Select.Item
                          key={version.id}
                          value={version.id}
                          className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30"
                        >
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                          <Select.ItemText>
                            {version.published ? '🔒 ' : ''}{version.version_id} - {version.description}
                          </Select.ItemText>
                        </Select.Item>
                      ))
                    )}
                  </Select.Viewport>
                </Select.Content>
              </Select.Portal>
            </Select.Root>
          </div>

          {/* View Switcher - Radix UI ToggleGroup */}
          {selectedProjectId && selectedVersionId && (
            <>
              {/* Separator */}
              <div className="h-6 w-px bg-gray-200 dark:bg-gray-600" />

              <ToggleGroup.Root
                type="single"
                value={viewMode}
                onValueChange={(value) => {
                  if (value) setViewMode(value as ViewMode);
                }}
                className="inline-flex bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1 shadow-inner"
              >
                <ToggleGroup.Item
                  value="canvas"
                  className="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                  </svg>
                  Canvas
                </ToggleGroup.Item>
                <ToggleGroup.Item
                  value="code"
                  className="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                  Code
                </ToggleGroup.Item>
              </ToggleGroup.Root>

              {/* Manage Tags Button */}
              <button
                onClick={() => setTagManagerOpen(true)}
                className="px-3 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center gap-2 shadow-sm hover:shadow-md"
                title="Manage project tags"
              >
                <svg className="w-4 h-4 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
                <span>Tags</span>
              </button>

              {/* Settings Dropdown - Radix UI DropdownMenu */}
              <div className="ml-auto">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger asChild>
                    <button
                      className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center justify-center shadow-sm hover:shadow-md"
                      title="Settings"
                      aria-label="Settings"
                    >
                      <Settings className="w-4 h-4" />
                    </button>
                  </DropdownMenu.Trigger>

                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      className="min-w-[180px] bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-1 z-[9999]"
                      sideOffset={5}
                      align="end"
                    >
                      {/* Theme Toggle */}
                      <DropdownMenu.Item
                        className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                        onSelect={() => toggleTheme()}
                      >
                        {isDark ? (
                          <>
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                            </svg>
                            <span>Light Mode</span>
                          </>
                        ) : (
                          <>
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                            </svg>
                            <span>Dark Mode</span>
                          </>
                        )}
                      </DropdownMenu.Item>

                      <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                      {/* Click-to-Focus Toggle */}
                      <DropdownMenu.Item
                        className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                        onSelect={() => toggleClickToFocus()}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                        <span className="flex-1">Click-to-Focus</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                          {clickToFocusEnabled ? 'ON' : 'OFF'}
                        </span>
                      </DropdownMenu.Item>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Canvas/Code Area - with top padding for fixed header */}
      <div className="flex-1 bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800 overflow-hidden relative">
        {!selectedProjectId || !selectedVersionId ? (
          // Empty state when no project/version selected
          <div className="h-full flex items-center justify-center">
            <div className="relative">
              {/* Decorative background elements */}
              <div className="absolute -top-20 -left-20 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
              <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-gradient-to-br from-blue-100 to-cyan-100 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />

              <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-12 md:p-16 text-center shadow-xl shadow-gray-200/50 dark:shadow-gray-900/50">
                <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
                  <svg
                    className="h-10 w-10 text-white"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                </div>
                <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">
                  No Project Selected
                </h3>
                <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto leading-relaxed">
                  Select a project and version from the dropdowns above to view and edit your class diagram
                </p>

                {/* Quick tip */}
                <div className="mt-8 pt-6 border-t border-gray-100 dark:border-gray-700/50">
                  <p className="text-xs text-gray-400 dark:text-gray-500 flex items-center justify-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Tip: Drag properties from the sidebar onto classes to add them
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : viewMode === 'canvas' ? (
          // React Flow Canvas View
          <>
            {/* Loading Progress Bar */}
            {isLoadingCanvas && (
              <div className="absolute top-0 left-0 right-0 z-50">
                <div className="h-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 animate-pulse" style={{
                  backgroundSize: '200% 100%',
                  animation: 'shimmer 2s ease-in-out infinite'
                }}>
                </div>
                <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm shadow-lg px-6 py-3 text-center border-b border-gray-100 dark:border-gray-700">
                  <div className="flex items-center justify-center gap-3">
                    <div className="relative">
                      <div className="w-5 h-5 border-2 border-indigo-200 dark:border-indigo-800 rounded-full"></div>
                      <div className="w-5 h-5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin absolute top-0 left-0"></div>
                    </div>
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
              onNodesChange={handleNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              onNodeDrag={handleNodeDrag}
              onNodeDragStop={handleNodeDragStop}
              onMove={(_, viewport) => setZoomLevel(viewport.zoom)}
              fitView
              attributionPosition="bottom-left"
              className={`${isDark ? 'bg-gray-900' : ''} ${isAnimating ? 'layout-animating' : ''}`}
              nodesDraggable={true}
              nodesConnectable={!isReadOnly}
              elementsSelectable={true}
              nodesFocusable={true}
              edgesFocusable={true}
              style={{
                background: isDark
                  ? 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)'
                  : 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #e2e8f0 100%)'
              }}
            >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1.5}
              color="currentColor"
              style={{
                color: 'rgb(99, 102, 241)',
                opacity: isDark ? 0.25 : 0.15
              }}
            />
            <Controls
              className="bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
              style={{
                borderRadius: '12px',
                overflow: 'hidden',
              }}
            />
            <MiniMap
              nodeStrokeColor={(node) => {
                if (node.type === 'input') return '#6366f1';
                if (node.type === 'output') return '#ec4899';
                return '#6366f1';
              }}
              nodeColor={(node) => {
                if (node.type === 'input') return '#e0e7ff';
                if (node.type === 'output') return '#fce7f3';
                return '#e0e7ff';
              }}
              className="dark:bg-gray-800 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
              maskColor="rgba(99, 102, 241, 0.1)"
              style={{
                borderRadius: '12px',
                border: '1px solid rgba(99, 102, 241, 0.2)',
              }}
            />

            {/* Read Only Indicator */}
            {isReadOnly && (
              <Panel position="top-left" className="bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-900/30 dark:to-yellow-900/30 text-amber-800 dark:text-amber-200 rounded-xl shadow-lg px-4 py-2 border border-amber-200/80 dark:border-amber-700/50 backdrop-blur-sm">
                <div className="flex items-center gap-2">
                  <div className="p-1 bg-amber-100 dark:bg-amber-800/50 rounded-lg">
                    <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 002 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <span className="text-xs font-semibold">Read Only Mode</span>
                </div>
              </Panel>
            )}

            {/* Expand/Collapse All Controls */}
            <Panel
              position="top-left"
              className={`bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 ${isReadOnly ? 'mt-14' : ''}`}
            >
              <div className="flex gap-1.5 p-1.5">
                <button
                  onClick={handleExpandAll}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                  title="Expand all properties"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                  <span>Expand</span>
                </button>
                <button
                  onClick={handleCollapseAll}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                  title="Collapse all properties"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                  </svg>
                  <span>Collapse</span>
                </button>
                {/* Group Selected Button */}
                {!isReadOnly && (
                  <button
                    onClick={handleCreateGroup}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-purple-50 dark:hover:bg-purple-900/30 hover:text-purple-600 dark:hover:text-purple-400 flex items-center gap-1.5 border border-transparent hover:border-purple-200 dark:hover:border-purple-700"
                    title="Group selected classes"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                    </svg>
                    <span>Group</span>
                  </button>
                )}
                {/* Manage Tags Button */}
                {!isReadOnly && (
                  <button
                    onClick={() => setTagManagerOpen(true)}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-amber-50 dark:hover:bg-amber-900/30 hover:text-amber-600 dark:hover:text-amber-400 flex items-center gap-1.5 border border-transparent hover:border-amber-200 dark:hover:border-amber-700"
                    title="Manage project tags"
                  >
                    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                    </svg>
                    <span>Tags</span>
                  </button>
                )}
              </div>
            </Panel>

            {/* Dangling $ref warning */}
            {(() => {
              const warn = hasDanglingRefs(nodes.map(n => ({ id: n.id, name: (n.data as any)?.name, properties: (n.data as any)?.properties })));
              return warn ? (
                <Panel position="top-left" className={`bg-gradient-to-r from-red-50 to-rose-50 dark:from-red-900/30 dark:to-rose-900/30 text-red-800 dark:text-red-200 rounded-xl shadow-lg px-4 py-2.5 border border-red-200/80 dark:border-red-700/50 backdrop-blur-sm ${isReadOnly ? 'mt-[8rem]' : 'mt-[4.5rem]'}`}>
                  <div className="flex items-center gap-2.5">
                    <div className="p-1 bg-red-100 dark:bg-red-800/50 rounded-lg">
                      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.72-1.36 3.485 0l6.518 11.6c.75 1.336-.213 3.001-1.742 3.001H3.48c-1.53 0-2.492-1.665-1.743-3.001l6.52-11.6zM11 13a1 1 0 10-2 0 1 1 0 002 0zm-1-2a1 1 0 01-1-1V8a1 1 0 112 0v2a1 1 0 01-1 1z" clipRule="evenodd"/>
                      </svg>
                    </div>
                    <span className="text-xs font-medium max-w-xs">Missing class references detected. Connect property handles to target classes to resolve.</span>
                  </div>
                </Panel>
              ) : null;
            })()}

            {/* Layout Control Button */}
            <Panel position="top-right" className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80" style={{ marginRight: '60px' }}>
              <div className="relative" ref={layoutDropdownRef}>
                <button
                  onClick={() => setLayoutDropdownOpen(!layoutDropdownOpen)}
                  className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md flex items-center gap-2"
                  title="Layout options"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {layoutDropdownOpen && (
                  <div className="absolute right-0 mt-2 w-80 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-[1002]">
                    <div className="py-1">
                      {/* Auto Layout Toggle */}
                      <div className="px-4 py-3 mb-1 border-b border-gray-100 dark:border-gray-700">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <svg className="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                            </svg>
                            <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                              Auto Layout
                            </span>
                          </div>
                          <Switch.Root
                            checked={autoLayoutEnabled}
                            onCheckedChange={setAutoLayoutEnabled}
                            className="w-11 h-6 bg-gray-200 dark:bg-gray-700 rounded-full relative data-[state=checked]:bg-indigo-600 transition-colors cursor-pointer"
                          >
                            <Switch.Thumb className="block w-5 h-5 bg-white rounded-full shadow-lg transition-transform duration-100 translate-x-0.5 will-change-transform data-[state=checked]:translate-x-[22px]" />
                          </Switch.Root>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
                          Automatically arrange nodes when adding or removing classes
                        </p>
                      </div>

                      {/* Save/Load Layout Buttons */}
                      <div className="px-4 py-3 mb-1 border-b border-gray-100 dark:border-gray-700">
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={handleSaveLayout}
                            disabled={autoLayoutEnabled || isReadOnly || layoutSaved}
                            className={`
                              px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2
                              ${layoutSaved
                                ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-700'
                                : !autoLayoutEnabled && !isReadOnly
                                ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 border border-indigo-200 dark:border-indigo-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                              }
                            `}
                            title={layoutSaved ? 'Layout saved!' : autoLayoutEnabled ? 'Disable auto-layout to save' : isReadOnly ? 'Cannot save in read-only mode' : 'Save current layout'}
                          >
                            {layoutSaved ? (
                              <>
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                                <span>Saved</span>
                              </>
                            ) : (
                              <>
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                                </svg>
                                <span>Save</span>
                              </>
                            )}
                          </button>
                          <button
                            onClick={handleLoadLayout}
                            disabled={autoLayoutEnabled}
                            className={`
                              px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2
                              ${!autoLayoutEnabled
                                ? 'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/50 border border-purple-200 dark:border-purple-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                              }
                            `}
                            title={autoLayoutEnabled ? 'Disable auto-layout to load' : 'Load saved layout'}
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                            </svg>
                            <span>Load</span>
                          </button>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                          {autoLayoutEnabled
                            ? 'Turn off auto-layout to save or load custom layouts'
                            : 'Save or load your canvas layout per version'
                          }
                        </p>
                      </div>

                      {/* Layout Algorithms Header */}
                      <div className="px-4 pt-2 pb-1">
                        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Layout Algorithms
                        </h4>
                      </div>

                      {/* Hierarchical Layouts */}
                      <div className="px-3 py-1">
                        <div className="px-2 py-1.5">
                          <span className="text-xs font-medium text-gray-400 dark:text-gray-500">Hierarchical</span>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('hierarchical-tb');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'hierarchical-tb' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">↓</span>
                              <div className="font-medium text-xs">Top to Bottom</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('hierarchical-lr');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'hierarchical-lr' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">→</span>
                              <div className="font-medium text-xs">Left to Right</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('hierarchical-bt');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'hierarchical-bt' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">↑</span>
                              <div className="font-medium text-xs">Bottom to Top</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('hierarchical-rl');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'hierarchical-rl' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">←</span>
                              <div className="font-medium text-xs">Right to Left</div>
                            </div>
                          </button>
                        </div>

                        {/* Other Layouts */}
                        <div className="px-2 py-1.5 mt-2">
                          <span className="text-xs font-medium text-gray-400 dark:text-gray-500">Other</span>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('force-directed');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'force-directed' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">🔄</span>
                              <div className="font-medium text-xs">Force-Directed</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('circular');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'circular' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">⭕</span>
                              <div className="font-medium text-xs">Circular</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('grid');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'grid' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">⊞</span>
                              <div className="font-medium text-xs">Grid</div>
                            </div>
                          </button>
                          <button
                            onClick={() => {
                              onLayoutAlgorithm('layered');
                              setLayoutDropdownOpen(false);
                            }}
                            className={`text-left px-3 py-3 rounded-lg transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 ${layoutAlgorithm === 'layered' ? 'bg-indigo-50 dark:bg-indigo-900/30' : ''}`}
                          >
                            <div className="flex flex-col items-center text-center gap-2">
                              <span className="text-2xl">📚</span>
                              <div className="font-medium text-xs">Layered</div>
                            </div>
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Panel>

            {/* Export Button Panel */}
            <Panel
              position="top-right"
              className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80"
            >
              <div className="relative" ref={exportDropdownRef}>
                <button
                  onClick={() => setExportDropdownOpen(!exportDropdownOpen)}
                  className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md"
                  title="Export canvas"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {exportDropdownOpen && (
                  <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[1002]">
                    <div className="py-1">
                      <div className="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Export Canvas
                      </div>
                      <button
                        onClick={handleExportPng}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        <span>PNG Image</span>
                      </button>
                      <button
                        onClick={handleExportJpeg}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        <span>JPEG Image</span>
                      </button>
                      <button
                        onClick={handleExportSvg}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                        </svg>
                        <span>SVG Image</span>
                      </button>
                      <button
                        onClick={handleExportPdf}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span>PDF Document</span>
                      </button>
                      <button
                        onClick={handleExportJson}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 3v6a1 1 0 001 1h6" />
                        </svg>
                        <span>JSON Data</span>
                      </button>
                      <div className="border-t border-gray-200 dark:border-gray-700 my-1"></div>
                      <button
                        onClick={handleExportMermaid}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        <span>Mermaid Diagram</span>
                      </button>
                      <button
                        onClick={handleExportPlantUml}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                        </svg>
                        <span>PlantUML Diagram</span>
                      </button>
                      <button
                        onClick={handleExportGraphMl}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                        </svg>
                        <span>GraphML Graph</span>
                      </button>
                      <button
                        onClick={handleExportDot}
                        className="w-full px-4 py-2 text-sm text-left text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-3 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        <span>DOT (GraphViz)</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          </ReactFlow>
          </>
        ) : viewMode === 'code' ? (
          // Monaco Editor Code View - OpenAPI 3.1.0 Specification
          <div className="h-full flex flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
            <div className="bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-5">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl shadow-lg shadow-indigo-500/25">
                      <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">
                        {codeDisplayFormat === 'openapi'
                          ? 'OpenAPI 3.1.0'
                          : codeDisplayFormat === 'arazzo'
                          ? 'Arazzo v1.0.1'
                          : 'JSON Schema'}
                      </h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {selectedProject?.name} • v{selectedVersion?.version_id}
                      </p>
                    </div>
                  </div>

                  {/* Display Format Selector */}
                  <div className="flex items-center gap-3 pl-5 border-l border-gray-200 dark:border-gray-700">
                    <Select.Root value={codeDisplayFormat} onValueChange={(value) => setCodeDisplayFormat(value as 'openapi' | 'arazzo' | 'jsonschema')}>
                      <Select.Trigger className="inline-flex items-center justify-between gap-2 px-3 py-2 text-sm font-medium border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 min-w-[200px]">
                        <Select.Value />
                        <Select.Icon>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </Select.Icon>
                      </Select.Trigger>
                      <Select.Portal>
                        <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]">
                          <Select.Viewport className="p-1">
                            <Select.Item value="openapi" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30">
                              <Select.ItemText>OpenAPI Specification</Select.ItemText>
                              <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                                <svg className="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                              </Select.ItemIndicator>
                            </Select.Item>
                            <Select.Item value="arazzo" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30">
                              <Select.ItemText>Arazzo Specification</Select.ItemText>
                              <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                                <svg className="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                              </Select.ItemIndicator>
                            </Select.Item>
                            <Select.Item value="jsonschema" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[state=checked]:bg-indigo-50 dark:data-[state=checked]:bg-indigo-900/30">
                              <Select.ItemText>JSON Schema</Select.ItemText>
                              <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                                <svg className="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                              </Select.ItemIndicator>
                            </Select.Item>
                          </Select.Viewport>
                        </Select.Content>
                      </Select.Portal>
                    </Select.Root>

                    {/* Format Toggle (JSON/YAML) */}
                    <ToggleGroup.Root
                      type="single"
                      value={codeFormat}
                      onValueChange={(value) => {
                        if (value) setCodeFormat(value as 'json' | 'yaml');
                      }}
                      className="inline-flex items-center bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1"
                    >
                      <ToggleGroup.Item
                        value="json"
                        className="px-3 py-2 text-xs font-semibold rounded-md transition-all duration-200 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm data-[state=off]:text-gray-600 dark:data-[state=off]:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                      >
                        JSON
                      </ToggleGroup.Item>
                      <ToggleGroup.Item
                        value="yaml"
                        className="px-3 py-2 text-xs font-semibold rounded-md transition-all duration-200 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm data-[state=off]:text-gray-600 dark:data-[state=off]:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                      >
                        YAML
                      </ToggleGroup.Item>
                    </ToggleGroup.Root>
                  </div>
                </div>

                <div className="flex gap-2">
                  <>
                    <Tooltip.Root>
                      <Tooltip.Trigger asChild>
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
                          className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
                            codeCopied
                              ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                        >
                          {codeCopied ? <Check size={16} /> : <Copy size={16} />}
                          {codeCopied ? 'Copied!' : 'Copy'}
                        </button>
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content
                          className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                          sideOffset={5}
                        >
                          {codeCopied ? 'Copied to clipboard!' : 'Copy to clipboard'}
                          <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>

                    <Tooltip.Root>
                      <Tooltip.Trigger asChild>
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
                          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-lg transition-all duration-200 shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40"
                        >
                          <Download size={16} />
                          Export
                        </button>
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content
                          className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                          sideOffset={5}
                        >
                          Download as {codeFormat.toUpperCase()} file
                          <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
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
        projectMetadata={(projects.find(p => p.id === selectedProjectId) as any)?.metadata}
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
    </Tooltip.Provider>
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

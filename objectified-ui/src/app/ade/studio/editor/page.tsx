'use client';

import { useCallback, useState, useEffect, useRef, useMemo, type ChangeEvent, type SetStateAction } from 'react';
import { useSession } from 'next-auth/react';
import { useSearchParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { useStudio } from '../StudioContext';
import {
  Copy,
  Download,
  Check,
  Settings,
  Building2,
  ChevronRight,
  Folder,
  ChevronDown,
  Tag,
  Layout,
  Code2,
  Sun,
  Moon,
  Eye,
  FileText,
  Info,
  Move,
  Lock,
  SeparatorHorizontal,
  SeparatorVertical,
  AlertTriangle,
  Save,
  Upload,
  ChevronUp,
  Wand2,
  Image,
  FileCode,
  FileJson,
  BarChart3,
  Network,
  Zap,
  MoveVertical,
  MoveHorizontal,
  Search,
  X,
  Focus,
  Plus,
  Minus,
  RotateCcw,
  Activity,
  History,
  Trash2,
  Bookmark,
  Users,
  Filter,
  SlidersHorizontal,
  ArrowUp,
  ArrowDown,
  Route,
  BoxSelect,
  Braces,
  Ban,
  Ghost,
  Undo2,
  TrendingUp,
  Presentation,
  PanelLeft,
} from 'lucide-react';
import * as Select from '@radix-ui/react-select';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Collapsible from '@radix-ui/react-collapsible';
import YAML from 'yaml';
import ClassPropertyEditDialog from '../../../components/ade/studio/ClassPropertyEditDialog';
import ReferenceDialog from '../../../components/ade/studio/ReferenceDialog';
import TagManager from '../../../components/ade/studio/TagManager';
import ClassEditDialog from '../../../components/ade/studio/ClassEditDialog';
import ExportWizard from '../../../components/ade/studio/ExportWizard';
import { generateOpenApiSpec } from '@/app/utils/openapi';
import { generateArazzoSpec } from '@/app/utils/arazzo';
import { generateJsonSchema } from '@/app/utils/jsonschema';
import { useDialog } from '@/app/components/providers/DialogProvider';
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
  SelectionMode,
  type Connection,
  type Edge,
  type Node,
  useReactFlow,
  useUpdateNodeInternals,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  updateClassPropertyRef,
  getTagsForProject,
  saveDefaultCanvasLayout,
  getNamedCanvasLayout,
  getNamedCanvasLayoutsForVersion,
  getEffectiveDefaultLayoutName,
  setUserCanvasLayoutDefaultName,
  clearUserCanvasLayoutDefaultName,
  setTenantCanvasLayoutDefaultName,
  clearTenantCanvasLayoutDefaultName,
  saveNamedCanvasLayout,
  listCanvasLayoutRevisions,
  restoreCanvasLayoutFromRevision,
  getGroupsForVersion,
  getClassIdsForVersion,
  syncGroupsForVersion,
  addClassToGroup,
  updateClassPositionInGroup,
  isTenantAdmin,
  duplicateClassesInGroup,
  bulkApplyEditsToGroupClasses,
} from '../../../../../lib/db/helper';
import { expandClassesForGroupExport, downloadTextFile } from '@/app/utils/group-schema-export';
import { mapEdgesForLayoutSave, mapNodesForLayoutSave } from '../lib/canvasLayoutPayload';
import {
  deleteClassWithSession,
  updateClassCanvasMetadataWithSession,
  getClassesWithPropertiesAndTagsWithSession,
  getClassWithPropertiesAndTagsWithSession
} from '../../../../../lib/api/rest-client';
import ClassNode from '../../../components/ade/studio/ClassNode';
import EdgeWithWideHit from '../../../components/ade/studio/EdgeWithWideHit';
import GroupNode, { GROUP_COLORS } from '../../../components/ade/studio/GroupNode';
import SmartEdge from '../../../components/ade/studio/SmartEdge';
import { applyAutoLayout } from '@/app/utils/canvas-auto-layout';
import { getCanvasBackgroundStyle } from '@/app/utils/canvas-background-style';
import { applyEdgeStyling } from '@/app/utils/edge-styling';
import { computeCanvasSuggestions } from '@/app/utils/canvas-suggestions';
import { getVisibleNodeIdsForIsolateSelection } from '@/app/utils/canvas-node-visibility';
import {
  hasActiveCanvasVisibilityRestrictions,
  computeClassIdsPassingHideCriteria,
  groupNodeIdIsVisible,
} from '@/app/utils/canvas-display-visibility';
import {
  collapsePrefsStorageKey,
  getClassIdsInCollapsedGroups,
  COLLAPSED_GROUP_FRAME_WIDTH,
  COLLAPSED_GROUP_FRAME_HEIGHT,
} from '@/app/utils/canvas-group-collapse';
import {
  MAX_CANVAS_GROUP_DEPTH,
  collectAllNodeIdsInGroupSubtree,
  collectDescendantGroupIds,
  collectSubtreeGroupIds,
  findInnermostGroupAtPosition,
  getGroupDepth,
  groupById,
  isStrictDescendantGroup,
  wouldNestExceedMaxDepth,
  type FlowLikeGroupNode,
} from '@/app/utils/canvas-nested-groups';
import {
  edgeBelongsOnCanvas,
  ghostEdgeClassName,
  ghostNodeClassName,
} from '@/app/utils/canvas-ghost-mode';
import { computeLayoutQuality } from '@/app/utils/layout-quality';
import {
  buildCanvasLayoutJsonDocument,
  parseCanvasLayoutJson,
  filterCanvasLayoutForTargetClasses,
  mergeSavedEdgeHandles,
} from '@/app/utils/canvas-layout-json';
import { computeSchemaMetrics, getCircularDependencyEdgeIds, getDependencyDepthMap, getAffectedClassIds, getUpstreamClassIds, getDependencyChainNodeAndEdgeIds } from '@/app/utils/schema-metrics';
import { toPng } from 'html-to-image';
import DraggablePanel from '../components/DraggablePanel';
import MemoryProfiler from '../components/MemoryProfiler';
import SchemaMetricsPanel from '../components/SchemaMetricsPanel';
import SchemaTimelinePanel from '../components/SchemaTimelinePanel';
import { useSearchHistory } from '../hooks/useSearchHistory';
import {
  loadPresentationBookmarks,
  savePresentationBookmarks,
  newPresentationBookmarkId,
  type CanvasPresentationBookmark,
} from './lib/canvas-presentation-bookmarks';
import { CanvasPresentationPanel, PresentationExitHint } from './components/CanvasPresentationPanel';

// Import extracted components
import { useExportFunctions } from './components';
import type { Project, Version, ViewMode } from './components/types';

// Dynamically import Monaco Editor with SSR disabled
const PRESENTATION_SAVE_DEBOUNCE_MS = 500;

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading editor...</div>
    </div>
  ),
});

const StudioContent = () => {
  const BUILTIN_LAYOUT_NAMES = useMemo(
    () => ['Development Layout', 'Presentation Layout', 'Logical Layout', 'Dependency Layout'],
    []
  );
  const { data: session } = useSession();
  const searchParams = useSearchParams();

  // Custom dark mode detection - prioritize localStorage, then fall back to system preference
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const initTheme = () => {
      const savedTheme = localStorage.getItem('theme');
      const html = document.documentElement;

      if (savedTheme === 'dark') {
        html.classList.add('dark');
        setIsDark(true);
      } else if (savedTheme === 'light') {
        html.classList.remove('dark');
        setIsDark(false);
      } else {
        // No saved preference - use system preference
        const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (systemPrefersDark) {
          html.classList.add('dark');
          setIsDark(true);
        } else {
          html.classList.remove('dark');
          setIsDark(false);
        }
      }
    };

    initTheme();

    // Listen for class changes (in case other components change the theme)
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });

    return () => {
      observer.disconnect();
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
    setToggleClassVisibilityFn,
    setHiddenClassIds,
    setCreateGroupFn,
    setCreateGroupAtPositionFn,
    clickToFocusEnabled,
    setClickToFocusEnabled: setContextClickToFocusEnabled,
    lodEnabled,
    edgeStyling,
    edgeRouting,
    edgeAnimation,
    gridSize,
    snapToGrid,
    gridStyle,
    showGrid,
    exportGridOverride,
    smartGuidesEnabled,
    setSmartGuidesEnabled,
    autoSaveLayoutEnabled,
    autoSaveLayoutIntervalSeconds,
    canvasBackground,
    groups,
    setGroups,
    addGroup,
    updateGroup,
    deleteGroup: deleteGroupFromContext,
    setDeleteAllClassesInGroupFn,
    setDeleteGroupFn,
    setSearchHistoryCount,
    setClearSearchHistoryFn,
    setCanvasPresentationMode,
  } = useStudio();

  // Toggle click-to-focus mode (defined after useStudio to access setContextClickToFocusEnabled)
  const toggleClickToFocus = useCallback(() => {
    const newValue = !clickToFocusEnabled;
    localStorage.setItem('clickToFocusEnabled', JSON.stringify(newValue));
    setContextClickToFocusEnabled(newValue);
    return newValue;
  }, [clickToFocusEnabled, setContextClickToFocusEnabled]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);

  // Use context values directly for project/version selection
  const selectedProjectId = contextProjectId || '';
  const selectedVersionId = contextVersionId || '';
  const setSelectedProjectId = setContextProjectId;
  const setSelectedVersionId = setContextVersionId;
  const [hiddenNodeIds, setHiddenNodeIdsState] = useState<Set<string>>(new Set());
  const getHiddenNodesStorageKey = useCallback((versionId: string) => `studio:hiddenNodes:${versionId}`, []);

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
  const sessionIsTenantAdmin = Boolean((session?.user as any)?.is_tenant_admin);
  const [effectiveIsTenantAdmin, setEffectiveIsTenantAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        if (sessionIsTenantAdmin) {
          if (!cancelled) setEffectiveIsTenantAdmin(true);
          return;
        }
        if (!currentTenantId) {
          if (!cancelled) setEffectiveIsTenantAdmin(false);
          return;
        }
        const res = await isTenantAdmin(currentTenantId);
        const response = JSON.parse(res);
        if (!cancelled) setEffectiveIsTenantAdmin(response.success && response.isAdmin);
      } catch {
        if (!cancelled) setEffectiveIsTenantAdmin(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [sessionIsTenantAdmin, currentTenantId]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isAnimating, setIsAnimating] = useState<boolean>(false);
  const { fitView, setCenter, getViewport, setViewport, getNodes, getEdges } = useReactFlow();
  const updateNodeInternals = useUpdateNodeInternals();

  // Zoom level state for level-of-detail rendering
  const [zoomLevel, setZoomLevel] = useState<number>(1);

  // Smart guides state for alignment assistance during drag
  const [guides, setGuides] = useState<{
    horizontal: Array<{ y: number; x1: number; x2: number }>;
    vertical: Array<{ x: number; y1: number; y2: number }>;
  }>({ horizontal: [], vertical: [] });

  // Selected nodes for spacing tools
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);

  // Focus mode: isolate selected classes and their immediate relationships (live from current selection)
  const [focusModeEnabled, setFocusModeEnabled] = useState(false);
  // #489: Focus degree (1 = selection + 1st-degree neighbors, 2 = + 2nd-degree, etc.); user can expand incrementally
  const [focusModeDegree, setFocusModeDegree] = useState(1);
  const FOCUS_MODE_MAX_DEGREE = 10;
  // #490: When set, focus mode shows only this group's members ("Focus on group")
  const [focusModeGroupId, setFocusModeGroupId] = useState<string | null>(null);
  // Inline hover expansion for "Focus on group" list (show groups inside dropdown on hover)

  // #488: Show only connected nodes (hide nodes with no edges)
  const [showOnlyConnectedNodes, setShowOnlyConnectedNodes] = useState(false);
  // #483: Additional hide criteria (persisted per version with showOnlyConnectedNodes)
  const [hideEmptyClasses, setHideEmptyClasses] = useState(false);
  const [hideDeprecatedClasses, setHideDeprecatedClasses] = useState(false);
  const [hiddenCanvasGroupIds, setHiddenCanvasGroupIds] = useState<Set<string>>(new Set());
  /** #484: Draw nodes hidden by filters/manual hide as semi-transparent instead of removing them. */
  const [nodeGhostsModeEnabled, setNodeGhostsModeEnabled] = useState(false);

  const getHideCriteriaStorageKey = useCallback((versionId: string) => `studio:canvasHideCriteria:${versionId}`, []);

  const toggleHiddenCanvasGroup = useCallback((groupId: string) => {
    setHiddenCanvasGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  // #154: Collapsed canvas groups — member classes hidden, compact frame; prefs per user + version
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(new Set());
  /** #155: Breadcrumb / drill path — innermost group id is last; empty = full canvas */
  const [nestedGroupDrillPath, setNestedGroupDrillPath] = useState<string[]>([]);

  useEffect(() => {
    setNestedGroupDrillPath([]);
  }, [selectedVersionId]);

  useEffect(() => {
    setNestedGroupDrillPath((prev) => {
      if (prev.length === 0) return prev;
      const idSet = new Set(groups.map((g) => g.id));
      let cut = prev.length;
      for (let i = 0; i < prev.length; i++) {
        if (!idSet.has(prev[i])) {
          cut = i;
          break;
        }
      }
      const next = prev.slice(0, cut);
      return next.length === prev.length ? prev : next;
    });
  }, [groups]);

  useEffect(() => {
    if (!currentUserId || !selectedVersionId) {
      setCollapsedGroupIds(new Set());
      return;
    }
    try {
      const raw = localStorage.getItem(collapsePrefsStorageKey(currentUserId, selectedVersionId));
      setCollapsedGroupIds(raw ? new Set(JSON.parse(raw) as string[]) : new Set());
    } catch {
      setCollapsedGroupIds(new Set());
    }
  }, [currentUserId, selectedVersionId]);

  const persistCollapsedGroupIds = useCallback(
    (next: Set<string>) => {
      if (!currentUserId || !selectedVersionId) return;
      try {
        localStorage.setItem(
          collapsePrefsStorageKey(currentUserId, selectedVersionId),
          JSON.stringify([...next])
        );
      } catch {
        /* ignore quota / private mode */
      }
    },
    [currentUserId, selectedVersionId]
  );

  const toggleGroupCollapsed = useCallback(
    (groupId: string) => {
      setCollapsedGroupIds((prev) => {
        const next = new Set(prev);
        if (next.has(groupId)) next.delete(groupId);
        else next.add(groupId);
        persistCollapsedGroupIds(next);
        return next;
      });
    },
    [persistCollapsedGroupIds]
  );

  const collapseAllCanvasGroups = useCallback(() => {
    if (groups.length === 0) return;
    const next = new Set(groups.map((g) => g.id));
    setCollapsedGroupIds(next);
    persistCollapsedGroupIds(next);
  }, [groups, persistCollapsedGroupIds]);

  const expandAllCanvasGroups = useCallback(() => {
    const next = new Set<string>();
    setCollapsedGroupIds(next);
    persistCollapsedGroupIds(next);
  }, [persistCollapsedGroupIds]);

  const toggleGroupCollapsedRef = useRef<(id: string) => void>(() => {});
  toggleGroupCollapsedRef.current = toggleGroupCollapsed;
  const collapseAllCanvasGroupsRef = useRef<() => void>(() => {});
  const expandAllCanvasGroupsRef = useRef<() => void>(() => {});
  collapseAllCanvasGroupsRef.current = collapseAllCanvasGroups;
  expandAllCanvasGroupsRef.current = expandAllCanvasGroups;

  /** Avoid clobbering localStorage on hydrate: save effect runs after load in the same tick. */
  const skipNextHideCriteriaPersistRef = useRef(false);

  // #482: Hide all class nodes except the current selection (and group frames that contain them)
  const [isolateSelectionEnabled, setIsolateSelectionEnabled] = useState(false);

  const canvasVisibilityRestricted = useMemo(
    () =>
      hasActiveCanvasVisibilityRestrictions({
        manualHiddenNodeCount: hiddenNodeIds.size,
        hideEmptyClasses,
        hideUnconnectedClasses: showOnlyConnectedNodes,
        hideDeprecatedClasses,
        hiddenGroupIdsCount: hiddenCanvasGroupIds.size,
        nodeGhostsModeEnabled,
        isolateSelectionEnabled,
        focusModeEnabled,
      }),
    [
      hiddenNodeIds,
      hideEmptyClasses,
      showOnlyConnectedNodes,
      hideDeprecatedClasses,
      hiddenCanvasGroupIds,
      nodeGhostsModeEnabled,
      isolateSelectionEnabled,
      focusModeEnabled,
    ]
  );

  // Spacing indicators state
  const [spacingIndicators, setSpacingIndicators] = useState<{
    horizontal: Array<{ x1: number; x2: number; y: number; distance: number }>;
    vertical: Array<{ y1: number; y2: number; x: number; distance: number }>;
  }>({ horizontal: [], vertical: [] });

  // Show spacing indicators toggle
  const [showSpacingIndicators, setShowSpacingIndicators] = useState(false);

  // #349: Edge hover – tooltip and highlighting
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const [edgeTooltipPosition, setEdgeTooltipPosition] = useState<{ x: number; y: number } | null>(null);

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
  const [hasExistingLayout, setHasExistingLayout] = useState(false);
  const [selectedLayoutName, setSelectedLayoutName] = useState('Development Layout');
  const [availableLayoutNames, setAvailableLayoutNames] = useState<string[]>(BUILTIN_LAYOUT_NAMES);
  /** Data URLs for saved layout snapshots keyed by trimmed layout name */
  const [namedLayoutSnapshotDataUrls, setNamedLayoutSnapshotDataUrls] = useState<Record<string, string>>({});
  const canvasCaptureAreaRef = useRef<HTMLDivElement>(null);
  const presentationShellRef = useRef<HTMLDivElement>(null);
  const selectedLayoutNameRef = useRef(selectedLayoutName);
  const [autoSavePending, setAutoSavePending] = useState(false);
  const autoSaveInFlightRef = useRef(false);

  // Track whether this is the first load for a given version (to apply saved layout only once)
  const initialLayoutAppliedRef = useRef<string | null>(null);

  useEffect(() => {
    selectedLayoutNameRef.current = selectedLayoutName;
  }, [selectedLayoutName]);

  useEffect(() => {
    setAutoSavePending(false);
  }, [selectedVersionId]);

  // Export wizard state
  const [exportWizardOpen, setExportWizardOpen] = useState(false);
  const [layoutDropdownOpen, setLayoutDropdownOpen] = useState(false);
  const layoutDropdownRef = useRef<HTMLDivElement>(null);
  const layoutJsonImportInputRef = useRef<HTMLInputElement>(null);
  const [layoutHistoryOpen, setLayoutHistoryOpen] = useState(false);
  const [layoutHistoryRevisions, setLayoutHistoryRevisions] = useState<
    Array<{ id: string; revision: number; created_at: string }>
  >([]);
  const [layoutHistoryLoading, setLayoutHistoryLoading] = useState(false);

  // #517: Canvas presentation — fullscreen slideshow of viewport bookmarks, speaker notes, timer
  const [canvasPresentationActive, setCanvasPresentationActive] = useState(false);
  const [presentationBookmarks, setPresentationBookmarks] = useState<CanvasPresentationBookmark[]>([]);
  const [presentationSlideIndex, setPresentationSlideIndex] = useState(0);
  const [presentationShowSpeakerNotes, setPresentationShowSpeakerNotes] = useState(true);
  const [presentationTimerStartMs, setPresentationTimerStartMs] = useState<number | null>(null);
  const [presentationTimerTick, setPresentationTimerTick] = useState(0);
  const [presentationHintVisible, setPresentationHintVisible] = useState(false);

  // #471: Preview layout suggestions before applying
  const [layoutPreviewNodes, setLayoutPreviewNodes] = useState<Node[] | null>(null);
  const [layoutPreviewLabel, setLayoutPreviewLabel] = useState<string>('');

  /** Latest canvas state for auto-save; avoids resetting the interval on every node/edge update (#315). */
  const nodesForAutoSaveRef = useRef(nodes);
  const edgesForAutoSaveRef = useRef(edges);
  const groupsForAutoSaveRef = useRef(groups);
  const autoSavePendingRef = useRef(autoSavePending);
  const layoutPreviewNodesForAutoSaveRef = useRef(layoutPreviewNodes);

  useEffect(() => {
    nodesForAutoSaveRef.current = nodes;
    edgesForAutoSaveRef.current = edges;
    groupsForAutoSaveRef.current = groups;
    autoSavePendingRef.current = autoSavePending;
    layoutPreviewNodesForAutoSaveRef.current = layoutPreviewNodes;
  }, [nodes, edges, groups, autoSavePending, layoutPreviewNodes]);

  // Canvas search state
  const [canvasSearchQuery, setCanvasSearchQuery] = useState('');
  const [canvasSearchOpen, setCanvasSearchOpen] = useState(false);
  const [canvasToolsDrawerOpen, setCanvasToolsDrawerOpen] = useState(false);
  const [canvasSearchUseRegex, setCanvasSearchUseRegex] = useState(false);
  const [searchHistoryOpen, setSearchHistoryOpen] = useState(false);
  const [searchFiltersOpen, setSearchFiltersOpen] = useState(false);
  const canvasSearchInputRef = useRef<HTMLInputElement>(null);
  const searchHistoryRef = useRef<HTMLDivElement>(null);
  const searchFiltersRef = useRef<HTMLDivElement>(null);

  // Search filter state
  type SearchFilterType = 'all' | 'class' | 'allOf' | 'oneOf' | 'anyOf';
  const [searchFilterType, setSearchFilterType] = useState<SearchFilterType>('all');
  const [searchFilterGroup, setSearchFilterGroup] = useState<string>('all'); // 'all' or group id
  const [searchFilterHasProperties, setSearchFilterHasProperties] = useState<'all' | 'with' | 'without'>('all');
  const [searchFilterPropertyName, setSearchFilterPropertyName] = useState('');

  // Search history hook
  const { history: searchHistory, addToHistory, removeFromHistory, clearHistory: clearSearchHistory } = useSearchHistory();

  // Sync search history with context so StudioHeader can access it
  useEffect(() => {
    setSearchHistoryCount(searchHistory.length);
  }, [searchHistory.length, setSearchHistoryCount]);

  useEffect(() => {
    setClearSearchHistoryFn(() => clearSearchHistory);
    return () => setClearSearchHistoryFn(null);
  }, [clearSearchHistory, setClearSearchHistoryFn]);

  // Memory profiler state
  const [memoryProfilerOpen, setMemoryProfilerOpen] = useState(false);
  const [memoryProfilerMinimized, setMemoryProfilerMinimized] = useState(false);
  const [schemaMetricsOpen, setSchemaMetricsOpen] = useState(false);
  const [schemaMetricsMinimized, setSchemaMetricsMinimized] = useState(false);
  const [schemaTimelineOpen, setSchemaTimelineOpen] = useState(false);
  const [schemaTimelineMinimized, setSchemaTimelineMinimized] = useState(false);

  // #547: Interactive dependency graph overlay – highlight $ref / allOf/anyOf/oneOf edges, dim the rest
  const [showDependencyOverlay, setShowDependencyOverlay] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('showDependencyOverlay');
      return saved === 'true';
    }
    return false;
  });
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('showDependencyOverlay', String(showDependencyOverlay));
  }, [showDependencyOverlay]);

  // #550: Impact Analysis mode – show all affected classes when one is changed
  const [impactAnalysisMode, setImpactAnalysisMode] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('impactAnalysisMode');
      return saved === 'true';
    }
    return false;
  });
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('impactAnalysisMode', String(impactAnalysisMode));
  }, [impactAnalysisMode]);

  // #551: Upstream/downstream dependency view; #552: 'path' = trace full chain
  const [dependencyView, setDependencyView] = useState<'all' | 'upstream' | 'downstream' | 'path'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('dependencyView');
      if (saved === 'upstream' || saved === 'downstream' || saved === 'path') return saved;
    }
    return 'all';
  });
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('dependencyView', dependencyView);
  }, [dependencyView]);

  // Classify dependency edges (property $ref and schema/property allOf/anyOf/oneOf)
  const isDependencyEdge = useCallback((edge: Edge) => {
    const id = edge.id || '';
    return /^(prop-|allOf-|anyOf-|oneOf-)/.test(id);
  }, []);
  const dependencyEdgeIds = useMemo(() => new Set(edges.filter(isDependencyEdge).map(e => e.id)), [edges, isDependencyEdge]);
  const nodesWithDependencyIds = useMemo(() => {
    const set = new Set<string>();
    edges.forEach(e => {
      if (isDependencyEdge(e)) {
        set.add(e.source);
        set.add(e.target);
      }
    });
    return set;
  }, [edges, isDependencyEdge]);

  // Schema metrics (for Schema Metrics panel #472)
  const schemaMetrics = useMemo(() => {
    const classNodes = nodes.filter((n) => n.type !== 'groupNode');
    if (classNodes.length === 0) return null;
    return computeSchemaMetrics(nodes, edges);
  }, [nodes, edges]);

  // #548: Circular dependency node/edge sets for canvas warning indicators
  const circularNodeIdsSet = useMemo(
    () => new Set(schemaMetrics?.circularDependencyNodeIds ?? []),
    [schemaMetrics?.circularDependencyNodeIds]
  );
  const circularEdgeIds = useMemo(() => getCircularDependencyEdgeIds(nodes, edges), [nodes, edges]);

  // #549: Dependency depth (1st, 2nd, 3rd degree from leaves) for overlay badge
  const dependencyEdges = useMemo(
    () => edges.filter(isDependencyEdge),
    [edges, isDependencyEdge]
  );
  const dependencyDepthMap = useMemo(
    () => getDependencyDepthMap(nodes, dependencyEdges),
    [nodes, dependencyEdges]
  );

  // #550: Affected class IDs when one class is selected in Impact Analysis mode
  const impactAnalysisSourceId = impactAnalysisMode && selectedNodeIds.length === 1 ? selectedNodeIds[0]! : null;
  const affectedClassIds = useMemo(() => {
    if (!impactAnalysisSourceId) return null;
    return getAffectedClassIds(impactAnalysisSourceId, nodes, dependencyEdges);
  }, [impactAnalysisSourceId, nodes, dependencyEdges]);

  // #551: Focal node for upstream/downstream view; #552: also for path (trace full chain)
  const dependencyFocalNodeId = showDependencyOverlay && (dependencyView === 'upstream' || dependencyView === 'downstream' || dependencyView === 'path') && selectedNodeIds.length === 1 ? selectedNodeIds[0]! : null;
  const dependencyUpstreamIds = useMemo(() => {
    if (!dependencyFocalNodeId || dependencyView !== 'upstream') return null;
    return getUpstreamClassIds(dependencyFocalNodeId, nodes, dependencyEdges);
  }, [dependencyFocalNodeId, dependencyView, nodes, dependencyEdges]);
  const dependencyDownstreamIds = useMemo(() => {
    if (!dependencyFocalNodeId || dependencyView !== 'downstream') return null;
    return getAffectedClassIds(dependencyFocalNodeId, nodes, dependencyEdges);
  }, [dependencyFocalNodeId, dependencyView, nodes, dependencyEdges]);
  // #552: Full chain (path) node and edge sets when view is 'path'
  const dependencyPathChain = useMemo(() => {
    if (!dependencyFocalNodeId || dependencyView !== 'path') return null;
    return getDependencyChainNodeAndEdgeIds(dependencyFocalNodeId, nodes, dependencyEdges);
  }, [dependencyFocalNodeId, dependencyView, nodes, dependencyEdges]);

  // Layout quality (#473): edge crossings, spacing uniformity, symmetry, balance
  const layoutQuality = useMemo(() => {
    const classNodes = nodes.filter((n) => n.type !== 'groupNode');
    if (classNodes.length === 0) return null;
    return computeLayoutQuality(nodes, edges);
  }, [nodes, edges]);

  // Canvas improvement suggestions (#474)
  const groupMemberIds = useMemo(() => {
    if (!groups.length) return undefined;
    return new Set(groups.flatMap((g) => g.nodeIds));
  }, [groups]);
  const canvasSuggestions = useMemo(() => {
    return computeCanvasSuggestions({
      nodes,
      edges,
      metrics: schemaMetrics,
      layoutQuality,
      groupMemberIds,
    });
  }, [nodes, edges, schemaMetrics, layoutQuality, groupMemberIds]);

  // #559: Sync per-node relationship count from edges into class node data (for badges)
  useEffect(() => {
    const countByNodeId = new Map<string, number>();
    edges.forEach((e) => {
      countByNodeId.set(e.source, (countByNodeId.get(e.source) ?? 0) + 1);
      countByNodeId.set(e.target, (countByNodeId.get(e.target) ?? 0) + 1);
    });
    setNodes((current) =>
      current.map((n) => {
        if (n.type !== 'classNode') return n;
        const relationshipCount = countByNodeId.get(n.id) ?? 0;
        const existing = (n.data as any)?.relationshipCount;
        if (existing === relationshipCount) return n;
        return { ...n, data: { ...(n.data as any), relationshipCount } };
      })
    );
  }, [edges, setNodes]);

  // Create stable refs for callbacks to prevent unnecessary re-renders
  const handlePropertyDropRef = useRef<any>(null);
  const handlePropertyEditRef = useRef<any>(null);
  const handlePropertyDeleteRef = useRef<any>(null);
  const handleClassEditRef = useRef<any>(null);
  const handleClassDeleteRef = useRef<any>(null);
  const handleCreateReferenceRef = useRef<any>(null);
  const handleThemeChangeRef = useRef<any>(null);
  const handleTogglePropertyExpansionRef = useRef<any>(null);

  // Refs for group handlers - initialized here, values set later
  const handleGroupRenameRef = useRef<any>(null);
  const handleGroupDeleteRef = useRef<any>(null);
  const handleDeleteAllClassesInGroupRef = useRef<any>(null);
  const handleExportGroupSchemaRef = useRef<
    ((groupId: string, nodeIds: string[], groupName: string, format: 'json' | 'yaml') => Promise<void>) | null
  >(null);
  const handleDuplicateGroupRef = useRef<
    ((groupId: string, nodeIds: string[], groupName: string) => Promise<void>) | null
  >(null);
  const handleBulkEditGroupClassesRef = useRef<
    ((
      groupId: string,
      nodeIds: string[],
      groupName: string,
      options: {
        descriptionPrefix?: string;
        descriptionSuffix?: string;
        tagId?: string;
        topLevelPropertyReadOnly?: boolean;
      }
    ) => Promise<void>) | null
  >(null);
  const handleGroupColorChangeRef = useRef<any>(null);
  const handleGroupStyleChangeRef = useRef<any>(null);
  const handleGroupTagsChangeRef = useRef<any>(null);
  const handleDrillIntoNestedGroupRef = useRef<(groupId: string) => void>(() => {});

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

  // Handle theme changes for a class node
  const handleThemeChange = useCallback(async (classId: string, theme: any) => {
    try {
      // Read current metadata synchronously from React Flow (avoids stale state from setState)
      const currentNodes = getNodes();
      const currentNode = currentNodes.find((n) => n.id === classId);
      const currentMetadata = (currentNode?.data as any)?.canvas_metadata || {};

      // Update canvas_metadata with new theme (merge so position/dimensions/group are preserved)
      const updatedMetadata = {
        ...currentMetadata,
        style: theme
      };

      // Save to database via REST API
      const response = await updateClassCanvasMetadataWithSession(classId, updatedMetadata);

      if (response.success) {
        // Update local node data so the node re-renders with new theme (border, colors, etc.)
        setNodes((nodes) =>
          nodes.map((n) =>
            n.id === classId
              ? {
                  ...n,
                  data: {
                    ...(n.data as any),
                    theme: { ...theme },
                    canvas_metadata: updatedMetadata
                  }
                }
              : n
          )
        );

        setTimeout(() => updateNodeInternals(classId), 0);
      } else {
        console.error('Failed to update class theme:', response.error);
      }
    } catch (error) {
      console.error('Error updating class theme:', error);
    }
  }, [getNodes, setNodes, updateNodeInternals]);

  // Keep ref updated
  handleThemeChangeRef.current = handleThemeChange;

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
          lodEnabled,
          onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args),
          // Preserve theme - don't overwrite it
          theme: (node.data as any).theme,
        },
      }))
    );
  }, [globalExpandedProperties, isReadOnly, zoomLevel, lodEnabled]);

  // Handle expand all properties
  const handleExpandAll = useCallback(() => {
    setNodes((currentNodes) => {
      const allPropertyIds = new Set<string>();
      currentNodes.forEach((node) => {
        const properties = (node.data as any)?.properties || [];
        properties.forEach((prop: any) => {
          allPropertyIds.add(prop.id);
        });
      });
      setGlobalExpandedProperties(allPropertyIds);
      // Also reflect immediately into node data
      return currentNodes.map((n) => ({ ...n, data: { ...(n.data as any), expandedProperties: allPropertyIds } }));
    });
  }, []);

  // Handle collapse all properties
  const handleCollapseAll = useCallback(() => {
    const empty = new Set<string>();
    setGlobalExpandedProperties(empty);
    // Also reflect immediately into node data
    setNodes((prev) => prev.map((n) => ({ ...n, data: { ...(n.data as any), expandedProperties: empty } })));
  }, []);

  // Canvas search - validate regex when in regex mode (for error message)
  const canvasSearchRegexError = useMemo(() => {
    if (!canvasSearchUseRegex || !canvasSearchQuery.trim()) return null;
    try {
      new RegExp(canvasSearchQuery.trim(), 'i');
      return null;
    } catch {
      return 'Invalid regex';
    }
  }, [canvasSearchUseRegex, canvasSearchQuery]);

  // Canvas search - compute matching node IDs (class + property names and descriptions, basic or regex)
  const matchingNodeIds = useMemo(() => {
    const raw = canvasSearchQuery.trim();
    const hasFilters = searchFilterType !== 'all' ||
                       searchFilterGroup !== 'all' ||
                       searchFilterHasProperties !== 'all' ||
                       searchFilterPropertyName.trim() !== '';

    // If no query and no filters, return empty set
    if (!raw && !hasFilters) return new Set<string>();

    const matching = new Set<string>();

    // Helper to check if properties match search query
    const propsMatch = (props: Array<{ name?: string; description?: string }> | undefined, test: (s: string) => boolean): boolean => {
      if (!props || !Array.isArray(props)) return false;
      return props.some(p => {
        const n = (p.name ?? '').trim();
        const d = (p.description ?? '').trim();
        return (n && test(n)) || (d && test(d));
      });
    };

    // Helper to check if node has a specific property by name
    const hasPropertyNamed = (props: Array<{ name?: string }> | undefined, propName: string): boolean => {
      if (!props || !Array.isArray(props) || !propName) return true; // No filter if no propName
      const lowerPropName = propName.toLowerCase();
      return props.some(p => (p.name ?? '').toLowerCase().includes(lowerPropName));
    };

    // Helper to check node type filter
    const matchesTypeFilter = (nodeData: Record<string, unknown>): boolean => {
      if (searchFilterType === 'all') return true;
      const schema = nodeData?.schema as Record<string, unknown> | undefined;
      const isAllOf = !!schema?.allOf;
      const isOneOf = !!schema?.oneOf;
      const isAnyOf = !!schema?.anyOf;

      switch (searchFilterType) {
        case 'class': return !isAllOf && !isOneOf && !isAnyOf;
        case 'allOf': return isAllOf;
        case 'oneOf': return isOneOf;
        case 'anyOf': return isAnyOf;
        default: return true;
      }
    };

    // Helper to check group filter
    const matchesGroupFilter = (nodeId: string): boolean => {
      if (searchFilterGroup === 'all') return true;
      const group = groups.find(g => g.nodeIds.includes(nodeId));
      if (searchFilterGroup === 'ungrouped') {
        return !group;
      }
      return group?.id === searchFilterGroup;
    };

    // Helper to check properties filter (has/doesn't have properties)
    const matchesPropertiesFilter = (props: Array<unknown> | undefined): boolean => {
      if (searchFilterHasProperties === 'all') return true;
      const hasProps = !!(props && Array.isArray(props) && props.length > 0);
      return searchFilterHasProperties === 'with' ? hasProps : !hasProps;
    };

    // Build search test function
    let searchTest: ((s: string) => boolean) | null = null;
    if (raw) {
      if (canvasSearchUseRegex) {
        try {
          const re = new RegExp(raw, 'i');
          searchTest = (s: string) => re.test(s);
        } catch {
          return matching; // Invalid regex: no matches
        }
      } else {
        const query = raw.toLowerCase();
        searchTest = (s: string) => s.toLowerCase().includes(query);
      }
    }

    // Filter nodes
    nodes.forEach(node => {
      if (node.type === 'groupNode') return;
      const nodeData = node.data as Record<string, unknown>;
      const name = (nodeData?.name as string) ?? '';
      const description = (nodeData?.description as string) ?? '';
      const properties = nodeData?.properties as Array<{ name?: string; description?: string }> | undefined;

      // Apply filters
      if (!matchesTypeFilter(nodeData)) return;
      if (!matchesGroupFilter(node.id)) return;
      if (!matchesPropertiesFilter(properties)) return;
      if (searchFilterPropertyName.trim() && !hasPropertyNamed(properties, searchFilterPropertyName.trim())) return;

      // Apply search query (if no query but has filters, include all filtered nodes)
      if (searchTest) {
        if (searchTest(name) || searchTest(description) || propsMatch(properties, searchTest)) {
          matching.add(node.id);
        }
      } else {
        // No search query, but filters matched
        matching.add(node.id);
      }
    });

    return matching;
  }, [canvasSearchQuery, canvasSearchUseRegex, nodes, groups, searchFilterType, searchFilterGroup, searchFilterHasProperties, searchFilterPropertyName]);

  // Handle opening canvas search
  const openCanvasSearch = useCallback(() => {
    setCanvasSearchOpen(true);
    // Focus the input after a short delay to allow render
    setTimeout(() => {
      canvasSearchInputRef.current?.focus();
    }, 50);
  }, []);

  // Reset all search filters
  const resetSearchFilters = useCallback(() => {
    setSearchFilterType('all');
    setSearchFilterGroup('all');
    setSearchFilterHasProperties('all');
    setSearchFilterPropertyName('');
  }, []);

  // Check if any filters are active
  const hasActiveFilters = useMemo(() => {
    return searchFilterType !== 'all' ||
           searchFilterGroup !== 'all' ||
           searchFilterHasProperties !== 'all' ||
           searchFilterPropertyName.trim() !== '';
  }, [searchFilterType, searchFilterGroup, searchFilterHasProperties, searchFilterPropertyName]);

  // Handle closing canvas search
  const closeCanvasSearch = useCallback(() => {
    // Save to history if there was a search query
    if (canvasSearchQuery.trim()) {
      addToHistory(canvasSearchQuery.trim(), canvasSearchUseRegex);
    }
    setCanvasSearchOpen(false);
    setCanvasSearchQuery('');
    setSearchHistoryOpen(false);
    setSearchFiltersOpen(false);
    // Reset filters when closing
    resetSearchFilters();
  }, [canvasSearchQuery, canvasSearchUseRegex, addToHistory, resetSearchFilters]);

  // Handle selecting a search history item
  const selectSearchHistoryItem = useCallback((query: string, isRegex: boolean) => {
    setCanvasSearchQuery(query);
    setCanvasSearchUseRegex(isRegex);
    setSearchHistoryOpen(false);
    canvasSearchInputRef.current?.focus();
  }, []);

  // Close history dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchHistoryRef.current && e.target && !searchHistoryRef.current.contains(e.target as globalThis.Node)) {
        setSearchHistoryOpen(false);
      }
    };
    if (searchHistoryOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [searchHistoryOpen]);

  // Close filters dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchFiltersRef.current && e.target && !searchFiltersRef.current.contains(e.target as globalThis.Node)) {
        setSearchFiltersOpen(false);
      }
    };
    if (searchFiltersOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [searchFiltersOpen]);

  // #488: Node IDs that have at least one edge (for "show only connected" filter)
  const connectedNodeIds = useMemo(() => {
    const set = new Set<string>();
    edges.forEach(edge => {
      set.add(edge.source);
      set.add(edge.target);
    });
    return set;
  }, [edges]);

  /** All class node IDs in the current graph (for #484 edge inclusion when ghosts mode is on). */
  const allBaseClassNodeIds = useMemo(() => {
    const baseNodes = layoutPreviewNodes ?? nodes;
    return new Set(baseNodes.filter((n) => n.type !== 'groupNode').map((n) => n.id));
  }, [layoutPreviewNodes, nodes]);

  // #483: Class IDs visible after manual per-node hide and hide criteria
  const visibleClassIdsAfterHideCriteria = useMemo(() => {
    const baseNodes = layoutPreviewNodes ?? nodes;
    const classNodes = baseNodes.filter((n) => n.type !== 'groupNode');
    const passing = computeClassIdsPassingHideCriteria(
      classNodes,
      groups,
      connectedNodeIds,
      {
        hideEmptyClasses,
        hideUnconnectedClasses: showOnlyConnectedNodes,
        hideDeprecatedClasses,
        hiddenGroupIds: hiddenCanvasGroupIds,
      }
    );
    return new Set([...passing].filter((id) => !hiddenNodeIds.has(id)));
  }, [
    layoutPreviewNodes,
    nodes,
    groups,
    connectedNodeIds,
    hideEmptyClasses,
    showOnlyConnectedNodes,
    hideDeprecatedClasses,
    hiddenCanvasGroupIds,
    hiddenNodeIds,
  ]);

  // Focus mode: focused set = either group members (#490) or selection + neighbors up to degree (BFS)
  const focusModeFocusedSet = useMemo(() => {
    if (!focusModeEnabled) return new Set<string>();
    // #490: Focus on group – only show this group's members
    if (focusModeGroupId) {
      return new Set<string>(collectAllNodeIdsInGroupSubtree(focusModeGroupId, groups));
    }
    const classNodeIds = selectedNodeIds.filter(id => {
      const node = nodes.find(n => n.id === id);
      return node && node.type !== 'groupNode';
    });
    if (classNodeIds.length === 0) return new Set<string>();
    const focusedSet = new Set<string>(classNodeIds);
    let current = new Set<string>(classNodeIds);
    for (let d = 0; d < focusModeDegree; d++) {
      const next = new Set<string>();
      for (const id of current) {
        for (const edge of edges) {
          const other = edge.source === id ? edge.target : edge.source;
          if (edge.source === id || edge.target === id) {
            focusedSet.add(other);
            next.add(other);
          }
        }
      }
      current = next;
    }
    return focusedSet;
  }, [focusModeEnabled, focusModeGroupId, groups, focusModeDegree, selectedNodeIds, nodes, edges]);

  const toggleFocusMode = useCallback(() => {
    setFocusModeEnabled(prev => !prev);
  }, []);

  const exitFocusMode = useCallback(() => {
    setFocusModeEnabled(false);
    setFocusModeDegree(1);
    setFocusModeGroupId(null);
  }, []);

  const focusOnGroup = useCallback((groupId: string) => {
    setFocusModeEnabled(true);
    setFocusModeGroupId(groupId);
  }, []);

  const focusOnSelection = useCallback(() => {
    setFocusModeGroupId(null);
  }, []);

  const expandFocusDegree = useCallback(() => {
    setFocusModeDegree(prev => Math.min(prev + 1, FOCUS_MODE_MAX_DEGREE));
  }, []);

  const reduceFocusDegree = useCallback(() => {
    setFocusModeDegree(prev => Math.max(1, prev - 1));
  }, []);

  const resetFocusDegree = useCallback(() => {
    setFocusModeDegree(1);
  }, []);

  useEffect(() => {
    if (!selectedVersionId) {
      setPresentationBookmarks([]);
      return;
    }
    setPresentationBookmarks(loadPresentationBookmarks(selectedVersionId));
    setPresentationSlideIndex(0);
  }, [selectedVersionId]);

  useEffect(() => {
    if (!selectedVersionId) return;
    const timeoutId = window.setTimeout(() => {
      savePresentationBookmarks(selectedVersionId, presentationBookmarks);
    }, PRESENTATION_SAVE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [selectedVersionId, presentationBookmarks]);

  useEffect(() => {
    if (!canvasPresentationActive || presentationTimerStartMs === null) return;
    const id = window.setInterval(() => setPresentationTimerTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [canvasPresentationActive, presentationTimerStartMs]);

  const applyPresentationSlide = useCallback(
    (index: number, bookmarks: CanvasPresentationBookmark[]) => {
      const b = bookmarks[index];
      if (!b) return;
      setViewport({ x: b.viewport.x, y: b.viewport.y, zoom: b.viewport.zoom }, { duration: 400 });
    },
    [setViewport]
  );

  const exitPresentation = useCallback(async () => {
    setCanvasPresentationActive(false);
    setCanvasPresentationMode(false);
    setPresentationHintVisible(false);
    try {
      if (document.fullscreenElement && presentationShellRef.current && document.fullscreenElement === presentationShellRef.current) {
        await document.exitFullscreen();
      }
    } catch {
      /* ignore */
    }
  }, [setCanvasPresentationMode]);

  const startPresentation = useCallback(async () => {
    if (presentationBookmarks.length === 0) {
      await alertDialog({
        message: 'Add at least one slide from the current canvas view (Layout → Presentation slides), then start again.',
        variant: 'warning',
      });
      return;
    }
    setPresentationSlideIndex(0);
    applyPresentationSlide(0, presentationBookmarks);
    setPresentationTimerStartMs(Date.now());
    setPresentationTimerTick(0);
    setCanvasPresentationActive(true);
    setCanvasPresentationMode(true);
    setPresentationHintVisible(true);
    window.setTimeout(() => setPresentationHintVisible(false), 10000);
    const el = presentationShellRef.current;
    if (el?.requestFullscreen) {
      try {
        await el.requestFullscreen();
      } catch {
        /* user denied or not allowed */
      }
    }
  }, [presentationBookmarks, applyPresentationSlide, alertDialog, setCanvasPresentationMode]);

  const addPresentationSlideFromView = useCallback(() => {
    const vp = getViewport();
    setPresentationBookmarks((prev) => [
      ...prev,
      {
        id: newPresentationBookmarkId(),
        title: `Slide ${prev.length + 1}`,
        viewport: { x: vp.x, y: vp.y, zoom: vp.zoom },
        speakerNote: '',
      },
    ]);
  }, [getViewport]);

  const updatePresentationSlideTitle = useCallback((id: string, title: string) => {
    setPresentationBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, title } : b)));
  }, []);

  const updatePresentationSlideNote = useCallback((id: string, speakerNote: string) => {
    setPresentationBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, speakerNote } : b)));
  }, []);

  const removePresentationSlide = useCallback((id: string) => {
    setPresentationBookmarks((prev) => {
      const next = prev.filter((b) => b.id !== id);
      setPresentationSlideIndex((i) => Math.min(i, Math.max(0, next.length - 1)));
      return next;
    });
  }, []);

  const goPresentationPrev = useCallback(() => {
    setPresentationSlideIndex((i) => {
      const next = Math.max(0, i - 1);
      applyPresentationSlide(next, presentationBookmarks);
      return next;
    });
  }, [applyPresentationSlide, presentationBookmarks]);

  const goPresentationNext = useCallback(() => {
    setPresentationSlideIndex((i) => {
      const next = Math.min(presentationBookmarks.length - 1, i + 1);
      applyPresentationSlide(next, presentationBookmarks);
      return next;
    });
  }, [applyPresentationSlide, presentationBookmarks]);

  useEffect(() => {
    if (!canvasPresentationActive) return;
    const onFs = () => {
      if (!document.fullscreenElement) {
        setCanvasPresentationActive(false);
        setPresentationHintVisible(false);
      }
    };
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, [canvasPresentationActive]);

  useEffect(() => {
    if (!canvasPresentationActive) return;
    const handler = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const inField = Boolean(t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT'));

      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        void exitPresentation();
        return;
      }
      if (inField && e.key !== 'Escape') return;

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        goPresentationNext();
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        goPresentationPrev();
      } else if (e.key === ' ' || e.key === 'PageDown') {
        e.preventDefault();
        goPresentationNext();
      } else if (e.key === 'PageUp') {
        e.preventDefault();
        goPresentationPrev();
      } else if (e.key.toLowerCase() === 'n') {
        e.preventDefault();
        setPresentationShowSpeakerNotes((v) => !v);
      } else if (e.key.toLowerCase() === 't') {
        e.preventDefault();
        setPresentationTimerStartMs(Date.now());
        setPresentationTimerTick((x) => x + 1);
      } else if (e.key === 'Home') {
        e.preventDefault();
        setPresentationSlideIndex(0);
        applyPresentationSlide(0, presentationBookmarks);
      } else if (e.key === 'End') {
        e.preventDefault();
        const last = Math.max(0, presentationBookmarks.length - 1);
        setPresentationSlideIndex(last);
        applyPresentationSlide(last, presentationBookmarks);
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, [
    canvasPresentationActive,
    exitPresentation,
    goPresentationNext,
    goPresentationPrev,
    applyPresentationSlide,
    presentationBookmarks,
  ]);

  const presentationElapsedLabel = useMemo(() => {
    if (presentationTimerStartMs === null) return '0:00';
    const sec = Math.floor((Date.now() - presentationTimerStartMs) / 1000);
    const m = Math.floor(sec / 60);
    const r = sec % 60;
    return `${m}:${r.toString().padStart(2, '0')}`;
  }, [presentationTimerStartMs, presentationTimerTick]);

  // Keyboard shortcut for canvas search (Cmd+F or Ctrl+F) and focus mode (Esc)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle in canvas view mode
      if (viewMode !== 'canvas') return;

      if (canvasPresentationActive) return;

      // Cmd+F or Ctrl+F to open search
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault();
        openCanvasSearch();
      }

      // Escape: exit focus mode, then isolate selection, then close search
      if (e.key === 'Escape') {
        if (focusModeEnabled) {
          exitFocusMode();
          e.preventDefault();
        } else if (isolateSelectionEnabled) {
          setIsolateSelectionEnabled(false);
          e.preventDefault();
        } else if (canvasSearchOpen) {
          closeCanvasSearch();
        }
      }

      // #154: Alt+Shift+[ collapse all groups; Alt+Shift+] expand all
      if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && (e.key === '[' || e.key === ']')) {
        const el = e.target as HTMLElement | null;
        if (el?.closest('input, textarea, [contenteditable="true"]')) return;
        if (groups.length === 0) return;
        e.preventDefault();
        if (e.key === '[') {
          collapseAllCanvasGroupsRef.current();
        } else {
          expandAllCanvasGroupsRef.current();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    viewMode,
    canvasSearchOpen,
    openCanvasSearch,
    closeCanvasSearch,
    focusModeEnabled,
    exitFocusMode,
    isolateSelectionEnabled,
    canvasPresentationActive,
    groups.length,
  ]);

  // #482: Turn off isolate when the class selection is cleared
  useEffect(() => {
    if (isolateSelectionEnabled && selectedNodeIds.length === 0) {
      setIsolateSelectionEnabled(false);
    }
  }, [isolateSelectionEnabled, selectedNodeIds.length]);

  // #154: Class node IDs hidden because they belong to a collapsed group — shared between displayNodes and displayEdges
  const classIdsHiddenByCollapse = useMemo(
    () => getClassIdsInCollapsedGroups(groups, collapsedGroupIds),
    [groups, collapsedGroupIds],
  );

  // Compute nodes with search and/or focus mode styling applied (#471: use preview nodes when in layout preview)
  const displayNodes = useMemo(() => {
    let result = layoutPreviewNodes ?? nodes;

    if (nestedGroupDrillPath.length > 0) {
      const focusId = nestedGroupDrillPath[nestedGroupDrillPath.length - 1]!;
      const visibleGroupIds = collectSubtreeGroupIds(focusId, groups);
      const visibleClassIds = new Set(collectAllNodeIdsInGroupSubtree(focusId, groups));
      result = result.filter((node) => {
        if (node.type === 'groupNode') return visibleGroupIds.has(node.id);
        return visibleClassIds.has(node.id);
      });
    }

    // #481 + #483: Manual hide, empty/unconnected/deprecated/group criteria — group frame if any member visible
    // #484: Optional ghosts mode — keep hidden nodes on canvas with semi-transparent styling
    const groupMap = new Map(groups.map((g) => [g.id, g]));
    if (nodeGhostsModeEnabled) {
      result = result.filter((node) => {
        if (node.type === 'groupNode') {
          const g = groupMap.get(node.id);
          return g ? groupNodeIdIsVisible(g, allBaseClassNodeIds, groups) : false;
        }
        return true;
      });
      result = result.map((node) => {
        const g = node.type === 'groupNode' ? groupMap.get(node.id) : undefined;
        const ghost = ghostNodeClassName(
          node.id,
          node.type,
          g,
          visibleClassIdsAfterHideCriteria,
          nodeGhostsModeEnabled,
          groups
        );
        if (!ghost) return node;
        const existingClassName = node.className || '';
        return { ...node, className: `${existingClassName} ${ghost}`.trim() };
      });
    } else {
      result = result.filter((node) => {
        if (node.type === 'groupNode') {
          const g = groupMap.get(node.id);
          return g ? groupNodeIdIsVisible(g, visibleClassIdsAfterHideCriteria, groups) : false;
        }
        return visibleClassIdsAfterHideCriteria.has(node.id);
      });
    }

    // #482: Show only selected classes and group containers that include them
    if (isolateSelectionEnabled && selectedNodeIds.length > 0) {
      const visibleIds = getVisibleNodeIdsForIsolateSelection(groups, new Set(selectedNodeIds));
      result = result.filter((node) => visibleIds.has(node.id));
    }

    // #154: Hide member class nodes for collapsed groups (compact frame applied below)
    if (classIdsHiddenByCollapse.size > 0) {
      result = result.filter((node) => {
        if (node.type === 'groupNode') return true;
        return !classIdsHiddenByCollapse.has(node.id);
      });
    }

    // Apply search classes when search is active
    if (canvasSearchQuery.trim() && canvasSearchOpen) {
      result = result.map(node => {
        if (node.type === 'groupNode') return node;
        const isMatch = matchingNodeIds.has(node.id);
        const existingClassName = node.className || '';
        const searchClass = isMatch ? 'search-highlighted' : 'search-dimmed';
        return {
          ...node,
          className: `${existingClassName} ${searchClass}`.trim()
        };
      });
    }

    // Apply focus mode dimming when focus mode is on (current selection + immediate relationships)
    if (focusModeEnabled && focusModeFocusedSet.size > 0) {
      result = result.map(node => {
        if (node.type === 'groupNode') return node;
        const inFocus = focusModeFocusedSet.has(node.id);
        const existingClassName = node.className || '';
        const focusClass = inFocus ? '' : 'focus-dimmed';
        return {
          ...node,
          className: `${existingClassName} ${focusClass}`.trim()
        };
      });
    }

    // Strip any legacy heatmap data from node data (Heat Map feature removed)
    result = result.map(node => {
      if (node.type === 'groupNode') return node;
      const d = node.data as Record<string, unknown>;
      if (d.heatmapMode != null || d.heatmapValue != null || d.heatmapLabel != null) {
        const { heatmapMode: _m, heatmapValue: _v, heatmapLabel: _l, ...rest } = d;
        return { ...node, data: rest };
      }
      return node;
    });

    // #547: Dependency graph overlay – dim nodes that have no dependency edges
    // #549: Show dependency depth level (1st, 2nd, 3rd degree) on class nodes
    // #551: Upstream/downstream view – dim nodes not in focal + upstream/downstream set
    // #552: Path view – dim nodes not in full chain (upstream ∪ downstream ∪ focal)
    if (showDependencyOverlay) {
      const pathChainNodeSet = dependencyView === 'path' && dependencyPathChain ? dependencyPathChain.nodeIds : null;
      const upstreamDownstreamHighlightSet =
        !pathChainNodeSet && dependencyFocalNodeId && (dependencyView === 'upstream' ? dependencyUpstreamIds : dependencyDownstreamIds)
          ? new Set([dependencyFocalNodeId, ...(dependencyView === 'upstream' ? dependencyUpstreamIds! : dependencyDownstreamIds!)])
          : null;
      const highlightSet = pathChainNodeSet ?? upstreamDownstreamHighlightSet;

      result = result.map(node => {
        if (node.type === 'groupNode') return node;
        const hasDependency = nodesWithDependencyIds.has(node.id);
        const inUpstreamDownstreamHighlight = highlightSet?.has(node.id) ?? false;
        const useHighlightSet = highlightSet != null;
        const depClass = useHighlightSet ? (inUpstreamDownstreamHighlight ? '' : 'dependency-dimmed') : (hasDependency ? '' : 'dependency-dimmed');
        const showDepth = useHighlightSet ? inUpstreamDownstreamHighlight : hasDependency;
        const rawDepth = dependencyDepthMap.get(node.id) ?? 0;
        const depthLabel =
          rawDepth === 0
            ? 'Leaf'
            : rawDepth === 1
              ? '1st'
              : rawDepth === 2
                ? '2nd'
                : rawDepth === 3
                  ? '3rd'
                  : '3+';
        const existingClassName = node.className || '';
        return {
          ...node,
          className: `${existingClassName} ${depClass}`.trim(),
          data: {
            ...(node.data as object),
            ...(showDepth ? { dependencyDepth: rawDepth, dependencyDepthLabel: depthLabel } : {}),
          },
        };
      });
    } else {
      result = result.map(node => {
        if (node.type === 'groupNode') return node;
        const d = node.data as Record<string, unknown>;
        if (d.dependencyDepth != null || d.dependencyDepthLabel != null) {
          const { dependencyDepth: _dd, dependencyDepthLabel: _dl, ...rest } = d;
          return { ...node, data: rest };
        }
        return node;
      });
    }

    // #548: Circular dependency warning – pass flag to class nodes for badge/border
    result = result.map(node => {
      if (node.type === 'groupNode') return node;
      const inCircular = circularNodeIdsSet.has(node.id);
      const d = node.data as Record<string, unknown>;
      if (inCircular === !!d.inCircularDependency) return node;
      const { inCircularDependency: _rem, ...rest } = d;
      return {
        ...node,
        data: { ...rest, ...(inCircular ? { inCircularDependency: true } : {}) },
      };
    });

    // #550: Impact Analysis mode – dim nodes not in {source} ∪ affected, pass impactSource/impactAffected
    if (impactAnalysisMode && impactAnalysisSourceId && affectedClassIds) {
      const highlightSet = new Set([impactAnalysisSourceId, ...affectedClassIds]);
      result = result.map(node => {
        if (node.type === 'groupNode') return node;
        const inHighlight = highlightSet.has(node.id);
        const existingClassName = node.className || '';
        const impactClass = inHighlight ? '' : 'impact-dimmed';
        const impactSource = node.id === impactAnalysisSourceId;
        const impactAffected = affectedClassIds.has(node.id);
        return {
          ...node,
          className: `${existingClassName} ${impactClass}`.trim(),
          data: {
            ...(node.data as object),
            ...(impactSource ? { impactSource: true } : {}),
            ...(impactAffected ? { impactAffected: true } : {}),
          },
        };
      });
    } else if (impactAnalysisMode) {
      result = result.map(node => {
        if (node.type !== 'classNode') return node;
        const d = node.data as Record<string, unknown>;
        if (d.impactSource != null || d.impactAffected != null) {
          const { impactSource: _s, impactAffected: _a, ...rest } = d;
          return { ...node, data: rest };
        }
        return node;
      });
    } else {
      result = result.map(node => {
        if (node.type !== 'classNode') return node;
        const d = node.data as Record<string, unknown>;
        if (d.impactSource != null || d.impactAffected != null) {
          const { impactSource: _s, impactAffected: _a, ...rest } = d;
          return { ...node, data: rest };
        }
        return node;
      });
    }

    // #154: Wire collapse toggle and collapsed state into all group nodes; compact frame for collapsed ones
    result = result.map((node) => {
      if (node.type !== 'groupNode') return node;

      const isCollapsed = collapsedGroupIds.has(node.id);
      const z = node.style?.zIndex ?? -1;

      return {
        ...node,
        ...(isCollapsed
          ? {
              width: COLLAPSED_GROUP_FRAME_WIDTH,
              height: COLLAPSED_GROUP_FRAME_HEIGHT,
            }
          : {}),
        style: {
          ...node.style,
          ...(isCollapsed
            ? {
                width: COLLAPSED_GROUP_FRAME_WIDTH,
                height: COLLAPSED_GROUP_FRAME_HEIGHT,
              }
            : {}),
          zIndex: z,
        },
        data: {
          ...(node.data as object),
          collapsed: isCollapsed,
          onToggleCollapse: () => {
            toggleGroupCollapsedRef.current(node.id);
          },
          onDrillInto: () => handleDrillIntoNestedGroupRef.current(node.id),
        },
      };
    });

    return result;
  }, [nodes, layoutPreviewNodes, nestedGroupDrillPath, visibleClassIdsAfterHideCriteria, allBaseClassNodeIds, nodeGhostsModeEnabled, isolateSelectionEnabled, selectedNodeIds, groups, collapsedGroupIds, classIdsHiddenByCollapse, canvasSearchQuery, canvasSearchOpen, matchingNodeIds, focusModeEnabled, focusModeFocusedSet, showDependencyOverlay, dependencyView, dependencyFocalNodeId, dependencyUpstreamIds, dependencyDownstreamIds, dependencyPathChain, nodesWithDependencyIds, dependencyDepthMap, circularNodeIdsSet, impactAnalysisMode, impactAnalysisSourceId, affectedClassIds]);

  // Compute edges with search and/or focus mode styling applied
  const displayEdges = useMemo(() => {
    let result = edges;

    // #483 / #488: Edges between class nodes on canvas; #484 extends to hidden nodes when ghosts mode is on
    result = result.filter((edge) =>
      edgeBelongsOnCanvas(
        edge.source,
        edge.target,
        visibleClassIdsAfterHideCriteria,
        allBaseClassNodeIds,
        nodeGhostsModeEnabled
      )
    );

    if (isolateSelectionEnabled && selectedNodeIds.length > 0) {
      const visibleIds = getVisibleNodeIdsForIsolateSelection(groups, new Set(selectedNodeIds));
      result = result.filter(
        (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)
      );
    }

    if (classIdsHiddenByCollapse.size > 0) {
      result = result.filter(
        (edge) =>
          !classIdsHiddenByCollapse.has(edge.source) && !classIdsHiddenByCollapse.has(edge.target)
      );
    }

    if (nestedGroupDrillPath.length > 0) {
      const focusId = nestedGroupDrillPath[nestedGroupDrillPath.length - 1]!;
      const visibleClassIds = new Set(collectAllNodeIdsInGroupSubtree(focusId, groups));
      result = result.filter(
        (edge) => visibleClassIds.has(edge.source) && visibleClassIds.has(edge.target)
      );
    }

    // #484: Edges that touch a hidden (ghost) class are drawn semi-transparent
    if (nodeGhostsModeEnabled) {
      result = result.map((edge) => {
        const ghost = ghostEdgeClassName(
          edge.source,
          edge.target,
          visibleClassIdsAfterHideCriteria,
          nodeGhostsModeEnabled
        );
        if (!ghost) return edge;
        const existingClassName = edge.className || '';
        return { ...edge, className: `${existingClassName} ${ghost}`.trim() };
      });
    }

    // Dim edges that don't connect to matching nodes when search is active
    if (canvasSearchQuery.trim() && canvasSearchOpen) {
      result = result.map(edge => {
        const sourceMatch = matchingNodeIds.has(edge.source);
        const targetMatch = matchingNodeIds.has(edge.target);
        const isConnectedToMatch = sourceMatch || targetMatch;
        if (!isConnectedToMatch) {
          const existingClassName = edge.className || '';
          return {
            ...edge,
            className: `${existingClassName} search-dimmed`.trim()
          };
        }
        return edge;
      });
    }

    // Dim edges not between focused nodes when focus mode is on
    if (focusModeEnabled && focusModeFocusedSet.size > 0) {
      result = result.map(edge => {
        const bothFocused = focusModeFocusedSet.has(edge.source) && focusModeFocusedSet.has(edge.target);
        if (!bothFocused) {
          const existingClassName = edge.className || '';
          return {
            ...edge,
            className: `${existingClassName} focus-dimmed`.trim()
          };
        }
        return edge;
      });
    }

    // #547: Dependency graph overlay – highlight dependency edges, dim others
    // #551: Upstream/downstream view – highlight only dependency edges inside focal subgraph
    // #552: Path view – highlight only dependency edges in full chain
    if (showDependencyOverlay) {
      const pathChainEdgeSet = dependencyView === 'path' && dependencyPathChain ? dependencyPathChain.edgeIds : null;
      const upstreamDownstreamEdgeHighlightSet =
        !pathChainEdgeSet && dependencyFocalNodeId && (dependencyView === 'upstream' ? dependencyUpstreamIds : dependencyDownstreamIds)
          ? new Set([dependencyFocalNodeId, ...(dependencyView === 'upstream' ? dependencyUpstreamIds! : dependencyDownstreamIds!)])
          : null;

      result = result.map(edge => {
        const isDep = dependencyEdgeIds.has(edge.id);
        const inPathChain = pathChainEdgeSet != null && pathChainEdgeSet.has(edge.id);
        const inSubgraph = pathChainEdgeSet != null ? inPathChain : (upstreamDownstreamEdgeHighlightSet != null && upstreamDownstreamEdgeHighlightSet.has(edge.source) && upstreamDownstreamEdgeHighlightSet.has(edge.target));
        const highlightDep = (pathChainEdgeSet != null ? (isDep && inPathChain) : upstreamDownstreamEdgeHighlightSet != null ? (isDep && inSubgraph) : isDep);
        const existingClassName = edge.className || '';
        const depClass = highlightDep ? 'dependency-highlight' : 'dependency-dimmed';
        return {
          ...edge,
          className: `${existingClassName} ${depClass}`.trim()
        };
      });
    }

    // #548: Circular dependency – warning style for edges that are part of a cycle
    result = result.map(edge => {
      const inCycle = circularEdgeIds.has(edge.id);
      const existingClassName = edge.className || '';
      const circularClass = 'circular-warning';
      const hasClass = existingClassName.includes(circularClass);
      if (inCycle === hasClass) return edge;
      const className = inCycle
        ? `${existingClassName} ${circularClass}`.trim()
        : existingClassName.replace(circularClass, '').trim();
      return { ...edge, className };
    });

    // #550: Impact Analysis – dim edges not connected to source or affected nodes
    if (impactAnalysisMode && impactAnalysisSourceId && affectedClassIds) {
      const highlightSet = new Set([impactAnalysisSourceId, ...affectedClassIds]);
      result = result.map(edge => {
        const sourceIn = highlightSet.has(edge.source);
        const targetIn = highlightSet.has(edge.target);
        if (sourceIn || targetIn) return edge;
        const existingClassName = edge.className || '';
        return {
          ...edge,
          className: `${existingClassName} impact-dimmed`.trim()
        };
      });
    }

    return result;
  }, [edges, visibleClassIdsAfterHideCriteria, allBaseClassNodeIds, nodeGhostsModeEnabled, isolateSelectionEnabled, selectedNodeIds, groups, classIdsHiddenByCollapse, nestedGroupDrillPath, canvasSearchQuery, canvasSearchOpen, matchingNodeIds, focusModeEnabled, focusModeFocusedSet, showDependencyOverlay, dependencyView, dependencyFocalNodeId, dependencyUpstreamIds, dependencyDownstreamIds, dependencyPathChain, dependencyEdgeIds, circularEdgeIds, impactAnalysisMode, impactAnalysisSourceId, affectedClassIds]);

  // #349: Apply hover highlight to the hovered edge (thicker stroke, higher zIndex)
  const edgesWithHover = useMemo(() => {
    if (!hoveredEdgeId) return displayEdges;
    return displayEdges.map((edge) => {
      if (edge.id !== hoveredEdgeId) return edge;
      const baseWidth = (edge.style?.strokeWidth as number) || 2;
      return {
        ...edge,
        zIndex: (edge.zIndex ?? 0) + 10,
        style: {
          ...edge.style,
          strokeWidth: baseWidth + 2,
          filter: 'drop-shadow(0 0 4px rgba(99, 102, 241, 0.5))',
        },
      };
    });
  }, [displayEdges, hoveredEdgeId]);

  // Compute canvas background style based on settings (shared util for preview + main canvas)
  const canvasBackgroundStyle = useMemo(
    () => getCanvasBackgroundStyle(canvasBackground, isDark),
    [canvasBackground, isDark]
  );

  // Handle zoom to class when selected in sidebar
  const zoomToClass = useCallback((classId: string) => {
    let targetNode: Node | undefined;

    // Get node data using functional setState
    setNodes((currentNodes) => {
      targetNode = currentNodes.find(n => n.id === classId);
      if (!targetNode) return currentNodes;

      // Highlight the node by adding a temporary selected state
      return currentNodes.map((n) => ({
        ...n,
        selected: n.id === classId,
      }));
    });

    if (!targetNode) return;

    // Center the view on the node with smooth animation
    const x = targetNode.position.x + (targetNode.width || 200) / 2;
    const y = targetNode.position.y + (targetNode.height || 150) / 2;
    const currentZoom = getViewport().zoom;

    // Zoom to 1.5x if currently zoomed out, otherwise keep current zoom
    const targetZoom = currentZoom < 1 ? 1.5 : currentZoom;

    setCenter(x, y, { zoom: targetZoom, duration: 250 });
  }, [setCenter, getViewport]);

  const setClassVisibility = useCallback((classId: string, visible?: boolean) => {
    setHiddenNodeIdsState((prev) => {
      const next = new Set(prev);
      const shouldHide = visible === undefined ? !next.has(classId) : !visible;
      if (shouldHide) {
        next.add(classId);
      } else {
        next.delete(classId);
      }
      return next;
    });
  }, []);

  /** #485: One action to clear manual hides, hide filters, ghosts, isolate, and focus mode. */
  const restoreCanvasVisibility = useCallback(() => {
    setHiddenNodeIdsState(new Set());
    setHideEmptyClasses(false);
    setHideDeprecatedClasses(false);
    setShowOnlyConnectedNodes(false);
    setHiddenCanvasGroupIds(new Set());
    setNodeGhostsModeEnabled(false);
    setIsolateSelectionEnabled(false);
    setFocusModeEnabled(false);
    setFocusModeGroupId(null);
    setFocusModeDegree(1);
  }, []);

  // Register zoomToClass function in context on mount
  useEffect(() => {
    setZoomToClassFn(() => zoomToClass);
    return () => setZoomToClassFn(null);
  }, [zoomToClass, setZoomToClassFn]);

  useEffect(() => {
    setToggleClassVisibilityFn(() => setClassVisibility);
    return () => setToggleClassVisibilityFn(null);
  }, [setClassVisibility, setToggleClassVisibilityFn]);

  useEffect(() => {
    if (!selectedVersionId) {
      setHiddenNodeIdsState(new Set());
      setHiddenClassIds([]);
      return;
    }
    const key = getHiddenNodesStorageKey(selectedVersionId);
    try {
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : [];
      const ids = Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : [];
      setHiddenNodeIdsState(new Set(ids));
      setHiddenClassIds(ids);
    } catch {
      setHiddenNodeIdsState(new Set());
      setHiddenClassIds([]);
    }
  }, [selectedVersionId, getHiddenNodesStorageKey, setHiddenClassIds]);

  useEffect(() => {
    const ids = Array.from(hiddenNodeIds);
    setHiddenClassIds(ids);
    if (!selectedVersionId) return;
    const key = getHiddenNodesStorageKey(selectedVersionId);
    localStorage.setItem(key, JSON.stringify(ids));
  }, [hiddenNodeIds, selectedVersionId, getHiddenNodesStorageKey, setHiddenClassIds]);

  useEffect(() => {
    if (!selectedVersionId) {
      setHideEmptyClasses(false);
      setHideDeprecatedClasses(false);
      setShowOnlyConnectedNodes(false);
      setHiddenCanvasGroupIds(new Set());
      setNodeGhostsModeEnabled(false);
      skipNextHideCriteriaPersistRef.current = false;
      return;
    }
    const key = getHideCriteriaStorageKey(selectedVersionId);
    try {
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && typeof parsed === 'object') {
        setHideEmptyClasses(!!(parsed as { hideEmpty?: boolean }).hideEmpty);
        setHideDeprecatedClasses(!!(parsed as { hideDeprecated?: boolean }).hideDeprecated);
        setShowOnlyConnectedNodes(!!(parsed as { hideUnconnected?: boolean }).hideUnconnected);
        const gids = (parsed as { hiddenGroupIds?: unknown }).hiddenGroupIds;
        setHiddenCanvasGroupIds(
          Array.isArray(gids)
            ? new Set(gids.filter((x): x is string => typeof x === 'string'))
            : new Set()
        );
        setNodeGhostsModeEnabled(!!(parsed as { nodeGhosts?: boolean }).nodeGhosts);
      } else {
        setHideEmptyClasses(false);
        setHideDeprecatedClasses(false);
        setShowOnlyConnectedNodes(false);
        setHiddenCanvasGroupIds(new Set());
        setNodeGhostsModeEnabled(false);
      }
    } catch {
      setHideEmptyClasses(false);
      setHideDeprecatedClasses(false);
      setShowOnlyConnectedNodes(false);
      setHiddenCanvasGroupIds(new Set());
      setNodeGhostsModeEnabled(false);
      // Remove corrupt or unparsable hide-criteria from storage so it doesn't cause repeated parse failures
      localStorage.removeItem(key);
    }
    skipNextHideCriteriaPersistRef.current = true;
  }, [selectedVersionId, getHideCriteriaStorageKey]);

  useEffect(() => {
    if (!selectedVersionId) return;
    if (skipNextHideCriteriaPersistRef.current) {
      skipNextHideCriteriaPersistRef.current = false;
      return;
    }
    const key = getHideCriteriaStorageKey(selectedVersionId);
    localStorage.setItem(
      key,
      JSON.stringify({
        hideEmpty: hideEmptyClasses,
        hideDeprecated: hideDeprecatedClasses,
        hideUnconnected: showOnlyConnectedNodes,
        hiddenGroupIds: Array.from(hiddenCanvasGroupIds),
        nodeGhosts: nodeGhostsModeEnabled,
      })
    );
  }, [
    hideEmptyClasses,
    hideDeprecatedClasses,
    showOnlyConnectedNodes,
    hiddenCanvasGroupIds,
    nodeGhostsModeEnabled,
    selectedVersionId,
    getHideCriteriaStorageKey,
  ]);

  // Helper to reload classes for current selectedVersionId (used after edits)
  const reloadClasses = useCallback(async (applyLayout = false) => {
    if (!selectedVersionId) return;

    setIsLoadingCanvas(true);
    setLoadingMessage('Refreshing canvas...');

    try {
      // Bulk load all classes with properties and tags via REST API
      const result = await getClassesWithPropertiesAndTagsWithSession(selectedVersionId);
      if (!result.success) {
        console.error('Failed to load classes:', result.error);
        return;
      }
      const classesWithProperties = result.classes || [];

      setLoadingMessage('Updating nodes and edges...');

      // Preserve group frame nodes across refresh; merge class nodes by position (#156).
      const currentNodes = getNodes();
      const savedGroupNodes: Node[] = currentNodes.filter((n) => n.type === 'groupNode');
      const existingPositions = new Map<string, { x: number; y: number }>(
        currentNodes.map((n) => [n.id, n.position])
      );

      const newNodes = await classesToNodes(classesWithProperties);
      // Restore positions from existing nodes
      newNodes.forEach(node => {
        const existingPos = existingPositions.get(node.id);
        if (existingPos) {
          node.position = existingPos;
        }
      });
      const finalNodes = [...savedGroupNodes, ...newNodes];
      const newEdges = createAllEdges(classesWithProperties);
      setEdges(newEdges);
      setNodes(finalNodes);
    } catch (error) {
      console.error('Failed to reload classes:', error);
    } finally {
      setIsLoadingCanvas(false);
      setLoadingMessage('');
    }
  }, [selectedVersionId, projects, versions, getNodes]);

  // Helper to update only a single class node without reloading the entire canvas
  const updateSingleClassNode = useCallback(async (classId: string) => {
    if (!classId) return;

    try {
      // Fetch only the updated class from the REST API
      const result = await getClassWithPropertiesAndTagsWithSession(classId);
      if (!result.success || !result.class) {
        console.error('Class not found:', classId, result.error);
        return;
      }
      const classData = result.class;

      // Extract theme from canvas_metadata if it exists
      const canvasMetadata = classData.canvas_metadata || {};
      const theme = canvasMetadata.style || {};

      // Update only the affected node's data, preserving its position
      // Also clear measured dimensions to force React Flow to remeasure
      setNodes((currentNodes) =>
        currentNodes.map((node) => {
          if (node.id === classId) {
            // Create a new node object without the measured property
            // This forces React Flow to remeasure the node dimensions
            const { measured, width, height, ...restNode } = node as any;
            return {
              ...restNode,
              data: {
                ...node.data,
                id: classData.id,
                name: classData.name,
                description: classData.description,
                properties: classData.properties || [],
                schema: classData.schema,
                tags: classData.tags || [],
                theme: theme,
              },
            };
          }
          return node;
        })
      );

      // Tell React Flow to recalculate the node's dimensions and handle positions
      // This is needed because the node size changes when properties are added/removed
      // Use requestAnimationFrame + setTimeout to ensure the DOM has fully updated
      // before recalculating - this gives React enough time to complete the render cycle
      requestAnimationFrame(() => {
        setTimeout(() => {
          updateNodeInternals(classId);
        }, 50);
      });

      // Update edges that might be affected by property changes (e.g., new $ref properties)
      // This is needed because adding a property with $ref creates new edges
      if (selectedVersionId) {
        const allClassesResult = await getClassesWithPropertiesAndTagsWithSession(selectedVersionId);
        if (allClassesResult.success && allClassesResult.classes) {
          const newEdges = createAllEdges(allClassesResult.classes);
          setEdges(newEdges);
        }
      }
    } catch (error) {
      console.error('Failed to update single class node:', error);
    }
  }, [setNodes, setEdges, selectedVersionId, updateNodeInternals]);

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
      // Create the property in the library via REST API
      const response = await fetch(`/api/properties/${projectId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description,
          data,
        }),
      });
      const result = await response.json();
      if (result.success) {
        return result.property.id;
      } else {
        // Property might already exist with this name, which is fine
        console.warn(`Could not create library property "${name}": ${result.error}`);
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

    // Add the main property via REST API
    const response = await fetch(`/api/classes/${classId}/properties`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        property_id: propertyId,
        name,
        description,
        data: cleanedData,
        parent_id: parentId,
      }),
    });

    const result = await response.json();
    if (!result.success) {
      return { success: false, error: result.error || 'Failed to add property to class' };
    }

    const newClassPropertyId = result.classProperty.id;

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
        await updateSingleClassNode(classId); // Only update the affected class node
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
  }, [isReadOnly, selectedProjectId, updateSingleClassNode, alertDialog]);

  // Keep ref updated
  handlePropertyDropRef.current = handlePropertyDrop;

  // Handle property deletion from class
  const handlePropertyDelete = useCallback(async (classId: string, classPropertyId: string) => {
    if (isReadOnly) return;

    try {
      console.log('Removing property from class:', classId, classPropertyId);

      const response = await fetch(`/api/classes/${classId}/properties/${classPropertyId}`, {
        method: 'DELETE',
      });

      const result = await response.json();

      if (result.success) {
        await updateSingleClassNode(classId); // Only update the affected class node
      } else {
        await alertDialog({
          message: result.error || 'Failed to remove property from class',
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
  }, [isReadOnly, updateSingleClassNode, alertDialog]);

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

      // Add reference property to class via REST API (property_id is null since this is not from the property library)
      const response = await fetch(`/api/classes/${referenceTargetClassId}/properties`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          property_id: null, // No property_id - direct class property
          name: referenceData.name,
          description: referenceData.description,
          data,
          parent_id: parentId, // Parent can be null for top-level or specific for nested
        }),
      });

      const result = await response.json();
      if (result.success) {
        await updateSingleClassNode(referenceTargetClassId);
        triggerSidebarRefresh();
        setReferenceDialogOpen(false);
      } else {
        await alertDialog({
          message: result.error || 'Failed to create reference',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error creating reference:', error);
      throw error;
    }
  }, [referenceTargetClassId, nodes, updateSingleClassNode, triggerSidebarRefresh]);

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
      const response = await deleteClassWithSession(classId);

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

    const group = groups.find((g) => g.id === groupId);
    const subtree = collectSubtreeGroupIds(groupId, groups);
    const subtreeCount = subtree.size;
    const confirmed = await confirmDialog({
      title: 'Delete Group',
      message:
        subtreeCount > 1
          ? `Delete "${group?.name || 'this group'}" and ${subtreeCount - 1} nested group frame(s)? Classes on the canvas are not deleted.`
          : `Are you sure you want to delete the group "${group?.name || 'this group'}"? The classes inside will not be deleted.`,
      variant: 'warning',
      confirmLabel: 'Delete Group',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    const byIdDel = groupById(groups);
    const sortedToRemove = Array.from(subtree).sort(
      (a, b) => getGroupDepth(b, byIdDel) - getGroupDepth(a, byIdDel)
    );
    for (const id of sortedToRemove) {
      deleteGroupFromContext(id);
      groupPositionsRef.current.delete(id);
    }

    setNodes((prevNodes) =>
      prevNodes.filter((node) => !(node.type === 'groupNode' && subtree.has(node.id)))
    );

    setNestedGroupDrillPath((prev) => prev.filter((id) => !subtree.has(id)));

    // Auto-save to database
    if (selectedVersionId && currentUserId) {
      try {
        const viewport = getViewport();
        const nodeData = nodes.filter((n) => !subtree.has(n.id) && n.type !== 'groupNode').map((node) => ({
          id: node.id,
          position: node.position,
          dimensions: node.style ? { width: node.style.width, height: node.style.height } : undefined
        }));
        const edgeData = edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target
        }));

        const updatedGroups = groups.filter((g) => !subtree.has(g.id));

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

  // Handle delete all classes in group
  // Optional classIdsFromNode/groupNameFromNode come from the group node so we don't rely on groups state being in sync
  const handleDeleteAllClassesInGroup = useCallback(async (
    groupId: string,
    _classIdsFromNode?: string[],
    groupNameFromNode?: string
  ) => {
    if (isReadOnly) return;

    const group = groups.find((g) => g.id === groupId);
    const classIds = collectAllNodeIdsInGroupSubtree(groupId, groups);
    const directCount = group?.nodeIds?.length ?? 0;
    const groupName = groupNameFromNode ?? group?.name ?? 'this group';

    if (classIds.length === 0) {
      return;
    }

    const confirmed = await confirmDialog({
      title: 'Delete All Classes in Group',
      message: `Are you sure you want to delete all ${classIds.length} class${classIds.length === 1 ? '' : 'es'} in "${groupName}"${
        classIds.length > directCount ? ' (including classes in nested group frames)' : ''
      }? This action cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete All',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    const errors: string[] = [];
    for (const classId of classIds) {
      const response = await deleteClassWithSession(classId);
      if (!response.success) {
        errors.push(response.error || classId);
      }
    }

    if (errors.length > 0) {
      await alertDialog({
        message: `Failed to delete ${errors.length} class${errors.length === 1 ? '' : 'es'}: ${errors.slice(0, 3).join(', ')}${errors.length > 3 ? '...' : ''}`,
        variant: 'error',
      });
    }

    await reloadClasses(true);
    triggerSidebarRefresh();
  }, [isReadOnly, groups, confirmDialog, alertDialog, deleteClassWithSession, reloadClasses, triggerSidebarRefresh]);

  const handleExportGroupSchema = useCallback(
    async (groupId: string, nodeIds: string[], groupName: string, format: 'json' | 'yaml') => {
      if (!selectedVersionId) return;
      const rootIds = collectAllNodeIdsInGroupSubtree(groupId, groups);
      const exportIds = rootIds.length > 0 ? rootIds : nodeIds;
      if (exportIds.length === 0) return;
      try {
        const res = await getClassesWithPropertiesAndTagsWithSession(selectedVersionId);
        if (!res.success || !res.classes) {
          await alertDialog({
            message: res.error || 'Failed to load classes for export.',
            variant: 'error',
          });
          return;
        }
        const expanded = expandClassesForGroupExport(exportIds, res.classes);
        if (expanded.length === 0) {
          await alertDialog({ message: 'No classes in this group to export.', variant: 'warning' });
          return;
        }
        const project = projects.find((p) => p.id === selectedProjectId);
        const ver = versions.find((v) => v.id === selectedVersionId);
        const specJson = await generateOpenApiSpec(expanded, {
          projectName: project?.name ? `${project.name} — ${groupName}` : groupName,
          version: ver?.version_id ?? '1.0.0',
          description: `OpenAPI components for canvas group "${groupName}" (Objectified export).`,
        });
        const safe = groupName.replace(/[^\w\-]+/g, '-').toLowerCase().slice(0, 80) || 'group';
        if (format === 'yaml') {
          const doc = JSON.parse(specJson);
          const yaml = YAML.stringify(doc, { lineWidth: 0, aliasDuplicateObjects: false } as any);
          downloadTextFile(`${safe}-openapi.yaml`, yaml, 'text/yaml');
        } else {
          downloadTextFile(`${safe}-openapi.json`, specJson, 'application/json');
        }
      } catch (err: unknown) {
        console.error('Failed to export group schema:', err);
        const message =
          err instanceof Error
            ? `Failed to export group schema: ${err.message}`
            : 'Failed to export group schema due to an unexpected error.';
        await alertDialog({ message, variant: 'error' });
      }
    },
    [selectedVersionId, selectedProjectId, projects, versions, alertDialog, groups]
  );

  const handleBulkEditGroupClasses = useCallback(
    async (
      groupId: string,
      nodeIds: string[],
      groupName: string,
      options: {
        descriptionPrefix?: string;
        descriptionSuffix?: string;
        tagId?: string;
        topLevelPropertyReadOnly?: boolean;
      }
    ) => {
      if (isReadOnly) return;
      const bulkIds = collectAllNodeIdsInGroupSubtree(groupId, groups);
      const targetIds = bulkIds.length > 0 ? bulkIds : nodeIds;
      if (targetIds.length === 0) return;
      const hasText =
        (options.descriptionPrefix && options.descriptionPrefix.trim().length > 0) ||
        (options.descriptionSuffix && options.descriptionSuffix.trim().length > 0);
      const hasTag = Boolean(options.tagId && options.tagId.trim().length > 0);
      const hasReadOnly = typeof options.topLevelPropertyReadOnly === 'boolean';
      if (!hasText && !hasTag && !hasReadOnly) {
        await alertDialog({
          message: 'Choose at least one change: description prefix/suffix, tag, or read-only.',
          variant: 'warning',
        });
        throw new Error('No bulk changes selected.');
      }
      const ok = await confirmDialog({
        title: 'Apply to all classes in group',
        message: `Update ${targetIds.length} class(es) in "${groupName}"${bulkIds.length > nodeIds.length ? ' (includes nested groups)' : ''}?`,
        confirmLabel: 'Apply',
        cancelLabel: 'Cancel',
      });
      if (!ok) throw new Error('cancelled');

      const raw = await bulkApplyEditsToGroupClasses(selectedVersionId!, targetIds, {
        descriptionPrefix:
          options.descriptionPrefix && options.descriptionPrefix.trim().length > 0
            ? options.descriptionPrefix
            : undefined,
        descriptionSuffix:
          options.descriptionSuffix && options.descriptionSuffix.trim().length > 0
            ? options.descriptionSuffix
            : undefined,
        tagId: hasTag ? options.tagId : undefined,
        topLevelPropertyReadOnly: hasReadOnly ? options.topLevelPropertyReadOnly : undefined,
      });
      const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
      if (!parsed.success) {
        await alertDialog({
          message: parsed.error || 'Bulk update failed.',
          variant: 'error',
        });
        throw new Error(parsed.error || 'Bulk update failed.');
      }
      await reloadClasses(true);
      triggerSidebarRefresh();
      await alertDialog({ message: 'Bulk changes applied to all classes in this group.', variant: 'success' });
    },
    [isReadOnly, selectedVersionId, confirmDialog, alertDialog, reloadClasses, triggerSidebarRefresh, groups]
  );

  const handleDuplicateGroup = useCallback(
    async (sourceGroupId: string, nodeIds: string[], sourceGroupName: string) => {
      if (isReadOnly || !selectedVersionId || nodeIds.length === 0) return;

      const ok = await confirmDialog({
        title: 'Duplicate group',
        message: `Create copies of all ${nodeIds.length} class(es) in "${sourceGroupName}" in a new group? References between these classes will target the duplicated types.`,
        confirmLabel: 'Duplicate',
        cancelLabel: 'Cancel',
      });
      if (!ok) return;

      const sourceGroup = groups.find((g) => g.id === sourceGroupId);
      const idSet = new Set(nodeIds);
      const oldPositions = new Map<string, { x: number; y: number }>();
      getNodes().forEach((n) => {
        if (idSet.has(n.id)) oldPositions.set(n.id, { ...n.position });
      });

      const dupRaw = await duplicateClassesInGroup(selectedVersionId, nodeIds);
      const dup = typeof dupRaw === 'string' ? JSON.parse(dupRaw) : dupRaw;
      if (!dup.success) {
        await alertDialog({
          message: dup.error || 'Could not duplicate classes.',
          variant: 'error',
        });
        return;
      }
      const idMap: Record<string, string> = dup.idMap || {};
      const OFFSET = 56;

      let newGroupName = `${sourceGroupName} Copy`;
      let suffix = 2;
      while (groups.some((g) => g.name === newGroupName)) {
        newGroupName = `${sourceGroupName} Copy ${suffix++}`;
      }

      const newGroupId = generateGroupId();
      const basePos = sourceGroup?.position || { x: 120, y: 120 };
      const newGroup = {
        id: newGroupId,
        name: newGroupName,
        color: sourceGroup?.color || GROUP_COLORS[0].name,
        parentId: null as string | null,
        nodeIds: nodeIds.map((oid) => idMap[oid]).filter(Boolean) as string[],
        position: { x: basePos.x + OFFSET, y: basePos.y + OFFSET },
        dimensions: sourceGroup?.dimensions || { width: 400, height: 300 },
        styleOptions:
          sourceGroup?.styleOptions ||
          ({
            borderStyle: 'dashed' as const,
            opacity: 1,
            shadow: 'none' as const,
            icon: 'folder',
          } as const),
        description: sourceGroup?.description,
        tags: sourceGroup?.tags,
      };

      const nextGroups = [...groups, newGroup];
      addGroup(newGroup);
      groupPositionsRef.current.set(newGroupId, { ...newGroup.position });

      const availableTags = projectTags.map((t) => ({
        id: t.id,
        name: t.tag_name,
        color: t.tag_color,
      }));

      const newGroupFlowNode: Node = {
        id: newGroupId,
        type: 'groupNode',
        position: newGroup.position,
        width: newGroup.dimensions.width,
        height: newGroup.dimensions.height,
        style: {
          width: newGroup.dimensions.width,
          height: newGroup.dimensions.height,
          zIndex: -1,
        },
        data: {
          id: newGroupId,
          name: newGroup.name,
          color: newGroup.color,
          nodeIds: newGroup.nodeIds,
          tags: newGroup.tags,
          styleOptions: newGroup.styleOptions,
          availableTags,
          onRename: (gid: string, name: string) => handleGroupRenameRef.current?.(gid, name),
          onDelete: (gid: string) => handleGroupDeleteRef.current?.(gid),
          onDeleteAllClassesInGroup: (gid: string, cids?: string[], gn?: string) =>
            handleDeleteAllClassesInGroupRef.current?.(gid, cids, gn),
          onExportGroupSchema: (gid: string, cids: string[], gn: string, fmt: 'json' | 'yaml') =>
            handleExportGroupSchemaRef.current?.(gid, cids, gn, fmt),
          onDuplicateGroup: (gid: string, cids: string[], gn: string) =>
            handleDuplicateGroupRef.current?.(gid, cids, gn),
          onBulkEditGroupClasses: (
            gid: string,
            cids: string[],
            gn: string,
            opts: {
              descriptionPrefix?: string;
              descriptionSuffix?: string;
              tagId?: string;
              topLevelPropertyReadOnly?: boolean;
            }
          ) => handleBulkEditGroupClassesRef.current?.(gid, cids, gn, opts),
          onColorChange: (gid: string, color: string) => handleGroupColorChangeRef.current?.(gid, color),
          onStyleChange: (gid: string, style: any) => handleGroupStyleChangeRef.current?.(gid, style),
          onTagsChange: (gid: string, t: any[]) => handleGroupTagsChangeRef.current?.(gid, t),
          parentId: null,
          onDrillInto: () => handleDrillIntoNestedGroupRef.current(newGroupId),
          isReadOnly,
        },
      };

      setNodes((prev) => [newGroupFlowNode, ...prev]);

      await reloadClasses(true);

      setNodes((prev) =>
        prev.map((node) => {
          if (node.type === 'groupNode') return node;
          for (const oid of nodeIds) {
            if (node.id === idMap[oid] && oldPositions.has(oid)) {
              const op = oldPositions.get(oid)!;
              return {
                ...node,
                position: { x: op.x + OFFSET, y: op.y + OFFSET },
              };
            }
          }
          return node;
        })
      );

      for (const oid of nodeIds) {
        const nid = idMap[oid];
        const op = oldPositions.get(oid);
        if (nid && op) {
          void updateClassCanvasMetadataWithSession(nid, {
            position: { x: op.x + OFFSET, y: op.y + OFFSET },
          });
        }
      }

      if (selectedVersionId && currentUserId) {
        try {
          const viewport = getViewport();
          const flowNodes = getNodes();
          const flowEdges = getEdges();
          const nodeData = flowNodes.map((node) => ({
            id: node.id,
            type: node.type,
            position: node.position,
            dimensions: {
              width: (node as any).measured?.width || (node as any).width || (node.style as any)?.width,
              height: (node as any).measured?.height || (node as any).height || (node.style as any)?.height,
            },
          }));
          const edgeData = flowEdges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
          }));
          await saveDefaultCanvasLayout(
            selectedVersionId,
            currentUserId,
            viewport,
            nodeData,
            edgeData,
            nextGroups
          );
        } catch (e) {
          console.error('Failed to save layout after duplicate group:', e);
        }
      }

      await alertDialog({
        message: `Duplicated ${nodeIds.length} class(es) into "${newGroupName}".`,
        variant: 'success',
      });
      triggerSidebarRefresh();
    },
    [
      isReadOnly,
      selectedVersionId,
      groups,
      confirmDialog,
      alertDialog,
      getNodes,
      getEdges,
      getViewport,
      addGroup,
      generateGroupId,
      reloadClasses,
      setNodes,
      projectTags,
      currentUserId,
      triggerSidebarRefresh,
    ]
  );

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

  const handleDrillIntoNestedGroup = useCallback((groupId: string) => {
    setNestedGroupDrillPath((prev) => [...prev, groupId]);
  }, []);

  // Assign current handlers to refs for use in effects
  handleGroupTagsChangeRef.current = handleGroupTagsChange;
  handleGroupRenameRef.current = handleGroupRename;
  handleGroupDeleteRef.current = handleGroupDelete;
  handleDeleteAllClassesInGroupRef.current = handleDeleteAllClassesInGroup;
  handleExportGroupSchemaRef.current = handleExportGroupSchema;
  handleDuplicateGroupRef.current = handleDuplicateGroup;
  handleBulkEditGroupClassesRef.current = handleBulkEditGroupClasses;
  handleGroupColorChangeRef.current = handleGroupColorChange;
  handleGroupStyleChangeRef.current = handleGroupStyleChange;
  handleDrillIntoNestedGroupRef.current = handleDrillIntoNestedGroup;

  // State for drag-over highlighting
  const [dragOverGroupId, setDragOverGroupId] = useState<string | null>(null);
  const dragOverGroupIdRef = useRef<string | null>(null);

  // #477: Canvas dropzone highlight when dragging new-group from sidebar
  const [isCanvasDropTarget, setIsCanvasDropTarget] = useState(false);

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
  const handleAddNodeToGroup = useCallback(async (groupId: string, nodeId: string, nodePosition: { x: number; y: number }) => {
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

    // Persist to database immediately with position
    try {
      const result = await addClassToGroup(groupId, nodeId, {
        positionX: nodePosition.x,
        positionY: nodePosition.y,
        sortOrder: updatedNodeIds.length - 1
      });
      const response = JSON.parse(result);
      if (!response.success) {
        console.error('Failed to persist class to group:', response.error);
      }
    } catch (error) {
      console.error('Error persisting class to group:', error);
    }
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

  // Innermost group frame containing (x,y) — #155 nesting uses smallest overlapping frame
  const findGroupAtPosition = useCallback((x: number, y: number, excludeGroupId?: string): string | null => {
    const groupFlowNodes = nodes.filter((n) => n.type === 'groupNode') as FlowLikeGroupNode[];
    const exclude = new Set<string>();
    if (excludeGroupId) exclude.add(excludeGroupId);
    return findInnermostGroupAtPosition(x, y, groupFlowNodes, exclude);
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

  // Handle node drag - check if over a group for visual feedback and calculate smart guides
  const handleNodeDrag = useCallback((event: React.MouseEvent, node: Node) => {
    if (isReadOnly) {
      setDragOverGroupId(null);
      setGuides({ horizontal: [], vertical: [] });
      return;
    }

    if (node.type === 'groupNode') {
      setGuides({ horizontal: [], vertical: [] });
      const desc = collectDescendantGroupIds(node.id, groups);
      const exclude = new Set<string>([node.id, ...desc]);
      const groupFlowNodes = nodes.filter((n) => n.type === 'groupNode') as FlowLikeGroupNode[];
      const nodeWidth = (node.measured?.width as number) || (node.width as number) || 400;
      const nodeHeight = (node.measured?.height as number) || (node.height as number) || 300;
      const cx = node.position.x + nodeWidth / 2;
      const cy = node.position.y + nodeHeight / 2;
      const target = findInnermostGroupAtPosition(cx, cy, groupFlowNodes, exclude);
      const byId = groupById(groups);
      const currentParent = groups.find((g) => g.id === node.id)?.parentId ?? null;
      let showTarget: string | null = null;
      if (target) {
        if (
          !isStrictDescendantGroup(node.id, target, byId) &&
          !wouldNestExceedMaxDepth(node.id, target, groups)
        ) {
          if (target !== currentParent) showTarget = target;
        }
      }
      setDragOverGroupId(showTarget);
      return;
    }

    // Get node dimensions and positions
    const nodeWidth = (node.measured?.width as number) || (node.width as number) || 260;
    const nodeHeight = (node.measured?.height as number) || (node.height as number) || 200;
    const nodeCenterX = node.position.x + nodeWidth / 2;
    const nodeCenterY = node.position.y + nodeHeight / 2;
    const nodeLeft = node.position.x;
    const nodeRight = node.position.x + nodeWidth;
    const nodeTop = node.position.y;
    const nodeBottom = node.position.y + nodeHeight;

    // Find if over any group
    const overGroupId = findGroupAtPosition(nodeCenterX, nodeCenterY);
    setDragOverGroupId(overGroupId);

    // Only calculate smart guides if enabled
    if (!smartGuidesEnabled) {
      setGuides({ horizontal: [], vertical: [] });
      return;
    }

    // Calculate smart guides for alignment
    const SNAP_THRESHOLD = 8; // pixels
    const newHorizontalGuides: Array<{ y: number; x1: number; x2: number }> = [];
    const newVerticalGuides: Array<{ x: number; y1: number; y2: number }> = [];

    // Get all other class nodes (not groups, not the dragging node)
    const otherNodes = nodes.filter(n => n.id !== node.id && n.type !== 'groupNode');

    otherNodes.forEach(otherNode => {
      const otherWidth = (otherNode.measured?.width as number) || (otherNode.width as number) || 260;
      const otherHeight = (otherNode.measured?.height as number) || (otherNode.height as number) || 200;
      const otherCenterX = otherNode.position.x + otherWidth / 2;
      const otherCenterY = otherNode.position.y + otherHeight / 2;
      const otherLeft = otherNode.position.x;
      const otherRight = otherNode.position.x + otherWidth;
      const otherTop = otherNode.position.y;
      const otherBottom = otherNode.position.y + otherHeight;

      // Calculate x bounds for horizontal guides
      const minX = Math.min(nodeLeft, otherLeft) - 20;
      const maxX = Math.max(nodeRight, otherRight) + 20;

      // Calculate y bounds for vertical guides
      const minY = Math.min(nodeTop, otherTop) - 20;
      const maxY = Math.max(nodeBottom, otherBottom) + 20;

      // Horizontal alignment checks (same Y positions)
      // Top edge alignment
      if (Math.abs(nodeTop - otherTop) < SNAP_THRESHOLD) {
        newHorizontalGuides.push({ y: otherTop, x1: minX, x2: maxX });
      }
      // Bottom edge alignment
      if (Math.abs(nodeBottom - otherBottom) < SNAP_THRESHOLD) {
        newHorizontalGuides.push({ y: otherBottom, x1: minX, x2: maxX });
      }
      // Center Y alignment
      if (Math.abs(nodeCenterY - otherCenterY) < SNAP_THRESHOLD) {
        newHorizontalGuides.push({ y: otherCenterY, x1: minX, x2: maxX });
      }
      // Top to bottom alignment
      if (Math.abs(nodeTop - otherBottom) < SNAP_THRESHOLD) {
        newHorizontalGuides.push({ y: otherBottom, x1: minX, x2: maxX });
      }
      // Bottom to top alignment
      if (Math.abs(nodeBottom - otherTop) < SNAP_THRESHOLD) {
        newHorizontalGuides.push({ y: otherTop, x1: minX, x2: maxX });
      }

      // Vertical alignment checks (same X positions)
      // Left edge alignment
      if (Math.abs(nodeLeft - otherLeft) < SNAP_THRESHOLD) {
        newVerticalGuides.push({ x: otherLeft, y1: minY, y2: maxY });
      }
      // Right edge alignment
      if (Math.abs(nodeRight - otherRight) < SNAP_THRESHOLD) {
        newVerticalGuides.push({ x: otherRight, y1: minY, y2: maxY });
      }
      // Center X alignment
      if (Math.abs(nodeCenterX - otherCenterX) < SNAP_THRESHOLD) {
        newVerticalGuides.push({ x: otherCenterX, y1: minY, y2: maxY });
      }
      // Left to right alignment
      if (Math.abs(nodeLeft - otherRight) < SNAP_THRESHOLD) {
        newVerticalGuides.push({ x: otherRight, y1: minY, y2: maxY });
      }
      // Right to left alignment
      if (Math.abs(nodeRight - otherLeft) < SNAP_THRESHOLD) {
        newVerticalGuides.push({ x: otherLeft, y1: minY, y2: maxY });
      }
    });

    setGuides({ horizontal: newHorizontalGuides, vertical: newVerticalGuides });
  }, [isReadOnly, findGroupAtPosition, nodes, smartGuidesEnabled, groups]);

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
    setGuides({ horizontal: [], vertical: [] }); // Clear smart guides

    if (isReadOnly) return;

    // #155: Nest or unnest group frames by dropping inside another group or on empty canvas
    if (node.type === 'groupNode') {
      const movingId = node.id;
      const desc = collectDescendantGroupIds(movingId, groups);
      const exclude = new Set<string>([movingId, ...desc]);
      const groupFlowNodes = nodes.filter((n) => n.type === 'groupNode') as FlowLikeGroupNode[];
      const nodeWidth = (node.measured?.width as number) || (node.width as number) || 400;
      const nodeHeight = (node.measured?.height as number) || (node.height as number) || 300;
      const cx = node.position.x + nodeWidth / 2;
      const cy = node.position.y + nodeHeight / 2;
      const targetParentId = findInnermostGroupAtPosition(cx, cy, groupFlowNodes, exclude);
      const currentParent = groups.find((g) => g.id === movingId)?.parentId ?? null;
      const newParent = targetParentId ?? null;
      const byId = groupById(groups);

      if (
        newParent &&
        (isStrictDescendantGroup(movingId, newParent, byId) ||
          wouldNestExceedMaxDepth(movingId, newParent, groups))
      ) {
        await alertDialog({
          message: isStrictDescendantGroup(movingId, newParent, byId)
            ? 'A group cannot be placed inside its own descendant.'
            : `Groups can nest at most ${MAX_CANVAS_GROUP_DEPTH} levels deep.`,
          variant: 'warning',
        });
        return;
      }

      if (newParent === currentParent) return;

      updateGroup(movingId, { parentId: newParent });
      setNodes((prev) =>
        prev.map((n) => {
          if (n.id === movingId && n.type === 'groupNode') {
            return { ...n, data: { ...(n.data as object), parentId: newParent } };
          }
          return n;
        })
      );

      if (selectedVersionId && currentUserId) {
        try {
          const viewport = getViewport();
          const nodeData = nodes.map((nd) => ({
            id: nd.id,
            type: nd.type,
            position: nd.position,
            dimensions: {
              width: (nd as any).measured?.width || (nd as any).width || (nd.style as any)?.width,
              height: (nd as any).measured?.height || (nd as any).height || (nd.style as any)?.height,
            },
          }));
          const edgeData = edges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
          }));
          const updatedGroups = groups.map((g) =>
            g.id === movingId ? { ...g, parentId: newParent } : g
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
          console.error('Failed to save after nesting change:', error);
        }
      }
      return;
    }

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
      await handleAddNodeToGroup(targetGroupId, node.id, node.position);
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
          await handleAddNodeToGroup(targetGroupId, node.id, node.position);
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
      else {
        // Update position in database
        try {
          await updateClassPositionInGroup(currentGroupId, node.id, node.position.x, node.position.y);
        } catch (error) {
          console.error('Error updating class position in group:', error);
        }
      }
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
      // If still partially inside, update position in database
      else {
        try {
          await updateClassPositionInGroup(currentGroupId, node.id, node.position.x, node.position.y);
        } catch (error) {
          console.error('Error updating class position in group:', error);
        }
      }
    }
    // Case 4: Node dragged within the same group (currentGroupId == targetGroupId)
    else if (currentGroupId && targetGroupId && currentGroupId === targetGroupId) {
      // Update position in database
      try {
        await updateClassPositionInGroup(currentGroupId, node.id, node.position.x, node.position.y);
      } catch (error) {
        console.error('Error updating class position in group:', error);
      }
    }
  }, [
    isReadOnly,
    findNodeGroup,
    findGroupAtPosition,
    handleAddNodeToGroup,
    handleRemoveNodeFromGroup,
    groups,
    confirmDialog,
    alertDialog,
    updateGroup,
    setNodes,
    nodes,
    edges,
    isNodeCompletelyOutsideGroup,
    selectedVersionId,
    currentUserId,
    getViewport,
    saveDefaultCanvasLayout,
  ]);

  // Handle canvas drag over - allow dropping groups; show dropzone when dragging new-group
  const handleCanvasDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    const isNewGroupDrag = event.dataTransfer.types.includes('application/x-objectified-drag-type');
    setIsCanvasDropTarget(isNewGroupDrag);
  }, []);

  // Clear canvas dropzone highlight when drag ends (e.g. drop elsewhere or cancel)
  useEffect(() => {
    const clearCanvasDropTarget = () => setIsCanvasDropTarget(false);
    document.addEventListener('dragend', clearCanvasDropTarget);
    document.addEventListener('drop', clearCanvasDropTarget);
    return () => {
      document.removeEventListener('dragend', clearCanvasDropTarget);
      document.removeEventListener('drop', clearCanvasDropTarget);
    };
  }, []);

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

    const createGroupAvailableTags = projectTags.map((t) => ({
      id: t.id,
      name: t.tag_name,
      color: t.tag_color,
    }));

    // Add group to context
    addGroup(newGroup);

    // Initialize group position ref for delta tracking during drag
    groupPositionsRef.current.set(groupId, { x: position.x, y: position.y });

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
        parentId: null,
        availableTags: createGroupAvailableTags,
        onRename: handleGroupRename,
        onDelete: handleGroupDelete,
        onDeleteAllClassesInGroup: handleDeleteAllClassesInGroup,
        onExportGroupSchema: (gid: string, cids: string[], gn: string, fmt: 'json' | 'yaml') =>
          handleExportGroupSchemaRef.current?.(gid, cids, gn, fmt),
        onDuplicateGroup: (gid: string, cids: string[], gn: string) =>
          handleDuplicateGroupRef.current?.(gid, cids, gn),
        onBulkEditGroupClasses: (
          gid: string,
          cids: string[],
          gn: string,
          opts: {
            descriptionPrefix?: string;
            descriptionSuffix?: string;
            tagId?: string;
            topLevelPropertyReadOnly?: boolean;
          }
        ) => handleBulkEditGroupClassesRef.current?.(gid, cids, gn, opts),
        onColorChange: handleGroupColorChange,
        onStyleChange: handleGroupStyleChange,
        onDrillInto: () => handleDrillIntoNestedGroupRef.current(groupId),
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

        // Get updated groups with the new name
        const updatedGroups = groups.map(g =>
          g.id === groupId ? { ...g, name: newGroup.name } : g
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
        console.error('Failed to auto-save group creation:', error);
      }
    }

  }, [groups, isReadOnly, addGroup, generateGroupId, setNodes, getViewport, handleGroupRename, handleGroupDelete, handleDeleteAllClassesInGroup, handleGroupColorChange, handleGroupStyleChange, selectedVersionId, currentUserId, nodes, edges, projectTags]);

  // Register handleCreateGroup function in context for sidebar access
  useEffect(() => {
    setCreateGroupFn(() => handleCreateGroup);
    return () => setCreateGroupFn(null);
  }, [handleCreateGroup, setCreateGroupFn]);

  // Register handleDeleteAllClassesInGroup in context for sidebar access
  useEffect(() => {
    setDeleteAllClassesInGroupFn((groupId: string, classIds?: string[], groupName?: string): Promise<void> =>
      handleDeleteAllClassesInGroupRef.current?.(groupId, classIds, groupName) ?? Promise.resolve()
    );
    return () => setDeleteAllClassesInGroupFn(null);
  }, [setDeleteAllClassesInGroupFn]);

  // Register group delete for sidebar (persists layout, removes nested subtree + group nodes)
  useEffect(() => {
    const register: SetStateAction<((groupId: string) => Promise<void>) | null> = () =>
      async (groupId: string) => {
        await handleGroupDeleteRef.current?.(groupId);
      };
    setDeleteGroupFn(register);
    return () => setDeleteGroupFn(null);
  }, [setDeleteGroupFn]);

  // Create a new group at a specific position (for drag-and-drop)
  const handleCreateGroupAtPosition = useCallback(async (dropPosition: { x: number; y: number }) => {
    if (isReadOnly) return;

    // Default group dimensions
    const defaultWidth = 400;
    const defaultHeight = 300;

    // Position group centered at the drop position
    const position = {
      x: dropPosition.x - defaultWidth / 2,
      y: dropPosition.y - defaultHeight / 2
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

    const createGroupAtDropAvailableTags = projectTags.map((t) => ({
      id: t.id,
      name: t.tag_name,
      color: t.tag_color,
    }));

    // Add group to context
    addGroup(newGroup);

    // Initialize group position ref for delta tracking during drag
    groupPositionsRef.current.set(groupId, { x: position.x, y: position.y });

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
        parentId: null,
        availableTags: createGroupAtDropAvailableTags,
        onRename: handleGroupRename,
        onDelete: handleGroupDelete,
        onDeleteAllClassesInGroup: handleDeleteAllClassesInGroup,
        onExportGroupSchema: (gid: string, cids: string[], gn: string, fmt: 'json' | 'yaml') =>
          handleExportGroupSchemaRef.current?.(gid, cids, gn, fmt),
        onDuplicateGroup: (gid: string, cids: string[], gn: string) =>
          handleDuplicateGroupRef.current?.(gid, cids, gn),
        onBulkEditGroupClasses: (
          gid: string,
          cids: string[],
          gn: string,
          opts: {
            descriptionPrefix?: string;
            descriptionSuffix?: string;
            tagId?: string;
            topLevelPropertyReadOnly?: boolean;
          }
        ) => handleBulkEditGroupClassesRef.current?.(gid, cids, gn, opts),
        onColorChange: handleGroupColorChange,
        onStyleChange: handleGroupStyleChange,
        onDrillInto: () => handleDrillIntoNestedGroupRef.current(groupId),
        isReadOnly: isReadOnly
      }
    };

    // Add group node to canvas
    setNodes(prevNodes => [groupNode, ...prevNodes]);

    // Auto-save to database
    const viewport = getViewport();
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

  }, [groups, isReadOnly, addGroup, generateGroupId, setNodes, getViewport, handleGroupRename, handleGroupDelete, handleDeleteAllClassesInGroup, handleGroupColorChange, handleGroupStyleChange, selectedVersionId, currentUserId, nodes, edges, projectTags]);

  // Register handleCreateGroupAtPosition function in context for drag-and-drop access
  useEffect(() => {
    setCreateGroupAtPositionFn(() => handleCreateGroupAtPosition);
    return () => setCreateGroupAtPositionFn(null);
  }, [handleCreateGroupAtPosition, setCreateGroupAtPositionFn]);

  // Handle canvas drop - create group at drop position
  const handleCanvasDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setIsCanvasDropTarget(false);

    if (isReadOnly) return;

    try {
      const data = event.dataTransfer.getData('application/json');
      if (!data) return;

      const dropData = JSON.parse(data);

      // Only handle new-group drops on the canvas itself
      if (dropData.type === 'new-group') {
        // Get the drop position relative to the canvas
        const viewport = getViewport();
        const bounds = (event.target as HTMLElement).closest('.react-flow')?.getBoundingClientRect();

        if (bounds) {
          // Convert screen coordinates to flow coordinates
          const x = (event.clientX - bounds.left - viewport.x) / viewport.zoom;
          const y = (event.clientY - bounds.top - viewport.y) / viewport.zoom;

          // Create group at the drop position
          handleCreateGroupAtPosition({ x, y });
        }
      }
    } catch (error) {
      console.error('Error handling canvas drop:', error);
    }
  }, [isReadOnly, getViewport, handleCreateGroupAtPosition]);

  // Track previous group positions for calculating deltas
  const groupPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  // Custom onNodesChange that syncs group positions/dimensions, moves children, and constrains grouped nodes
  const handleNodesChange = useCallback((changes: any[]) => {
    const shouldTriggerAutoSave = changes.some((change: any) => {
      if (!change || typeof change !== 'object') return false;
      return (
        change.type === 'position' ||
        change.type === 'dimensions' ||
        change.type === 'add' ||
        change.type === 'remove'
      );
    });

    if (shouldTriggerAutoSave) {
      setAutoSavePending(true);
    }
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

        // #155: Nested group frames stay within parent bounds (same rules as class nodes)
        if (node?.type === 'groupNode') {
          const selfGroup = groups.find((g) => g.id === change.id);
          const pgId = selfGroup?.parentId;
          if (!pgId) return change;
          const parentGn = nodes.find((n) => n.id === pgId && n.type === 'groupNode');
          if (!parentGn) return change;
          const nodeWidth = (node?.measured?.width as number) || (node?.width as number) || 400;
          const nodeHeight = (node?.measured?.height as number) || (node?.height as number) || 300;
          const groupX = parentGn.position.x;
          const groupY = parentGn.position.y;
          const groupWidth =
            (parentGn.measured?.width as number) || (parentGn.style?.width as number) || 400;
          const groupHeight =
            (parentGn.measured?.height as number) || (parentGn.style?.height as number) || 300;
          const nodeLeft = change.position.x;
          const nodeRight = change.position.x + nodeWidth;
          const nodeTop = change.position.y;
          const nodeBottom = change.position.y + nodeHeight;
          const groupLeft = groupX;
          const groupRight = groupX + groupWidth;
          const groupTop = groupY;
          const groupBottom = groupY + groupHeight;
          const isCompletelyOutside =
            nodeRight < groupLeft ||
            nodeLeft > groupRight ||
            nodeBottom < groupTop ||
            nodeTop > groupBottom;
          if (isCompletelyOutside && change.dragging) return change;
          if (isCompletelyOutside && !change.dragging) return change;
          const constrainedX = Math.max(
            groupX,
            Math.min(change.position.x, groupX + groupWidth - nodeWidth)
          );
          const constrainedY = Math.max(
            groupY,
            Math.min(change.position.y, groupY + groupHeight - nodeHeight)
          );
          return {
            ...change,
            position: { x: constrainedX, y: constrainedY },
          };
        }

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

    // Move child class nodes and nested group frames when a parent group moves (#155)
    if (groupDeltas.size > 0) {
      const byId = groupById(groups);
      setNodes((prevNodes) => {
        return prevNodes.map((node) => {
          if (node.type === 'groupNode') {
            for (const [movedGid, delta] of groupDeltas) {
              if (node.id === movedGid) continue;
              if (isStrictDescendantGroup(movedGid, node.id, byId)) {
                const newX = node.position.x + delta.dx;
                const newY = node.position.y + delta.dy;
                // Keep groupPositionsRef in sync so the next drag computes correct deltas
                groupPositionsRef.current.set(node.id, { x: newX, y: newY });
                return {
                  ...node,
                  position: {
                    x: newX,
                    y: newY,
                  },
                };
              }
            }
            return node;
          }

          for (const [groupId, delta] of groupDeltas) {
            const group = groups.find((g) => g.id === groupId);
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

  const handleEdgesChange = useCallback((changes: any[]) => {
    const hasLayoutAffectingChange = changes.some((change) => {
      if (!change || typeof change !== 'object') return false;

      if (change.type === 'add' || change.type === 'remove') {
        return true;
      }

      if (change.type === 'update') {
        const update = (change as any).update;
        if (update && typeof update === 'object' && update.type === 'replace') {
          return true;
        }
      }

      return false;
    });

    if (hasLayoutAffectingChange) {
      setAutoSavePending(true);
    }
    onEdgesChange(changes);
  }, [onEdgesChange]);

  // ============================================================================
  // END GROUP MANAGEMENT HANDLERS
  // ============================================================================

  // ============================================================================
  // LAYOUT SAVE/LOAD HANDLERS
  // ============================================================================

  // Save current canvas layout
  const handleSaveLayout = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId) return;

    const layoutName = selectedLayoutName.trim();
    if (!layoutName) {
      await alertDialog({
        message: 'Please enter a layout name.',
        variant: 'warning',
      });
      return;
    }

    try {
      setLoadingMessage('Saving canvas layout...');
      setIsLoadingCanvas(true);

      let snapshotDataUrl: string | undefined;
      let snapshotBase64ForServer: string | undefined;
      const captureEl = canvasCaptureAreaRef.current;
      if (captureEl) {
        try {
          const dataUrl = await toPng(captureEl, {
            pixelRatio: 0.45,
            cacheBust: true,
            backgroundColor: isDark ? '#111827' : '#f8fafc',
          });
          const comma = dataUrl.indexOf(',');
          if (comma !== -1 && dataUrl.slice(0, comma).includes('image/png')) {
            snapshotDataUrl = dataUrl;
            snapshotBase64ForServer = dataUrl.slice(comma + 1);
          }
        } catch (snapErr) {
          console.warn('Canvas snapshot capture failed:', snapErr);
        }
      }

      // Get current viewport
      const viewport = getViewport();

      const nodeData = mapNodesForLayoutSave(nodes);
      const edgeData = mapEdgesForLayoutSave(edges);

      // Save selected named layout to database
      const result = await saveNamedCanvasLayout(
        selectedVersionId,
        currentUserId,
        layoutName,
        viewport,
        nodeData,
        edgeData,
        groups,
        snapshotBase64ForServer
      );

      const response = JSON.parse(result);

      if (response.success) {
        setSelectedLayoutName(layoutName);
        if (snapshotDataUrl) {
          setNamedLayoutSnapshotDataUrls((prev) => ({ ...prev, [layoutName]: snapshotDataUrl }));
        }
        // Show "Saved" state temporarily
        setLayoutSaved(true);
        setHasExistingLayout(true);
        setAvailableLayoutNames(prev => {
          if (prev.includes(layoutName)) return prev;
          return [...prev, layoutName];
        });
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
  }, [isReadOnly, selectedVersionId, currentUserId, selectedLayoutName, nodes, edges, groups, getViewport, alertDialog, isDark]);

  const handleSetMyDefaultLayoutName = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId) return;
    const layoutName = selectedLayoutName.trim();
    if (!layoutName) {
      await alertDialog({ message: 'Please enter a layout name.', variant: 'warning' });
      return;
    }
    try {
      const result = await setUserCanvasLayoutDefaultName(selectedVersionId, layoutName);
      const response = JSON.parse(result);
      if (response.success) {
        await alertDialog({
          message: `This layout name is now your default when you open this version.`,
          variant: 'success',
        });
      } else {
        await alertDialog({ message: response.error || 'Could not save preference', variant: 'error' });
      }
    } catch {
      await alertDialog({ message: 'Could not save preference', variant: 'error' });
    }
  }, [isReadOnly, selectedVersionId, currentUserId, selectedLayoutName, alertDialog]);

  const handleClearMyDefaultLayoutName = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId) return;
    try {
      const result = await clearUserCanvasLayoutDefaultName(selectedVersionId);
      const response = JSON.parse(result);
      if (response.success) {
        await alertDialog({
          message: 'Your personal default was cleared. The team or built-in default will apply on next open.',
          variant: 'success',
        });
      } else {
        await alertDialog({ message: response.error || 'Could not clear preference', variant: 'error' });
      }
    } catch {
      await alertDialog({ message: 'Could not clear preference', variant: 'error' });
    }
  }, [isReadOnly, selectedVersionId, currentUserId, alertDialog]);

  const handleSetTeamDefaultLayoutName = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId || !currentTenantId || !effectiveIsTenantAdmin) return;
    const layoutName = selectedLayoutName.trim();
    if (!layoutName) {
      await alertDialog({ message: 'Please enter a layout name.', variant: 'warning' });
      return;
    }
    try {
      const result = await setTenantCanvasLayoutDefaultName(
        selectedVersionId,
        currentTenantId,
        layoutName
      );
      const response = JSON.parse(result);
      if (response.success) {
        await alertDialog({
          message: `Team default layout name for this version is now "${layoutName}".`,
          variant: 'success',
        });
      } else {
        await alertDialog({ message: response.error || 'Could not save team default', variant: 'error' });
      }
    } catch {
      await alertDialog({ message: 'Could not save team default', variant: 'error' });
    }
  }, [
    isReadOnly,
    selectedVersionId,
    currentUserId,
    currentTenantId,
    effectiveIsTenantAdmin,
    selectedLayoutName,
    alertDialog,
  ]);

  const handleClearTeamDefaultLayoutName = useCallback(async () => {
    if (isReadOnly || !selectedVersionId || !currentUserId || !currentTenantId || !effectiveIsTenantAdmin) return;
    const ok = await confirmDialog({
      title: 'Clear team default',
      message: 'Remove the team default layout name for this version? Members without a personal default will use the built-in fallback on next open.',
    });
    if (!ok) return;
    try {
      const result = await clearTenantCanvasLayoutDefaultName(selectedVersionId, currentTenantId);
      const response = JSON.parse(result);
      if (response.success) {
        await alertDialog({ message: 'Team default cleared.', variant: 'success' });
      } else {
        await alertDialog({ message: response.error || 'Could not clear team default', variant: 'error' });
      }
    } catch {
      await alertDialog({ message: 'Could not clear team default', variant: 'error' });
    }
  }, [
    isReadOnly,
    selectedVersionId,
    currentUserId,
    currentTenantId,
    effectiveIsTenantAdmin,
    confirmDialog,
    alertDialog,
  ]);

  const autoSaveDefaultLayout = useCallback(async () => {
    if (
      !autoSaveLayoutEnabled ||
      !autoSavePendingRef.current ||
      isReadOnly ||
      !selectedVersionId ||
      !currentUserId ||
      layoutPreviewNodesForAutoSaveRef.current ||
      autoSaveInFlightRef.current
    ) {
      return;
    }

    autoSaveInFlightRef.current = true;
    try {
      const viewport = getViewport();
      const nodeData = mapNodesForLayoutSave(nodesForAutoSaveRef.current);
      const edgeData = mapEdgesForLayoutSave(edgesForAutoSaveRef.current);

      const result = await saveDefaultCanvasLayout(
        selectedVersionId,
        currentUserId,
        viewport,
        nodeData,
        edgeData,
        groupsForAutoSaveRef.current
      );
      const response = JSON.parse(result);
      if (response.success) {
        setAutoSavePending(false);
      }
    } catch (error) {
      console.error('Failed to auto-save layout:', error);
    } finally {
      autoSaveInFlightRef.current = false;
    }
  }, [
    autoSaveLayoutEnabled,
    isReadOnly,
    selectedVersionId,
    currentUserId,
    getViewport,
  ]);

  useEffect(() => {
    if (!autoSaveLayoutEnabled || autoSaveLayoutIntervalSeconds < 10) return;

    const intervalId = window.setInterval(() => {
      void autoSaveDefaultLayout();
    }, autoSaveLayoutIntervalSeconds * 1000);

    return () => window.clearInterval(intervalId);
  }, [autoSaveLayoutEnabled, autoSaveLayoutIntervalSeconds, autoSaveDefaultLayout]);

  /**
   * Shared path for applying saved layout data (DB or JSON import) after groups are in the database.
   */
  const applyCanvasLayoutPayload = useCallback(
    async (options: {
      layout: {
        viewport?: { x?: number; y?: number; zoom?: number };
        nodes?: unknown;
        edges?: unknown;
      };
      layoutNameToSet?: string;
      clearGroupsWhenEmpty?: boolean;
    }) => {
      const { layout, layoutNameToSet, clearGroupsWhenEmpty } = options;

      if (layout.viewport) {
        const viewport = layout.viewport;
        const x =
          typeof viewport.x === 'number' && Number.isFinite(viewport.x) ? viewport.x : 0;
        const y =
          typeof viewport.y === 'number' && Number.isFinite(viewport.y) ? viewport.y : 0;
        const zoom =
          typeof viewport.zoom === 'number' && Number.isFinite(viewport.zoom) ? viewport.zoom : 1;
        setViewport(
          { x, y, zoom },
          { duration: 250 }
        );
      }

      let loadedGroups: any[] = [];
      let classPositionsInGroups: Record<string, { x: number | null; y: number | null }> = {};
      try {
        const groupsResult = await getGroupsForVersion(selectedVersionId!);
        loadedGroups = JSON.parse(groupsResult);

        if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
          loadedGroups.forEach((g: any) => {
            if (g.classPositions) {
              Object.assign(classPositionsInGroups, g.classPositions);
            }
          });

          const canvasGroups = loadedGroups.map((g: any) => ({
            id: g.id,
            name: g.name,
            description: g.description,
            color: g.color,
            position: g.position,
            dimensions: g.dimensions,
            nodeIds: g.nodeIds || [],
            parentId: g.parentId ?? null,
            tags: g.metadata?.tags || [],
            styleOptions: {
              borderStyle: g.borderStyle || 'dashed',
              opacity: g.opacity ?? 1,
              shadow: g.metadata?.shadow || 'none',
              icon: g.metadata?.icon || 'folder',
            },
          }));
          setGroups(canvasGroups);
          loadedGroups = canvasGroups;

          canvasGroups.forEach((group: any) => {
            groupPositionsRef.current.set(group.id, { x: group.position.x, y: group.position.y });
          });
        } else if (clearGroupsWhenEmpty) {
          setGroups([]);
          groupPositionsRef.current.clear();
        }
      } catch (error) {
        console.error('Error loading groups:', error);
      }

      await reloadClasses(false);

      setTimeout(() => {
        const layoutNodes = Array.isArray(layout.nodes) ? layout.nodes : [];
        const availableTags = projectTags.map((t) => ({ id: t.id, name: t.tag_name, color: t.tag_color }));

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
                zIndex: -1,
              },
              data: {
                id: group.id,
                name: group.name,
                color: group.color,
                nodeIds: group.nodeIds || [],
                parentId: group.parentId ?? null,
                tags: group.metadata?.tags || [],
                styleOptions: group.styleOptions,
                availableTags,
                onRename: (groupId: string, name: string) => handleGroupRenameRef.current?.(groupId, name),
                onDelete: (groupId: string) => handleGroupDeleteRef.current?.(groupId),
                onDeleteAllClassesInGroup: (gid: string, cids?: string[], gn?: string) =>
                  handleDeleteAllClassesInGroupRef.current?.(gid, cids, gn),
                onExportGroupSchema: (gid: string, cids: string[], gn: string, fmt: 'json' | 'yaml') =>
                  handleExportGroupSchemaRef.current?.(gid, cids, gn, fmt),
                onDuplicateGroup: (gid: string, cids: string[], gn: string) =>
                  handleDuplicateGroupRef.current?.(gid, cids, gn),
                onBulkEditGroupClasses: (
                  gid: string,
                  cids: string[],
                  gn: string,
                  opts: {
                    descriptionPrefix?: string;
                    descriptionSuffix?: string;
                    tagId?: string;
                    topLevelPropertyReadOnly?: boolean;
                  }
                ) => handleBulkEditGroupClassesRef.current?.(gid, cids, gn, opts),
                onColorChange: (groupId: string, color: string) =>
                  handleGroupColorChangeRef.current?.(groupId, color),
                onStyleChange: (groupId: string, style: any) =>
                  handleGroupStyleChangeRef.current?.(groupId, style),
                onTagsChange: (groupId: string, tags: any[]) =>
                  handleGroupTagsChangeRef.current?.(groupId, tags),
                onDrillInto: () => handleDrillIntoNestedGroupRef.current(group.id),
                isReadOnly,
              },
            };
            groupNodes.push(groupNode);
          });
        }

        if (layoutNodes.length > 0) {
          const layoutNodeMap = new Map<string, any>(
            layoutNodes.map((n: any) => [n.id, n])
          );
          setNodes((prevNodes) => {
            const updatedNodes = prevNodes.map((node) => {
              const { measured, width, height, ...restNode } = node as any;

              if (classPositionsInGroups[node.id]) {
                const savedPos = classPositionsInGroups[node.id];
                if (savedPos.x !== null && savedPos.y !== null) {
                  return {
                    ...restNode,
                    position: { x: savedPos.x, y: savedPos.y },
                  };
                }
              }

              const savedNode = layoutNodeMap.get(node.id);
              if (savedNode) {
                return {
                  ...restNode,
                  position: savedNode.position,
                };
              }
              return restNode;
            });

            return [...groupNodes, ...updatedNodes];
          });

          requestAnimationFrame(() => {
            setTimeout(() => {
              layoutNodes.forEach((n: any) => {
                if (n.id) {
                  updateNodeInternals(n.id);
                }
              });
            }, 100);
          });
        } else {
          setNodes((prevNodes) => [...groupNodes, ...prevNodes]);
        }

        triggerSidebarRefresh();

        if (Array.isArray(layout.edges) && layout.edges.length > 0) {
          setEdges((eds) => mergeSavedEdgeHandles(eds, layout.edges as unknown[]));
        }

        setIsLoadingCanvas(false);
        setLoadingMessage('');
        setLayoutDropdownOpen(false);
      }, 500);

      if (layoutNameToSet !== undefined) {
        setSelectedLayoutName(layoutNameToSet);
      }
    },
    [
      selectedVersionId,
      reloadClasses,
      setNodes,
      setEdges,
      setGroups,
      setViewport,
      projectTags,
      isReadOnly,
      triggerSidebarRefresh,
      updateNodeInternals,
    ]
  );

  // Load saved canvas layout
  const handleLoadLayout = useCallback(async () => {
    if (!selectedVersionId || !currentUserId) return;

    const layoutName = selectedLayoutName.trim();
    if (!layoutName) {
      await alertDialog({
        message: 'Please enter a layout name to load.',
        variant: 'warning',
      });
      return;
    }

    try {
      setLoadingMessage('Loading canvas layout...');
      setIsLoadingCanvas(true);

      const result = await getNamedCanvasLayout(selectedVersionId, currentUserId, layoutName);
      const response = JSON.parse(result);

      if (!response.success || !response.layout) {
        await alertDialog({
          message: `No saved "${layoutName}" found for this version`,
          variant: 'warning',
        });
        setIsLoadingCanvas(false);
        setLoadingMessage('');
        setLayoutDropdownOpen(false);
        return;
      }

      await applyCanvasLayoutPayload({
        layout: response.layout,
        layoutNameToSet: layoutName,
      });
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
  }, [selectedVersionId, currentUserId, selectedLayoutName, reloadClasses, alertDialog, applyCanvasLayoutPayload]);

  const handleExportLayoutJson = useCallback(() => {
    if (!selectedVersionId) return;
    const viewport = getViewport();
    const nodeData = mapNodesForLayoutSave(nodes);
    const edgeData = mapEdgesForLayoutSave(edges);
    const doc = buildCanvasLayoutJsonDocument({
      layoutName: selectedLayoutName.trim() || undefined,
      viewport,
      nodes: nodeData,
      edges: edgeData,
      groups,
      gridSettings: {
        size: gridSize,
        snapToGrid,
        showGrid,
        gridStyle,
      },
      generator: { name: 'objectified-ui' },
    });
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const base =
      selectedLayoutName
        .trim()
        .replace(/[^a-zA-Z0-9-_]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'canvas-layout';
    a.href = url;
    a.download = `${base}-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [
    selectedVersionId,
    getViewport,
    nodes,
    edges,
    groups,
    selectedLayoutName,
    gridSize,
    snapToGrid,
    showGrid,
    gridStyle,
  ]);

  const handleImportLayoutJsonPick = useCallback(() => {
    layoutJsonImportInputRef.current?.click();
  }, []);

  const handleImportLayoutJsonSelected = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file || !selectedVersionId || !currentUserId || isReadOnly) return;

      let text: string;
      try {
        text = await file.text();
      } catch {
        await alertDialog({ message: 'Could not read the file.', variant: 'error' });
        return;
      }

      let parsedJson: unknown;
      try {
        parsedJson = JSON.parse(text);
      } catch {
        await alertDialog({ message: 'The file is not valid JSON.', variant: 'error' });
        return;
      }

      const parsed = parseCanvasLayoutJson(parsedJson);
      if (!parsed.ok) {
        await alertDialog({ message: parsed.error, variant: 'error' });
        return;
      }

      const ok = await confirmDialog({
        title: 'Import layout from JSON',
        message:
          'Replace the current canvas with this layout? Class positions apply only to classes that exist in this version. Groups and viewport will match the file after import.',
      });
      if (!ok) return;

      try {
        setLoadingMessage('Importing layout...');
        setIsLoadingCanvas(true);

        const idsRes = await getClassIdsForVersion(selectedVersionId);
        const idsParsed = JSON.parse(idsRes);
        if (!idsParsed.success || !Array.isArray(idsParsed.classIds)) {
          await alertDialog({
            message: idsParsed.error || 'Could not load classes for this version.',
            variant: 'error',
          });
          setIsLoadingCanvas(false);
          setLoadingMessage('');
          return;
        }

        const validIds = new Set<string>(idsParsed.classIds);
        const filtered = filterCanvasLayoutForTargetClasses(parsed.doc, validIds);

        const syncRes = await syncGroupsForVersion(
          selectedVersionId,
          filtered.groups,
          filtered.nodePositions
        );
        const syncParsed = JSON.parse(syncRes);
        if (!syncParsed.success) {
          await alertDialog({
            message: syncParsed.error || 'Failed to sync groups for this layout.',
            variant: 'error',
          });
          setIsLoadingCanvas(false);
          setLoadingMessage('');
          return;
        }

        if (filtered.droppedClassCount > 0) {
          await alertDialog({
            message: `${filtered.droppedClassCount} class(es) from the file are not in this version and were skipped.`,
            variant: 'warning',
          });
        }

        const layoutPayload = {
          viewport: filtered.viewport,
          nodes: filtered.nodes,
          edges: filtered.edges,
        };

        await applyCanvasLayoutPayload({
          layout: layoutPayload,
          layoutNameToSet: parsed.doc.layoutName?.trim() || selectedLayoutName,
          clearGroupsWhenEmpty: true,
        });
      } catch (err) {
        console.error('Error importing layout JSON:', err);
        await alertDialog({
          message: 'An error occurred while importing the layout.',
          variant: 'error',
        });
        setIsLoadingCanvas(false);
        setLoadingMessage('');
        setLayoutDropdownOpen(false);
      }
    },
    [
      selectedVersionId,
      currentUserId,
      isReadOnly,
      alertDialog,
      confirmDialog,
      applyCanvasLayoutPayload,
      selectedLayoutName,
    ]
  );

  const handleRestoreLayoutRevision = useCallback(
    async (revisionId: string) => {
      if (!selectedVersionId || !currentUserId || isReadOnly) return;
      const layoutName = selectedLayoutName.trim();
      if (!layoutName) {
        await alertDialog({
          message: 'Please enter a layout name that matches a saved layout.',
          variant: 'warning',
        });
        return;
      }
      const ok = await confirmDialog({
        title: 'Restore layout version',
        message:
          'Replace the current canvas with this saved version? Your current layout is stored in history first.',
      });
      if (!ok) return;
      try {
        setLoadingMessage('Restoring layout...');
        setIsLoadingCanvas(true);
        const layoutRes = await getNamedCanvasLayout(selectedVersionId, currentUserId, layoutName);
        const layoutParsed = JSON.parse(layoutRes);
        if (!layoutParsed.success || !layoutParsed.layout) {
          await alertDialog({
            message: `No saved "${layoutName}" found for this version`,
            variant: 'warning',
          });
          setIsLoadingCanvas(false);
          setLoadingMessage('');
          return;
        }
        const restoreRes = await restoreCanvasLayoutFromRevision(
          layoutParsed.layout.id,
          revisionId,
          selectedVersionId,
          currentUserId
        );
        const restoreParsed = JSON.parse(restoreRes);
        if (!restoreParsed.success) {
          await alertDialog({
            message: restoreParsed.error || 'Could not restore this version',
            variant: 'error',
          });
          setIsLoadingCanvas(false);
          setLoadingMessage('');
          return;
        }
        await handleLoadLayout();
      } catch (error) {
        console.error('Error restoring layout revision:', error);
        await alertDialog({
          message: 'An error occurred while restoring the layout',
          variant: 'error',
        });
        setIsLoadingCanvas(false);
        setLoadingMessage('');
      }
    },
    [
      selectedVersionId,
      currentUserId,
      isReadOnly,
      selectedLayoutName,
      confirmDialog,
      alertDialog,
      handleLoadLayout,
    ]
  );

  useEffect(() => {
    if (!layoutHistoryOpen || !layoutDropdownOpen || !selectedVersionId || !currentUserId) {
      return;
    }
    let cancelled = false;
    (async () => {
      setLayoutHistoryLoading(true);
      try {
        const name = selectedLayoutName.trim();
        if (!name) {
          if (!cancelled) {
            setLayoutHistoryRevisions([]);
          }
          return;
        }
        const layoutRes = await getNamedCanvasLayout(selectedVersionId, currentUserId, name);
        const parsed = JSON.parse(layoutRes);
        if (!parsed.success || !parsed.layout) {
          if (!cancelled) {
            setLayoutHistoryRevisions([]);
          }
          return;
        }
        const revRes = await listCanvasLayoutRevisions(parsed.layout.id, selectedVersionId, currentUserId);
        const revParsed = JSON.parse(revRes);
        if (!cancelled && revParsed.success) {
          setLayoutHistoryRevisions(revParsed.revisions || []);
        }
      } catch (error) {
        console.error('Error loading layout history:', error);
        if (!cancelled) {
          setLayoutHistoryRevisions([]);
        }
      } finally {
        if (!cancelled) {
          setLayoutHistoryLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    layoutHistoryOpen,
    layoutDropdownOpen,
    selectedVersionId,
    currentUserId,
    selectedLayoutName,
  ]);

  // #471: Preview layout before applying — compute layout and show preview (do not commit)
  const handlePreviewLayout = useCallback((direction: 'TB' | 'LR') => {
    if (nodes.length === 0) return;
    setLayoutDropdownOpen(false);
    try {
      const layoutedNodes = applyAutoLayout(nodes, edges, {
        nodeSpacingX: direction === 'LR' ? 150 : 100,
        nodeSpacingY: direction === 'LR' ? 100 : 150,
        direction: direction,
        padding: 80,
        centerNodes: true,
        minimizeCrossings: true,
      });
      setLayoutPreviewNodes(layoutedNodes);
      setLayoutPreviewLabel(direction === 'TB' ? 'Top to Bottom' : 'Left to Right');
    } catch (error) {
      console.error('Error computing layout preview:', error);
    }
  }, [nodes, edges]);

  // #471: Apply the previewed layout (commit and sync groups)
  const handleApplyLayoutPreview = useCallback(() => {
    if (!layoutPreviewNodes) return;
    setNodes(layoutPreviewNodes);
    const updatedGroupNodes = layoutPreviewNodes.filter(n => n.type === 'groupNode');
    if (updatedGroupNodes.length > 0 && groups.length > 0) {
      const updatedGroups = groups.map(group => {
        const groupNode = updatedGroupNodes.find(n => n.id === group.id);
        if (groupNode) {
          groupPositionsRef.current.set(groupNode.id, { x: groupNode.position.x, y: groupNode.position.y });
          return {
            ...group,
            position: groupNode.position,
            dimensions: {
              width: (groupNode.style as any)?.width || (groupNode.data as any)?.width || group.dimensions?.width || 300,
              height: (groupNode.style as any)?.height || (groupNode.data as any)?.height || group.dimensions?.height || 200,
            },
          };
        }
        return group;
      });
      setGroups(updatedGroups);
    }
    setTimeout(() => fitView({ padding: 0.1, duration: 300 }), 100);
    setLayoutPreviewNodes(null);
    setLayoutPreviewLabel('');
  }, [layoutPreviewNodes, groups, setNodes, setGroups, fitView]);

  // #471: Cancel layout preview and revert to current positions
  const handleCancelLayoutPreview = useCallback(() => {
    setLayoutPreviewNodes(null);
    setLayoutPreviewLabel('');
  }, []);

  // Fit view to previewed layout when entering preview mode so user sees full suggestion
  useEffect(() => {
    if (!layoutPreviewNodes?.length) return;
    const t = setTimeout(() => fitView({ padding: 0.1, duration: 300 }), 150);
    return () => clearTimeout(t);
  }, [layoutPreviewNodes, fitView]);

  // Auto-arrange Top to Bottom — show preview first (#471)
  const handleAutoArrangeTB = useCallback(() => {
    handlePreviewLayout('TB');
  }, [handlePreviewLayout]);

  // Auto-arrange Left to Right — show preview first (#471)
  const handleAutoArrangeLR = useCallback(() => {
    handlePreviewLayout('LR');
  }, [handlePreviewLayout]);

  // Legacy handler - defaults to Top to Bottom
  const handleAutoArrange = useCallback(() => {
    handlePreviewLayout('TB');
  }, [handlePreviewLayout]);

  // Suggestion action: e.g. apply hierarchical layout when user clicks "Try Auto-organize" (#474, #471 preview)
  const handleSuggestionAction = useCallback(
    (suggestion: { action?: { type: string; direction?: 'TB' | 'LR' } }) => {
      if (suggestion.action?.type === 'apply_hierarchical_layout') {
        handlePreviewLayout(suggestion.action.direction ?? 'TB');
      }
    },
    [handlePreviewLayout]
  );

  // ============================================================================
  // END LAYOUT SAVE/LOAD HANDLERS
  // ============================================================================

  // Use extracted export functions hook (legacy - kept for backward compatibility)
  const {
    handleExportPng,
    handleExportSvg,
    handleExportJpeg,
    handleExportPdf,
    handleExportMermaid,
    handleExportPlantUml,
    handleExportDot,
    handleExportGraphMl,
    handleExportJson,
  } = useExportFunctions({
    projects,
    versions,
    selectedProjectId,
    selectedVersionId,
    nodes,
    edges,
    isDark,
    alertDialog,
    setLoadingMessage,
    setIsLoadingCanvas,
    setExportDropdownOpen: setExportWizardOpen, // Use the wizard state
  });

  // Define custom node types
  const nodeTypes = {
    classNode: ClassNode,
    groupNode: GroupNode,
  };

  // Define custom edge types (wide hit area for easier hover on default/straight/smoothstep)
  const edgeTypes = {
    default: EdgeWithWideHit,
    straight: EdgeWithWideHit,
    smoothstep: EdgeWithWideHit,
    smart: SmartEdge,
  };

  // Helper function to convert classes to React Flow nodes
  const classesToNodes = async (classes: any[]): Promise<Node[]> => {
    return classes.map((cls, index) => {
      // Extract theme from canvas_metadata if it exists
      const canvasMetadata = cls.canvas_metadata || {};
      const theme = canvasMetadata.style || {};

      return {
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
          updated_at: cls.updated_at, // For heatmap: change frequency (#560)
          theme: theme, // Pass theme from canvas_metadata
          // Use refs to avoid triggering re-renders when callbacks change
          onPropertyDrop: (...args: any[]) => handlePropertyDropRef.current?.(...args),
          onPropertyEdit: (...args: any[]) => handlePropertyEditRef.current?.(...args),
          onPropertyDelete: (...args: any[]) => handlePropertyDeleteRef.current?.(...args),
          onClassEdit: (...args: any[]) => handleClassEditRef.current?.(...args),
          onClassDelete: (...args: any[]) => handleClassDeleteRef.current?.(...args),
          onCreateReference: (...args: any[]) => handleCreateReferenceRef.current?.(...args),
          onThemeChange: (...args: any[]) => handleThemeChangeRef.current?.(...args),
          onToggleVisibility: (classId: string, visible?: boolean) => setClassVisibility(classId, visible),
          isReadOnly: isReadOnly,
          expandedProperties: globalExpandedProperties,
          onTogglePropertyExpansion: (...args: any[]) => handleTogglePropertyExpansionRef.current?.(...args),
          zoomLevel: 1 // Initial zoom level
        }
      };
    });
  };

  // Helper function to extract class name from $ref
  const extractClassNameFromRef = (ref: string): string | null => {
    if (ref.includes('/')) {
      const parts = ref.split('/');
      return parts[parts.length - 1] || null;
    }
    return ref;
  };

  // Helper function to get React Flow edge type from routing setting
  const getEdgeType = (): string => {
    switch (edgeRouting) {
      case 'straight':
        return 'straight';
      case 'bezier':
        return 'default'; // React Flow's default is bezier
      case 'orthogonal':
        return 'smoothstep'; // smoothstep creates orthogonal paths
      case 'smart':
        return 'smart'; // Custom SmartEdge that avoids node overlap
      default:
        return 'default';
    }
  };

  // Helper function to check if edges should be animated
  const shouldAnimateEdges = (): boolean => {
    return edgeAnimation !== 'none';
  };

  // Helper function to get animation class name based on animation type
  const getAnimationClassName = (): string => {
    switch (edgeAnimation) {
      case 'flow':
        return 'edge-animation-flow';
      case 'pulse':
        return 'edge-animation-pulse';
      case 'dash':
        return 'edge-animation-dash';
      default:
        return '';
    }
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
                  type: getEdgeType(),
                  animated: false,
                  label: `${prop.name} (${label}:${refClassName}${isSourceArray ? '[]' : ''})`,
                  data: { sourceNodeId: cls.id, targetNodeId: targetClassId },
                  style: {
                    stroke: edgeColor,
                    strokeWidth: 3,
                    strokeDasharray
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
                  zIndex: 0
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
          if (propData.items.anyOf && Array.isArray(propData.items.anyOf)) {
            createCompositionEdges('anyOf', propData.items.anyOf);
            return;
          }
          if (propData.items.oneOf && Array.isArray(propData.items.oneOf)) {
            createCompositionEdges('oneOf', propData.items.oneOf);
            return;
          }
          if (propData.items.allOf && Array.isArray(propData.items.allOf)) {
            createCompositionEdges('allOf', propData.items.allOf);
            return;
          }
        }

        // Check for direct $ref (existing logic)
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

              if (targetRefName === cls.name) {
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
            type: getEdgeType(),
            animated: false,
            label: `${prop.name} (${cardinality})`,
            data: { sourceNodeId: cls.id, targetNodeId: targetClassId },
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

    // Apply edge styling based on user preferences
    return edges.map(edge => applyEdgeStyling(edge, edgeStyling));
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
              const targetId = classNameToId.get(refClassName)!;
              edges.push({
                id: `allOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: targetId,
                type: getEdgeType(),
                animated: false,
                label: `allOf:${refClassName}`,
                data: { sourceNodeId: cls.id, targetNodeId: targetId },
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
                // Add Z-index to layer edges below nodes
                zIndex: 0
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
              const targetId = classNameToId.get(refClassName)!;
              edges.push({
                id: `anyOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: targetId,
                type: getEdgeType(),
                animated: false,
                label: `anyOf:${refClassName}`,
                data: { sourceNodeId: cls.id, targetNodeId: targetId },
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
                zIndex: 0
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
              const targetId = classNameToId.get(refClassName)!;
              edges.push({
                id: `oneOf-${cls.id}-${refClassName}-${index}`,
                source: cls.id,
                sourceHandle: 'comp-bottom', // Use single composition handle
                target: targetId,
                type: getEdgeType(),
                animated: false,
                label: `oneOf:${refClassName}`,
                data: { sourceNodeId: cls.id, targetNodeId: targetId },
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

    // Apply edge styling based on user preferences
    return edges.map(edge => applyEdgeStyling(edge, edgeStyling));
  };

  // Helper function to create all edges (properties + composition)
  const createAllEdges = (classes: any[]): Edge[] => {
    const propertyEdges = createPropertyRefEdges(classes);
    const compositionEdges = createCompositionEdges(classes);
    const allEdges = [...propertyEdges, ...compositionEdges];

    // Apply animation to all edges based on user preference
    return allEdges.map(edge => ({
      ...edge,
      animated: shouldAnimateEdges(),
      className: getAnimationClassName(),
    }));
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


  // Handle clicking outside layout dropdown to close it
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (layoutDropdownRef.current && !layoutDropdownRef.current.contains(event.target as HTMLElement)) {
        setLayoutDropdownOpen(false);
      }
    };

    if (layoutDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [layoutDropdownOpen]);

  useEffect(() => {
    if (!layoutDropdownOpen) {
      setLayoutHistoryOpen(false);
    }
  }, [layoutDropdownOpen]);

  // Load versions when project is selected
  useEffect(() => {
    if (selectedProjectId) {
      loadVersions(selectedProjectId);
    } else {
      setVersions([]);
      setSelectedVersionId('');
      setContextVersionId('');
      setIsReadOnly(false); // Reset read-only flag when no project is selected
    }
  }, [selectedProjectId]);

  // Apply projectId/versionId from URL (e.g. after "View on Canvas" from import complete)
  const urlVersionIdAppliedRef = useRef(false);
  useEffect(() => {
    const projectId = searchParams.get('projectId');
    const versionId = searchParams.get('versionId');
    if (!projectId) return;
    if (selectedProjectId !== projectId) {
      setSelectedProjectId(projectId);
    }
    if (versionId && selectedProjectId === projectId && versions.length > 0) {
      const versionExists = versions.some((v) => v.id === versionId);
      if (versionExists && !urlVersionIdAppliedRef.current) {
        urlVersionIdAppliedRef.current = true;
        setSelectedVersionId(versionId);
      }
    }
  }, [searchParams, selectedProjectId, versions, setSelectedProjectId, setSelectedVersionId]);
  useEffect(() => {
    if (!searchParams.get('projectId') || !searchParams.get('versionId')) {
      urlVersionIdAppliedRef.current = false;
    }
  }, [searchParams]);

  // Load classes and render them on canvas when version changes or canvas refresh is triggered
  useEffect(() => {
    const loadClasses = async () => {
      if (!selectedVersionId) {
        setNodes([]);
        setEdges([]);
        setGroups([]);
        return;
      }

      // Check if this is the first load for this version
      const isFirstLoad = initialLayoutAppliedRef.current !== selectedVersionId;

      setIsLoadingCanvas(true);
      setLoadingMessage('Loading classes, properties, and tags...');

      try {
        // Bulk load all classes with properties and tags via REST API
        const result = await getClassesWithPropertiesAndTagsWithSession(selectedVersionId);
        if (!result.success) {
          console.error('Failed to load classes:', result.error);
          return;
        }
        const classesWithProperties = result.classes || [];

        setLoadingMessage('Updating nodes and edges...');

        // Create new nodes
        const newNodes = await classesToNodes(classesWithProperties);

        // Preserve existing node positions if they exist (using functional state read)
        setNodes((currentNodes) => {
          if (currentNodes.length > 0) {
            const existingPositions = new Map(currentNodes.map(n => [n.id, n.position]));
            newNodes.forEach(node => {
              const existingPos = existingPositions.get(node.id);
              if (existingPos) {
                node.position = existingPos;
              }
            });
          }
          return currentNodes; // Return current for now, will set after loading groups
        });

        const newEdges = createAllEdges(classesWithProperties);
        setEdges(newEdges);

        // Load groups from database
        setLoadingMessage('Loading groups...');
        let groupNodes: Node[] = [];
        let classPositionsInGroups: Record<string, { x: number | null; y: number | null }> = {};

        try {
          const groupsResult = await getGroupsForVersion(selectedVersionId);
          let loadedGroups = JSON.parse(groupsResult);

          if (loadedGroups && Array.isArray(loadedGroups) && loadedGroups.length > 0) {
            // Extract class positions from all groups
            loadedGroups.forEach((g: any) => {
              if (g.classPositions) {
                Object.assign(classPositionsInGroups, g.classPositions);
              }
            });

            // Transform to CanvasGroup format and set in context
            const availableTags = projectTags.map(t => ({ id: t.id, name: t.tag_name, color: t.tag_color }));
            const canvasGroups = loadedGroups.map((g: any) => ({
              id: g.id,
              name: g.name,
              description: g.description,
              color: g.color,
              position: g.position,
              dimensions: g.dimensions,
              nodeIds: g.nodeIds || [],
              parentId: g.parentId ?? null,
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

            // Initialize group positions ref for delta tracking during drag
            canvasGroups.forEach((group: any) => {
              groupPositionsRef.current.set(group.id, { x: group.position.x, y: group.position.y });
            });

            // Create group nodes for ReactFlow
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
                  parentId: group.parentId ?? null,
                  tags: group.metadata?.tags || [],
                  styleOptions: {
                    borderStyle: group.borderStyle || 'dashed',
                    opacity: group.opacity ?? 1,
                    shadow: group.metadata?.shadow || 'none',
                    icon: group.metadata?.icon || 'folder'
                  },
                  availableTags,
                  onRename: (groupId: string, name: string) => handleGroupRenameRef.current?.(groupId, name),
                  onDelete: (groupId: string) => handleGroupDeleteRef.current?.(groupId),
                  onDeleteAllClassesInGroup: (gid: string, cids?: string[], gn?: string) =>
                    handleDeleteAllClassesInGroupRef.current?.(gid, cids, gn),
                  onExportGroupSchema: (gid: string, cids: string[], gn: string, fmt: 'json' | 'yaml') =>
                    handleExportGroupSchemaRef.current?.(gid, cids, gn, fmt),
                  onDuplicateGroup: (gid: string, cids: string[], gn: string) =>
                    handleDuplicateGroupRef.current?.(gid, cids, gn),
                  onBulkEditGroupClasses: (
                    gid: string,
                    cids: string[],
                    gn: string,
                    opts: {
                      descriptionPrefix?: string;
                      descriptionSuffix?: string;
                      tagId?: string;
                      topLevelPropertyReadOnly?: boolean;
                    }
                  ) => handleBulkEditGroupClassesRef.current?.(gid, cids, gn, opts),
                  onColorChange: (groupId: string, color: string) => handleGroupColorChangeRef.current?.(groupId, color),
                  onStyleChange: (groupId: string, style: any) => handleGroupStyleChangeRef.current?.(groupId, style),
                  onTagsChange: (groupId: string, tags: any[]) => handleGroupTagsChangeRef.current?.(groupId, tags),
                  onDrillInto: () => handleDrillIntoNestedGroupRef.current(group.id),
                  isReadOnly
                }
              };
              groupNodes.push(groupNode);
            });
          } else {
            // No groups found, clear groups
            setGroups([]);
          }
        } catch (error) {
          console.error('Error loading groups:', error);
          setGroups([]);
        }

        // Apply class positions from groups if available
        let finalNodes = newNodes.map(node => {
          if (classPositionsInGroups[node.id]) {
            const savedPos = classPositionsInGroups[node.id];
            if (savedPos.x !== null && savedPos.y !== null) {
              return {
                ...node,
                position: { x: savedPos.x, y: savedPos.y }
              };
            }
          }
          return node;
        });

        // On first load, resolve default layout name (user → tenant → built-in), then load that named layout if present
        if (isFirstLoad && currentUserId) {
          setLoadingMessage('Checking for saved layout...');
          let layoutNameForInitialLoad = selectedLayoutNameRef.current.trim();
          try {
            const prefResult = await getEffectiveDefaultLayoutName(
              selectedVersionId,
              currentUserId,
              currentTenantId || undefined
            );
            const prefParsed = JSON.parse(prefResult);
            if (prefParsed.success && prefParsed.layoutName && typeof prefParsed.layoutName === 'string') {
              layoutNameForInitialLoad = prefParsed.layoutName.trim();
              if (layoutNameForInitialLoad) {
                setSelectedLayoutName(layoutNameForInitialLoad);
                selectedLayoutNameRef.current = layoutNameForInitialLoad;
              }
            }
          } catch {
            // keep ref/default name
          }
          if (layoutNameForInitialLoad) {
            try {
              const layoutResult = await getNamedCanvasLayout(
                selectedVersionId,
                currentUserId,
                layoutNameForInitialLoad
              );
              const layoutResponse = JSON.parse(layoutResult);

              if (layoutResponse.success && layoutResponse.layout) {
                const savedLayout = layoutResponse.layout;
                setLoadingMessage('Applying saved layout...');

                // Apply saved viewport
                if (savedLayout.viewport) {
                  setViewport(
                    { x: savedLayout.viewport.x, y: savedLayout.viewport.y, zoom: savedLayout.viewport.zoom },
                    { duration: 250 }
                  );
                }

                // Apply saved node positions
                if (savedLayout.nodes && Array.isArray(savedLayout.nodes)) {
                  const savedPositions = new Map<string, { x: number; y: number }>(
                    savedLayout.nodes.map((n: any) => [n.id, n.position])
                  );
                  finalNodes = finalNodes.map(node => {
                    // First check if position is in classPositionsInGroups (groups take priority)
                    if (classPositionsInGroups[node.id]) {
                      const savedPos = classPositionsInGroups[node.id];
                      if (savedPos.x !== null && savedPos.y !== null) {
                        return node; // Already has group position
                      }
                    }
                    // Otherwise apply saved layout position
                    const savedPos = savedPositions.get(node.id);
                    if (savedPos && typeof savedPos.x === 'number' && typeof savedPos.y === 'number') {
                      return { ...node, position: { x: savedPos.x, y: savedPos.y } };
                    }
                    return node;
                  }) as Node[];
                }

                setHasExistingLayout(true);
              }
            } catch (error) {
              console.error('Error loading saved layout on first load:', error);
            }
          }

          // Mark that initial layout has been applied for this version
          initialLayoutAppliedRef.current = selectedVersionId;
        }

        // Set nodes with group nodes first (behind class nodes due to zIndex: -1)
        setNodes([...groupNodes, ...finalNodes]);

        // Update node internals for all class nodes to ensure handle positions are correct
        // This is needed after initial load because node sizes may vary based on content
        requestAnimationFrame(() => {
          setTimeout(() => {
            finalNodes.forEach(node => {
              updateNodeInternals(node.id);
            });
          }, 100);
        });

        // Trigger sidebar refresh to update groups list
        triggerSidebarRefresh();
      } catch (error) {
        console.error('Failed to reload classes:', error);
      } finally {
        setIsLoadingCanvas(false);
        setLoadingMessage('');
      }
    };

    loadClasses();
  }, [selectedVersionId, selectedProjectId, canvasRefreshKey, projects, versions, currentUserId, currentTenantId, projectTags, isReadOnly, updateNodeInternals, setViewport]);

  // Check layout availability when version or selected layout changes
  useEffect(() => {
    const checkLayoutExists = async () => {
      if (!selectedVersionId || !currentUserId) {
        setHasExistingLayout(false);
        setAvailableLayoutNames(BUILTIN_LAYOUT_NAMES);
        setNamedLayoutSnapshotDataUrls({});
        return;
      }

      try {
        const allLayoutsResult = await getNamedCanvasLayoutsForVersion(
          selectedVersionId,
          currentUserId
        );
        const allLayoutsResponse = JSON.parse(allLayoutsResult);
        const dbLayoutNames = (allLayoutsResponse.layouts || [])
          .map((layout: any) => layout.name)
          .filter((name: string | null): name is string => Boolean(name));
        setAvailableLayoutNames(
          Array.from(new Set([...BUILTIN_LAYOUT_NAMES, ...dbLayoutNames]))
        );

        const snapMap: Record<string, string> = {};
        for (const layout of allLayoutsResponse.layouts || []) {
          const n = typeof layout.name === 'string' ? layout.name.trim() : '';
          if (n && layout.snapshotImageBase64) {
            snapMap[n] = `data:image/png;base64,${layout.snapshotImageBase64}`;
          }
        }
        setNamedLayoutSnapshotDataUrls(snapMap);

        const trimmedSelection = selectedLayoutName.trim();
        const hasExistingLayoutForSelection =
          !!trimmedSelection &&
          (allLayoutsResponse.layouts || []).some(
            (layout: any) => layout.name === trimmedSelection
          );
        setHasExistingLayout(hasExistingLayoutForSelection);
      } catch (error) {
        console.error('Error checking layout existence:', error);
        setHasExistingLayout(false);
        setAvailableLayoutNames(BUILTIN_LAYOUT_NAMES);
        setNamedLayoutSnapshotDataUrls({});
      }
    };

    checkLayoutExists();
  }, [selectedVersionId, currentUserId, selectedLayoutName, BUILTIN_LAYOUT_NAMES]);

  // Regenerate edges when edge styling or routing preferences change
  useEffect(() => {
    if (!selectedVersionId) return;

    // Use functional setState to access current nodes
    setNodes((currentNodes) => {
      if (currentNodes.length > 0) {
        // Extract class data from nodes
        const classesWithProperties = currentNodes
          .filter(n => n.type !== 'groupNode')
          .map(node => ({
            id: node.id,
            name: (node.data as any).name,
            properties: (node.data as any).properties || [],
            schema: (node.data as any).schema,
          }));

        // Regenerate edges with new styling/routing
        const newEdges = createAllEdges(classesWithProperties);
        setEdges(newEdges);
      }
      return currentNodes; // No change to nodes
    });
  }, [edgeStyling, edgeRouting, edgeAnimation, selectedVersionId]);

  // Generate specs on-demand when switching views or when canvas changes
  useEffect(() => {
    const generateSpec = async () => {
      if (!selectedVersionId || viewMode !== 'code') return;

      try {
        // Get current nodes using functional state access
        let classesWithProperties: any[] = [];
        setNodes((currentNodes) => {
          classesWithProperties = currentNodes
            .filter(n => n.type !== 'groupNode')
            .map(node => ({
              id: node.id,
              name: (node.data as any).name,
              description: (node.data as any).description,
              properties: (node.data as any).properties || [],
              schema: (node.data as any).schema,
              tags: (node.data as any).tags || []
            }));
          return currentNodes; // No change
        });

        if (classesWithProperties.length === 0) return;

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
  }, [viewMode, codeDisplayFormat, selectedVersionId, selectedProjectId, projects, versions]);

  const loadProjects = async () => {
    if (!currentTenantId) return;

    setIsLoadingProjects(true);
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) {
        throw new Error(`Failed to fetch projects: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.projects) {
        setProjects(data.projects);
      } else {
        throw new Error(data.error || 'Failed to load projects');
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
      setProjects([]);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const loadVersions = async (projectId: string) => {
    setIsLoadingVersions(true);
    try {
      const response = await fetch(`/api/versions?projectId=${projectId}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch versions: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.versions) {
        setVersions(data.versions);

        // Auto-select the first version if available
        if (data.versions.length > 0) {
          const firstVersion = data.versions[0];
          setSelectedVersionId(firstVersion.id);
          setIsReadOnly(firstVersion.published || false);
        }
      } else {
        throw new Error(data.error || 'Failed to load versions');
      }
    } catch (error) {
      console.error('Failed to load versions:', error);
      setVersions([]);
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
            const response = JSON.parse(res);
            if (!response.success) {
              await alertDialog({
                message: response.error || 'Failed to update property reference',
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
        setAutoSavePending(true);
      } catch (e) {
        console.error('onConnect failed:', e);
      }
    },
    [setEdges, reloadClasses, triggerSidebarRefresh]
  );

  const onNodeClick = useCallback((event: React.MouseEvent, node: any) => {
    console.log('Clicked node:', node);
    console.log('clickToFocusEnabled value:', clickToFocusEnabled);

    // If click-to-focus is enabled, zoom to the clicked node
    if (clickToFocusEnabled) {
      console.log('Zooming to class:', node.id);
      zoomToClass(node.id);
    } else {
      console.log('Click-to-focus is disabled, skipping zoom');
    }
  }, [clickToFocusEnabled, zoomToClass]);

  const onEdgeClick = useCallback((event: React.MouseEvent, edge: Edge) => {
    console.log('Clicked edge:', edge);
  }, []);

  // #349: Edge hover – show tooltip and track position for highlighting
  const onEdgeMouseEnter = useCallback((event: React.MouseEvent, edge: Edge) => {
    setHoveredEdgeId(edge.id);
    setEdgeTooltipPosition({ x: event.clientX, y: event.clientY });
  }, []);
  const onEdgeMouseLeave = useCallback(() => {
    setHoveredEdgeId(null);
    setEdgeTooltipPosition(null);
  }, []);

  // #349: Update edge tooltip position to follow cursor while hovering
  useEffect(() => {
    if (!hoveredEdgeId) return;
    const handleMove = (e: MouseEvent) => setEdgeTooltipPosition({ x: e.clientX, y: e.clientY });
    window.addEventListener('mousemove', handleMove);
    return () => window.removeEventListener('mousemove', handleMove);
  }, [hoveredEdgeId]);

  // Handle selection change for spacing tools
  const onSelectionChange = useCallback(({ nodes: selectedNodes }: { nodes: Node[] }) => {
    const classNodeIds = selectedNodes
      .filter(n => n.type !== 'groupNode')
      .map(n => n.id);
    setSelectedNodeIds(classNodeIds);

    // Update spacing indicators when selection changes
    if (showSpacingIndicators && classNodeIds.length >= 2) {
      calculateSpacingIndicators(classNodeIds);
    } else {
      setSpacingIndicators({ horizontal: [], vertical: [] });
    }
  }, [showSpacingIndicators]);

  // Calculate spacing indicators between selected nodes
  const calculateSpacingIndicators = useCallback((nodeIds: string[]) => {
    const selectedNodes = nodes.filter(n => nodeIds.includes(n.id) && n.type !== 'groupNode');
    if (selectedNodes.length < 2) {
      setSpacingIndicators({ horizontal: [], vertical: [] });
      return;
    }

    // Sort by X position for horizontal spacing
    const sortedByX = [...selectedNodes].sort((a, b) => a.position.x - b.position.x);
    // Sort by Y position for vertical spacing
    const sortedByY = [...selectedNodes].sort((a, b) => a.position.y - b.position.y);

    const horizontal: Array<{ x1: number; x2: number; y: number; distance: number }> = [];
    const vertical: Array<{ y1: number; y2: number; x: number; distance: number }> = [];

    // Calculate horizontal gaps
    for (let i = 0; i < sortedByX.length - 1; i++) {
      const current = sortedByX[i];
      const next = sortedByX[i + 1];
      const currentWidth = (current.measured?.width as number) || (current.width as number) || 260;
      const currentRight = current.position.x + currentWidth;
      const nextLeft = next.position.x;
      const gap = nextLeft - currentRight;

      if (gap > 0) {
        const currentHeight = (current.measured?.height as number) || (current.height as number) || 200;
        const nextHeight = (next.measured?.height as number) || (next.height as number) || 200;
        const avgY = (current.position.y + currentHeight / 2 + next.position.y + nextHeight / 2) / 2;

        horizontal.push({
          x1: currentRight,
          x2: nextLeft,
          y: avgY,
          distance: Math.round(gap)
        });
      }
    }

    // Calculate vertical gaps
    for (let i = 0; i < sortedByY.length - 1; i++) {
      const current = sortedByY[i];
      const next = sortedByY[i + 1];
      const currentHeight = (current.measured?.height as number) || (current.height as number) || 200;
      const currentBottom = current.position.y + currentHeight;
      const nextTop = next.position.y;
      const gap = nextTop - currentBottom;

      if (gap > 0) {
        const currentWidth = (current.measured?.width as number) || (current.width as number) || 260;
        const nextWidth = (next.measured?.width as number) || (next.width as number) || 260;
        const avgX = (current.position.x + currentWidth / 2 + next.position.x + nextWidth / 2) / 2;

        vertical.push({
          y1: currentBottom,
          y2: nextTop,
          x: avgX,
          distance: Math.round(gap)
        });
      }
    }

    setSpacingIndicators({ horizontal, vertical });
  }, [nodes]);

  // Distribute nodes with equal horizontal spacing
  const distributeHorizontal = useCallback(() => {
    if (selectedNodeIds.length < 3) return;

    const selectedNodes = nodes.filter(n => selectedNodeIds.includes(n.id) && n.type !== 'groupNode');
    if (selectedNodes.length < 3) return;

    // Sort by X position
    const sorted = [...selectedNodes].sort((a, b) => a.position.x - b.position.x);

    // Get first and last node positions
    const firstNode = sorted[0];
    const lastNode = sorted[sorted.length - 1];
    const lastWidth = (lastNode.measured?.width as number) || (lastNode.width as number) || 260;

    // Calculate total width and total spacing needed
    const totalWidth = sorted.reduce((sum, n) => {
      const w = (n.measured?.width as number) || (n.width as number) || 260;
      return sum + w;
    }, 0);

    const startX = firstNode.position.x;
    const endX = lastNode.position.x + lastWidth;
    const availableSpace = endX - startX - totalWidth;
    const gap = availableSpace / (sorted.length - 1);

    // Update node positions
    let currentX = startX;
    const updates: { id: string; position: { x: number; y: number } }[] = [];

    sorted.forEach((node, index) => {
      const width = (node.measured?.width as number) || (node.width as number) || 260;
      updates.push({
        id: node.id,
        position: { x: currentX, y: node.position.y }
      });
      currentX += width + gap;
    });

    setNodes(prevNodes => prevNodes.map(n => {
      const update = updates.find(u => u.id === n.id);
      return update ? { ...n, position: update.position } : n;
    }));

    // Recalculate indicators
    if (showSpacingIndicators) {
      setTimeout(() => calculateSpacingIndicators(selectedNodeIds), 50);
    }
  }, [selectedNodeIds, nodes, setNodes, showSpacingIndicators, calculateSpacingIndicators]);

  // Distribute nodes with equal vertical spacing
  const distributeVertical = useCallback(() => {
    if (selectedNodeIds.length < 3) return;

    const selectedNodes = nodes.filter(n => selectedNodeIds.includes(n.id) && n.type !== 'groupNode');
    if (selectedNodes.length < 3) return;

    // Sort by Y position
    const sorted = [...selectedNodes].sort((a, b) => a.position.y - b.position.y);

    // Get first and last node positions
    const firstNode = sorted[0];
    const lastNode = sorted[sorted.length - 1];
    const lastHeight = (lastNode.measured?.height as number) || (lastNode.height as number) || 200;

    // Calculate total height and total spacing needed
    const totalHeight = sorted.reduce((sum, n) => {
      const h = (n.measured?.height as number) || (n.height as number) || 200;
      return sum + h;
    }, 0);

    const startY = firstNode.position.y;
    const endY = lastNode.position.y + lastHeight;
    const availableSpace = endY - startY - totalHeight;
    const gap = availableSpace / (sorted.length - 1);

    // Update node positions
    let currentY = startY;
    const updates: { id: string; position: { x: number; y: number } }[] = [];

    sorted.forEach((node, index) => {
      const height = (node.measured?.height as number) || (node.height as number) || 200;
      updates.push({
        id: node.id,
        position: { x: node.position.x, y: currentY }
      });
      currentY += height + gap;
    });

    setNodes(prevNodes => prevNodes.map(n => {
      const update = updates.find(u => u.id === n.id);
      return update ? { ...n, position: update.position } : n;
    }));

    // Recalculate indicators
    if (showSpacingIndicators) {
      setTimeout(() => calculateSpacingIndicators(selectedNodeIds), 50);
    }
  }, [selectedNodeIds, nodes, setNodes, showSpacingIndicators, calculateSpacingIndicators]);

  // Toggle spacing indicators
  const toggleSpacingIndicators = useCallback(() => {
    const newValue = !showSpacingIndicators;
    setShowSpacingIndicators(newValue);
    if (newValue && selectedNodeIds.length >= 2) {
      calculateSpacingIndicators(selectedNodeIds);
    } else {
      setSpacingIndicators({ horizontal: [], vertical: [] });
    }
  }, [showSpacingIndicators, selectedNodeIds, calculateSpacingIndicators]);

  const selectedProject = projects.find(p => p.id === selectedProjectId);
  const selectedVersion = versions.find(v => v.id === selectedVersionId);

  // Show tenant selection prompt if no tenant is selected
  if (!currentTenantId) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-gray-50 dark:bg-gray-900">
        <div className="text-center max-w-md px-6">
          <Building2 className="mx-auto h-16 w-16 text-gray-400 dark:text-gray-600 mb-4" />
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
            No Tenant Selected
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Please select a tenant to get started with the Designer. You&apos;ll need to choose a tenant before you can manage projects, versions, and schemas.
          </p>
          <button
            onClick={() => window.location.href = '/ade/dashboard/tenants'}
            className="inline-flex items-center px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            <ChevronRight className="mr-2 h-5 w-5" />
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
        <style jsx global>{`
          /* #349 Edge hover - cursor to show interactivity */
          .react-flow__edge {
            cursor: pointer;
          }
          /* Edge Animation Styles */
          .react-flow__edge.edge-animation-flow .react-flow__edge-path {
            stroke-dasharray: 5;
            animation: edge-flow 1s linear infinite;
          }
          .react-flow__edge.edge-animation-pulse .react-flow__edge-path {
            animation: edge-pulse 2s ease-in-out infinite;
          }
          .react-flow__edge.edge-animation-dash .react-flow__edge-path {
            stroke-dasharray: 10 5;
            animation: edge-dash 0.5s linear infinite;
          }
          @keyframes edge-flow {
            0% {
              stroke-dashoffset: 24;
            }
            100% {
              stroke-dashoffset: 0;
            }
          }
          @keyframes edge-pulse {
            0%, 100% {
              stroke-opacity: 1;
              stroke-width: 2;
            }
            50% {
              stroke-opacity: 0.5;
              stroke-width: 4;
            }
          }
          @keyframes edge-dash {
            0% {
              stroke-dashoffset: 15;
            }
            100% {
              stroke-dashoffset: 0;
            }
          }

          /* Canvas search - dim non-matching nodes */
          .react-flow__node.search-dimmed {
            opacity: 0.25 !important;
            filter: grayscale(50%) !important;
            transition: opacity 0.2s ease, filter 0.2s ease !important;
          }
          .react-flow__node.search-highlighted {
            opacity: 1 !important;
            filter: none !important;
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.5), 0 0 20px rgba(99, 102, 241, 0.3) !important;
            transition: opacity 0.2s ease, filter 0.2s ease, box-shadow 0.2s ease !important;
          }
          /* Also dim edges connected to dimmed nodes */
          .react-flow__edge.search-dimmed path {
            opacity: 0.15 !important;
            transition: opacity 0.2s ease !important;
          }

          /* Focus mode (#487) - dim and blur non-focused nodes */
          .react-flow__node.focus-dimmed {
            opacity: 0.2 !important;
            filter: blur(2px) grayscale(60%) !important;
            transition: opacity 0.2s ease, filter 0.2s ease !important;
            pointer-events: none !important;
          }
          .react-flow__edge.focus-dimmed path {
            opacity: 0.12 !important;
            stroke-dasharray: 4 4 !important;
            transition: opacity 0.2s ease !important;
          }

          /* #484 Node ghosts — hidden-by-filter nodes still drawn */
          .react-flow__node.canvas-node-ghost {
            opacity: 0.38 !important;
            transition: opacity 0.2s ease !important;
          }
          .react-flow__edge.canvas-edge-ghost path {
            opacity: 0.35 !important;
            transition: opacity 0.2s ease !important;
          }

          /* #547 Dependency graph overlay */
          .react-flow__node.dependency-dimmed {
            opacity: 0.2 !important;
            filter: grayscale(70%) !important;
            transition: opacity 0.2s ease, filter 0.2s ease !important;
          }
          .react-flow__edge.dependency-dimmed path {
            opacity: 0.12 !important;
            transition: opacity 0.2s ease !important;
          }
          .react-flow__edge.dependency-highlight path {
            stroke-width: 3 !important;
            filter: drop-shadow(0 0 4px rgba(99, 102, 241, 0.5)) !important;
            transition: stroke-width 0.2s ease, filter 0.2s ease !important;
          }

          /* #548 Circular dependency warning */
          .react-flow__edge.circular-warning path {
            stroke: #f59e0b !important;
            stroke-width: 2.5 !important;
            stroke-dasharray: 6 4 !important;
            animation: circular-warning-pulse 2s ease-in-out infinite;
          }
          @keyframes circular-warning-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.75; }
          }

          /* #550 Impact Analysis – dim nodes/edges not in source or affected set */
          .react-flow__node.impact-dimmed {
            opacity: 0.25 !important;
            filter: grayscale(80%) !important;
            transition: opacity 0.2s ease, filter 0.2s ease !important;
          }
          .react-flow__edge.impact-dimmed path {
            opacity: 0.15 !important;
            transition: opacity 0.2s ease !important;
          }
        `}</style>

      {/* Header with Project and Version Selectors — hidden in canvas presentation mode (#517) */}
      {!canvasPresentationActive && (
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
                <Folder className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                <Select.Value placeholder="Select project..." />
                <Select.Icon className="ml-auto">
                  <ChevronDown className="w-4 h-4 text-gray-400" />
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
                <Tag className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                <Select.Value placeholder="Select version..." />
                <Select.Icon className="ml-auto">
                  <ChevronDown className="w-4 h-4 text-gray-400" />
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
                  <Layout className="w-4 h-4" />
                  Canvas
                </ToggleGroup.Item>
                <ToggleGroup.Item
                  value="code"
                  className="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  <Code2 className="w-4 h-4" />
                  Code
                </ToggleGroup.Item>
              </ToggleGroup.Root>

              {/* Manage Tags Button */}
              <button
                onClick={() => setTagManagerOpen(true)}
                className="px-3 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center gap-2 shadow-sm hover:shadow-md"
                title="Manage project tags"
              >
                <Tag className="w-4 h-4 text-amber-500" />
                <span>Tags</span>
              </button>

              {/* Settings Dropdown - Radix UI DropdownMenu */}
              <div className="ml-auto">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger asChild>
                    <button
                      className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center justify-center"
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
                            <Sun className="w-4 h-4" />
                            <span>Light Mode</span>
                          </>
                        ) : (
                          <>
                            <Moon className="w-4 h-4" />
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
                        <Eye className="w-4 h-4" />
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
      )}

      {/* Canvas/Code Area - with top padding for fixed header */}
      <div className={`flex-1 bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800 overflow-hidden relative ${canvasPresentationActive ? 'pt-0' : ''}`}>
        {!selectedProjectId || !selectedVersionId ? (
          // Empty state when no project/version selected
          <div className="h-full flex items-center justify-center">
            <div className="relative">
              {/* Decorative background elements */}
              <div className="absolute -top-20 -left-20 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
              <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-gradient-to-br from-blue-100 to-cyan-100 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />

              <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-12 md:p-16 text-center shadow-xl shadow-gray-200/50 dark:shadow-gray-900/50">
                <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/25">
                  <FileText className="h-10 w-10 text-white" />
                </div>
                <h3 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-3">
                  No Project Selected
                </h3>
                <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto leading-relaxed">
                  Select a project and version from the dropdowns above to view and edit your class diagram
                </p>

                {/* Quick tip */}
                <div className="mt-8 pt-6 border-t border-gray-100 dark:border-gray-700/50">
                  <p className="text-xs text-gray-400 dark:text-gray-500 flex items-center justify-center gap-2">
                    <Info className="w-4 h-4" />
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

            {/* #547: Dependency graph overlay indicator; #551: Upstream/downstream toggles */}
            {showDependencyOverlay && !layoutPreviewNodes && !canvasPresentationActive && (
              <Panel position="top-center" className="!mt-4 z-[1001]">
                <div className="flex items-center gap-3 px-3 py-2 rounded-lg shadow-md border border-indigo-200/80 dark:border-indigo-700/50 bg-indigo-50/95 dark:bg-indigo-900/30 backdrop-blur-sm">
                  <Network className="h-4 w-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
                  <span className="text-sm font-medium text-indigo-800 dark:text-indigo-200 shrink-0">Dependency graph</span>
                  <ToggleGroup.Root
                    type="single"
                    value={dependencyView}
                    onValueChange={(v) => v && (v === 'all' || v === 'upstream' || v === 'downstream' || v === 'path') && setDependencyView(v)}
                    className="flex rounded-md overflow-hidden border border-indigo-200 dark:border-indigo-600 bg-white/60 dark:bg-indigo-950/50"
                    aria-label="Dependency view"
                  >
                    <ToggleGroup.Item
                      value="all"
                      className="px-2.5 py-1 text-xs font-medium data-[state=on]:bg-indigo-200/80 dark:data-[state=on]:bg-indigo-700/50 data-[state=on]:text-indigo-900 dark:data-[state=on]:text-indigo-100 hover:bg-indigo-100/80 dark:hover:bg-indigo-800/30 text-indigo-700 dark:text-indigo-300"
                      title="Show all dependencies"
                    >
                      All
                    </ToggleGroup.Item>
                    <ToggleGroup.Item
                      value="upstream"
                      className="px-2.5 py-1 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-200/80 dark:data-[state=on]:bg-indigo-700/50 data-[state=on]:text-indigo-900 dark:data-[state=on]:text-indigo-100 hover:bg-indigo-100/80 dark:hover:bg-indigo-800/30 text-indigo-700 dark:text-indigo-300"
                      title="Show only what this class depends on (select a class)"
                    >
                      <ArrowUp className="h-3 w-3" />
                      Upstream
                    </ToggleGroup.Item>
                    <ToggleGroup.Item
                      value="downstream"
                      className="px-2.5 py-1 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-200/80 dark:data-[state=on]:bg-indigo-700/50 data-[state=on]:text-indigo-900 dark:data-[state=on]:text-indigo-100 hover:bg-indigo-100/80 dark:hover:bg-indigo-800/30 text-indigo-700 dark:text-indigo-300"
                      title="Show only what depends on this class (select a class)"
                    >
                      <ArrowDown className="h-3 w-3" />
                      Downstream
                    </ToggleGroup.Item>
                    <ToggleGroup.Item
                      value="path"
                      className="px-2.5 py-1 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-200/80 dark:data-[state=on]:bg-indigo-700/50 data-[state=on]:text-indigo-900 dark:data-[state=on]:text-indigo-100 hover:bg-indigo-100/80 dark:hover:bg-indigo-800/30 text-indigo-700 dark:text-indigo-300"
                      title="Trace full chain: click a class to highlight upstream + downstream path"
                    >
                      <Route className="h-3 w-3" />
                      Path
                    </ToggleGroup.Item>
                  </ToggleGroup.Root>
                  {(dependencyView === 'upstream' || dependencyView === 'downstream' || dependencyView === 'path') && !dependencyFocalNodeId && (
                    <span className="text-xs text-indigo-600 dark:text-indigo-400 italic">Select a class</span>
                  )}
                  {(dependencyView === 'upstream' && dependencyFocalNodeId && dependencyUpstreamIds) && (
                    <span className="text-xs text-indigo-600 dark:text-indigo-400">{dependencyUpstreamIds.size} upstream</span>
                  )}
                  {(dependencyView === 'downstream' && dependencyFocalNodeId && dependencyDownstreamIds) && (
                    <span className="text-xs text-indigo-600 dark:text-indigo-400">{dependencyDownstreamIds.size} downstream</span>
                  )}
                  {(dependencyView === 'path' && dependencyFocalNodeId && dependencyPathChain) && (
                    <span className="text-xs text-indigo-600 dark:text-indigo-400">{dependencyPathChain.nodeIds.size} in chain</span>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowDependencyOverlay(false)}
                    className="p-1 rounded-md text-indigo-600 dark:text-indigo-400 hover:bg-indigo-200/50 dark:hover:bg-indigo-800/50 shrink-0"
                    title="Turn off dependency overlay"
                    aria-label="Turn off dependency overlay"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </Panel>
            )}
            {/* #550: Impact Analysis indicator (stack below dependency overlay when both on) */}
            {impactAnalysisMode && !layoutPreviewNodes && !canvasPresentationActive && (
              <Panel position="top-center" className={showDependencyOverlay ? '!mt-14 z-[1001]' : '!mt-4 z-[1001]'}>
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg shadow-md border border-amber-200/80 dark:border-amber-700/50 bg-amber-50/95 dark:bg-amber-900/30 backdrop-blur-sm">
                  <Zap className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
                  {impactAnalysisSourceId && affectedClassIds ? (
                    <span className="text-sm font-medium text-amber-800 dark:text-amber-200">
                      Impact: {String((nodes.find(n => n.id === impactAnalysisSourceId)?.data as { name?: string } | undefined)?.name ?? impactAnalysisSourceId)} ({affectedClassIds.size} affected)
                    </span>
                  ) : (
                    <span className="text-sm font-medium text-amber-800 dark:text-amber-200">Impact Analysis — select a class to see affected</span>
                  )}
                  <button
                    type="button"
                    onClick={() => setImpactAnalysisMode(false)}
                    className="p-1 rounded-md text-amber-600 dark:text-amber-400 hover:bg-amber-200/50 dark:hover:bg-amber-800/50"
                    title="Turn off Impact Analysis"
                    aria-label="Turn off Impact Analysis"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </Panel>
            )}
            {/* #471: Layout preview bar — Apply or Cancel suggested layout */}
            {layoutPreviewNodes && !canvasPresentationActive && (
              <Panel position="top-center" className="!mt-4 z-[1001]">
                <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-teal-200 dark:border-teal-700 px-4 py-3 flex items-center gap-4">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                    Previewing layout: <span className="text-teal-700 dark:text-teal-300">{layoutPreviewLabel}</span>
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleApplyLayoutPreview}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-teal-600 text-white hover:bg-teal-700 dark:bg-teal-500 dark:hover:bg-teal-600 transition-colors"
                    >
                      <Check className="w-4 h-4" />
                      Apply
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelLayoutPreview}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-500 transition-colors"
                    >
                      <X className="w-4 h-4" />
                      Cancel
                    </button>
                  </div>
                </div>
              </Panel>
            )}

            <div
              ref={presentationShellRef}
              className={`absolute inset-0 flex min-h-0 w-full ${
                canvasPresentationActive && presentationShowSpeakerNotes ? 'flex-row' : 'flex-col'
              }`}
            >
              <div
                ref={canvasCaptureAreaRef}
                className={`relative min-h-0 overflow-hidden ${
                  canvasPresentationActive && presentationShowSpeakerNotes ? 'min-w-0 flex-1' : 'h-full w-full'
                }`}
              >
              <ReactFlow
              nodes={displayNodes}
              edges={edgesWithHover}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              defaultEdgeOptions={{ zIndex: 0 }}
              minZoom={0.1}
              maxZoom={2}
              onNodesChange={handleNodesChange}
              onEdgesChange={handleEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              onEdgeMouseEnter={onEdgeMouseEnter}
              onEdgeMouseLeave={onEdgeMouseLeave}
              onNodeDrag={handleNodeDrag}
              onNodeDragStop={handleNodeDragStop}
              onSelectionChange={onSelectionChange}
              onDragOver={handleCanvasDragOver}
              onDrop={handleCanvasDrop}
              onMove={(_, viewport) => setZoomLevel(viewport.zoom)}
              onMoveEnd={() => setAutoSavePending(true)}
              snapToGrid={snapToGrid}
              snapGrid={[gridSize, gridSize]}
              fitView
              attributionPosition="bottom-left"
              className={`${isAnimating ? 'layout-animating' : ''} ${isCanvasDropTarget ? 'ring-2 ring-blue-400/60 ring-offset-2 ring-offset-white dark:ring-offset-gray-900 border-2 border-dashed border-blue-400 rounded-xl transition-all duration-150' : ''}`}
              nodesDraggable={!layoutPreviewNodes}
              nodesConnectable={!isReadOnly}
              elementsSelectable={true}
              selectionOnDrag={true}
              selectionMode={SelectionMode.Partial}
              nodesFocusable={true}
              edgesFocusable={true}
              style={canvasBackgroundStyle}
            >
            {/* Custom SVG marker definitions for arrow styles */}
            <svg style={{ position: 'absolute', width: 0, height: 0 }}>
              <defs>
                {/* Generate diamond and circle markers for each edge color */}
                {[
                  edgeStyling.directColor,
                  edgeStyling.optionalColor,
                  edgeStyling.weakColor,
                  edgeStyling.bidirectionalColor,
                ].map((color) => {
                  const colorId = color.replace('#', '');
                  return (
                    <g key={colorId}>
                      {/* Diamond marker */}
                      <marker
                        id={`diamond-marker-${colorId}`}
                        viewBox="0 0 12 12"
                        refX="6"
                        refY="6"
                        markerWidth="12"
                        markerHeight="12"
                        orient="auto-start-reverse"
                      >
                        <path
                          d="M 6 0 L 12 6 L 6 12 L 0 6 Z"
                          fill={color}
                          stroke={color}
                          strokeWidth="1"
                        />
                      </marker>
                      {/* Circle marker */}
                      <marker
                        id={`circle-marker-${colorId}`}
                        viewBox="0 0 10 10"
                        refX="5"
                        refY="5"
                        markerWidth="10"
                        markerHeight="10"
                        orient="auto-start-reverse"
                      >
                        <circle
                          cx="5"
                          cy="5"
                          r="4"
                          fill={color}
                          stroke={color}
                          strokeWidth="1"
                        />
                      </marker>
                    </g>
                  );
                })}
              </defs>
            </svg>
            {nestedGroupDrillPath.length > 0 && (
              <Panel
                position="top-left"
                className="!mt-12 ml-2 z-[1002] max-w-[min(100vw-2rem,28rem)]"
              >
                <nav
                  aria-label="Nested groups"
                  className="flex flex-wrap items-center gap-1 rounded-lg border border-gray-200/80 dark:border-gray-600 bg-white/95 dark:bg-gray-800/95 px-2 py-1.5 text-xs shadow-md backdrop-blur-sm"
                >
                  <button
                    type="button"
                    className="rounded px-1.5 py-0.5 font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/40"
                    onClick={() => setNestedGroupDrillPath([])}
                  >
                    Canvas
                  </button>
                  {nestedGroupDrillPath.map((gid, idx) => {
                    const g = groups.find((x) => x.id === gid);
                    const label = g?.name ?? gid;
                    return (
                      <span key={`${gid}-${idx}`} className="flex items-center gap-1 text-gray-500 dark:text-gray-400">
                        <ChevronRight className="h-3 w-3 shrink-0" />
                        <button
                          type="button"
                          className="max-w-[10rem] truncate rounded px-1.5 py-0.5 text-left text-gray-800 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                          onClick={() => setNestedGroupDrillPath((p) => p.slice(0, idx + 1))}
                        >
                          {label}
                        </button>
                      </span>
                    );
                  })}
                </nav>
              </Panel>
            )}
            {/* #349: Edge hover tooltip */}
            {hoveredEdgeId && edgeTooltipPosition && (() => {
              const hoveredEdge = displayEdges.find((e) => e.id === hoveredEdgeId);
              if (!hoveredEdge) return null;
              const sourceName = (nodes.find((n) => n.id === hoveredEdge.source)?.data as any)?.name ?? hoveredEdge.source;
              const targetName = (nodes.find((n) => n.id === hoveredEdge.target)?.data as any)?.name ?? hoveredEdge.target;
              const label = hoveredEdge.label ?? 'Relationship';
              return (
                <div
                  className="pointer-events-none fixed z-[10000] px-2.5 py-2 rounded-lg shadow-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-xs max-w-[240px]"
                  style={{
                    left: edgeTooltipPosition.x + 12,
                    top: edgeTooltipPosition.y + 12,
                  }}
                >
                  {typeof label === 'string' && <div className="font-semibold text-indigo-600 dark:text-indigo-400 mb-1">{label}</div>}
                  <div className="text-gray-500 dark:text-gray-400">
                    {sourceName} → {targetName}
                  </div>
                </div>
              );
            })()}
            {canvasBackground.type === 'grid' && (exportGridOverride !== null ? exportGridOverride : showGrid) && (
              <Background
                variant={
                  gridStyle === 'dots'
                    ? BackgroundVariant.Dots
                    : gridStyle === 'lines'
                      ? BackgroundVariant.Lines
                      : BackgroundVariant.Cross
                }
                gap={gridSize}
                size={1.5}
                color="currentColor"
                style={{
                  color: canvasBackground.gridColor || (isDark ? 'rgb(148, 163, 184)' : 'rgb(99, 102, 241)'),
                  opacity: canvasBackground.gridOpacity ?? (isDark ? 0.25 : 0.15),
                }}
              />
            )}
            {!canvasPresentationActive && (
            <Controls
              className="bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
              style={{
                borderRadius: '12px',
                overflow: 'hidden',
              }}
            />
            )}
            {!canvasPresentationActive && (
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
            )}

            {/* Smart Guides for Alignment - uses viewport to render in flow coordinate space */}
            {(guides.horizontal.length > 0 || guides.vertical.length > 0) && (() => {
              const viewport = getViewport();
              return (
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    pointerEvents: 'none',
                    zIndex: 1000,
                    overflow: 'hidden',
                  }}
                >
                  <svg
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      pointerEvents: 'none',
                      overflow: 'visible',
                    }}
                  >
                    <g transform={`translate(${viewport.x}, ${viewport.y}) scale(${viewport.zoom})`}>
                      {/* Horizontal guide lines */}
                      {guides.horizontal.map((guide, index) => (
                        <line
                          key={`h-${index}`}
                          x1={guide.x1}
                          y1={guide.y}
                          x2={guide.x2}
                          y2={guide.y}
                          stroke="#f472b6"
                          strokeWidth={2 / viewport.zoom}
                          strokeDasharray={`${6 / viewport.zoom} ${4 / viewport.zoom}`}
                          style={{ filter: 'drop-shadow(0 0 2px rgba(244, 114, 182, 0.5))' }}
                        />
                      ))}
                      {/* Vertical guide lines */}
                      {guides.vertical.map((guide, index) => (
                        <line
                          key={`v-${index}`}
                          x1={guide.x}
                          y1={guide.y1}
                          x2={guide.x}
                          y2={guide.y2}
                          stroke="#f472b6"
                          strokeWidth={2 / viewport.zoom}
                          strokeDasharray={`${6 / viewport.zoom} ${4 / viewport.zoom}`}
                          style={{ filter: 'drop-shadow(0 0 2px rgba(244, 114, 182, 0.5))' }}
                        />
                      ))}
                    </g>
                  </svg>
                </div>
              );
            })()}

            {/* Spacing Indicators - shows distance between selected nodes */}
            {showSpacingIndicators && (spacingIndicators.horizontal.length > 0 || spacingIndicators.vertical.length > 0) && (() => {
              const viewport = getViewport();
              return (
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    pointerEvents: 'none',
                    zIndex: 999,
                    overflow: 'hidden',
                  }}
                >
                  <svg
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      pointerEvents: 'none',
                      overflow: 'visible',
                    }}
                  >
                    <defs>
                      <marker
                        id="arrowStart"
                        markerWidth="6"
                        markerHeight="6"
                        refX="3"
                        refY="3"
                        orient="auto"
                      >
                        <path d="M6,0 L6,6 L0,3 Z" fill="#10b981" />
                      </marker>
                      <marker
                        id="arrowEnd"
                        markerWidth="6"
                        markerHeight="6"
                        refX="3"
                        refY="3"
                        orient="auto"
                      >
                        <path d="M0,0 L0,6 L6,3 Z" fill="#10b981" />
                      </marker>
                    </defs>
                    <g transform={`translate(${viewport.x}, ${viewport.y}) scale(${viewport.zoom})`}>
                      {/* Horizontal spacing indicators */}
                      {spacingIndicators.horizontal.map((indicator, index) => {
                        const midX = (indicator.x1 + indicator.x2) / 2;
                        return (
                          <g key={`h-spacing-${index}`}>
                            {/* Distance line */}
                            <line
                              x1={indicator.x1}
                              y1={indicator.y}
                              x2={indicator.x2}
                              y2={indicator.y}
                              stroke="#10b981"
                              strokeWidth={2 / viewport.zoom}
                              markerStart="url(#arrowStart)"
                              markerEnd="url(#arrowEnd)"
                            />
                            {/* Vertical caps */}
                            <line
                              x1={indicator.x1}
                              y1={indicator.y - 10 / viewport.zoom}
                              x2={indicator.x1}
                              y2={indicator.y + 10 / viewport.zoom}
                              stroke="#10b981"
                              strokeWidth={1.5 / viewport.zoom}
                            />
                            <line
                              x1={indicator.x2}
                              y1={indicator.y - 10 / viewport.zoom}
                              x2={indicator.x2}
                              y2={indicator.y + 10 / viewport.zoom}
                              stroke="#10b981"
                              strokeWidth={1.5 / viewport.zoom}
                            />
                            {/* Distance label background */}
                            <rect
                              x={midX - 20 / viewport.zoom}
                              y={indicator.y - 22 / viewport.zoom}
                              width={40 / viewport.zoom}
                              height={16 / viewport.zoom}
                              rx={4 / viewport.zoom}
                              fill={isDark ? '#064e3b' : '#d1fae5'}
                              stroke="#10b981"
                              strokeWidth={1 / viewport.zoom}
                            />
                            {/* Distance label */}
                            <text
                              x={midX}
                              y={indicator.y - 11 / viewport.zoom}
                              textAnchor="middle"
                              fontSize={10 / viewport.zoom}
                              fill={isDark ? '#6ee7b7' : '#047857'}
                              fontWeight="600"
                              fontFamily="monospace"
                            >
                              {indicator.distance}px
                            </text>
                          </g>
                        );
                      })}
                      {/* Vertical spacing indicators */}
                      {spacingIndicators.vertical.map((indicator, index) => {
                        const midY = (indicator.y1 + indicator.y2) / 2;
                        return (
                          <g key={`v-spacing-${index}`}>
                            {/* Distance line */}
                            <line
                              x1={indicator.x}
                              y1={indicator.y1}
                              x2={indicator.x}
                              y2={indicator.y2}
                              stroke="#10b981"
                              strokeWidth={2 / viewport.zoom}
                              markerStart="url(#arrowStart)"
                              markerEnd="url(#arrowEnd)"
                            />
                            {/* Horizontal caps */}
                            <line
                              x1={indicator.x - 10 / viewport.zoom}
                              y1={indicator.y1}
                              x2={indicator.x + 10 / viewport.zoom}
                              y2={indicator.y1}
                              stroke="#10b981"
                              strokeWidth={1.5 / viewport.zoom}
                            />
                            <line
                              x1={indicator.x - 10 / viewport.zoom}
                              y1={indicator.y2}
                              x2={indicator.x + 10 / viewport.zoom}
                              y2={indicator.y2}
                              stroke="#10b981"
                              strokeWidth={1.5 / viewport.zoom}
                            />
                            {/* Distance label background */}
                            <rect
                              x={indicator.x + 8 / viewport.zoom}
                              y={midY - 8 / viewport.zoom}
                              width={40 / viewport.zoom}
                              height={16 / viewport.zoom}
                              rx={4 / viewport.zoom}
                              fill={isDark ? '#064e3b' : '#d1fae5'}
                              stroke="#10b981"
                              strokeWidth={1 / viewport.zoom}
                            />
                            {/* Distance label */}
                            <text
                              x={indicator.x + 28 / viewport.zoom}
                              y={midY + 3 / viewport.zoom}
                              textAnchor="middle"
                              fontSize={10 / viewport.zoom}
                              fill={isDark ? '#6ee7b7' : '#047857'}
                              fontWeight="600"
                              fontFamily="monospace"
                            >
                              {indicator.distance}px
                            </text>
                          </g>
                        );
                      })}
                    </g>
                  </svg>
                </div>
              );
            })()}

            {/* Spacing Tools Panel - shown when multiple nodes selected */}
            {selectedNodeIds.length >= 2 && !canvasPresentationActive && (
              <Panel
                position="bottom-center"
                className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 px-2 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 px-2">
                    {selectedNodeIds.length} selected
                  </span>
                  <div className="h-4 w-px bg-gray-200 dark:bg-gray-600" />

                  {/* Show Spacing Indicators Toggle */}
                  <button
                    onClick={toggleSpacingIndicators}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 flex items-center gap-1.5 border ${
                      showSpacingIndicators 
                        ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-700'
                        : 'bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-transparent hover:bg-gray-100 dark:hover:bg-gray-600'
                    }`}
                    title="Show spacing between nodes"
                  >
                    <Move className="h-3.5 w-3.5" />
                    <span>Spacing</span>
                  </button>

                  {selectedNodeIds.length >= 3 && (
                    <>
                      <div className="h-4 w-px bg-gray-200 dark:bg-gray-700" />

                      {/* Distribute Horizontally */}
                      <button
                        onClick={distributeHorizontal}
                        className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                        title="Distribute nodes with equal horizontal spacing"
                      >
                        <SeparatorHorizontal className="h-3.5 w-3.5" />
                        <span>Distribute H</span>
                      </button>

                      {/* Distribute Vertically */}
                      <button
                        onClick={distributeVertical}
                        className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                        title="Distribute nodes with equal vertical spacing"
                      >
                        <SeparatorVertical className="h-3.5 w-3.5" />
                        <span>Distribute V</span>
                      </button>
                    </>
                  )}
                </div>
              </Panel>
            )}

            {/* Focus mode indicator - by selection+degree (#489) or by group (#490), exit with Esc or X */}
            {focusModeEnabled && !canvasPresentationActive && (
              <Panel position="top-center" className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-full shadow-lg border border-gray-200/80 dark:border-gray-700/80 px-4 py-2">
                <div className="flex items-center gap-2">
                  <Focus className="h-4 w-4 text-indigo-600 dark:text-indigo-400 shrink-0" />
                  {focusModeGroupId ? (
                    <>
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Group:</span>
                      <span className="text-sm font-medium text-indigo-600 dark:text-indigo-400 truncate max-w-[140px]" title={groups.find(g => g.id === focusModeGroupId)?.name}>
                        {groups.find(g => g.id === focusModeGroupId)?.name ?? 'Unknown'}
                      </span>
                      <button
                        onClick={focusOnSelection}
                        className="px-2 py-1 text-xs rounded-md hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400"
                        title="Switch to selection focus"
                        aria-label="Focus by selection"
                      >
                        Selection
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Focus mode</span>
                      <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
                        {focusModeDegree === 1 ? '1st' : focusModeDegree === 2 ? '2nd' : focusModeDegree === 3 ? '3rd' : `${focusModeDegree}th`} degree
                      </span>
                      <div className="flex items-center gap-0.5 border border-gray-200 dark:border-gray-600 rounded-md overflow-hidden">
                        <button
                          onClick={reduceFocusDegree}
                          disabled={focusModeDegree <= 1}
                          className="p-1.5 rounded-none hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400 disabled:opacity-40 disabled:pointer-events-none"
                          title="Reduce focus (fewer connections)"
                          aria-label="Reduce focus degree"
                        >
                          <Minus className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={expandFocusDegree}
                          disabled={focusModeDegree >= FOCUS_MODE_MAX_DEGREE}
                          className="p-1.5 rounded-none hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400 disabled:opacity-40 disabled:pointer-events-none"
                          title="Expand focus (include more connections)"
                          aria-label="Expand focus degree"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <button
                        onClick={resetFocusDegree}
                        disabled={focusModeDegree <= 1}
                        className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400 disabled:opacity-40 disabled:pointer-events-none"
                        title="Reset focus to 1st degree"
                        aria-label="Reset focus degree"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                  <button
                    onClick={exitFocusMode}
                    className="p-1 rounded-full hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                    title="Exit focus mode (Esc)"
                    aria-label="Exit focus mode"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </Panel>
            )}

            {/* Read Only Indicator */}
            {isReadOnly && !canvasPresentationActive && (
              <Panel position="top-left" className="bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-900/30 dark:to-yellow-900/30 text-amber-800 dark:text-amber-200 rounded-xl shadow-lg px-4 py-2 border border-amber-200/80 dark:border-amber-700/50 backdrop-blur-sm">
                <div className="flex items-center gap-2">
                  <div className="p-1 bg-amber-100 dark:bg-amber-800/50 rounded-lg">
                    <Lock className="h-4 w-4" />
                  </div>
                  <span className="text-xs font-semibold">Read Only Mode</span>
                </div>
              </Panel>
            )}

            {/* Canvas tools: compact mini drawer in upper-left (#842) */}
            {!canvasPresentationActive && (
              <>
                <Panel
                  position="top-left"
                  className={`bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 ${isReadOnly ? 'mt-14' : ''}`}
                >
                  <Collapsible.Root open={canvasToolsDrawerOpen} onOpenChange={setCanvasToolsDrawerOpen}>
                    <div className="flex items-stretch gap-1.5 p-1.5">
                      <Collapsible.Trigger asChild>
                        <button
                          type="button"
                          aria-expanded={canvasToolsDrawerOpen}
                          aria-controls="ade-canvas-tools-mini-drawer"
                          title="Canvas tools"
                          className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 flex items-center gap-2 border ${
                            canvasVisibilityRestricted
                              ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700'
                              : 'bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-transparent hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 hover:border-indigo-200 dark:hover:border-indigo-700'
                          }`}
                        >
                          <PanelLeft className="h-4 w-4 shrink-0" aria-hidden />
                          <span>Tools</span>
                          <ChevronRight
                            className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${canvasToolsDrawerOpen ? 'rotate-180' : ''}`}
                            aria-hidden
                          />
                        </button>
                      </Collapsible.Trigger>

                      <Collapsible.Content
                        id="ade-canvas-tools-mini-drawer"
                        className="overflow-hidden"
                      >
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={handleExpandAll}
                            className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                            title="Expand all properties"
                          >
                            <ChevronDown className="h-3.5 w-3.5" />
                            <span>Expand</span>
                          </button>
                          <button
                            type="button"
                            onClick={handleCollapseAll}
                            className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                            title="Collapse all properties"
                          >
                            <ChevronUp className="h-3.5 w-3.5" />
                            <span>Collapse</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCanvasToolsDrawerOpen(false);
                              openCanvasSearch();
                            }}
                            className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400 flex items-center gap-1.5 border border-transparent hover:border-indigo-200 dark:hover:border-indigo-700"
                            title="Search classes (Cmd+F)"
                          >
                            <Search className="h-3.5 w-3.5" />
                            <span>Search</span>
                          </button>

                          <DropdownMenu.Root>
                            <DropdownMenu.Trigger asChild>
                              <button
                                type="button"
                                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 flex items-center gap-1.5 border ${
                                  canvasVisibilityRestricted
                                    ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700'
                                    : 'bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-transparent hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400'
                                }`}
                                title="View mode options"
                                aria-label="View mode"
                              >
                                <Eye className="h-3.5 w-3.5" />
                                <span>View Mode</span>
                                <ChevronDown className="h-3.5 w-3.5 opacity-70" />
                              </button>
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Portal>
                              <DropdownMenu.Content
                                className="min-w-[200px] bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-1 z-[9999] overflow-visible"
                                sideOffset={5}
                                align="start"
                              >
                                <DropdownMenu.CheckboxItem
                                  checked={focusModeEnabled}
                                  onCheckedChange={(checked) => {
                                    setFocusModeEnabled(!!checked);
                                    if (!checked) {
                                      setFocusModeGroupId(null);
                                      setFocusModeDegree(1);
                                    }
                                  }}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                                  onSelect={(e) => e.preventDefault()}
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <Focus className="h-4 w-4 shrink-0" />
                                  <span>Focus</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.Sub>
                                  <DropdownMenu.SubTrigger className="flex items-center gap-3 px-3 py-2 text-sm rounded-md outline-none cursor-pointer text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 data-[state=open]:bg-gray-100 dark:data-[state=open]:bg-gray-700">
                                    <Folder className="h-4 w-4 shrink-0" />
                                    <span>Focus on group</span>
                                    <ChevronRight className="h-4 w-4 ml-auto shrink-0" />
                                  </DropdownMenu.SubTrigger>
                                  <DropdownMenu.SubContent
                                    className="min-w-[180px] max-w-[240px] rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 py-1 z-50 overflow-x-hidden"
                                    sideOffset={4}
                                    alignOffset={-4}
                                  >
                                    {groups.length === 0 ? (
                                      <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No groups</div>
                                    ) : (
                                      <div className="max-h-[240px] overflow-y-auto overflow-x-hidden">
                                        {groups.map((g) => (
                                          <button
                                            key={g.id}
                                            type="button"
                                            className="w-full min-w-0 flex items-center justify-between gap-2 px-3 py-2 text-sm text-left text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 outline-none mx-0.5"
                                            onClick={() => focusOnGroup(g.id)}
                                          >
                                            <span className="truncate min-w-0">{g.name}</span>
                                            <span className="text-xs text-gray-400 tabular-nums shrink-0">({g.nodeIds.length})</span>
                                          </button>
                                        ))}
                                      </div>
                                    )}
                                  </DropdownMenu.SubContent>
                                </DropdownMenu.Sub>
                                <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />
                                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                                  Hide on canvas
                                </div>
                                <DropdownMenu.CheckboxItem
                                  checked={hideEmptyClasses}
                                  onCheckedChange={(checked) => setHideEmptyClasses(!!checked)}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                                  onSelect={(e) => e.preventDefault()}
                                  title="Hide classes that have no properties"
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <Braces className="h-4 w-4 shrink-0" />
                                  <span>Empty classes</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.CheckboxItem
                                  checked={showOnlyConnectedNodes}
                                  onCheckedChange={(checked) => setShowOnlyConnectedNodes(!!checked)}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                                  onSelect={(e) => e.preventDefault()}
                                  title="Hide classes with no relationships (no edges on the canvas)"
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <Network className="h-4 w-4 shrink-0" />
                                  <span>Unconnected classes</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.CheckboxItem
                                  checked={hideDeprecatedClasses}
                                  onCheckedChange={(checked) => setHideDeprecatedClasses(!!checked)}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                                  onSelect={(e) => e.preventDefault()}
                                  title="Hide classes marked deprecated in schema"
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <Ban className="h-4 w-4 shrink-0" />
                                  <span>Deprecated classes</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.Sub>
                                  <DropdownMenu.SubTrigger className="flex items-center gap-3 px-3 py-2 text-sm rounded-md outline-none cursor-pointer text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 data-[state=open]:bg-gray-100 dark:data-[state=open]:bg-gray-700">
                                    <Folder className="h-4 w-4 shrink-0" />
                                    <span>Hide group members</span>
                                    <ChevronRight className="h-4 w-4 ml-auto shrink-0" />
                                  </DropdownMenu.SubTrigger>
                                  <DropdownMenu.SubContent
                                    className="min-w-[200px] max-w-[260px] rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 py-1 z-50 overflow-x-hidden"
                                    sideOffset={4}
                                    alignOffset={-4}
                                  >
                                    {groups.length === 0 ? (
                                      <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No groups</div>
                                    ) : (
                                      <div className="max-h-[240px] overflow-y-auto overflow-x-hidden">
                                        {groups.map((g) => (
                                          <button
                                            key={g.id}
                                            type="button"
                                            className="w-full min-w-0 flex items-center gap-2 px-3 py-2 text-sm text-left text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 outline-none mx-0.5"
                                            onClick={(e) => {
                                              e.preventDefault();
                                              toggleHiddenCanvasGroup(g.id);
                                            }}
                                          >
                                            <span className="inline-flex w-5 shrink-0 items-center justify-center text-indigo-600 dark:text-indigo-400">
                                              {hiddenCanvasGroupIds.has(g.id) ? <Check className="h-4 w-4" /> : null}
                                            </span>
                                            <span className="truncate min-w-0">{g.name}</span>
                                            <span className="text-xs text-gray-400 tabular-nums shrink-0">({g.nodeIds.length})</span>
                                          </button>
                                        ))}
                                      </div>
                                    )}
                                  </DropdownMenu.SubContent>
                                </DropdownMenu.Sub>
                                <DropdownMenu.CheckboxItem
                                  checked={nodeGhostsModeEnabled}
                                  onCheckedChange={(checked) => setNodeGhostsModeEnabled(!!checked)}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                                  onSelect={(e) => e.preventDefault()}
                                  title="Show nodes hidden by filters or manual hide as semi-transparent instead of removing them"
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <Ghost className="h-4 w-4 shrink-0" />
                                  <span>Node ghosts</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />
                                <DropdownMenu.CheckboxItem
                                  checked={isolateSelectionEnabled}
                                  disabled={selectedNodeIds.length === 0}
                                  onCheckedChange={(checked) => setIsolateSelectionEnabled(!!checked)}
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[disabled]:opacity-50 data-[disabled]:pointer-events-none"
                                  onSelect={(e) => e.preventDefault()}
                                  title={
                                    selectedNodeIds.length === 0
                                      ? 'Select one or more class nodes on the canvas first'
                                      : 'Show only selected classes (Esc to clear)'
                                  }
                                >
                                  <DropdownMenu.ItemIndicator className="inline-flex w-5 items-center justify-center">
                                    <Check className="h-4 w-4" />
                                  </DropdownMenu.ItemIndicator>
                                  <BoxSelect className="h-4 w-4 shrink-0" />
                                  <span>Selected only</span>
                                </DropdownMenu.CheckboxItem>
                                <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />
                                <DropdownMenu.Item
                                  className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700 data-[disabled]:opacity-40 data-[disabled]:pointer-events-none"
                                  disabled={!canvasVisibilityRestricted}
                                  title="Show every class again: clear manual hides, hide filters, node ghosts, isolate selection, and focus mode"
                                  onSelect={() => restoreCanvasVisibility()}
                                >
                                  <Undo2 className="h-4 w-4 shrink-0" />
                                  <span>Show all nodes</span>
                                </DropdownMenu.Item>
                              </DropdownMenu.Content>
                            </DropdownMenu.Portal>
                          </DropdownMenu.Root>

                          {!isReadOnly && (
                            <button
                              type="button"
                              onClick={() => {
                                setCanvasToolsDrawerOpen(false);
                                setTagManagerOpen(true);
                              }}
                              className="px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-amber-50 dark:hover:bg-amber-900/30 hover:text-amber-600 dark:hover:text-amber-400 flex items-center gap-1.5 border border-transparent hover:border-amber-200 dark:hover:border-amber-700"
                              title="Manage project tags"
                            >
                              <Tag className="h-3.5 w-3.5" />
                              <span>Tags</span>
                            </button>
                          )}
                        </div>
                      </Collapsible.Content>
                    </div>
                  </Collapsible.Root>
                </Panel>
              </>
            )}

            {/* Canvas Search Panel */}
            {canvasSearchOpen && !canvasPresentationActive && (
              <Panel
                position="top-center"
                className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80"
              >
                <div className="relative" ref={searchHistoryRef}>
                  <div className="flex items-center gap-2 p-2">
                    <Search className="h-4 w-4 text-gray-400 dark:text-gray-500 shrink-0" />
                    <input
                      ref={canvasSearchInputRef}
                      type="text"
                      value={canvasSearchQuery}
                      onChange={(e) => setCanvasSearchQuery(e.target.value)}
                      onFocus={() => searchHistory.length > 0 && setSearchHistoryOpen(true)}
                      placeholder={canvasSearchUseRegex ? 'Regex pattern...' : 'Search classes...'}
                      className="w-64 px-2 py-1 text-sm bg-transparent border-none outline-none text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500"
                      autoFocus
                    />
                    {/* History toggle button */}
                    {searchHistory.length > 0 && (
                      <button
                        onClick={() => { setSearchHistoryOpen(!searchHistoryOpen); setSearchFiltersOpen(false); }}
                        className={`p-1 transition-colors rounded shrink-0 ${
                          searchHistoryOpen 
                            ? 'text-indigo-500 bg-indigo-50 dark:bg-indigo-900/30' 
                            : 'text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                        title={`Search history (${searchHistory.length} items)`}
                      >
                        <History className="h-4 w-4" />
                      </button>
                    )}
                    {/* Filters toggle button */}
                    <button
                      onClick={() => { setSearchFiltersOpen(!searchFiltersOpen); setSearchHistoryOpen(false); }}
                      className={`p-1 transition-colors rounded shrink-0 relative ${
                        searchFiltersOpen 
                          ? 'text-indigo-500 bg-indigo-50 dark:bg-indigo-900/30' 
                          : hasActiveFilters
                            ? 'text-amber-500 bg-amber-50 dark:bg-amber-900/30'
                            : 'text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                      title={hasActiveFilters ? 'Filters active - click to modify' : 'Search filters'}
                    >
                      <SlidersHorizontal className="h-4 w-4" />
                      {hasActiveFilters && (
                        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-amber-500 rounded-full" />
                      )}
                    </button>
                    <ToggleGroup.Root
                      type="single"
                      value={canvasSearchUseRegex ? 'regex' : 'basic'}
                      onValueChange={(v) => v && setCanvasSearchUseRegex(v === 'regex')}
                      className="inline-flex rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/50 p-0.5"
                      aria-label="Search mode"
                    >
                      <ToggleGroup.Item
                        value="basic"
                        className="px-2 py-0.5 text-xs rounded data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:shadow data-[state=on]:text-gray-900 dark:data-[state=on]:text-gray-100 text-gray-500 dark:text-gray-400"
                      >
                        Basic
                      </ToggleGroup.Item>
                      <ToggleGroup.Item
                        value="regex"
                        className="px-2 py-0.5 text-xs rounded data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:shadow data-[state=on]:text-gray-900 dark:data-[state=on]:text-gray-100 text-gray-500 dark:text-gray-400"
                      >
                        Regex
                      </ToggleGroup.Item>
                    </ToggleGroup.Root>
                    {(canvasSearchQuery || hasActiveFilters) && (
                      <>
                        {canvasSearchRegexError ? (
                          <span className="text-xs text-red-600 dark:text-red-400 px-2 py-0.5 shrink-0" title="Pattern is not a valid regular expression">
                            {canvasSearchRegexError}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded shrink-0">
                            {matchingNodeIds.size} found
                          </span>
                        )}
                      </>
                    )}
                    <button
                      onClick={closeCanvasSearch}
                      className="p-1 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors rounded hover:bg-gray-100 dark:hover:bg-gray-700 shrink-0"
                      title="Close search (Esc)"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  {/* Search Filters Dropdown */}
                  {searchFiltersOpen && (
                    <div ref={searchFiltersRef} className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50 p-3">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
                          <Filter className="h-3.5 w-3.5" />
                          Search Filters
                        </span>
                        {hasActiveFilters && (
                          <button
                            onClick={resetSearchFilters}
                            className="text-xs text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 flex items-center gap-1"
                          >
                            <X className="h-3 w-3" />
                            Clear filters
                          </button>
                        )}
                      </div>

                      <div className="space-y-3">
                        {/* Type Filter */}
                        <div>
                          <label className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5 block">
                            Class Type
                          </label>
                          <div className="flex flex-wrap gap-1">
                            {[
                              { value: 'all', label: 'All' },
                              { value: 'class', label: 'Class' },
                              { value: 'allOf', label: 'allOf' },
                              { value: 'oneOf', label: 'oneOf' },
                              { value: 'anyOf', label: 'anyOf' },
                            ].map((opt) => (
                              <button
                                key={opt.value}
                                onClick={() => setSearchFilterType(opt.value as SearchFilterType)}
                                className={`px-2 py-1 text-xs rounded-md transition-colors ${
                                  searchFilterType === opt.value
                                    ? 'bg-indigo-500 text-white'
                                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                                }`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* Group Filter */}
                        <div>
                          <label className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5 block">
                            Group
                          </label>
                          <select
                            value={searchFilterGroup}
                            onChange={(e) => setSearchFilterGroup(e.target.value)}
                            className="w-full px-2 py-1.5 text-xs bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-md text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          >
                            <option value="all">All groups</option>
                            <option value="ungrouped">Ungrouped only</option>
                            {groups.map((group) => (
                              <option key={group.id} value={group.id}>
                                {group.name}
                              </option>
                            ))}
                          </select>
                        </div>

                        {/* Properties Filter */}
                        <div>
                          <label className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5 block">
                            Properties
                          </label>
                          <div className="flex flex-wrap gap-1">
                            {[
                              { value: 'all', label: 'Any' },
                              { value: 'with', label: 'Has properties' },
                              { value: 'without', label: 'No properties' },
                            ].map((opt) => (
                              <button
                                key={opt.value}
                                onClick={() => setSearchFilterHasProperties(opt.value as 'all' | 'with' | 'without')}
                                className={`px-2 py-1 text-xs rounded-md transition-colors ${
                                  searchFilterHasProperties === opt.value
                                    ? 'bg-indigo-500 text-white'
                                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                                }`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* Property Name Filter */}
                        <div>
                          <label className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5 block">
                            Has Property Named
                          </label>
                          <input
                            type="text"
                            value={searchFilterPropertyName}
                            onChange={(e) => setSearchFilterPropertyName(e.target.value)}
                            placeholder="e.g., id, email, createdAt..."
                            className="w-full px-2 py-1.5 text-xs bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-md text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </div>
                      </div>

                      {/* Active filters summary */}
                      {hasActiveFilters && (
                        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                          <div className="flex flex-wrap gap-1">
                            {searchFilterType !== 'all' && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded">
                                Type: {searchFilterType}
                                <button onClick={() => setSearchFilterType('all')} className="hover:text-indigo-900 dark:hover:text-indigo-100">
                                  <X className="h-2.5 w-2.5" />
                                </button>
                              </span>
                            )}
                            {searchFilterGroup !== 'all' && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded">
                                Group: {searchFilterGroup === 'ungrouped' ? 'Ungrouped' : groups.find(g => g.id === searchFilterGroup)?.name || searchFilterGroup}
                                <button onClick={() => setSearchFilterGroup('all')} className="hover:text-indigo-900 dark:hover:text-indigo-100">
                                  <X className="h-2.5 w-2.5" />
                                </button>
                              </span>
                            )}
                            {searchFilterHasProperties !== 'all' && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded">
                                {searchFilterHasProperties === 'with' ? 'Has properties' : 'No properties'}
                                <button onClick={() => setSearchFilterHasProperties('all')} className="hover:text-indigo-900 dark:hover:text-indigo-100">
                                  <X className="h-2.5 w-2.5" />
                                </button>
                              </span>
                            )}
                            {searchFilterPropertyName.trim() && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded">
                                Property: {searchFilterPropertyName}
                                <button onClick={() => setSearchFilterPropertyName('')} className="hover:text-indigo-900 dark:hover:text-indigo-100">
                                  <X className="h-2.5 w-2.5" />
                                </button>
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Search History Dropdown */}
                  {searchHistoryOpen && searchHistory.length > 0 && !searchFiltersOpen && (
                    <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 max-h-64 overflow-y-auto z-50">
                      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Recent Searches</span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            clearSearchHistory();
                            setSearchHistoryOpen(false);
                          }}
                          className="text-xs text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 flex items-center gap-1"
                        >
                          <Trash2 className="h-3 w-3" />
                          Clear all
                        </button>
                      </div>
                      <div className="py-1">
                        {searchHistory.map((item, index) => (
                          <div
                            key={`${item.query}-${item.isRegex}-${index}`}
                            className="flex items-center justify-between px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer group"
                            onClick={() => selectSearchHistoryItem(item.query, item.isRegex)}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <Search className="h-3 w-3 text-gray-400 dark:text-gray-500 shrink-0" />
                              <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                                {item.query}
                              </span>
                              {item.isRegex && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded shrink-0">
                                  Regex
                                </span>
                              )}
                            </div>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                removeFromHistory(item.query, item.isRegex);
                              }}
                              className="p-0.5 text-gray-400 hover:text-red-500 dark:text-gray-500 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                              title="Remove from history"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </Panel>
            )}

            {/* Dangling $ref warning */}
            {(() => {
              const warn = hasDanglingRefs(nodes.map(n => ({ id: n.id, name: (n.data as any)?.name, properties: (n.data as any)?.properties })));
              return warn && !canvasPresentationActive ? (
                <Panel position="top-left" className={`bg-gradient-to-r from-red-50 to-rose-50 dark:from-red-900/30 dark:to-rose-900/30 text-red-800 dark:text-red-200 rounded-xl shadow-lg px-4 py-2.5 border border-red-200/80 dark:border-red-700/50 backdrop-blur-sm ${isReadOnly ? 'mt-[8rem]' : 'mt-[4.5rem]'}`}>
                  <div className="flex items-center gap-2.5">
                    <div className="p-1 bg-red-100 dark:bg-red-800/50 rounded-lg">
                      <AlertTriangle className="h-4 w-4" />
                    </div>
                    <span className="text-xs font-medium max-w-xs">Missing class references detected. Connect property handles to target classes to resolve.</span>
                  </div>
                </Panel>
              ) : null;
            })()}

            {/* Layout Control Button */}
            {!canvasPresentationActive && (
            <Panel position="top-right" className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80" style={{ marginRight: '60px' }}>
              <div className="relative" ref={layoutDropdownRef}>
                <input
                  ref={layoutJsonImportInputRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  aria-hidden
                  onChange={(e) => void handleImportLayoutJsonSelected(e)}
                />
                <button
                  onClick={() => setLayoutDropdownOpen(!layoutDropdownOpen)}
                  className={`p-2 text-sm font-medium rounded-lg border transition-all duration-200 shadow-sm hover:shadow-md ${
                    showDependencyOverlay
                      ? 'border-indigo-300 dark:border-indigo-600 bg-indigo-50/80 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100/80 dark:hover:bg-indigo-900/50'
                      : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50'
                  }`}
                  title="Layout options"
                >
                  <Layout className="w-5 h-5" />
                </button>

                {/* Dropdown Menu */}
                {layoutDropdownOpen && (
                  <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[1002]">
                    <div className="py-2">
                      {/* Save/Load Layout Buttons */}
                      <div className="px-4 py-3">
                        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                          Canvas Layout
                        </h4>
                        <div className="mb-3">
                          <label
                            htmlFor="layout-name-input"
                            className="block text-xs text-gray-500 dark:text-gray-400 mb-1"
                          >
                            Layout Name
                          </label>
                          <input
                            id="layout-name-input"
                            type="text"
                            list="canvas-suggested-layout-names"
                            value={selectedLayoutName}
                            onChange={(e) => setSelectedLayoutName(e.target.value)}
                            placeholder="Built-in name or your own"
                            autoComplete="off"
                            className="w-full px-2.5 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-200 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                          />
                          <datalist id="canvas-suggested-layout-names">
                            {availableLayoutNames.map((layoutName) => (
                              <option key={layoutName} value={layoutName} />
                            ))}
                          </datalist>
                          {namedLayoutSnapshotDataUrls[selectedLayoutName.trim()] ? (
                            <div className="mt-2 flex items-start gap-2">
                              <img
                                src={namedLayoutSnapshotDataUrls[selectedLayoutName.trim()]}
                                alt=""
                                className="h-16 w-28 shrink-0 rounded-md border border-gray-200 dark:border-gray-600 object-cover bg-gray-100 dark:bg-gray-800"
                              />
                              <span className="text-xs text-gray-500 dark:text-gray-400 leading-snug pt-0.5">
                                Saved canvas preview for this layout name
                              </span>
                            </div>
                          ) : null}
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={handleSaveLayout}
                            disabled={isReadOnly || layoutSaved}
                            className={`
                              px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2
                              ${layoutSaved
                                ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-700'
                                : !isReadOnly
                                ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 border border-indigo-200 dark:border-indigo-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                              }
                            `}
                            title={layoutSaved ? 'Layout saved!' : isReadOnly ? 'Cannot save in read-only mode' : 'Save current layout'}
                          >
                            {layoutSaved ? (
                              <>
                                <Check className="w-4 h-4" />
                                <span>Saved</span>
                              </>
                            ) : (
                              <>
                                <Save className="w-4 h-4" />
                                <span>Save</span>
                              </>
                            )}
                          </button>
                          <button
                            onClick={handleLoadLayout}
                            disabled={!hasExistingLayout}
                            className={`px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 ${
                              hasExistingLayout
                                ? 'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/50 border border-purple-200 dark:border-purple-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                            }`}
                            title={hasExistingLayout ? 'Load saved layout' : 'No saved layout available'}
                          >
                            <Upload className="w-4 h-4" />
                            <span>Load</span>
                          </button>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                          Type a custom name or pick a suggestion. Save and load multiple layouts per version.
                        </p>
                        <div className="grid grid-cols-2 gap-2 mt-3">
                          <button
                            type="button"
                            onClick={handleExportLayoutJson}
                            disabled={!selectedVersionId}
                            className={`px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 ${
                              selectedVersionId
                                ? 'bg-slate-50 dark:bg-slate-900/30 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-900/50 border border-slate-200 dark:border-slate-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                            }`}
                            title="Download the current canvas layout as versioned JSON"
                          >
                            <Download className="w-4 h-4" />
                            <span>Export JSON</span>
                          </button>
                          <button
                            type="button"
                            onClick={handleImportLayoutJsonPick}
                            disabled={isReadOnly || !selectedVersionId || !currentUserId}
                            className={`px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 ${
                              !isReadOnly && selectedVersionId && currentUserId
                                ? 'bg-slate-50 dark:bg-slate-900/30 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-900/50 border border-slate-200 dark:border-slate-700'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-400 cursor-not-allowed border border-gray-200 dark:border-gray-600'
                            }`}
                            title="Apply a layout from a JSON file exported from Objectified"
                          >
                            <FileJson className="w-4 h-4" />
                            <span>Import JSON</span>
                          </button>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                          Versioned JSON for sharing layouts across versions and projects. Import applies only classes that exist in this version.
                        </p>
                        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 space-y-2">
                          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Default on open
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Choose which named layout loads first for this version. Your preference overrides the team default.
                          </p>
                          <div className="flex flex-col gap-2">
                            <button
                              type="button"
                              onClick={() => void handleSetMyDefaultLayoutName()}
                              disabled={isReadOnly || !selectedLayoutName.trim()}
                              className={`flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                                isReadOnly || !selectedLayoutName.trim()
                                  ? 'border-gray-200 dark:border-gray-600 bg-gray-100 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
                                  : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600'
                              }`}
                              title="Use the current layout name as your personal default when opening this version"
                            >
                              <Bookmark className="h-4 w-4 shrink-0" aria-hidden />
                              Set as my default
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleClearMyDefaultLayoutName()}
                              disabled={isReadOnly}
                              className={`text-xs text-left px-1 py-0.5 rounded ${
                                isReadOnly
                                  ? 'text-gray-400 cursor-not-allowed'
                                  : 'text-indigo-600 dark:text-indigo-400 hover:underline'
                              }`}
                            >
                              Clear my default
                            </button>
                            {effectiveIsTenantAdmin && currentTenantId ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() => void handleSetTeamDefaultLayoutName()}
                                  disabled={isReadOnly || !selectedLayoutName.trim()}
                                  className={`flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                                    isReadOnly || !selectedLayoutName.trim()
                                      ? 'border-gray-200 dark:border-gray-600 bg-gray-100 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
                                      : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600'
                                  }`}
                                  title="Team default for members who have not set a personal default"
                                >
                                  <Users className="h-4 w-4 shrink-0" aria-hidden />
                                  Set as team default
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void handleClearTeamDefaultLayoutName()}
                                  disabled={isReadOnly}
                                  className={`text-xs text-left px-1 py-0.5 rounded ${
                                    isReadOnly
                                      ? 'text-gray-400 cursor-not-allowed'
                                      : 'text-indigo-600 dark:text-indigo-400 hover:underline'
                                  }`}
                                >
                                  Clear team default
                                </button>
                              </>
                            ) : null}
                          </div>
                        </div>
                        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                          <button
                            type="button"
                            onClick={() => setLayoutHistoryOpen((open) => !open)}
                            aria-expanded={layoutHistoryOpen}
                            aria-controls="layout-history-panel"
                            className="flex w-full items-center justify-between gap-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400"
                          >
                            <span className="flex items-center gap-1.5">
                              <History className="h-3.5 w-3.5 shrink-0" aria-hidden />
                              Layout history
                            </span>
                            {layoutHistoryOpen ? (
                              <ChevronUp className="h-4 w-4 shrink-0" aria-hidden />
                            ) : (
                              <ChevronDown className="h-4 w-4 shrink-0" aria-hidden />
                            )}
                          </button>
                          {layoutHistoryOpen && (
                            <div id="layout-history-panel" className="mt-2 max-h-40 space-y-1 overflow-y-auto">
                              {layoutHistoryLoading && (
                                <p className="text-xs text-gray-500 dark:text-gray-400">Loading history…</p>
                              )}
                              {!layoutHistoryLoading && layoutHistoryRevisions.length === 0 && (
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  No prior versions yet. Each named save stores the previous state (up to 50).
                                </p>
                              )}
                              {!layoutHistoryLoading &&
                                layoutHistoryRevisions.map((rev) => (
                                  <div
                                    key={rev.id}
                                    className="flex items-center justify-between gap-2 rounded-md py-1 text-xs"
                                  >
                                    <span className="min-w-0 truncate text-gray-600 dark:text-gray-300">
                                      Rev {rev.revision} ·{' '}
                                      {typeof rev.created_at === 'string'
                                        ? new Date(rev.created_at).toLocaleString()
                                        : ''}
                                    </span>
                                    <button
                                      type="button"
                                      disabled={isReadOnly}
                                      onClick={() => void handleRestoreLayoutRevision(rev.id)}
                                      className="shrink-0 rounded border border-indigo-200 px-2 py-0.5 text-indigo-700 transition-colors hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-indigo-700 dark:text-indigo-300 dark:hover:bg-indigo-950/40"
                                    >
                                      Restore
                                    </button>
                                  </div>
                                ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* #517 Presentation slides */}
                      <div className="border-t border-gray-200 dark:border-gray-700 mx-4" />
                      <div className="px-4 py-3">
                        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                          <Presentation className="h-3.5 w-3.5 shrink-0" aria-hidden />
                          Presentation
                        </h4>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                          Save viewport positions as slides, then present fullscreen with notes and a timer (local to this browser).
                        </p>
                        <button
                          type="button"
                          onClick={addPresentationSlideFromView}
                          disabled={isReadOnly || !selectedVersionId}
                          className="w-full mb-2 px-3 py-2 text-sm font-medium rounded-lg border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-800 dark:text-indigo-200 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Add slide from current view
                        </button>
                        <ul className="mb-2 max-h-32 space-y-1 overflow-y-auto">
                          {presentationBookmarks.map((b, idx) => (
                            <li key={b.id} className="flex items-center gap-1 text-xs">
                              <span className="w-4 shrink-0 tabular-nums text-gray-400">{idx + 1}.</span>
                              <input
                                value={b.title}
                                onChange={(e) => updatePresentationSlideTitle(b.id, e.target.value)}
                                className="min-w-0 flex-1 rounded border border-gray-200 bg-white px-1.5 py-0.5 text-gray-800 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
                                aria-label={`Slide ${idx + 1} title`}
                              />
                              <button
                                type="button"
                                onClick={() => {
                                  setPresentationSlideIndex(idx);
                                  applyPresentationSlide(idx, presentationBookmarks);
                                }}
                                className="shrink-0 text-indigo-600 hover:underline dark:text-indigo-400"
                              >
                                Go
                              </button>
                              <button
                                type="button"
                                onClick={() => removePresentationSlide(b.id)}
                                className="shrink-0 rounded p-0.5 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                                title="Remove slide"
                                aria-label={`Remove slide ${idx + 1}`}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </li>
                          ))}
                        </ul>
                        <button
                          type="button"
                          onClick={() => void startPresentation()}
                          disabled={presentationBookmarks.length === 0}
                          className="flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
                        >
                          <Presentation className="h-4 w-4 shrink-0" aria-hidden />
                          Start presentation
                        </button>
                      </div>

                      {/* Divider */}
                      <div className="border-t border-gray-200 dark:border-gray-700 mx-4" />

                      {/* Auto-arrange Section */}
                      <div className="px-4 py-3">
                        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                          Auto Layout
                        </h4>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={handleAutoArrangeTB}
                            disabled={nodes.filter(n => n.type !== 'groupNode').length === 0}
                            className="px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/50 border border-teal-200 dark:border-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            title="Arrange classes top to bottom"
                          >
                            <MoveVertical className="w-4 h-4" />
                          </button>
                          <button
                            onClick={handleAutoArrangeLR}
                            disabled={nodes.filter(n => n.type !== 'groupNode').length === 0}
                            className="px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/50 border border-teal-200 dark:border-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            title="Arrange classes left to right"
                          >
                            <MoveHorizontal className="w-4 h-4" />
                          </button>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                          Automatically arrange classes hierarchically based on relationships
                        </p>
                      </div>

                      <div className="border-t border-gray-200 dark:border-gray-700 mx-4" />

                      {/* #547 Dependency graph overlay */}
                      <div className="px-4 py-3">
                        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                          Visualization
                        </h4>
                        <label className="flex items-center gap-3 px-1 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <input
                            type="checkbox"
                            checked={showDependencyOverlay}
                            onChange={(e) => setShowDependencyOverlay(e.target.checked)}
                            className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500"
                          />
                          <Network className="h-4 w-4 shrink-0 text-indigo-500" />
                          <span>Dependency graph</span>
                        </label>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 px-1">
                          Highlight $ref and allOf/anyOf/oneOf edges, dim the rest
                        </p>
                        {/* #551: Upstream/downstream dependency view toggles */}
                        {showDependencyOverlay && (
                          <div className="mt-2 px-1">
                            <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1.5">View</span>
                            <ToggleGroup.Root
                              type="single"
                              value={dependencyView}
                              onValueChange={(v) => v && (v === 'all' || v === 'upstream' || v === 'downstream' || v === 'path') && setDependencyView(v)}
                              className="flex rounded-md overflow-hidden border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800"
                              aria-label="Dependency view"
                            >
                              <ToggleGroup.Item
                                value="all"
                                className="px-2.5 py-1.5 text-xs font-medium data-[state=on]:bg-indigo-100 dark:data-[state=on]:bg-indigo-900/50 data-[state=on]:text-indigo-800 dark:data-[state=on]:text-indigo-200 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                              >
                                All
                              </ToggleGroup.Item>
                              <ToggleGroup.Item
                                value="upstream"
                                className="px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-100 dark:data-[state=on]:bg-indigo-900/50 data-[state=on]:text-indigo-800 dark:data-[state=on]:text-indigo-200 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                                title="What this class depends on (select a class on canvas)"
                              >
                                <ArrowUp className="h-3 w-3" />
                                Upstream
                              </ToggleGroup.Item>
                              <ToggleGroup.Item
                                value="downstream"
                                className="px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-100 dark:data-[state=on]:bg-indigo-900/50 data-[state=on]:text-indigo-800 dark:data-[state=on]:text-indigo-200 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                                title="What depends on this class (select a class on canvas)"
                              >
                                <ArrowDown className="h-3 w-3" />
                                Downstream
                              </ToggleGroup.Item>
                              <ToggleGroup.Item
                                value="path"
                                className="px-2.5 py-1.5 text-xs font-medium flex items-center gap-1 data-[state=on]:bg-indigo-100 dark:data-[state=on]:bg-indigo-900/50 data-[state=on]:text-indigo-800 dark:data-[state=on]:text-indigo-200 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                                title="Trace full chain: click a class to highlight upstream + downstream path"
                              >
                                <Route className="h-3 w-3" />
                                Path
                              </ToggleGroup.Item>
                            </ToggleGroup.Root>
                            {(dependencyView === 'upstream' || dependencyView === 'downstream' || dependencyView === 'path') && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Select a class on the canvas to trace</p>
                            )}
                          </div>
                        )}
                        {/* #550 Impact Analysis mode */}
                        <label className="flex items-center gap-3 px-1 py-2 mt-2 text-sm text-gray-700 dark:text-gray-300 rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <input
                            type="checkbox"
                            checked={impactAnalysisMode}
                            onChange={(e) => setImpactAnalysisMode(e.target.checked)}
                            className="rounded border-gray-300 dark:border-gray-600 text-amber-600 focus:ring-amber-500"
                          />
                          <Zap className="h-4 w-4 shrink-0 text-amber-500" />
                          <span>Impact Analysis</span>
                        </label>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 px-1">
                          Select a class to see all affected (dependent) classes
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
            )}

            {/* Export Button Panel */}
            {!canvasPresentationActive && (
            <Panel
              position="top-right"
              className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80"
            >
              <button
                onClick={() => setExportWizardOpen(true)}
                className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md"
                title="Export canvas"
              >
                <Download className="w-5 h-5" />
              </button>
            </Panel>
            )}

            {/* Schema Metrics & Memory Profiler buttons - next to map controls (bottom-left) */}
            {!canvasPresentationActive && (
            <Panel
              position="bottom-left"
              className="flex items-center gap-1 bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80"
              style={{ marginBottom: '15px', marginLeft: '52px' }}
            >
              {!schemaMetricsOpen && (
                <button
                  onClick={() => setSchemaMetricsOpen(true)}
                  className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md"
                  title="Schema Metrics"
                >
                  <BarChart3 className="w-5 h-5" />
                </button>
              )}
              {!schemaTimelineOpen && (
                <button
                  onClick={() => setSchemaTimelineOpen(true)}
                  className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md"
                  title="Schema timeline — evolution across versions"
                >
                  <TrendingUp className="w-5 h-5" />
                </button>
              )}
              {!memoryProfilerOpen && (
                <button
                  onClick={() => setMemoryProfilerOpen(true)}
                  className="p-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 shadow-sm hover:shadow-md"
                  title="Memory Profiler"
                >
                  <Activity className="w-5 h-5" />
                </button>
              )}
            </Panel>
            )}

            {canvasPresentationActive && (
              <>
                <Panel position="bottom-center" className="z-[1002] mb-2 max-w-[min(100%,42rem)]">
                  <CanvasPresentationPanel
                    slideLabel={presentationBookmarks[presentationSlideIndex]?.title ?? 'Slide'}
                    slideIndexDisplay={presentationBookmarks.length === 0 ? 0 : presentationSlideIndex + 1}
                    slideTotal={Math.max(1, presentationBookmarks.length)}
                    elapsedLabel={presentationElapsedLabel}
                    showSpeakerNotes={presentationShowSpeakerNotes}
                    onToggleSpeakerNotes={() => setPresentationShowSpeakerNotes((v) => !v)}
                    onPrev={goPresentationPrev}
                    onNext={goPresentationNext}
                    onResetTimer={() => {
                      setPresentationTimerStartMs(Date.now());
                      setPresentationTimerTick((x) => x + 1);
                    }}
                    onExit={() => void exitPresentation()}
                    canGoPrev={presentationSlideIndex > 0}
                    canGoNext={
                      presentationBookmarks.length > 0 &&
                      presentationSlideIndex < presentationBookmarks.length - 1
                    }
                  />
                </Panel>
                {presentationHintVisible && (
                  <Panel position="top-center" className="z-[1002] !mt-4 max-w-lg">
                    <PresentationExitHint onDismiss={() => setPresentationHintVisible(false)} />
                  </Panel>
                )}
              </>
            )}

              </ReactFlow>
              </div>
            {canvasPresentationActive && presentationShowSpeakerNotes && (
              <aside className="flex h-full max-h-full w-80 min-w-0 shrink-0 flex-col border-l border-gray-200 bg-white/98 dark:border-gray-700 dark:bg-gray-950/98">
                <div className="border-b border-gray-200 px-3 py-2 dark:border-gray-700">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Speaker notes
                  </p>
                  <p className="text-[10px] text-gray-500 dark:text-gray-500">
                    Current slide only · saved with this version (this browser)
                  </p>
                </div>
                <textarea
                  value={presentationBookmarks[presentationSlideIndex]?.speakerNote ?? ''}
                  onChange={(e) => {
                    const id = presentationBookmarks[presentationSlideIndex]?.id;
                    if (id) updatePresentationSlideNote(id, e.target.value);
                  }}
                  className="min-h-0 flex-1 resize-none border-0 bg-transparent px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-0 dark:text-gray-100 dark:placeholder:text-gray-600"
                  placeholder="Notes for this slide…"
                  aria-label="Speaker notes for current slide"
                />
              </aside>
            )}
            </div>

          {/* Draggable panels (outside ReactFlow so position:fixed is viewport-relative) */}
          {schemaMetricsOpen && !canvasPresentationActive && (
            <DraggablePanel
              storageKey="schema-metrics-panel"
              defaultPosition={{ left: 20, top: 120 }}
            >
                <SchemaMetricsPanel
                  metrics={schemaMetrics}
                  layoutQuality={layoutQuality}
                  suggestions={canvasSuggestions}
                  onSuggestionAction={handleSuggestionAction}
                  onClose={() => setSchemaMetricsOpen(false)}
                  isMinimized={schemaMetricsMinimized}
                  onMinimizeToggle={() => setSchemaMetricsMinimized(!schemaMetricsMinimized)}
                />
            </DraggablePanel>
          )}
          {memoryProfilerOpen && !canvasPresentationActive && (
            <DraggablePanel
              storageKey="memory-profiler-panel"
              defaultPosition={{ left: 20, top: 120 }}
            >
              <MemoryProfiler
                nodeCount={nodes.filter(n => n.type !== 'groupNode').length}
                edgeCount={edges.length}
                groupCount={nodes.filter(n => n.type === 'groupNode').length}
                onClose={() => setMemoryProfilerOpen(false)}
                isMinimized={memoryProfilerMinimized}
                onMinimizeToggle={() => setMemoryProfilerMinimized(!memoryProfilerMinimized)}
              />
            </DraggablePanel>
          )}
          {schemaTimelineOpen && !canvasPresentationActive && (
            <DraggablePanel
              storageKey="schema-timeline-panel"
              defaultPosition={{ left: 20, top: 280 }}
            >
              <SchemaTimelinePanel
                versions={versions}
                selectedVersionId={selectedVersionId}
                onSelectVersion={(versionId) => {
                  setSelectedVersionId(versionId);
                  const v = versions.find((x) => x.id === versionId);
                  setIsReadOnly(v?.published ?? false);
                }}
                onClose={() => setSchemaTimelineOpen(false)}
                isMinimized={schemaTimelineMinimized}
                onMinimizeToggle={() => setSchemaTimelineMinimized(!schemaTimelineMinimized)}
              />
            </DraggablePanel>
          )}

          {/* Export Wizard Dialog */}
          <ExportWizard
            open={exportWizardOpen}
            onClose={() => setExportWizardOpen(false)}
            nodes={nodes}
            edges={edges}
            groups={groups.map((g) => ({ id: g.id, name: g.name, nodeIds: g.nodeIds }))}
            isDark={isDark}
            projectName={projects.find(p => p.id === selectedProjectId)?.name || 'canvas'}
            versionId={versions.find(v => v.version_id === selectedVersionId)?.version_id || '1'}
            alertDialog={alertDialog}
          />
          </>
        ) : viewMode === 'code' ? (
          // Monaco Editor Code View - OpenAPI 3.1.0 Specification
          <div className="h-full flex flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
            <div className="bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-5">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl shadow-lg shadow-indigo-500/25">
                      <Code2 className="w-5 h-5 text-white" />
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
        onSaved={async (applyLayout?: boolean) => {
          if (applyLayout) {
            await reloadClasses(true);
          } else if (editingClassId) {
            await updateSingleClassNode(editingClassId);
            triggerSidebarRefresh();
          } else {
            await reloadClasses(false);
          }
        }}
        allClassProperties={
          editingClassId
            ? (nodes.find(n => n.id === editingClassId)?.data as any)?.properties || []
            : []
        }
        existingClassNames={nodes.map(n => (n.data as any).name).filter(Boolean)}
        availableClasses={nodes.map(n => ({
          id: n.id,
          name: (n.data as any).name
        })).filter(c => c.name)}
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
        versionId={selectedVersionId || ''}
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

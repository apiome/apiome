'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, ReactNode, Dispatch, SetStateAction } from 'react';
import { usePathname } from 'next/navigation';
import {
  getCachedInitialCanvasPrefsBundle,
  getCanvasSurfaceFromPathname,
  loadCanvasPrefsBundle,
  studioCanvasPrefStorageKey,
  type StudioCanvasSurface,
} from './lib/studio-canvas-prefs-storage';
import type { OverallSchemaQualityDetail } from '@/app/utils/overall-schema-quality';
import type { VersionBranchRow } from '@/app/components/ade/version-dialogs/types';
import type {
  StudioGitPaletteActionId,
  StudioGitPaletteHandlers,
} from '@/app/utils/studio-keybindings';

// Group style options
export interface GroupStyleOptions {
  borderStyle: 'dashed' | 'solid' | 'dotted';
  opacity: number;
  shadow: 'none' | 'sm' | 'md' | 'lg';
  icon: string;
}

// Group tag definition
export interface GroupTag {
  id: string;
  name: string;
  color: string;
}

// Group definition for canvas grouping
export interface CanvasGroup {
  id: string;
  name: string;
  description?: string;
  color: string;
  nodeIds: string[];
  /** Parent canvas group for nesting (#155); omit or null = top-level. */
  parentId?: string | null;
  tags?: GroupTag[];
  position: { x: number; y: number };
  dimensions: { width: number; height: number };
  styleOptions?: GroupStyleOptions;
}

// Edge styling options
export type EdgeStyleType = 'solid' | 'dashed' | 'dotted' | 'double';

// Edge routing options
export type EdgeRoutingType = 'straight' | 'bezier' | 'orthogonal' | 'smart';

// Edge animation options
export type EdgeAnimationType = 'none' | 'flow' | 'pulse' | 'dash';

// Edge arrow style options
export type EdgeArrowStyle = 'arrow' | 'diamond' | 'circle' | 'open';

// Canvas background types
export type CanvasBackgroundType = 'solid' | 'grid' | 'image' | 'gradient' | 'texture';
export type GradientDirection = 'to-r' | 'to-l' | 'to-t' | 'to-b' | 'to-tr' | 'to-tl' | 'to-br' | 'to-bl';
export type TextureType = 'noise' | 'paper' | 'fabric' | 'carbon' | 'concrete' | 'wood';

export interface CanvasBackgroundOptions {
  type: CanvasBackgroundType;
  solidColor: string;
  gridColor: string;
  gridOpacity: number;
  imageUrl: string;
  imageOpacity: number;
  imageFit: 'cover' | 'contain' | 'tile' | 'center';
  gradientFrom: string;
  gradientTo: string;
  gradientDirection: GradientDirection;
  textureType: TextureType;
  textureOpacity: number;
  textureColor: string;
  // New: background-level opacity and blur
  backgroundOpacity: number; // 0-1
  backgroundBlur: number; // 0-20 (px)
}

export interface EdgeStylingOptions {
  directReferences: EdgeStyleType;
  optionalReferences: EdgeStyleType;
  weakReferences: EdgeStyleType;
  bidirectional: EdgeStyleType;
  directColor: string;
  optionalColor: string;
  weakColor: string;
  bidirectionalColor: string;
  // Arrow styles
  directArrowStyle: EdgeArrowStyle;
  optionalArrowStyle: EdgeArrowStyle;
  weakArrowStyle: EdgeArrowStyle;
  bidirectionalArrowStyle: EdgeArrowStyle;
}

interface StudioContextType {
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
  selectedVersionId: string | null;
  setSelectedVersionId: (id: string | null) => void;
  /** Named version branch whose tip matches the current revision when applicable (#2722 GLI-03). */
  selectedBranchId: string | null;
  setSelectedBranchId: (id: string | null) => void;
  /** Cached GET /version-branches per project for branch chip + resolution. */
  versionBranchesByProjectId: Record<string, VersionBranchRow[]>;
  setVersionBranchesForProject: (projectId: string, branches: VersionBranchRow[]) => void;
  /** Registered by `DesignerCanvasGitMenu` so "New branch" in the branch submenu can open the dialog. */
  registerBranchFromRevisionOpener: (fn: (() => void) | null) => void;
  openBranchFromRevisionDialog: () => void;
  /** Mergeable handlers for `GitCommandPalette` — registered by `DesignerCanvasGitMenu`. */
  registerGitPaletteHandler: <K extends StudioGitPaletteActionId>(
    key: K,
    fn: StudioGitPaletteHandlers[K] | null
  ) => void;
  invokeGitPaletteAction: (key: StudioGitPaletteActionId) => boolean;
  canvasRefreshKey: number;
  triggerCanvasRefresh: () => void;
  sidebarRefreshKey: number;
  triggerSidebarRefresh: () => void;
  isReadOnly: boolean;
  setIsReadOnly: (value: boolean) => void;
  zoomToClassFn: ((classId: string) => void) | null;
  setZoomToClassFn: (fn: ((classId: string) => void) | null) => void;
  toggleClassVisibilityFn: ((classId: string, visible?: boolean) => void) | null;
  setToggleClassVisibilityFn: (fn: ((classId: string, visible?: boolean) => void) | null) => void;
  hiddenClassIds: string[];
  setHiddenClassIds: (ids: string[]) => void;
  createGroupFn: (() => void) | null;
  setCreateGroupFn: (fn: (() => void) | null) => void;
  createGroupAtPositionFn: ((position: { x: number; y: number }) => void) | null;
  setCreateGroupAtPositionFn: (fn: ((position: { x: number; y: number }) => void) | null) => void;
  clickToFocusEnabled: boolean;
  setClickToFocusEnabled: (value: boolean) => void;
  lodEnabled: boolean;
  setLodEnabled: (value: boolean) => void;
  // Grid settings
  gridSize: number;
  setGridSize: (size: number) => void;
  snapToGrid: boolean;
  setSnapToGrid: (enabled: boolean) => void;
  gridStyle: 'dots' | 'lines' | 'cross';
  setGridStyle: (style: 'dots' | 'lines' | 'cross') => void;
  showGrid: boolean;
  setShowGrid: (visible: boolean) => void;
  /** When set, overrides showGrid for export capture only (e.g. Export Wizard). Do not persist. */
  exportGridOverride: boolean | null;
  setExportGridOverride: (visible: boolean | null) => void;
  // Smart guides
  smartGuidesEnabled: boolean;
  setSmartGuidesEnabled: (enabled: boolean) => void;
  // Auto-save layout settings
  autoSaveLayoutEnabled: boolean;
  setAutoSaveLayoutEnabled: (enabled: boolean) => void;
  autoSaveLayoutIntervalSeconds: number;
  setAutoSaveLayoutIntervalSeconds: (seconds: number) => void;
  // Edge styling
  edgeStyling: EdgeStylingOptions;
  setEdgeStyling: (options: EdgeStylingOptions) => void;
  // Edge routing
  edgeRouting: EdgeRoutingType;
  setEdgeRouting: (routing: EdgeRoutingType) => void;
  // Edge animation
  edgeAnimation: EdgeAnimationType;
  setEdgeAnimation: (animation: EdgeAnimationType) => void;
  // Canvas background
  canvasBackground: CanvasBackgroundOptions;
  setCanvasBackground: (options: CanvasBackgroundOptions) => void;
  // Group management
  groups: CanvasGroup[];
  setGroups: (groups: CanvasGroup[]) => void;
  addGroup: (group: CanvasGroup) => void;
  updateGroup: (groupId: string, updates: Partial<CanvasGroup>) => void;
  deleteGroup: (groupId: string) => void;
  /** Called to delete all classes contained in a group (registered by editor). */
  deleteAllClassesInGroupFn: ((groupId: string, classIds?: string[], groupName?: string) => Promise<void>) | null;
  setDeleteAllClassesInGroupFn: (fn: ((groupId: string, classIds?: string[], groupName?: string) => Promise<void>) | null) => void;
  /** Full group delete from sidebar: nested subtree, canvas nodes, layout persistence (registered by editor). */
  deleteGroupFn: ((groupId: string) => Promise<void>) | null;
  setDeleteGroupFn: Dispatch<SetStateAction<((groupId: string) => Promise<void>) | null>>;
  addNodeToGroup: (groupId: string, nodeId: string) => void;
  removeNodeFromGroup: (groupId: string, nodeId: string) => void;
  // Search history
  searchHistoryCount: number;
  setSearchHistoryCount: (count: number) => void;
  clearSearchHistoryFn: (() => void) | null;
  setClearSearchHistoryFn: (fn: (() => void) | null) => void;
  /** Clears React Flow selection on the editor canvas (registered by editor); used before leaving canvas view (#2595). */
  clearCanvasSelectionFn: (() => void) | null;
  setClearCanvasSelectionFn: (fn: (() => void) | null) => void;
  /** Hides group floating toolbars (hover/settings/export still open); set before switching to Code so no stray clicks (#2595). */
  suppressGroupFloatingToolbars: boolean;
  setSuppressGroupFloatingToolbars: (value: boolean) => void;
  /** While editor is on the Code tab, pathname can still be /editor — disable sidebar group destructive row actions (#2595). */
  suppressGroupSidebarDestructive: boolean;
  setSuppressGroupSidebarDestructive: (value: boolean) => void;
  /** When true, studio chrome (sidebar, studio header) is hidden for canvas presentation mode (#517). */
  canvasPresentationMode: boolean;
  setCanvasPresentationMode: (value: boolean) => void;
  /** Live overall schema quality 0–100 from Canvas (#245); null when not on editor or no classes yet */
  schemaQualityScore: number | null;
  setSchemaQualityScore: (value: number | null) => void;
  /** Weighted breakdown for header dialog / metrics card (#2548); null when score is unavailable */
  schemaQualityDetail: OverallSchemaQualityDetail | null;
  setSchemaQualityDetail: (value: OverallSchemaQualityDetail | null) => void;
  /** Canvas / studio edits not yet persisted (#2569). */
  syncLocalDirty: boolean;
  setSyncLocalDirty: (value: boolean) => void;
  /** Live React Flow viewport published by canvas surfaces; consumed by the studio footer bar. */
  canvasViewport: { zoom: number; x: number; y: number };
  setCanvasViewport: (vp: { zoom: number; x: number; y: number }) => void;
  /** Resolved display label for the selected project, published by StudioHeader once projects load. */
  selectedProjectName: string | null;
  setSelectedProjectName: (name: string | null) => void;
  /** Project metadata `domainCategory` id for the selected project, published by StudioHeader (#615). */
  selectedProjectDomainCategoryId: string | null;
  setSelectedProjectDomainCategoryId: (id: string | null) => void;
  /** Resolved display label for the selected version (e.g. "v1.2.3"), published by StudioHeader. */
  selectedVersionLabel: string | null;
  setSelectedVersionLabel: (label: string | null) => void;
  /** Paths editor: canvas vs code (sessionStorage `studio.paths.viewMode`; #2640 P-01). */
  pathsViewMode: 'canvas' | 'code';
  setPathsViewMode: (mode: 'canvas' | 'code') => void;
  /** Registered by Paths canvas: flush debounced layout save before switching to Code (#2654). */
  registerPathsCanvasFlush: (fn: (() => Promise<void>) | null) => void;
  flushPathsCanvas: () => Promise<void>;
  /** Bumped when Paths canvas/code data changes so PATH QUALITY can recompute (#2656). */
  pathsQualityRevision: number;
  bumpPathsQualityRevision: () => void;
  /** Registered by Paths canvas: zoom to a node by React Flow id (DB operation id or path-node-*). */
  focusPathsCanvasNodeFn: ((nodeId: string) => void) | null;
  setFocusPathsCanvasNodeFn: (fn: ((nodeId: string) => void) | null) => void;
  /**
   * Class node IDs currently selected on the editor canvas (#259). Published
   * by the editor's React Flow `onSelectionChange` so chrome surfaces — most
   * notably the Studio AI chatbot — can ground their behaviour in what the
   * user is looking at.
   */
  selectedCanvasNodeIds: string[];
  setSelectedCanvasNodeIds: (ids: string[]) => void;
}

export const PATHS_VIEW_MODE_STORAGE_KEY = 'studio.paths.viewMode';

const StudioContext = createContext<StudioContextType | undefined>(undefined);

export function StudioProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const canvasSurface: StudioCanvasSurface = useMemo(
    () => getCanvasSurfaceFromPathname(pathname),
    [pathname]
  );

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [versionBranchesByProjectId, setVersionBranchesByProjectId] = useState<
    Record<string, VersionBranchRow[]>
  >({});
  const branchFromRevisionOpenerRef = useRef<(() => void) | null>(null);
  const registerBranchFromRevisionOpener = useCallback((fn: (() => void) | null) => {
    branchFromRevisionOpenerRef.current = fn;
  }, []);
  const openBranchFromRevisionDialog = useCallback(() => {
    branchFromRevisionOpenerRef.current?.();
  }, []);

  const gitPaletteHandlersRef = useRef<StudioGitPaletteHandlers>({});
  const registerGitPaletteHandler = useCallback(
    <K extends StudioGitPaletteActionId>(key: K, fn: StudioGitPaletteHandlers[K] | null) => {
      if (fn == null) {
        delete gitPaletteHandlersRef.current[key];
      } else {
        gitPaletteHandlersRef.current[key] = fn;
      }
    },
    []
  );
  const invokeGitPaletteAction = useCallback((key: StudioGitPaletteActionId) => {
    const fn = gitPaletteHandlersRef.current[key];
    if (typeof fn === 'function') {
      fn();
      return true;
    }
    return false;
  }, []);

  const setVersionBranchesForProject = useCallback((projectId: string, branches: VersionBranchRow[]) => {
    setVersionBranchesByProjectId((prev) => ({ ...prev, [projectId]: branches }));
  }, []);

  const [canvasRefreshKey, setCanvasRefreshKey] = useState<number>(0);
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState<number>(0);
  const [isReadOnly, setIsReadOnly] = useState<boolean>(false);
  const [zoomToClassFn, setZoomToClassFn] = useState<((classId: string) => void) | null>(null);
  const [toggleClassVisibilityFn, setToggleClassVisibilityFn] = useState<((classId: string, visible?: boolean) => void) | null>(null);
  const [hiddenClassIds, setHiddenClassIds] = useState<string[]>([]);
  const [createGroupFn, setCreateGroupFn] = useState<(() => void) | null>(null);
  const [createGroupAtPositionFn, setCreateGroupAtPositionFn] = useState<((position: { x: number; y: number }) => void) | null>(null);

  /** Namespaced per-surface prefs — see lib/studio-canvas-prefs-storage.ts (#2641). */
  const [clickToFocusEnabled, setClickToFocusEnabled] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).clickToFocusEnabled
  );
  const [lodEnabled, setLodEnabled] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).lodEnabled
  );

  const [gridSize, setGridSize] = useState<number>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).gridSize
  );

  const [snapToGrid, setSnapToGrid] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).snapToGrid
  );

  const [gridStyle, setGridStyle] = useState<'dots' | 'lines' | 'cross'>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).gridStyle
  );

  const [showGrid, setShowGrid] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).showGrid
  );

  /** Temporary override for grid visibility during export (#407). Not persisted. */
  const [exportGridOverride, setExportGridOverride] = useState<boolean | null>(null);

  const [smartGuidesEnabled, setSmartGuidesEnabled] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).smartGuidesEnabled
  );
  const [autoSaveLayoutEnabled, setAutoSaveLayoutEnabled] = useState<boolean>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).autoSaveLayoutEnabled
  );
  const [autoSaveLayoutIntervalSeconds, setAutoSaveLayoutIntervalSecondsRaw] = useState<number>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).autoSaveLayoutIntervalSeconds
  );
  const setAutoSaveLayoutIntervalSeconds = useCallback((seconds: number) => {
    setAutoSaveLayoutIntervalSecondsRaw(Math.min(300, Math.max(10, seconds)));
  }, []);

  const [edgeStyling, setEdgeStyling] = useState<EdgeStylingOptions>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).edgeStyling
  );

  const [edgeRouting, setEdgeRouting] = useState<EdgeRoutingType>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).edgeRouting
  );

  const [edgeAnimation, setEdgeAnimation] = useState<EdgeAnimationType>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).edgeAnimation
  );

  const [canvasBackground, setCanvasBackground] = useState<CanvasBackgroundOptions>(
    () => getCachedInitialCanvasPrefsBundle(typeof window !== 'undefined' ? window.location.pathname : null).canvasBackground
  );

  const prevCanvasSurfaceRef = useRef<StudioCanvasSurface | null>(null);
  const isSurfaceSwitchingRef = useRef(false);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (prevCanvasSurfaceRef.current === null) {
      prevCanvasSurfaceRef.current = canvasSurface;
      return;
    }
    if (prevCanvasSurfaceRef.current === canvasSurface) return;
    prevCanvasSurfaceRef.current = canvasSurface;
    const bundle = loadCanvasPrefsBundle(canvasSurface);
    isSurfaceSwitchingRef.current = true;
    queueMicrotask(() => {
      setClickToFocusEnabled(bundle.clickToFocusEnabled);
      setLodEnabled(bundle.lodEnabled);
      setGridSize(bundle.gridSize);
      setSnapToGrid(bundle.snapToGrid);
      setGridStyle(bundle.gridStyle);
      setShowGrid(bundle.showGrid);
      setSmartGuidesEnabled(bundle.smartGuidesEnabled);
      setAutoSaveLayoutEnabled(bundle.autoSaveLayoutEnabled);
      setAutoSaveLayoutIntervalSecondsRaw(bundle.autoSaveLayoutIntervalSeconds);
      setEdgeStyling(bundle.edgeStyling);
      setEdgeRouting(bundle.edgeRouting);
      setEdgeAnimation(bundle.edgeAnimation);
      setCanvasBackground(bundle.canvasBackground);
      isSurfaceSwitchingRef.current = false;
    });
  }, [canvasSurface]);

  const [groups, setGroups] = useState<CanvasGroup[]>([]);

  // Search history state
  const [searchHistoryCount, setSearchHistoryCount] = useState<number>(0);
  const [clearSearchHistoryFn, setClearSearchHistoryFn] = useState<(() => void) | null>(null);

  const [canvasPresentationMode, setCanvasPresentationMode] = useState(false);
  const [schemaQualityScore, setSchemaQualityScore] = useState<number | null>(null);
  const [schemaQualityDetail, setSchemaQualityDetail] = useState<OverallSchemaQualityDetail | null>(null);
  const [syncLocalDirty, setSyncLocalDirty] = useState(false);
  const [canvasViewport, setCanvasViewportState] = useState<{ zoom: number; x: number; y: number }>({
    zoom: 1,
    x: 0,
    y: 0,
  });
  const setCanvasViewport = useCallback((vp: { zoom: number; x: number; y: number }) => {
    setCanvasViewportState((prev) =>
      prev.zoom === vp.zoom && prev.x === vp.x && prev.y === vp.y ? prev : vp
    );
  }, []);
  const [selectedProjectName, setSelectedProjectName] = useState<string | null>(null);
  const [selectedProjectDomainCategoryId, setSelectedProjectDomainCategoryId] = useState<string | null>(null);
  const [selectedVersionLabel, setSelectedVersionLabel] = useState<string | null>(null);

  const [pathsViewMode, setPathsViewModeState] = useState<'canvas' | 'code'>(() => {
    if (typeof window === 'undefined') return 'canvas';
    try {
      const raw = sessionStorage.getItem(PATHS_VIEW_MODE_STORAGE_KEY);
      if (raw === 'canvas' || raw === 'code') return raw;
    } catch {
      /* ignore */
    }
    return 'canvas';
  });

  const setPathsViewMode = useCallback((mode: 'canvas' | 'code') => {
    setPathsViewModeState(mode);
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.setItem(PATHS_VIEW_MODE_STORAGE_KEY, mode);
      } catch {
        /* ignore */
      }
    }
  }, []);

  const pathsCanvasFlushFnRef = useRef<(() => Promise<void>) | null>(null);
  const registerPathsCanvasFlush = useCallback((fn: (() => Promise<void>) | null) => {
    pathsCanvasFlushFnRef.current = fn;
  }, []);
  const flushPathsCanvas = useCallback(async () => {
    await pathsCanvasFlushFnRef.current?.();
  }, []);

  const [pathsQualityRevision, setPathsQualityRevision] = useState(0);
  const bumpPathsQualityRevision = useCallback(() => {
    setPathsQualityRevision((n) => n + 1);
  }, []);

  const [focusPathsCanvasNodeFn, setFocusPathsCanvasNodeFn] = useState<((nodeId: string) => void) | null>(null);

  const [selectedCanvasNodeIds, setSelectedCanvasNodeIdsState] = useState<string[]>([]);
  const setSelectedCanvasNodeIds = useCallback((ids: string[]) => {
    setSelectedCanvasNodeIdsState((prev) => {
      if (prev.length === ids.length && prev.every((id, i) => id === ids[i])) return prev;
      return ids;
    });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'gridSize'), gridSize.toString());
    } catch {
      /* ignore */
    }
  }, [canvasSurface, gridSize]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'snapToGrid'), JSON.stringify(snapToGrid));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, snapToGrid]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'gridStyle'), gridStyle);
    } catch {
      /* ignore */
    }
  }, [canvasSurface, gridStyle]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'showGrid'), JSON.stringify(showGrid));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, showGrid]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'smartGuidesEnabled'), JSON.stringify(smartGuidesEnabled));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, smartGuidesEnabled]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'clickToFocusEnabled'), JSON.stringify(clickToFocusEnabled));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, clickToFocusEnabled]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'lodEnabled'), JSON.stringify(lodEnabled));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, lodEnabled]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'autoSaveLayoutEnabled'), JSON.stringify(autoSaveLayoutEnabled));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, autoSaveLayoutEnabled]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(
        studioCanvasPrefStorageKey(canvasSurface, 'autoSaveLayoutIntervalSeconds'),
        String(autoSaveLayoutIntervalSeconds)
      );
    } catch {
      /* ignore */
    }
  }, [canvasSurface, autoSaveLayoutIntervalSeconds]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'edgeStyling'), JSON.stringify(edgeStyling));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, edgeStyling]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'edgeRouting'), edgeRouting);
    } catch {
      /* ignore */
    }
  }, [canvasSurface, edgeRouting]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'edgeAnimation'), edgeAnimation);
    } catch {
      /* ignore */
    }
  }, [canvasSurface, edgeAnimation]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isSurfaceSwitchingRef.current) return;
    try {
      localStorage.setItem(studioCanvasPrefStorageKey(canvasSurface, 'canvasBackground'), JSON.stringify(canvasBackground));
    } catch {
      /* ignore */
    }
  }, [canvasSurface, canvasBackground]);

  const triggerCanvasRefresh = () => {
    setCanvasRefreshKey(prev => prev + 1);
  };

  const triggerSidebarRefresh = () => {
    setSidebarRefreshKey(prev => prev + 1);
  };

  const addGroup = (group: CanvasGroup) => {
    setGroups(prev => [...prev, group]);
  };

  const updateGroup = (groupId: string, updates: Partial<CanvasGroup>) => {
    setGroups(prev => prev.map(g =>
      g.id === groupId ? { ...g, ...updates } : g
    ));
  };

  const deleteGroup = (groupId: string) => {
    setGroups(prev => prev.filter(g => g.id !== groupId));
  };

  const [deleteAllClassesInGroupFn, setDeleteAllClassesInGroupFn] = useState<((groupId: string, classIds?: string[], groupName?: string) => Promise<void>) | null>(null);
  const [deleteGroupFn, setDeleteGroupFn] = useState<((groupId: string) => Promise<void>) | null>(null);
  const [clearCanvasSelectionFn, setClearCanvasSelectionFn] = useState<(() => void) | null>(null);
  const [suppressGroupFloatingToolbars, setSuppressGroupFloatingToolbars] = useState(false);
  const [suppressGroupSidebarDestructive, setSuppressGroupSidebarDestructive] = useState(false);

  const addNodeToGroup = (groupId: string, nodeId: string) => {
    setGroups(prev => prev.map(g => {
      if (g.id === groupId && !g.nodeIds.includes(nodeId)) {
        return { ...g, nodeIds: [...g.nodeIds, nodeId] };
      }
      return g;
    }));
  };

  const removeNodeFromGroup = (groupId: string, nodeId: string) => {
    setGroups(prev => prev.map(g => {
      if (g.id === groupId) {
        return { ...g, nodeIds: g.nodeIds.filter(id => id !== nodeId) };
      }
      return g;
    }));
  };

  return (
    <StudioContext.Provider value={{
      selectedProjectId,
      setSelectedProjectId,
      selectedVersionId,
      setSelectedVersionId,
      selectedBranchId,
      setSelectedBranchId,
      versionBranchesByProjectId,
      setVersionBranchesForProject,
      registerBranchFromRevisionOpener,
      openBranchFromRevisionDialog,
      registerGitPaletteHandler,
      invokeGitPaletteAction,
      canvasRefreshKey,
      triggerCanvasRefresh,
      sidebarRefreshKey,
      triggerSidebarRefresh,
      isReadOnly,
      setIsReadOnly,
      zoomToClassFn,
      setZoomToClassFn,
      toggleClassVisibilityFn,
      setToggleClassVisibilityFn,
      hiddenClassIds,
      setHiddenClassIds,
      createGroupFn,
      setCreateGroupFn,
      createGroupAtPositionFn,
      setCreateGroupAtPositionFn,
      clickToFocusEnabled,
      setClickToFocusEnabled,
      lodEnabled,
      setLodEnabled,
      gridSize,
      setGridSize,
      snapToGrid,
      setSnapToGrid,
      gridStyle,
      setGridStyle,
      showGrid,
      setShowGrid,
      exportGridOverride,
      setExportGridOverride,
      smartGuidesEnabled,
      setSmartGuidesEnabled,
      autoSaveLayoutEnabled,
      setAutoSaveLayoutEnabled,
      autoSaveLayoutIntervalSeconds,
      setAutoSaveLayoutIntervalSeconds,
      edgeStyling,
      setEdgeStyling,
      edgeRouting,
      setEdgeRouting,
      edgeAnimation,
      setEdgeAnimation,
      canvasBackground,
      setCanvasBackground,
      groups,
      setGroups,
      addGroup,
      updateGroup,
      deleteGroup,
      deleteAllClassesInGroupFn,
      setDeleteAllClassesInGroupFn,
      deleteGroupFn,
      setDeleteGroupFn,
      addNodeToGroup,
      removeNodeFromGroup,
      searchHistoryCount,
      setSearchHistoryCount,
      clearSearchHistoryFn,
      setClearSearchHistoryFn,
      clearCanvasSelectionFn,
      setClearCanvasSelectionFn,
      suppressGroupFloatingToolbars,
      setSuppressGroupFloatingToolbars,
      suppressGroupSidebarDestructive,
      setSuppressGroupSidebarDestructive,
      canvasPresentationMode,
      setCanvasPresentationMode,
      schemaQualityScore,
      setSchemaQualityScore,
      schemaQualityDetail,
      setSchemaQualityDetail,
      syncLocalDirty,
      setSyncLocalDirty,
      canvasViewport,
      setCanvasViewport,
      selectedProjectName,
      setSelectedProjectName,
      selectedProjectDomainCategoryId,
      setSelectedProjectDomainCategoryId,
      selectedVersionLabel,
      setSelectedVersionLabel,
      pathsViewMode,
      setPathsViewMode,
      registerPathsCanvasFlush,
      flushPathsCanvas,
      pathsQualityRevision,
      bumpPathsQualityRevision,
      focusPathsCanvasNodeFn,
      setFocusPathsCanvasNodeFn,
      selectedCanvasNodeIds,
      setSelectedCanvasNodeIds,
    }}>
      {children}
    </StudioContext.Provider>
  );
}

export function useStudio() {
  const context = useContext(StudioContext);
  if (context === undefined) {
    throw new Error('useStudio must be used within a StudioProvider');
  }
  return context;
}

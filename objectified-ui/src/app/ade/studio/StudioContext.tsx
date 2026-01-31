'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

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
  canvasRefreshKey: number;
  triggerCanvasRefresh: () => void;
  sidebarRefreshKey: number;
  triggerSidebarRefresh: () => void;
  isReadOnly: boolean;
  setIsReadOnly: (value: boolean) => void;
  zoomToClassFn: ((classId: string) => void) | null;
  setZoomToClassFn: (fn: ((classId: string) => void) | null) => void;
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
  // Smart guides
  smartGuidesEnabled: boolean;
  setSmartGuidesEnabled: (enabled: boolean) => void;
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
  addNodeToGroup: (groupId: string, nodeId: string) => void;
  removeNodeFromGroup: (groupId: string, nodeId: string) => void;
}

const StudioContext = createContext<StudioContextType | undefined>(undefined);

export function StudioProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [canvasRefreshKey, setCanvasRefreshKey] = useState<number>(0);
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState<number>(0);
  const [isReadOnly, setIsReadOnly] = useState<boolean>(false);
  const [zoomToClassFn, setZoomToClassFn] = useState<((classId: string) => void) | null>(null);
  const [createGroupFn, setCreateGroupFn] = useState<(() => void) | null>(null);
  const [createGroupAtPositionFn, setCreateGroupAtPositionFn] = useState<((position: { x: number; y: number }) => void) | null>(null);
  const [clickToFocusEnabled, setClickToFocusEnabled] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('clickToFocusEnabled');
      return saved ? JSON.parse(saved) : true; // Default to enabled
    }
    return true;
  });
  const [lodEnabled, setLodEnabled] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('lodEnabled');
      return saved ? JSON.parse(saved) : false; // Default to disabled
    }
    return false;
  });

  // Grid settings
  const [gridSize, setGridSize] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('gridSize');
      return saved ? parseInt(saved, 10) : 20; // Default to 20px
    }
    return 20;
  });

  const [snapToGrid, setSnapToGrid] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('snapToGrid');
      return saved ? JSON.parse(saved) : true; // Default to enabled
    }
    return true;
  });

  const [gridStyle, setGridStyle] = useState<'dots' | 'lines' | 'cross'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('gridStyle');
      return (saved as 'dots' | 'lines' | 'cross') || 'dots'; // Default to dots
    }
    return 'dots';
  });

  const [smartGuidesEnabled, setSmartGuidesEnabled] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('smartGuidesEnabled');
      return saved ? JSON.parse(saved) : true; // Default to enabled
    }
    return true;
  });

  const [edgeStyling, setEdgeStyling] = useState<EdgeStylingOptions>(() => {
    const defaults: EdgeStylingOptions = {
      directReferences: 'solid' as const,
      optionalReferences: 'dashed' as const,
      weakReferences: 'dotted' as const,
      bidirectional: 'double' as const,
      directColor: '#64748b', // Slate (first color in palette)
      optionalColor: '#f97316', // Orange
      weakColor: '#8b5cf6', // Purple
      bidirectionalColor: '#ec4899', // Pink
      // Arrow styles - default to standard arrow
      directArrowStyle: 'arrow' as const,
      optionalArrowStyle: 'arrow' as const,
      weakArrowStyle: 'arrow' as const,
      bidirectionalArrowStyle: 'arrow' as const,
    };

    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('edgeStyling');
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          // Merge with defaults to ensure all properties exist
          return {
            ...defaults,
            ...parsed,
          };
        } catch (e) {
          console.error('Failed to parse edge styling from localStorage:', e);
          return defaults;
        }
      }
    }
    return defaults;
  });

  const [edgeRouting, setEdgeRouting] = useState<EdgeRoutingType>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('edgeRouting');
      if (saved && ['straight', 'bezier', 'orthogonal', 'smart'].includes(saved)) {
        return saved as EdgeRoutingType;
      }
    }
    return 'bezier'; // Default to curved/bezier
  });

  const [edgeAnimation, setEdgeAnimation] = useState<EdgeAnimationType>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('edgeAnimation');
      if (saved && ['none', 'flow', 'pulse', 'dash'].includes(saved)) {
        return saved as EdgeAnimationType;
      }
    }
    return 'none'; // Default to no animation
  });

  // Canvas background settings
  const defaultCanvasBackground: CanvasBackgroundOptions = {
    type: 'grid',
    solidColor: '#f8fafc',
    gridColor: '#6366f1',
    gridOpacity: 0.15,
    imageUrl: '',
    imageOpacity: 0.5,
    imageFit: 'cover',
    gradientFrom: '#f8fafc',
    gradientTo: '#e2e8f0',
    gradientDirection: 'to-br',
    textureType: 'noise',
    textureOpacity: 0.1,
    textureColor: '#64748b',
  };

  const [canvasBackground, setCanvasBackground] = useState<CanvasBackgroundOptions>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('canvasBackground');
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          return { ...defaultCanvasBackground, ...parsed };
        } catch (e) {
          console.error('Failed to parse canvas background from localStorage:', e);
          return defaultCanvasBackground;
        }
      }
    }
    return defaultCanvasBackground;
  });

  const [groups, setGroups] = useState<CanvasGroup[]>([]);

  // Persist grid settings to localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('gridSize', gridSize.toString());
    }
  }, [gridSize]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('snapToGrid', JSON.stringify(snapToGrid));
    }
  }, [snapToGrid]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('gridStyle', gridStyle);
    }
  }, [gridStyle]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('smartGuidesEnabled', JSON.stringify(smartGuidesEnabled));
    }
  }, [smartGuidesEnabled]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('edgeStyling', JSON.stringify(edgeStyling));
    }
  }, [edgeStyling]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('edgeRouting', edgeRouting);
    }
  }, [edgeRouting]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('edgeAnimation', edgeAnimation);
    }
  }, [edgeAnimation]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('canvasBackground', JSON.stringify(canvasBackground));
    }
  }, [canvasBackground]);

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
      canvasRefreshKey,
      triggerCanvasRefresh,
      sidebarRefreshKey,
      triggerSidebarRefresh,
      isReadOnly,
      setIsReadOnly,
      zoomToClassFn,
      setZoomToClassFn,
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
      smartGuidesEnabled,
      setSmartGuidesEnabled,
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
      addNodeToGroup,
      removeNodeFromGroup
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

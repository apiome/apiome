'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

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
  clickToFocusEnabled: boolean;
  setClickToFocusEnabled: (value: boolean) => void;
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
  const [clickToFocusEnabled, setClickToFocusEnabled] = useState<boolean>(true);
  const [groups, setGroups] = useState<CanvasGroup[]>([]);

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
      clickToFocusEnabled,
      setClickToFocusEnabled,
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


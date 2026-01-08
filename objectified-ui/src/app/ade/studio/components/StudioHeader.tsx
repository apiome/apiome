'use client';

import * as React from 'react';
import { useSession } from 'next-auth/react';
import { useRouter, usePathname } from 'next/navigation';
import { Check, Settings, Palette } from 'lucide-react';
import * as Select from '@radix-ui/react-select';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Popover from '@radix-ui/react-popover';
import { useStudio } from '../StudioContext';
import { EDGE_COLORS_4X4 } from '../../../utils/color-themes';
import {
  getProjectsForTenant,
  getVersionsForProject,
  getTagsForProject
} from '../../../../../lib/db/helper';

// Helper function to determine if a color is dark
function isColorDark(hexColor: string | undefined): boolean {
  if (!hexColor) hexColor = '#64748b'; // Default to Slate gray if undefined
  const hex = hexColor.replace('#', '');
  const r = parseInt(hex.substr(0, 2), 16);
  const g = parseInt(hex.substr(2, 2), 16);
  const b = parseInt(hex.substr(4, 2), 16);
  // Calculate relative luminance
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance < 0.5;
}

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

type ViewMode = 'editor' | 'paths' | 'code';

interface StudioHeaderProps {
  projectTags?: any[];
  onProjectTagsLoaded?: (tags: any[]) => void;
}

export default function StudioHeader({ onProjectTagsLoaded }: StudioHeaderProps) {
  const { data: session } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const currentTenantId = (session?.user as any)?.current_tenant_id;

  const {
    selectedProjectId,
    setSelectedProjectId: setContextProjectId,
    selectedVersionId,
    setSelectedVersionId: setContextVersionId,
    setIsReadOnly,
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
    setEdgeRouting
  } = useStudio();

  const [projects, setProjects] = React.useState<Project[]>([]);
  const [versions, setVersions] = React.useState<Version[]>([]);
  const [localProjectId, setLocalProjectId] = React.useState<string>(selectedProjectId || '');
  const [localVersionId, setLocalVersionId] = React.useState<string>(selectedVersionId || '');
  const [isLoadingProjects, setIsLoadingProjects] = React.useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = React.useState(false);

  // Determine current view mode from pathname
  const viewMode: ViewMode = pathname?.includes('/code')
    ? 'code'
    : pathname?.includes('/paths')
      ? 'paths'
      : 'editor';

  // Toggle click-to-focus mode
  const toggleClickToFocus = React.useCallback(() => {
    setClickToFocusEnabled(!clickToFocusEnabled);
    localStorage.setItem('clickToFocusEnabled', JSON.stringify(!clickToFocusEnabled));
  }, [clickToFocusEnabled, setClickToFocusEnabled]);

  // Toggle LOD mode
  const toggleLod = React.useCallback(() => {
    const newValue = !lodEnabled;
    setLodEnabled(newValue);
    localStorage.setItem('lodEnabled', JSON.stringify(newValue));
  }, [lodEnabled, setLodEnabled]);

  // Sync local state with context
  React.useEffect(() => {
    if (selectedProjectId !== localProjectId) {
      setLocalProjectId(selectedProjectId || '');
    }
    if (selectedVersionId !== localVersionId) {
      setLocalVersionId(selectedVersionId || '');
    }
  }, [selectedProjectId, selectedVersionId]);

  // Load projects on mount
  React.useEffect(() => {
    const loadProjects = async () => {
      if (!currentTenantId) {
        setProjects([]);
        return;
      }
      setIsLoadingProjects(true);
      try {
        const result = await getProjectsForTenant(currentTenantId);
        const data = JSON.parse(result);
        setProjects(data);
      } catch (error) {
        console.error('Failed to load projects:', error);
        setProjects([]);
      } finally {
        setIsLoadingProjects(false);
      }
    };
    loadProjects();
  }, [currentTenantId]);

  // Load versions when project changes and auto-select most recent
  React.useEffect(() => {
    const loadVersions = async () => {
      if (!localProjectId) {
        setVersions([]);
        return;
      }
      setIsLoadingVersions(true);
      try {
        const result = await getVersionsForProject(localProjectId);
        const data = JSON.parse(result);
        setVersions(data);

        // Auto-select the most recent version (first in the list)
        if (data.length > 0) {
          const mostRecentVersion = data[0];
          setLocalVersionId(mostRecentVersion.id);
          setContextVersionId(mostRecentVersion.id);
          setIsReadOnly(mostRecentVersion.published ?? false);
        }
      } catch (error) {
        console.error('Failed to load versions:', error);
        setVersions([]);
      } finally {
        setIsLoadingVersions(false);
      }
    };
    loadVersions();
  }, [localProjectId, setContextVersionId, setIsReadOnly]);

  // Load project tags when project changes
  const loadProjectTags = React.useCallback(async (projectId: string) => {
    if (!projectId) return;
    try {
      const result = await getTagsForProject(projectId);
      const tags = JSON.parse(result);
      onProjectTagsLoaded?.(tags);
    } catch (error) {
      console.error('Failed to load project tags:', error);
    }
  }, [onProjectTagsLoaded]);

  // Handle project selection
  const handleProjectChange = (value: string) => {
    setLocalProjectId(value);
    setContextProjectId(value);
    setLocalVersionId('');
    setContextVersionId('');
    setIsReadOnly(false);
    if (value) {
      loadProjectTags(value);
    }
  };

  // Handle version selection
  const handleVersionChange = (value: string) => {
    setLocalVersionId(value);
    setContextVersionId(value);
    const version = versions.find(v => v.id === value);
    setIsReadOnly(version?.published ?? false);
  };

  // Handle view mode change
  const handleViewModeChange = (value: string) => {
    if (!value) return;
    if (value === 'editor') {
      router.push('/ade/studio/editor');
    } else if (value === 'paths') {
      router.push('/ade/studio/paths');
    } else if (value === 'code') {
      router.push('/ade/studio/code');
    }
  };

  if (!currentTenantId) {
    return null;
  }

  return (
    <div className="bg-gradient-to-r from-white via-slate-50 to-white dark:from-gray-800 dark:via-gray-800 dark:to-gray-800 border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-1.5 shadow-sm" style={{ position: 'fixed', top: 48, left: 0, right: 0, zIndex: 1000 }}>
      <div className="flex flex-wrap items-center gap-4 w-full">
        {/* Project Selector */}
        <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
          <Select.Root
            value={localProjectId}
            onValueChange={handleProjectChange}
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

        {/* Version Selector */}
        <div className="flex items-center gap-2" style={{ position: 'relative', zIndex: 1001 }}>
          <Select.Root
            value={localVersionId}
            onValueChange={handleVersionChange}
            disabled={isLoadingVersions || !localProjectId || versions.length === 0}
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

        {/* View Switcher and Settings - only show when project and version selected */}
        {localProjectId && localVersionId && (
          <>
            {/* Separator */}
            <div className="h-6 w-px bg-gray-200 dark:bg-gray-600" />

            <ToggleGroup.Root
              type="single"
              value={viewMode}
              onValueChange={handleViewModeChange}
              className="inline-flex bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1 shadow-inner"
            >
              <ToggleGroup.Item
                value="editor"
                className="px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                </svg>
                Canvas
              </ToggleGroup.Item>
              {/*<ToggleGroup.Item*/}
              {/*  value="paths"*/}
              {/*  className="px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-amber-600 dark:data-[state=on]:text-amber-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"*/}
              {/*>*/}
              {/*  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">*/}
              {/*    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />*/}
              {/*  </svg>*/}
              {/*  Paths*/}
              {/*</ToggleGroup.Item>*/}
              <ToggleGroup.Item
                value="code"
                className="px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 flex items-center gap-1.5 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                Code
              </ToggleGroup.Item>
            </ToggleGroup.Root>

            {/* Settings Dropdown */}
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

                    {/* Level of Detail Toggle */}
                    <DropdownMenu.Item
                      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                      onSelect={() => toggleLod()}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM13 10H7" />
                      </svg>
                      <span className="flex-1">Level of Detail</span>
                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                        {lodEnabled ? 'ON' : 'OFF'}
                      </span>
                    </DropdownMenu.Item>

                    <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                    {/* Snap to Grid Toggle */}
                    <DropdownMenu.Item
                      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                      onSelect={() => setSnapToGrid(!snapToGrid)}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                      </svg>
                      <span className="flex-1">Snap to Grid</span>
                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                        {snapToGrid ? 'ON' : 'OFF'}
                      </span>
                    </DropdownMenu.Item>

                    {/* Smart Guides Toggle */}
                    <DropdownMenu.Item
                      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                      onSelect={() => setSmartGuidesEnabled(!smartGuidesEnabled)}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                      </svg>
                      <span className="flex-1">Smart Guides</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${smartGuidesEnabled ? 'bg-pink-100 dark:bg-pink-900/30 text-pink-600 dark:text-pink-400' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'}`}>
                        {smartGuidesEnabled ? 'ON' : 'OFF'}
                      </span>
                    </DropdownMenu.Item>

                    <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                    {/* Grid Size Slider */}
                    <div className="px-3 py-3">
                      <div className="flex items-center gap-2 mb-2">
                        <svg className="w-4 h-4 text-gray-700 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                        </svg>
                        <span className="text-sm text-gray-700 dark:text-gray-300">Grid Size</span>
                        <span className="ml-auto text-xs px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 font-medium">
                          {gridSize}px
                        </span>
                      </div>
                      <input
                        type="range"
                        min="10"
                        max="50"
                        step="5"
                        value={gridSize}
                        onChange={(e) => setGridSize(Number(e.target.value))}
                        className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                        onPointerDown={(e) => e.stopPropagation()}
                        onPointerMove={(e) => e.stopPropagation()}
                      />
                      <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                        <span>10px</span>
                        <span>50px</span>
                      </div>
                    </div>

                    <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                    {/* Grid Style Selector */}
                    <div className="px-3 py-3">
                      <div className="flex items-center gap-2 mb-2">
                        <svg className="w-4 h-4 text-gray-700 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                        </svg>
                        <span className="text-sm text-gray-700 dark:text-gray-300">Grid Style</span>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <button
                          onClick={() => setGridStyle('dots')}
                          onPointerDown={(e) => e.stopPropagation()}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all ${
                            gridStyle === 'dots'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                        >
                          Dots
                        </button>
                        <button
                          onClick={() => setGridStyle('lines')}
                          onPointerDown={(e) => e.stopPropagation()}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all ${
                            gridStyle === 'lines'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                        >
                          Lines
                        </button>
                        <button
                          onClick={() => setGridStyle('cross')}
                          onPointerDown={(e) => e.stopPropagation()}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all ${
                            gridStyle === 'cross'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                        >
                          Cross
                        </button>
                      </div>
                    </div>

                    <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                    {/* Edge Styling */}
                    <div className="px-3 py-3">
                      <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4 text-gray-700 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                        </svg>
                        <span className="text-sm text-gray-700 dark:text-gray-300">Edge Styles</span>
                      </div>
                      <div className="space-y-2">
                        {/* Direct References */}
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-600 dark:text-gray-400 w-20">Direct</span>
                          <select
                            value={edgeStyling.directReferences}
                            onChange={(e) => setEdgeStyling({ ...edgeStyling, directReferences: e.target.value as any })}
                            className="px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                          >
                            <option value="solid">Solid</option>
                            <option value="dashed">Dashed</option>
                            <option value="dotted">Dotted</option>
                            <option value="double">Double</option>
                          </select>
                          <Popover.Root>
                            <Popover.Trigger asChild>
                              <button
                                className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 relative flex items-center justify-center"
                                style={{ backgroundColor: edgeStyling.directColor }}
                                title="Change direct edge color"
                              >
                                <Palette
                                  className="w-4 h-4"
                                  style={{ color: isColorDark(edgeStyling.directColor) ? 'white' : 'black' }}
                                />
                              </button>
                            </Popover.Trigger>
                            <Popover.Portal>
                              <Popover.Content
                                className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-2 z-[10000]"
                                sideOffset={5}
                              >
                                <div className="grid grid-cols-4 gap-1.5">
                                  {EDGE_COLORS_4X4.map((color) => (
                                    <button
                                      key={color.hex}
                                      onClick={() => setEdgeStyling({ ...edgeStyling, directColor: color.hex })}
                                      className="w-7 h-7 rounded-full hover:scale-110 transition-transform border-2 border-gray-200 dark:border-gray-700"
                                      style={{ backgroundColor: color.hex }}
                                      title={color.name}
                                    />
                                  ))}
                                </div>
                              </Popover.Content>
                            </Popover.Portal>
                          </Popover.Root>
                        </div>

                        {/* Optional References */}
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-600 dark:text-gray-400 w-20">Optional</span>
                          <select
                            value={edgeStyling.optionalReferences}
                            onChange={(e) => setEdgeStyling({ ...edgeStyling, optionalReferences: e.target.value as any })}
                            className="px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                          >
                            <option value="solid">Solid</option>
                            <option value="dashed">Dashed</option>
                            <option value="dotted">Dotted</option>
                            <option value="double">Double</option>
                          </select>
                          <Popover.Root>
                            <Popover.Trigger asChild>
                              <button
                                className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 relative flex items-center justify-center"
                                style={{ backgroundColor: edgeStyling.optionalColor }}
                                title="Change optional edge color"
                              >
                                <Palette
                                  className="w-4 h-4"
                                  style={{ color: isColorDark(edgeStyling.optionalColor) ? 'white' : 'black' }}
                                />
                              </button>
                            </Popover.Trigger>
                            <Popover.Portal>
                              <Popover.Content
                                className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-2 z-[10000]"
                                sideOffset={5}
                              >
                                <div className="grid grid-cols-4 gap-1.5">
                                  {EDGE_COLORS_4X4.map((color) => (
                                    <button
                                      key={color.hex}
                                      onClick={() => setEdgeStyling({ ...edgeStyling, optionalColor: color.hex })}
                                      className="w-7 h-7 rounded-full hover:scale-110 transition-transform border-2 border-gray-200 dark:border-gray-700"
                                      style={{ backgroundColor: color.hex }}
                                      title={color.name}
                                    />
                                  ))}
                                </div>
                              </Popover.Content>
                            </Popover.Portal>
                          </Popover.Root>
                        </div>

                        {/* Weak References */}
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-600 dark:text-gray-400 w-20">Weak</span>
                          <select
                            value={edgeStyling.weakReferences}
                            onChange={(e) => setEdgeStyling({ ...edgeStyling, weakReferences: e.target.value as any })}
                            className="px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                          >
                            <option value="solid">Solid</option>
                            <option value="dashed">Dashed</option>
                            <option value="dotted">Dotted</option>
                            <option value="double">Double</option>
                          </select>
                          <Popover.Root>
                            <Popover.Trigger asChild>
                              <button
                                className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 relative flex items-center justify-center"
                                style={{ backgroundColor: edgeStyling.weakColor }}
                                title="Change weak edge color"
                              >
                                <Palette
                                  className="w-4 h-4"
                                  style={{ color: isColorDark(edgeStyling.weakColor) ? 'white' : 'black' }}
                                />
                              </button>
                            </Popover.Trigger>
                            <Popover.Portal>
                              <Popover.Content
                                className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-2 z-[10000]"
                                sideOffset={5}
                              >
                                <div className="grid grid-cols-4 gap-1.5">
                                  {EDGE_COLORS_4X4.map((color) => (
                                    <button
                                      key={color.hex}
                                      onClick={() => setEdgeStyling({ ...edgeStyling, weakColor: color.hex })}
                                      className="w-7 h-7 rounded-full hover:scale-110 transition-transform border-2 border-gray-200 dark:border-gray-700"
                                      style={{ backgroundColor: color.hex }}
                                      title={color.name}
                                    />
                                  ))}
                                </div>
                              </Popover.Content>
                            </Popover.Portal>
                          </Popover.Root>
                        </div>

                        {/* Bidirectional */}
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-600 dark:text-gray-400 w-20">Bidir.</span>
                          <select
                            value={edgeStyling.bidirectional}
                            onChange={(e) => setEdgeStyling({ ...edgeStyling, bidirectional: e.target.value as any })}
                            className="px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                          >
                            <option value="solid">Solid</option>
                            <option value="dashed">Dashed</option>
                            <option value="dotted">Dotted</option>
                            <option value="double">Double</option>
                          </select>
                          <Popover.Root>
                            <Popover.Trigger asChild>
                              <button
                                className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 relative flex items-center justify-center"
                                style={{ backgroundColor: edgeStyling.bidirectionalColor }}
                                title="Change bidirectional edge color"
                              >
                                <Palette
                                  className="w-4 h-4"
                                  style={{ color: isColorDark(edgeStyling.bidirectionalColor) ? 'white' : 'black' }}
                                />
                              </button>
                            </Popover.Trigger>
                            <Popover.Portal>
                              <Popover.Content
                                className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 p-2 z-[10000]"
                                sideOffset={5}
                              >
                                <div className="grid grid-cols-4 gap-1.5">
                                  {EDGE_COLORS_4X4.map((color) => (
                                    <button
                                      key={color.hex}
                                      onClick={() => setEdgeStyling({ ...edgeStyling, bidirectionalColor: color.hex })}
                                      className="w-7 h-7 rounded-full hover:scale-110 transition-transform border-2 border-gray-200 dark:border-gray-700"
                                      style={{ backgroundColor: color.hex }}
                                      title={color.name}
                                    />
                                  ))}
                                </div>
                              </Popover.Content>
                            </Popover.Portal>
                          </Popover.Root>
                        </div>
                      </div>
                    </div>

                    <DropdownMenu.Separator className="h-px bg-gray-200 dark:bg-gray-700 my-1" />

                    {/* Edge Routing */}
                    <div className="px-3 py-3">
                      <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4 text-gray-700 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                        </svg>
                        <span className="text-sm text-gray-700 dark:text-gray-300">Edge Routing</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          onClick={() => setEdgeRouting('straight')}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
                            edgeRouting === 'straight'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                          title="Direct straight lines between nodes"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <line x1="4" y1="4" x2="20" y2="20" />
                          </svg>
                          Straight
                        </button>
                        <button
                          onClick={() => setEdgeRouting('bezier')}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
                            edgeRouting === 'bezier'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                          title="Smooth curved bezier lines"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path d="M4 4 C 10 4, 14 20, 20 20" />
                          </svg>
                          Curved
                        </button>
                        <button
                          onClick={() => setEdgeRouting('orthogonal')}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
                            edgeRouting === 'orthogonal'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                          title="Right-angle orthogonal routing"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path d="M4 4 L 4 12 L 20 12 L 20 20" />
                          </svg>
                          Orthogonal
                        </button>
                        <button
                          onClick={() => setEdgeRouting('smart')}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
                            edgeRouting === 'smart'
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                          }`}
                          title="Smart routing that avoids node overlap"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path d="M4 4 L 4 8 L 12 8 L 12 16 L 20 16 L 20 20" />
                            <rect x="8" y="10" width="4" height="4" fill="currentColor" opacity="0.3" />
                          </svg>
                          Smart
                        </button>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                        {edgeRouting === 'straight' && 'Direct lines between connected nodes'}
                        {edgeRouting === 'bezier' && 'Smooth curved connections'}
                        {edgeRouting === 'orthogonal' && 'Right-angle paths (horizontal/vertical only)'}
                        {edgeRouting === 'smart' && 'Automatically routes around other nodes'}
                      </p>
                    </div>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            </div>
          </>
        )}
      </div>
    </div>
  );
}


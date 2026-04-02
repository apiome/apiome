'use client';

import { Check, Settings, Copy, Download, Loader2 } from 'lucide-react';
import * as Select from '@radix-ui/react-select';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import type { Project, Version, ViewMode } from './types';

interface EditorToolbarProps {
  // Data
  projects: Project[];
  versions: Version[];
  selectedProjectId: string;
  selectedVersionId: string;
  viewMode: ViewMode;
  isReadOnly: boolean;
  isDark: boolean;
  isLoadingProjects: boolean;
  isLoadingVersions: boolean;
  currentTenantId: string | null;
  clickToFocusEnabled: boolean;
  lodEnabled: boolean;
  layoutSaved: boolean;

  // Setters
  setSelectedProjectId: (id: string) => void;
  setContextProjectId: (id: string) => void;
  setSelectedVersionId: (id: string) => void;
  setContextVersionId: (id: string) => void;
  setIsReadOnly: (readOnly: boolean) => void;
  setViewMode: (mode: ViewMode) => void;
  setTagManagerOpen: (open: boolean) => void;
  setProjectTags: (tags: any[]) => void;

  // Handlers
  loadProjectTags: (projectId: string) => Promise<void>;
  toggleTheme: () => void;
  toggleClickToFocus: () => void;
  toggleLod: () => void;
  handleSaveLayout: () => Promise<void>;
  handleLoadLayout: () => Promise<void>;

  // Export handlers
  handleExportPng: () => Promise<void>;
  handleExportSvg: () => Promise<void>;
  handleExportJpeg: () => Promise<void>;
  handleExportPdf: () => Promise<void>;
  handleExportMermaid: () => Promise<void>;
  handleExportPlantUml: () => Promise<void>;
  handleExportDot: () => Promise<void>;
  handleExportGraphMl: () => Promise<void>;
  handleExportJson: () => Promise<void>;

  // Dropdown state
  exportDropdownOpen: boolean;
  setExportDropdownOpen: (open: boolean) => void;
  layoutDropdownOpen: boolean;
  setLayoutDropdownOpen: (open: boolean) => void;
  exportDropdownRef: React.RefObject<HTMLDivElement>;
  layoutDropdownRef: React.RefObject<HTMLDivElement>;
}

export function EditorToolbar({
  projects,
  versions,
  selectedProjectId,
  selectedVersionId,
  viewMode,
  isReadOnly,
  isDark,
  isLoadingProjects,
  isLoadingVersions,
  currentTenantId,
  clickToFocusEnabled,
  lodEnabled,
  layoutSaved,
  setSelectedProjectId,
  setContextProjectId,
  setSelectedVersionId,
  setContextVersionId,
  setIsReadOnly,
  setViewMode,
  setTagManagerOpen,
  setProjectTags,
  loadProjectTags,
  toggleTheme,
  toggleClickToFocus,
  toggleLod,
  handleSaveLayout,
  handleLoadLayout,
  handleExportPng,
  handleExportSvg,
  handleExportJpeg,
  handleExportPdf,
  handleExportMermaid,
  handleExportPlantUml,
  handleExportDot,
  handleExportGraphMl,
  handleExportJson,
  exportDropdownOpen,
  setExportDropdownOpen,
  layoutDropdownOpen,
  setLayoutDropdownOpen,
  exportDropdownRef,
  layoutDropdownRef,
}: EditorToolbarProps) {
  return (
    <div className="bg-gradient-to-r from-white via-slate-50 to-white dark:from-gray-800 dark:via-gray-800 dark:to-gray-800 border-b border-gray-200/80 dark:border-gray-700/80 px-2 py-1.5 shadow-sm" style={{ position: 'fixed', top: 48, left: 0, right: 0, zIndex: 1000 }}>
      <div className="flex flex-wrap items-center gap-4 w-full">
        {/* Project Selector */}
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
            <Select.Trigger
              aria-busy={isLoadingProjects}
              className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoadingProjects ? (
                <Loader2 className="w-4 h-4 shrink-0 animate-spin text-indigo-500 dark:text-indigo-400" aria-hidden />
              ) : (
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2zM4 13a1 1 0 001-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                </svg>
              )}
              <Select.Value placeholder={isLoadingProjects ? 'Loading projects…' : 'Select project...'} />
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
            <Select.Trigger
              aria-busy={isLoadingVersions}
              className="inline-flex items-center gap-2 bg-white dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 shadow-sm px-3 py-2 text-sm text-gray-900 dark:text-white hover:border-indigo-300 dark:hover:border-indigo-500/50 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/20 min-w-[220px] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoadingVersions ? (
                <Loader2 className="w-4 h-4 shrink-0 animate-spin text-indigo-500 dark:text-indigo-400" aria-hidden />
              ) : (
                <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
              )}
              <Select.Value placeholder={isLoadingVersions ? 'Loading versions…' : 'Select version...'} />
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

        {/* View Switcher and Actions */}
        {selectedProjectId && selectedVersionId && (
          <>
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

            {/* Settings Dropdown */}
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
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                      ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                        </svg>
                      )}
                      <span>{isDark ? 'Light Mode' : 'Dark Mode'}</span>
                    </DropdownMenu.Item>

                    {/* Click to Focus Toggle */}
                    <DropdownMenu.Item
                      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                      onSelect={() => toggleClickToFocus()}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      <span>Click to Focus: {clickToFocusEnabled ? 'On' : 'Off'}</span>
                    </DropdownMenu.Item>

                    {/* LOD Toggle */}
                    <DropdownMenu.Item
                      className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 data-[highlighted]:bg-gray-100 dark:data-[highlighted]:bg-gray-700"
                      onSelect={() => toggleLod()}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                      </svg>
                      <span>Detail Scaling: {lodEnabled ? 'On' : 'Off'}</span>
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            </div>

            {/* Layout Actions */}
            {viewMode === 'canvas' && (
              <div className="relative" ref={layoutDropdownRef}>
                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <button
                      onClick={() => setLayoutDropdownOpen(!layoutDropdownOpen)}
                      className={`px-3 py-2 text-sm font-medium rounded-lg border transition-all duration-200 flex items-center gap-2 shadow-sm hover:shadow-md ${
                        layoutSaved
                          ? 'border-green-300 dark:border-green-600 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300'
                          : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50'
                      }`}
                      title="Layout options"
                    >
                      {layoutSaved ? (
                        <>
                          <Check className="w-4 h-4" />
                          <span>Saved</span>
                        </>
                      ) : (
                        <>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                          </svg>
                          <span>Layout</span>
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </>
                      )}
                    </button>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content
                      className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                      sideOffset={5}
                    >
                      Save or load canvas layout
                      <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>

                {layoutDropdownOpen && (
                  <div className="absolute right-0 mt-2 w-64 rounded-lg border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-800 z-[1002]">
                    <div
                      aria-hidden="true"
                      className="absolute -top-2 right-5 h-3.5 w-3.5 rotate-45 border-l border-t border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
                    />
                    <div className="p-2">
                      <button
                        onClick={handleSaveLayout}
                        disabled={isReadOnly}
                        className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                        </svg>
                        <div className="text-left">
                          <div className="font-medium">Save Layout</div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">Save current positions</div>
                        </div>
                      </button>
                      <button
                        onClick={handleLoadLayout}
                        className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      >
                        <svg className="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                        </svg>
                        <div className="text-left">
                          <div className="font-medium">Load Layout</div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">Restore saved positions</div>
                        </div>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Export Dropdown */}
            {viewMode === 'canvas' && (
              <div className="relative" ref={exportDropdownRef}>
                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <button
                      onClick={() => setExportDropdownOpen(!exportDropdownOpen)}
                      className="px-3 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700/50 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all duration-200 flex items-center gap-2 shadow-sm hover:shadow-md"
                      title="Export canvas"
                    >
                      <Download className="w-4 h-4" />
                      <span>Export</span>
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content
                      className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                      sideOffset={5}
                    >
                      Export canvas as image or diagram
                      <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>

                {exportDropdownOpen && (
                  <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[1002]">
                    <div className="p-1">
                      <div className="px-3 py-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                        Images
                      </div>
                      <button onClick={handleExportPng} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 rounded px-1">PNG</span>
                        <span>PNG Image</span>
                      </button>
                      <button onClick={handleExportSvg} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-purple-100 dark:bg-purple-900/50 text-purple-600 dark:text-purple-400 rounded px-1">SVG</span>
                        <span>SVG Vector</span>
                      </button>
                      <button onClick={handleExportJpeg} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-orange-100 dark:bg-orange-900/50 text-orange-600 dark:text-orange-400 rounded px-1">JPG</span>
                        <span>JPEG Image</span>
                      </button>
                      <button onClick={handleExportPdf} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400 rounded px-1">PDF</span>
                        <span>PDF Document</span>
                      </button>

                      <div className="my-1 border-t border-gray-200 dark:border-gray-700" />

                      <div className="px-3 py-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                        Diagrams
                      </div>
                      <button onClick={handleExportMermaid} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-teal-100 dark:bg-teal-900/50 text-teal-600 dark:text-teal-400 rounded px-1">MMD</span>
                        <span>Mermaid Diagram</span>
                      </button>
                      <button onClick={handleExportPlantUml} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400 rounded px-1">UML</span>
                        <span>PlantUML</span>
                      </button>
                      <button onClick={handleExportDot} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-yellow-100 dark:bg-yellow-900/50 text-yellow-600 dark:text-yellow-400 rounded px-1">DOT</span>
                        <span>GraphViz DOT</span>
                      </button>
                      <button onClick={handleExportGraphMl} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400 rounded px-1">XML</span>
                        <span>GraphML</span>
                      </button>

                      <div className="my-1 border-t border-gray-200 dark:border-gray-700" />

                      <div className="px-3 py-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                        Data
                      </div>
                      <button onClick={handleExportJson} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                        <span className="w-6 text-center text-xs font-mono bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded px-1">{ }</span>
                        <span>Canvas JSON</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}


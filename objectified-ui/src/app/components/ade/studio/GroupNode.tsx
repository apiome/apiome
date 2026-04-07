'use client';

import React, { memo, useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { NodeProps, NodeResizer } from '@xyflow/react';
import {
  Folder, Edit2, Trash2, X, Check, Palette, Settings,
  Box, Layers, Database, Shield, Users, Zap, Globe, Lock,
  FileText, Tag, Star, Heart, Flag, Bookmark, Archive, Package,
  FileX, ChevronRight, ChevronDown, Download, FileJson, FileCode2, Copy, SlidersHorizontal,
  ListTree,
} from 'lucide-react';
import * as Popover from '@radix-ui/react-popover';
import { COLLAPSED_GROUP_FRAME_WIDTH, COLLAPSED_GROUP_FRAME_HEIGHT } from '@/app/utils/canvas-group-collapse';
import { parseCssHexColor, resolveGroupFrameHex } from '@/app/utils/group-frame-colors';
import { tagChipClass, tagDotClass } from '@/app/utils/tag-color-tokens';
import GroupBulkEditDialog, { type GroupBulkEditTagOption } from './GroupBulkEditDialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/app/components/ui/Select';

// Available group icons
export const GROUP_ICONS = [
  { name: 'folder', icon: Folder, label: 'Folder' },
  { name: 'box', icon: Box, label: 'Box' },
  { name: 'layers', icon: Layers, label: 'Layers' },
  { name: 'database', icon: Database, label: 'Database' },
  { name: 'shield', icon: Shield, label: 'Shield' },
  { name: 'users', icon: Users, label: 'Users' },
  { name: 'zap', icon: Zap, label: 'Zap' },
  { name: 'globe', icon: Globe, label: 'Globe' },
  { name: 'lock', icon: Lock, label: 'Lock' },
  { name: 'file', icon: FileText, label: 'File' },
  { name: 'tag', icon: Tag, label: 'Tag' },
  { name: 'star', icon: Star, label: 'Star' },
  { name: 'heart', icon: Heart, label: 'Heart' },
  { name: 'flag', icon: Flag, label: 'Flag' },
  { name: 'bookmark', icon: Bookmark, label: 'Bookmark' },
  { name: 'archive', icon: Archive, label: 'Archive' },
  { name: 'package', icon: Package, label: 'Package' },
];

// Border style options
export const BORDER_STYLES = [
  { name: 'dashed', label: 'Dashed', class: 'border-dashed' },
  { name: 'solid', label: 'Solid', class: 'border-solid' },
  { name: 'dotted', label: 'Dotted', class: 'border-dotted' },
];

// Background opacity options
export const OPACITY_OPTIONS = [
  { value: 0.1, label: '10%' },
  { value: 0.2, label: '20%' },
  { value: 0.3, label: '30%' },
  { value: 0.5, label: '50%' },
  { value: 0.7, label: '70%' },
  { value: 1, label: '100%' },
];

// Shadow options
export const SHADOW_OPTIONS = [
  { name: 'none', label: 'None', class: '' },
  { name: 'sm', label: 'Small', class: 'shadow-sm' },
  { name: 'md', label: 'Medium', class: 'shadow-md' },
  { name: 'lg', label: 'Large', class: 'shadow-lg' },
];

// Predefined group colors with name, bg, border, and text colors
export const GROUP_COLORS = [
  { name: 'indigo', bg: 'bg-indigo-50 dark:bg-indigo-950/30', border: 'border-indigo-300 dark:border-indigo-700', text: 'text-indigo-700 dark:text-indigo-300', hex: '#6366f1' },
  { name: 'purple', bg: 'bg-purple-50 dark:bg-purple-950/30', border: 'border-purple-300 dark:border-purple-700', text: 'text-purple-700 dark:text-purple-300', hex: '#a855f7' },
  { name: 'pink', bg: 'bg-pink-50 dark:bg-pink-950/30', border: 'border-pink-300 dark:border-pink-700', text: 'text-pink-700 dark:text-pink-300', hex: '#ec4899' },
  { name: 'rose', bg: 'bg-rose-50 dark:bg-rose-950/30', border: 'border-rose-300 dark:border-rose-700', text: 'text-rose-700 dark:text-rose-300', hex: '#f43f5e' },
  { name: 'red', bg: 'bg-red-50 dark:bg-red-950/30', border: 'border-red-300 dark:border-red-700', text: 'text-red-700 dark:text-red-300', hex: '#ef4444' },
  { name: 'orange', bg: 'bg-orange-50 dark:bg-orange-950/30', border: 'border-orange-300 dark:border-orange-700', text: 'text-orange-700 dark:text-orange-300', hex: '#f97316' },
  { name: 'amber', bg: 'bg-amber-50 dark:bg-amber-950/30', border: 'border-amber-300 dark:border-amber-700', text: 'text-amber-700 dark:text-amber-300', hex: '#f59e0b' },
  { name: 'yellow', bg: 'bg-yellow-50 dark:bg-yellow-950/30', border: 'border-yellow-300 dark:border-yellow-700', text: 'text-yellow-700 dark:text-yellow-300', hex: '#eab308' },
  { name: 'lime', bg: 'bg-lime-50 dark:bg-lime-950/30', border: 'border-lime-300 dark:border-lime-700', text: 'text-lime-700 dark:text-lime-300', hex: '#84cc16' },
  { name: 'green', bg: 'bg-green-50 dark:bg-green-950/30', border: 'border-green-300 dark:border-green-700', text: 'text-green-700 dark:text-green-300', hex: '#22c55e' },
  { name: 'emerald', bg: 'bg-emerald-50 dark:bg-emerald-950/30', border: 'border-emerald-300 dark:border-emerald-700', text: 'text-emerald-700 dark:text-emerald-300', hex: '#10b981' },
  { name: 'teal', bg: 'bg-teal-50 dark:bg-teal-950/30', border: 'border-teal-300 dark:border-teal-700', text: 'text-teal-700 dark:text-teal-300', hex: '#14b8a6' },
  { name: 'cyan', bg: 'bg-cyan-50 dark:bg-cyan-950/30', border: 'border-cyan-300 dark:border-cyan-700', text: 'text-cyan-700 dark:text-cyan-300', hex: '#06b6d4' },
  { name: 'sky', bg: 'bg-sky-50 dark:bg-sky-950/30', border: 'border-sky-300 dark:border-sky-700', text: 'text-sky-700 dark:text-sky-300', hex: '#0ea5e9' },
  { name: 'blue', bg: 'bg-blue-50 dark:bg-blue-950/30', border: 'border-blue-300 dark:border-blue-700', text: 'text-blue-700 dark:text-blue-300', hex: '#3b82f6' },
  { name: 'gray', bg: 'bg-gray-50 dark:bg-gray-800/50', border: 'border-gray-300 dark:border-gray-600', text: 'text-gray-700 dark:text-gray-300', hex: '#6b7280' },
];

export interface GroupStyleOptions {
  borderStyle: 'dashed' | 'solid' | 'dotted';
  opacity: number;
  shadow: 'none' | 'sm' | 'md' | 'lg';
  icon: string;
}

export const DEFAULT_STYLE_OPTIONS: GroupStyleOptions = {
  borderStyle: 'dashed',
  opacity: 1,
  shadow: 'none',
  icon: 'folder',
};

export interface GroupNodeData {
  id: string;
  name: string;
  description?: string;
  /** Preset name from GROUP_COLORS or custom `#RRGGBB` / `#RGB` (#97). */
  color: string;
  nodeIds: string[]; // IDs of nodes contained in this group
  styleOptions?: GroupStyleOptions; // Visual styling options
  isHighlighted?: boolean; // Visual highlight when node is dragged over
  onRename?: (groupId: string, newName: string) => void;
  onDelete?: (groupId: string) => void;
  onDeleteAllClassesInGroup?: (groupId: string, classIds?: string[], groupName?: string) => void;
  /** Export OpenAPI schema for group members + transitive refs (#156). */
  onExportGroupSchema?: (
    groupId: string,
    nodeIds: string[],
    groupName: string,
    format: 'json' | 'yaml'
  ) => void | Promise<void>;
  /** Duplicate all classes in the group into a new group (#156). */
  onDuplicateGroup?: (groupId: string, nodeIds: string[], groupName: string) => void | Promise<void>;
  /** Bulk metadata / tags / top-level readOnly (#156). */
  onBulkEditGroupClasses?: (
    groupId: string,
    nodeIds: string[],
    groupName: string,
    options: {
      descriptionPrefix?: string;
      descriptionSuffix?: string;
      tagId?: string;
      topLevelPropertyReadOnly?: boolean;
    }
  ) => void | Promise<void>;
  /** Project tags for bulk assign */
  availableTags?: GroupBulkEditTagOption[];
  /** Tags assigned to this group frame (project tags); persisted on group metadata (#95). */
  tags?: Array<{ id: string; name: string; color: string }>;
  onTagsChange?: (groupId: string, tags: Array<{ id: string; name: string; color: string }>) => void;
  onColorChange?: (groupId: string, newColor: string) => void;
  onStyleChange?: (groupId: string, styleOptions: GroupStyleOptions) => void;
  isReadOnly?: boolean;
  /** Canvas frame is collapsed to title + count only (#154). */
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  /** #155: Parent group id if nested */
  parentId?: string | null;
  /** #155: Drill into group (breadcrumb navigation) */
  onDrillInto?: (groupId: string) => void;
}

const GroupNode = memo((props: NodeProps) => {
  const { data, selected } = props;
  const groupData = data as unknown as GroupNodeData;
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(groupData.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const colorPopoverContentRef = useRef<HTMLDivElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportPopoverOpen, setExportPopoverOpen] = useState(false);
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [isFrameHovered, setIsFrameHovered] = useState(false);
  const [customHexDraft, setCustomHexDraft] = useState('');

  const showFloatingToolbar = useMemo(
    () =>
      !groupData.isReadOnly &&
      !isEditing &&
      (selected ||
        isFrameHovered ||
        settingsOpen ||
        colorPickerOpen ||
        exportPopoverOpen),
    [
      groupData.isReadOnly,
      isEditing,
      selected,
      isFrameHovered,
      settingsOpen,
      colorPickerOpen,
      exportPopoverOpen,
    ]
  );

  const { hex: frameHex, preset: matchedPreset } = useMemo(
    () => resolveGroupFrameHex(groupData.color, GROUP_COLORS),
    [groupData.color]
  );

  const presetBorderClass = matchedPreset ? matchedPreset.border : '';
  const useCustomFrameBorder = !matchedPreset && parseCssHexColor(groupData.color) !== null;

  useEffect(() => {
    if (!colorPickerOpen) return;
    const { hex: h, preset: p } = resolveGroupFrameHex(groupData.color, GROUP_COLORS);
    setCustomHexDraft(p ? '' : h);
  }, [colorPickerOpen, groupData.color]);

  // Get style options with defaults
  const styleOptions = useMemo(
    () => ({ ...DEFAULT_STYLE_OPTIONS, ...groupData.styleOptions }),
    [groupData.styleOptions]
  );

  // Determine if we should use light text based on background darkness
  const useLightText = true;
  const textColorClass = useLightText ? 'text-white' : (matchedPreset?.text ?? GROUP_COLORS[0].text);

  // Get the icon component
  const IconComponent = GROUP_ICONS.find(i => i.name === styleOptions.icon)?.icon || Folder;

  // Get border style class
  const borderStyleClass = BORDER_STYLES.find(b => b.name === styleOptions.borderStyle)?.class || 'border-dashed';

  // Get shadow class
  const shadowClass = SHADOW_OPTIONS.find(s => s.name === styleOptions.shadow)?.class || '';

  const nodeCount = groupData.nodeIds?.length || 0;

  const assignedTags = useMemo(() => groupData.tags ?? [], [groupData.tags]);
  const addableTags = useMemo(
    () =>
      (groupData.availableTags ?? []).filter(
        (t) => !assignedTags.some((a) => a.id === t.id)
      ),
    [groupData.availableTags, assignedTags]
  );

  const handleStartEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (groupData.isReadOnly) return;
    setEditName(groupData.name);
    setIsEditing(true);
  }, [groupData.name, groupData.isReadOnly]);

  const handleSaveEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (editName.trim() && editName !== groupData.name) {
      groupData.onRename?.(groupData.id, editName.trim());
    }
    setIsEditing(false);
  }, [editName, groupData]);

  const handleCancelEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setEditName(groupData.name);
    setIsEditing(false);
  }, [groupData.name]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === 'Enter') {
      if (editName.trim() && editName !== groupData.name) {
        groupData.onRename?.(groupData.id, editName.trim());
      }
      setIsEditing(false);
    } else if (e.key === 'Escape') {
      setEditName(groupData.name);
      setIsEditing(false);
    }
  }, [editName, groupData]);

  const handleDelete = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (groupData.isReadOnly) return;
    groupData.onDelete?.(groupData.id);
  }, [groupData]);

  const handleDeleteAllClassesInGroup = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (groupData.isReadOnly) return;
    groupData.onDeleteAllClassesInGroup?.(groupData.id, groupData.nodeIds, groupData.name);
  }, [groupData]);

  const runExportSchema = useCallback(
    async (format: 'json' | 'yaml', e: React.MouseEvent) => {
      e.stopPropagation();
      if (groupData.isReadOnly || nodeCount === 0) return;
      setExportPopoverOpen(false);
      await groupData.onExportGroupSchema?.(groupData.id, groupData.nodeIds, groupData.name, format);
    },
    [groupData, nodeCount]
  );

  const handleDuplicateGroupClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (groupData.isReadOnly || nodeCount === 0) return;
      void groupData.onDuplicateGroup?.(groupData.id, groupData.nodeIds, groupData.name);
    },
    [groupData, nodeCount]
  );

  const handleOpenBulk = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (groupData.isReadOnly || nodeCount === 0) return;
    setBulkDialogOpen(true);
  }, [groupData, nodeCount]);

  const handleBulkSubmit = useCallback(
    async (options: {
      descriptionPrefix?: string;
      descriptionSuffix?: string;
      tagId?: string;
      topLevelPropertyReadOnly?: boolean;
    }) => {
      await groupData.onBulkEditGroupClasses?.(groupData.id, groupData.nodeIds, groupData.name, options);
    },
    [groupData]
  );

  const handleColorChange = useCallback(
    (colorValue: string) => {
      if (groupData.isReadOnly) return;
      groupData.onColorChange?.(groupData.id, colorValue);
      setColorPickerOpen(false);
    },
    [groupData]
  );

  // Handle style option changes
  const handleStyleChange = useCallback(
    (key: keyof GroupStyleOptions, value: GroupStyleOptions[keyof GroupStyleOptions]) => {
      if (groupData.isReadOnly) return;
      const newOptions = { ...styleOptions, [key]: value };
      groupData.onStyleChange?.(groupData.id, newOptions);
    },
    [groupData, styleOptions]
  );

  const handleAddGroupTag = useCallback(
    (tagId: string) => {
      if (groupData.isReadOnly || !tagId) return;
      const opt = groupData.availableTags?.find((t) => t.id === tagId);
      if (!opt) return;
      const color = opt.color && opt.color.length > 0 ? opt.color : 'default';
      groupData.onTagsChange?.(groupData.id, [...assignedTags, { id: opt.id, name: opt.name, color }]);
    },
    [groupData, assignedTags]
  );

  const handleRemoveGroupTag = useCallback(
    (tagId: string) => {
      if (groupData.isReadOnly) return;
      groupData.onTagsChange?.(
        groupData.id,
        assignedTags.filter((t) => t.id !== tagId)
      );
    },
    [groupData, assignedTags]
  );

  const isCollapsed = Boolean(groupData.collapsed);

  return (
    <>
      {/* Node resizer for adjusting group size */}
      <NodeResizer
        minWidth={200}
        minHeight={150}
        isVisible={selected && !groupData.isReadOnly && !isCollapsed}
        lineClassName="!border-indigo-400"
        handleClassName="!w-3 !h-3 !bg-indigo-500 !border-2 !border-white !rounded"
      />

      <div
        data-testid="group-node-surface"
        className={`
          relative w-full h-full rounded-2xl border-2 transition-all duration-200
          ${borderStyleClass} ${presetBorderClass} ${shadowClass}
          ${selected ? 'ring-2 ring-indigo-500 ring-offset-2 dark:ring-offset-gray-900' : ''}
          ${groupData.isHighlighted ? 'ring-4 ring-green-500 ring-offset-4 dark:ring-offset-gray-900 scale-[1.02] border-green-500 dark:border-green-400' : ''}
        `}
        style={{
          minWidth: isCollapsed ? COLLAPSED_GROUP_FRAME_WIDTH : 200,
          minHeight: isCollapsed ? COLLAPSED_GROUP_FRAME_HEIGHT : 150,
          backgroundColor: `${frameHex}${Math.round(styleOptions.opacity * 25.5).toString(16).padStart(2, '0')}`,
          ...(useCustomFrameBorder ? { borderColor: `${frameHex}99` } : {})
        }}
        onMouseEnter={() => setIsFrameHovered(true)}
        onMouseLeave={() => setIsFrameHovered(false)}
      >
        {/* Group Header */}
        <div
          className={`
            absolute -top-3 left-4 px-3 py-1 rounded-lg border ${shadowClass || 'shadow-sm'}
            ${presetBorderClass} ${textColorClass}
            flex items-center gap-2 cursor-move
          `}
          style={{
            backgroundColor: `${frameHex}${Math.round(Math.min(styleOptions.opacity + 0.3, 1) * 255).toString(16).padStart(2, '0')}`,
            ...(useCustomFrameBorder ? { borderColor: `${frameHex}cc` } : {})
          }}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              groupData.onToggleCollapse?.();
            }}
            onPointerDown={(e) => e.stopPropagation()}
            className={`p-0.5 rounded shrink-0 -ml-0.5 transition-colors ${useLightText ? 'hover:bg-white/25' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
            title={isCollapsed ? 'Expand group (show classes)' : 'Collapse group (hide classes)'}
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? 'Expand group' : 'Collapse group'}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          {groupData.onDrillInto && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                groupData.onDrillInto?.(groupData.id);
              }}
              onPointerDown={(e) => e.stopPropagation()}
              className={`p-0.5 rounded shrink-0 transition-colors ${useLightText ? 'hover:bg-white/25' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
              title="Nested view — focus breadcrumb on this group"
              aria-label="Drill into nested group"
            >
              <ListTree className="h-4 w-4" />
            </button>
          )}
          <IconComponent className="h-4 w-4" />

          {isEditing ? (
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={handleKeyDown}
                className={`
                  px-2 py-0.5 text-sm font-medium rounded border-0 outline-none
                  bg-white/90 dark:bg-gray-800/90 text-gray-900 dark:text-white
                  w-32
                `}
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
              <button
                onClick={handleSaveEdit}
                className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
              >
                <Check className={`h-3 w-3 ${useLightText ? 'text-green-300' : 'text-green-600 dark:text-green-400'}`} />
              </button>
              <button
                onClick={handleCancelEdit}
                className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
              >
                <X className={`h-3 w-3 ${useLightText ? 'text-red-300' : 'text-red-600 dark:text-red-400'}`} />
              </button>
            </div>
          ) : (
            <>
              <span className="text-sm font-semibold">{groupData.name}</span>
              <span className="text-xs opacity-70">({nodeCount})</span>
            </>
          )}
        </div>

        {!isCollapsed && assignedTags.length > 0 && (
          <div
            className="absolute top-7 left-4 right-4 z-10 flex flex-wrap gap-1 pointer-events-none"
            aria-label="Group tags"
          >
            {assignedTags.map((tag) => (
              <span
                key={tag.id}
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${tagChipClass(tag.color)}`}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}

        {/* Floating toolbar: outside the title pill, top -24px / right -2px (#859) */}
        {showFloatingToolbar && (
          <div
            role="toolbar"
            aria-label="Group edit actions"
            className={`
              absolute -top-6 right-[-2px] z-20 flex max-w-[min(100%,calc(100vw-2rem))] flex-wrap items-center gap-1 rounded-lg border px-1.5 py-1
              ${shadowClass || 'shadow-md'}
              ${presetBorderClass} ${textColorClass}
            `}
            style={{
              backgroundColor: `${frameHex}${Math.round(Math.min(styleOptions.opacity + 0.3, 1) * 255).toString(16).padStart(2, '0')}`,
              ...(useCustomFrameBorder ? { borderColor: `${frameHex}cc` } : {})
            }}
            onMouseDown={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
              {/* Settings popover */}
              <Popover.Root open={settingsOpen} onOpenChange={setSettingsOpen}>
                <Popover.Trigger asChild>
                  <button
                    type="button"
                    aria-label="Style settings"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setSettingsOpen(v => !v);
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                    className={`p-1 rounded transition-colors cursor-pointer ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                    title="Style settings"
                  >
                    <Settings className="h-3.5 w-3.5" />
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content
                    className="z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-4 w-96"
                    sideOffset={5}
                    onOpenAutoFocus={(e) => e.preventDefault()}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Group Styling</h4>

                    {(assignedTags.length > 0 ||
                      (!groupData.isReadOnly && (groupData.availableTags?.length ?? 0) > 0)) && (
                      <div className="mb-4">
                        <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2 block">
                          Tags
                        </label>
                        {assignedTags.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mb-2">
                            {assignedTags.map((tag) => (
                              <span
                                key={tag.id}
                                className={`inline-flex items-center gap-1 text-xs pl-2 pr-1 py-0.5 rounded-md border ${tagChipClass(tag.color)}`}
                              >
                                {tag.name}
                                {!groupData.isReadOnly && (
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveGroupTag(tag.id)}
                                    className="rounded p-0.5 hover:bg-black/10 dark:hover:bg-white/10"
                                    aria-label={`Remove tag ${tag.name}`}
                                  >
                                    <X className="h-3 w-3" />
                                  </button>
                                )}
                              </span>
                            ))}
                          </div>
                        )}
                        {!groupData.isReadOnly && addableTags.length > 0 && (
                          <Select
                            key={assignedTags.map((t) => t.id).join(',')}
                            value=""
                            onValueChange={(id) => {
                              if (id) handleAddGroupTag(id);
                            }}
                          >
                            <SelectTrigger className="h-8 text-xs border-dashed w-full">
                              <Tag className="h-3 w-3 mr-1 shrink-0" />
                              Add tag
                            </SelectTrigger>
                            <SelectContent>
                              {addableTags.map((t) => (
                                <SelectItem key={t.id} value={t.id}>
                                  <span className="flex items-center gap-2">
                                    <span className={`text-lg leading-none ${tagDotClass(t.color || 'default')}`}>
                                      ●
                                    </span>
                                    {t.name}
                                  </span>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                      </div>
                    )}

                    {/* Icon Selection */}
                    <div className="mb-4">
                      <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2 block">Icon</label>
                      <div className="grid grid-cols-6 gap-1.5">
                        {GROUP_ICONS.map((iconOption) => {
                          const Icon = iconOption.icon;
                          return (
                            <button
                              key={iconOption.name}
                              onClick={() => handleStyleChange('icon', iconOption.name)}
                              className={`
                                p-2 rounded-lg transition-all hover:bg-gray-100 dark:hover:bg-gray-700
                                flex items-center justify-center
                                ${styleOptions.icon === iconOption.name 
                                  ? 'bg-indigo-100 dark:bg-indigo-900/50 ring-2 ring-indigo-500' 
                                  : 'bg-gray-50 dark:bg-gray-700/50'}
                              `}
                              title={iconOption.label}
                            >
                              <Icon className="h-4 w-4 text-gray-700 dark:text-gray-300" />
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Border Style */}
                    <div className="mb-4">
                      <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2 block">Border Style</label>
                      <div className="flex gap-2">
                        {BORDER_STYLES.map((style) => (
                          <button
                            key={style.name}
                            onClick={() => handleStyleChange('borderStyle', style.name)}
                            className={`
                              flex-1 px-3 py-2 text-xs font-medium rounded-lg transition-all
                              ${styleOptions.borderStyle === style.name
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-2 ring-indigo-500'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'}
                            `}
                          >
                            {style.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Shadow */}
                    <div className="mb-4">
                      <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2 block">Shadow</label>
                      <div className="flex gap-2">
                        {SHADOW_OPTIONS.map((shadow) => (
                          <button
                            key={shadow.name}
                            onClick={() => handleStyleChange('shadow', shadow.name)}
                            className={`
                              flex-1 px-2 py-2 text-xs font-medium rounded-lg transition-all
                              ${styleOptions.shadow === shadow.name
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-2 ring-indigo-500'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'}
                            `}
                          >
                            {shadow.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Opacity Slider */}
                    <div>
                      <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2 block">Background Opacity</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min="0"
                          max="100"
                          value={Math.round(styleOptions.opacity * 100)}
                          onChange={(e) => handleStyleChange('opacity', parseInt(e.target.value) / 100)}
                          className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                          style={{
                            background: `linear-gradient(to right, rgb(99 102 241) 0%, rgb(99 102 241) ${styleOptions.opacity * 100}%, rgb(229 231 235) ${styleOptions.opacity * 100}%, rgb(229 231 235) 100%)`
                          }}
                        />
                        <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-12 text-right">
                          {Math.round(styleOptions.opacity * 100)}%
                        </span>
                      </div>
                    </div>

                    <Popover.Arrow className="fill-white dark:fill-gray-800" />
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>

              {/* Color picker */}
              <Popover.Root open={colorPickerOpen} onOpenChange={setColorPickerOpen}>
                <Popover.Trigger asChild>
                  <button
                    type="button"
                    aria-label="Change color"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setColorPickerOpen(v => !v);
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                    className={`p-1 rounded transition-colors cursor-pointer ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                    title="Change color"
                  >
                    <Palette className="h-3.5 w-3.5" />
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content
                    ref={colorPopoverContentRef}
                    className="z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-3"
                    sideOffset={5}
                    onOpenAutoFocus={(e) => e.preventDefault()}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="grid grid-cols-4 gap-2">
                      {GROUP_COLORS.map((color) => (
                        <button
                          key={color.name}
                          type="button"
                          disabled={groupData.isReadOnly}
                          onClick={() => handleColorChange(color.name)}
                          className={`
                            w-6 h-6 rounded-full border-2 transition-transform hover:scale-110
                            ${color.name === groupData.color ? 'ring-2 ring-offset-2 ring-indigo-500 dark:ring-offset-gray-800' : ''}
                          `}
                          style={{ backgroundColor: color.hex }}
                          title={color.name}
                        />
                      ))}
                    </div>
                    <div className="border-t border-gray-200 dark:border-gray-600 pt-3 mt-3 space-y-2">
                      <div className="text-xs font-medium text-gray-600 dark:text-gray-400">Custom color</div>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={frameHex}
                          onChange={(e) => {
                            const v = parseCssHexColor(e.target.value);
                            if (v) handleColorChange(v);
                          }}
                          className="h-8 w-10 shrink-0 cursor-pointer rounded border border-gray-300 dark:border-gray-600 bg-transparent p-0"
                          title="Pick a custom container color"
                          aria-label="Custom color picker"
                          disabled={groupData.isReadOnly}
                        />
                        <input
                          type="text"
                          value={customHexDraft}
                          onChange={(e) => setCustomHexDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              const v = parseCssHexColor(customHexDraft);
                              if (v) handleColorChange(v);
                            }
                          }}
                          onBlur={(e) => {
                            if (
                              e.relatedTarget instanceof Element &&
                              colorPopoverContentRef.current?.contains(e.relatedTarget)
                            ) {
                              return;
                            }
                            const v = parseCssHexColor(customHexDraft);
                            if (v) handleColorChange(v);
                          }}
                          placeholder="#6366f1"
                          disabled={groupData.isReadOnly}
                          className="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2 py-1 font-mono text-xs text-gray-900 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                          aria-label="Custom color hex value"
                        />
                      </div>
                      {useCustomFrameBorder ? (
                        <p className="text-[10px] text-gray-500 dark:text-gray-400">Custom container color (saved with the layout)</p>
                      ) : null}
                    </div>
                    <Popover.Arrow className="fill-white dark:fill-gray-800" />
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>

              {/* Rename button */}
              <button
                onClick={handleStartEdit}
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
                aria-label="Rename group"
                className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                title="Rename group"
              >
                <Edit2 className="h-3.5 w-3.5" />
              </button>

              {/* Export OpenAPI (JSON/YAML) — group + transitive schema deps (#156) */}
              {nodeCount > 0 && (
                <Popover.Root open={exportPopoverOpen} onOpenChange={setExportPopoverOpen}>
                  <Popover.Trigger asChild>
                    <button
                      type="button"
                      aria-label="Export group as OpenAPI schema file"
                      onClick={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        setExportPopoverOpen((v) => !v);
                      }}
                      onMouseDown={(e) => e.stopPropagation()}
                      className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                      title="Export group as OpenAPI schema file"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                  </Popover.Trigger>
                  <Popover.Portal>
                    <Popover.Content
                      className="z-[9999] bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 p-2 min-w-[160px]"
                      sideOffset={5}
                      onOpenAutoFocus={(e) => e.preventDefault()}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-900 dark:text-gray-100"
                        onClick={(e) => void runExportSchema('json', e)}
                      >
                        <FileJson className="h-4 w-4 shrink-0" />
                        OpenAPI JSON
                      </button>
                      <button
                        type="button"
                        className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-900 dark:text-gray-100"
                        onClick={(e) => void runExportSchema('yaml', e)}
                      >
                        <FileCode2 className="h-4 w-4 shrink-0" />
                        OpenAPI YAML
                      </button>
                      <Popover.Arrow className="fill-white dark:fill-gray-800" />
                    </Popover.Content>
                  </Popover.Portal>
                </Popover.Root>
              )}

              {/* Duplicate entire group (#156) */}
              {nodeCount > 0 && (
                <button
                  onClick={handleDuplicateGroupClick}
                  onMouseDown={(e) => e.stopPropagation()}
                  onPointerDown={(e) => e.stopPropagation()}
                  aria-label="Duplicate group (all classes)"
                  className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                  title="Duplicate group (all classes)"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              )}

              {/* Bulk edit classes (#156) */}
              {nodeCount > 0 && (
                <button
                  onClick={handleOpenBulk}
                  onMouseDown={(e) => e.stopPropagation()}
                  onPointerDown={(e) => e.stopPropagation()}
                  aria-label="Bulk edit all classes in group"
                  className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-white/30' : 'hover:bg-white/50 dark:hover:bg-gray-700/50'}`}
                  title="Bulk edit all classes in group"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                </button>
              )}

              {/* Delete all classes in group (only when group has classes) */}
              {nodeCount > 0 && (
                <button
                  onClick={handleDeleteAllClassesInGroup}
                  onMouseDown={(e) => e.stopPropagation()}
                  onPointerDown={(e) => e.stopPropagation()}
                  aria-label="Delete all classes in group"
                  className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-amber-400/40 text-amber-200' : 'hover:bg-amber-100 dark:hover:bg-amber-900/30 text-amber-600 dark:text-amber-400'}`}
                  title="Delete all classes in group"
                >
                  <FileX className="h-3.5 w-3.5" />
                </button>
              )}
              {/* Delete group button */}
              <button
                onClick={handleDelete}
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
                aria-label="Delete group"
                className={`p-1 rounded transition-colors ${useLightText ? 'hover:bg-red-400/40 text-red-200' : 'hover:bg-red-100 dark:hover:bg-red-900/30 text-red-600 dark:text-red-400'}`}
                title="Delete group"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
          </div>
        )}

        {/* Description (if any) */}
        {groupData.description && !isCollapsed && (
          <div className={`absolute bottom-2 left-4 right-4 text-xs ${textColorClass} opacity-70 truncate`}>
            {groupData.description}
          </div>
        )}
      </div>

      <GroupBulkEditDialog
        open={bulkDialogOpen}
        onOpenChange={setBulkDialogOpen}
        groupName={groupData.name}
        classCount={nodeCount}
        availableTags={groupData.availableTags || []}
        onSubmit={handleBulkSubmit}
      />
    </>
  );
});

GroupNode.displayName = 'GroupNode';

export default GroupNode;


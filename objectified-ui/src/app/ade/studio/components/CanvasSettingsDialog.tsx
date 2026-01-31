'use client';

import * as React from 'react';
import { Palette, Settings } from 'lucide-react';
import * as Popover from '@radix-ui/react-popover';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { EDGE_COLORS_4X4 } from '../../../utils/color-themes';
import type {
  EdgeStylingOptions,
  EdgeRoutingType,
  EdgeAnimationType,
  EdgeArrowStyle,
} from '../StudioContext';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  BackgroundVariant,
  Handle,
  Position,
  type Node,
  type Edge,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// Helper function to determine if a color is dark
function isColorDark(hexColor: string | undefined): boolean {
  if (!hexColor) hexColor = '#64748b';
  const hex = hexColor.replace('#', '');
  const r = parseInt(hex.substr(0, 2), 16);
  const g = parseInt(hex.substr(2, 2), 16);
  const b = parseInt(hex.substr(4, 2), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance < 0.5;
}

// Preview node component for the settings dialog
function PreviewClassNode({ data }: { data: { label: string; properties: string[]; isAllOf?: boolean } }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border-2 border-gray-200 dark:border-gray-600 min-w-[140px]">
      {/* Connection handles */}
      <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-indigo-500" />
      <Handle type="target" position={Position.Left} className="w-2 h-2 !bg-indigo-500" />
      <Handle type="source" position={Position.Right} className="w-2 h-2 !bg-indigo-500" />
      <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-indigo-500" />

      <div className={`px-3 py-2 border-b border-gray-200 dark:border-gray-600 ${data.isAllOf ? 'bg-purple-50 dark:bg-purple-900/30' : 'bg-indigo-50 dark:bg-indigo-900/30'}`}>
        <div className="text-sm font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
          {data.isAllOf && <span className="text-[10px] px-1.5 py-0.5 bg-purple-200 dark:bg-purple-800 text-purple-700 dark:text-purple-300 rounded">allOf</span>}
          {data.label}
        </div>
      </div>
      <div className="px-3 py-2">
        {data.properties.map((prop, idx) => (
          <div key={idx} className="text-xs text-gray-600 dark:text-gray-400 py-0.5">
            • {prop}
          </div>
        ))}
      </div>
    </div>
  );
}

const nodeTypes = {
  previewClass: PreviewClassNode,
};

// Separate component for the preview canvas to ensure proper remounting
interface PreviewCanvasProps {
  gridStyle: 'dots' | 'lines' | 'cross';
  gridSize: number;
  nodes: Node[];
  edges: Edge[];
}

function PreviewCanvas({ gridStyle, gridSize, nodes, edges }: PreviewCanvasProps) {
  const [renderKey, setRenderKey] = React.useState(0);

  // Force re-render when grid style changes
  React.useEffect(() => {
    setRenderKey(prev => prev + 1);
  }, [gridStyle, gridSize]);

  const backgroundVariant = React.useMemo(() => {
    switch (gridStyle) {
      case 'dots': return BackgroundVariant.Dots;
      case 'lines': return BackgroundVariant.Lines;
      case 'cross': return BackgroundVariant.Cross;
      default: return BackgroundVariant.Dots;
    }
  }, [gridStyle]);

  // Detect dark mode
  const [isDark, setIsDark] = React.useState(false);
  React.useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };
    checkDarkMode();

    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    return () => observer.disconnect();
  }, []);

  return (
    <ReactFlowProvider key={`flow-provider-${renderKey}`}>
      <div style={{ width: '100%', height: '100%' }}>
        <ReactFlow
          key={`flow-${renderKey}`}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          panOnScroll={false}
          panOnDrag={false}
          preventScrolling={false}
          minZoom={0.5}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            key={`bg-${renderKey}`}
            variant={backgroundVariant}
            gap={gridSize}
            size={1.5}
            color="currentColor"
            style={{
              color: isDark ? 'rgb(148, 163, 184)' : 'rgb(99, 102, 241)',
              opacity: isDark ? 0.3 : 0.2
            }}
          />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </ReactFlowProvider>
  );
}

interface CanvasSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Current settings
  clickToFocusEnabled: boolean;
  snapToGrid: boolean;
  smartGuidesEnabled: boolean;
  gridSize: number;
  gridStyle: 'dots' | 'lines' | 'cross';
  edgeStyling: EdgeStylingOptions;
  edgeRouting: EdgeRoutingType;
  edgeAnimation: EdgeAnimationType;
  // Callbacks to apply settings
  onSave: (settings: {
    clickToFocusEnabled: boolean;
    snapToGrid: boolean;
    smartGuidesEnabled: boolean;
    gridSize: number;
    gridStyle: 'dots' | 'lines' | 'cross';
    edgeStyling: EdgeStylingOptions;
    edgeRouting: EdgeRoutingType;
    edgeAnimation: EdgeAnimationType;
  }) => void;
}

export default function CanvasSettingsDialog({
  open,
  onOpenChange,
  clickToFocusEnabled,
  snapToGrid,
  smartGuidesEnabled,
  gridSize,
  gridStyle,
  edgeStyling,
  edgeRouting,
  edgeAnimation,
  onSave,
}: CanvasSettingsDialogProps) {
  // Local state for form
  const [localClickToFocus, setLocalClickToFocus] = React.useState(clickToFocusEnabled);
  const [localSnapToGrid, setLocalSnapToGrid] = React.useState(snapToGrid);
  const [localSmartGuides, setLocalSmartGuides] = React.useState(smartGuidesEnabled);
  const [localGridSize, setLocalGridSize] = React.useState(gridSize);
  const [localGridStyle, setLocalGridStyle] = React.useState(gridStyle);
  const [localEdgeStyling, setLocalEdgeStyling] = React.useState(edgeStyling);
  const [localEdgeRouting, setLocalEdgeRouting] = React.useState(edgeRouting);
  const [localEdgeAnimation, setLocalEdgeAnimation] = React.useState(edgeAnimation);

  // Reset local state when dialog opens
  React.useEffect(() => {
    if (open) {
      setLocalClickToFocus(clickToFocusEnabled);
      setLocalSnapToGrid(snapToGrid);
      setLocalSmartGuides(smartGuidesEnabled);
      setLocalGridSize(gridSize);
      setLocalGridStyle(gridStyle);
      setLocalEdgeStyling(edgeStyling);
      setLocalEdgeRouting(edgeRouting);
      setLocalEdgeAnimation(edgeAnimation);
    }
  }, [open, clickToFocusEnabled, snapToGrid, smartGuidesEnabled, gridSize, gridStyle, edgeStyling, edgeRouting, edgeAnimation]);

  const handleSave = () => {
    onSave({
      clickToFocusEnabled: localClickToFocus,
      snapToGrid: localSnapToGrid,
      smartGuidesEnabled: localSmartGuides,
      gridSize: localGridSize,
      gridStyle: localGridStyle,
      edgeStyling: localEdgeStyling,
      edgeRouting: localEdgeRouting,
      edgeAnimation: localEdgeAnimation,
    });
    onOpenChange(false);
  };

  const handleCancel = () => {
    onOpenChange(false);
  };

  // Define preview nodes: User, Group, Permission, AdminUser
  const previewNodes: Node[] = React.useMemo(() => [
    {
      id: 'user',
      type: 'previewClass',
      position: { x: 50, y: 50 },
      data: {
        label: 'User',
        properties: ['id: string', 'name: string', 'email: string', 'permissions: Permission[]']
      },
    },
    {
      id: 'group',
      type: 'previewClass',
      position: { x: 280, y: 30 },
      data: {
        label: 'Group',
        properties: ['id: string', 'name: string', 'users: User[]']
      },
    },
    {
      id: 'permission',
      type: 'previewClass',
      position: { x: 50, y: 230 },
      data: {
        label: 'Permission',
        properties: ['id: string', 'key: string', 'value: any']
      },
    },
    {
      id: 'adminuser',
      type: 'previewClass',
      position: { x: 280, y: 200 },
      data: {
        label: 'AdminUser',
        properties: ['role: string', 'level: number'],
        isAllOf: true,
      },
    },
  ], []);

  // Get edge type based on routing setting
  const getEdgeType = React.useCallback((routing: EdgeRoutingType) => {
    switch (routing) {
      case 'straight': return 'straight';
      case 'bezier': return 'default';
      case 'orthogonal': return 'smoothstep';
      case 'smart': return 'smoothstep';
      default: return 'default';
    }
  }, []);

  // Get stroke dasharray based on style
  const getStrokeDasharray = React.useCallback((style: string) => {
    switch (style) {
      case 'dashed': return '6,3';
      case 'dotted': return '2,2';
      default: return undefined;
    }
  }, []);

  // Define preview edges with current styling
  const previewEdges: Edge[] = React.useMemo(() => {
    const edgeType = getEdgeType(localEdgeRouting);

    return [
      // User has Permissions (Direct reference)
      {
        id: 'user-permission',
        source: 'user',
        target: 'permission',
        type: edgeType,
        style: {
          stroke: localEdgeStyling.directColor,
          strokeWidth: 2,
          strokeDasharray: getStrokeDasharray(localEdgeStyling.directReferences),
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: localEdgeStyling.directColor },
        label: 'permissions',
        labelStyle: { fontSize: 10, fill: localEdgeStyling.directColor },
        animated: localEdgeAnimation === 'flow' || localEdgeAnimation === 'dash',
      },
      // Group has Users (Direct reference)
      {
        id: 'group-user',
        source: 'group',
        target: 'user',
        type: edgeType,
        style: {
          stroke: localEdgeStyling.directColor,
          strokeWidth: 2,
          strokeDasharray: getStrokeDasharray(localEdgeStyling.directReferences),
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: localEdgeStyling.directColor },
        label: 'users',
        labelStyle: { fontSize: 10, fill: localEdgeStyling.directColor },
        animated: localEdgeAnimation === 'flow' || localEdgeAnimation === 'dash',
      },
      // AdminUser allOf User (Weak/inheritance reference)
      {
        id: 'adminuser-user',
        source: 'adminuser',
        target: 'user',
        type: edgeType,
        style: {
          stroke: localEdgeStyling.weakColor,
          strokeWidth: 2,
          strokeDasharray: getStrokeDasharray(localEdgeStyling.weakReferences),
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: localEdgeStyling.weakColor },
        label: 'allOf',
        labelStyle: { fontSize: 10, fill: localEdgeStyling.weakColor },
        animated: localEdgeAnimation === 'flow' || localEdgeAnimation === 'dash',
      },
    ];
  }, [localEdgeStyling, localEdgeRouting, localEdgeAnimation, getEdgeType, getStrokeDasharray]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[95vw] h-[85vh] max-h-[800px] p-0 flex flex-col" showCloseButton={false}>
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-gray-200 dark:border-gray-700">
          <DialogTitle className="flex items-center gap-2">
            <Settings className="w-5 h-5 text-indigo-500" />
            Canvas Settings
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 flex overflow-hidden">
          {/* Settings Form - Left Side */}
          <div className="w-1/2 border-r border-gray-200 dark:border-gray-700 overflow-y-auto p-6">
            <div className="space-y-6">
              {/* Behavior Section */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Behavior
                </h3>
                <div className="space-y-3">
                  {/* Click-to-Focus */}
                  <label className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <svg className="w-4 h-4 text-gray-600 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      <span className="text-sm text-gray-700 dark:text-gray-300">Click-to-Focus</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={localClickToFocus}
                      onChange={(e) => setLocalClickToFocus(e.target.checked)}
                      className="w-4 h-4 text-indigo-500 rounded focus:ring-indigo-500"
                    />
                  </label>
                </div>
              </div>

              {/* Grid Section */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                  </svg>
                  Grid
                </h3>
                <div className="space-y-3">
                  {/* Snap to Grid */}
                  <label className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <svg className="w-4 h-4 text-gray-600 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                      </svg>
                      <span className="text-sm text-gray-700 dark:text-gray-300">Snap to Grid</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={localSnapToGrid}
                      onChange={(e) => setLocalSnapToGrid(e.target.checked)}
                      className="w-4 h-4 text-indigo-500 rounded focus:ring-indigo-500"
                    />
                  </label>

                  {/* Smart Guides */}
                  <label className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <svg className="w-4 h-4 text-gray-600 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                      </svg>
                      <span className="text-sm text-gray-700 dark:text-gray-300">Smart Guides</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={localSmartGuides}
                      onChange={(e) => setLocalSmartGuides(e.target.checked)}
                      className="w-4 h-4 text-indigo-500 rounded focus:ring-indigo-500"
                    />
                  </label>

                  {/* Grid Size */}
                  <div className="p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-gray-700 dark:text-gray-300">Grid Size</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 font-medium">
                        {localGridSize}px
                      </span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="50"
                      step="5"
                      value={localGridSize}
                      onChange={(e) => setLocalGridSize(Number(e.target.value))}
                      className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                    />
                    <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                      <span>10px</span>
                      <span>50px</span>
                    </div>
                  </div>

                  {/* Grid Style */}
                  <div className="p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <span className="text-sm text-gray-700 dark:text-gray-300 block mb-2">Grid Style</span>
                    <div className="grid grid-cols-3 gap-2">
                      {(['dots', 'lines', 'cross'] as const).map((style) => (
                        <button
                          key={style}
                          onClick={() => setLocalGridStyle(style)}
                          className={`px-3 py-2 rounded-md text-xs font-medium transition-all ${
                            localGridStyle === style
                              ? 'bg-indigo-500 text-white shadow-sm'
                              : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 border border-gray-200 dark:border-gray-600'
                          }`}
                        >
                          {style.charAt(0).toUpperCase() + style.slice(1)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Edge Styles Section */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                  Edge Styles
                </h3>
                <div className="space-y-3">
                  {/* Direct References */}
                  <div className="flex items-center justify-between gap-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-20">Direct</span>
                    <select
                      value={localEdgeStyling.directReferences}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, directReferences: e.target.value as any })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                      title="Line style"
                    >
                      <option value="solid">Solid</option>
                      <option value="dashed">Dashed</option>
                      <option value="dotted">Dotted</option>
                      <option value="double">Double</option>
                    </select>
                    <select
                      value={localEdgeStyling.directArrowStyle || 'arrow'}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, directArrowStyle: e.target.value as EdgeArrowStyle })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 w-20"
                      title="Arrow style"
                    >
                      <option value="arrow">Arrow</option>
                      <option value="diamond">Diamond</option>
                      <option value="circle">Circle</option>
                      <option value="open">Open</option>
                    </select>
                    <Popover.Root>
                      <Popover.Trigger asChild>
                        <button
                          className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 flex items-center justify-center"
                          style={{ backgroundColor: localEdgeStyling.directColor }}
                        >
                          <Palette
                            className="w-4 h-4"
                            style={{ color: isColorDark(localEdgeStyling.directColor) ? 'white' : 'black' }}
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
                                onClick={() => setLocalEdgeStyling({ ...localEdgeStyling, directColor: color.hex })}
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
                  <div className="flex items-center justify-between gap-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-20">Optional</span>
                    <select
                      value={localEdgeStyling.optionalReferences}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, optionalReferences: e.target.value as any })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                      title="Line style"
                    >
                      <option value="solid">Solid</option>
                      <option value="dashed">Dashed</option>
                      <option value="dotted">Dotted</option>
                      <option value="double">Double</option>
                    </select>
                    <select
                      value={localEdgeStyling.optionalArrowStyle || 'arrow'}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, optionalArrowStyle: e.target.value as EdgeArrowStyle })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 w-20"
                      title="Arrow style"
                    >
                      <option value="arrow">Arrow</option>
                      <option value="diamond">Diamond</option>
                      <option value="circle">Circle</option>
                      <option value="open">Open</option>
                    </select>
                    <Popover.Root>
                      <Popover.Trigger asChild>
                        <button
                          className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 flex items-center justify-center"
                          style={{ backgroundColor: localEdgeStyling.optionalColor }}
                        >
                          <Palette
                            className="w-4 h-4"
                            style={{ color: isColorDark(localEdgeStyling.optionalColor) ? 'white' : 'black' }}
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
                                onClick={() => setLocalEdgeStyling({ ...localEdgeStyling, optionalColor: color.hex })}
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
                  <div className="flex items-center justify-between gap-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-20">Weak</span>
                    <select
                      value={localEdgeStyling.weakReferences}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, weakReferences: e.target.value as any })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                      title="Line style"
                    >
                      <option value="solid">Solid</option>
                      <option value="dashed">Dashed</option>
                      <option value="dotted">Dotted</option>
                      <option value="double">Double</option>
                    </select>
                    <select
                      value={localEdgeStyling.weakArrowStyle || 'arrow'}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, weakArrowStyle: e.target.value as EdgeArrowStyle })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 w-20"
                      title="Arrow style"
                    >
                      <option value="arrow">Arrow</option>
                      <option value="diamond">Diamond</option>
                      <option value="circle">Circle</option>
                      <option value="open">Open</option>
                    </select>
                    <Popover.Root>
                      <Popover.Trigger asChild>
                        <button
                          className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 flex items-center justify-center"
                          style={{ backgroundColor: localEdgeStyling.weakColor }}
                        >
                          <Palette
                            className="w-4 h-4"
                            style={{ color: isColorDark(localEdgeStyling.weakColor) ? 'white' : 'black' }}
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
                                onClick={() => setLocalEdgeStyling({ ...localEdgeStyling, weakColor: color.hex })}
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
                  <div className="flex items-center justify-between gap-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-20">Bidir.</span>
                    <select
                      value={localEdgeStyling.bidirectional}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, bidirectional: e.target.value as any })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 flex-1"
                      title="Line style"
                    >
                      <option value="solid">Solid</option>
                      <option value="dashed">Dashed</option>
                      <option value="dotted">Dotted</option>
                      <option value="double">Double</option>
                    </select>
                    <select
                      value={localEdgeStyling.bidirectionalArrowStyle || 'arrow'}
                      onChange={(e) => setLocalEdgeStyling({ ...localEdgeStyling, bidirectionalArrowStyle: e.target.value as EdgeArrowStyle })}
                      className="px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 w-20"
                      title="Arrow style"
                    >
                      <option value="arrow">Arrow</option>
                      <option value="diamond">Diamond</option>
                      <option value="circle">Circle</option>
                      <option value="open">Open</option>
                    </select>
                    <Popover.Root>
                      <Popover.Trigger asChild>
                        <button
                          className="w-8 h-8 rounded-full border-2 border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 transition-colors flex-shrink-0 flex items-center justify-center"
                          style={{ backgroundColor: localEdgeStyling.bidirectionalColor }}
                        >
                          <Palette
                            className="w-4 h-4"
                            style={{ color: isColorDark(localEdgeStyling.bidirectionalColor) ? 'white' : 'black' }}
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
                                onClick={() => setLocalEdgeStyling({ ...localEdgeStyling, bidirectionalColor: color.hex })}
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

              {/* Edge Routing Section */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                  </svg>
                  Edge Routing
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: 'straight', label: 'Straight', icon: 'M4 4 L20 20', description: 'Direct lines between nodes' },
                    { value: 'bezier', label: 'Curved', icon: 'M4 4 C 10 4, 14 20, 20 20', description: 'Smooth curved connections' },
                    { value: 'orthogonal', label: 'Orthogonal', icon: 'M4 4 L 4 12 L 20 12 L 20 20', description: 'Right-angle paths' },
                    { value: 'smart', label: 'Smart', icon: 'M4 4 L 4 8 L 12 8 L 12 16 L 20 16 L 20 20', description: 'Auto-routes around nodes' },
                  ].map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setLocalEdgeRouting(option.value as EdgeRoutingType)}
                      className={`p-3 rounded-lg text-left transition-all ${
                        localEdgeRouting === option.value
                          ? 'bg-indigo-500 text-white shadow-sm'
                          : 'bg-gray-50 dark:bg-gray-800/50 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50 border border-gray-200 dark:border-gray-700'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                          <path d={option.icon} />
                        </svg>
                        <span className="text-sm font-medium">{option.label}</span>
                      </div>
                      <p className={`text-xs ${localEdgeRouting === option.value ? 'text-indigo-100' : 'text-gray-500 dark:text-gray-400'}`}>
                        {option.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Edge Animation Section */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Edge Animation
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: 'none', label: 'None', description: 'Static edges' },
                    { value: 'flow', label: 'Flow', description: 'Flowing dots' },
                    { value: 'pulse', label: 'Pulse', description: 'Pulsing glow' },
                    { value: 'dash', label: 'Dash', description: 'Marching dashes' },
                  ].map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setLocalEdgeAnimation(option.value as EdgeAnimationType)}
                      className={`p-3 rounded-lg text-left transition-all ${
                        localEdgeAnimation === option.value
                          ? 'bg-indigo-500 text-white shadow-sm'
                          : 'bg-gray-50 dark:bg-gray-800/50 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50 border border-gray-200 dark:border-gray-700'
                      }`}
                    >
                      <span className="text-sm font-medium">{option.label}</span>
                      <p className={`text-xs mt-0.5 ${localEdgeAnimation === option.value ? 'text-indigo-100' : 'text-gray-500 dark:text-gray-400'}`}>
                        {option.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Canvas Preview - Right Side with ReactFlow */}
          <div className="w-1/2 p-6 bg-gray-100 dark:bg-gray-900/50 flex flex-col">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              Preview
            </h3>
            <div className="flex-1 rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
              <PreviewCanvas
                key={`preview-${localGridStyle}-${localGridSize}-${localEdgeRouting}-${localEdgeAnimation}-${JSON.stringify(localEdgeStyling)}`}
                gridStyle={localGridStyle}
                gridSize={localGridSize}
                nodes={previewNodes}
                edges={previewEdges}
              />
            </div>

            {/* Legend */}
            <div className="mt-3 flex flex-wrap gap-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="w-4 h-0.5" style={{ backgroundColor: localEdgeStyling.directColor }} />
                <span className="text-gray-600 dark:text-gray-400">Direct (has/contains)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-4 h-0.5" style={{ backgroundColor: localEdgeStyling.weakColor }} />
                <span className="text-gray-600 dark:text-gray-400">Weak (allOf)</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer with Cancel and Save buttons - both on the right */}
        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
          <button
            onClick={handleCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors shadow-sm"
          >
            Save
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


// Shared types for the Studio Editor

export interface Project {
  id: string;
  name: string;
  slug: string;
}

export interface Version {
  id: string;
  version_id: string;
  /** DB / legacy field; REST often sends `shortMessage` instead. */
  description?: string | null;
  shortMessage?: string | null;
  published: boolean;
  /** ISO timestamp for timeline / sorting (#323) */
  created_at?: string;
}

export type ViewMode = 'canvas' | 'code';

export type CodeDisplayFormat = 'openapi' | 'arazzo' | 'jsonschema';

export interface GroupStyleOptions {
  borderStyle: 'solid' | 'dashed' | 'dotted';
  opacity: number;
  shadow: 'none' | 'sm' | 'md' | 'lg';
  icon: string;
}

export interface CanvasGroup {
  id: string;
  name: string;
  description?: string;
  color: string;
  position: { x: number; y: number };
  dimensions: { width: number; height: number };
  nodeIds: string[];
  parentId?: string | null;
  tags?: any[];
  styleOptions?: GroupStyleOptions;
}

export interface SpacingIndicator {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  distance: number;
  type: 'horizontal' | 'vertical';
}

export interface SmartGuides {
  horizontal: Array<{ y: number; x1: number; x2: number }>;
  vertical: Array<{ x: number; y1: number; y2: number }>;
}

export interface NodeData {
  id: string;
  name: string;
  description?: string;
  properties?: any[];
  schema?: any;
  tags?: any[];
  theme?: any;
  expandedPropertyIds?: Set<string>;
}

export interface EdgeData {
  label?: string;
  type?: string;
  cardinality?: string;
}


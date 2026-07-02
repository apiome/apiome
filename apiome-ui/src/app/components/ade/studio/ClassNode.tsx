import React, { memo, useState, useEffect, useRef } from 'react';
import { Handle, Position, type NodeProps, useUpdateNodeInternals } from '@xyflow/react';
import {
  Edit,
  Trash2,
  ChevronRight,
  ChevronDown,
  Palette,
  Smile,
  // Node icon options - organized by category
  User,
  Users,
  UserCircle,
  UserCheck,
  Building,
  Building2,
  Home,
  Store,
  Factory,
  Landmark,
  ShoppingCart,
  ShoppingBag,
  CreditCard,
  Wallet,
  DollarSign,
  Receipt,
  Package,
  Box,
  Boxes,
  Archive,
  FileText,
  File,
  Files,
  Folder,
  FolderOpen,
  Database,
  HardDrive,
  Server,
  Cloud,
  Globe,
  Map as MapIcon,
  MapPin,
  Navigation,
  Mail,
  MessageSquare,
  MessageCircle,
  Send,
  Bell,
  BellRing,
  Calendar,
  CalendarDays,
  Clock,
  Timer,
  AlarmClock,
  Settings,
  Cog,
  Wrench,
  Hammer,
  Key,
  Lock,
  Unlock,
  Shield,
  ShieldCheck,
  Eye,
  EyeOff,
  Search,
  Filter,
  Tag,
  Tags,
  Bookmark,
  Star,
  Heart,
  ThumbsUp,
  Award,
  Trophy,
  Medal,
  Zap,
  Bolt,
  Activity,
  TrendingUp,
  BarChart,
  PieChart,
  LineChart,
  Layers,
  Layout,
  Grid,
  List,
  Table,
  Columns,
  Link,
  Link2,
  Unlink,
  Share,
  Share2,
  Download,
  Upload,
  Image,
  Camera,
  Video,
  Music,
  Headphones,
  Mic,
  Phone,
  Smartphone,
  Tablet,
  Monitor,
  Laptop,
  Printer,
  Cpu,
  Wifi,
  Bluetooth,
  Battery,
  Power,
  Play,
  Pause,
  RefreshCw,
  RotateCcw,
  Repeat,
  Shuffle,
  Code,
  Terminal,
  Hash,
  AtSign,
  Percent,
  Plus,
  Minus,
  X,
  Check,
  CheckCircle,
  XCircle,
  AlertCircle,
  AlertTriangle,
  Info,
  HelpCircle,
  CircleDot,
  Circle,
  Square,
  Triangle,
  Hexagon,
  Octagon,
  Diamond,
  Gem,
  Crown,
  Flag,
  Bookmark as BookmarkIcon,
  Paperclip,
  Scissors,
  Clipboard,
  ClipboardList,
  ClipboardCheck,
  FileCheck,
  FilePlus,
  FileX,
  FileCode,
  FileJson,
  Briefcase,
  GraduationCap,
  BookOpen,
  Book,
  Library,
  Newspaper,
  Rss,
  Radio,
  Tv,
  Cast,
  Airplay,
  Speaker,
  Volume2,
  type LucideIcon,
} from 'lucide-react';
import { useDialog } from '../../providers/DialogProvider';
import * as Popover from '@radix-ui/react-popover';
import { cn } from '../../../../../lib/utils';
import { tagInlineColors } from '@/app/utils/tag-color-tokens';
import { NodeCard } from '../canvas/NodeCard';
import { NodeHeader } from '../canvas/NodeHeader';
import { NodeHandleDot } from '../canvas/NodeHandleDot';
import { NodeBadge } from '../canvas/NodeBadge';
import { NodeTypeChip } from '../canvas/NodeTypeChip';
import { PropertyRow } from '../canvas/PropertyRow';
import { accentVar } from '../canvas/canvas-theme';

// Icon options for class nodes - curated list organized by category
const NODE_ICON_OPTIONS: Array<{ name: string; icon: LucideIcon; category: string }> = [
  // People & Organizations
  { name: 'User', icon: User, category: 'People' },
  { name: 'Users', icon: Users, category: 'People' },
  { name: 'UserCircle', icon: UserCircle, category: 'People' },
  { name: 'UserCheck', icon: UserCheck, category: 'People' },
  { name: 'Building', icon: Building, category: 'People' },
  { name: 'Building2', icon: Building2, category: 'People' },
  { name: 'Home', icon: Home, category: 'People' },
  { name: 'Store', icon: Store, category: 'People' },
  { name: 'Factory', icon: Factory, category: 'People' },
  { name: 'Landmark', icon: Landmark, category: 'People' },
  // Commerce & Finance
  { name: 'ShoppingCart', icon: ShoppingCart, category: 'Commerce' },
  { name: 'ShoppingBag', icon: ShoppingBag, category: 'Commerce' },
  { name: 'CreditCard', icon: CreditCard, category: 'Commerce' },
  { name: 'Wallet', icon: Wallet, category: 'Commerce' },
  { name: 'DollarSign', icon: DollarSign, category: 'Commerce' },
  { name: 'Receipt', icon: Receipt, category: 'Commerce' },
  // Storage & Data
  { name: 'Package', icon: Package, category: 'Storage' },
  { name: 'Box', icon: Box, category: 'Storage' },
  { name: 'Boxes', icon: Boxes, category: 'Storage' },
  { name: 'Archive', icon: Archive, category: 'Storage' },
  { name: 'Database', icon: Database, category: 'Storage' },
  { name: 'HardDrive', icon: HardDrive, category: 'Storage' },
  { name: 'Server', icon: Server, category: 'Storage' },
  { name: 'Cloud', icon: Cloud, category: 'Storage' },
  // Files & Documents
  { name: 'FileText', icon: FileText, category: 'Files' },
  { name: 'File', icon: File, category: 'Files' },
  { name: 'Files', icon: Files, category: 'Files' },
  { name: 'Folder', icon: Folder, category: 'Files' },
  { name: 'FolderOpen', icon: FolderOpen, category: 'Files' },
  { name: 'FileCode', icon: FileCode, category: 'Files' },
  { name: 'FileJson', icon: FileJson, category: 'Files' },
  { name: 'ClipboardList', icon: ClipboardList, category: 'Files' },
  // Communication
  { name: 'Mail', icon: Mail, category: 'Communication' },
  { name: 'MessageSquare', icon: MessageSquare, category: 'Communication' },
  { name: 'MessageCircle', icon: MessageCircle, category: 'Communication' },
  { name: 'Send', icon: Send, category: 'Communication' },
  { name: 'Bell', icon: Bell, category: 'Communication' },
  { name: 'BellRing', icon: BellRing, category: 'Communication' },
  { name: 'Phone', icon: Phone, category: 'Communication' },
  // Time & Scheduling
  { name: 'Calendar', icon: Calendar, category: 'Time' },
  { name: 'CalendarDays', icon: CalendarDays, category: 'Time' },
  { name: 'Clock', icon: Clock, category: 'Time' },
  { name: 'Timer', icon: Timer, category: 'Time' },
  { name: 'AlarmClock', icon: AlarmClock, category: 'Time' },
  // Security & Access
  { name: 'Key', icon: Key, category: 'Security' },
  { name: 'Lock', icon: Lock, category: 'Security' },
  { name: 'Unlock', icon: Unlock, category: 'Security' },
  { name: 'Shield', icon: Shield, category: 'Security' },
  { name: 'ShieldCheck', icon: ShieldCheck, category: 'Security' },
  { name: 'Eye', icon: Eye, category: 'Security' },
  // Settings & Tools
  { name: 'Settings', icon: Settings, category: 'Tools' },
  { name: 'Cog', icon: Cog, category: 'Tools' },
  { name: 'Wrench', icon: Wrench, category: 'Tools' },
  { name: 'Hammer', icon: Hammer, category: 'Tools' },
  // Location
  { name: 'Globe', icon: Globe, category: 'Location' },
  { name: 'Map', icon: MapIcon, category: 'Location' },
  { name: 'MapPin', icon: MapPin, category: 'Location' },
  { name: 'Navigation', icon: Navigation, category: 'Location' },
  // Organization
  { name: 'Tag', icon: Tag, category: 'Organization' },
  { name: 'Tags', icon: Tags, category: 'Organization' },
  { name: 'Bookmark', icon: Bookmark, category: 'Organization' },
  { name: 'Filter', icon: Filter, category: 'Organization' },
  { name: 'Search', icon: Search, category: 'Organization' },
  { name: 'Layers', icon: Layers, category: 'Organization' },
  // Status & Feedback
  { name: 'Star', icon: Star, category: 'Status' },
  { name: 'Heart', icon: Heart, category: 'Status' },
  { name: 'ThumbsUp', icon: ThumbsUp, category: 'Status' },
  { name: 'Award', icon: Award, category: 'Status' },
  { name: 'Trophy', icon: Trophy, category: 'Status' },
  { name: 'CheckCircle', icon: CheckCircle, category: 'Status' },
  { name: 'AlertCircle', icon: AlertCircle, category: 'Status' },
  { name: 'AlertTriangle', icon: AlertTriangle, category: 'Status' },
  { name: 'Info', icon: Info, category: 'Status' },
  // Analytics
  { name: 'Activity', icon: Activity, category: 'Analytics' },
  { name: 'TrendingUp', icon: TrendingUp, category: 'Analytics' },
  { name: 'BarChart', icon: BarChart, category: 'Analytics' },
  { name: 'PieChart', icon: PieChart, category: 'Analytics' },
  { name: 'LineChart', icon: LineChart, category: 'Analytics' },
  { name: 'Zap', icon: Zap, category: 'Analytics' },
  // Layout
  { name: 'Layout', icon: Layout, category: 'Layout' },
  { name: 'Grid', icon: Grid, category: 'Layout' },
  { name: 'List', icon: List, category: 'Layout' },
  { name: 'Table', icon: Table, category: 'Layout' },
  { name: 'Columns', icon: Columns, category: 'Layout' },
  // Connections
  { name: 'Link', icon: Link, category: 'Connections' },
  { name: 'Link2', icon: Link2, category: 'Connections' },
  { name: 'Share', icon: Share, category: 'Connections' },
  { name: 'Share2', icon: Share2, category: 'Connections' },
  // Media
  { name: 'Image', icon: Image, category: 'Media' },
  { name: 'Camera', icon: Camera, category: 'Media' },
  { name: 'Video', icon: Video, category: 'Media' },
  { name: 'Music', icon: Music, category: 'Media' },
  // Devices
  { name: 'Smartphone', icon: Smartphone, category: 'Devices' },
  { name: 'Tablet', icon: Tablet, category: 'Devices' },
  { name: 'Monitor', icon: Monitor, category: 'Devices' },
  { name: 'Laptop', icon: Laptop, category: 'Devices' },
  { name: 'Printer', icon: Printer, category: 'Devices' },
  // Tech
  { name: 'Code', icon: Code, category: 'Tech' },
  { name: 'Terminal', icon: Terminal, category: 'Tech' },
  { name: 'Cpu', icon: Cpu, category: 'Tech' },
  { name: 'Wifi', icon: Wifi, category: 'Tech' },
  // Shapes
  { name: 'Circle', icon: Circle, category: 'Shapes' },
  { name: 'Square', icon: Square, category: 'Shapes' },
  { name: 'Triangle', icon: Triangle, category: 'Shapes' },
  { name: 'Hexagon', icon: Hexagon, category: 'Shapes' },
  { name: 'Diamond', icon: Diamond, category: 'Shapes' },
  { name: 'Gem', icon: Gem, category: 'Shapes' },
  { name: 'Crown', icon: Crown, category: 'Shapes' },
  // Education
  { name: 'GraduationCap', icon: GraduationCap, category: 'Education' },
  { name: 'BookOpen', icon: BookOpen, category: 'Education' },
  { name: 'Book', icon: Book, category: 'Education' },
  { name: 'Library', icon: Library, category: 'Education' },
  // Business
  { name: 'Briefcase', icon: Briefcase, category: 'Business' },
  { name: 'Flag', icon: Flag, category: 'Business' },
  { name: 'Newspaper', icon: Newspaper, category: 'Business' },
];

// Define custom node data type for classes
type ClassProperty = {
  id: string;
  name: string;
  type?: string;
  description?: string;
  data?: any; // JSONB data containing the property schema
  parent_id?: string | null; // Parent property ID for nested properties
};

export type NodeBorderStyle = 'solid' | 'dashed' | 'dotted';

// Label styling for class name in header (#343)
export type LabelTextAlign = 'left' | 'center' | 'right';
export type LabelFontWeight = 'normal' | 'bold';

type ClassNodeTheme = {
  backgroundColor?: string;
  borderColor?: string;
  borderWidth?: number; // 1-5px
  borderStyle?: NodeBorderStyle;
  headerGradient?: string;
  textColor?: string;
  headerTextColor?: string;
  icon?: string; // Icon name from lucide-react
  // Label styling (#343)
  labelFontSize?: number; // px
  labelFontFamily?: string;
  labelFontWeight?: LabelFontWeight;
  labelFontStyle?: 'normal' | 'italic';
  labelTextAlign?: LabelTextAlign;
  labelMultiLine?: boolean;
};

type DragPayload = {
  type?: string;
  property?: {
    name?: string;
    type?: string;
    data?: any;
  };
};

// Border options for node style (#342) — includes 1.5 to match default
const BORDER_WIDTH_OPTIONS = [1, 2, 3, 4, 5] as const;
const BORDER_STYLE_OPTIONS: Array<{ name: NodeBorderStyle; label: string }> = [
  { name: 'solid', label: 'Solid' },
  { name: 'dashed', label: 'Dashed' },
  { name: 'dotted', label: 'Dotted' },
];

// Label styling options (#343)
const LABEL_FONT_SIZE_OPTIONS = [10, 11, 12, 13, 14, 16, 18, 20] as const;
const LABEL_FONT_FAMILY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'inherit', label: 'Default' },
  { value: 'system-ui, sans-serif', label: 'System' },
  { value: 'Georgia, serif', label: 'Serif' },
  { value: 'ui-monospace, monospace', label: 'Mono' },
  { value: 'Inter, system-ui, sans-serif', label: 'Inter' },
];

// --- Custom color picker: derive full theme from a single primary hex ---
function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const m = hex.replace(/^#/, '').match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i)
    || hex.replace(/^#/, '').match(/^([0-9a-f])([0-9a-f])([0-9a-f])$/i);
  if (!m) return null;
  const expand = (x: string) => (x.length === 1 ? x + x : x);
  return {
    r: parseInt(expand(m[1]), 16),
    g: parseInt(expand(m[2]), 16),
    b: parseInt(expand(m[3]), 16),
  };
}
function rgbToHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b].map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, '0')).join('');
}
function darkenHex(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const f = 1 - Math.max(0, Math.min(1, amount));
  return rgbToHex(rgb.r * f, rgb.g * f, rgb.b * f);
}
function lightTint(hex: string, mixWhite: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const w = Math.max(0, Math.min(1, mixWhite));
  return rgbToHex(
    rgb.r * (1 - w) + 255 * w,
    rgb.g * (1 - w) + 255 * w,
    rgb.b * (1 - w) + 255 * w
  );
}
/** Normalize to #rrggbb for input[type=color] and storage */
function normalizeHex(hex: string): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return '#6366f1';
  return rgbToHex(rgb.r, rgb.g, rgb.b);
}
/** Build full ClassNode theme from a single primary (header/border) color */
function themeFromPrimaryColor(primaryHex: string): Omit<ClassNodeTheme, 'icon'> {
  const hex = normalizeHex(primaryHex);
  const darker = darkenHex(hex, 0.18);
  const bg = lightTint(hex, 0.92);
  const text = darkenHex(hex, 0.55);
  return {
    backgroundColor: bg,
    borderColor: hex,
    headerGradient: `linear-gradient(135deg, ${hex} 0%, ${darker} 100%)`,
    textColor: text,
    headerTextColor: '#ffffff',
  };
}

function getBaseTypeFromData(data: any): string | undefined {
  if (Array.isArray(data?.type)) {
    return data.type.find((t: string) => t !== 'null');
  }
  return data?.type;
}

export function getDropPreviewPropertyType(property: { type?: string; data?: any } | null | undefined): string {
  // Prefer schema from `property.data` (string or object), but fall back to the
  // full `property` object so that top-level $ref/items are also supported.
  let schemaFromData: any | undefined;

  if (property?.data) {
    if (typeof property.data === 'string') {
      const trimmed = property.data.trim();
      if (trimmed) {
        try {
          schemaFromData = JSON.parse(trimmed);
        } catch {
          // Ignore parse errors and fall back to using the full property object.
          schemaFromData = undefined;
        }
      }
    } else if (typeof property.data === 'object') {
      schemaFromData = property.data;
    }
  }

  const schema = (schemaFromData && typeof schemaFromData === 'object')
    ? schemaFromData
    : (property && typeof property === 'object' ? property : {});

  const baseType = getBaseTypeFromData(schema);
  if (baseType === 'array') {
    if (schema?.items?.$ref) {
      const refName = String(schema.items.$ref).split('/').pop();
      return `${refName || 'ref'}[]`;
    }
    if (schema?.items?.type) {
      const itemBaseType = getBaseTypeFromData(schema.items);
      return `${itemBaseType || schema.items.type}[]`;
    }
    return 'array';
  }
  if (schema?.$ref) {
    return String(schema.$ref).split('/').pop() || 'ref';
  }
  if (schema?.allOf) return 'allOf';
  if (schema?.anyOf) return 'anyOf';
  if (schema?.oneOf) return 'oneOf';
  return baseType || property?.type || 'object';
}

type ClassNodeData = {
  id: string;
  name: string;
  description?: string;
  properties?: ClassProperty[];
  schema?: any; // Schema containing allOf/anyOf/oneOf
  tags?: Array<{ id: string; tag_name: string; tag_color: string }>;
  onPropertyDrop?: (classId: string, propertyData: any, parentId?: string | null) => void;
  onPropertyEdit?: (classId: string, classProperty: ClassProperty) => void;
  onPropertyDelete?: (classId: string, classPropertyId: string) => void;
  onClassEdit?: (classData: any) => void;
  onClassDelete?: (classId: string, className: string) => void;
  onCreateReference?: (classOrCompositeId: string) => void;
  onThemeChange?: (classId: string, theme: ClassNodeTheme) => void;
  onToggleVisibility?: (classId: string, visible?: boolean) => void;
  isReadOnly?: boolean;
  expandedProperties?: Set<string>; // Global expanded properties state
  onTogglePropertyExpansion?: (propertyId: string) => void; // Callback to toggle property expansion
  zoomLevel?: number; // Current zoom level for level-of-detail rendering
  lodEnabled?: boolean; // Whether LOD is enabled (defaults to true)
  theme?: ClassNodeTheme; // Custom theme from canvas_metadata
  /** #559: Number of edges connected to this node (source or target) for badge display */
  relationshipCount?: number;
  /** #560: Heatmap visualization mode (when set, heatmapValue is 0–1) */
  heatmapMode?: 'off' | 'complexity' | 'changeFrequency' | 'usage' | 'documentation';
  heatmapValue?: number;
  heatmapLabel?: string;
  /** #548: Part of a circular dependency – show warning indicator */
  inCircularDependency?: boolean;
  /** #549: Dependency depth (0=leaf, 1=1st, 2=2nd, 3=3rd, 4+=3+) when overlay is on */
  dependencyDepth?: number;
  /** #549: Human-readable label e.g. "1st", "2nd", "3rd", "3+", "Leaf" */
  dependencyDepthLabel?: string;
  /** #550: Impact Analysis – this node is the selected (changed) class */
  impactSource?: boolean;
  /** #550: Impact Analysis – this node is affected by the selected class */
  impactAffected?: boolean;
};

function ClassNode({ id, data, selected }: NodeProps) {
  const typedData = data as ClassNodeData;
  const { confirm: confirmDialog } = useDialog();
  const updateNodeInternals = useUpdateNodeInternals();

  const [dragTarget, setDragTarget] = useState<'node' | 'property' | null>(null);
  const [dragOverPropertyId, setDragOverPropertyId] = useState<string | null>(null);
  /** #479: Reason string when drop would be invalid (duplicate, read-only, etc.); null when valid or not dragging over */
  const [invalidDropReason, setInvalidDropReason] = useState<string | null>(null);
  const [ghostPreview, setGhostPreview] = useState<{ name: string; typeLabel: string; parentId: string | null } | null>(null);
  const ghostPreviewKeyRef = useRef<string | null>(null);
  const [localExpandedProperties, setLocalExpandedProperties] = useState<Set<string>>(new Set());
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [iconSearchQuery, setIconSearchQuery] = useState('');
  /** #854: Property row shows type by default; edit/delete replace type on hover (editable canvas only). */
  const [hoveredPropertyRowId, setHoveredPropertyRowId] = useState<string | null>(null);
  /** #853: Hover on class node shows editing actions outside the card (popover open keeps toolbar visible). */

  const nodeRef = useRef<HTMLDivElement>(null);

  // Use ResizeObserver to detect when the node's actual DOM size changes
  // This is more reliable than depending on property changes
  useEffect(() => {
    const element = nodeRef.current;
    if (!element) return;

    let timeoutId: NodeJS.Timeout | null = null;

    const resizeObserver = new ResizeObserver(() => {
      // Debounce the updateNodeInternals call to avoid excessive updates
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      timeoutId = setTimeout(() => {
        // When the element size changes, tell React Flow to recalculate handle positions
        updateNodeInternals(id);
      }, 10);
    });

    resizeObserver.observe(element);

    // Also trigger an initial update after mount
    const initialTimeout = setTimeout(() => {
      updateNodeInternals(id);
    }, 100);

    return () => {
      resizeObserver.disconnect();
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      clearTimeout(initialTimeout);
    };
  }, [id, updateNodeInternals]);

  // Predefined color themes (6x4 grid = 24 colors) - square tiles like custom selector
  const colorThemes = [
    { name: 'Slate', hex: '#64748b', headerGradient: 'linear-gradient(135deg, #64748b 0%, #475569 100%)', backgroundColor: '#f8fafc', borderColor: '#64748b', textColor: '#1e293b', headerTextColor: '#ffffff' },
    { name: 'Gray', hex: '#6b7280', headerGradient: 'linear-gradient(135deg, #6b7280 0%, #4b5563 100%)', backgroundColor: '#f9fafb', borderColor: '#6b7280', textColor: '#111827', headerTextColor: '#ffffff' },
    { name: 'Zinc', hex: '#71717a', headerGradient: 'linear-gradient(135deg, #71717a 0%, #52525b 100%)', backgroundColor: '#fafafa', borderColor: '#71717a', textColor: '#18181b', headerTextColor: '#ffffff' },
    { name: 'Stone', hex: '#78716c', headerGradient: 'linear-gradient(135deg, #78716c 0%, #57534e 100%)', backgroundColor: '#fafaf9', borderColor: '#78716c', textColor: '#1c1917', headerTextColor: '#ffffff' },
    { name: 'Red', hex: '#ef4444', headerGradient: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)', backgroundColor: '#fef2f2', borderColor: '#ef4444', textColor: '#991b1b', headerTextColor: '#ffffff' },
    { name: 'Rose', hex: '#f43f5e', headerGradient: 'linear-gradient(135deg, #f43f5e 0%, #e11d48 100%)', backgroundColor: '#fff1f2', borderColor: '#f43f5e', textColor: '#9f1239', headerTextColor: '#ffffff' },
    { name: 'Orange', hex: '#f97316', headerGradient: 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)', backgroundColor: '#fff7ed', borderColor: '#f97316', textColor: '#9a3412', headerTextColor: '#ffffff' },
    { name: 'Amber', hex: '#f59e0b', headerGradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)', backgroundColor: '#fffbeb', borderColor: '#f59e0b', textColor: '#92400e', headerTextColor: '#ffffff' },
    { name: 'Yellow', hex: '#eab308', headerGradient: 'linear-gradient(135deg, #eab308 0%, #ca8a04 100%)', backgroundColor: '#fefce8', borderColor: '#eab308', textColor: '#854d0e', headerTextColor: '#ffffff' },
    { name: 'Lime', hex: '#84cc16', headerGradient: 'linear-gradient(135deg, #84cc16 0%, #65a30d 100%)', backgroundColor: '#f7fee7', borderColor: '#84cc16', textColor: '#3f6212', headerTextColor: '#ffffff' },
    { name: 'Green', hex: '#22c55e', headerGradient: 'linear-gradient(135deg, #22c55e 0%, #16a34a 100%)', backgroundColor: '#f0fdf4', borderColor: '#22c55e', textColor: '#166534', headerTextColor: '#ffffff' },
    { name: 'Emerald', hex: '#10b981', headerGradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', backgroundColor: '#ecfdf5', borderColor: '#10b981', textColor: '#065f46', headerTextColor: '#ffffff' },
    { name: 'Teal', hex: '#14b8a6', headerGradient: 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)', backgroundColor: '#f0fdfa', borderColor: '#14b8a6', textColor: '#115e59', headerTextColor: '#ffffff' },
    { name: 'Cyan', hex: '#06b6d4', headerGradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)', backgroundColor: '#ecfeff', borderColor: '#06b6d4', textColor: '#164e63', headerTextColor: '#ffffff' },
    { name: 'Sky', hex: '#0ea5e9', headerGradient: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)', backgroundColor: '#f0f9ff', borderColor: '#0ea5e9', textColor: '#0c4a6e', headerTextColor: '#ffffff' },
    { name: 'Blue', hex: '#3b82f6', headerGradient: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)', backgroundColor: '#eff6ff', borderColor: '#3b82f6', textColor: '#1e40af', headerTextColor: '#ffffff' },
    { name: 'Indigo', hex: '#6366f1', headerGradient: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)', backgroundColor: '#eef2ff', borderColor: '#6366f1', textColor: '#3730a3', headerTextColor: '#ffffff' },
    { name: 'Violet', hex: '#8b5cf6', headerGradient: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)', backgroundColor: '#f5f3ff', borderColor: '#8b5cf6', textColor: '#5b21b6', headerTextColor: '#ffffff' },
    { name: 'Purple', hex: '#a855f7', headerGradient: 'linear-gradient(135deg, #a855f7 0%, #9333ea 100%)', backgroundColor: '#faf5ff', borderColor: '#a855f7', textColor: '#6b21a8', headerTextColor: '#ffffff' },
    { name: 'Fuchsia', hex: '#d946ef', headerGradient: 'linear-gradient(135deg, #d946ef 0%, #c026d3 100%)', backgroundColor: '#fdf4ff', borderColor: '#d946ef', textColor: '#86198f', headerTextColor: '#ffffff' },
    { name: 'Pink', hex: '#ec4899', headerGradient: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)', backgroundColor: '#fdf2f8', borderColor: '#ec4899', textColor: '#9d174d', headerTextColor: '#ffffff' },
    { name: 'Deep Blue', hex: '#1d4ed8', headerGradient: 'linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%)', backgroundColor: '#eff6ff', borderColor: '#1d4ed8', textColor: '#1e3a8a', headerTextColor: '#ffffff' },
    { name: 'Neutral', hex: '#525252', headerGradient: 'linear-gradient(135deg, #525252 0%, #404040 100%)', backgroundColor: '#fafafa', borderColor: '#525252', textColor: '#171717', headerTextColor: '#ffffff' },
    { name: 'Slate Blue', hex: '#475569', headerGradient: 'linear-gradient(135deg, #475569 0%, #334155 100%)', backgroundColor: '#f8fafc', borderColor: '#475569', textColor: '#1e293b', headerTextColor: '#ffffff' },
  ];

  const handleThemeSelect = (theme: Omit<ClassNodeTheme, 'name'>) => {
    if (typedData.onThemeChange) {
      typedData.onThemeChange(typedData.id, theme);
    }
    // Close the color picker after selection
    setColorPickerOpen(false);
  };

  // Custom color picker: derive full theme from chosen hex and merge with existing (border, icon)
  const handleCustomColorChange = (hex: string) => {
    if (!typedData.onThemeChange) return;
    const derived = themeFromPrimaryColor(hex);
    const currentTheme = typedData.theme || {};
    typedData.onThemeChange(typedData.id, {
      ...currentTheme,
      ...derived,
      // Preserve border and icon
      borderWidth: currentTheme.borderWidth,
      borderStyle: currentTheme.borderStyle,
      icon: currentTheme.icon,
    });
  };

  // Current primary color for the color input (borderColor or default)
  const customColorValue = typedData.theme?.borderColor
    ? normalizeHex(typedData.theme.borderColor)
    : '#6366f1';

  // Handle icon selection - merges with existing theme
  const handleIconSelect = (iconName: string | null) => {
    if (typedData.onThemeChange) {
      const currentTheme = typedData.theme || {};
      typedData.onThemeChange(typedData.id, { ...currentTheme, icon: iconName || undefined });
    }
    setIconPickerOpen(false);
    setIconSearchQuery('');
  };

  // Handle border change - merges with existing theme (#342)
  const handleBorderChange = (updates: { borderWidth?: number; borderStyle?: NodeBorderStyle }) => {
    if (typedData.onThemeChange) {
      const currentTheme = typedData.theme || {};
      typedData.onThemeChange(typedData.id, { ...currentTheme, ...updates });
    }
  };

  // Handle label style change - merges with existing theme (#343)
  const handleLabelStyleChange = (updates: Partial<Pick<ClassNodeTheme, 'labelFontSize' | 'labelFontFamily' | 'labelFontWeight' | 'labelFontStyle' | 'labelTextAlign' | 'labelMultiLine'>>) => {
    if (typedData.onThemeChange) {
      const currentTheme = typedData.theme || {};
      typedData.onThemeChange(typedData.id, { ...currentTheme, ...updates });
    }
  };

  // Get the icon component for the current theme
  const getIconComponent = (): LucideIcon | null => {
    const iconName = typedData.theme?.icon;
    if (!iconName) return null;
    const iconOption = NODE_ICON_OPTIONS.find(opt => opt.name === iconName);
    return iconOption?.icon || null;
  };

  // Filter icons based on search query
  const filteredIcons = iconSearchQuery.trim()
    ? NODE_ICON_OPTIONS.filter(opt =>
        opt.name.toLowerCase().includes(iconSearchQuery.toLowerCase()) ||
        opt.category.toLowerCase().includes(iconSearchQuery.toLowerCase())
      )
    : NODE_ICON_OPTIONS;

  // Level of detail calculations based on zoom
  // At zoom < 0.5 (50% - zoomed out), show minimal detail (class name only)
  // At zoom 0.5-1.0, transition from minimal to full detail
  // At zoom >= 1.0 (zoomed in), show full detail
  const zoom = typedData.zoomLevel ?? 1;
  const lodEnabled = typedData.lodEnabled ?? false; // Default to disabled

  // Calculate opacity for different detail levels
  // Properties fade out completely when zoomed out to 50% or less
  // If LOD is disabled, always show full opacity
  const propertiesOpacity = lodEnabled ? Math.max(0, Math.min(1, (zoom - 0.5) / 0.5)) : 1;

  // Description fades out when zooming out to 75% or less
  // If LOD is disabled, always show full opacity
  const descriptionOpacity = lodEnabled ? Math.max(0, Math.min(1, (zoom - 0.75) / 0.25)) : 1;

  // Tags fade out at same rate as description
  const tagsOpacity = descriptionOpacity;

  // Show properties only when there's visible opacity (or LOD is disabled)
  const showProperties = !lodEnabled || propertiesOpacity > 0.05;
  const showDescription = !lodEnabled || descriptionOpacity > 0.05;
  const showTags = !lodEnabled || tagsOpacity > 0.05;

  // Use global expanded state if provided, otherwise use local state
  const expandedProperties = typedData.expandedProperties || localExpandedProperties;

  const togglePropertyExpansion = (propertyId: string) => {
    if (typedData.onTogglePropertyExpansion) {
      // Use global handler if provided
      typedData.onTogglePropertyExpansion(propertyId);
    } else {
      // Fall back to local state
      const next = new Set(localExpandedProperties);
      if (next.has(propertyId)) next.delete(propertyId); else next.add(propertyId);
      setLocalExpandedProperties(next);
    }
  };

  // Build hierarchical property structure
  const buildPropertyHierarchy = (): { topLevel: ClassProperty[]; childMap: Map<string, ClassProperty[]> } => {
    const all = typedData.properties || [];
    const topLevel = all.filter((p) => !p.parent_id);
    const childMap = new Map<string, ClassProperty[]>();
    all.forEach((p) => {
      if (p.parent_id) {
        if (!childMap.has(p.parent_id)) childMap.set(p.parent_id, []);
        childMap.get(p.parent_id)!.push(p);
      }
    });
    return { topLevel, childMap };
  };

  // Helpers for schema parsing
  const parseData = (prop: ClassProperty) => (typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data || {});

  // Helper to get base type from nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
  const getBaseType = (propData: any): string | undefined => {
    if (Array.isArray(propData?.type)) {
      return propData.type.find((t: string) => t !== 'null');
    }
    return propData?.type;
  };

  const hasRef = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    const baseType = getBaseType(d);
    // Check for direct $ref
    if (d?.$ref) return true;
    // Check for array items $ref
    if (baseType === 'array' && d?.items?.$ref) return true;
    // Check for composition types (allOf/anyOf/oneOf)
    if (d?.allOf || d?.anyOf || d?.oneOf) return true;
    // Check for composition types in array items
    if (baseType === 'array' && d?.items) {
      if (d.items.allOf || d.items.anyOf || d.items.oneOf) return true;
    }
    return false;
  };

  const isInlineObjectContainer = (prop: ClassProperty): boolean => {
    const d = parseData(prop);
    const baseType = getBaseType(d);
    if (baseType === 'object' && !d.$ref) return true;
    if (baseType === 'array') {
      const items = d.items || {};
      if (items.type === 'object' && !items.$ref) return true;
      // If items is missing but we have inline children attached, treat as container
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      return hasInlineChildren;
    }
    return false;
  };

  const isDescendantOfDraggedProperty = (propertyId: string, draggedParentId: string | null): boolean => {
    if (!draggedParentId) return false;
    const all = typedData.properties || [];
    let current = all.find((p) => p.id === propertyId);
    while (current && current.parent_id) {
      if (current.parent_id === draggedParentId) return true;
      current = all.find((p) => p.id === current!.parent_id);
    }
    return false;
  };

  const getPropertyType = (prop: ClassProperty): string => {
    const d = parseData(prop);

    // Handle allOf/anyOf/oneOf compositions
    if (d?.allOf && Array.isArray(d.allOf)) {
      const types = d.allOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `allOf(${types.length})` : 'allOf';
    }
    if (d?.anyOf && Array.isArray(d.anyOf)) {
      const types = d.anyOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `anyOf(${types.length})` : 'anyOf';
    }
    if (d?.oneOf && Array.isArray(d.oneOf)) {
      const types = d.oneOf.map((item: any) => {
        if (item.$ref) return item.$ref.split('/').pop();
        return item.type || 'schema';
      }).filter(Boolean);
      return types.length > 0 ? `oneOf(${types.length})` : 'oneOf';
    }

    if (d?.type === 'array') {
      // Handle composition in array items
      if (d.items?.allOf && Array.isArray(d.items.allOf)) {
        const types = d.items.allOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `allOf(${types.length})[]` : 'allOf[]';
      }
      if (d.items?.anyOf && Array.isArray(d.items.anyOf)) {
        const types = d.items.anyOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `anyOf(${types.length})[]` : 'anyOf[]';
      }
      if (d.items?.oneOf && Array.isArray(d.items.oneOf)) {
        const types = d.items.oneOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        return types.length > 0 ? `oneOf(${types.length})[]` : 'oneOf[]';
      }
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        return `${refName}[]`;
      }
      if (d.items?.type) {
        return `${d.items.type}[]`;
      }
      // Items missing or unassigned reference
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        if (refName === '__unassigned__') return '(unassigned)[]';
        return `${refName}[]`;
      }
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      return hasInlineChildren ? 'object[]' : 'any[]';
    }

    // Handle nullable type arrays (OpenAPI 3.1 style like ['string', 'null'])
    const baseType = getBaseType(d);
    const isNullable = Array.isArray(d?.type) && d.type.includes('null');

    if (baseType === 'array') {
      // Handle composition in array items
      if (d.items?.allOf && Array.isArray(d.items.allOf)) {
        const types = d.items.allOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `allOf(${types.length})[]${suffix}` : `allOf[]${suffix}`;
      }
      if (d.items?.anyOf && Array.isArray(d.items.anyOf)) {
        const types = d.items.anyOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `anyOf(${types.length})[]${suffix}` : `anyOf[]${suffix}`;
      }
      if (d.items?.oneOf && Array.isArray(d.items.oneOf)) {
        const types = d.items.oneOf.map((item: any) => {
          if (item.$ref) return item.$ref.split('/').pop();
          return item.type || 'schema';
        }).filter(Boolean);
        const suffix = isNullable ? '?' : '';
        return types.length > 0 ? `oneOf(${types.length})[]${suffix}` : `oneOf[]${suffix}`;
      }
      if (d.items?.$ref) {
        const refName = d.items.$ref.split('/').pop();
        const suffix = isNullable ? '?' : '';
        return `${refName}[]${suffix}`;
      }
      if (d.items?.type) {
        const suffix = isNullable ? '?' : '';
        return `${d.items.type}[]${suffix}`;
      }
      const hasInlineChildren = (typedData.properties || []).some((p) => p.parent_id === prop.id);
      const suffix = isNullable ? '?' : '';
      return hasInlineChildren ? `object[]${suffix}` : `any[]${suffix}`;
    }

    if (d?.$ref) {
      const refName = d.$ref.split('/').pop();
      if (refName === '__unassigned__') return '(unassigned)';
      const suffix = isNullable ? '?' : '';
      return `${refName ?? 'ref'}${suffix}`;
    }

    const typeName = baseType || prop.type || 'object';
    const suffix = isNullable ? '?' : '';
    return `${typeName}${suffix}`;
  };

  // #479: Validate whether a drop at the given parent would be invalid (duplicate name or read-only)
  const validateDrop = (parentId: string | null, dragPayload: { type?: string; property?: { name?: string } } | null): string | null => {
    if (!dragPayload || !dragPayload.type) return null;
    if (typedData.isReadOnly) return 'This class is read-only';
    if (dragPayload.type === 'property' && dragPayload.property?.name) {
      const name = String(dragPayload.property.name).trim();
      const props = typedData.properties || [];
      const duplicate = props.some(
        (p) =>
          (p.parent_id === parentId || (p.parent_id == null && parentId == null)) &&
          String(p.name).trim() === name
      );
      if (duplicate) return 'A property with this name already exists at this level';
    }
    return null;
  };

  const setGhostPreviewFromPayload = (payload: DragPayload | null, parentId: string | null) => {
    if (payload?.type !== 'property' || !payload.property?.name) {
      if (ghostPreviewKeyRef.current !== null) {
        ghostPreviewKeyRef.current = null;
        setGhostPreview(null);
      }
      return;
    }
    const name = String(payload.property.name).trim();
    if (!name) {
      if (ghostPreviewKeyRef.current !== null) {
        ghostPreviewKeyRef.current = null;
        setGhostPreview(null);
      }
      return;
    }
    const typeLabel = getDropPreviewPropertyType(payload.property);
    const previewKey = `${parentId ?? 'root'}|${name}|${typeLabel}`;
    if (ghostPreviewKeyRef.current === previewKey) return;
    ghostPreviewKeyRef.current = previewKey;
    setGhostPreview({
      name,
      typeLabel,
      parentId,
    });
  };

  const clearGhostPreview = () => {
    if (ghostPreviewKeyRef.current !== null) {
      ghostPreviewKeyRef.current = null;
      setGhostPreview(null);
    }
  };

  const renderGhostPreviewRow = (key: string, paddingLeft?: string) => {
    if (!ghostPreview || invalidDropReason) return null;
    return (
      <div
        key={key}
        style={{
          display: 'grid',
          gridTemplateColumns: '16px 1fr auto 36px',
          alignItems: 'center',
          padding: '5px 10px',
          ...(paddingLeft ? { paddingLeft } : {}),
          background: 'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)',
          borderBottom: '1px dashed #93c5fd',
          gap: '4px',
          minHeight: '28px',
          opacity: 0.95,
        }}
        aria-hidden
      >
        <div />
        <div style={{ fontWeight: 500, color: '#1d4ed8', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {ghostPreview.name}
        </div>
        <div style={{ fontSize: '9px', color: '#1e40af', fontFamily: '"SF Mono", Monaco, "Cascadia Code", monospace', whiteSpace: 'nowrap', background: 'rgba(147, 197, 253, 0.35)', padding: '1px 6px', borderRadius: '3px', fontWeight: 500 }}>
          {ghostPreview.typeLabel}
        </div>
        <div style={{ fontSize: '9px', color: '#1d4ed8', textAlign: 'right', paddingRight: '2px', fontStyle: 'italic' }}>preview</div>
      </div>
    );
  };

  // DnD Handlers (top-level)
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragTarget !== 'property') setDragTarget('node');
    // #479: Validate drop (getData may be empty in some browsers until drop)
    try {
      const raw = e.dataTransfer.getData('application/json');
      const payload = raw ? (JSON.parse(raw) as DragPayload) : null;
      const reason = validateDrop(null, payload);
      setInvalidDropReason(reason);
      if (reason) e.dataTransfer.dropEffect = 'none';
      setGhostPreviewFromPayload(payload, null);
    } catch {
      setInvalidDropReason(null);
      clearGhostPreview();
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    setInvalidDropReason(null);
    clearGhostPreview();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    setInvalidDropReason(null);
    clearGhostPreview();
    if (typedData.isReadOnly) return;
    try {
      const raw = e.dataTransfer.getData('application/json');
      if (raw) {
        const dropData = JSON.parse(raw);
        // #479: Re-validate on drop; do not perform invalid drop
        if (validateDrop(null, dropData)) return;
        if (dropData.type === 'property' && typedData.onPropertyDrop) {
          typedData.onPropertyDrop(typedData.id, dropData.property, null);
        } else if (dropData.type === 'new-reference' && typedData.onCreateReference) {
          typedData.onCreateReference(typedData.id);
        }
      }
    } catch (err) {
      console.error('Error handling property drop:', err);
    }
  };

  // DnD Handlers (per-property for containers)
  const handlePropertyDragOver = (e: React.DragEvent, propertyId: string, isObject: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    if (isObject) {
      setDragTarget('property');
      setDragOverPropertyId(propertyId);
      try {
        const raw = e.dataTransfer.getData('application/json');
        const payload = raw ? (JSON.parse(raw) as DragPayload) : null;
        const reason = validateDrop(propertyId, payload);
        setInvalidDropReason(reason);
        if (reason) e.dataTransfer.dropEffect = 'none';
        setGhostPreviewFromPayload(payload, propertyId);
      } catch {
        setInvalidDropReason(null);
        clearGhostPreview();
      }
    } else {
      setDragTarget('node');
      setDragOverPropertyId(null);
      try {
        const raw = e.dataTransfer.getData('application/json');
        const payload = raw ? (JSON.parse(raw) as DragPayload) : null;
        const reason = validateDrop(null, payload);
        setInvalidDropReason(reason);
        if (reason) e.dataTransfer.dropEffect = 'none';
        setGhostPreviewFromPayload(payload, null);
      } catch {
        setInvalidDropReason(null);
        clearGhostPreview();
      }
    }
  };

  const handlePropertyDragLeave = (e: React.DragEvent, propertyId: string, isObject: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    setInvalidDropReason(null);
    clearGhostPreview();
  };

  const handlePropertyDrop = (e: React.DragEvent, parentPropertyId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragTarget(null);
    setDragOverPropertyId(null);
    setInvalidDropReason(null);
    clearGhostPreview();
    if (typedData.isReadOnly) return;
    try {
      const raw = e.dataTransfer.getData('application/json');
      if (raw) {
        const dropData = JSON.parse(raw);
        // #479: Re-validate on drop; do not perform invalid drop
        if (validateDrop(parentPropertyId, dropData)) return;
        if (dropData.type === 'property' && typedData.onPropertyDrop) {
          typedData.onPropertyDrop(typedData.id, dropData.property, parentPropertyId);
        } else if (dropData.type === 'new-reference' && typedData.onCreateReference) {
          typedData.onCreateReference(`${typedData.id}|${parentPropertyId}`);
        }
      }
    } catch (err) {
      console.error('Error handling nested property drop:', err);
    }
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (typedData.onClassEdit) {
      typedData.onClassEdit({
        id: typedData.id,
        name: typedData.name,
        description: typedData.description,
        schema: typedData.schema,
        properties: typedData.properties,
      });
    }
  };

  const { topLevel, childMap } = buildPropertyHierarchy();

  // Theme pass-through (custom user-chosen colors/borders). The NodeCard primitive
  // owns default surfaces, selection glow, drop overlays, and warning rings.
  const customBorderColor = typedData.theme?.borderColor || undefined;
  const customBackground = typedData.theme?.backgroundColor || undefined;
  const customHeaderBackground = typedData.theme?.headerGradient || undefined;
  const customHeaderTextColor = typedData.theme?.headerTextColor || undefined;
  const customTextColor = typedData.theme?.textColor || undefined;
  const borderWidth = Math.min(5, Math.max(1, typedData.theme?.borderWidth ?? 1));
  const borderStyle = typedData.theme?.borderStyle ?? 'solid';

  const isDropTarget = dragTarget === 'node' || dragTarget === 'property';
  const isValidDropTarget = isDropTarget && !invalidDropReason;

  // Heatmap tint (cool -> warm by value) — rendered by NodeCard as a full-card overlay.
  const heatmapTint =
    typedData.heatmapMode && typedData.heatmapMode !== 'off' && typeof typedData.heatmapValue === 'number'
      ? (() => {
          const v = Math.max(0, Math.min(1, typedData.heatmapValue));
          const opacity = 0.2 + v * 0.4;
          const r = Math.round(59 + (239 - 59) * v);
          const g = Math.round(130 + (68 - 130) * v);
          const b = Math.round(246 + (68 - 246) * v);
          return `rgba(${r}, ${g}, ${b}, ${opacity})`;
        })()
      : undefined;

  const propCount = (typedData.properties || []).length;
  const relCount = typedData.relationshipCount ?? 0;
  const headerBadgeVariant: 'overlay' | 'neutral' = customHeaderBackground ? 'overlay' : 'neutral';
  const headerInfoVariant: 'overlay' | 'info' = customHeaderBackground ? 'overlay' : 'info';
  const headerWarnVariant: 'overlay' | 'warning' = customHeaderBackground ? 'overlay' : 'warning';

  return (
    <div
      className="relative group"
    >
      {!typedData.isReadOnly && (
        <div
          className={cn(
            'absolute -right-[2px] -top-[24px] z-[35]',
            'flex items-center gap-0.5',
            'rounded-lg border border-slate-200/90',
            'bg-white/95 py-0.5 pl-0.5 pr-0.5',
            'shadow-lg backdrop-blur-sm',
            'dark:border-slate-600/90 dark:bg-slate-900/95',
            'pointer-events-none opacity-0',
            'group-hover:pointer-events-auto group-hover:opacity-100',
            'focus-within:pointer-events-auto focus-within:opacity-100',
            (colorPickerOpen || iconPickerOpen) && '!opacity-100 !pointer-events-auto',
          )}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="relative z-[1] flex items-center gap-0.5">
            {/* Color picker button using Popover */}
            <Popover.Root open={colorPickerOpen} onOpenChange={setColorPickerOpen}>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-200 bg-slate-100 text-slate-700 transition-colors hover:bg-slate-200 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
                  onClick={(e) => e.stopPropagation()}
                  title="Change colors"
                >
                  <Palette size={12} />
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-3 min-w-[200px]"
                  sideOffset={5}
                  onOpenAutoFocus={(e) => e.preventDefault()}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Presets</div>
                  <div className="grid grid-cols-6 gap-1">
                    {colorThemes.map((color) => (
                      <button
                        key={color.name}
                        onClick={() => handleThemeSelect(color)}
                        className="w-7 h-7 rounded border-2 border-gray-300 dark:border-gray-600 transition-all hover:scale-105 hover:ring-2 hover:ring-offset-1 hover:ring-gray-400 dark:hover:ring-gray-500"
                        style={{ backgroundColor: color.hex }}
                        title={color.name}
                      />
                    ))}
                  </div>
                  {/* Custom color picker */}
                  <div className="mt-2.5 pt-2.5 border-t border-gray-100 dark:border-gray-700">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Custom color</div>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={customColorValue}
                        onChange={(e) => handleCustomColorChange(e.target.value)}
                        className="w-8 h-8 rounded border-2 border-gray-300 dark:border-gray-600 cursor-pointer p-0.5 bg-white dark:bg-gray-700"
                        title="Pick a color"
                      />
                      <input
                        type="text"
                        value={customColorValue}
                        onChange={(e) => {
                          const v = e.target.value.trim();
                          if (/^#[0-9a-fA-F]{3,6}$/.test(v) || /^[0-9a-fA-F]{3,6}$/.test(v)) {
                            const hex = v.startsWith('#') ? v : '#' + v;
                            handleCustomColorChange(hex);
                          }
                        }}
                        className="flex-1 min-w-0 px-2 py-1.5 text-xs rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100 font-mono"
                        placeholder="#6366f1"
                        spellCheck={false}
                      />
                    </div>
                  </div>
                  {/* Border configuration (#342) */}
                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 space-y-2">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-400">Border</div>
                    <div>
                      <div className="text-[10px] text-gray-500 dark:text-gray-500 mb-1">Thickness</div>
                      <div className="flex gap-1">
                        {BORDER_WIDTH_OPTIONS.map((w) => (
                          <button
                            key={w}
                            onClick={() => handleBorderChange({ borderWidth: w })}
                            className={`flex-1 min-w-0 py-1 text-[10px] font-medium rounded transition-all ${
                              (typedData.theme?.borderWidth ?? 1.5) === w
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                            }`}
                          >
                            {w}px
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-gray-500 dark:text-gray-500 mb-1">Style</div>
                      <div className="flex gap-1">
                        {BORDER_STYLE_OPTIONS.map((s) => (
                          <button
                            key={s.name}
                            onClick={() => handleBorderChange({ borderStyle: s.name })}
                            className={`flex-1 min-w-0 py-1 text-[10px] font-medium rounded transition-all ${
                              (typedData.theme?.borderStyle ?? 'solid') === s.name
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                            }`}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                  {/* Label styling (#343) */}
                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 space-y-2">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-400">Label</div>
                    <div className="flex gap-2">
                      <div className="w-1/2 min-w-0">
                        <div className="text-[10px] text-gray-500 dark:text-gray-500 mb-1">Font size</div>
                        <select
                          value={typedData.theme?.labelFontSize ?? 13}
                          onChange={(e) => handleLabelStyleChange({ labelFontSize: Number(e.target.value) })}
                          className="w-full px-2 py-1.5 text-xs rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                        >
                          {LABEL_FONT_SIZE_OPTIONS.map((s) => (
                            <option key={s} value={s}>{s}px</option>
                          ))}
                        </select>
                      </div>
                      <div className="w-1/2 min-w-0">
                        <div className="text-[10px] text-gray-500 dark:text-gray-500 mb-1">Font family</div>
                        <select
                          value={typedData.theme?.labelFontFamily ?? 'inherit'}
                          onChange={(e) => handleLabelStyleChange({ labelFontFamily: e.target.value })}
                          className="w-full px-2 py-1.5 text-xs rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                        >
                          {LABEL_FONT_FAMILY_OPTIONS.map((f) => (
                            <option key={f.value} value={f.value}>{f.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleLabelStyleChange({ labelFontWeight: (typedData.theme?.labelFontWeight ?? 'bold') === 'bold' ? 'normal' : 'bold' })}
                        className={`flex-1 py-1 text-[10px] font-medium rounded transition-all ${
                          (typedData.theme?.labelFontWeight ?? 'bold') === 'bold'
                            ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                        }`}
                      >
                        Bold
                      </button>
                      <button
                        onClick={() => handleLabelStyleChange({ labelFontStyle: (typedData.theme?.labelFontStyle ?? 'normal') === 'italic' ? 'normal' : 'italic' })}
                        className={`flex-1 py-1 text-[10px] font-medium rounded transition-all ${
                          (typedData.theme?.labelFontStyle ?? 'normal') === 'italic'
                            ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                        }`}
                      >
                        Italic
                      </button>
                    </div>
                    <div>
                      <div className="text-[10px] text-gray-500 dark:text-gray-500 mb-1">Position</div>
                      <div className="flex gap-1">
                        {(['left', 'center', 'right'] as const).map((align) => (
                          <button
                            key={align}
                            onClick={() => handleLabelStyleChange({ labelTextAlign: align })}
                            className={`flex-1 min-w-0 py-1 text-[10px] font-medium rounded transition-all capitalize ${
                              (typedData.theme?.labelTextAlign ?? 'left') === align
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                            }`}
                          >
                            {align}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <button
                        onClick={() => handleLabelStyleChange({ labelMultiLine: !(typedData.theme?.labelMultiLine ?? false) })}
                        className={`w-full py-1 text-[10px] font-medium rounded transition-all ${
                          typedData.theme?.labelMultiLine
                            ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 ring-1 ring-indigo-500'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                        }`}
                      >
                        Multi-line {typedData.theme?.labelMultiLine ? 'on' : 'off'}
                      </button>
                    </div>
                  </div>
                  <Popover.Arrow className="fill-white dark:fill-gray-800" />
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>

            {/* Icon picker button using Popover */}
            <Popover.Root open={iconPickerOpen} onOpenChange={(open) => {
              setIconPickerOpen(open);
              if (!open) setIconSearchQuery('');
            }}>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className={
                    typedData.theme?.icon
                      ? 'relative flex h-7 w-7 shrink-0 items-center justify-center rounded border border-indigo-300 bg-indigo-100 text-indigo-700 transition-colors hover:bg-indigo-200 dark:border-indigo-500 dark:bg-indigo-900/40 dark:text-indigo-200 dark:hover:bg-indigo-900/60'
                      : 'relative flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-200 bg-slate-100 text-slate-700 transition-colors hover:bg-slate-200 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600'
                  }
                  onClick={(e) => e.stopPropagation()}
                  title={typedData.theme?.icon ? `Icon: ${typedData.theme.icon}` : "Change icon"}
                >
                  {(() => {
                    const CurrentIcon = getIconComponent();
                    return CurrentIcon ? <CurrentIcon size={12} /> : <Smile size={12} />;
                  })()}
                  {/* Active indicator dot */}
                  {typedData.theme?.icon && (
                    <span
                      className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full border border-white/80 bg-green-500 dark:border-white/80"
                    />
                  )}
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-3 w-72"
                  sideOffset={5}
                  onOpenAutoFocus={(e) => e.preventDefault()}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="space-y-2">
                    {/* Search input */}
                    <input
                      type="text"
                      placeholder="Search icons..."
                      value={iconSearchQuery}
                      onChange={(e) => setIconSearchQuery(e.target.value)}
                      className="w-full px-2 py-1.5 text-xs border border-gray-200 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                      onClick={(e) => e.stopPropagation()}
                    />

                    {/* Remove icon button */}
                    {typedData.theme?.icon && (
                      <button
                        onClick={() => handleIconSelect(null)}
                        className="w-full px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors text-left"
                      >
                        ✕ Remove icon (show initials)
                      </button>
                    )}

                    {/* Icon list - vertical scroll only, no horizontal scroll */}
                    <div className="max-h-48 overflow-y-auto overflow-x-hidden">
                      <div className="grid grid-cols-6 gap-1 w-full min-w-0">
                        {filteredIcons.map((iconOpt) => {
                          const IconComp = iconOpt.icon;
                          const isSelected = typedData.theme?.icon === iconOpt.name;
                          return (
                            <button
                              key={iconOpt.name}
                              onClick={() => handleIconSelect(iconOpt.name)}
                              className={`w-7 h-7 rounded flex items-center justify-center transition-all hover:scale-110 ${
                                isSelected 
                                  ? 'bg-indigo-500 text-white ring-2 ring-indigo-300' 
                                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                              }`}
                              title={iconOpt.name}
                            >
                              <IconComp size={14} />
                            </button>
                          );
                        })}
                      </div>
                      {filteredIcons.length === 0 && (
                        <div className="text-xs text-gray-400 dark:text-gray-500 text-center py-4">
                          No icons found
                        </div>
                      )}
                    </div>

                    {/* Category hint */}
                    <div className="text-[10px] text-gray-400 dark:text-gray-500 pt-1 border-t border-gray-100 dark:border-gray-700">
                      Search by name or category (People, Commerce, Storage, Files, Security, etc.)
                    </div>
                  </div>
                  <Popover.Arrow className="fill-white dark:fill-gray-800" />
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>

            {/* Hide node button (#481) */}
            <button
              type="button"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-200 bg-slate-100 text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-blue-900/30"
              onClick={(e) => {
                e.stopPropagation();
                typedData.onToggleVisibility?.(typedData.id, false);
              }}
              title="Hide class"
            >
              <EyeOff size={12} />
            </button>

            {/* Delete button */}
            <button
              type="button"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-200 bg-slate-100 text-slate-700 transition-colors hover:border-red-300 hover:bg-red-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-red-900/40"
              onClick={(e) => {
                e.stopPropagation();
                if (typedData.onClassDelete) typedData.onClassDelete(typedData.id, typedData.name);
              }}
              title="Delete class"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      )}
    <NodeCard
      innerRef={nodeRef}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onDoubleClick={handleDoubleClick}
      title={typedData.heatmapLabel}
      selected={selected}
      customBorderColor={customBorderColor}
      borderWidth={borderWidth}
      borderStyle={borderStyle}
      customBackground={customBackground}
      isValidDropTarget={isValidDropTarget}
      invalidDropReason={invalidDropReason}
      warning={!!(typedData.inCircularDependency && !selected)}
      heatmapTint={heatmapTint}
      style={{ cursor: 'pointer', color: customTextColor }}
    >
      <NodeHandleDot
        type="target"
        position={Position.Top}
        color={selected ? accentVar('default') : 'var(--node-text-subtle)'}
      />

      <NodeHeader
        role="default"
        customAccent={customBorderColor}
        customBackground={customHeaderBackground}
        customTextColor={customHeaderTextColor}
        textAlign={typedData.theme?.labelTextAlign ?? 'left'}
        icon={(() => {
          const IconComp = getIconComponent();
          if (IconComp) return <IconComp size={14} strokeWidth={2.5} />;
          return <span>{typedData.name.substring(0, 2).toUpperCase()}</span>;
        })()}
        title={
          <>
            <div
              style={{
                fontSize: `${typedData.theme?.labelFontSize ?? 13}px`,
                fontFamily: typedData.theme?.labelFontFamily ?? 'inherit',
                fontWeight:
                  typedData.theme?.labelFontWeight === 'bold'
                    ? 600
                    : typedData.theme?.labelFontWeight === 'normal'
                    ? 400
                    : 600,
                fontStyle: typedData.theme?.labelFontStyle ?? 'normal',
                letterSpacing: '-0.01em',
                overflow: 'hidden',
                textOverflow: typedData.theme?.labelMultiLine ? 'clip' : 'ellipsis',
                whiteSpace: typedData.theme?.labelMultiLine ? 'normal' : 'nowrap',
                wordBreak: typedData.theme?.labelMultiLine ? 'break-word' : undefined,
                textDecoration: typedData.schema?.deprecated ? 'line-through' : 'none',
                opacity: typedData.schema?.deprecated ? 0.7 : 1,
                lineHeight: 1.3,
              }}
            >
              {typedData.name}
            </div>
            {showTags && typedData.tags && typedData.tags.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '3px',
                  marginTop: '3px',
                  opacity: tagsOpacity,
                  transition: 'opacity 0.2s ease',
                }}
              >
                {typedData.tags.map((tag) => {
                  const colors = tagInlineColors(tag.tag_color);
                  return (
                    <span
                      key={tag.id}
                      style={{
                        fontSize: '9px',
                        padding: '1px 6px',
                        borderRadius: '3px',
                        background: colors.bg,
                        color: '#ffffff',
                        fontWeight: 500,
                        border: `1px solid ${colors.border}`,
                        whiteSpace: 'nowrap',
                        lineHeight: 1.4,
                      }}
                    >
                      {tag.tag_name}
                    </span>
                  );
                })}
              </div>
            )}
          </>
        }
        badges={
          <>
            {typedData.inCircularDependency && (
              <NodeBadge variant={headerWarnVariant} title="Part of a circular dependency">
                <AlertTriangle size={10} strokeWidth={2.5} />
              </NodeBadge>
            )}
            {typedData.dependencyDepthLabel != null && (
              <NodeBadge
                variant={headerInfoVariant}
                title={`Dependency depth: ${typedData.dependencyDepthLabel} degree`}
              >
                <Layers size={10} strokeWidth={2.5} />
                {typedData.dependencyDepthLabel}
              </NodeBadge>
            )}
            {typedData.impactSource && (
              <NodeBadge variant={headerWarnVariant} title="Selected for impact analysis (changing this class affects others)">
                Changed
              </NodeBadge>
            )}
            {typedData.impactAffected && (
              <NodeBadge variant={headerInfoVariant} title="Affected by the selected class change">
                Affected
              </NodeBadge>
            )}
            <NodeBadge variant={headerBadgeVariant} title={`${propCount} propert${propCount === 1 ? 'y' : 'ies'}`}>
              <List size={10} strokeWidth={2.5} />
              {propCount}
            </NodeBadge>
            {relCount > 0 && (
              <NodeBadge variant={headerInfoVariant} title={`${relCount} relationship${relCount === 1 ? '' : 's'}`}>
                <Link2 size={10} strokeWidth={2.5} />
                {relCount}
              </NodeBadge>
            )}
          </>
        }
      />

      {/* Description / drop hint */}
      {showDescription && (
        <div
          style={{
            padding: '5px 12px',
            fontSize: '11px',
            color:
              dragTarget === 'node' && !invalidDropReason
                ? 'var(--node-success)'
                : 'var(--node-text-muted)',
            lineHeight: 1.4,
            background:
              dragTarget === 'node' && !invalidDropReason
                ? 'color-mix(in srgb, var(--node-success) 10%, transparent)'
                : 'var(--node-surface-muted)',
            borderBottom: '1px solid var(--node-border-muted)',
            minHeight: '24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: dragTarget === 'node' && !invalidDropReason ? 'center' : 'flex-start',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            opacity: descriptionOpacity,
            transition: 'all 0.18s ease',
            fontStyle: typedData.description ? 'normal' : 'italic',
            fontWeight: dragTarget === 'node' && !invalidDropReason ? 500 : 400,
          }}
        >
          {dragTarget === 'node' && !invalidDropReason
            ? 'Drop here'
            : (typedData.description || 'No description')}
        </div>
      )}

      {/* Collapsed: references-only mini-list (edges + ref info preserved) */}
      {!showProperties && (() => {
        const allProps = typedData.properties || [];
        const refProps = allProps.filter((p: ClassProperty) => hasRef(p));
        if (refProps.length === 0) return null;
        return (
          <div
            style={{
              padding: '6px 0 4px 0',
              borderTop: '1px solid var(--node-border-muted)',
              background: 'var(--node-surface-muted)',
            }}
          >
            <div
              style={{
                fontSize: '10px',
                fontWeight: 600,
                color: 'var(--node-text-muted)',
                padding: '0 10px 4px 10px',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              References
            </div>
            {refProps.map((p) => (
              <div
                key={p.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto',
                  alignItems: 'center',
                  padding: '4px 10px',
                  minHeight: '24px',
                  position: 'relative',
                  gap: '8px',
                }}
              >
                <span
                  style={{
                    fontSize: '11px',
                    color: 'var(--node-text-muted)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={`${p.name} -> ${getPropertyType(p)}`}
                >
                  {p.name}
                  <span style={{ color: 'var(--node-text-subtle)', margin: '0 4px' }}>{'\u2192'}</span>
                </span>
                <NodeTypeChip label={getPropertyType(p)} dense />
                <NodeHandleDot
                  type="source"
                  position={Position.Right}
                  id={`prop-${p.id}`}
                  role="ref"
                  isConnectable={!typedData.isReadOnly}
                />
              </div>
            ))}
          </div>
        );
      })()}

      {/* Properties */}
      {showProperties && (
        <div
          style={{
            padding: 0,
            opacity: propertiesOpacity,
            transition: 'opacity 0.2s ease',
          }}
        >
          {topLevel.length > 0 || (ghostPreview && ghostPreview.parentId === null && !invalidDropReason) ? (
            <>
              {ghostPreview && ghostPreview.parentId === null && renderGhostPreviewRow('root-ghost-preview')}
              {topLevel.flatMap((prop, idx) => {
                const totalTopLevel = topLevel.length;
                const renderProperty = (
                  p: ClassProperty,
                  depth: number,
                  isLast: boolean = false
                ): React.JSX.Element[] => {
                  const container = isInlineObjectContainer(p);
                  const children = childMap.get(p.id) || [];
                  const isExpanded = expandedProperties.has(p.id);
                  const draggedOver = dragOverPropertyId === p.id;
                  const childOfDragged = isDescendantOfDraggedProperty(p.id, dragOverPropertyId);
                  const isInDropZone = draggedOver || childOfDragged;
                  const isInvalidDropZone = isInDropZone && !!invalidDropReason;
                  const isRequired = p.data?.required;
                  const parsed = parseData(p);
                  const isDeprecated = !!parsed?.deprecated;
                  const deprecationMessage =
                    typeof parsed?.deprecationMessage === 'string' ? parsed.deprecationMessage : undefined;
                  const canShowPropertyActions =
                    !typedData.isReadOnly && !!(typedData.onPropertyEdit || typedData.onPropertyDelete);
                  const showPropertyRowActions =
                    canShowPropertyActions && hoveredPropertyRowId === p.id;

                  const rowElements: React.JSX.Element[] = [];
                  rowElements.push(
                    <PropertyRow
                      key={p.id}
                      depth={depth}
                      container={container}
                      expanded={isExpanded}
                      onToggleExpanded={() => togglePropertyExpansion(p.id)}
                      name={p.name}
                      required={!!isRequired}
                      deprecated={isDeprecated}
                      deprecationMessage={deprecationMessage}
                      childCount={children.length}
                      isValidDropZone={isInDropZone && !isInvalidDropZone}
                      isInvalidDropZone={isInvalidDropZone}
                      last={isLast}
                      onMouseEnter={() => setHoveredPropertyRowId(p.id)}
                      onMouseLeave={() =>
                        setHoveredPropertyRowId((prev) => (prev === p.id ? null : prev))
                      }
                      onDragOver={
                        !typedData.isReadOnly
                          ? (e) => handlePropertyDragOver(e, p.id, container)
                          : undefined
                      }
                      onDragLeave={
                        !typedData.isReadOnly
                          ? (e) => handlePropertyDragLeave(e, p.id, container)
                          : undefined
                      }
                      onDrop={
                        container && !typedData.isReadOnly
                          ? (e) => handlePropertyDrop(e, p.id)
                          : undefined
                      }
                      right={
                        showPropertyRowActions ? (
                          <div style={{ display: 'flex', gap: '2px', justifyContent: 'flex-end' }}>
                            {typedData.onPropertyEdit && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  typedData.onPropertyEdit!(typedData.id, p);
                                }}
                                aria-label="Edit property"
                                title="Edit property"
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  cursor: 'pointer',
                                  padding: '3px',
                                  borderRadius: '3px',
                                  color: 'var(--node-text-subtle)',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  transition: 'all 0.12s ease',
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.background =
                                    'color-mix(in srgb, var(--node-accent) 14%, transparent)';
                                  e.currentTarget.style.color = 'var(--node-accent)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.background = 'transparent';
                                  e.currentTarget.style.color = 'var(--node-text-subtle)';
                                }}
                              >
                                <Edit size={11} />
                              </button>
                            )}
                            {typedData.onPropertyDelete && (
                              <button
                                type="button"
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  const confirmed = await confirmDialog({
                                    title: 'Remove Property',
                                    message: `Remove "${p.name}" from this class?`,
                                    variant: 'warning',
                                    confirmLabel: 'Remove',
                                    cancelLabel: 'Cancel',
                                  });
                                  if (confirmed) typedData.onPropertyDelete!(typedData.id, p.id);
                                }}
                                aria-label="Remove property from class"
                                title="Remove property from class"
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  cursor: 'pointer',
                                  padding: '3px',
                                  borderRadius: '3px',
                                  color: 'var(--node-text-subtle)',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  transition: 'all 0.12s ease',
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.background =
                                    'color-mix(in srgb, var(--node-danger) 14%, transparent)';
                                  e.currentTarget.style.color = 'var(--node-danger)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.background = 'transparent';
                                  e.currentTarget.style.color = 'var(--node-text-subtle)';
                                }}
                              >
                                <Trash2 size={11} />
                              </button>
                            )}
                          </div>
                        ) : (
                          <NodeTypeChip label={getPropertyType(p)} />
                        )
                      }
                    >
                      {hasRef(p) && (
                        <NodeHandleDot
                          type="source"
                          position={Position.Right}
                          id={`prop-${p.id}`}
                          role="ref"
                          isConnectable={!typedData.isReadOnly}
                        />
                      )}
                    </PropertyRow>
                  );

                  if (ghostPreview && ghostPreview.parentId === p.id && !invalidDropReason) {
                    rowElements.push(
                      renderGhostPreviewRow(
                        `${p.id}-ghost-preview`,
                        `${10 + (depth + 1) * 14}px`
                      ) as React.JSX.Element
                    );
                  }

                  if (container && isExpanded && children.length > 0) {
                    children.forEach((c, childIdx) =>
                      rowElements.push(...renderProperty(c, depth + 1, childIdx === children.length - 1))
                    );
                  }

                  return rowElements;
                };

                return renderProperty(prop, 0, idx === totalTopLevel - 1);
              })}
            </>
          ) : (
            <div
              style={{
                padding: '10px 12px',
                textAlign: 'center',
                color: 'var(--node-text-subtle)',
                fontSize: '11px',
                fontStyle: 'italic',
                background: 'var(--node-surface-muted)',
              }}
            >
              No properties
            </div>
          )}
        </div>
      )}

      {/* Bottom composition handle (allOf/anyOf/oneOf) */}
      {typedData.schema && (() => {
        const schema =
          typeof (typedData.schema as any) === 'string'
            ? JSON.parse(typedData.schema as any)
            : (typedData.schema as any);
        const hasComposition =
          (schema?.allOf && Array.isArray(schema.allOf) && schema.allOf.some((it: any) => it.$ref)) ||
          (schema?.anyOf && Array.isArray(schema.anyOf) && schema.anyOf.some((it: any) => it.$ref)) ||
          (schema?.oneOf && Array.isArray(schema.oneOf) && schema.oneOf.some((it: any) => it.$ref));

        let compRole: 'comp-all' | 'comp-any' | 'comp-one' | 'default' = 'default';
        if (schema?.allOf && schema.allOf.length > 0) compRole = 'comp-all';
        else if (schema?.anyOf && schema.anyOf.length > 0) compRole = 'comp-any';
        else if (schema?.oneOf && schema.oneOf.length > 0) compRole = 'comp-one';

        return hasComposition ? (
          <NodeHandleDot
            key="comp-bottom"
            type="source"
            position={Position.Bottom}
            id="comp-bottom"
            role={compRole}
            size={10}
            isConnectable={false}
          />
        ) : null;
      })()}
    </NodeCard>
    </div>
  );
}

// Custom comparison function for memo - always re-render when data changes
// This ensures handle positions are recalculated when properties are added/removed
const arePropsEqual = (prevProps: NodeProps, nextProps: NodeProps) => {
  // If id or selected changed, re-render
  if (prevProps.id !== nextProps.id || prevProps.selected !== nextProps.selected) {
    return false;
  }

  // Always re-render when data changes to ensure handles are repositioned
  // We do a shallow comparison first, then deep compare properties
  const prevData = prevProps.data as ClassNodeData;
  const nextData = nextProps.data as ClassNodeData;

  if (prevData === nextData) {
    return true;
  }

  // If properties array length changed, definitely re-render
  const prevProps_ = (prevData?.properties || []);
  const nextProps_ = (nextData?.properties || []);
  if (prevProps_.length !== nextProps_.length) {
    return false;
  }

  // Check if property IDs are the same
  const prevIds = prevProps_.map(p => p.id).join(',');
  const nextIds = nextProps_.map(p => p.id).join(',');
  if (prevIds !== nextIds) {
    return false;
  }

  // Check if theme changed - compare key theme properties
  const prevTheme = prevData?.theme;
  const nextTheme = nextData?.theme;
  if (prevTheme?.headerGradient !== nextTheme?.headerGradient ||
      prevTheme?.backgroundColor !== nextTheme?.backgroundColor ||
      prevTheme?.borderColor !== nextTheme?.borderColor ||
      prevTheme?.borderWidth !== nextTheme?.borderWidth ||
      prevTheme?.borderStyle !== nextTheme?.borderStyle ||
      prevTheme?.textColor !== nextTheme?.textColor ||
      prevTheme?.headerTextColor !== nextTheme?.headerTextColor ||
      prevTheme?.icon !== nextTheme?.icon ||
      prevTheme?.labelFontSize !== nextTheme?.labelFontSize ||
      prevTheme?.labelFontFamily !== nextTheme?.labelFontFamily ||
      prevTheme?.labelFontWeight !== nextTheme?.labelFontWeight ||
      prevTheme?.labelFontStyle !== nextTheme?.labelFontStyle ||
      prevTheme?.labelTextAlign !== nextTheme?.labelTextAlign ||
      prevTheme?.labelMultiLine !== nextTheme?.labelMultiLine) {
    return false;
  }

  // Check if expandedProperties changed (Set comparison)
  const prevExpanded = prevData?.expandedProperties;
  const nextExpanded = nextData?.expandedProperties;
  if (prevExpanded !== nextExpanded) {
    // If references are different, check if contents are the same
    if (!prevExpanded || !nextExpanded) {
      return false;
    }
    if (prevExpanded.size !== nextExpanded.size) {
      return false;
    }
    // Check if all items in prev are in next
    for (const item of prevExpanded) {
      if (!nextExpanded.has(item)) {
        return false;
      }
    }
  }

  // #548: Circular dependency indicator
  if (prevData?.inCircularDependency !== nextData?.inCircularDependency) {
    return false;
  }

  // #549: Dependency depth badge
  if (prevData?.dependencyDepth !== nextData?.dependencyDepth || prevData?.dependencyDepthLabel !== nextData?.dependencyDepthLabel) {
    return false;
  }

  // #550: Impact Analysis badges
  if (prevData?.impactSource !== nextData?.impactSource || prevData?.impactAffected !== nextData?.impactAffected) {
    return false;
  }

  // For other data changes, do a simple reference check
  return prevData?.name === nextData?.name &&
         prevData?.description === nextData?.description &&
         prevData?.isReadOnly === nextData?.isReadOnly;
};

export default memo(ClassNode, arePropsEqual);

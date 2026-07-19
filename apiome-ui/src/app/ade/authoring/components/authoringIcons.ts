/**
 * Icon resolution for the Authoring shell (UXE-1.2).
 *
 * Surfaces, commands and state badges name their icon as a string so those
 * modules stay free of React imports and remain unit-testable. This map is the
 * single place those names become components; an unknown name degrades to a
 * neutral glyph rather than throwing.
 */

import {
  AlertTriangle,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  Clock,
  CloudOff,
  Compass,
  Eye,
  FileText,
  FolderOpen,
  GitBranch,
  GitMerge,
  Globe,
  History,
  Layers,
  Loader2,
  Lock,
  MinusCircle,
  PenTool,
  Quote,
  RefreshCw,
  Rocket,
  Sparkles,
  Undo2,
  UserCheck,
  X,
  type LucideIcon,
} from 'lucide-react';

const AUTHORING_ICONS: Record<string, LucideIcon> = {
  BarChart3,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  // The release vocabulary names the filled tick CircleCheck; Lucide's export
  // for that glyph is CheckCircle2.
  CircleCheck: CheckCircle2,
  CircleDot,
  Clock,
  CloudOff,
  Compass,
  Eye,
  FileText,
  FolderOpen,
  GitBranch,
  GitMerge,
  Globe,
  History,
  Layers,
  // Lucide exports the spinner as Loader2; the state vocabulary names it
  // LoaderCircle, which is the same glyph under its newer name.
  LoaderCircle: Loader2,
  Lock,
  MinusCircle,
  PenTool,
  Quote,
  RefreshCw,
  Rocket,
  Sparkles,
  // Likewise TriangleAlert is the newer name for Lucide's AlertTriangle.
  TriangleAlert: AlertTriangle,
  Undo2,
  UserCheck,
  X,
};

/**
 * Resolve an icon name to a component.
 *
 * @param name - Icon name declared by a surface, command or badge.
 * @returns The matching icon, or a neutral fallback.
 */
export function resolveAuthoringIcon(name: string | undefined): LucideIcon {
  if (!name) return Circle;
  return AUTHORING_ICONS[name] ?? Circle;
}

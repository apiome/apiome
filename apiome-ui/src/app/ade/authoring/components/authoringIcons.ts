/**
 * Icon resolution for the Authoring shell (UXE-1.2).
 *
 * Surfaces, commands and state badges name their icon as a string so those
 * modules stay free of React imports and remain unit-testable. This map is the
 * single place those names become components; an unknown name degrades to a
 * neutral glyph rather than throwing.
 */

import {
  BarChart3,
  Check,
  Circle,
  CircleDot,
  CloudOff,
  Compass,
  Eye,
  FolderOpen,
  GitBranch,
  GitMerge,
  Globe,
  Layers,
  Loader2,
  Lock,
  PenTool,
  Rocket,
  type LucideIcon,
} from 'lucide-react';

const AUTHORING_ICONS: Record<string, LucideIcon> = {
  BarChart3,
  Check,
  CircleDot,
  CloudOff,
  Compass,
  Eye,
  FolderOpen,
  GitBranch,
  GitMerge,
  Globe,
  Layers,
  // Lucide exports the spinner as Loader2; the state vocabulary names it
  // LoaderCircle, which is the same glyph under its newer name.
  LoaderCircle: Loader2,
  Lock,
  PenTool,
  Rocket,
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

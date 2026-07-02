/**
 * Shared Color Themes
 *
 * 16 color palette (4x4 grid) used across the application
 * for consistent color selection in nodes, groups, and edges
 */

export interface ColorTheme {
  name: string;
  hex: string;
  headerGradient?: string;
  backgroundColor?: string;
  borderColor?: string;
  textColor?: string;
  headerTextColor?: string;
}

export const EDGE_COLOR_THEMES: ColorTheme[] = [
  { name: 'Slate', hex: '#64748b' },
  { name: 'Gray', hex: '#6b7280' },
  { name: 'Zinc', hex: '#71717a' },
  { name: 'Stone', hex: '#78716c' },
  { name: 'Red', hex: '#ef4444' },
  { name: 'Orange', hex: '#f97316' },
  { name: 'Amber', hex: '#f59e0b' },
  { name: 'Yellow', hex: '#eab308' },
  { name: 'Lime', hex: '#84cc16' },
  { name: 'Green', hex: '#22c55e' },
  { name: 'Emerald', hex: '#10b981' },
  { name: 'Teal', hex: '#14b8a6' },
  { name: 'Cyan', hex: '#06b6d4' },
  { name: 'Sky', hex: '#0ea5e9' },
  { name: 'Blue', hex: '#3b82f6' },
  { name: 'Indigo', hex: '#6366f1' },
  { name: 'Violet', hex: '#8b5cf6' },
  { name: 'Purple', hex: '#a855f7' },
  { name: 'Fuchsia', hex: '#d946ef' },
  { name: 'Pink', hex: '#ec4899' },
  { name: 'Rose', hex: '#f43f5e' },
];

// Trim to 16 colors for 4x4 grid
export const EDGE_COLORS_4X4 = EDGE_COLOR_THEMES.slice(0, 16);


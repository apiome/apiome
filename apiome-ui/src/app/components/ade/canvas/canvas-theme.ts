/**
 * Canvas design tokens + helpers for react-flow nodes.
 *
 * These are the single source of truth for how nodes look across every canvas
 * (Studio schema, Paths, Migration, Version history). Node components should
 * read colors and spacing from these helpers rather than hard-coding hexes.
 *
 * The CSS variables themselves live in `canvas.css` (light defaults) and are
 * overridden under `.dark` / `[data-theme]` selectors.
 */

export type NodeAccentRole =
  | 'default'   // Studio ClassNode / generic
  | 'group'     // Group frame
  | 'ref'       // Property-level $ref edges / handles
  | 'comp-all'  // allOf
  | 'comp-any'  // anyOf
  | 'comp-one'  // oneOf
  | 'from'      // Migration "from" side
  | 'to'        // Migration "to" side
  | 'rule'      // Migration rule node
  | 'path'      // Paths template
  | 'param'     // Path parameter
  | 'request'   // Request body
  | 'response'  // Response body (2xx default)
  | 'status-2xx'
  | 'status-3xx'
  | 'status-4xx'
  | 'status-5xx'
  | 'revision'; // Version history

/** Primary accent color for a role, as a CSS `var(...)` reference. */
export function accentVar(role: NodeAccentRole = 'default'): string {
  switch (role) {
    case 'ref': return 'var(--node-accent-ref)';
    case 'comp-all': return 'var(--node-accent-comp-all)';
    case 'comp-any': return 'var(--node-accent-comp-any)';
    case 'comp-one': return 'var(--node-accent-comp-one)';
    case 'from': return 'var(--node-accent-from)';
    case 'to': return 'var(--node-accent-to)';
    case 'rule': return 'var(--node-accent-rule)';
    case 'path': return 'var(--node-accent-path)';
    case 'param': return 'var(--node-accent-param)';
    case 'request': return 'var(--node-accent-request)';
    case 'response':
    case 'status-2xx': return 'var(--node-accent-2xx)';
    case 'status-3xx': return 'var(--node-accent-3xx)';
    case 'status-4xx': return 'var(--node-accent-4xx)';
    case 'status-5xx': return 'var(--node-accent-5xx)';
    case 'revision': return 'var(--node-accent-revision)';
    case 'group': return 'var(--node-accent-group)';
    case 'default':
    default:
      return 'var(--node-accent)';
  }
}

/** A soft tinted background suitable for icon tiles / accent chips. */
export function accentTintVar(role: NodeAccentRole = 'default'): string {
  return `color-mix(in srgb, ${accentVar(role)} 14%, transparent)`;
}

/** RGB triplet for the accent, for rgba() constructions (glows, overlays). */
export function accentRgba(role: NodeAccentRole, alpha: number): string {
  return `color-mix(in srgb, ${accentVar(role)} ${Math.round(alpha * 100)}%, transparent)`;
}

/* ---- Property-type chip role classification -------------------------------- */

export type TypeChipRole = 'ref' | 'array' | 'composition' | 'primitive' | 'object' | 'unassigned';

/**
 * Classify a display type string (e.g. "User", "string[]", "allOf(2)") into a
 * visual role for NodeTypeChip. Cheap heuristic — purely cosmetic.
 */
export function classifyTypeLabel(label: string): TypeChipRole {
  if (!label) return 'primitive';
  const lower = label.toLowerCase();
  if (lower.startsWith('(unassigned')) return 'unassigned';
  if (lower.startsWith('allof') || lower.startsWith('anyof') || lower.startsWith('oneof')) return 'composition';
  const isArray = lower.endsWith('[]') || lower.endsWith('[]?');
  const head = lower.replace(/\[\]\??$/, '');
  const primitives = new Set(['string', 'number', 'integer', 'boolean', 'null', 'any', 'unknown']);
  if (primitives.has(head.replace(/\?$/, ''))) return isArray ? 'array' : 'primitive';
  if (head === 'object') return 'object';
  if (isArray) return 'array';
  return 'ref';
}

/* ---- Dimensions / spacing -------------------------------------------------- */

export const CANVAS_TOKENS = {
  radius: 8,
  headerStripeHeight: 3,
  handleSize: 8,
  handleSizeLarge: 10,
  propertyRowHeight: 26,
  nodeMinWidth: 280,
  nodeMaxWidth: 440,
} as const;

/* ---- Color manipulation (for existing custom-color picker integration) ---- */

export function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const clean = hex.replace(/^#/, '');
  const m = clean.match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i)
    || clean.match(/^([0-9a-f])([0-9a-f])([0-9a-f])$/i);
  if (!m) return null;
  const expand = (x: string) => (x.length === 1 ? x + x : x);
  return {
    r: parseInt(expand(m[1]), 16),
    g: parseInt(expand(m[2]), 16),
    b: parseInt(expand(m[3]), 16),
  };
}

export function rgbToHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b]
    .map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, '0'))
    .join('');
}

export function normalizeHex(hex: string, fallback = '#6366f1'): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return fallback;
  return rgbToHex(rgb.r, rgb.g, rgb.b);
}

export function relLuminance(hex: string): number {
  const rgb = hexToRgb(normalizeHex(hex));
  if (!rgb) return 0;
  const [r, g, b] = [rgb.r, rgb.g, rgb.b].map((c) => c / 255);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

export function readableTextOn(hex: string): string {
  return relLuminance(hex) > 0.6 ? '#0f172a' : '#ffffff';
}

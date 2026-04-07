/**
 * Resolve canvas group frame colors: presets use theme names; DB and custom picks use #RGB / #RRGGBB (#97).
 */

export type GroupColorPreset = {
  name: string;
  hex: string;
  bg: string;
  border: string;
  text: string;
};

/** Parse and normalize a CSS hex color, or null if invalid. */
export function parseCssHexColor(input: string | undefined | null): string | null {
  if (input == null || typeof input !== 'string') return null;
  const s = input.trim();
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (!m) return null;
  const cap = m[1];
  if (cap.length === 3) {
    const [r, g, b] = cap.split('').map((c) => c + c);
    return `#${r}${g}${b}`.toLowerCase();
  }
  return `#${cap.toLowerCase()}`;
}

export function resolveGroupFrameHex(
  color: string | undefined,
  presets: readonly GroupColorPreset[]
): { hex: string; preset: GroupColorPreset | null } {
  if (!presets.length) {
    return { hex: '#6366f1', preset: null };
  }
  if (!color) {
    return { hex: presets[0].hex, preset: presets[0] };
  }
  const byName = presets.find((p) => p.name === color);
  if (byName) {
    return { hex: byName.hex, preset: byName };
  }
  const hex = parseCssHexColor(color);
  if (hex) {
    return { hex, preset: null };
  }
  return { hex: presets[0].hex, preset: presets[0] };
}

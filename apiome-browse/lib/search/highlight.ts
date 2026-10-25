/**
 * Split text into plain and highlighted segments for the needles a query carries.
 *
 * Pure so the components stay a thin `<mark>` wrapper and the matching rules (case-insensitive,
 * longest needle wins, no overlapping marks) are unit-tested once.
 */

export interface HighlightSegment {
  text: string;
  hit: boolean;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Segment `text` by `needles`.
 *
 * @param text The text to mark up.
 * @param needles The strings to highlight; empty strings are ignored. Longer needles are tried
 *   first so `"payment intent"` is one mark rather than two.
 * @returns Segments in order; concatenating their `text` reproduces the input exactly.
 */
export function highlightSegments(text: string, needles: readonly string[]): HighlightSegment[] {
  const clean = [...new Set(needles.map((n) => n.trim()).filter(Boolean))].sort(
    (a, b) => b.length - a.length
  );
  if (!text || clean.length === 0) return text ? [{ text, hit: false }] : [];
  const pattern = new RegExp(`(${clean.map(escapeRegExp).join('|')})`, 'gi');
  const out: HighlightSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) out.push({ text: text.slice(last, index), hit: false });
    out.push({ text: match[0], hit: true });
    last = index + match[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false });
  return out;
}

/**
 * Trim a long snippet around the first needle so the match is visible, keeping ~`radius`
 * characters either side and adding ellipses where text was cut.
 */
export function excerptAround(text: string, needles: readonly string[], radius = 110): string {
  if (!text) return '';
  if (text.length <= radius * 2) return text;
  const lower = text.toLowerCase();
  let at = -1;
  for (const needle of needles) {
    const n = needle.trim().toLowerCase();
    if (!n) continue;
    const idx = lower.indexOf(n);
    if (idx >= 0 && (at < 0 || idx < at)) at = idx;
  }
  if (at < 0) return `${text.slice(0, radius * 2).trimEnd()}…`;
  const start = Math.max(0, at - radius);
  const end = Math.min(text.length, at + radius);
  return `${start > 0 ? '…' : ''}${text.slice(start, end).trim()}${end < text.length ? '…' : ''}`;
}

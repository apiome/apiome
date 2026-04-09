/**
 * Returns a browser-normalized CSS color string if the input is accepted, else null.
 */
export function tryParseCssColor(input: string): string | null {
  const s = input.trim();
  if (!s) return null;
  if (typeof document === 'undefined') {
    if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(s)) return s;
    return s;
  }
  const el = document.createElement('div');
  el.style.color = '';
  el.style.color = s;
  const out = el.style.color;
  return out || null;
}

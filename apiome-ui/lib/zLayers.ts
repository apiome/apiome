/**
 * The stacking scale (SUX-1.1, apiome#6748), as the names a class or a stylesheet spends.
 *
 * `src/app/globals.css` declares one `--z-<name>` token and one `z-<name>` utility per entry,
 * in this order, lowest first; `tests/z-index-scale.test.tsx` fails if the two drift. The list
 * lives in code as well as in CSS so `cn()` can teach `tailwind-merge` that `z-modal` and
 * `z-[1234]` are the same property — otherwise a caller's override would be kept *beside*
 * the primitive's own layer and the winner would depend on stylesheet order.
 */
export const Z_LAYERS = [
  'base',
  'raised',
  'sticky',
  'chrome',
  'floating',
  'overlay',
  'modal',
  'popover',
  'toast',
  'alert',
] as const;

/** One step of the stacking scale. */
export type ZLayer = (typeof Z_LAYERS)[number];

/**
 * The CSS expression for a layer, for the few places that set `z-index` from script
 * (an inline `style`, or a third-party component that only takes one).
 *
 * @param layer The step of the scale.
 * @returns `var(--z-<layer>)`, which resolves against the token in `globals.css`.
 */
export function zLayer(layer: ZLayer): string {
  return `var(--z-${layer})`;
}

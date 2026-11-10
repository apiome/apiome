import { type ClassValue, clsx } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';
import { Z_LAYERS } from './zLayers';

/**
 * `tailwind-merge`, taught the custom utilities that share a property with a built-in one.
 *
 * The `z-<layer>` stacking utilities (SUX-1.1) join Tailwind's `z-*` group, so
 * `cn('z-modal', 'z-[20]')` keeps only `z-[20]` — the last one wins, as with any other
 * conflicting pair.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      z: [{ z: [...Z_LAYERS] }],
    },
  },
});

/**
 * Utility function to merge Tailwind CSS classes with clsx
 * This handles conditional classes and merges conflicting Tailwind classes correctly
 *
 * @param inputs Class names, conditional class maps and arrays, as `clsx` accepts them.
 * @returns One class string, with conflicting Tailwind utilities resolved last-wins.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

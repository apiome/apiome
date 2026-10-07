/** How the `Mod` placeholder is shown — the product binds it to Ctrl on Windows/Linux and ⌘ on macOS. */
export const MOD_LABEL = 'Ctrl / ⌘';

/**
 * Split a chord string into the labels of its keys.
 *
 * @param keys - A chord such as `Mod+Shift+K`; a literal plus key is written `Plus`.
 * @returns The key labels in order, with `Mod` and `Plus` expanded and blanks dropped.
 */
export function splitChord(keys: string): string[] {
  return keys
    .split('+')
    .map((key) => key.trim())
    .filter(Boolean)
    .map((key) => (key === 'Mod' ? MOD_LABEL : key === 'Plus' ? '+' : key));
}

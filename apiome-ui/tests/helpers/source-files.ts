/**
 * Recursive source-file listing for the source-text guard suites.
 *
 * Several suites pin a *deletion* — a retired module, a retired token — by scanning the
 * package's text, because nothing renders the deleted thing any more and no behavioural
 * suite could notice it coming back. They all need the same walk.
 */

import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/** `.ts` and `.tsx` — the default set of extensions {@link sourceFiles} returns. */
export const TYPESCRIPT_EXTENSIONS = /\.(ts|tsx)$/;

/**
 * Every file under a directory, recursively, whose name matches `extensions`.
 *
 * `node_modules` and dot-directories (`.next`, `.turbo`, …) are skipped: they hold
 * generated or third-party output, not this package's source.
 *
 * @param dir Absolute directory to walk.
 * @param extensions Pattern tested against each file's base name. Defaults to
 *   {@link TYPESCRIPT_EXTENSIONS}.
 * @returns Absolute paths of every matching file beneath `dir`, in directory order.
 */
export function sourceFiles(dir: string, extensions: RegExp = TYPESCRIPT_EXTENSIONS): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry.startsWith('.')) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      found.push(...sourceFiles(path, extensions));
    } else if (extensions.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

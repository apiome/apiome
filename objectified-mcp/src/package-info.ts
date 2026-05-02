import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

let cachedVersion: string | undefined;

export function packageVersion(): string {
  if (cachedVersion) return cachedVersion;
  const base = dirname(fileURLToPath(import.meta.url));
  const pkgPath = join(base, '..', 'package.json');
  const raw = readFileSync(pkgPath, 'utf8');
  cachedVersion = (JSON.parse(raw) as { version: string }).version;
  return cachedVersion;
}

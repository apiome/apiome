/**
 * The OpenAPI test-drive viewer's vendor bundles, read from `node_modules` — MFX-44.2 (#4368).
 *
 * `swagger-ui-dist`, `redoc` and (MFX-44.4) `@asyncapi/react-component` are build-time dependencies
 * whose standalone bundles the viewer pages load from `/test-drive/vendor/…`. They are found by walking up from the server's working directory
 * to the nearest `node_modules` holding them — `apiome-ui/` in development (hoisted to the monorepo
 * root), the standalone output in production, where `outputFileTracingIncludes` copies them.
 */

import { promises as fs } from 'node:fs';
import path from 'node:path';

import asyncApiReactPackage from '@asyncapi/react-component/package.json';
import redocPackage from 'redoc/package.json';
import swaggerUiPackage from 'swagger-ui-dist/package.json';

import { TEST_DRIVE_VENDOR_ASSETS } from './openapi-viewer';

/**
 * Find a file under the nearest `node_modules` that has it, walking up from `start`.
 *
 * @param relative The path under `node_modules`.
 * @param start Where to start (the server's working directory by default).
 * @returns The absolute path, or null when no ancestor has it.
 */
export async function findInNodeModules(relative: string, start = process.cwd()): Promise<string | null> {
  let dir = path.resolve(start);
  for (;;) {
    const candidate = path.join(dir, 'node_modules', relative);
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      const parent = path.dirname(dir);
      if (parent === dir) return null;
      dir = parent;
    }
  }
}

/**
 * Read one allow-listed vendor asset.
 *
 * @param name The file name requested (`swagger-ui-bundle.js`, …).
 * @param start Where the `node_modules` search starts (tests).
 * @returns Its bytes and content type, or null for a name not on the list or a missing file.
 */
export async function readTestDriveVendorAsset(
  name: string,
  start?: string,
): Promise<{ bytes: Buffer; contentType: string } | null> {
  if (!Object.prototype.hasOwnProperty.call(TEST_DRIVE_VENDOR_ASSETS, name)) return null;
  const asset = TEST_DRIVE_VENDOR_ASSETS[name];
  const file = await findInNodeModules(asset.file, start);
  if (!file) return null;
  return { bytes: await fs.readFile(file), contentType: asset.contentType };
}

/**
 * The bundles' cache key: their package versions, joined (`5.34.0-2.5.4-3.2.2`).
 *
 * @returns The key.
 */
export function testDriveVendorVersion(): string {
  return `${swaggerUiPackage.version}-${redocPackage.version}-${asyncApiReactPackage.version}`;
}

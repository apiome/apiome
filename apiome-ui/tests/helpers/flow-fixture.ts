/**
 * Docs-screenshot dumps of a React Flow view, rendered by the REAL React Flow under jsdom (MFX-45.3/45.4).
 *
 * A node with a known `width` / `height` and `handles` draws without measuring, so jsdom can render the
 * diagram; what jsdom lacks is SVG layout (React Flow sizes an edge label's background from `getBBox`),
 * and the fixture page lacks React Flow's own stylesheet (the app imports it with the component). These
 * helpers fill both gaps.
 */

import * as fs from 'fs';
import * as path from 'path';

/** Give SVG elements a `getBBox` sized roughly like monospace text, once. */
export function polyfillSvgBBox(): void {
  const proto = window.SVGElement.prototype as unknown as { getBBox?: () => DOMRect };
  proto.getBBox ??= function getBBox(this: SVGElement) {
    return { x: 0, y: 0, width: (this.textContent ?? '').length * 6.6, height: 14 } as DOMRect;
  };
}

/**
 * React Flow's stylesheet, read from node_modules directly (under Jest the module resolver maps `.css`
 * to a stub).
 */
export function reactFlowCss(): string {
  const file = [path.join(__dirname, '..', '..', 'node_modules'), path.join(__dirname, '..', '..', '..', 'node_modules')]
    .map((root) => path.join(root, '@xyflow', 'react', 'dist', 'style.css'))
    .find((candidate) => fs.existsSync(candidate));
  if (!file) throw new Error('@xyflow/react/dist/style.css not found');
  return fs.readFileSync(file, 'utf-8');
}

/**
 * Write a fixture under `e2e/fixtures/<dir>/<file>`: the markup, then React Flow's stylesheet (after the
 * markup, so the mount's first child is the visible diagram the screenshot waits for).
 */
export function writeFlowFixture(dir: string, file: string, markup: string): void {
  const out = path.join(__dirname, '..', '..', 'e2e', 'fixtures', dir);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, file), `${markup}<style>${reactFlowCss()}</style>\n`);
}

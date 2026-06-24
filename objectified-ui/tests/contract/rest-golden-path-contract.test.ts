/**
 * Golden-path UI <-> REST contract: the UI side (RC1-3.1, #3616).
 *
 * The UI's editor flows reach the REST spine through thin proxy routes under `src/app/api`, which
 * build their upstream URL from `${REST_API_BASE_URL}/...` (REST_API_BASE_URL already ends in `/v1`).
 * This test reads the single source-of-truth contract at `scripts/golden_path/contract.json`, takes
 * the operations the UI owns (`ui: true`), and asserts the proxy routes still call a matching upstream
 * path shape. If a proxy is deleted or its upstream path is renamed, the contract goes red — the
 * mirror of the REST-side check in `objectified-rest/tests/test_golden_path_contract.py`.
 *
 * Matching is structural: each path segment that is a parameter (REST `{x}` or UI `${x}`) is collapsed
 * to `*`, so the two sides' differing parameter names are irrelevant.
 */

import * as fs from 'fs';
import * as path from 'path';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const CONTRACT_PATH = path.join(REPO_ROOT, 'scripts', 'golden_path', 'contract.json');
const API_ROOT = path.resolve(__dirname, '..', '..', 'src', 'app', 'api');

interface ContractOp {
  step: string;
  method: string;
  path: string;
  ui: boolean;
}

/** Collapse a `/`-delimited path to its segment "shape", replacing parameter segments with `*`. */
function shape(p: string): string {
  return p
    .split('?')[0]
    .split('/')
    .filter((seg) => seg.length > 0)
    .map((seg) => (seg.includes('${') || (seg.startsWith('{') && seg.endsWith('}')) ? '*' : seg))
    .join('/');
}

/** REST contract path -> UI-relative shape (REST_API_BASE_URL already carries the `/v1` prefix). */
function restPathToUiShape(restPath: string): string {
  const withoutV1 = restPath.replace(/^\/v1\b/, '');
  return shape(withoutV1);
}

/** Recursively collect every file under `dir`. */
function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

/** All upstream `${REST_API_BASE_URL}/...` template paths referenced by the UI proxy routes, as shapes. */
function collectUiUpstreamShapes(): Set<string> {
  const shapes = new Set<string>();
  const files = walk(API_ROOT).filter((f) => f.endsWith('.ts') || f.endsWith('.tsx'));
  // Capture the path portion of a `${REST_API_BASE_URL}<path>` template literal, up to the first
  // backtick, quote, or template-literal control character that ends the path.
  const re = /\$\{REST_API_BASE_URL\}(\/[^`"'\s]*)/g;
  for (const file of files) {
    const text = fs.readFileSync(file, 'utf8');
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      shapes.add(shape(m[1]));
    }
  }
  return shapes;
}

const contract: { operations: ContractOp[] } = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8'));
const uiOps = contract.operations.filter((op) => op.ui);

describe('golden-path UI <-> REST contract (UI side)', () => {
  it('the shared contract file exists and defines UI-owned operations', () => {
    expect(fs.existsSync(CONTRACT_PATH)).toBe(true);
    expect(uiOps.length).toBeGreaterThan(0);
  });

  it('the UI exposes proxy routes for the golden-path endpoints', () => {
    expect(fs.existsSync(API_ROOT)).toBe(true);
  });

  it.each(uiOps.map((op) => [`${op.method} ${op.path}`, op] as const))(
    'UI proxies %s',
    (_label, op) => {
      const expected = restPathToUiShape(op.path);
      const upstreamShapes = collectUiUpstreamShapes();
      expect(Array.from(upstreamShapes)).toContain(expected);
    },
  );
});

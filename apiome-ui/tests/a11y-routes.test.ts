/**
 * The axe gate's route ledger — HIVE-10.2 (#5338), `e2e/a11y/routes.ts`.
 *
 * "axe gate in CI for all redesigned routes" only means something if "all" is checked. This suite
 * holds the ledger against the visual-parity harness's own record of the redesign: every page
 * mockup that harness compares, or leaves uncovered for any reason other than `awaiting-redesign`,
 * must have an entry — and every entry must point at something that exists.
 */

import fs from 'node:fs';
import path from 'node:path';

import { A11Y_ROUTES, A11Y_SPEC_FILES } from '../e2e/a11y/routes';
import { PARITY_ROUTES, UNCOVERED_MOCKUPS } from '../e2e/visual/routes';

const E2E = path.join(__dirname, '..', 'e2e');

/** Every redesigned page mockup, per the visual-parity ledger. */
const REDESIGNED = [
  ...PARITY_ROUTES.map((route) => route.mockup),
  ...UNCOVERED_MOCKUPS.filter((entry) => entry.reason !== 'awaiting-redesign').map((entry) => entry.mockup),
];

describe('a11y route ledger', () => {
  it('names every redesigned page mockup', () => {
    const covered = new Set(A11Y_ROUTES.map((route) => route.mockup));
    expect(REDESIGNED.filter((mockup) => !covered.has(mockup))).toEqual([]);
  });

  it('uses each id once', () => {
    const ids = A11Y_ROUTES.map((route) => route.id);
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([]);
  });

  it.each(A11Y_ROUTES.map((route) => [route.id, route] as const))('%s points at something that exists', (_id, route) => {
    const subject = route.subject;
    if (subject.kind === 'fixtures') {
      const dir = path.join(E2E, 'fixtures', subject.dir);
      const files = subject.files ?? fs.readdirSync(dir).filter((file) => file.endsWith('.html'));
      expect(files.length).toBeGreaterThan(0);
      for (const file of files) expect(fs.existsSync(path.join(dir, file))).toBe(true);
    } else if (subject.kind === 'route') {
      expect(subject.path).toMatch(/^\//);
    } else {
      expect(fs.existsSync(path.join(E2E, subject.file))).toBe(true);
    }
  });

  it.each(A11Y_SPEC_FILES.map((file) => [file]))('%s runs axe at the shared WCAG 2.2 tags', (file) => {
    const source = fs.readFileSync(path.join(E2E, file), 'utf8');
    expect(source).toContain("from './support/a11y'");
    expect(source).toMatch(/\bWCAG_TAGS\b/);
    // No private tag list that could fall behind the shared one again.
    expect(source).not.toMatch(/const WCAG_TAGS\s*=/);
  });

  it('runs the gate in the three gate themes', () => {
    const helper = fs.readFileSync(path.join(E2E, 'support', 'a11y.ts'), 'utf8');
    expect(helper).toMatch(/GATE_THEMES[^=]*=\s*\[null, 'dark', 'high-contrast'\]/);
    expect(helper).toMatch(/WCAG_TAGS = \[[^\]]*'wcag22aa'/);
  });
});

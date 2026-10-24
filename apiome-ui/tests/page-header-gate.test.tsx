/**
 * The page gates (HIVE-13.2, #5615): header action cap, one banner, no "Coming soon" buttons.
 *
 * DESIGN.md §1.2 and §5.3 give a `PageHeader` one primary action, at most two secondaries and
 * an optional ⋯ menu; §5.4 gives a page one banner under its header, with several statuses
 * folded into a `StatusStrip`; §10 forbids controls that lead nowhere. Before this suite
 * nothing enforced any of it — which is how Versions reached six header controls (a project
 * select among them) and three stacked banners. The rules themselves are
 * `tests/helpers/page-gates.ts`; this suite holds them to four things:
 *
 *   1. **Live renders** of `PageHeader`, `Button`, `Alert` and `StatusStrip`, so the rules
 *      recognise what the primitives draw today (a `Button` is known by its base classes;
 *      if those change, the first test fails instead of the count going quietly to zero).
 *   2. **The negative fixtures** in `e2e/fixtures/hive-page-gates/` — Versions before
 *      HIVE-11.2 (banner stack) and before HIVE-11.3 (crowded header). The gate must fail
 *      both; if it ever passes them, it has stopped measuring.
 *   3. **Every committed fixture dump** under `e2e/fixtures/` — the rendered pages the a11y,
 *      parity and docs suites already mount — with a small allow-list for pages that are not
 *      released. An entry fails as `stale` once its page passes, so the list only shrinks.
 *   4. **The source**, for the one rule a dump can miss: no `<select>` or `Select` inside a
 *      `PageHeader`'s `actions` / `primaryAction`, on any route, dumped or not.
 *
 * The source half of "no dead controls" — a disabled button carries its reason — is a ratchet
 * in `tests/copy-voice-gate.test.ts`. CI: both run in the unit-test step of
 * `.github/workflows/apiome-ui.yml`.
 */

import React from 'react';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';
import ts from 'typescript';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { StatusStrip } from '@/app/components/ui/StatusStrip';

import {
  BUTTON_MARK,
  PAGE_GATE_LIMITS,
  countHeaderActions,
  isButtonPrimitive,
  isPrimaryButton,
  leadingBanners,
  pageGateViolations,
  type PageGateViolation,
} from './helpers/page-gates';

const ROOT = join(__dirname, '..');
const FIXTURES = join(ROOT, 'e2e', 'fixtures');

/** The negative fixtures — frozen history the gate must fail. */
const NEGATIVE_DIR = 'hive-page-gates';

/**
 * Fixture folders that are history rather than today's pages. `hive-first-row` holds the
 * HIVE-13.3 Catalog copies from before and after its quiet pass; nothing re-dumps them.
 */
const HISTORY_DIRS: ReadonlySet<string> = new Set([NEGATIVE_DIR, 'hive-first-row']);

/**
 * Fixture folders allowed to break a rule, each with its reason.
 *
 * Only pages that are not released (`lib/feature-release.ts`) belong here: RC6 runs the gates
 * over the pages it releases (`docs/RC6_OOE.md`), and a held-back page joins them when its
 * feature does. An entry whose pages all pass fails as stale — delete it.
 */
const PAGE_GATE_EXCEPTIONS: Readonly<
  Record<string, { rules: readonly PageGateViolation['rule'][]; reason: string }>
> = {
  'hive-primitive-detail': {
    rules: ['header-actions'],
    reason:
      'Primitives is held back (feature-release `primitives`): Edit, Export and Deprecate are three ' +
      'secondaries. Move one into a ⋯ menu when the page is released.',
  },
};

/** Every `.html` under a directory, recursively. */
function htmlFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return entry.endsWith('.html') ? [path] : [];
  });
}

/** Parse a fixture dump into a document. */
function parse(path: string): Document {
  return new DOMParser().parseFromString(readFileSync(path, 'utf8'), 'text/html');
}

/** The top-level fixture folder a path sits in. */
function folderOf(path: string): string {
  return relative(FIXTURES, path).split(sep)[0];
}

/** Every fixture dump that shows today's pages, parsed once. */
const dumps = htmlFiles(FIXTURES)
  .filter((path) => !HISTORY_DIRS.has(folderOf(path)))
  .map((path) => ({ rel: relative(FIXTURES, path), folder: folderOf(path), doc: parse(path) }));

// =========================================================================================
// 1. The rules, against what the primitives render today
// =========================================================================================

describe('the page-gate rules recognise the primitives', () => {
  const VARIANTS = [
    'primary',
    'default',
    'accent',
    'outline',
    'soft',
    'ghost',
    'danger',
    'danger-soft',
    'honey',
    'link',
    'secondary',
    'destructive',
    'success',
  ] as const;

  it.each(VARIANTS)('knows a %s Button by its base classes', (variant) => {
    const { getByRole } = render(<Button variant={variant}>Go</Button>);
    const button = getByRole('button');
    expect(button).toHaveClass(BUTTON_MARK);
    expect(isButtonPrimitive(button)).toBe(true);
    expect(isPrimaryButton(button)).toBe(variant === 'primary' || variant === 'default');
  });

  it('counts an unstyled Button as primary — its default variant is the ink fill', () => {
    const { getByRole } = render(<Button>Go</Button>);
    expect(isPrimaryButton(getByRole('button'))).toBe(true);
  });

  it('knows a Button asChild link, and ignores a plain button', () => {
    const { getByRole } = render(
      <>
        <Button asChild variant="outline">
          <a href="/edit">Edit</a>
        </Button>
        <button type="button">Plain</button>
      </>
    );
    expect(isButtonPrimitive(getByRole('link'))).toBe(true);
    expect(isButtonPrimitive(getByRole('button', { name: 'Plain' }))).toBe(false);
  });

  it('holds the DESIGN.md limits', () => {
    expect(PAGE_GATE_LIMITS).toEqual({ primary: 1, secondary: 2, overflow: 1, banners: 1 });
  });
});

describe('the header action cap', () => {
  /** Render a header and return its counts and violations. */
  function judge(element: React.ReactElement) {
    const { container } = render(element);
    const header = container.querySelector('[data-testid="page-header"]')!;
    return { count: countHeaderActions(header), violations: pageGateViolations(container) };
  }

  it('passes one primary, two secondaries and a ⋯ menu', () => {
    const { count, violations } = judge(
      <PageHeader
        title="Projects"
        actions={
          <>
            <Button variant="outline">Import</Button>
            <Button variant="ghost">Compare</Button>
          </>
        }
        overflow={{ items: [{ id: 'merge', label: 'Merge branches', onSelect: () => {} }] }}
        primaryAction={<Button variant="primary">New project</Button>}
      />
    );
    expect(count).toEqual({ primary: 1, secondary: 2, overflow: 1, selects: [] });
    expect(violations).toEqual([]);
  });

  it('fails a second primary', () => {
    const { violations } = judge(
      <PageHeader title="Projects" actions={<Button>New</Button>} primaryAction={<Button>Create</Button>} />
    );
    expect(violations).toEqual([{ rule: 'header-actions', detail: '2 primary buttons (limit 1)' }]);
  });

  it('fails a third secondary', () => {
    const { violations } = judge(
      <PageHeader
        title="Versions"
        actions={
          <>
            <Button variant="outline">Import</Button>
            <Button variant="outline">Compare</Button>
            <Button variant="outline">Merge</Button>
          </>
        }
      />
    );
    expect(violations).toEqual([{ rule: 'header-actions', detail: '3 secondary buttons (limit 2)' }]);
  });

  it('fails a select in the actions slot — native or combobox', () => {
    const { violations } = judge(
      <PageHeader
        title="Versions"
        actions={
          <>
            <select aria-label="Environment">
              <option>prod</option>
            </select>
            <button type="button" role="combobox" aria-expanded="false" aria-controls="x" aria-label="Select project">
              Payments API
            </button>
          </>
        }
      />
    );
    expect(violations.map((violation) => violation.rule)).toEqual(['header-select', 'header-select']);
    expect(violations[1].detail).toContain('Select project');
  });

  it('does not count read-outs that are not Buttons, nor an icon inside a link', () => {
    const { count } = judge(
      <PageHeader
        title="Payments API"
        actions={
          <>
            <button type="button" className="cid-orb">
              84 Quality
            </button>
            <Button asChild variant="outline">
              <a href="/code">
                <span aria-hidden>{'</>'}</span>View code
              </a>
            </Button>
          </>
        }
      />
    );
    expect(count).toEqual({ primary: 0, secondary: 1, overflow: 0, selects: [] });
  });
});

describe('the banner rule', () => {
  /** Render a page with a header and the given body. */
  function judge(body: React.ReactNode) {
    const { container } = render(
      <Page>
        <PageHeader title="Versions" />
        <PageBody>{body}</PageBody>
      </Page>
    );
    const header = container.querySelector('[data-testid="page-header"]')!;
    return { banners: leadingBanners(header), violations: pageGateViolations(container) };
  }

  const STRIP_ITEMS = [
    { id: 'compat', tone: 'ok' as const, label: 'Compatible', title: 'Compatible', body: 'v2 is compatible.' },
    { id: 'sunset', tone: 'warn' as const, label: 'Sunset', title: 'Sunset', body: 'v1 retires soon.' },
  ];

  it('passes one banner, then content', () => {
    const { banners, violations } = judge(
      <>
        <Alert variant="warning">Deprecated</Alert>
        <div>Table</div>
      </>
    );
    expect(banners).toHaveLength(1);
    expect(violations).toEqual([]);
  });

  it('passes a StatusStrip with several statuses — it is one banner', () => {
    const { banners, violations } = judge(
      <>
        <StatusStrip items={STRIP_ITEMS} aria-label="Project status" />
        <div>Table</div>
      </>
    );
    expect(banners).toHaveLength(1);
    expect(violations).toEqual([]);
  });

  it('fails two banners in a row', () => {
    const { violations } = judge(
      <>
        <Alert variant="info">What’s new</Alert>
        <Alert variant="warning">Deprecated</Alert>
        <div>Table</div>
      </>
    );
    expect(violations).toEqual([
      { rule: 'banners', detail: '2 banners under the header (limit 1) — use a StatusStrip' },
    ]);
  });

  it('looks through a wrapper that only stacks banners', () => {
    const { banners } = judge(
      <div className="ver-banners">
        <div role="status">Compatible</div>
        <div role="status">What’s new</div>
        <div role="status">Deprecated</div>
      </div>
    );
    expect(banners).toHaveLength(3);
  });

  it('ignores an alert further down the page, and screen-reader-only live regions', () => {
    const { banners, violations } = judge(
      <>
        <span role="status" className="sr-only">
          Saved
        </span>
        <Alert variant="info">Heads up</Alert>
        <form>
          <Alert variant="error">Name is required</Alert>
        </form>
      </>
    );
    expect(banners).toHaveLength(1);
    expect(violations).toEqual([]);
  });
});

describe('the no-"Coming soon"-button rule', () => {
  it('fails a button whose text says Coming soon', () => {
    const { container } = render(
      <button type="button" disabled>
        gRPC <span>Coming soon</span>
      </button>
    );
    expect(pageGateViolations(container)).toEqual([
      { rule: 'coming-soon-button', detail: '“Coming soon” inside a button: “gRPC Coming soon”' },
    ]);
  });

  it('passes the label on a plain element, and as a disabled button’s title', () => {
    const { container } = render(
      <>
        <div aria-disabled="true">
          gRPC <span>Coming soon</span>
        </div>
        <button type="button" disabled title="Coming soon">
          gRPC
        </button>
      </>
    );
    expect(pageGateViolations(container)).toEqual([]);
  });
});

// =========================================================================================
// 2. The negative fixtures
// =========================================================================================

describe('the negative fixtures (e2e/fixtures/hive-page-gates/)', () => {
  /** The rules a negative fixture breaks. */
  function rulesBroken(name: string): string[] {
    return [...new Set(pageGateViolations(parse(join(FIXTURES, NEGATIVE_DIR, name))).map((v) => v.rule))].sort();
  }

  it('fails Versions before HIVE-11.2 on the banner stack and the crowded header', () => {
    expect(rulesBroken('versions-pre-11-2.html')).toEqual(['banners', 'header-actions', 'header-select']);
  });

  it('fails Versions before HIVE-11.3 on the crowded header alone', () => {
    const doc = parse(join(FIXTURES, NEGATIVE_DIR, 'versions-pre-11-3.html'));
    expect(countHeaderActions(doc.querySelector('[data-testid="page-header"]')!)).toEqual({
      primary: 1,
      secondary: 3,
      overflow: 0,
      selects: ['Select project'],
    });
    expect(rulesBroken('versions-pre-11-3.html')).toEqual(['header-actions', 'header-select']);
  });

  it('passes Versions as it is today', () => {
    expect(pageGateViolations(parse(join(FIXTURES, 'hive-versions', 'timeline.html')))).toEqual([]);
  });
});

// =========================================================================================
// 3. Every committed fixture dump
// =========================================================================================

describe('every page the suites dump passes the gates', () => {
  /** Violations per fixture file, excluding allow-listed rules. */
  function failures(): string[] {
    return dumps.flatMap(({ rel, folder, doc }) => {
      const allowed = PAGE_GATE_EXCEPTIONS[folder]?.rules ?? [];
      return pageGateViolations(doc)
        .filter((violation) => !allowed.includes(violation.rule))
        .map((violation) => `${rel}: ${violation.rule} — ${violation.detail}`);
    });
  }

  it('finds the pages it is meant to judge (the scan is not silently empty)', () => {
    const headers = dumps.reduce(
      (total, { doc }) => total + doc.querySelectorAll('[data-testid="page-header"]').length,
      0
    );
    expect(dumps.length).toBeGreaterThan(200);
    expect(headers).toBeGreaterThan(100);
  });

  it('breaks no rule outside the allow-list', () => {
    expect(failures()).toEqual([]);
  });

  it.each(Object.entries(PAGE_GATE_EXCEPTIONS))(
    'allow-lists %s only while it still needs it (no stale entry)',
    (folder, { rules, reason }) => {
      expect(reason.trim().length).toBeGreaterThan(0);
      const pages = dumps.filter((dump) => dump.folder === folder);
      expect(pages.length).toBeGreaterThan(0);
      const broken = new Set(pages.flatMap(({ doc }) => pageGateViolations(doc).map((v) => v.rule)));
      for (const rule of rules) expect({ folder, rule, stillBroken: broken.has(rule) }).toEqual({
        folder,
        rule,
        stillBroken: true,
      });
    }
  );
});

// =========================================================================================
// 4. The source: no select in a header's actions, dumped or not
// =========================================================================================

describe('no PageHeader puts a select in its actions (source)', () => {
  /** Every `.tsx` under `src/`, outside route handlers. */
  function sources(directory: string = join(ROOT, 'src')): string[] {
    return readdirSync(directory).flatMap((entry) => {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) return entry === 'api' ? [] : sources(path);
      return entry.endsWith('.tsx') ? [path] : [];
    });
  }

  /** `path:line` of every `select` / `Select` element inside a header's action props. */
  function selectsInHeaderActions(): { headers: number; found: string[] } {
    let headers = 0;
    const found: string[] = [];
    for (const path of sources()) {
      const text = readFileSync(path, 'utf8');
      if (!text.includes('PageHeader')) continue;
      const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const inspect = (node: ts.Node, inActions: boolean) => {
        if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && inActions) {
          const tag = node.tagName.getText(file);
          if (tag === 'select' || tag === 'Select') {
            found.push(`${relative(ROOT, path)}:${file.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
          }
        }
        if (
          ts.isJsxAttribute(node) &&
          ['actions', 'primaryAction'].includes(node.name.getText(file)) &&
          ts.isJsxOpeningLikeElement(node.parent.parent) &&
          node.parent.parent.tagName.getText(file) === 'PageHeader'
        ) {
          headers += 1;
          ts.forEachChild(node, (child) => inspect(child, true));
          return;
        }
        ts.forEachChild(node, (child) => inspect(child, inActions));
      };
      inspect(file, false);
    }
    return { headers, found };
  }

  it('finds header action slots to inspect, and no select in any of them', () => {
    const { headers, found } = selectsInHeaderActions();
    expect(headers).toBeGreaterThan(30);
    expect(found).toEqual([]);
  });
});

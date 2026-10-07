/**
 * The copy gate — HIVE-10.4 (#5340), `docs/mockups/DESIGN.md` §10 "Content & voice".
 *
 * "Titles are nouns ('Projects'), buttons are verbs ('New project'), descriptions answer 'what
 * is this for?' in ≤ 14 words. Avoid 'Manage', 'Configure' as titles. Errors: what happened +
 * what to do."
 *
 * The rules below read every string in `src/` (see `tests/helpers/copy-scan.ts`) and fail on:
 *
 *   1. **generic copy** — "No records found", "No data", "Something went wrong", "An error
 *      occurred", "Unknown error", "not wired"…;
 *   2. **errors without a next step** — a complete "Failed to … / Couldn't … / Unable to …" literal
 *      that says what happened but not what to do, and an `ErrorState` / `ErrorBanner` with no
 *      retry or action;
 *   3. **state titles** that are not sentence-case nouns, end in "." or "!", or say
 *      Manage / Configure / Management / Configuration;
 *   4. **state and page descriptions** longer than 14 words;
 *   5. **loading copy** that names nothing ("Loading…") or spells the ellipsis as "...";
 *   6. **hand-rolled empty states** — a "No … yet / found / available / match" written straight
 *      into markup instead of the honeycomb `EmptyState`, and the retired indigo gradient tile.
 *
 * Two things the pass could only reduce are held by exact ratchets that may only go down: error
 * prefixes a server detail is appended to (`'Failed to load: ' + reason`), and raw
 * `x instanceof Error ? x.message` passthroughs whose server text the gate cannot read.
 *
 * The per-route review this gate stands behind is `apiome-ui/docs/HIVE_COPY_AUDIT.md`.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { SRC_ROOT, UI_ROOT, scanCopy, sourceFiles, type CopyLocation } from './helpers/copy-scan';

const scan = scanCopy();
const where = (copy: CopyLocation & { text?: string }) => `${copy.file}:${copy.line}${copy.text ? ` — ${copy.text}` : ''}`;

/** Copy that says nothing a reader can act on. */
const BANNED =
  /\b(no records found|no data|no results|no items|nothing to display|something went wrong|an (?:unexpected )?error occurred|unknown error|not wired)\b/i;

/** The opening of an error that says what failed. */
const FAILURE = /^(Failed to|Could not|Couldn't|Couldn’t|Unable to)\b/;

/** Words that name what to do next. */
const NEXT_STEP =
  /\b(try again|retry|refresh|reload|check|sign in|ask|contact|choose|pick|select|open|re-?run|wait|start|create|add|copy it|use|enter|reconnect)\b/i;

/** Words a sentence-case title may still capitalise: product names, acronyms, proper nouns. */
const PROPER = new Set([
  'API', 'APIs', 'MCP', 'SDK', 'SDKs', 'OpenAPI', 'AsyncAPI', 'GraphQL', 'GitHub', 'GitLab', 'Bitbucket',
  'Git', 'SSO', 'URL', 'URLs', 'JSON', 'YAML', 'CSV', 'REST', 'CI', 'ID', 'IDs', 'Apiome', 'Agent', 'Access',
  'Claude', 'Desktop', 'Studio', 'Swagger', 'Postman', 'Protobuf', 'gRPC', 'SOAP', 'WSDL', 'OData', 'Avro',
  'TOTP', 'OAuth', 'SAML', 'OIDC', 'IP', 'SQL', 'HTTP', 'RPS', 'Recommended', 'Spectral', 'Free', 'AI',
]);

/** One reviewed exception: why this copy may break a rule. */
interface Allowed {
  file: string;
  text: RegExp;
  reason: string;
}

/** Hand-written "No …" text that is not an empty state (a select option, a sentence fragment). */
const ALLOWED_HANDROLLED: Allowed[] = [
  {
    file: 'src/app/ade/database/components/DatabaseHeader.tsx',
    text: /^No (projects in this workspace|versions in this project yet)$/,
    reason: 'a row inside a Radix Select viewport; a boxed empty state cannot sit in a listbox',
  },
  {
    file: 'src/app/ade/migration/components/MigrationHeader.tsx',
    text: /^No (projects in this workspace|versions in this project yet)$/,
    reason: 'a row inside a Radix Select viewport; a boxed empty state cannot sit in a listbox',
  },
  {
    file: 'src/app/components/ade/dashboard/VersionMockCell.tsx',
    text: /^No requests yet$/,
    reason: 'the quiet label that stands in for a sparkline in every version row (HIVE-6.2 mockup)',
  },
  {
    file: 'src/app/components/ade/catalog/CatalogStatsRow.tsx',
    text: /^No formats yet$/,
    reason: 'a stat tile footnote in place of the format badge, not a panel-level empty state',
  },
  {
    file: 'src/app/design-system/mcp/page.tsx',
    text: /^No (history|discovery history|tool calls) yet$/,
    reason: 'gallery captions naming the specimen below; the specimen itself is the EmptyState',
  },
];

/** Titles that are deliberately not nouns, or name a proper noun the casing rule cannot know. */
const ALLOWED_TITLES: Allowed[] = [
  {
    file: 'src/app/design-system/page-header/page.tsx',
    text: /^Contoso Health/,
    reason: 'gallery specimen: a long title naming a fictional organisation, to show wrapping',
  },
];

/** Failure text that is not a complete message: the sentence continues after inline markup. */
const ALLOWED_FAILURES: Allowed[] = [
  {
    file: 'src/app/components/ade/dashboard/catalog/CatalogLintPanel.tsx',
    text: /^Could not locate$/,
    reason: 'continues after the inline path: “… in the source — showing the document head.”',
  },
];

/** Raw `instanceof Error ? x.message` passthroughs when this gate landed; may only go down. */
const RAW_MESSAGE_PASSTHROUGH_BASELINE = 484;

/** "Failed to …: " prefixes followed by a server detail when this gate landed; may only go down. */
const FAILURE_PREFIX_BASELINE = 62;

const allowed = (list: Allowed[], copy: CopyLocation & { text: string }) =>
  list.some((entry) => copy.file.endsWith(entry.file) && entry.text.test(copy.text));

/** A failure literal that is a prefix: a detail is appended after it. */
const isPrefix = (text: string) => /[:(]\s*$/.test(text);

describe('generic copy', () => {
  it('uses none of the phrases that say nothing a reader can act on', () => {
    const hits = [...scan.literals, ...scan.jsxText].filter((copy) => BANNED.test(copy.text)).map(where);
    expect(hits).toEqual([]);
  });

  it('never spells an ellipsis as three dots', () => {
    const hits = [...scan.literals, ...scan.jsxText].filter((copy) => /[A-Za-z]\.\.\.(\s|$)/.test(copy.text)).map(where);
    expect(hits).toEqual([]);
  });
});

describe('errors say what happened and what to do', () => {
  it('gives every complete failure message a next step', () => {
    // A failure used as a *title* states what happened; its state's retry or action button is the
    // next step, so titles (and headings) are exempt here and held to the title rules instead.
    const titleTexts = new Set(scan.stateCopy.filter((copy) => /title$/i.test(copy.prop)).map((copy) => copy.text));
    const hits = [...scan.literals, ...scan.jsxText]
      .filter((copy) => !('partial' in copy && copy.partial) && FAILURE.test(copy.text) && !isPrefix(copy.text))
      .filter((copy) => !titleTexts.has(copy.text) && !('role' in copy && copy.role === 'title'))
      .filter((copy) => !('ancestors' in copy && /^h[1-6]$/.test(copy.ancestors[0] ?? '')))
      .filter((copy) => !allowed(ALLOWED_FAILURES, copy))
      .filter((copy) => !NEXT_STEP.test(copy.text) && !copy.text.includes('—'))
      .map(where);
    expect(hits).toEqual([]);
  });

  it('gives every ErrorState and ErrorBanner a retry or an action', () => {
    const hits = scan.stateSites
      .filter((site) => site.component === 'ErrorState' || site.component === 'ErrorBanner')
      .filter((site) => !site.props.includes('onRetry') && !site.props.includes('action'))
      .map(where);
    expect(hits).toEqual([]);
  });

  it('holds failure prefixes (a server detail follows) at the locked baseline', () => {
    const prefixes = scan.literals.filter((copy) => FAILURE.test(copy.text) && (copy.partial || isPrefix(copy.text)));
    expect(prefixes.length).toBe(FAILURE_PREFIX_BASELINE);
  });

  it('holds raw error-message passthroughs at the locked baseline', () => {
    const pattern = /instanceof Error\s*(?:&&\s*\w+(?:\.\w+)*\s*)?\?\s*\w+(?:\.\w+)*\.message\b/g;
    const count = sourceFiles().reduce((total, file) => total + (readFileSync(file, 'utf8').match(pattern) ?? []).length, 0);
    expect(count).toBe(RAW_MESSAGE_PASSTHROUGH_BASELINE);
  });
});

describe('state and page titles are sentence-case nouns', () => {
  const titles = scan.stateCopy.filter((copy) => /title$/i.test(copy.prop));

  it('reads at least the copy it should', () => {
    expect(titles.length).toBeGreaterThan(150);
  });

  it('ends with no full stop or exclamation mark', () => {
    expect(titles.filter((copy) => /[.!]$/.test(copy.text.trim())).map(where)).toEqual([]);
  });

  it('is sentence case (product names and acronyms excepted)', () => {
    const shouting = titles.filter((copy) => {
      if (allowed(ALLOWED_TITLES, copy)) return false;
      const words = copy.text.trim().split(/\s+/).slice(1);
      return words.some((word) => {
        const bare = word.replace(/^[“"‘'(]+|[”"’'),:;?]+$/g, '');
        return /^[A-Z][a-z]/.test(bare) && !PROPER.has(bare);
      });
    });
    expect(shouting.map(where)).toEqual([]);
  });

  it('never titles a page or state "Manage …", "Configure …", "… Management" or "… Configuration"', () => {
    const headingText = scan.jsxText.filter((copy) => /^h[1-3]$/.test(copy.ancestors[0] ?? ''));
    const hits = [...titles, ...headingText].filter((copy) =>
      /^(Manage|Configure)\b|\b(Management|Configuration)\b/.test(copy.text),
    );
    expect(hits.map(where)).toEqual([]);
  });
});

describe('descriptions answer the question in ≤ 14 words', () => {
  it('keeps every state and page description to 14 words', () => {
    const long = scan.stateCopy
      .filter((copy) => copy.prop === 'description')
      .filter((copy) => copy.text.trim().split(/\s+/).length > 14)
      .map((copy) => `${where(copy)} (${copy.text.trim().split(/\s+/).length} words)`);
    expect(long).toEqual([]);
  });
});

describe('loading copy names what is loading', () => {
  it('never shows a bare "Loading…" from a call site', () => {
    const bare = scan.stateCopy
      .filter((copy) => copy.component === 'LoadingState' && copy.prop === 'message')
      .filter((copy) => /^Loading\s*(…|\.\.\.)?$/.test(copy.text.trim()));
    expect(bare.map(where)).toEqual([]);
  });
});

describe('empty states use the honeycomb art', () => {
  it('writes no "No … yet / found / available / match" straight into markup', () => {
    const handRolled = scan.jsxText
      .filter((copy) => /^No [\w\s'’,-]+? (yet|found|available|match(es)?)[.!]?$/.test(copy.text))
      .filter((copy) => !copy.ancestors.some((tag) => /^(EmptyState|GatedState|ErrorState)$/.test(tag)))
      .filter((copy) => !allowed(ALLOWED_HANDROLLED, copy))
      .map(where);
    expect(handRolled).toEqual([]);
  });

  it('has retired the indigo-to-purple gradient tile', () => {
    // className strings are skipped by the prose scan, so read the components' markup directly.
    // (`.ts` palettes such as the catalog's avatar gradients are data, not the tile.)
    const tiles: string[] = [];
    for (const file of sourceFiles().filter((path) => path.endsWith('.tsx'))) {
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((line, index) => {
          if (/\bfrom-indigo-\d+\b[^'"`]*\bto-purple-\d+\b/.test(line)) tiles.push(`${file.slice(UI_ROOT.length + 1)}:${index + 1}`);
        });
    }
    expect(tiles).toEqual([]);
  });

  it('keeps every allow-list entry live (a stale exception must be deleted)', () => {
    const texts = [...scan.jsxText, ...scan.stateCopy, ...scan.literals];
    for (const entry of [...ALLOWED_HANDROLLED, ...ALLOWED_TITLES, ...ALLOWED_FAILURES]) {
      expect(texts.some((copy) => copy.file.endsWith(entry.file) && entry.text.test(copy.text))).toBe(true);
      expect(entry.reason.length).toBeGreaterThan(15);
    }
  });
});

it('scans the source it means to', () => {
  expect(SRC_ROOT).toBe(join(UI_ROOT, 'src'));
});

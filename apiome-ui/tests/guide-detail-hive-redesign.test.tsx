/**
 * The style-guide detail redesign, rendered (HIVE-5.7, #5310).
 *
 * `guide-detail-model.test.ts` holds the derivations, `guide-detail-css.test.ts` holds the
 * declarations, and the three `guide-editor-*.test.tsx` suites hold the REST contract this
 * ticket did not change. This holds what the redesign *is*, against a mocked `global.fetch`
 * returning the `{success, data}` envelopes the proxies really answer with — the ticket's
 * four acceptance criteria and the mockup's **Keeps (1:1)** list:
 *
 *   1. **Monaco follows the active theme** — asserted where a jsdom suite honestly can: the
 *      editor asks for the Hive theme id and defines it before it mounts.
 *      `monaco-hive-theme.test.ts` pins what that theme *is* in all nine palettes.
 *   2. **Severity per rule and the default baseline are both visible.**
 *   3. **Dry-run results map back to editor markers**, asserted on the markers the tab
 *      really sets, and on the finding rows that scroll the editor to them.
 *   4. **Unsaved changes survive tab switches and warn on navigation** — the failure the
 *      ticket's problem statement names.
 *
 * Plus the redesign's own additions: the "Modified only" chip with its count, the grouped
 * catalog's foot, and the not-found state.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

// ---------------------------------------------------------------------------------------
// Monaco double
// ---------------------------------------------------------------------------------------

/** Every `setModelMarkers` call the tab made, by owner. */
let markerCalls: { owner: string; markers: { message: string; severity: number }[] }[] = [];

/** Every theme id `defineTheme` was asked to define. */
let definedThemes: string[] = [];

/** Lines the editor was asked to scroll to. */
let revealedLines: number[] = [];

jest.mock('monaco-yaml', () => ({ configureMonacoYaml: jest.fn() }));

jest.mock('@monaco-editor/react', () => {
  const ReactLocal = jest.requireActual('react') as typeof import('react');

  /** Props the tab passes that this double has to honour. */
  interface EditorProps {
    value?: string;
    theme?: string;
    onChange?: (value: string) => void;
    onMount?: (editor: unknown, monaco: unknown) => void;
    beforeMount?: (monaco: unknown) => void;
  }

  /**
   * A textarea standing in for Monaco.
   *
   * It records the three things this suite asks about the real editor: which theme it was
   * asked for, which markers it was given, and which line it was scrolled to.
   */
  function MockEditor({ value, theme, onChange, onMount, beforeMount }: EditorProps) {
    ReactLocal.useEffect(() => {
      const monaco = {
        editor: {
          createModel: (text: string, _lang: string, uri: { toString: () => string }) => ({
            getValue: () => text,
            uri,
            dispose: jest.fn(),
          }),
          setModelMarkers: (
            _model: unknown,
            owner: string,
            markers: { message: string; severity: number }[]
          ) => {
            markerCalls.push({ owner, markers });
          },
          defineTheme: (name: string) => definedThemes.push(name),
          setTheme: jest.fn(),
          Uri: { parse: (s: string) => ({ toString: () => s }) },
        },
        Uri: { parse: (s: string) => ({ toString: () => s }) },
      };
      beforeMount?.(monaco);
      const editor = {
        getModel: () => ({
          getValue: () => value ?? '',
          uri: { toString: () => 'inmemory://model/custom-rules.yaml' },
          dispose: jest.fn(),
        }),
        setModel: jest.fn(),
        revealLineInCenter: (line: number) => revealedLines.push(line),
        setPosition: jest.fn(),
        focus: jest.fn(),
        getAction: () => ({ run: jest.fn() }),
      };
      onMount?.(editor, monaco);
      // Mount-only: the real editor is created once and then driven through its model.
    }, []);

    return ReactLocal.createElement('textarea', {
      'aria-label': 'Custom rules YAML',
      'data-theme-id': theme,
      value: value ?? '',
      onChange: (event: { target: { value: string } }) => onChange?.(event.target.value),
    });
  }

  return { __esModule: true, default: MockEditor };
});

const mockConfirm = jest.fn<Promise<boolean>, [unknown]>(() => Promise.resolve(true));
const mockPush = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({
    confirm: (options: unknown) => mockConfirm(options),
    alert: jest.fn(),
  }),
}));

import GuideEditorClient from '../src/app/ade/dashboard/style-guides/[guideId]/GuideEditorClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

const GUIDE_ID = 'g-acme';

const RULES = [
  {
    ruleId: 'path-kebab-case',
    pack: 'openapi',
    category: 'naming',
    defaultSeverity: 'warning',
    rationale: 'Path segments should be lowercase kebab-case so URLs read consistently.',
    docsAnchor: 'path-kebab-case',
    enabled: true,
    severity: 'warning',
  },
  {
    ruleId: 'schema-names-pascal-case',
    pack: 'openapi',
    category: 'naming',
    defaultSeverity: 'info',
    rationale: 'Component schema names become type names in most generators.',
    docsAnchor: 'schema-names-pascal-case',
    enabled: false,
    severity: 'info',
  },
  {
    ruleId: 'info-contact',
    pack: 'common',
    category: 'documentation',
    defaultSeverity: 'warning',
    rationale: 'Consumers need someone to reach when a contract breaks.',
    docsAnchor: 'info-contact',
    // A stored override: default warning, this guide says error.
    enabled: true,
    severity: 'error',
  },
];

const CUSTOM_YAML = [
  'rules:',
  '  operation-summary-max-length:',
  '    description: Summaries stay under 60 characters.',
  '    severity: warning',
  '  refund-idempotency-key:',
  '    description: POST /refunds must declare an Idempotency-Key header.',
  '    severity: error',
  '',
].join('\n');

const FINDINGS = [
  {
    id: 'f-1',
    path: 'paths./refunds.post.parameters',
    category: 'custom',
    rule: 'refund-idempotency-key',
    severity: 'error',
    message: 'POST /refunds must declare an Idempotency-Key header parameter.',
  },
  {
    id: 'f-2',
    path: 'paths./payouts.post.summary',
    category: 'custom',
    rule: 'operation-summary-max-length',
    severity: 'warning',
    message: 'Summaries stay under 60 characters.',
  },
];

// ---------------------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------------------

let calls: { url: string; method: string; body: unknown }[] = [];
let isAdmin = true;
let guideSource: 'builtin' | 'custom' = 'custom';
let rulesFound = true;
let ruleErrors: Record<string, string> = {};

function jsonResponse(payload: unknown) {
  return Promise.resolve({ status: 200, json: () => Promise.resolve(payload) } as Response);
}

/**
 * The rules payload, merged the way the REST layer merges it.
 *
 * @param rules The rule rows.
 * @returns The view.
 */
function rulesView(rules: typeof RULES) {
  return {
    guideId: GUIDE_ID,
    guideName: 'Acme REST',
    source: guideSource,
    rules,
    count: rules.length,
    enabledCount: rules.filter((rule) => rule.enabled).length,
    docsPage: 'apiome-docs/docs/build/lint-rules.md',
  };
}

function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(init.body as string) : null;
    calls.push({ url, method, body });

    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: { is_admin: isAdmin, permissions: [] } });
    }
    if (url.includes('/api/projects')) {
      return jsonResponse({ success: true, projects: [{ id: 'p-1', name: 'Payments API' }] });
    }
    if (url.includes('/api/versions?')) {
      return jsonResponse({
        success: true,
        versions: [{ id: 'v-1', version_id: 'v2.4.0', name: 'draft' }],
      });
    }
    if (url.includes(`${GUIDE_ID}/custom-rules/preview`)) {
      return jsonResponse({
        success: true,
        data: {
          projectId: 'p-1',
          versionRecordId: 'v-1',
          versionId: 'v2.4.0',
          count: FINDINGS.length,
          findings: FINDINGS,
          ruleErrors,
        },
      });
    }
    if (url.includes(`${GUIDE_ID}/custom-rules`) && method === 'PUT') {
      return jsonResponse({
        success: true,
        data: {
          guideId: GUIDE_ID,
          guideName: 'Acme REST',
          source: guideSource,
          yaml: (body as { yaml: string }).yaml,
          ruleCount: 2,
        },
      });
    }
    if (url.includes(`${GUIDE_ID}/custom-rules`)) {
      return jsonResponse({
        success: true,
        data: {
          guideId: GUIDE_ID,
          guideName: 'Acme REST',
          source: guideSource,
          yaml: CUSTOM_YAML,
          ruleCount: 2,
        },
      });
    }
    if (url.includes(`${GUIDE_ID}/rules`) && method === 'PUT') {
      const put = (body as { rules: typeof RULES }).rules;
      const byId = new Map(put.map((rule) => [rule.ruleId, rule]));
      return jsonResponse({
        success: true,
        data: rulesView(
          RULES.map((rule) => ({
            ...rule,
            enabled: byId.get(rule.ruleId)?.enabled ?? rule.enabled,
            severity: byId.get(rule.ruleId)?.severity ?? rule.severity,
          }))
        ),
      });
    }
    if (url.includes(`${GUIDE_ID}/rules`)) {
      return rulesFound
        ? jsonResponse({ success: true, data: rulesView(RULES) })
        : jsonResponse({ success: true, data: null });
    }
    if (url.includes(`${GUIDE_ID}/policy`)) {
      return jsonResponse({ success: true, data: null });
    }
    return jsonResponse({ success: false, error: 'Unexpected request' });
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
}

beforeEach(() => {
  calls = [];
  markerCalls = [];
  definedThemes = [];
  revealedLines = [];
  isAdmin = true;
  guideSource = 'custom';
  rulesFound = true;
  ruleErrors = {};
  mockConfirm.mockClear();
  mockConfirm.mockResolvedValue(true);
  mockPush.mockClear();
  mockFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
});

/** Render the page and wait for the catalog to land. */
async function renderPage() {
  render(<GuideEditorClient guideId={GUIDE_ID} />);
  await screen.findByText('path-kebab-case');
}

/** Render the page and open the custom-rules tab. */
async function openCustomRules() {
  await renderPage();
  fireEvent.click(screen.getByTestId('guide-tab-custom'));
  await screen.findByLabelText('Custom rules YAML');
}

// ---------------------------------------------------------------------------------------
// 1. The header
// ---------------------------------------------------------------------------------------

describe('the page header', () => {
  it('keeps the back arrow, the guide name, the live count and the three tabs', async () => {
    await renderPage();

    expect(screen.getByRole('heading', { name: 'Acme REST', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Back to style guides')).toBeInTheDocument();
    expect(screen.getByTestId('guide-enabled-count')).toHaveTextContent('2 of 3 rules enabled');
    expect(
      screen.getByText('Tailor which built-in rules apply and how severely they score.')
    ).toBeInTheDocument();

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Rule catalog3',
      'Custom rules',
      'Policy',
    ]);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
  });

  it('counts the custom rules on their tab once they have been loaded', async () => {
    await openCustomRules();
    expect(screen.getByTestId('guide-tab-custom')).toHaveTextContent('2');
  });

  it('marks the built-in guide, and the trail ends on the guide', async () => {
    guideSource = 'builtin';
    await renderPage();

    expect(screen.getByText('Built-in')).toBeInTheDocument();
    const trail = screen.getByTestId('page-breadcrumb');
    expect(within(trail).getByText('Style guides')).toBeInTheDocument();
    expect(within(trail).getByText('Acme REST')).toBeInTheDocument();
  });

  it('draws the not-found state when the guide is gone', async () => {
    rulesFound = false;
    render(<GuideEditorClient guideId={GUIDE_ID} />);

    expect(await screen.findByTestId('guide-not-found')).toBeInTheDocument();
    expect(screen.getByText('Style guide not found.')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('guide-not-found-back'));
    expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/style-guides');
  });
});

// ---------------------------------------------------------------------------------------
// 2. The rule catalog — the second acceptance criterion
// ---------------------------------------------------------------------------------------

describe('the rule catalog', () => {
  it('shows both severities: the guide’s in the select, the registry’s in the pill', async () => {
    await renderPage();

    // `info-contact` is a stored override — default warning, this guide scores it error.
    const row = screen.getByText('info-contact').closest('li') as HTMLElement;
    expect(within(row).getByText('default: warning')).toBeInTheDocument();
    expect(within(row).getByLabelText('Severity for info-contact')).toHaveValue('error');
  });

  it('groups by category, each with its own on-count, and counts the foot', async () => {
    await renderPage();

    const naming = screen.getByRole('region', { name: 'naming rules' });
    expect(within(naming).getByText('1 of 2 on')).toBeInTheDocument();
    expect(within(naming).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByTestId('rule-catalog-foot')).toHaveTextContent(
      'Showing 3 of 3 rules · 2 categories'
    );
  });

  it('leaves a switched-off rule’s severity select inert', async () => {
    await renderPage();
    expect(screen.getByLabelText('Severity for schema-names-pascal-case')).toBeDisabled();
  });

  it('filters to what has been modified, and says how many that is', async () => {
    await renderPage();
    const chip = screen.getByTestId('rule-catalog-modified-chip');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    expect(chip).toHaveTextContent('0');

    fireEvent.click(screen.getByLabelText('Enable schema-names-pascal-case'));
    expect(chip).toHaveTextContent('1');

    fireEvent.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('schema-names-pascal-case')).toBeInTheDocument();
    expect(screen.queryByText('path-kebab-case')).toBeNull();
  });

  it('says so rather than claiming an empty search when nothing is modified', async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId('rule-catalog-modified-chip'));
    expect(screen.getByText('No rules have been modified.')).toBeInTheDocument();
  });

  it('raises the save bar with a live count, and saves the whole set', async () => {
    await renderPage();
    expect(screen.queryByTestId('rule-catalog-save-bar')).toBeNull();

    fireEvent.click(screen.getByLabelText('Enable schema-names-pascal-case'));
    const bar = screen.getByTestId('rule-catalog-save-bar');
    expect(bar).toHaveTextContent('1 unsaved rule change');
    expect(screen.getByTestId('guide-enabled-count')).toHaveTextContent('3 of 3 rules enabled');

    fireEvent.click(screen.getByTestId('rule-catalog-save-bar-save'));

    await waitFor(() => expect(screen.queryByTestId('rule-catalog-save-bar')).toBeNull());
    const put = calls.find((call) => call.method === 'PUT');
    expect((put!.body as { rules: unknown[] }).rules).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------------------
// 3. Custom rules — the first and third acceptance criteria
// ---------------------------------------------------------------------------------------

describe('the custom-rules editor', () => {
  it('asks for the Hive theme and defines it before the editor mounts', async () => {
    await openCustomRules();

    expect(definedThemes).toContain('hive');
    expect(screen.getByLabelText('Custom rules YAML')).toHaveAttribute('data-theme-id', 'hive');
  });

  it('maps a dry run onto editor markers, on the rules that produced them', async () => {
    await openCustomRules();
    await waitFor(() => expect(screen.getByLabelText('Preview version')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('custom-rules-run'));
    await screen.findByText('refund-idempotency-key');

    const preview = markerCalls
      .filter((call) => call.owner === 'apiome-custom-rules-preview')
      .pop();
    expect(preview!.markers).toHaveLength(2);
    // Monaco's `MarkerSeverity`: 8 is Error, 4 is Warning.
    expect(preview!.markers.map((marker) => marker.severity).sort()).toEqual([4, 8]);
    expect(preview!.markers[0].message).toContain('paths./refunds.post.parameters');
  });

  it('scrolls the editor to the rule a finding names', async () => {
    await openCustomRules();
    await waitFor(() => expect(screen.getByLabelText('Preview version')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('custom-rules-run'));
    fireEvent.click(await screen.findByTestId('custom-rules-finding-f-1'));

    // Line 5 of the fixture is `  refund-idempotency-key:`.
    expect(revealedLines).toContain(5);
  });

  it('reports rules that could not run at all, and marks them as errors', async () => {
    ruleErrors = { 'operation-summary-max-length': 'functionOptions.max must be a number' };
    await openCustomRules();
    await waitFor(() => expect(screen.getByLabelText('Preview version')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('custom-rules-run'));

    expect(await screen.findByTestId('custom-rules-aborted')).toHaveTextContent(
      'functionOptions.max must be a number'
    );
    const preview = markerCalls
      .filter((call) => call.owner === 'apiome-custom-rules-preview')
      .pop();
    expect(preview!.markers).toHaveLength(3);
  });

  it('reports what the last run cost, beside the button that ran it', async () => {
    await openCustomRules();
    await waitFor(() => expect(screen.getByLabelText('Preview version')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('custom-rules-run'));
    expect(await screen.findByTestId('custom-rules-run-meta')).toHaveTextContent('Payments API');
  });

  it('says how many problems the document has, in the status line', async () => {
    await openCustomRules();
    expect(screen.getByTestId('custom-rules-status')).toHaveTextContent('No problems');

    await waitFor(() => expect(screen.getByLabelText('Preview version')).not.toBeDisabled());
    fireEvent.click(screen.getByTestId('custom-rules-run'));

    await waitFor(() =>
      expect(screen.getByTestId('custom-rules-status')).toHaveTextContent('2 problems')
    );
  });
});

// ---------------------------------------------------------------------------------------
// 4. Unsaved work — the fourth acceptance criterion
// ---------------------------------------------------------------------------------------

describe('unsaved changes', () => {
  it('keeps a catalog edit across a tab switch', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Enable schema-names-pascal-case'));

    fireEvent.click(screen.getByTestId('guide-tab-custom'));
    await screen.findByLabelText('Custom rules YAML');
    fireEvent.click(screen.getByTestId('guide-tab-catalog'));

    expect(screen.getByTestId('rule-catalog-save-bar')).toHaveTextContent('1 unsaved rule change');
    expect(screen.getByLabelText('Enable schema-names-pascal-case')).toBeChecked();
  });

  it('keeps a YAML edit across a tab switch, without re-reading it', async () => {
    await openCustomRules();
    fireEvent.change(screen.getByLabelText('Custom rules YAML'), {
      target: { value: 'rules: {}\n# edited\n' },
    });

    fireEvent.click(screen.getByTestId('guide-tab-catalog'));
    fireEvent.click(screen.getByTestId('guide-tab-custom'));

    expect(screen.getByLabelText('Custom rules YAML')).toHaveValue('rules: {}\n# edited\n');
    expect(screen.getByTestId('custom-rules-save-bar')).toBeInTheDocument();
    expect(calls.filter((call) => call.url.includes('/custom-rules')).length).toBe(1);
  });

  it('warns before leaving, naming both drafts, and stays when declined', async () => {
    mockConfirm.mockResolvedValue(false);
    await openCustomRules();

    fireEvent.change(screen.getByLabelText('Custom rules YAML'), {
      target: { value: 'rules: {}\n' },
    });
    fireEvent.click(screen.getByTestId('guide-tab-catalog'));
    fireEvent.click(screen.getByLabelText('Enable schema-names-pascal-case'));

    fireEvent.click(screen.getByLabelText('Back to style guides'));

    await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    expect(mockConfirm.mock.calls[0][0]).toMatchObject({
      title: 'Discard unsaved changes?',
      message:
        'You have unsaved 1 rule change and edits to the custom rules. ' +
        'Leaving this page discards them.',
      confirmLabel: 'Discard and leave',
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('leaves without asking when nothing is unsaved', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Back to style guides'));

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/style-guides'));
    expect(mockConfirm).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------------------
// 5. Read-only, and what it costs nobody
// ---------------------------------------------------------------------------------------

describe('the read-only treatment', () => {
  it('explains the built-in guide on each surface in its own words', async () => {
    guideSource = 'builtin';
    await renderPage();
    expect(screen.getByTestId('guide-readonly-rules')).toHaveTextContent(
      /read-only\. Duplicate it from the Style Guides list to customize its rules/
    );

    fireEvent.click(screen.getByTestId('guide-tab-custom'));
    await screen.findByLabelText('Custom rules YAML');
    expect(screen.getByTestId('guide-readonly-custom-rules')).toHaveTextContent(
      /Duplicate it from the Style Guides list to author custom rules/
    );
  });

  it('explains what a member may still do', async () => {
    isAdmin = false;
    await renderPage();
    expect(screen.getByTestId('guide-readonly-rules')).toHaveTextContent(
      'Only tenant administrators can change style guide rules. You can browse the catalog.'
    );
    expect(screen.getByLabelText('Enable path-kebab-case')).toBeDisabled();

    fireEvent.click(screen.getByTestId('guide-tab-custom'));
    await screen.findByLabelText('Custom rules YAML');
    // A member may still dry-run the rules they cannot edit, which is what the notice says.
    expect(screen.getByTestId('guide-readonly-custom-rules')).toHaveTextContent(
      'You can preview violations.'
    );
    expect(screen.getByTestId('custom-rules-run')).toBeInTheDocument();
    expect(screen.queryByTestId('custom-rules-format')).toBeNull();
  });

  it('costs an unopened tab nothing', async () => {
    await renderPage();
    expect(calls.some((call) => call.url.includes('/custom-rules'))).toBe(false);
    expect(calls.some((call) => call.url.includes('/policy'))).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

/**
 * The documentation site's Style guides page (`apiome-docs/screens.json`, DOCS-1.8) is captured
 * from these dumps when the golden-path stack is not running. Written into
 * `e2e/fixtures/hive-a11y/` with
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/guide-detail-hive-redesign.test.tsx -t "docs fixtures"`.
 *
 * One custom guide, "Acme REST", seen on each of its three tabs: a rule catalog spread over
 * four categories with one rule switched off and one severity raised above its default, the
 * custom-rules editor after a dry run that found two violations, and a policy with an armed
 * approval gate and two saved policy versions. The editor is this suite's textarea stand-in
 * for Monaco, carrying the same YAML.
 */
describe('the docs fixtures', () => {
  const DOCS_RULES = [
    ['operation-operationId', 'openapi', 'operations', 'error', 'Every operation needs an operationId so SDKs get stable method names.', true, 'error'],
    ['operation-summary', 'openapi', 'operations', 'warning', 'A one-line summary is what the catalog and the reference show first.', true, 'warning'],
    ['operation-tags', 'openapi', 'operations', 'warning', 'Tags group operations in the reference and in generated SDKs.', true, 'warning'],
    ['path-kebab-case', 'openapi', 'naming', 'warning', 'Path segments should be lowercase kebab-case so URLs read consistently.', true, 'error'],
    ['schema-names-pascal-case', 'openapi', 'naming', 'info', 'Component schema names become type names in most generators.', false, 'info'],
    ['property-camel-case', 'openapi', 'naming', 'info', 'Property names in camelCase match the JSON your SDKs serialise.', true, 'info'],
    ['info-contact', 'common', 'documentation', 'warning', 'Consumers need someone to reach when a contract breaks.', true, 'warning'],
    ['info-description', 'common', 'documentation', 'warning', 'The API description is the first paragraph of its reference page.', true, 'warning'],
    ['security-defined', 'openapi', 'security', 'error', 'Every operation is covered by a security requirement or explicitly marked public.', true, 'error'],
    ['no-http-basic', 'openapi', 'security', 'warning', 'HTTP Basic sends reusable credentials on every request.', true, 'warning'],
  ].map(([ruleId, pack, category, defaultSeverity, rationale, enabled, severity]) => ({
    ruleId: ruleId as string,
    pack: pack as string,
    category: category as string,
    defaultSeverity: defaultSeverity as string,
    rationale: rationale as string,
    docsAnchor: ruleId as string,
    enabled: enabled as boolean,
    severity: severity as string,
  }));

  const DOCS_YAML = [
    'rules:',
    '  operation-summary-max-length:',
    '    description: Summaries stay under 60 characters.',
    '    severity: warning',
    '    given: $.paths[*][*].summary',
    '    then:',
    '      function: length',
    '      functionOptions: { max: 60 }',
    '  refund-idempotency-key:',
    '    description: POST /refunds must declare an Idempotency-Key header.',
    '    severity: error',
    "    given: $.paths['/refunds'].post.parameters[*].name",
    '    then:',
    '      function: pattern',
    '      functionOptions: { match: ^Idempotency-Key$ }',
    '',
  ].join('\n');

  const DOCS_POLICY = {
    guideId: GUIDE_ID,
    axisGates: { quality: { minGrade: 'B' } },
    requiredCoverage: ['quality'],
    ciOutcomes: { failOnUnwaivedErrors: true, failOnRequiredCoverage: true, failOnAxisGates: false },
    breakingPublishPolicy: 'block',
    requiredApprovals: 2,
    requiredReviewerRole: 'release-manager',
  };

  const DOCS_POLICY_VERSIONS = [
    {
      id: 'pv-2',
      guideId: GUIDE_ID,
      versionNumber: 2,
      contentFingerprint: '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8',
      axisGates: DOCS_POLICY.axisGates,
      requiredCoverage: DOCS_POLICY.requiredCoverage,
      ciOutcomes: DOCS_POLICY.ciOutcomes,
      actorLabel: 'maria.chen@acme.dev',
      createdAt: '2026-09-26T13:20:00Z',
    },
    {
      id: 'pv-1',
      guideId: GUIDE_ID,
      versionNumber: 1,
      contentFingerprint: '6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b',
      axisGates: { quality: { minGrade: 'C' } },
      requiredCoverage: [],
      ciOutcomes: { failOnUnwaivedErrors: true, failOnRequiredCoverage: true, failOnAxisGates: true },
      actorLabel: 'devon.ruiz@acme.dev',
      createdAt: '2026-08-14T09:05:00Z',
    },
  ];

  beforeEach(() => {
    const base = global.fetch;
    const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const method = init?.method || 'GET';
      if (url.includes('/api/access/roles')) {
        return jsonResponse({
          success: true,
          data: [
            { id: 'r-owner', slug: 'owner', name: 'Owner', is_builtin: true },
            { id: 'r-admin', slug: 'admin', name: 'Admin', is_builtin: true },
            { id: 'r-release', slug: 'release-manager', name: 'Release Manager', is_builtin: false },
          ],
        });
      }
      if (method === 'GET' && url.endsWith(`${GUIDE_ID}/rules`)) {
        return jsonResponse({ success: true, data: rulesView(DOCS_RULES as typeof RULES) });
      }
      if (method === 'GET' && url.endsWith(`${GUIDE_ID}/custom-rules`)) {
        return jsonResponse({
          success: true,
          data: { guideId: GUIDE_ID, guideName: 'Acme REST', source: 'custom', yaml: DOCS_YAML, ruleCount: 2 },
        });
      }
      if (url.includes(`${GUIDE_ID}/policy-versions`)) {
        return jsonResponse({
          success: true,
          data: { versions: DOCS_POLICY_VERSIONS, count: DOCS_POLICY_VERSIONS.length },
        });
      }
      if (method === 'GET' && url.endsWith(`${GUIDE_ID}/policy`)) {
        return jsonResponse({ success: true, data: DOCS_POLICY });
      }
      return (base as typeof fetch)(input, init);
    });
    // @ts-expect-error - assigning a test double to the global
    global.fetch = fn;
  });

  /** The page root, which is what the docs screenshot mounts. */
  const page = () =>
    (document.querySelector('.page') ?? document.body.firstElementChild) as HTMLElement;

  it('renders the rule catalog, the custom-rules editor after a dry run, and the policy', async () => {
    render(<GuideEditorClient guideId={GUIDE_ID} />);
    await screen.findByText('security-defined');
    expect(screen.getByTestId('guide-enabled-count')).toHaveTextContent('9 of 10 rules enabled');
    writeA11yFixture('style-guide-rules', liveMarkup(page()));

    fireEvent.click(screen.getByTestId('guide-tab-custom'));
    await screen.findByLabelText('Custom rules YAML');
    await waitFor(() => expect(screen.getByTestId('custom-rules-run')).toBeEnabled());
    fireEvent.click(screen.getByTestId('custom-rules-run'));
    await screen.findByTestId('custom-rules-finding-f-1');
    // Monaco is mocked as a bare textarea, which a browser draws as a two-line box. The dump
    // shows the editor's text as a block instead, so the screenshot reads like the real editor.
    const holder = document.createElement('div');
    holder.innerHTML = liveMarkup(page());
    const customPage = holder.firstElementChild as HTMLElement;
    const yaml = customPage.querySelector('textarea[aria-label="Custom rules YAML"]');
    if (yaml) {
      const block = document.createElement('pre');
      block.className = 'mono';
      block.style.margin = '0';
      block.style.padding = '12px 16px';
      block.style.whiteSpace = 'pre';
      block.textContent = (screen.getByLabelText('Custom rules YAML') as HTMLTextAreaElement).value;
      yaml.replaceWith(block);
    }
    writeA11yFixture('style-guide-custom-rule', customPage.outerHTML);

    fireEvent.click(screen.getByTestId('guide-tab-policy'));
    const panel = await screen.findByTestId('guide-policy-panel');
    await waitFor(() =>
      expect(within(panel).getByLabelText('Required reviewer role')).toHaveValue('release-manager')
    );
    writeA11yFixture('style-guide-policy', liveMarkup(page()));
  });

  it('renders the built-in guide’s read-only catalog', async () => {
    guideSource = 'builtin';
    render(<GuideEditorClient guideId={GUIDE_ID} />);
    await screen.findByText('security-defined');
    expect(screen.getByTestId('guide-readonly-rules')).toBeInTheDocument();
    writeA11yFixture('style-guide-builtin', liveMarkup(page()));
  });
});

/**
 * Style-guide import/export (#1747).
 *
 * The pure half (`styleGuideTransfer`): the download filename, the request the dialog builds,
 * and the sentence a refused import becomes. Then the screen, against a mocked `global.fetch`
 * answering with the `{success, data}` envelopes the style-guides proxy really sends: the
 * **Export** row action (members included), and the **Import guide** dialog from a file and
 * from a URL — its inline validation, a refused document with its pointer, and the result view
 * that reports skipped rules.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import StyleGuidesClient from '../src/app/ade/dashboard/style-guides/StyleGuidesClient';
import { TooltipProvider } from '../src/app/components/ui/Tooltip';
import {
  EMPTY_STYLE_GUIDE_IMPORT_DRAFT,
  buildStyleGuideImportRequest,
  describeStyleGuideImportFailure,
  styleGuideExportFilename,
  styleGuideImportSummary,
} from '../src/app/components/ade/styleGuides/styleGuideTransfer';

// ---------------------------------------------------------------------------------------
// The pure half
// ---------------------------------------------------------------------------------------

describe('styleGuideExportFilename', () => {
  it.each([
    ['Payments Guide', 'payments-guide.style-guide.json'],
    ['  API / v2 — Rules!! ', 'api-v2-rules.style-guide.json'],
    ['***', 'style-guide.json'],
  ])('names %p as %p, the same way the REST layer does', (name, expected) => {
    expect(styleGuideExportFilename(name)).toBe(expected);
  });

  it('caps the slug without leaving a trailing dash', () => {
    const name = `${'a'.repeat(79)} b`;
    expect(styleGuideExportFilename(name)).toBe(`${'a'.repeat(79)}.style-guide.json`);
  });
});

describe('buildStyleGuideImportRequest', () => {
  const draft = EMPTY_STYLE_GUIDE_IMPORT_DRAFT;

  it('asks for a file before sending anything', () => {
    expect(buildStyleGuideImportRequest(draft)).toEqual({
      error: 'Choose a style-guide JSON file to import.',
    });
  });

  it('sends the file text with its name as the source label', () => {
    expect(
      buildStyleGuideImportRequest({ ...draft, fileContent: '{}', fileName: 'g.json', name: ' X ' })
    ).toEqual({ request: { content: '{}', name: 'X', sourceLabel: 'g.json' } });
  });

  it('asks for a URL, and only an http(s) one', () => {
    expect(buildStyleGuideImportRequest({ ...draft, source: 'url' })).toEqual({
      error: 'Enter the URL of a style-guide JSON document.',
    });
    expect(buildStyleGuideImportRequest({ ...draft, source: 'url', url: 'ftp://x/y' })).toEqual({
      error: 'The URL must start with http:// or https://.',
    });
  });

  it('sends a trimmed URL and leaves a blank name out', () => {
    expect(
      buildStyleGuideImportRequest({ ...draft, source: 'url', url: ' https://e.com/g.json ' })
    ).toEqual({ request: { url: 'https://e.com/g.json' } });
  });
});

describe('describeStyleGuideImportFailure', () => {
  it('names the offending node of a malformed document', () => {
    const error = Object.assign(new Error('x'), {
      detail: { message: "'severity' must be one of: error, warning, info", pointer: 'builtinRules[2].severity' },
    });
    expect(describeStyleGuideImportFailure(error)).toBe(
      "'severity' must be one of: error, warning, info (at builtinRules[2].severity)"
    );
  });

  it('falls back to the message, then to a generic sentence', () => {
    expect(describeStyleGuideImportFailure(new Error('blocked address'))).toBe('blocked address');
    expect(describeStyleGuideImportFailure(null)).toBe('Failed to import the style guide');
  });
});

describe('styleGuideImportSummary', () => {
  it('counts what was stored, in singular and plural', () => {
    const base = { guide: { id: 'g', name: 'G' }, sourceLabel: null, skipped: [] };
    expect(styleGuideImportSummary({ ...base, builtinRuleCount: 1, customRuleCount: 2 })).toBe(
      'Imported 1 built-in rule setting and 2 custom rules.'
    );
  });
});

// ---------------------------------------------------------------------------------------
// The screen
// ---------------------------------------------------------------------------------------

const GUIDES = [
  {
    id: 'g-builtin',
    name: 'Apiome Recommended',
    description: null,
    source: 'builtin',
    isDefault: true,
    ruleCount: 41,
    enabledRuleCount: 41,
    tenantAssigned: false,
    projectAssignments: [],
    createdAt: null,
    updatedAt: null,
  },
  {
    id: 'g-acme',
    name: 'Acme REST',
    description: 'House rules.',
    source: 'custom',
    isDefault: false,
    ruleCount: 12,
    enabledRuleCount: 9,
    tenantAssigned: false,
    projectAssignments: [],
    createdAt: '2026-07-01T00:00:00Z',
    updatedAt: '2026-08-14T16:22:00Z',
  },
];

const EXPORT_DOCUMENT = {
  format: 'apiome.style-guide',
  formatVersion: 1,
  exportedAt: '2026-11-12T10:00:00+00:00',
  guide: { name: 'Acme REST', description: 'House rules.', externalLintProfile: 'baseline' },
  builtinRules: [{ ruleId: 'naming.path-kebab-case', enabled: true, severity: 'error' }],
  customRules: [],
};

const IMPORT_RESULT = {
  guide: { ...GUIDES[1], id: 'g-new', name: 'Acme REST (imported)' },
  sourceLabel: 'acme-rest.style-guide.json',
  builtinRuleCount: 12,
  customRuleCount: 3,
  skipped: [{ ruleId: 'future.rule', reason: 'unknown_rule', detail: 'not on this instance' }],
};

/** Every call the mocked proxies saw. */
let calls: { url: string; method: string; body: unknown }[] = [];
let isAdmin = true;
/** What the next import POST answers with. */
let importResponse: { success: boolean; data?: unknown; error?: unknown } = {
  success: true,
  data: IMPORT_RESULT,
};

/**
 * A resolved `Response` double carrying a proxy envelope.
 *
 * @param payload The envelope.
 * @returns The response.
 */
function jsonResponse(payload: unknown) {
  return Promise.resolve({ status: 200, json: () => Promise.resolve(payload) } as Response);
}

beforeEach(() => {
  window.localStorage.clear();
  calls = [];
  isAdmin = true;
  importResponse = { success: true, data: IMPORT_RESULT };
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : null });
    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: { is_admin: isAdmin, permissions: [] } });
    }
    if (url.includes('/api/projects')) return jsonResponse({ success: true, projects: [] });
    if (url.endsWith('/export')) return jsonResponse({ success: true, data: EXPORT_DOCUMENT });
    if (url === '/api/style-guides/import') return jsonResponse(importResponse);
    if (url.startsWith('/api/style-guides')) {
      return jsonResponse({ success: true, data: { guides: GUIDES, count: GUIDES.length } });
    }
    return jsonResponse({ success: true, data: null });
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
});

/** Render the page and wait for the list. */
async function renderPage() {
  render(
    <TooltipProvider>
      <StyleGuidesClient />
    </TooltipProvider>
  );
  await screen.findByText('Acme REST');
}

/** The import POSTs the page made. */
const importCalls = () => calls.filter((c) => c.url === '/api/style-guides/import');

describe('the Export row action', () => {
  let createObjectURL: jest.Mock;
  let revokeObjectURL: jest.Mock;
  let clicked: string[];

  beforeEach(() => {
    clicked = [];
    createObjectURL = jest.fn(() => 'blob:export');
    revokeObjectURL = jest.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this.download);
      });
  });

  afterEach(() => jest.restoreAllMocks());

  it('downloads the guide as <name>.style-guide.json', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByTestId('style-guide-export-g-acme'));

    await waitFor(() => expect(clicked).toEqual(['acme-rest.style-guide.json']));
    expect(calls.some((c) => c.url === '/api/style-guides/g-acme/export')).toBe(true);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    // jsdom's Blob has no `text()`, so read it the way a browser without one would.
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(blob.type).toBe('application/json');
    expect(JSON.parse(text)).toEqual(EXPORT_DOCUMENT);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:export');
  });

  it('is offered for the read-only built-in guide', async () => {
    await renderPage();
    expect(screen.getByLabelText('Export Apiome Recommended')).toBeInTheDocument();
  });

  it('is the one row action a member gets', async () => {
    isAdmin = false;
    await renderPage();
    expect(screen.getByTestId('style-guide-export-g-acme')).toBeInTheDocument();
    expect(screen.queryByTestId('style-guide-assign-g-acme')).not.toBeInTheDocument();
    expect(screen.queryByTestId('style-guides-import')).not.toBeInTheDocument();
  });
});

describe('the Import guide dialog', () => {
  /** Open the dialog and return it. */
  async function openDialog(user: ReturnType<typeof userEvent.setup>) {
    await renderPage();
    await user.click(screen.getByTestId('style-guides-import'));
    return screen.findByTestId('style-guide-import-dialog');
  }

  /** Pick a file in the dialog's file input. */
  async function pickFile(dialog: HTMLElement, text: string, name = 'acme-rest.style-guide.json') {
    const file = new File([text], name, { type: 'application/json' });
    // jsdom's File lacks `text()` in some versions; give it one.
    Object.defineProperty(file, 'text', { value: () => Promise.resolve(text) });
    fireEvent.change(within(dialog).getByTestId('style-guide-import-file'), {
      target: { files: [file] },
    });
    await waitFor(() => expect(within(dialog).queryByTestId('style-guide-import-error')).toBeNull());
  }

  it('refuses to send without a file', async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByTestId('style-guide-import-submit'));

    expect(within(dialog).getByTestId('style-guide-import-error')).toHaveTextContent(
      'Choose a style-guide JSON file to import.'
    );
    expect(importCalls()).toHaveLength(0);
  });

  it('imports an uploaded file, then reports what it stored and skipped', async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);
    const text = JSON.stringify(EXPORT_DOCUMENT);
    await pickFile(dialog, text);
    await user.type(within(dialog).getByTestId('style-guide-import-name'), 'Acme REST (imported)');
    await user.click(within(dialog).getByTestId('style-guide-import-submit'));

    const result = await within(dialog).findByTestId('style-guide-import-result');
    expect(importCalls()[0].body).toEqual({
      content: text,
      name: 'Acme REST (imported)',
      sourceLabel: 'acme-rest.style-guide.json',
    });
    expect(result).toHaveTextContent('Created “Acme REST (imported)”.');
    expect(result).toHaveTextContent('Imported 12 built-in rule settings and 3 custom rules.');
    expect(within(dialog).getByTestId('style-guide-import-skipped')).toHaveTextContent('future.rule');

    await user.click(within(dialog).getByTestId('style-guide-import-done'));
    await waitFor(() =>
      expect(screen.queryByTestId('style-guide-import-dialog')).not.toBeInTheDocument()
    );
  });

  it('imports from a URL', async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole('radio', { name: 'URL' }));
    await user.type(
      within(dialog).getByTestId('style-guide-import-url'),
      'https://example.com/acme.style-guide.json'
    );
    await user.click(within(dialog).getByTestId('style-guide-import-submit'));

    await within(dialog).findByTestId('style-guide-import-result');
    expect(importCalls()[0].body).toEqual({ url: 'https://example.com/acme.style-guide.json' });
  });

  it('shows a refused document inline, with the node it points at, and stays open', async () => {
    importResponse = {
      success: false,
      error: { message: 'unknown key \'policy\'', pointer: 'policy' },
    };
    const user = userEvent.setup();
    const dialog = await openDialog(user);
    await pickFile(dialog, '{"format":"apiome.style-guide","formatVersion":1,"policy":{}}');
    await user.click(within(dialog).getByTestId('style-guide-import-submit'));

    expect(await within(dialog).findByTestId('style-guide-import-error')).toHaveTextContent(
      "unknown key 'policy' (at policy)"
    );
    expect(within(dialog).queryByTestId('style-guide-import-result')).not.toBeInTheDocument();
  });

  it('refuses a file over the 1 MiB limit before reading it', async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);
    const file = new File(['x'], 'huge.json', { type: 'application/json' });
    Object.defineProperty(file, 'size', { value: 2_000_000 });
    fireEvent.change(within(dialog).getByTestId('style-guide-import-file'), {
      target: { files: [file] },
    });

    expect(await within(dialog).findByTestId('style-guide-import-error')).toHaveTextContent(
      'larger than the 1 MiB limit'
    );
  });
});

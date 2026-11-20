/**
 * COA-2.5 (#7048) — the OpenAPI 3.2 constructs panel above the spec viewer's code.
 *
 * - a 3.2 document lists its QUERY / custom-method operations, tag hierarchy, streaming media types
 *   and querystring parameters, one group each;
 * - a group with no entries is not drawn;
 * - a 3.1 document (or one with none of the constructs) draws nothing;
 * - **axe** passes on the panel;
 * - the spec viewer shows the panel above the code and names the declared version.
 *
 * It also writes the docs fixtures the `openapi32-operations` and `openapi32-tags` screenshots are
 * captured from (`apiome-docs/screens.json`) when `OAS32_FIXTURE_DUMP=1` is set:
 *
 *     OAS32_FIXTURE_DUMP=1 npx jest tests/openapi32-constructs-panel.test.tsx
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import YAML from 'yaml';

import Openapi32ConstructsPanel from '../src/app/components/ade/versions/Openapi32ConstructsPanel';
import SpecViewerDialog from '../src/app/components/ade/versions/SpecViewerDialog';
import type { Version } from '../src/app/components/ade/versions/versionsModel';

/** Monaco is a browser editor; the code is drawn as a plain block, as the screenshot shows it. */
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value }: { value: string }) => (
    <pre className="mono" data-testid="mock-monaco">
      {value}
    </pre>
  ),
}));

/** next/dynamic loads Monaco lazily; render the mocked module directly. */
jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('@monaco-editor/react');
    return mod.default;
  },
}));

/** The export cards read REST; not under test. */
jest.mock('@/app/components/ade/dashboard/export/VersionExportPanel', () => ({
  __esModule: true,
  default: () => null,
}));

/** A 3.2 document with one of each construct. */
const SPEC_32 = JSON.stringify({
  openapi: '3.2.0',
  info: { title: 'Orders', version: '1.0.0' },
  tags: [
    { name: 'orders', summary: 'Orders', kind: 'nav' },
    { name: 'order-search', parent: 'orders' },
    { name: 'plain' },
  ],
  paths: {
    '/orders': {
      get: {
        parameters: [
          { name: 'filter', in: 'querystring', content: { 'application/x-www-form-urlencoded': { schema: { type: 'object' } } } },
        ],
        responses: { '200': { description: 'ok', content: { 'application/jsonl': { itemSchema: { type: 'object' } } } } },
      },
      query: { operationId: 'searchOrders', responses: { '200': { description: 'ok' } } },
      additionalOperations: { REPORT: { responses: { '200': { description: 'ok' } } } },
    },
  },
});

describe('Openapi32ConstructsPanel', () => {
  it('lists each construct of a 3.2 document', () => {
    render(<Openapi32ConstructsPanel spec={SPEC_32} />);
    const panel = screen.getByTestId('oas32-constructs');
    expect(within(panel).getByRole('heading', { name: 'OpenAPI 3.2.0 constructs' })).toBeInTheDocument();

    const operations = within(panel).getByTestId('oas32-operations');
    expect(within(operations).getAllByTestId('method-chip').map((chip) => chip.textContent)).toEqual(['QUERY', 'REPORT']);
    expect(operations).toHaveTextContent('searchOrders');
    expect(operations).toHaveTextContent('additionalOperations');

    const tags = within(panel).getByTestId('oas32-tags');
    expect(within(tags).getAllByRole('listitem')).toHaveLength(2);
    expect(tags).toHaveTextContent('order-searchunder orders');
    expect(tags).toHaveTextContent('kind nav');
    expect(tags).not.toHaveTextContent('plain');

    expect(within(panel).getByTestId('oas32-streams')).toHaveTextContent('application/jsonlJSON Lines');
    expect(within(panel).getByTestId('oas32-querystring')).toHaveTextContent('filter');
  });

  it('leaves out a group with no entries', () => {
    const spec = JSON.stringify({ openapi: '3.2.0', paths: { '/a': { query: { responses: {} } } } });
    render(<Openapi32ConstructsPanel spec={spec} />);
    expect(screen.getByTestId('oas32-operations')).toBeInTheDocument();
    expect(screen.queryByTestId('oas32-tags')).not.toBeInTheDocument();
    expect(screen.queryByTestId('oas32-streams')).not.toBeInTheDocument();
    expect(screen.queryByTestId('oas32-querystring')).not.toBeInTheDocument();
  });

  it('draws nothing for a 3.1 document', () => {
    const spec31 = JSON.stringify({ ...JSON.parse(SPEC_32), openapi: '3.1.0' });
    const { container } = render(<Openapi32ConstructsPanel spec={spec31} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('draws nothing for an empty or unreadable spec', () => {
    const { container, rerender } = render(<Openapi32ConstructsPanel spec="" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<Openapi32ConstructsPanel spec="{oops" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('passes axe', async () => {
    const { container } = render(<Openapi32ConstructsPanel spec={SPEC_32} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

/** The docs fixtures' document: an orders API using each construct. */
const DOCS_SPEC = JSON.stringify(
  {
    openapi: '3.2.0',
    info: { title: 'Orders API', version: '2.4.0' },
    tags: [
      { name: 'orders', summary: 'Orders', description: 'Everything about orders', kind: 'nav' },
      { name: 'order-search', summary: 'Search', parent: 'orders', kind: 'nav' },
      { name: 'order-events', summary: 'Events', parent: 'orders', kind: 'nav' },
      { name: 'beta', kind: 'badge' },
    ],
    paths: {
      '/orders': {
        get: {
          operationId: 'listOrders',
          tags: ['orders'],
          parameters: [
            {
              name: 'filter',
              in: 'querystring',
              content: {
                'application/x-www-form-urlencoded': {
                  schema: { type: 'object', properties: { status: { type: 'string' } } },
                },
              },
            },
          ],
          responses: {
            '200': {
              description: 'Orders as JSON Lines',
              content: { 'application/jsonl': { itemSchema: { $ref: '#/components/schemas/Order' } } },
            },
          },
        },
        query: {
          operationId: 'searchOrders',
          tags: ['order-search', 'beta'],
          requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/OrderQuery' } } } },
          responses: { '200': { description: 'Matching orders' } },
        },
        additionalOperations: {
          REPORT: {
            operationId: 'reportOrders',
            tags: ['order-events'],
            responses: {
              '200': {
                description: 'Order events',
                content: { 'text/event-stream': { itemSchema: { $ref: '#/components/schemas/OrderEvent' } } },
              },
            },
          },
        },
      },
    },
    components: {
      schemas: {
        Order: { type: 'object', properties: { id: { type: 'string' } } },
        OrderQuery: { type: 'object', properties: { status: { type: 'string' } } },
        OrderEvent: { type: 'object', properties: { type: { type: 'string' } } },
      },
    },
  },
  null,
  2
);

/** The revision the docs fixtures show. */
const DOCS_VERSION = { id: 'rev-240', project_id: 'project-1', version_id: '2.4.0' } as unknown as Version;

/** Render the spec viewer over a spec. */
function renderViewer(spec: string, format: 'json' | 'yaml' = 'json') {
  return render(
    <SpecViewerDialog
      open
      onOpenChange={() => undefined}
      version={DOCS_VERSION}
      projectName="Orders API"
      projectSlug="orders-api"
      spec={spec}
      loading={false}
      format={format}
      onFormatChange={() => undefined}
      recentExportsRefresh={0}
    />
  );
}

describe('SpecViewerDialog with an OpenAPI 3.2 document', () => {
  it('names the declared version and lists the constructs above the code', async () => {
    renderViewer(DOCS_SPEC);
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(within(dialog).getByRole('heading', { name: 'OpenAPI 3.2.0 specification' })).toBeInTheDocument();
    const panel = within(dialog).getByTestId('oas32-constructs');
    const editor = within(dialog).getByTestId('spec-viewer-editor');
    // The panel comes before the code.
    expect(panel.compareDocumentPosition(editor) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows no panel for a 3.1 document', async () => {
    renderViewer(JSON.stringify({ openapi: '3.1.0', info: {}, paths: {} }));
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(within(dialog).getByRole('heading', { name: 'OpenAPI 3.1.0 specification' })).toBeInTheDocument();
    expect(within(dialog).queryByTestId('oas32-constructs')).not.toBeInTheDocument();
  });

  it('shows no panel while the spec is loading', async () => {
    render(
      <SpecViewerDialog
        open
        onOpenChange={() => undefined}
        version={DOCS_VERSION}
        spec={DOCS_SPEC}
        loading
        format="json"
        onFormatChange={() => undefined}
        recentExportsRefresh={0}
      />
    );
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(within(dialog).getByRole('heading', { name: 'OpenAPI specification' })).toBeInTheDocument();
    expect(within(dialog).queryByTestId('oas32-constructs')).not.toBeInTheDocument();
  });

  it('renders the docs fixtures (and writes them on request)', async () => {
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-versions');
    const dumps: Array<[string, string, 'json' | 'yaml']> = [
      ['spec-viewer-oas32', DOCS_SPEC, 'json'],
      ['spec-viewer-oas32-tags', DOCS_SPEC, 'yaml'],
    ];
    for (const [name, spec, format] of dumps) {
      const { unmount } = renderViewer(spec, format);
      const dialog = await screen.findByTestId('spec-viewer-dialog');
      await waitFor(() => expect(within(dialog).getByTestId('oas32-tags')).toBeInTheDocument());
      if (format === 'yaml') expect(dialog).toHaveTextContent(YAML.stringify(JSON.parse(spec)).split('\n')[0]);
      if (process.env.OAS32_FIXTURE_DUMP === '1') {
        fs.mkdirSync(out, { recursive: true });
        fs.writeFileSync(path.join(out, `${name}.html`), dialog.outerHTML);
      }
      unmount();
    }
  });
});

/**
 * COA-5.7 (#7083): "Download original" and the compare view's Originals mode.
 *
 * `fetch` is mocked per URL. Pinned: the helpers read the offered file name and word the two
 * refusals; the button saves the file under that name and toasts a refusal; the Originals panel
 * diffs the two files (counts, line numbers, an identical pair) and says which side has no
 * stored original instead of diffing against nothing.
 *
 * COA-5.13 (#7089) turned the Originals tab into a **Rendered / Original** switch on the Diff tab;
 * the fixtures below draw that switch above the panel, as the page does.
 *
 * The docs screenshot fixtures (`versions-download-original`, `versions-compare`,
 * `versions-compare-originals`) are written when `ORIGINALS_FIXTURE_DUMP=1`:
 *
 *     ORIGINALS_FIXTURE_DUMP=1 npx jest tests/version-original-ui.test.tsx
 */

import fs from 'fs';
import path from 'path';
import * as React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockToast = { success: jest.fn(), error: jest.fn(), warning: jest.fn(), info: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

/** Monaco is a browser editor; the spec viewer's code is drawn as a plain block. */
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value }: { value: string }) => (
    <pre className="mono" data-testid="mock-monaco">
      {value}
    </pre>
  ),
}));
jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    return require('@monaco-editor/react').default;
  },
}));
jest.mock('@/app/components/ade/dashboard/export/VersionExportPanel', () => ({ __esModule: true, default: () => null }));

import SpecViewerDialog from '../src/app/components/ade/versions/SpecViewerDialog';
import type { Version } from '../src/app/components/ade/versions/versionsModel';
import DownloadOriginalButton from '../src/app/components/ade/versions/DownloadOriginalButton';
import OriginalsDiffPanel from '../src/app/components/ade/versions/OriginalsDiffPanel';
import { WindowedDiffRows } from '../src/app/components/ade/versions/WindowedDiffRows';
import { Segmented, SegmentedItem } from '../src/app/components/ui/Segmented';
import {
  VERSION_CHANGE_TONE,
  VERSION_DIFF_LEGEND,
  buildVersionDiffRows,
} from '../src/app/components/ade/version-dialogs/versionDialogsModel';
import { diffLines } from 'diff';
import {
  filenameFromDisposition,
  originalErrorMessage,
  versionOriginalHref,
} from '../src/app/utils/version-original';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const V1 = '11111111-1111-4111-8111-111111111111';
const V2 = '22222222-2222-4222-8222-222222222222';

type Reply = { status: number; body: string; headers?: Record<string, string> };
let replies: Record<string, Reply> = {};

function file(body: string, name: string): Reply {
  return { status: 200, body, headers: { 'content-disposition': `attachment; filename="${name}"` } };
}

function refusal(status: number, code: string): Reply {
  return { status, body: JSON.stringify({ success: false, error: 'REST says no', code }) };
}

/** A response-shaped object (jsdom has no fetch `Response`). */
function fakeResponse(reply: Reply) {
  const headers = new Map(Object.entries(reply.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  const bytes = new TextEncoder().encode(reply.body);
  return {
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
    json: async () => JSON.parse(reply.body),
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    blob: async () => new Blob([reply.body]),
  };
}

beforeEach(() => {
  replies = {};
  mockToast.success.mockClear();
  mockToast.error.mockClear();
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const reply = Object.entries(replies).find(([version]) => url.includes(`/api/versions/${version}/`))?.[1];
    return fakeResponse(reply ?? { status: 500, body: '{}' });
  }) as unknown as typeof fetch;
});

describe('helpers', () => {
  test('the proxy URL carries the project and part', () => {
    expect(versionOriginalHref(PROJECT, V1)).toBe(`/api/versions/${V1}/original?projectId=${PROJECT}`);
    expect(versionOriginalHref(PROJECT, V1, 'api/a b.yaml')).toBe(
      `/api/versions/${V1}/original?projectId=${PROJECT}&part=api%2Fa+b.yaml`,
    );
  });

  test('the offered file name', () => {
    expect(filenameFromDisposition('attachment; filename="pets.yaml"')).toBe('pets.yaml');
    expect(filenameFromDisposition("attachment; filename=\"_.yaml\"; filename*=UTF-8''%E6%B3%A8.yaml")).toBe('注.yaml');
    expect(filenameFromDisposition('attachment; filename="../x/evil.sh"')).toBe('evil.sh');
    expect(filenameFromDisposition(null)).toBe('original');
  });

  test('the refusals read as sentences', () => {
    expect(originalErrorMessage('original-not-stored')).toMatch(/No original file is stored/);
    expect(originalErrorMessage('original-withheld')).toMatch(/withheld at import/);
    expect(originalErrorMessage(undefined, 'REST says no')).toBe('REST says no');
  });
});

describe('DownloadOriginalButton', () => {
  test('saves the file under the offered name', async () => {
    replies[V1] = file('openapi: 3.1.0\n', 'pets.yaml');
    const createObjectURL = jest.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL, revokeObjectURL: jest.fn() });
    const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    render(<DownloadOriginalButton projectId={PROJECT} versionId={V1} />);
    fireEvent.click(screen.getByTestId('download-original'));

    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Downloaded pets.yaml'));
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  test('a version with nothing stored toasts why', async () => {
    replies[V1] = refusal(404, 'original-not-stored');

    render(<DownloadOriginalButton projectId={PROJECT} versionId={V1} />);
    fireEvent.click(screen.getByRole('button', { name: /Download original/ }));

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith('No original file is stored for this version.'),
    );
  });
});

describe('OriginalsDiffPanel', () => {
  const base = { projectId: PROJECT, versionId: V1, label: 'v1.0.0' };
  const head = { projectId: PROJECT, versionId: V2, label: 'v1.1.0' };

  test('diffs the two originals', async () => {
    replies[V1] = file('openapi: 3.1.0\ninfo:\n  title: Pets\n', 'pets.yaml');
    replies[V2] = file('openapi: 3.1.0\ninfo:\n  title: Pet Store\n', 'pets-v2.yaml');

    render(<OriginalsDiffPanel base={base} head={head} />);

    expect(await screen.findByTestId('originals-diff')).toBeInTheDocument();
    expect(screen.getByText('pets.yaml')).toBeInTheDocument();
    expect(screen.getByText('pets-v2.yaml')).toBeInTheDocument();
    const counts = screen.getByTestId('originals-diff-counts');
    expect(counts).toHaveTextContent('+1');
    expect(counts).toHaveTextContent('−1');
    const rows = screen.getByTestId('originals-diff-rows');
    expect(rows).toHaveTextContent('- title: Pets');
    expect(rows).toHaveTextContent('+ title: Pet Store');
    expect(rows.querySelector('[data-change="removed"]')).not.toBeNull();
  });

  test('an identical pair says so', async () => {
    replies[V1] = file('a: 1\n', 'a.yaml');
    replies[V2] = file('a: 1\n', 'a.yaml');

    render(<OriginalsDiffPanel base={base} head={head} />);

    expect(await screen.findByText('Identical files')).toBeInTheDocument();
  });

  test('a side with no stored original is named', async () => {
    replies[V1] = file('a: 1\n', 'a.yaml');
    replies[V2] = refusal(410, 'original-withheld');

    render(<OriginalsDiffPanel base={base} head={head} />);

    const empty = await screen.findByTestId('originals-diff-unavailable');
    expect(empty).toHaveTextContent('v1.1.0: The original was withheld at import');
    expect(empty).not.toHaveTextContent('v1.0.0:');
  });
});

describe('docs fixtures', () => {
  const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-versions');
  const dump = (name: string, html: string) => {
    if (process.env.ORIGINALS_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${name}.html`), html);
  };

  /** Two revisions of one imported spec: a renamed title, a new path and a widened enum. */
  const spec = (title: string, extra: boolean) =>
    [
      'openapi: 3.1.0',
      'info:',
      `  title: ${title}`,
      '  version: 1.0.0',
      'servers:',
      '  - url: https://api.example.com/v1',
      'paths:',
      ...Array.from({ length: 12 }, (_, i) => [
        `  /orders/${i}:`,
        '    get:',
        `      operationId: getOrder${i}`,
        '      responses:',
        "        '200':",
        '          description: OK',
      ]).flat(),
      ...(extra ? ['  /orders/{id}/refunds:', '    post:', '      operationId: refundOrder', '      responses:', "        '202':", '          description: Accepted'] : []),
      'components:',
      '  schemas:',
      '    OrderStatus:',
      '      type: string',
      `      enum: [placed, paid, shipped${extra ? ', refunded' : ''}]`,
    ].join('\n') + '\n';

  /** The Diff tab's first row, as the Versions page draws it: the switch, the legend, the pair. */
  const legendRow = (source: 'rendered' | 'original') => (
    <div className="vdlg-compare__legend-row">
      <Segmented value={source} onValueChange={() => undefined} size="sm" aria-label="What to compare">
        <SegmentedItem value="rendered">Rendered</SegmentedItem>
        <SegmentedItem value="original">Original</SegmentedItem>
      </Segmented>
      <div className="vdlg-legend">
        {VERSION_DIFF_LEGEND.map((entry) => (
          <span key={entry.change} className="vdlg-legend__item">
            <span className="vdlg-legend__swatch" data-tone={VERSION_CHANGE_TONE[entry.change]} aria-hidden />
            {entry.label}
          </span>
        ))}
      </div>
      <div className="hive-quiet">v1.0.0 → v1.1.0</div>
    </div>
  );
  const tabPanelStyle = { blockSize: '52rem', display: 'flex', flexDirection: 'column' } as const;

  /** The document apiome-rest renders for a revision: OpenAPI 3.2, compact, re-printed by the UI. */
  const rendered = (title: string, extra: boolean) =>
    JSON.stringify(
      {
        openapi: '3.2.0',
        info: { title: 'orders API', version: extra ? '1.1.0' : '1.0.0', description: title },
        paths: {
          '/orders': { get: { operationId: 'listOrders', responses: { '200': { description: 'OK' } } } },
          ...(extra
            ? { '/orders/{id}/refunds': { post: { operationId: 'refundOrder', responses: { '202': { description: 'Accepted' } } } } }
            : {}),
        },
        components: {
          schemas: {
            Order: {
              type: 'object',
              title: 'Order',
              properties: {
                id: { type: 'string', format: 'uuid', description: 'Identifier' },
                status: { $ref: '#/components/schemas/OrderStatus' },
              },
              required: ['id'],
            },
            OrderStatus: {
              type: 'string',
              title: 'OrderStatus',
              enum: extra ? ['placed', 'paid', 'shipped', 'refunded'] : ['placed', 'paid', 'shipped'],
            },
          },
        },
      },
      null,
      2,
    );

  test('the Diff tab on Rendered', () => {
    const parts = diffLines(rendered('Orders', false), rendered('Orders', true));
    const { container } = render(
      <div className="vdlg-compare__tabpanel vdlg-compare__tabpanel--diff" style={tabPanelStyle}>
        {legendRow('rendered')}
        <div className="vdlg-diff" data-testid="compare-diff" data-changes-only>
          <WindowedDiffRows
            rows={buildVersionDiffRows(parts, 'unified', true)}
            showLineNo={false}
            className="vdlg-diff__scroll"
            testId="compare-diff-rows"
          />
        </div>
      </div>,
    );
    const rows = screen.getByTestId('compare-diff-rows');
    expect(rows.querySelector('[data-change="added"]')).not.toBeNull();
    expect(rows).toHaveTextContent('refundOrder');
    expect(rows).toHaveTextContent('unchanged lines');
    dump('compare-rendered', container.innerHTML);
  });

  test('the Diff tab on Original', async () => {
    replies[V1] = file(spec('Orders', false), 'orders.yaml');
    replies[V2] = file(spec('Orders API', true), 'orders.yaml');
    const { container } = render(
      <div className="vdlg-compare__tabpanel vdlg-compare__tabpanel--diff" style={tabPanelStyle}>
        {legendRow('original')}
        <OriginalsDiffPanel
          base={{ projectId: PROJECT, versionId: V1, label: 'v1.0.0' }}
          head={{ projectId: PROJECT, versionId: V2, label: 'v1.1.0' }}
        />
      </div>,
    );
    await screen.findByTestId('originals-diff');
    expect(screen.getByTestId('originals-diff-counts')).toHaveTextContent('+8');
    dump('compare-originals', container.innerHTML);
  });

  test('Download original in the spec viewer', async () => {
    const version = { id: V1, project_id: PROJECT, version_id: '1.1.0' } as unknown as Version;
    render(
      <SpecViewerDialog
        open
        onOpenChange={() => undefined}
        version={version}
        projectName="Orders API"
        projectSlug="orders-api"
        spec={JSON.stringify({ openapi: '3.1.0', info: { title: 'Orders API', version: '1.1.0' }, paths: {} }, null, 2)}
        loading={false}
        format="json"
        onFormatChange={() => undefined}
        recentExportsRefresh={0}
      />,
    );
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(screen.getByTestId('spec-viewer-download-original')).toHaveTextContent('Download original');
    dump('spec-viewer-download-original', dialog.outerHTML);
  });
});

/**
 * The Studio half of the AsyncAPI test drive — MFX-44.4 (#4370).
 *
 * - `parseAsyncApiDocument` reads JSON and YAML, AsyncAPI 3.x and 2.x, counts channels and operations,
 *   and says why a file is not one it can render (not JSON/YAML, no `asyncapi`, an unsupported major);
 * - `AsyncApiTestDriveFrame` draws a sandboxed, no-same-origin iframe, posts the parsed document once
 *   the page is ready (and again when the file changes), reports the renderer's error, ignores
 *   messages from other windows, and shows a notice for a file it cannot show.
 */

import React from 'react';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import {
  asyncApiSummaryText,
  countAsyncApiOperations,
  parseAsyncApiDocument,
} from '../src/app/components/ade/dashboard/export/asyncApiTestDrive';
import { AsyncApiTestDriveFrame } from '../src/app/components/ade/dashboard/export/AsyncApiTestDriveFrame';
import { TestDrivePanel } from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const V3 = {
  asyncapi: '3.1.0',
  info: { title: 'Orders', version: '1.0.0' },
  channels: {
    orderCreated: { address: 'orders/created', messages: { OrderCreated: { payload: { type: 'object' } } } },
    orderShipped: { address: 'orders/shipped', messages: { OrderShipped: { payload: { type: 'object' } } } },
  },
  operations: {
    onOrderCreated: { action: 'receive', channel: { $ref: '#/channels/orderCreated' } },
    onOrderShipped: { action: 'receive', channel: { $ref: '#/channels/orderShipped' } },
    publishOrderCreated: { action: 'send', channel: { $ref: '#/channels/orderCreated' } },
  },
};
const TEXT = JSON.stringify(V3);

describe('parseAsyncApiDocument', () => {
  it('reads a 3.x JSON document and counts its channels and operations', () => {
    expect(parseAsyncApiDocument(TEXT)).toEqual({
      ok: true,
      document: { spec: V3, version: '3.1.0', channels: 2, operations: 3 },
    });
  });

  it('reads a 2.x YAML document, counting publish / subscribe as operations', () => {
    const yaml = [
      'asyncapi: 2.6.0',
      'info: { title: Orders, version: "1" }',
      'channels:',
      '  orders/created: { subscribe: { message: { payload: { type: object } } }, publish: { message: { payload: { type: object } } } }',
      '  orders/shipped: { subscribe: { message: { payload: { type: object } } } }',
      '',
    ].join('\n');
    const parsed = parseAsyncApiDocument(yaml);
    expect(parsed.ok && parsed.document).toMatchObject({ version: '2.6.0', channels: 2, operations: 3 });
    expect(countAsyncApiOperations({ channels: { a: null, b: { parameters: {} } } }, '2')).toBe(0);
    expect(countAsyncApiOperations({}, '3')).toBe(0);
  });

  it('says why a file cannot be rendered', () => {
    expect(parseAsyncApiDocument('{not json')).toMatchObject({ ok: false, error: expect.stringContaining('not valid JSON or YAML') });
    expect(parseAsyncApiDocument('[1, 2]')).toMatchObject({ ok: false, error: 'The file is not an AsyncAPI document.' });
    expect(parseAsyncApiDocument('{"openapi":"3.1.0"}')).toMatchObject({ ok: false, error: expect.stringContaining('no `asyncapi`') });
    expect(parseAsyncApiDocument('{"asyncapi":"1.2.0"}')).toMatchObject({
      ok: false, error: expect.stringContaining('reads AsyncAPI 2.x and 3.x'),
    });
  });

  it('summarizes the document for the note', () => {
    expect(asyncApiSummaryText({ version: '3.1.0', channels: 2, operations: 3 })).toBe('AsyncAPI 3.1.0 · 2 channels · 3 operations');
    expect(asyncApiSummaryText({ version: '2.6.0', channels: 1, operations: 1 })).toBe('AsyncAPI 2.6.0 · 1 channel · 1 operation');
  });
});

describe('AsyncApiTestDriveFrame', () => {
  function mount(text = TEXT) {
    const view = render(<AsyncApiTestDriveFrame text={text} />);
    const frame = screen.getByTestId('asyncapi-test-drive-frame') as HTMLIFrameElement;
    const posted: Record<string, unknown>[] = [];
    jest.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(((message: Record<string, unknown>) => {
      posted.push(message);
    }) as never);
    const fromPage = (data: Record<string, unknown>, source: unknown = frame.contentWindow) =>
      act(() => {
        window.dispatchEvent(new MessageEvent('message', { data, source: source as Window }));
      });
    return { ...view, frame, posted, fromPage };
  }

  it('draws a sandboxed iframe with no same-origin', () => {
    const { frame } = mount();
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame.getAttribute('src')).toBe('/test-drive/asyncapi');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
    expect(screen.getByText(/AsyncAPI 3\.1\.0 · 2 channels · 3 operations\. Drawn in a sandbox/)).toBeInTheDocument();
  });

  it('posts the document once the page is ready, and marks it rendered', async () => {
    const { posted, fromPage } = mount();
    expect(posted).toEqual([]);
    await fromPage({ type: 'apiome-test-drive:ready' });
    expect(posted).toEqual([{ type: 'apiome-test-drive:load', spec: V3 }]);
    expect(screen.getByTestId('asyncapi-test-drive')).toHaveAttribute('data-state', 'loading');
    await fromPage({ type: 'apiome-test-drive:rendered' });
    expect(screen.getByTestId('asyncapi-test-drive')).toHaveAttribute('data-state', 'rendered');
  });

  it('re-posts when the file changes', async () => {
    const { posted, fromPage, rerender } = mount();
    await fromPage({ type: 'apiome-test-drive:ready' });
    const v2 = { asyncapi: '2.6.0', info: { title: 'Orders', version: '1' }, channels: {} };
    rerender(<AsyncApiTestDriveFrame text={JSON.stringify(v2)} />);
    expect(posted.at(-1)).toEqual({ type: 'apiome-test-drive:load', spec: v2 });
  });

  it("reports the renderer's error", async () => {
    const { fromPage } = mount();
    await fromPage({ type: 'apiome-test-drive:error', message: 'There are errors in your Asyncapi document' });
    expect(screen.getByRole('alert')).toHaveTextContent('There are errors in your Asyncapi document');
    expect(screen.getByTestId('asyncapi-test-drive')).toHaveAttribute('data-state', 'error');
  });

  it('ignores messages from anywhere but its own frame', async () => {
    const { posted, fromPage } = mount();
    await fromPage({ type: 'apiome-test-drive:ready' }, window);
    expect(posted).toEqual([]);
  });

  it('shows a notice, and no frame, for a file it cannot render', () => {
    render(<AsyncApiTestDriveFrame text='{"asyncapi":"1.2.0"}' />);
    expect(screen.getByTestId('asyncapi-test-drive-unreadable')).toHaveTextContent('AsyncAPI 1.2.0 cannot be rendered here');
    expect(screen.queryByTestId('asyncapi-test-drive-frame')).toBeNull();
  });
});

/**
 * The documentation site's Export studio page (`apiome-docs/screens.json`, id
 * `export-studio-asyncapi-test-drive`) captures the AsyncAPI viewer tab from this dump:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/asyncapi-test-drive-frame.test.tsx -t "docs fixture"`. A static
 * dump runs no script, so the dumped frame is fed through the page's fragment feed (`#spec=…`) — the
 * same document the Studio would post.
 */
describe('the docs fixture', () => {
  it('renders the AsyncAPI viewer tab of an AsyncAPI target', () => {
    const orders = {
      asyncapi: '3.1.0',
      info: { title: 'Order Events', version: '1.2.0', description: 'Exported from Apiome.' },
      channels: {
        orderCreated: {
          address: 'orders/created',
          messages: {
            OrderCreated: {
              name: 'OrderCreated',
              payload: { type: 'object', properties: { orderId: { type: 'string' }, total: { type: 'number' } } },
            },
          },
        },
        orderShipped: {
          address: 'orders/shipped',
          messages: {
            OrderShipped: {
              name: 'OrderShipped',
              payload: { type: 'object', properties: { orderId: { type: 'string' }, carrier: { type: 'string' } } },
            },
          },
        },
      },
      operations: {
        onOrderCreated: { action: 'receive', channel: { $ref: '#/channels/orderCreated' }, summary: 'An order was placed' },
        onOrderShipped: { action: 'receive', channel: { $ref: '#/channels/orderShipped' }, summary: 'An order left the warehouse' },
      },
    };
    const tools = [
      { kind: 'asyncapi-render', label: 'AsyncAPI viewer', server_side: false },
      { kind: 'toolchain', label: 'asyncapi validate', server_side: true, available: false,
        unavailable_reason: 'The asyncapi toolchain is not installed on this server.' },
    ];
    render(
      <TestDrivePanel tools={tools} targetKey="asyncapi" renderers={{
        'asyncapi-render': () => <AsyncApiTestDriveFrame text={JSON.stringify(orders)} />,
        toolchain: () => null,
      }} />,
    );
    const frame = screen.getByTestId('asyncapi-test-drive-frame');
    frame.setAttribute('src', `${frame.getAttribute('src')}#spec=${encodeURIComponent(JSON.stringify(orders))}`);
    writeA11yFixture('export-studio-asyncapi-test-drive', document.body.firstElementChild!.outerHTML);
  });
});

/**
 * The Studio half of the OpenAPI test drive — MFX-44.2 (#4368).
 *
 * - `parseOpenApiDocument` reads JSON and YAML, OpenAPI 3.x and Swagger 2.0, counts operations, flags a
 *   large document, and says why a file is not one;
 * - `withMockServer` points the document at a running mock; `mockRequestPath` accepts only requests
 *   under the mock's base URL;
 * - `OpenApiTestDriveFrame` draws a sandboxed, no-same-origin iframe, posts the parsed document once the
 *   page is ready (Try it out off without a mock, on with one — Swagger UI only), sends a request under
 *   the mock through the try proxy and answers the page, refuses any other request without a fetch, and
 *   reports a file it cannot show.
 */

import React from 'react';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import {
  countOperations,
  LARGE_SPEC_OPERATIONS,
  mockRequestPath,
  parseOpenApiDocument,
  withMockServer,
} from '../src/app/components/ade/dashboard/export/openApiTestDrive';
import { OpenApiTestDriveFrame } from '../src/app/components/ade/dashboard/export/OpenApiTestDriveFrame';
import { TestDrivePanel } from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const SPEC = {
  openapi: '3.1.0',
  info: { title: 'Pets', version: '1.0.0' },
  paths: { '/pets': { get: { responses: {} }, post: { responses: {} } }, '/pets/{id}': { get: { responses: {} }, parameters: [] } },
};
const TEXT = JSON.stringify(SPEC);
const MOCK = { id: 'mock-1', baseUrl: 'https://rest.example/v1/mock/mock-1' };

describe('parseOpenApiDocument', () => {
  it('reads JSON and YAML, 3.x and 2.0, and counts operations', () => {
    const json = parseOpenApiDocument(TEXT);
    expect(json).toEqual({ ok: true, document: { spec: SPEC, version: '3.1.0', operations: 3, large: false } });
    const yaml = parseOpenApiDocument('swagger: "2.0"\ninfo:\n  title: Pets\n  version: "1"\npaths: {}\n');
    expect(yaml.ok && yaml.document.version).toBe('2.0');
    expect(countOperations({ paths: { '/a': { get: {}, summary: 'x', trace: {} } } })).toBe(2);
  });

  it('flags a large document', () => {
    const paths = Object.fromEntries(
      Array.from({ length: LARGE_SPEC_OPERATIONS + 1 }, (_, i) => [`/r${i}`, { get: { responses: {} } }]),
    );
    const large = parseOpenApiDocument(JSON.stringify({ openapi: '3.0.3', info: {}, paths }));
    expect(large.ok && large.document).toMatchObject({ operations: LARGE_SPEC_OPERATIONS + 1, large: true });
  });

  it('says why a file is not an OpenAPI document', () => {
    expect(parseOpenApiDocument('{not json')).toMatchObject({ ok: false, error: expect.stringContaining('not valid JSON or YAML') });
    expect(parseOpenApiDocument('type Query { a: Int }')).toMatchObject({ ok: false });
    expect(parseOpenApiDocument('{"asyncapi":"3.0.0"}')).toMatchObject({ ok: false, error: expect.stringContaining('no `openapi`') });
    expect(parseOpenApiDocument('[1, 2]')).toMatchObject({ ok: false });
  });
});

describe('the mock', () => {
  it('points the document at the mock', () => {
    expect(withMockServer(SPEC, MOCK.baseUrl).servers).toEqual([{ url: MOCK.baseUrl, description: 'Test-drive mock server' }]);
    expect(withMockServer({ swagger: '2.0' }, MOCK.baseUrl)).toMatchObject({
      schemes: ['https'], host: 'rest.example', basePath: '/v1/mock/mock-1',
    });
    expect(SPEC).not.toHaveProperty('servers');
  });

  it('accepts only requests under the mock', () => {
    expect(mockRequestPath(`${MOCK.baseUrl}/pets?limit=2`, MOCK.baseUrl)).toBe('/pets?limit=2');
    expect(mockRequestPath(MOCK.baseUrl, MOCK.baseUrl)).toBe('/');
    expect(mockRequestPath(`${MOCK.baseUrl}/`, `${MOCK.baseUrl}/`)).toBe('/');
    expect(mockRequestPath('https://rest.example/v1/mock/mock-10/pets', MOCK.baseUrl)).toBeNull();
    expect(mockRequestPath('https://evil.example/v1/mock/mock-1/pets', MOCK.baseUrl)).toBeNull();
    expect(mockRequestPath('https://rest.example/v1/admin', MOCK.baseUrl)).toBeNull();
    expect(mockRequestPath('not a url', MOCK.baseUrl)).toBeNull();
  });
});

describe('OpenApiTestDriveFrame', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, status: 200, headers: { 'content-type': 'application/json' }, body: '[]' }),
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  function mount(props: Partial<React.ComponentProps<typeof OpenApiTestDriveFrame>> = {}) {
    render(<OpenApiTestDriveFrame viewer="swagger-ui" text={TEXT} {...props} />);
    const frame = screen.getByTestId(`openapi-test-drive-frame-${props.viewer ?? 'swagger-ui'}`) as HTMLIFrameElement;
    const posted: Record<string, unknown>[] = [];
    jest.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(((message: Record<string, unknown>) => {
      posted.push(message);
    }) as never);
    const fromPage = (data: Record<string, unknown>) =>
      act(() => {
        window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow }));
      });
    return { frame, posted, fromPage };
  }

  it('draws a sandboxed iframe with no same-origin', () => {
    const { frame } = mount();
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame.getAttribute('src')).toBe('/test-drive/openapi?viewer=swagger-ui');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('posts the document once the page is ready, with Try it out off without a mock', async () => {
    const { posted, fromPage } = mount();
    expect(posted).toEqual([]);
    await fromPage({ type: 'apiome-test-drive:ready' });
    expect(posted).toEqual([{ type: 'apiome-test-drive:load', spec: SPEC, tryOut: false, large: false }]);
    expect(screen.getByText(/makes no network requests\. Start the mock server/)).toBeInTheDocument();
    await fromPage({ type: 'apiome-test-drive:rendered' });
    expect(screen.getByTestId('openapi-test-drive-swagger-ui')).toHaveAttribute('data-state', 'rendered');
  });

  it('points Swagger UI at a running mock and sends its requests through the try proxy', async () => {
    const { posted, fromPage } = mount({ mock: MOCK });
    await fromPage({ type: 'apiome-test-drive:ready' });
    expect(posted[0]).toMatchObject({ tryOut: true, spec: { servers: [{ url: MOCK.baseUrl }] } });
    await fromPage({ type: 'apiome-test-drive:request', id: 7, method: 'GET', url: `${MOCK.baseUrl}/pets?limit=1` });
    await act(async () => {});
    expect(fetchMock).toHaveBeenCalledWith('/api/export/mock/mock-1/try', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ method: 'GET', path: '/pets?limit=1' }),
    }));
    expect(posted.at(-1)).toEqual({
      type: 'apiome-test-drive:response', id: 7, status: 200, headers: { 'content-type': 'application/json' }, body: '[]',
    });
  });

  it('does not re-render the viewer for a new object describing the same mock', async () => {
    const { rerender } = render(<OpenApiTestDriveFrame viewer="swagger-ui" text={TEXT} mock={{ ...MOCK }} />);
    const frame = screen.getByTestId('openapi-test-drive-frame-swagger-ui') as HTMLIFrameElement;
    const post = jest.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((() => undefined) as never);
    await act(() => {
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'apiome-test-drive:ready' }, source: frame.contentWindow }));
    });
    rerender(<OpenApiTestDriveFrame viewer="swagger-ui" text={TEXT} mock={{ ...MOCK }} />);
    expect(post).toHaveBeenCalledTimes(1);
    rerender(<OpenApiTestDriveFrame viewer="swagger-ui" text={TEXT} mock={null} />);
    expect(post).toHaveBeenCalledTimes(2);
    expect(post.mock.calls[1][0]).toMatchObject({ tryOut: false });
  });

  it('refuses a request outside the mock, or with no mock, without sending it', async () => {
    const { posted, fromPage } = mount({ mock: MOCK });
    await fromPage({ type: 'apiome-test-drive:ready' });
    await fromPage({ type: 'apiome-test-drive:request', id: 1, method: 'GET', url: 'https://evil.example/steal' });
    await act(async () => {});
    expect(fetchMock).not.toHaveBeenCalled();
    expect(posted.at(-1)).toMatchObject({ id: 1, error: 'Only requests to the running mock server are sent.' });
  });

  it('keeps ReDoc read-only even with a mock', async () => {
    const { posted, fromPage } = mount({ viewer: 'redoc', mock: MOCK });
    await fromPage({ type: 'apiome-test-drive:ready' });
    expect(posted[0]).toMatchObject({ tryOut: false, spec: SPEC });
    await fromPage({ type: 'apiome-test-drive:request', id: 2, method: 'GET', url: `${MOCK.baseUrl}/pets` });
    await act(async () => {});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ignores messages from anywhere but its own frame', async () => {
    const { posted } = mount();
    await act(() => {
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'apiome-test-drive:ready' }, source: window }));
    });
    expect(posted).toEqual([]);
  });

  it('reports a render error, and a file that is not OpenAPI', async () => {
    const { fromPage } = mount();
    await fromPage({ type: 'apiome-test-drive:error', message: 'bad $ref' });
    expect(screen.getByRole('alert')).toHaveTextContent('bad $ref');
    render(<OpenApiTestDriveFrame viewer="redoc" text="syntax = proto3;" />);
    expect(screen.getByTestId('openapi-test-drive-unreadable')).toBeInTheDocument();
  });
});

/**
 * The documentation site's Export studio page (`apiome-docs/screens.json`, id
 * `export-studio-openapi-test-drive`) captures the Swagger UI tab from this dump:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/openapi-test-drive-frame.test.tsx -t "docs fixture"`. A static
 * dump runs no script, so the dumped frame is fed through the viewer's fragment feed (`#spec=…`) — the
 * same document the Studio would post.
 */
describe('the docs fixture', () => {
  it('renders the Swagger UI tab of an OpenAPI target', () => {
    const petstore = {
      openapi: '3.1.0',
      info: { title: 'Pet Store API', version: '1.2.0', description: 'Exported from Apiome.' },
      paths: {
        '/pets': {
          get: { tags: ['pets'], operationId: 'listPets', summary: 'List pets', responses: { '200': { description: 'The pets' } } },
          post: { tags: ['pets'], operationId: 'createPet', summary: 'Create a pet', responses: { '201': { description: 'Created' } } },
        },
        '/pets/{petId}': {
          get: {
            tags: ['pets'], operationId: 'getPet', summary: 'Get a pet',
            parameters: [{ name: 'petId', in: 'path', required: true, schema: { type: 'string' } }],
            responses: { '200': { description: 'The pet' }, '404': { description: 'Not found' } },
          },
          delete: {
            tags: ['pets'], operationId: 'deletePet', summary: 'Delete a pet',
            parameters: [{ name: 'petId', in: 'path', required: true, schema: { type: 'string' } }],
            responses: { '204': { description: 'Deleted' } },
          },
        },
      },
    };
    const tools = [
      { kind: 'swagger-ui', label: 'Swagger UI', server_side: false },
      { kind: 'redoc', label: 'ReDoc', server_side: false },
      { kind: 'toolchain', label: 'redocly lint', server_side: true, available: false,
        unavailable_reason: 'The redocly toolchain is not installed on this server.' },
      { kind: 'mock-server', label: 'Mock server', server_side: true },
    ];
    render(
      <TestDrivePanel tools={tools} targetKey="openapi" renderers={{
        'swagger-ui': () => <OpenApiTestDriveFrame viewer="swagger-ui" text={JSON.stringify(petstore)} />,
        redoc: () => null,
        toolchain: () => null,
        'mock-server': () => null,
      }} />,
    );
    const frame = screen.getByTestId('openapi-test-drive-frame-swagger-ui');
    frame.setAttribute('src', `${frame.getAttribute('src')}#spec=${encodeURIComponent(JSON.stringify(petstore))}`);
    writeA11yFixture('export-studio-openapi-test-drive', document.body.firstElementChild!.outerHTML);
  });
});

/**
 * The GraphiQL test drive's page and Studio frame — MFX-44.3 (#4369).
 *
 * - the page (`graphiqlViewerHtml`) loads only the self-hosted bundle, under a policy with no inline
 *   script and no network (the route that serves it: `graphql-test-drive-route.test.ts`);
 * - the page script (`lib/test-drive/graphiql-app.tsx`, GraphiQL stubbed) posts `ready`, draws GraphiQL
 *   over the schema itself (docs and autocomplete need no introspection request) with an example query
 *   and a fetcher that answers from the mock, says "Mock data", reports SDL it cannot read, reads the
 *   fragment feed, and listens to its parent only;
 * - `GraphQLTestDriveFrame` draws a sandboxed, no-same-origin iframe, posts the SDL and the app's
 *   appearance once the page is ready, labels the answers as mock data, reports a page error, ignores
 *   other windows, and shows a notice instead of GraphiQL for invalid SDL.
 */

import React from 'react';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { FRAGMENT_SDL_MAX_CHARS, graphiqlViewerCsp, graphiqlViewerHtml } from '../lib/test-drive/graphiql-viewer';
import { GraphQLTestDriveFrame } from '../src/app/components/ade/dashboard/export/GraphQLTestDriveFrame';
import { TestDrivePanel } from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { appAppearance } from '../src/app/components/ade/dashboard/export/graphqlTestDrive';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const SDL = 'type Pet { id: ID! name: String! }\ntype Query { pets: [Pet!]! }';

describe('the GraphiQL page', () => {
  it('loads only the self-hosted bundle, under a no-network policy', () => {
    const html = graphiqlViewerHtml('4.1.2-16.15.0');
    expect(html).toContain('<script src="/test-drive/graphiql/graphiql-test-drive.js?v=4.1.2-16.15.0"></script>');
    expect(html).toContain('<link rel="stylesheet" href="/test-drive/graphiql/graphiql-test-drive.css?v=4.1.2-16.15.0">');
    expect(html).toContain(`data-fragment-max="${FRAGMENT_SDL_MAX_CHARS}"`);
    expect(html).not.toMatch(/<script>/);
    const csp = graphiqlViewerCsp();
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("script-src 'self';");
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toContain("frame-ancestors 'self'");
  });
});

describe('the GraphiQL page script', () => {
  type GraphiQLStubProps = {
    schema: unknown;
    defaultQuery: string;
    response: string;
    fetcher: (params: { query: string }) => Promise<unknown>;
    forcedTheme?: string;
    storage: { getItem(key: string): string | null };
    children?: React.ReactNode;
  };
  /** Records each render of the stubbed GraphiQL, with its props. */
  const graphiqlRendered = jest.fn<(props: GraphiQLStubProps) => void>();
  const lastProps = () => graphiqlRendered.mock.calls.at(-1)?.[0] ?? null;
  let posted: Record<string, unknown>[];

  /** Load the page script into a fresh page, with GraphiQL stubbed out. */
  async function loadPage(hash = '') {
    document.body.innerHTML = '<p id="test-drive-status">Waiting…</p><div id="test-drive-root"></div>';
    document.body.dataset.fragmentMax = String(FRAGMENT_SDL_MAX_CHARS);
    window.history.replaceState(null, '', `/test-drive/graphql${hash}`);
    graphiqlRendered.mockClear();
    posted = [];
    // In jsdom the page is its own parent; record what it posts instead of delivering it.
    jest.spyOn(window, 'postMessage').mockImplementation(((message: Record<string, unknown>) => {
      posted.push(message);
    }) as never);
    jest.resetModules();
    jest.doMock('graphiql', () => {
      function GraphiQL(props: GraphiQLStubProps) {
        graphiqlRendered(props);
        return <div data-testid="graphiql-stub" data-theme={props.forcedTheme ?? 'system'}>{props.children}</div>;
      }
      GraphiQL.Logo = function Logo({ children }: { children: React.ReactNode }) {
        return <div data-testid="graphiql-logo">{children}</div>;
      };
      return { GraphiQL };
    });
    await act(async () => {
      await import('../lib/test-drive/graphiql-app');
    });
  }

  /** A message from the Studio. */
  const fromStudio = (data: Record<string, unknown>, source: Window = window) =>
    act(async () => {
      window.dispatchEvent(new MessageEvent('message', { data, source }));
    });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.dontMock('graphiql');
  });

  it('posts ready, then draws GraphiQL over the schema and its mock', async () => {
    await loadPage();
    expect(posted).toEqual([{ type: 'apiome-test-drive:ready' }]);
    await fromStudio({ type: 'apiome-test-drive:load', sdl: SDL, theme: 'dark' });
    expect(posted.at(-1)).toEqual({ type: 'apiome-test-drive:rendered' });
    // The script renders through its own (freshly loaded) React, so wait for the DOM rather than act.
    expect(await screen.findByTestId('graphiql-stub')).toHaveAttribute('data-theme', 'dark');
    expect(screen.getByTestId('graphiql-logo')).toHaveTextContent('Mock data');
    expect(document.getElementById('test-drive-status')).not.toBeVisible();
    expect(lastProps()!.schema).toBeTruthy();
    expect(lastProps()!.defaultQuery).toContain('pets {\n    id\n    name\n  }');
    expect(lastProps()!.storage.getItem('graphiql:tabState')).toBeNull();
    // The example query arrives already answered with mock data.
    expect(JSON.parse(lastProps()!.response)).toEqual({
      data: { pets: [{ id: expect.stringMatching(/^id-/), name: 'Example text' }, { id: expect.stringMatching(/^id-/), name: 'Example text' }] },
    });
    const result = await lastProps()!.fetcher({ query: '{ pets { name } }' });
    expect(result).toEqual({ data: { pets: [{ name: 'Example text' }, { name: 'Example text' }] } });
  });

  it('reports SDL it cannot read', async () => {
    await loadPage();
    await fromStudio({ type: 'apiome-test-drive:load', sdl: 'type Query {' });
    expect(posted.at(-1)).toMatchObject({ type: 'apiome-test-drive:error', message: expect.stringContaining('not valid GraphQL SDL') });
    expect(document.getElementById('test-drive-status')).toHaveTextContent('not valid GraphQL SDL');
    expect(screen.queryByTestId('graphiql-stub')).toBeNull();
  });

  it('reads the fragment feed, following the system theme', async () => {
    await loadPage(`#sdl=${encodeURIComponent(SDL)}`);
    expect(await screen.findByTestId('graphiql-stub')).toHaveAttribute('data-theme', 'system');
    expect(posted).toEqual([{ type: 'apiome-test-drive:ready' }, { type: 'apiome-test-drive:rendered' }]);
  });

  it('listens to its parent only', async () => {
    await loadPage();
    const other = { postMessage: () => undefined } as unknown as Window;
    await fromStudio({ type: 'apiome-test-drive:load', sdl: SDL }, other);
    expect(screen.queryByTestId('graphiql-stub')).toBeNull();
  });
});

describe('GraphQLTestDriveFrame', () => {
  function mount(sdl = SDL) {
    render(<GraphQLTestDriveFrame sdl={sdl} />);
    const frame = screen.getByTestId('graphql-test-drive-frame') as HTMLIFrameElement;
    const posted: Record<string, unknown>[] = [];
    jest.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(((message: Record<string, unknown>) => {
      posted.push(message);
    }) as never);
    const fromPage = (data: Record<string, unknown>, source: Window | null = frame.contentWindow) =>
      act(() => {
        window.dispatchEvent(new MessageEvent('message', { data, source }));
      });
    return { frame, posted, fromPage };
  }

  afterEach(() => {
    document.documentElement.style.colorScheme = '';
  });

  it('draws a sandboxed iframe with no same-origin, labelled as mock data', () => {
    const { frame } = mount();
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame).toHaveAttribute('src', '/test-drive/graphql');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
    expect(screen.getByTestId('graphql-test-drive-mock-label')).toHaveTextContent('Mock data');
    expect(screen.getByTestId('graphql-test-drive')).toHaveTextContent('2 types · 1 query.');
  });

  it("posts the SDL and the app's appearance once the page is ready", async () => {
    document.documentElement.style.colorScheme = 'dark';
    const { posted, fromPage } = mount();
    expect(posted).toEqual([]);
    await fromPage({ type: 'apiome-test-drive:ready' });
    expect(posted).toEqual([{ type: 'apiome-test-drive:load', sdl: SDL, theme: 'dark' }]);
    await fromPage({ type: 'apiome-test-drive:rendered' });
    expect(screen.getByTestId('graphql-test-drive')).toHaveAttribute('data-state', 'rendered');
  });

  it('reports a page error', async () => {
    const { fromPage } = mount();
    await fromPage({ type: 'apiome-test-drive:error', message: 'The schema could not be mocked: boom' });
    expect(screen.getByRole('alert')).toHaveTextContent('could not be mocked: boom');
    expect(screen.getByTestId('graphql-test-drive')).toHaveAttribute('data-state', 'error');
  });

  it('ignores messages from anywhere but its own frame', async () => {
    const { posted, fromPage } = mount();
    await fromPage({ type: 'apiome-test-drive:ready' }, window);
    expect(posted).toEqual([]);
  });

  it('shows a notice instead of GraphiQL for invalid SDL', () => {
    render(<GraphQLTestDriveFrame sdl="type Query { a: Missing }" />);
    expect(screen.getByTestId('graphql-test-drive-unreadable')).toHaveTextContent('Missing');
    expect(screen.queryByTestId('graphql-test-drive-frame')).toBeNull();
  });
});

describe('appAppearance', () => {
  it("reads the app's painted appearance, or null", () => {
    const root = document.createElement('html');
    expect(appAppearance(root)).toBeNull();
    root.style.colorScheme = 'light';
    expect(appAppearance(root)).toBe('light');
    expect(appAppearance(null)).toBeNull();
  });
});

/**
 * The documentation site's Export studio page (`apiome-docs/screens.json`, id
 * `export-studio-graphql-test-drive`) captures the GraphiQL tab from this dump:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/graphql-test-drive-frame.test.tsx -t "docs fixture"`. A static
 * dump runs no script, so the dumped frame is fed through the page's fragment feed (`#sdl=…`) — the
 * same SDL the Studio would post — and follows the captured theme.
 */
describe('the docs fixture', () => {
  it('renders the GraphiQL tab of a GraphQL target', () => {
    const petstore = [
      '"""A pet in the store."""',
      'type Pet {',
      '  id: ID!',
      '  name: String!',
      '  status: PetStatus!',
      '  tags: [String!]!',
      '  born: DateTime',
      '}',
      '',
      'enum PetStatus {',
      '  AVAILABLE',
      '  PENDING',
      '  SOLD',
      '}',
      '',
      'scalar DateTime',
      '',
      'type Query {',
      '  """List pets."""',
      '  pets(limit: Int = 20): [Pet!]!',
      '  """Get a pet."""',
      '  pet(id: ID!): Pet',
      '}',
      '',
      'input NewPet {',
      '  name: String!',
      '  status: PetStatus = AVAILABLE',
      '}',
      '',
      'type Mutation {',
      '  """Create a pet."""',
      '  createPet(input: NewPet!): Pet!',
      '}',
      '',
    ].join('\n');
    const tools = [
      { kind: 'graphiql', label: 'GraphiQL', server_side: false },
      { kind: 'mock-server', label: 'Mock server', server_side: true, available: false,
        unavailable_reason: 'Export test-drive mock servers are disabled on this server.' },
    ];
    render(
      <TestDrivePanel tools={tools} targetKey="graphql" renderers={{
        graphiql: () => <GraphQLTestDriveFrame sdl={petstore} />,
        'mock-server': () => null,
      }} />,
    );
    const frame = screen.getByTestId('graphql-test-drive-frame');
    frame.setAttribute('src', `${frame.getAttribute('src')}#sdl=${encodeURIComponent(petstore)}`);
    writeA11yFixture('export-studio-graphql-test-drive', document.body.firstElementChild!.outerHTML);
  });
});

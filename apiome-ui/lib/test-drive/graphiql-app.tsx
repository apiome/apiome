/**
 * The GraphiQL test-drive page's script — MFX-44.3 (#4369).
 *
 * Bundled with React, GraphiQL, `graphql` and `@graphql-tools/mock` into
 * `public/test-drive/graphiql/graphiql-test-drive.js` by `scripts/build-test-drive-graphiql.mjs`, and
 * loaded by the page `graphiql-viewer.ts` builds. It is the whole page: it waits for the SDL, builds
 * the schema and its mock resolvers, and draws GraphiQL over them. GraphiQL is handed the schema
 * itself, so the docs explorer and autocomplete need no introspection request, and its fetcher runs
 * every query in this page — nothing is sent anywhere (the page's CSP has `connect-src 'none'`). The first query arrives already answered, so mock data shows at once.
 *
 * Messages (all `type`s prefixed `apiome-test-drive:`) go to and come from the parent window only:
 * the page posts `ready`, then `rendered` or `error` (`message`); the Studio posts `load` (`sdl`,
 * `theme`). A small SDL can come in the URL fragment instead (`#sdl=…&theme=…`).
 */

import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { GraphiQL } from 'graphiql';
import type { GraphQLSchema } from 'graphql';
import 'graphiql/style.css';
import './graphiql-app.css';

import { buildMockSchema, executeMock, type MockGraphQLParams } from './graphql-mock';
import { exampleQuery, readGraphQLSdl } from './graphql-sdl';

/** The prefix of every message the page and the Studio exchange (same as the OpenAPI viewer's). */
const PREFIX = 'apiome-test-drive:';

/** The GraphiQL theme the Studio asks for; `null` follows the system setting. */
type ViewerTheme = 'light' | 'dark' | null;

/** A schema ready for GraphiQL, or why the SDL cannot be explored. */
type Prepared =
  | { ok: true; schema: GraphQLSchema; mocked: GraphQLSchema; query: string; response: string }
  | { ok: false; error: string };

/**
 * Post a message to the Studio.
 *
 * @param type The kind, without the prefix.
 * @param extra Its fields.
 */
function post(type: string, extra: Record<string, unknown> = {}): void {
  window.parent.postMessage({ type: `${PREFIX}${type}`, ...extra }, '*');
}

/**
 * An in-memory store for GraphiQL's tabs and settings. The sandbox has an opaque origin, so
 * `localStorage` throws; nothing needs to outlive the tab anyway.
 *
 * @returns A fresh, empty store.
 */
function memoryStorage() {
  const items = new Map<string, string>();
  return {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
    clear: () => items.clear(),
    get length() {
      return items.size;
    },
  };
}

/**
 * Read the SDL, build its mock, and answer a first query with it.
 *
 * @param sdl The emitted file's text.
 * @returns The schema, its mock, a first query and its mock answer (so the response pane shows mock
 *   data from the start), or the reason the schema cannot be explored.
 */
async function prepare(sdl: string): Promise<Prepared> {
  const read = readGraphQLSdl(sdl);
  if (!read.ok) return read;
  try {
    const mocked = buildMockSchema(read.schema);
    const query = exampleQuery(read.schema);
    const response = JSON.stringify(await executeMock(mocked, { query }), null, 2);
    return { ok: true, schema: read.schema, mocked, query, response };
  } catch (error) {
    return { ok: false, error: `The schema could not be mocked: ${error instanceof Error ? error.message : String(error)}` };
  }
}

/** GraphiQL over one schema's mock. */
function TestDrive({ prepared, theme }: { prepared: Extract<Prepared, { ok: true }>; theme: ViewerTheme }) {
  // One store per mount, and a new schema remounts (`key`): a new file starts from its own example
  // query, not the last file's tabs.
  const [storage] = useState(memoryStorage);
  const fetcher = useMemo(() => (params: MockGraphQLParams) => executeMock(prepared.mocked, params), [prepared]);
  return (
    <GraphiQL
      schema={prepared.schema}
      fetcher={fetcher}
      defaultQuery={prepared.query}
      response={prepared.response}
      storage={storage}
      forcedTheme={theme ?? undefined}
      isHeadersEditorEnabled={false}
      shouldPersistHeaders={false}
    >
      <GraphiQL.Logo>
        <span className="test-drive-mock-label">Mock data</span>
      </GraphiQL.Logo>
    </GraphiQL>
  );
}

const status = document.getElementById('test-drive-status') as HTMLElement;
const container = document.getElementById('test-drive-root') as HTMLElement;
let root: Root | null = null;

/**
 * Draw GraphiQL for an SDL, or say why it cannot be.
 *
 * @param sdl The emitted file's text.
 * @param theme The theme to force, or null for the system's.
 */
async function render(sdl: string, theme: ViewerTheme): Promise<void> {
  const prepared = await prepare(sdl);
  if (!prepared.ok) {
    root?.unmount();
    root = null;
    status.textContent = prepared.error;
    status.hidden = false;
    post('error', { message: prepared.error });
    return;
  }
  status.hidden = true;
  root ??= createRoot(container);
  root.render(<TestDrive key={sdl} prepared={prepared} theme={theme} />);
  post('rendered');
}

/** The theme named in a message or the fragment, or null. */
function themeOf(value: unknown): ViewerTheme {
  return value === 'light' || value === 'dark' ? value : null;
}

window.addEventListener('message', (event) => {
  if (event.source !== window.parent) return;
  const message = (event.data ?? {}) as Record<string, unknown>;
  if (message.type === `${PREFIX}load` && typeof message.sdl === 'string') void render(message.sdl, themeOf(message.theme));
});

// The fragment feed: a small SDL in the URL fragment, which never reaches the server.
const fragment = new URLSearchParams(window.location.hash.slice(1));
const fragmentSdl = fragment.get('sdl');
const fragmentMax = Number(document.body.dataset.fragmentMax ?? 0);
if (fragmentSdl && fragmentSdl.length <= fragmentMax) void render(fragmentSdl, themeOf(fragment.get('theme')));
post('ready');

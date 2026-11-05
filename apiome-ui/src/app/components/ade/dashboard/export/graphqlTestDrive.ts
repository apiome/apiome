/**
 * The Studio half of the GraphQL test drive (GraphiQL) — MFX-44.3 (#4369).
 *
 * The emitted SDL is read here first, so a file that is not a valid schema shows a notice instead of
 * an empty GraphiQL, then posted into the sandboxed page (`/test-drive/graphql`, see
 * `lib/test-drive/graphiql-viewer.ts`), which builds the mock and runs every query itself.
 */

import { GRAPHIQL_VIEWER_PATH } from '@lib/test-drive/graphiql-viewer';

export { readGraphQLSdl, type GraphQLSchemaSummary, type GraphQLSdlResult } from '@lib/test-drive/graphql-sdl';

/** The GraphiQL theme to force: the app's painted appearance, or null to follow the system. */
export type GraphiqlTheme = 'light' | 'dark' | null;

/**
 * The GraphiQL page's URL.
 *
 * @returns The iframe's `src`.
 */
export function graphiqlViewerSrc(): string {
  return GRAPHIQL_VIEWER_PATH;
}

/**
 * The appearance the app is painted in, so GraphiQL matches it.
 *
 * @param root The document element (the theme provider writes `style.color-scheme` on it).
 * @returns `light` or `dark`, or null when the app has not said.
 */
export function appAppearance(root: HTMLElement | null | undefined): GraphiqlTheme {
  const scheme = root?.style.colorScheme;
  return scheme === 'light' || scheme === 'dark' ? scheme : null;
}

/**
 * The note's count of what the schema declares, e.g. `12 types · 4 queries · 2 mutations`.
 *
 * @param summary The schema summary.
 * @returns The counts that are not zero (types and queries always).
 */
export function schemaSummaryText(summary: { types: number; queries: number; mutations: number; subscriptions: number }): string {
  const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  const parts = [count(summary.types, 'type'), count(summary.queries, 'query', 'queries')];
  if (summary.mutations) parts.push(count(summary.mutations, 'mutation'));
  if (summary.subscriptions) parts.push(count(summary.subscriptions, 'subscription'));
  return parts.join(' · ');
}

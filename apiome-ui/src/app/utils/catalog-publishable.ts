/**
 * Project-vs-Catalog publishability predicate (MFI-23.8, #4017).
 *
 * A *catalog item* is the `publishable = false` slice of projects (MFI-23.1): an OpenAPI-worthy
 * *non*-OpenAPI import (gRPC, GraphQL, AsyncAPI, …) that may be incomplete and is therefore never a
 * publish candidate. The UI uses this single predicate to decide whether to surface any Publish
 * affordance; REST enforces the same rule server-side so a direct API call is refused regardless.
 *
 * The flag is intentionally interpreted as "publishable unless explicitly false": older or partial
 * payloads that omit `publishable` (and ordinary OpenAPI/Swagger projects, which default to `true`)
 * remain publishable, while only an explicit `publishable === false` withholds the affordance.
 */

/** The minimal shape needed to decide publishability — just the `publishable` flag. */
export interface PublishableProjectLike {
  publishable?: boolean | null;
}

/**
 * Whether a project may be published.
 *
 * @param project The project (or `undefined`/`null` when it cannot be resolved).
 * @returns `false` only when the project is a catalog item (`publishable === false`); `true`
 *   otherwise, including when the project is unknown or the flag is absent.
 */
export function isProjectPublishable(
  project: PublishableProjectLike | undefined | null,
): boolean {
  return project ? project.publishable !== false : true;
}

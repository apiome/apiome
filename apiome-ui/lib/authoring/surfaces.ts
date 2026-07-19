/**
 * Authoring surfaces: the secondary navigation shared by every screen inside
 * the `/ade/authoring` route group (UXE-1.2).
 *
 * The suite dropdown (UXE-1.1) is how you *enter* Authoring; this is how you
 * move *within* it. Both read from the same route constants so a destination
 * can never drift between the two.
 */

import { UI_AUTHORING_ROUTES } from '../studio-routes';

/** Identifier of an Authoring surface. */
export type AuthoringSurfaceId = 'overview' | 'scribe' | 'slate' | 'releases' | 'insights';

/**
 * Delivery state of a surface.
 *
 * `available` surfaces do their real work. `planned` surfaces render inside the
 * shell and explain what is coming, so scope and navigation stay continuous
 * instead of dead-ending on a 404 before UXE-2.x lands.
 */
export type AuthoringSurfaceStatus = 'available' | 'planned';

/** One destination in the Authoring secondary navigation. */
export type AuthoringSurface = {
  id: AuthoringSurfaceId;
  label: string;
  /** One line describing the surface, used in nav and the command palette. */
  description: string;
  /** Absolute route path, without scope parameters. */
  path: string;
  /** Lucide icon name, resolved on the client. */
  icon: string;
  /** License flag required to use the surface, when it is gated. */
  featureFlag?: string;
  status: AuthoringSurfaceStatus;
  /** Ticket that will deliver a `planned` surface. Shown in its placeholder. */
  plannedIn?: string;
};

/** Ordered Authoring destinations. Mirrors the suite dropdown order. */
export const AUTHORING_SURFACES: readonly AuthoringSurface[] = [
  {
    id: 'overview',
    label: 'Overview',
    description: 'Coverage, releases, delivery and next actions',
    path: UI_AUTHORING_ROUTES.root,
    icon: 'Compass',
    status: 'available',
  },
  {
    id: 'scribe',
    label: 'Scribe',
    description: 'AI-assisted content and guide workspace',
    path: UI_AUTHORING_ROUTES.scribe,
    icon: 'PenTool',
    featureFlag: 'scribe',
    status: 'planned',
    plannedIn: 'UXE-2.2',
  },
  {
    id: 'slate',
    label: 'Slate',
    description: 'Portal design, preview and publishing',
    path: UI_AUTHORING_ROUTES.slate,
    icon: 'Layers',
    featureFlag: 'slate',
    status: 'planned',
    plannedIn: 'UXE-2.3',
  },
  {
    id: 'releases',
    label: 'Releases',
    description: 'Previews, production, promotion and rollback',
    path: UI_AUTHORING_ROUTES.releases,
    icon: 'Rocket',
    featureFlag: 'hosted',
    status: 'planned',
    plannedIn: 'UXE-2.4',
  },
  {
    id: 'insights',
    label: 'Insights',
    description: 'Content, search, API, delivery and cost signals',
    path: UI_AUTHORING_ROUTES.insights,
    icon: 'BarChart3',
    featureFlag: 'hosted',
    status: 'planned',
    plannedIn: 'UXE-2.x',
  },
] as const;

/**
 * Find a surface by id.
 *
 * @param id - Surface id.
 * @returns The surface, or `undefined` when `id` is unknown.
 */
export function getAuthoringSurface(id: string): AuthoringSurface | undefined {
  return AUTHORING_SURFACES.find((surface) => surface.id === id);
}

/**
 * True when `pathname` is inside the Authoring route group.
 *
 * @param pathname - Current route.
 */
export function isAuthoringPathname(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  const root = UI_AUTHORING_ROUTES.root;
  return pathname === root || pathname.startsWith(`${root}/`);
}

/**
 * Resolve which surface a route belongs to.
 *
 * Child routes resolve to their parent surface so a nested screen (e.g. a
 * Scribe document) still highlights Scribe. Overview is only matched exactly,
 * because its path is the prefix of every other surface.
 *
 * @param pathname - Current route.
 * @returns The owning surface, or `undefined` outside the route group.
 */
export function resolveAuthoringSurface(
  pathname: string | null | undefined
): AuthoringSurface | undefined {
  if (!isAuthoringPathname(pathname)) return undefined;
  const path = pathname!;

  const nested = AUTHORING_SURFACES.find(
    (surface) =>
      surface.id !== 'overview' && (path === surface.path || path.startsWith(`${surface.path}/`))
  );
  if (nested) return nested;

  return getAuthoringSurface('overview');
}

/**
 * True when a surface should render as the active nav destination.
 *
 * @param surface - Candidate surface.
 * @param pathname - Current route.
 */
export function isAuthoringSurfaceActive(
  surface: AuthoringSurface,
  pathname: string | null | undefined
): boolean {
  return resolveAuthoringSurface(pathname)?.id === surface.id;
}

/**
 * True when the viewer holds the license flags a surface requires.
 *
 * Ungated surfaces are always entitled, so Overview remains reachable and can
 * explain what the rest of Authoring needs.
 *
 * @param surface - Surface to test.
 * @param entitledFlags - License flags granted to the session.
 */
export function isAuthoringSurfaceEntitled(
  surface: AuthoringSurface,
  entitledFlags: ReadonlySet<string>
): boolean {
  return !surface.featureFlag || entitledFlags.has(surface.featureFlag);
}

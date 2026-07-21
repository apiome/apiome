import { getMainAppUrl, normalizeAppOrigin } from './app-urls';
import { getCommercialNavItems, type ExternalNavItem } from './external-links';
import { getSuiteTriggerIsActive } from './suite-contract';
import { STUDIO_APP_ROUTES, UI_STUDIO_ROUTES } from './studio-routes';

export { getMainAppUrl, normalizeAppOrigin };

/** True when this Next.js app is the standalone studio surface. */
export function isStudioSurface(): boolean {
  return process.env.NEXT_PUBLIC_APP_SURFACE === 'studio';
}

/** @deprecated Prefer getMainAppUrl() — resolved at call time for correct env in tests and SSR. */
export const MAIN_APP_URL = getMainAppUrl();

export function mainAppPath(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${getMainAppUrl()}${suffix}`;
}

export function getPlatformCoreNavItems(): ExternalNavItem[] {
  const onStudio = isStudioSurface();
  return [
    {
      id: 'home',
      label: 'Home',
      href: onStudio ? mainAppPath('/ade') : '/ade',
      external: onStudio,
    },
    {
      id: 'control-panel',
      label: 'Control Panel',
      href: onStudio ? mainAppPath('/ade/dashboard') : '/ade/dashboard',
      external: onStudio,
    },
  ];
}

/** Commercial app tabs (Suite) — pass items filtered by license entitlements. */
export function getStudioCommercialNavItems(entitledFlags: Set<string>): ExternalNavItem[] {
  return getCommercialNavItems(entitledFlags);
}

export function getPlatformNavItems(commercialNavItems: ExternalNavItem[] = []): ExternalNavItem[] {
  return [...getPlatformCoreNavItems(), ...commercialNavItems];
}

/** Nav href comes from commercial product config (NEXT_PUBLIC_STUDIO_URL). */
export function resolvePlatformNavHref(item: ExternalNavItem): string {
  return item.href;
}

function isStudioAppPathActive(pathname: string): boolean {
  if (isStudioSurface()) {
    return (
      pathname === STUDIO_APP_ROUTES.root ||
      pathname === STUDIO_APP_ROUTES.editor ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.editor}/`) ||
      pathname === STUDIO_APP_ROUTES.paths ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.paths}/`) ||
      pathname === STUDIO_APP_ROUTES.code ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.code}/`)
    );
  }
  return (
    pathname === UI_STUDIO_ROUTES.root ||
    pathname.startsWith(`${UI_STUDIO_ROUTES.root}/`)
  );
}

export function platformNavItemIsActive(item: ExternalNavItem, pathname: string | null): boolean {
  if (!pathname) return false;

  if (item.id === 'home') {
    return !isStudioSurface() && pathname === '/ade';
  }
  if (item.id === 'control-panel') {
    return !isStudioSurface() && pathname.startsWith('/ade/dashboard');
  }
  // Designer trigger: built-in studio routes, plus any contributed active check
  // from a commercial suite host (no product-specific paths live here).
  if (item.id === 'suite') {
    const contributed = getSuiteTriggerIsActive();
    return isStudioAppPathActive(pathname) || (contributed?.(pathname) ?? false);
  }

  if (item.external || item.href.startsWith('http://') || item.href.startsWith('https://')) {
    return false;
  }
  return (
    pathname === item.href ||
    (item.href !== '/ade' && pathname.startsWith(`${item.href}/`))
  );
}

export function platformProfilePath(): string {
  return isStudioSurface() ? mainAppPath('/ade/dashboard/profile') : '/ade/dashboard/profile';
}

import { getCommercialNavItems, type ExternalNavItem } from './external-links';
import { STUDIO_APP_ROUTES, UI_STUDIO_ROUTES } from './studio-routes';

const DEFAULT_MAIN_APP_URL = 'https://main.apiome.dev';

export function normalizeAppOrigin(url: string, fallback: string): string {
  const trimmed = url.trim();
  if (!trimmed) return fallback.replace(/\/+$/, '');
  return trimmed.replace(/\/+$/, '');
}

/** True when this Next.js app is the standalone studio surface. */
export function isStudioSurface(): boolean {
  return process.env.NEXT_PUBLIC_APP_SURFACE === 'studio';
}

export function getMainAppUrl(): string {
  return normalizeAppOrigin(
    process.env.NEXT_PUBLIC_MAIN_APP_URL || '',
    DEFAULT_MAIN_APP_URL
  );
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
  if (item.id === 'suite') {
    return isStudioAppPathActive(pathname);
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

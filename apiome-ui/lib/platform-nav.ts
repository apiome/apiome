import { getExternalNavItems, type ExternalNavItem } from './external-links';
import { STUDIO_APP_ROUTES, UI_STUDIO_ROUTES } from './studio-routes';

const DEFAULT_MAIN_APP_URL = 'https://app.apiome.app';

export function normalizeAppOrigin(url: string, fallback: string): string {
  const trimmed = url.trim();
  if (!trimmed) return fallback.replace(/\/+$/, '');
  return trimmed.replace(/\/+$/, '');
}

export const MAIN_APP_URL = normalizeAppOrigin(
  process.env.NEXT_PUBLIC_MAIN_APP_URL || '',
  DEFAULT_MAIN_APP_URL
);

/** True when this Next.js app is the standalone studio surface. */
export function isStudioSurface(): boolean {
  return process.env.NEXT_PUBLIC_APP_SURFACE === 'studio';
}

export function mainAppPath(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${MAIN_APP_URL}${suffix}`;
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

/** Designer / Paths entries when commercial studio is enabled but external-links.json is empty. */
export function getStudioCommercialNavItems(): ExternalNavItem[] {
  const configured = getExternalNavItems();
  if (configured.length > 0) return configured;
  if (!isStudioSurface() && !process.env.NEXT_PUBLIC_STUDIO_URL?.trim()) {
    return [];
  }
  return [
    {
      id: 'designer',
      label: 'Designer',
      href: UI_STUDIO_ROUTES.editor,
      external: false,
    },
    {
      id: 'paths',
      label: 'Paths',
      href: UI_STUDIO_ROUTES.paths,
      external: false,
    },
  ];
}

export function getPlatformNavItems(): ExternalNavItem[] {
  return [...getPlatformCoreNavItems(), ...getStudioCommercialNavItems()];
}

export function resolvePlatformNavHref(item: ExternalNavItem): string {
  if (isStudioSurface()) {
    if (item.id === 'designer') return STUDIO_APP_ROUTES.editor;
    if (item.id === 'paths') return STUDIO_APP_ROUTES.paths;
    return item.href;
  }
  if (item.id === 'designer') return UI_STUDIO_ROUTES.editor;
  if (item.id === 'paths') return UI_STUDIO_ROUTES.paths;
  return item.href;
}

export function platformNavItemIsActive(item: ExternalNavItem, pathname: string | null): boolean {
  if (!pathname) return false;

  if (item.id === 'home') {
    return !isStudioSurface() && pathname === '/ade';
  }
  if (item.id === 'control-panel') {
    return !isStudioSurface() && pathname.startsWith('/ade/dashboard');
  }
  if (item.id === 'designer') {
    if (isStudioSurface()) {
      return (
        pathname === STUDIO_APP_ROUTES.editor ||
        pathname.startsWith(`${STUDIO_APP_ROUTES.editor}/`) ||
        pathname === STUDIO_APP_ROUTES.code ||
        pathname.startsWith(`${STUDIO_APP_ROUTES.code}/`)
      );
    }
    return (
      pathname === UI_STUDIO_ROUTES.editor ||
      pathname.startsWith(`${UI_STUDIO_ROUTES.editor}/`) ||
      pathname === UI_STUDIO_ROUTES.code ||
      pathname.startsWith(`${UI_STUDIO_ROUTES.code}/`)
    );
  }
  if (item.id === 'paths') {
    if (isStudioSurface()) {
      return pathname === STUDIO_APP_ROUTES.paths || pathname.startsWith(`${STUDIO_APP_ROUTES.paths}/`);
    }
    return pathname === UI_STUDIO_ROUTES.paths || pathname.startsWith(`${UI_STUDIO_ROUTES.paths}/`);
  }

  if (item.external || item.href.startsWith('http://') || item.href.startsWith('https://')) {
    return false;
  }
  if (item.isActive) return item.isActive(pathname);
  return (
    pathname === item.href ||
    (item.href !== '/ade' && pathname.startsWith(`${item.href}/`))
  );
}

export function platformProfilePath(): string {
  return isStudioSurface() ? mainAppPath('/ade/dashboard/profile') : '/ade/dashboard/profile';
}

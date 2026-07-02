/**
 * Studio main-nav active states: Designer and Paths share `/ade/studio` prefix;
 * Paths must not highlight Designer.
 */

export function isDesignerStudioNavActive(pathname: string): boolean {
  return (
    pathname === '/ade/studio' ||
    (pathname.startsWith('/ade/studio/') && !pathname.startsWith('/ade/studio/paths'))
  );
}

export function isPathsStudioNavActive(pathname: string): boolean {
  return pathname === '/ade/studio/paths' || pathname.startsWith('/ade/studio/paths/');
}

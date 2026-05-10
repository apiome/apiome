/**
 * Locale-aware, case-insensitive name order for project dropdowns.
 * Tie-breaks by id so order is stable when names collide.
 */
export function sortProjectsForSelector<T extends { name: string; id?: string | number | null }>(
  projects: T[]
): T[] {
  return [...projects].sort((a, b) => {
    const byName = a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    if (byName !== 0) return byName;
    return String(a.id ?? '').localeCompare(String(b.id ?? ''));
  });
}

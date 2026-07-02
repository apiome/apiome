/**
 * Shared tag color tokens for project-tag chips across canvas nodes (#95).
 * Used by both GroupNode (Tailwind-class approach) and ClassNode (inline-style approach).
 */

/** Maps a project-tag color name to Tailwind classes for a chip (bg + text + border). */
export function tagChipClass(color: string): string {
  const m: Record<string, string> = {
    default:
      'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100 border-gray-200 dark:border-gray-600',
    primary:
      'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-800 dark:text-indigo-200 border-indigo-200 dark:border-indigo-700',
    secondary:
      'bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-200 border-purple-200 dark:border-purple-700',
    error:
      'bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200 border-red-200 dark:border-red-700',
    warning:
      'bg-amber-100 dark:bg-amber-900/40 text-amber-900 dark:text-amber-200 border-amber-200 dark:border-amber-700',
    info:
      'bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-700',
    success:
      'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-700',
  };
  return m[color] || m.default;
}

/** Maps a project-tag color name to a Tailwind text-color class for a color dot. */
export function tagDotClass(color: string): string {
  const m: Record<string, string> = {
    default: 'text-gray-500',
    primary: 'text-indigo-500',
    secondary: 'text-purple-500',
    error: 'text-red-500',
    warning: 'text-amber-500',
    info: 'text-blue-500',
    success: 'text-emerald-500',
  };
  return m[color] || m.default;
}

/** Maps a project-tag color name to inline rgba bg/border values (used by canvas nodes with inline styles). */
export function tagInlineColors(color: string): { bg: string; border: string } {
  const m: Record<string, { bg: string; border: string }> = {
    default: { bg: 'rgba(255, 255, 255, 0.15)', border: 'rgba(255, 255, 255, 0.25)' },
    primary: { bg: 'rgba(99, 102, 241, 0.3)', border: 'rgba(99, 102, 241, 0.5)' },
    secondary: { bg: 'rgba(168, 85, 247, 0.3)', border: 'rgba(168, 85, 247, 0.5)' },
    error: { bg: 'rgba(239, 68, 68, 0.3)', border: 'rgba(239, 68, 68, 0.5)' },
    warning: { bg: 'rgba(245, 158, 11, 0.3)', border: 'rgba(245, 158, 11, 0.5)' },
    info: { bg: 'rgba(59, 130, 246, 0.3)', border: 'rgba(59, 130, 246, 0.5)' },
    success: { bg: 'rgba(16, 185, 129, 0.3)', border: 'rgba(16, 185, 129, 0.5)' },
  };
  return m[color] || m.default;
}

/**
 * Normalizes project-tag rows for group pickers. `getTagsForProject` returns `name`/`color`;
 * class-tag joins use `tag_name`/`tag_color` (#2526).
 */
export function mapProjectTagToGroupOption(t: {
  id: string;
  name?: string;
  tag_name?: string;
  color?: string;
  tag_color?: string;
}): { id: string; name: string; color: string } {
  return {
    id: t.id,
    name: t.tag_name ?? t.name ?? '',
    color: t.tag_color ?? t.color ?? 'default',
  };
}

/** Fills missing tag labels on group nodes from the project tag catalog (e.g. legacy saves, #2526).
 *  Accepts either a raw project-tag array or a prebuilt catalog Map so callers that process
 *  multiple groups can build the Map once and reuse it rather than rebuilding it per-group.
 */
export function normalizeStoredGroupTags(
  stored:
    | Array<{ id: string; name?: string; color?: string; tag_name?: string; tag_color?: string }>
    | undefined
    | null,
  projectTagsOrCatalog:
    | Array<{ id: string; name?: string; tag_name?: string; color?: string; tag_color?: string }>
    | Map<string, { id: string; name: string; color: string }>
): Array<{ id: string; name: string; color: string }> {
  if (!stored?.length) return [];
  const catalog =
    projectTagsOrCatalog instanceof Map
      ? projectTagsOrCatalog
      : new Map(projectTagsOrCatalog.map((t) => [t.id, mapProjectTagToGroupOption(t)]));
  return stored.map((t) => {
    const c = catalog.get(t.id);
    return {
      id: t.id,
      name: t.tag_name ?? t.name ?? c?.name ?? '',
      color: t.tag_color ?? t.color ?? c?.color ?? 'default',
    };
  });
}

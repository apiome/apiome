import { mapProjectTagToGroupOption } from '@/app/utils/tag-color-tokens';

export interface TagGroupPlanEntry {
  /** Display name used for the group title (from project tag catalog when available). */
  tagName: string;
  /** Representative project tag id for styling / group tag chips. */
  tagId: string;
  classIds: string[];
}

/**
 * Plans canvas groups so each tag name (shared by at least two classes) gets its own group.
 * Classes with multiple tags are assigned to at most one group: the first tag name in
 * Unicode code-point order among tag names that still need members (greedy assignment).
 * Code-point ordering is used (not localeCompare) to guarantee identical results across
 * all runtime locales.
 */
export function computeTagGroupPlan(
  classes: Array<{ id: string; tags?: Array<{ id: string; tag_name?: string; name?: string }> }>,
  projectTags: Array<{
    id: string;
    name?: string;
    tag_name?: string;
    color?: string;
    tag_color?: string;
  }>
): TagGroupPlanEntry[] {
  const catalog = new Map(projectTags.map((t) => [t.id, mapProjectTagToGroupOption(t)]));

  const byTagName = new Map<string, { tagIds: string[]; classIds: Set<string> }>();

  for (const cls of classes) {
    for (const t of cls.tags || []) {
      const opt = catalog.get(t.id);
      const name = (opt?.name ?? t.tag_name ?? t.name ?? '').trim();
      if (!name) continue;

      let bucket = byTagName.get(name);
      if (!bucket) {
        bucket = { tagIds: [], classIds: new Set<string>() };
        byTagName.set(name, bucket);
      }
      if (!bucket.tagIds.includes(t.id)) {
        bucket.tagIds.push(t.id);
      }
      bucket.classIds.add(cls.id);
    }
  }

  const sortedNames = [...byTagName.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const assigned = new Set<string>();
  const result: TagGroupPlanEntry[] = [];

  for (const name of sortedNames) {
    const bucket = byTagName.get(name)!;
    const members = [...bucket.classIds].filter((id) => !assigned.has(id));
    if (members.length < 2) continue;

    const tagId = [...bucket.tagIds].sort()[0]!;
    for (const id of members) {
      assigned.add(id);
    }
    result.push({ tagName: name, tagId, classIds: members });
  }

  return result;
}

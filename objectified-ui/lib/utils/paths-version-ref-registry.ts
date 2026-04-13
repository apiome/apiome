/**
 * Central registry for Paths / OpenAPI reuse: version classes and `$ref` to
 * `#/components/schemas/<ClassName>`. Used to validate refs without duplicating
 * schema JSON (class_id is canonical; export emits `$ref`).
 */

export interface VersionClassEntry {
  id: string;
  name: string;
}

export interface PathsVersionRefRegistry {
  readonly idToName: ReadonlyMap<string, string>;
  readonly nameSet: ReadonlySet<string>;
  refForClassId(classId: string): string | null;
  isOrphanClassId(classId: string | null | undefined): boolean;
  /** Walk arbitrary JSON and report `#/components/schemas/<name>` where `<name>` is not in this version. */
  findBrokenComponentSchemaRefs(value: unknown): Array<{ path: string; ref: string }>;
}

export function createPathsVersionRefRegistry(classes: VersionClassEntry[]): PathsVersionRefRegistry {
  const idToName = new Map(classes.map((c) => [c.id, c.name]));
  const nameSet = new Set(classes.map((c) => c.name));

  function refForClassId(classId: string): string | null {
    const name = idToName.get(classId);
    if (!name) return null;
    return `#/components/schemas/${name}`;
  }

  function isOrphanClassId(classId: string | null | undefined): boolean {
    if (!classId) return false;
    return !idToName.has(classId);
  }

  function findBrokenComponentSchemaRefs(value: unknown): Array<{ path: string; ref: string }> {
    const broken: Array<{ path: string; ref: string }> = [];

    const walk = (obj: unknown, path: string) => {
      if (obj === null || obj === undefined) return;
      if (Array.isArray(obj)) {
        obj.forEach((item, i) => walk(item, `${path}[${i}]`));
        return;
      }
      if (typeof obj !== 'object') return;

      const o = obj as Record<string, unknown>;
      if (typeof o.$ref === 'string') {
        const ref = o.$ref;
        const m = ref.match(/^#\/components\/schemas\/(.+)$/);
        if (m && !nameSet.has(m[1])) {
          broken.push({ path, ref });
        }
      }
      for (const key of Object.keys(o)) {
        walk(o[key], path ? `${path}.${key}` : key);
      }
    };

    walk(value, 'root');
    return broken;
  }

  return {
    idToName,
    nameSet,
    refForClassId,
    isOrphanClassId,
    findBrokenComponentSchemaRefs,
  };
}

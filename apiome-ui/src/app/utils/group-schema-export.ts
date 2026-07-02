import { findReferencedClasses } from '@/app/utils/openapi-schema-refs';

/**
 * Collect every class in `allClasses` that is in `rootClassIds` or referenced from them
 * (transitive `#/components/schemas/X` closure). Used for group OpenAPI export (#156).
 */
export function expandClassesForGroupExport(rootClassIds: string[], allClasses: any[]): any[] {
  const byId = new Map<string, any>((allClasses || []).map((c) => [c.id, c]));
  const included = new Set<string>();

  for (const id of rootClassIds) {
    if (byId.has(id)) included.add(id);
  }

  const byName = new Map<string, any>((allClasses || []).map((c) => [c.name, c]));

  let changed = true;
  while (changed) {
    changed = false;
    for (const id of Array.from(included)) {
      const cls = byId.get(id);
      if (!cls) continue;
      const refs = new Set<string>();

      try {
        const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : cls.schema;
        if (schema) findReferencedClasses(schema, refs);
      } catch {
        /* ignore */
      }

      for (const p of cls.properties || []) {
        try {
          const d = typeof p.data === 'string' ? JSON.parse(p.data) : p.data;
          if (d) findReferencedClasses(d, refs);
        } catch {
          /* ignore */
        }
      }

      for (const refName of refs) {
        const dep = byName.get(refName);
        if (dep && !included.has(dep.id)) {
          included.add(dep.id);
          changed = true;
        }
      }
    }
  }

  return (allClasses || []).filter((c) => included.has(c.id));
}

export function downloadTextFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

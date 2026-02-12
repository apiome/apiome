'use server';

import { createClass, addPropertyToClass } from './helper';
import { getImporter, NormalizedClass } from '../importers';
import { cookies } from 'next/headers';

export interface ImportClassesInput {
  versionId: string;
  projectId: string;
  document: any;
  selectedSchemas: string[];
  /** When true, apply naming convention to class and property names (#581) */
  applyNamingConvention?: boolean;
  /** Convention for class names (default: PascalCase) */
  classNamingConvention?: 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';
  /** Convention for property names (default: camelCase) */
  propertyNamingConvention?: 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';
  /** Optional map: schema key → class name. Applied with smart naming from schema context (#753). */
  classNameMap?: Record<string, string>;
  /** Optional prefix applied to every class name after naming convention (#755). */
  classPrefix?: string;
  /** Optional suffix applied to every class name after naming convention (#755). */
  classSuffix?: string;
}

export interface ImportClassesResult {
  success: boolean;
  importedCount?: number;
  skippedCount?: number;
  error?: string;
  importedClasses?: string[];
}

// Stable JSON stringify that sorts object keys to ensure consistent signatures
function stableStringify(obj: any): string {
  if (obj === null || obj === undefined) return JSON.stringify(obj);
  if (typeof obj !== 'object') return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return '[' + obj.map(item => stableStringify(item)).join(',') + ']';
  }
  const sortedKeys = Object.keys(obj).sort();
  const pairs = sortedKeys.map(key => JSON.stringify(key) + ':' + stableStringify(obj[key]));
  return '{' + pairs.join(',') + '}';
}

async function writeClassWithProperties(
  projectId: string,
  versionId: string,
  cls: NormalizedClass,
  propertyIdMap: Map<string, string>
) {
  const resClass = JSON.parse(await createClass(versionId, cls.name, cls.description || null, cls.schema || { type: 'object' }));
  if (!resClass.success) throw new Error(resClass.error || 'Failed to create class');
  const classId = resClass.class.id as string;

  const linkRec = async (classId: string, props: any[], parentId: string | null = null) => {
    for (const p of props || []) {
      let propertyId: string | null = null;
      const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
      if (!isReference) {
        const sig = stableStringify(p.data);
        propertyId = propertyIdMap.get(sig) || null;

        // Database constraint requires: property_id IS NOT NULL OR data contains $ref
        if (propertyId === null) {
          console.warn(`Skipping property "${p.name}" in class "${cls.name}" - no library entry found`);
          if (p.children && p.children.length) {
            console.warn(`Also skipping ${p.children.length} child properties of "${p.name}"`);
          }
          continue;
        }
      }
      const addRes = JSON.parse(
        await addPropertyToClass(classId, propertyId, p.name, p.description || null, p.data, parentId)
      );
      if (!addRes.success) throw new Error(addRes.error || 'Failed to add property');
      const newId = addRes.classProperty.id as string;
      if (p.children && p.children.length) await linkRec(classId, p.children, newId);
    }
  };

  await linkRec(classId, cls.properties || [], null);
  return classId;
}

export async function importClassesToVersion(input: ImportClassesInput): Promise<ImportClassesResult> {
  try {
    const { versionId, projectId, document, selectedSchemas } = input;

    if (!versionId || !projectId) {
      return { success: false, error: 'Version ID and Project ID are required' };
    }

    if (!selectedSchemas || selectedSchemas.length === 0) {
      return { success: false, error: 'No schemas selected for import' };
    }

    // Use OpenAPI importer to normalize the document
    const importer = getImporter('openapi');
    if (!importer) {
      return { success: false, error: 'OpenAPI importer not available' };
    }

    const norm = importer.normalize({
      document,
      options: {
        selectedSchemas,
        applyNamingConvention: input.applyNamingConvention ?? true,
        classNamingConvention: input.classNamingConvention ?? 'PascalCase',
        propertyNamingConvention: input.propertyNamingConvention ?? 'camelCase',
        classNameMap: input.classNameMap,
        classPrefix: input.classPrefix,
        classSuffix: input.classSuffix,
      },
    });
    if (norm.warnings.length) {
      console.log('Normalization warnings:', norm.warnings);
    }

    // Build property library: collect all unique non-reference properties
    const propertyMap = new Map<string, { data: any; description?: string; names: Set<string> }>();
    const propertyIdMap = new Map<string, string>(); // sig -> propertyId

    const collectProperties = (props: any[]) => {
      for (const p of props || []) {
        const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
        if (!isReference) {
          const sig = stableStringify(p.data);
          if (!propertyMap.has(sig)) {
            propertyMap.set(sig, { data: p.data, description: p.description, names: new Set<string>() });
          }
          propertyMap.get(sig)!.names.add(p.name);
        }
        if (p.children && p.children.length) collectProperties(p.children);
      }
    };

    for (const cls of norm.classes) {
      collectProperties(cls.properties || []);
    }

    // Create properties in the library via REST API (through Next.js API route)
    const cookieStore = await cookies();
    // Build cookie header string from cookies
    const cookieHeader = cookieStore.getAll()
      .map(cookie => `${cookie.name}=${cookie.value}`)
      .join('; ');
    
    // Get the base URL for API calls - use internal URL for server-side calls
    const baseUrl = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000';
    
    for (const [sig, entry] of propertyMap.entries()) {
      const primaryName = Array.from(entry.names).sort()[0];
      try {
        // Call the Next.js API route which handles authentication via session
        const headers: Record<string, string> = { 
          'Content-Type': 'application/json',
        };
        if (cookieHeader) {
          headers['Cookie'] = cookieHeader; // Forward cookies for session authentication
        }
        
        const response = await fetch(`${baseUrl}/api/properties/${projectId}`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            name: primaryName,
            description: entry.description || null,
            data: entry.data,
          }),
        });
        const res = await response.json();
        if (res.success && res.property) {
          propertyIdMap.set(sig, res.property.id);
        } else {
          console.warn(`Failed to create property "${primaryName}": ${res.error || 'Unknown error'}`);
        }
      } catch (error: any) {
        console.warn(`Failed to create property "${primaryName}": ${error.message || 'Unknown error'}`);
      }
    }

    // Import classes (importer already filtered by selectedSchemas; names may be transformed by naming convention)
    const importedClasses: string[] = [];
    let skippedCount = 0;

    for (const cls of norm.classes) {
      try {
        await writeClassWithProperties(projectId, versionId, cls, propertyIdMap);
        importedClasses.push(cls.name);
      } catch (error: any) {
        // If class already exists, skip it
        if (error.message?.includes('already exists')) {
          console.log(`Class "${cls.name}" already exists, skipping`);
          skippedCount++;
        } else {
          throw error;
        }
      }
    }

    return {
      success: true,
      importedCount: importedClasses.length,
      skippedCount,
      importedClasses,
    };
  } catch (error: any) {
    console.error('Error importing classes:', error);
    return {
      success: false,
      error: error.message || 'An error occurred during import',
    };
  }
}


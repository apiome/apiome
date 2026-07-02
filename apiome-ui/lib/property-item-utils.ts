import type { PropertyItem } from '@/app/components/ade/studio/StudioSideNav';

/**
 * Parses a JSON Schema snippet from user-edited text (AI suggestion customize flow, #272).
 */
export function parseJsonSchemaObjectText(
  schemaText: string,
): { ok: true; schema: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = schemaText.trim();
  if (!trimmed) {
    return { ok: false, error: 'Schema cannot be empty.' };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { ok: false, error: 'Schema must be valid JSON.' };
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'Schema JSON must be a JSON object.' };
  }
  return { ok: true, schema: parsed as Record<string, unknown> };
}

/**
 * Builds a PropertyItem seed from editable name, description, and schema JSON (Studio AI suggestions, #272).
 */
export function buildPropertyItemFromAiSeedForm(input: {
  name: string;
  description: string;
  schemaText: string;
}): { ok: true; item: PropertyItem } | { ok: false; error: string } {
  const nameTrim = input.name.trim();
  if (!nameTrim) {
    return { ok: false, error: 'Property name is required.' };
  }
  const schemaResult = parseJsonSchemaObjectText(input.schemaText);
  if (!schemaResult.ok) {
    return schemaResult;
  }
  const descTrim = input.description.trim();
  const item = {
    ...schemaResult.schema,
    id: '__ai_seed__',
    name: nameTrim,
  } as PropertyItem;
  // Always remove any description carried in from the schema JSON, then
  // re-apply it only if the user actually provided one in the form field.
  delete item.description;
  if (descTrim) {
    item.description = descTrim;
  }
  return { ok: true, item };
}

/**
 * Converts a PropertyItem into the reduced shape expected by the Ollama API's
 * `existing_properties` payload field (id and name stripped, description normalised).
 */
export function propertyItemToExistingApiShape(p: PropertyItem): {
  name: string;
  description: string | null;
  data: Record<string, unknown>;
} {
  const rec = p as unknown as Record<string, unknown>;
  const name = rec.name;
  const description = rec.description;
  const data = { ...rec };
  delete data.id;
  delete data.name;
  delete data.description;
  return {
    name: typeof name === 'string' ? name : String(name ?? ''),
    description: description != null && String(description).trim() ? String(description) : null,
    data,
  };
}

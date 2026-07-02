/**
 * Validate a data payload against a JSON Schema (e.g. class_schema.schema).
 * Uses Ajv with JSON Schema 2020-12 support.
 */

import Ajv, { type ErrorObject } from 'ajv';
import addFormats from 'ajv-formats';

export interface ValidationResult {
  valid: boolean;
  errors?: Array<{ path?: string; message: string }>;
}

function getDefaultAjv(): InstanceType<typeof Ajv> {
  const ajv = new Ajv({
    strictSchema: false,
    validateSchema: false, // only validate payload against schema fields, not schema meta ($id, $schema, etc.)
    addUsedSchema: false,  // do not add schemas by $id or resolve external refs
  } as object);
  // ajv-formats types expect its own bundled Ajv; cast to avoid version mismatch
  (addFormats as (ajv: unknown) => void)(ajv);
  return ajv;
}

/**
 * Validate payload against a JSON Schema (draft 2020-12 supported).
 */
export function validatePayloadAgainstSchema(
  payload: unknown,
  schema: object
): ValidationResult {
  const ajv = getDefaultAjv();
  try {
    const validate = ajv.compile(schema);
    const valid = validate(payload);
    if (valid) {
      return { valid: true };
    }
    const errors: Array<{ path?: string; message: string }> = (validate.errors ?? []).map(
      (err: ErrorObject) => {
        const e = err as { instancePath?: string; message?: string; params?: { propertyName?: string } };
        return {
          path: e.instancePath || (e.params?.propertyName ?? undefined),
          message: e.message ?? 'Validation failed',
        };
      }
    );
    return { valid: false, errors };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Schema compilation failed';
    return { valid: false, errors: [{ message }] };
  }
}

/**
 * Stub for validating a data payload against a JSON Schema (e.g. class_schema.schema).
 * Production validation will use class_schema.schema (JSON Schema 2020-12) for the selected class.
 * This stub always returns valid; replace with ajv or similar when implementing insert.
 */

export interface ValidationResult {
  valid: boolean;
  errors?: Array<{ path?: string; message: string }>;
}

/**
 * Validate payload against a JSON Schema. Stub implementation.
 */
export function validatePayloadAgainstSchema(
  _payload: unknown,
  _schema: object
): ValidationResult {
  return { valid: true };
}

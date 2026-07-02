'use server';

/**
 * OpenAPI JSON Schema validation runs only on the server (#2655 / P-16).
 * `@seriousme/openapi-schema-validator` depends on Node built-ins (`fs`) and must not be imported from Client Components.
 */

import { Validator } from '@seriousme/openapi-schema-validator';
import {
  formatSchemaValidatorErrors,
  isPlainObject,
  validateOpenAPISemantics,
  VALIDATOR_NOTE,
  type OpenAPIExportIssue,
  type OpenAPIExportValidationResult,
} from './openapi-export-validation';

export async function validateOpenAPIExport(spec: unknown): Promise<OpenAPIExportValidationResult> {
  const errors: OpenAPIExportIssue[] = [];
  const warnings: OpenAPIExportIssue[] = [];
  let schemaValidationCompleted = false;

  if (!isPlainObject(spec)) {
    return {
      errors: [{ severity: 'error', message: 'Specification must be a JSON object.' }],
      warnings: [],
      schemaValidationCompleted: false,
      validatorNote: VALIDATOR_NOTE,
    };
  }

  const semantic = validateOpenAPISemantics(spec);
  for (const i of semantic) {
    if (i.severity === 'error') errors.push(i);
    else warnings.push(i);
  }

  try {
    const validator = new Validator();
    const res = await validator.validate(spec as Record<string, unknown>);
    schemaValidationCompleted = true;
    if (!res.valid && res.errors !== undefined) {
      errors.push(...formatSchemaValidatorErrors(res.errors));
    }
  } catch (e) {
    errors.push({
      severity: 'error',
      message: `OpenAPI schema validation could not run: ${e instanceof Error ? e.message : String(e)}. Export is blocked until validation succeeds.`,
      path: '#',
    });
  }

  return {
    errors,
    warnings,
    schemaValidationCompleted,
    validatorNote: VALIDATOR_NOTE,
  };
}

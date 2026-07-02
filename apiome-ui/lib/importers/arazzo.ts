/**
 * Arazzo document importer (#299).
 * Imports Arazzo 1.0.1 workflow documents by extracting classes from
 * components.schemas (when present) or inferring schemas from workflow steps.
 */

import { Importer, ImportSourceKind, NormalizeOptions, NormalizeResult } from './index';
import { openApiImporter } from './openapi';

/**
 * Infer JSON Schema-like objects from Arazzo workflows when components.schemas is missing.
 * Uses workflow inputs and step request bodies to build minimal schemas so the rest of the
 * import pipeline (preview, selection, naming) works.
 */
export function inferArazzoSchemasFromWorkflows(doc: any): Record<string, any> {
  const schemas: Record<string, any> = {};
  if (!doc || !doc.workflows || !Array.isArray(doc.workflows)) return schemas;

  for (const wf of doc.workflows) {
    const workflowId = wf.workflowId ?? wf.name;
    if (!workflowId) continue;

    // Workflow-level inputs (JSON Schema)
    if (wf.inputs && typeof wf.inputs === 'object' && wf.inputs.properties) {
      const key = toPascalSchemaKey(String(workflowId) + 'Inputs');
      if (!schemas[key]) {
        schemas[key] = {
          type: 'object',
          description: wf.description ?? wf.summary ?? `Inputs for ${workflowId}`,
          properties: { ...wf.inputs.properties },
          required: Array.isArray(wf.inputs.required) ? wf.inputs.required : [],
        };
      }
    }

    const steps = wf.steps;
    if (!Array.isArray(steps)) continue;

    for (const step of steps) {
      const stepId = step.stepId ?? step.name;
      if (!stepId) continue;

      // Step request body: requestBody.payload (spec) or request.parameters.body (YAML examples)
      let body: any = null;
      if (step.requestBody?.payload && typeof step.requestBody.payload === 'object') {
        body = step.requestBody.payload;
      } else if (step.request?.parameters?.body && typeof step.request.parameters.body === 'object') {
        body = step.request.parameters.body;
      } else if (step.request?.parameters?.body !== undefined) {
        body = typeof step.request.parameters.body === 'object' ? step.request.parameters.body : {};
      }
      if (!body || typeof body !== 'object') continue;

      const key = toPascalSchemaKey(String(workflowId) + '_' + String(stepId));
      if (schemas[key]) continue;

      const properties: Record<string, any> = {};
      for (const [propName, value] of Object.entries(body)) {
        if (propName.startsWith('$') || propName.startsWith('{')) continue; // skip expressions
        properties[propName] = inferPropertySchema(value);
      }
      schemas[key] = {
        type: 'object',
        description: step.description ?? step.summary ?? `Request body for ${stepId}`,
        properties,
        required: [],
      };
    }
  }

  return schemas;
}

function toPascalSchemaKey(s: string): string {
  // Preserve PascalCase from workflowId/stepId; only strip separators and invalid chars
  const out = s.replace(/[-_\s]+/g, '').replace(/[^A-Za-z0-9]/g, '');
  return out.length > 0 ? out : 'Schema';
}

function inferPropertySchema(value: unknown): Record<string, unknown> {
  if (value === null) return { type: 'string', nullable: true };
  if (typeof value === 'string') return { type: 'string' };
  if (typeof value === 'number') return Number.isInteger(value) ? { type: 'integer' } : { type: 'number' };
  if (typeof value === 'boolean') return { type: 'boolean' };
  if (Array.isArray(value)) {
    const first = value[0];
    const items = first !== undefined ? inferPropertySchema(first) : { type: 'string' };
    return { type: 'array', items };
  }
  if (typeof value === 'object') {
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      props[k] = inferPropertySchema(v);
    }
    return { type: 'object', properties: props };
  }
  return { type: 'string' };
}

export const arazzoImporter: Importer = {
  kind: 'arazzo' as ImportSourceKind,
  normalize({ document, options }: { document: any; options: NormalizeOptions }): NormalizeResult {
    const warnings: string[] = [];
    let doc = document;

    const hasComponentsSchemas =
      document?.components?.schemas && Object.keys(document.components.schemas).length > 0;

    if (!hasComponentsSchemas) {
      const inferred = inferArazzoSchemasFromWorkflows(document);
      if (Object.keys(inferred).length > 0) {
        doc = {
          ...document,
          components: {
            ...document?.components,
            schemas: { ...(document?.components?.schemas || {}), ...inferred },
          },
        };
        warnings.push('No components.schemas found; classes were inferred from workflow steps.');
      } else {
        return {
          classes: [],
          warnings: ['No components.schemas and no workflow steps with request bodies to import.'],
        };
      }
    }

    const result = openApiImporter.normalize({ document: doc, options });
    return {
      classes: result.classes,
      warnings: [...warnings, ...(result.warnings || [])],
    };
  },
};

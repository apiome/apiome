#!/usr/bin/env node
/**
 * Build a strict, standalone JSON Schema for one Kubernetes kind (MFX-21.6, #4345).
 *
 * kubeconform validates a manifest against a self-contained ("standalone") schema; with -strict it
 * also expects that schema to forbid unknown properties. yannh/kubernetes-json-schema no longer
 * publishes a standalone schema for apiextensions.k8s.io/v1 CustomResourceDefinition (only its
 * sub-objects), so the image builds it from the non-standalone pair the repository still has: the
 * kind's schema and `_definitions.json`. This is what yannh's own generator does with --stand-alone
 * --strict:
 *
 *   - every `$ref` to `_definitions.json#/definitions/<name>` (by URL, as the kind's schema writes it,
 *     or `#/definitions/<name>` inside the definitions) is replaced by that definition,
 *     recursively; a definition that refers back to itself (JSONSchemaProps does) is cut to `{}`
 *     at the point of recursion rather than expanded forever;
 *   - every object schema that lists `properties` and says nothing about `additionalProperties`
 *     gets `"additionalProperties": false` (the strict variant).
 *
 * Usage: node k8s-standalone-schema.mjs <kind-schema.json> <_definitions.json> <out.json>
 */

import { readFileSync, writeFileSync } from 'node:fs';

/**
 * A definition reference: local (`#/definitions/<name>`, inside `_definitions.json`) or to the
 * definitions file by any path or URL (`…/_definitions.json#/definitions/<name>`, in a kind's schema).
 */
const DEFINITION_REF = /(?:^|_definitions\.json)#\/definitions\/(.+)$/;

/**
 * Inline every definition reference of `node`.
 *
 * @param {unknown} node - A schema node.
 * @param {Record<string, unknown>} definitions - `_definitions.json`'s `definitions`.
 * @param {string[]} stack - The definitions being expanded on the current path (cycle guard).
 * @returns {unknown} The standalone node.
 */
function inline(node, definitions, stack) {
  if (Array.isArray(node)) return node.map((item) => inline(item, definitions, stack));
  if (node === null || typeof node !== 'object') return node;
  const match = typeof node.$ref === 'string' ? DEFINITION_REF.exec(node.$ref) : null;
  if (match) {
    const ref = node.$ref;
    const name = decodeURIComponent(match[1]);
    if (stack.includes(name)) return {};
    const target = definitions[name];
    if (target === undefined) throw new Error(`unresolved $ref ${ref}`);
    return inline(target, definitions, [...stack, name]);
  }
  const out = {};
  for (const [key, value] of Object.entries(node)) out[key] = inline(value, definitions, stack);
  return out;
}

/**
 * Forbid unknown properties on every object schema that lists its properties.
 *
 * @param {unknown} node - A standalone schema node (modified in place).
 */
function strict(node) {
  if (Array.isArray(node)) {
    node.forEach(strict);
    return;
  }
  if (node === null || typeof node !== 'object') return;
  if (node.properties && typeof node.properties === 'object' && !('additionalProperties' in node)) {
    node.additionalProperties = false;
  }
  for (const value of Object.values(node)) strict(value);
}

const [kindPath, definitionsPath, outPath] = process.argv.slice(2);
if (!kindPath || !definitionsPath || !outPath) {
  console.error('usage: k8s-standalone-schema.mjs <kind-schema.json> <_definitions.json> <out.json>');
  process.exit(2);
}
const definitions = JSON.parse(readFileSync(definitionsPath, 'utf8')).definitions ?? {};
const schema = inline(JSON.parse(readFileSync(kindPath, 'utf8')), definitions, []);
strict(schema);
writeFileSync(outPath, JSON.stringify(schema));

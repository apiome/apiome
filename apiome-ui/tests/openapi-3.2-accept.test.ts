/**
 * OA1 (#3498) — Accept OpenAPI 3.2.0 documents.
 *
 * Verifies the version gate was lifted so 3.2.0 documents are accepted and routed to the
 * importer (importing at least at 3.1 fidelity), that the analyzer reports them as supported,
 * and that unknown future 3.x minors degrade to a non-blocking warning instead of a hard error.
 */

import fs from 'fs';
import path from 'path';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import {
  analyzeSpecification,
  classifyOpenAPIVersion,
  MAX_KNOWN_OPENAPI_MINOR,
} from '../src/app/utils/openapi-analyzer';

const examplePath = path.join(__dirname, '../examples/openapi/32-openapi-3.2.0-minimal.yaml');
const example32 = fs.readFileSync(examplePath, 'utf-8');

describe('classifyOpenAPIVersion (OA1 #3498)', () => {
  it('classifies 3.0.x as a known 3.x minor 0', () => {
    expect(classifyOpenAPIVersion('3.0.0')).toEqual({ minor: 0, isThreeX: true, isKnownMinor: true });
    expect(classifyOpenAPIVersion('3.0.3')).toEqual({ minor: 0, isThreeX: true, isKnownMinor: true });
  });

  it('classifies 3.1.x as a known 3.x minor 1', () => {
    expect(classifyOpenAPIVersion('3.1.0')).toEqual({ minor: 1, isThreeX: true, isKnownMinor: true });
  });

  it('classifies 3.2.0 as a known 3.x minor 2', () => {
    expect(classifyOpenAPIVersion('3.2.0')).toEqual({ minor: 2, isThreeX: true, isKnownMinor: true });
  });

  it('classifies an unknown future 3.x minor as 3.x but not a known minor', () => {
    expect(classifyOpenAPIVersion('3.9.0')).toEqual({ minor: 9, isThreeX: true, isKnownMinor: false });
    expect(classifyOpenAPIVersion(`3.${MAX_KNOWN_OPENAPI_MINOR + 1}.0`)).toEqual({
      minor: MAX_KNOWN_OPENAPI_MINOR + 1,
      isThreeX: true,
      isKnownMinor: false,
    });
  });

  it('classifies non-3.x and malformed versions as not 3.x', () => {
    expect(classifyOpenAPIVersion('4.0.0')).toEqual({ minor: null, isThreeX: false, isKnownMinor: false });
    expect(classifyOpenAPIVersion('2.0')).toEqual({ minor: null, isThreeX: false, isKnownMinor: false });
    expect(classifyOpenAPIVersion('')).toEqual({ minor: null, isThreeX: false, isKnownMinor: false });
    // @ts-expect-error exercising malformed (non-string) input is intentional
    expect(classifyOpenAPIVersion(undefined)).toEqual({ minor: null, isThreeX: false, isKnownMinor: false });
  });
});

describe('analyzeSpecification version gate (OA1 #3498)', () => {
  function docWith(version: string) {
    return JSON.stringify({
      openapi: version,
      info: { title: 'T', version: '1.0.0' },
      paths: {},
      components: { schemas: { Foo: { type: 'object', properties: { a: { type: 'string' } } } } },
    });
  }

  it('reports 3.2.0 as a supported OpenAPI format with a display name noting 3.2.0', async () => {
    const result = await analyzeSpecification(docWith('3.2.0'), 'openapi-3.2.json');
    expect(result.format).toBe('openapi');
    expect(result.formatSupported).toBe(true);
    expect(result.version).toBe('3.2.0');
    expect(result.formatDisplayName).toContain('3.2.0');
  });

  it('does not emit a high-severity "not supported" warning for 3.2.0', async () => {
    const result = await analyzeSpecification(docWith('3.2.0'), 'openapi-3.2.json');
    const blocking = result.warnings.filter(
      (w) => w.path === 'openapi' && w.severity === 'high',
    );
    expect(blocking).toHaveLength(0);
    // It should instead carry a low-severity "normalized for import" note.
    const note = result.warnings.find((w) => w.path === 'openapi');
    expect(note?.severity).toBe('low');
    expect(note?.message.toLowerCase()).toContain('normalized');
  });

  it.each(['3.0.0', '3.1.0', '3.2.0'])('treats %s as supported', async (version) => {
    const result = await analyzeSpecification(docWith(version), 'openapi.json');
    expect(result.formatSupported).toBe(true);
  });

  it('degrades an unknown future 3.x version to a non-blocking warning, not a hard error', async () => {
    const result = await analyzeSpecification(docWith('3.9.0'), 'openapi-3.9.json');
    expect(result.format).toBe('openapi');
    // Accepted (not hard-rejected at the format gate).
    expect(result.formatSupported).toBe(true);
    // No critical errors introduced by the version.
    const versionErrors = result.errors.filter((e) => e.severity === 'critical');
    expect(versionErrors).toHaveLength(0);
    // Non-blocking warning is present and is not high severity.
    const note = result.warnings.find((w) => w.path === 'openapi');
    expect(note).toBeDefined();
    expect(note?.severity).not.toBe('high');
  });

  it('still flags a non-3.x version (e.g. 4.0.0) as unsupported', async () => {
    const result = await analyzeSpecification(docWith('4.0.0'), 'openapi-4.json');
    expect(result.formatSupported).toBe(false);
    const note = result.warnings.find((w) => w.path === 'openapi');
    expect(note?.severity).toBe('high');
  });
});

describe('parseOpenAPISpec routes 3.2.0 through the importer (OA1 #3498)', () => {
  it('imports the minimal 3.2.0 example successfully (not the JSON-Schema fallback)', () => {
    const result = parseOpenAPISpec(example32);
    expect(result.success).toBe(true);
    expect(result.error).toBeUndefined();

    const widget = result.classes.find((c) => c.name === 'Widget');
    expect(widget).toBeDefined();
    const propNames = widget?.properties.map((p) => p.name) ?? [];
    expect(propNames).toEqual(expect.arrayContaining(['id', 'name', 'quantity']));

    // Operations/paths and security schemes survive (would be lost via the JSON-Schema bag fallback).
    expect(result.paths?.length).toBeGreaterThan(0);
    expect(result.securitySchemes?.some((s) => s.scheme_name === 'apiKey')).toBe(true);
  });

  it('produces the same classes/properties as the 3.1 equivalent', () => {
    const result32 = parseOpenAPISpec(example32);
    const result31 = parseOpenAPISpec(example32.replace('openapi: 3.2.0', 'openapi: 3.1.0'));

    const classes32 = result32.classes.map((c) => ({ name: c.name, props: c.properties.map((p) => p.name).sort() }));
    const classes31 = result31.classes.map((c) => ({ name: c.name, props: c.properties.map((p) => p.name).sort() }));
    expect(classes32).toEqual(classes31);
  });
});

/**
 * Arazzo 1.0.x / 1.1.x consistency across the UI surfaces — COA-1.1 (#7037).
 *
 * - The generator (`utils/arazzo.ts` + `templates/arazzo/arazzo-spec.hbs`) writes the requested
 *   version, defaults to 1.1.0 for an AsyncAPI source and 1.0.1 otherwise, and never downgrades.
 * - The import wizard's analyzer accepts both 1.0.x and 1.1.x and rejects other versions.
 * - A generated 1.1 document with an AsyncAPI source round-trips: analyze → import keeps the
 *   version and both sources, with no unsupported-source warning.
 */

import { describe, it, expect } from '@jest/globals';
import {
  ARAZZO_VERSION_1_0,
  ARAZZO_VERSION_1_1,
  ArazzoSourceDescription,
  generateArazzoSpec,
  resolveArazzoVersion,
} from '../src/app/utils/arazzo';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';
import { arazzoImporter } from '../lib/importers/arazzo';
import type { NormalizeOptions } from '../lib/importers';

const CLASSES = [{ id: '1', name: 'Order', description: 'An order', properties: [] }];

const OPENAPI_SOURCE: ArazzoSourceDescription = {
  name: 'orders',
  type: 'openapi',
  url: 'https://api.example.test/openapi.yaml',
};
const ASYNCAPI_SOURCE: ArazzoSourceDescription = {
  name: 'orderEvents',
  type: 'asyncapi',
  url: 'https://events.example.test/asyncapi.yaml',
};

/** The parts of a generated document these tests read. */
interface GeneratedArazzo {
  arazzo: string;
  info: { description: string };
  sourceDescriptions: ArazzoSourceDescription[];
}

/** Generate a document and parse it back into an object. */
async function generate(options: Parameters<typeof generateArazzoSpec>[1]): Promise<GeneratedArazzo> {
  return JSON.parse(await generateArazzoSpec(CLASSES, options));
}

describe('resolveArazzoVersion', () => {
  it('defaults to 1.0.1 for OpenAPI-only sources', () => {
    expect(resolveArazzoVersion(undefined, [OPENAPI_SOURCE])).toBe(ARAZZO_VERSION_1_0);
    expect(resolveArazzoVersion('  ', [OPENAPI_SOURCE])).toBe('1.0.1');
  });

  it('defaults to 1.1.0 when a source is AsyncAPI', () => {
    expect(resolveArazzoVersion(undefined, [OPENAPI_SOURCE, ASYNCAPI_SOURCE])).toBe(ARAZZO_VERSION_1_1);
  });

  it.each(['1.0.0', '1.0.1', '1.1.0', '1.1.1'])('writes the explicit version %s as given', (version) => {
    expect(resolveArazzoVersion(` ${version} `, [OPENAPI_SOURCE])).toBe(version);
  });

  it('rejects 1.0.x for a document with an AsyncAPI source', () => {
    expect(() => resolveArazzoVersion('1.0.1', [ASYNCAPI_SOURCE])).toThrow(/AsyncAPI/);
  });

  it.each(['2.0.0', '1.2.0', '1.1', 'latest'])('rejects the unsupported version %s', (version) => {
    expect(() => resolveArazzoVersion(version, [OPENAPI_SOURCE])).toThrow(/not supported/);
  });
});

describe('generateArazzoSpec version option', () => {
  it('keeps 1.0.1 by default', async () => {
    const doc = await generate({ projectName: 'Shop' });
    expect(doc.arazzo).toBe('1.0.1');
    expect(doc.sourceDescriptions).toEqual([
      expect.objectContaining({ name: 'openapi-source', type: 'openapi', url: './openapi.json' }),
    ]);
    expect(doc.info.description).toBe('Generated Arazzo 1.0.1 workflow specification from Apiome Studio');
  });

  it.each(['1.0.1', '1.1.0'])('writes the requested version %s', async (version) => {
    const doc = await generate({ arazzoVersion: version });
    expect(doc.arazzo).toBe(version);
    expect(doc.info.description).toBe(`Generated Arazzo ${version} workflow specification from Apiome Studio`);
  });

  it('defaults to 1.1.0 and keeps both sources when one is AsyncAPI', async () => {
    const doc = await generate({ sourceDescriptions: [OPENAPI_SOURCE, ASYNCAPI_SOURCE] });
    expect(doc.arazzo).toBe('1.1.0');
    expect(doc.sourceDescriptions.map((s) => s.type)).toEqual(['openapi', 'asyncapi']);
  });

  it('refuses to downgrade an AsyncAPI-bearing document to 1.0', async () => {
    await expect(
      generateArazzoSpec(CLASSES, { arazzoVersion: '1.0.1', sourceDescriptions: [ASYNCAPI_SOURCE] })
    ).rejects.toThrow(/AsyncAPI/);
  });
});

describe('import wizard analyzer', () => {
  it.each(['1.0.0', '1.0.1', '1.1.0', '1.1.1'])('supports Arazzo %s', async (version) => {
    const content = JSON.stringify({ arazzo: version, info: { title: 'T', version: '1' }, workflows: [] });
    const result = await analyzeSpecification(content, 'flow.arazzo.json');
    expect(result.format).toBe('arazzo');
    expect(result.version).toBe(version);
    expect(result.formatSupported).toBe(true);
    expect(result.formatDisplayName).toBe(`Arazzo ${version}`);
  });

  it.each(['2.0.0', '1.2.0'])('marks Arazzo %s as unsupported', async (version) => {
    const content = JSON.stringify({ arazzo: version, info: { title: 'T', version: '1' }, workflows: [] });
    const result = await analyzeSpecification(content, 'flow.arazzo.json');
    expect(result.formatSupported).toBe(false);
    expect(result.formatDisplayName).toBe(`Arazzo ${version} (unsupported version)`);
  });
});

describe('generate → analyze → import round trip', () => {
  it.each([
    ['1.0.1', [OPENAPI_SOURCE]],
    ['1.1.0', [OPENAPI_SOURCE, ASYNCAPI_SOURCE]],
  ] as const)('keeps Arazzo %s and its sources', async (version, sources) => {
    const text = await generateArazzoSpec(CLASSES, {
      arazzoVersion: version,
      sourceDescriptions: [...sources],
    });

    const analysis = await analyzeSpecification(text, 'generated.arazzo.json');
    expect(analysis.formatSupported).toBe(true);
    expect(analysis.version).toBe(version);

    const document = JSON.parse(text);
    const result = arazzoImporter.normalize({ document, options: {} as NormalizeOptions });
    expect(document.arazzo).toBe(version);
    expect(result.classes.length).toBeGreaterThan(0);
    expect(result.arazzoResolution?.sources.map((s) => s.name)).toEqual(sources.map((s) => s.name));
    expect(result.arazzoResolution?.issues.map((i) => i.code)).not.toContain('SOURCE_TYPE_UNSUPPORTED');
  });
});

/**
 * Unit tests for the export-target → Monaco language / extension / filename mapping (MFX-9.4, #3869).
 *
 * The mappings are pure functions so they can be pinned without rendering Monaco: an emitter id
 * resolves (version-tolerant) to its canonical serialization, a byte sample refines JSON-or-YAML
 * targets, and everything unknown degrades to `plaintext` / `export.txt`.
 */

import {
  downloadFileNameForExportTarget,
  fileExtensionForExportTarget,
  monacoLanguageForExportTarget,
} from '../src/app/utils/export-target-language';

describe('monacoLanguageForExportTarget', () => {
  it('defaults known targets to their canonical JSON serialization', () => {
    expect(monacoLanguageForExportTarget('openapi')).toBe('json');
    expect(monacoLanguageForExportTarget('swagger')).toBe('json');
  });

  it('collapses version/variant suffixes to the base target id', () => {
    expect(monacoLanguageForExportTarget('openapi-3.1')).toBe('json');
    expect(monacoLanguageForExportTarget('openapi-3.0')).toBe('json');
    expect(monacoLanguageForExportTarget('swagger-2.0')).toBe('json');
    expect(monacoLanguageForExportTarget('OpenAPI-3.1')).toBe('json');
  });

  it('refines a JSON-or-YAML target from the emitted bytes', () => {
    expect(monacoLanguageForExportTarget('openapi', '{\n  "openapi": "3.1.0"\n}')).toBe('json');
    expect(monacoLanguageForExportTarget('openapi', 'openapi: 3.1.0\ninfo:')).toBe('yaml');
    expect(monacoLanguageForExportTarget('openapi', '---\nopenapi: 3.1.0')).toBe('yaml');
    expect(monacoLanguageForExportTarget('openapi', '<?xml version="1.0"?>')).toBe('xml');
  });

  it('maps the no-op sample emitter to plaintext', () => {
    expect(monacoLanguageForExportTarget('sample')).toBe('plaintext');
  });

  it('degrades unknown or absent targets to plaintext, sniffing when possible', () => {
    expect(monacoLanguageForExportTarget(null)).toBe('plaintext');
    expect(monacoLanguageForExportTarget('')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('totally-made-up')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('totally-made-up', '{ "a": 1 }')).toBe('json');
    expect(monacoLanguageForExportTarget('totally-made-up', '<root/>')).toBe('xml');
  });
});

describe('fileExtensionForExportTarget', () => {
  it('defaults known targets to .json and refines to .yaml from a sample', () => {
    expect(fileExtensionForExportTarget('openapi')).toBe('.json');
    expect(fileExtensionForExportTarget('openapi-3.1')).toBe('.json');
    expect(fileExtensionForExportTarget('openapi', 'openapi: 3.1.0')).toBe('.yaml');
  });

  it('falls back to .txt for unrecognised targets', () => {
    expect(fileExtensionForExportTarget('totally-made-up')).toBe('.txt');
    expect(fileExtensionForExportTarget(null)).toBe('.txt');
  });
});

describe('downloadFileNameForExportTarget', () => {
  it('names the artifact from the target id and serialization', () => {
    expect(downloadFileNameForExportTarget('openapi')).toBe('openapi.json');
    expect(downloadFileNameForExportTarget('openapi-3.1')).toBe('openapi.json');
    expect(downloadFileNameForExportTarget('openapi', 'openapi: 3.1.0')).toBe('openapi.yaml');
    expect(downloadFileNameForExportTarget('swagger-2.0')).toBe('swagger.json');
  });

  it('falls back to export.txt for unrecognised targets', () => {
    expect(downloadFileNameForExportTarget('totally-made-up')).toBe('export.txt');
  });
});

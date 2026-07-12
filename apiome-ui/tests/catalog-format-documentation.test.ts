/**
 * Unit tests for catalog format technical documentation URLs (MFI-23.12).
 */
import { describe, test, expect } from '@jest/globals';
import { IMPORTABLE_ALTERNATIVE_FORMATS } from '../src/app/utils/catalog-format-registry';
import {
  CATALOG_FORMAT_DOCUMENTATION_URL,
  catalogFormatDocumentationUrl,
} from '../src/app/utils/catalog-format-documentation';

describe('catalog-format-documentation', () => {
  test('every importable alternative format has an official documentation URL', () => {
    for (const fmt of IMPORTABLE_ALTERNATIVE_FORMATS) {
      const url = catalogFormatDocumentationUrl(fmt.id);
      expect(url).toBeTruthy();
      expect(url).toMatch(/^https:\/\//);
    }
  });

  test('documentation map keys are unique and resolve back through the helper', () => {
    const keys = Object.keys(CATALOG_FORMAT_DOCUMENTATION_URL);
    expect(new Set(keys).size).toBe(keys.length);
    for (const key of keys) {
      expect(catalogFormatDocumentationUrl(key)).toBe(CATALOG_FORMAT_DOCUMENTATION_URL[key]);
    }
  });
});

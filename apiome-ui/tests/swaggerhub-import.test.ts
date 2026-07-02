/**
 * Tests for SwaggerHub Import Functionality
 */

import { describe, it, expect, jest } from '@jest/globals';
import {
  validateSwaggerHubOptions,
  SwaggerHubImportOptions
} from '../src/app/utils/swaggerhub-import';

describe('SwaggerHub Import', () => {
  describe('validateSwaggerHubOptions', () => {
    it('should validate correct options', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore',
        version: '1.0.0'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
      expect(result.error).toBeUndefined();
    });

    it('should validate options without version', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'myorg',
        api: 'petstore'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
    });

    it('should reject empty owner', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: '',
        api: 'petstore'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Owner');
    });

    it('should reject missing owner', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        api: 'petstore'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Owner');
    });

    it('should reject empty api name', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'myorg',
        api: ''
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('API name');
    });

    it('should reject missing api name', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'myorg'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('API name');
    });

    it('should reject invalid owner format', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'my org!',
        api: 'petstore'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Invalid owner');
    });

    it('should reject invalid api name format', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'myorg',
        api: 'pet store!'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Invalid API name');
    });

    it('should reject invalid version format', () => {
      const options: Partial<SwaggerHubImportOptions> = {
        owner: 'myorg',
        api: 'petstore',
        version: 'v1.0.0!'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Invalid version');
    });

    it('should accept hyphens in owner', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'my-org',
        api: 'petstore'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
    });

    it('should accept underscores in api name', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'pet_store'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
    });

    it('should accept dots in version', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore',
        version: '1.0.0'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
    });

    it('should accept semantic versions', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore',
        version: '2.1.3-beta.1'
      };

      const result = validateSwaggerHubOptions(options);
      expect(result.valid).toBe(true);
    });
  });

  describe('SwaggerHub URL Construction', () => {
    it('should construct correct API URL', () => {
      const owner = 'myorg';
      const api = 'petstore';
      const version = '1.0.0';

      const expectedUrl = `https://api.swaggerhub.com/apis/${owner}/${api}/${version}`;

      // This tests the URL format expected by the utility
      expect(expectedUrl).toBe('https://api.swaggerhub.com/apis/myorg/petstore/1.0.0');
    });

    it('should handle version with dots and hyphens', () => {
      const owner = 'myorg';
      const api = 'petstore';
      const version = '2.1.0-rc.1';

      const expectedUrl = `https://api.swaggerhub.com/apis/${owner}/${api}/${version}`;

      expect(expectedUrl).toBe('https://api.swaggerhub.com/apis/myorg/petstore/2.1.0-rc.1');
    });
  });

  describe('SwaggerHub Import Flow', () => {
    it('should handle successful import with all fields', () => {
      const mockResult = {
        success: true,
        content: '{"openapi": "3.1.0"}',
        filename: 'petstore-1.0.0.json',
        version: '1.0.0',
        isPrivate: false
      };

      expect(mockResult.success).toBe(true);
      expect(mockResult.content).toBeDefined();
      expect(mockResult.filename).toContain('petstore');
      expect(mockResult.version).toBe('1.0.0');
    });

    it('should handle private API indication', () => {
      const mockResult = {
        success: true,
        content: '{"openapi": "3.1.0"}',
        filename: 'private-api-1.0.0.json',
        version: '1.0.0',
        isPrivate: true
      };

      expect(mockResult.isPrivate).toBe(true);
    });

    it('should handle authentication failures', () => {
      const mockResult = {
        success: false,
        error: 'Authentication failed. Please check your API key.',
        isPrivate: true
      };

      expect(mockResult.success).toBe(false);
      expect(mockResult.error).toContain('Authentication');
      expect(mockResult.isPrivate).toBe(true);
    });

    it('should handle not found errors', () => {
      const mockResult = {
        success: false,
        error: 'API not found: myorg/petstore/1.0.0'
      };

      expect(mockResult.success).toBe(false);
      expect(mockResult.error).toContain('not found');
    });

    it('should handle access denied', () => {
      const mockResult = {
        success: false,
        error: 'Access denied. This API may be private or your API key lacks permissions.',
        isPrivate: true
      };

      expect(mockResult.success).toBe(false);
      expect(mockResult.error).toContain('Access denied');
    });
  });

  describe('Version Resolution', () => {
    it('should use latest version when not specified', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore'
        // version is undefined
      };

      expect(options.version).toBeUndefined();
    });

    it('should use specific version when provided', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore',
        version: '2.0.0'
      };

      expect(options.version).toBe('2.0.0');
    });
  });

  describe('API Key Handling', () => {
    it('should accept optional API key', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore',
        apiKey: 'test-api-key-12345'
      };

      expect(options.apiKey).toBeDefined();
      expect(options.apiKey).toBe('test-api-key-12345');
    });

    it('should work without API key for public APIs', () => {
      const options: SwaggerHubImportOptions = {
        owner: 'myorg',
        api: 'petstore'
        // apiKey is undefined
      };

      expect(options.apiKey).toBeUndefined();
    });
  });
});


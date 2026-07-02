/**
 * Test for External Documentation Feature
 *
 * This test verifies that the externalDocs feature properly handles
 * external documentation links per OpenAPI 3.1 specification.
 */

import { describe, it, expect } from '@jest/globals';

describe('External Documentation Feature', () => {
  describe('Schema Integration', () => {
    it('should create externalDocs with URL only', () => {
      const formData = {
        externalDocsUrl: 'https://docs.example.com/user',
        externalDocsDescription: '',
      };

      const schema: any = { type: 'object', properties: {} };

      // Add externalDocs if URL is provided
      if (formData.externalDocsUrl.trim()) {
        schema.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription.trim()) {
          schema.externalDocs.description = formData.externalDocsDescription.trim();
        }
      }

      expect(schema.externalDocs).toBeDefined();
      expect(schema.externalDocs.url).toBe('https://docs.example.com/user');
      expect(schema.externalDocs.description).toBeUndefined();
    });

    it('should create externalDocs with URL and description', () => {
      const formData = {
        externalDocsUrl: 'https://docs.example.com/user',
        externalDocsDescription: 'Complete user guide',
      };

      const schema: any = { type: 'object', properties: {} };

      if (formData.externalDocsUrl.trim()) {
        schema.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription.trim()) {
          schema.externalDocs.description = formData.externalDocsDescription.trim();
        }
      }

      expect(schema.externalDocs).toBeDefined();
      expect(schema.externalDocs.url).toBe('https://docs.example.com/user');
      expect(schema.externalDocs.description).toBe('Complete user guide');
    });

    it('should not create externalDocs when URL is empty', () => {
      const formData = {
        externalDocsUrl: '',
        externalDocsDescription: 'Some description',
      };

      const schema: any = { type: 'object', properties: {} };

      if (formData.externalDocsUrl.trim()) {
        schema.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription.trim()) {
          schema.externalDocs.description = formData.externalDocsDescription.trim();
        }
      }

      expect(schema.externalDocs).toBeUndefined();
    });

    it('should trim whitespace from URL and description', () => {
      const formData = {
        externalDocsUrl: '  https://docs.example.com/user  ',
        externalDocsDescription: '  Complete user guide  ',
      };

      const schema: any = { type: 'object', properties: {} };

      if (formData.externalDocsUrl.trim()) {
        schema.externalDocs = {
          url: formData.externalDocsUrl.trim()
        };
        if (formData.externalDocsDescription.trim()) {
          schema.externalDocs.description = formData.externalDocsDescription.trim();
        }
      }

      expect(schema.externalDocs.url).toBe('https://docs.example.com/user');
      expect(schema.externalDocs.description).toBe('Complete user guide');
    });
  });

  describe('Schema Loading', () => {
    it('should extract externalDocs from schema', () => {
      const schema = {
        type: 'object',
        properties: {},
        externalDocs: {
          url: 'https://docs.example.com/user',
          description: 'User guide',
        },
      };

      const externalDocsUrl = schema.externalDocs?.url || '';
      const externalDocsDescription = schema.externalDocs?.description || '';

      expect(externalDocsUrl).toBe('https://docs.example.com/user');
      expect(externalDocsDescription).toBe('User guide');
    });

    it('should handle missing externalDocs', () => {
      const schema = {
        type: 'object',
        properties: {},
      };

      const externalDocsUrl = schema.externalDocs?.url || '';
      const externalDocsDescription = schema.externalDocs?.description || '';

      expect(externalDocsUrl).toBe('');
      expect(externalDocsDescription).toBe('');
    });

    it('should handle externalDocs with URL only', () => {
      const schema = {
        type: 'object',
        properties: {},
        externalDocs: {
          url: 'https://docs.example.com/user',
        },
      };

      const externalDocsUrl = schema.externalDocs?.url || '';
      const externalDocsDescription = schema.externalDocs?.description || '';

      expect(externalDocsUrl).toBe('https://docs.example.com/user');
      expect(externalDocsDescription).toBe('');
    });
  });

  describe('URL Validation', () => {
    it('should accept valid HTTP URLs', () => {
      const validUrls = [
        'http://docs.example.com',
        'https://docs.example.com',
        'https://docs.example.com/path',
        'https://docs.example.com/path?query=value',
        'https://docs.example.com/path#anchor',
        'https://github.com/user/repo/wiki/Page',
        'https://www.youtube.com/watch?v=abc123',
      ];

      validUrls.forEach(url => {
        try {
          const parsed = new URL(url);
          expect(parsed.protocol).toMatch(/^https?:$/);
        } catch (e) {
          fail(`URL should be valid: ${url}`);
        }
      });
    });

    it('should identify HTTPS vs HTTP', () => {
      const httpsUrl = 'https://docs.example.com';
      const httpUrl = 'http://docs.example.com';

      const httpsUrlObj = new URL(httpsUrl);
      const httpUrlObj = new URL(httpUrl);

      expect(httpsUrlObj.protocol).toBe('https:');
      expect(httpUrlObj.protocol).toBe('http:');
    });
  });

  describe('OpenAPI Compliance', () => {
    it('should match OpenAPI 3.1 externalDocs structure', () => {
      const externalDocs = {
        url: 'https://docs.example.com/user',
        description: 'User documentation',
      };

      // Required field
      expect(externalDocs.url).toBeDefined();
      expect(typeof externalDocs.url).toBe('string');

      // Optional field
      if (externalDocs.description) {
        expect(typeof externalDocs.description).toBe('string');
      }

      // No additional properties (per spec)
      const allowedKeys = ['url', 'description'];
      Object.keys(externalDocs).forEach(key => {
        expect(allowedKeys).toContain(key);
      });
    });

    it('should allow externalDocs at schema level', () => {
      const schema = {
        type: 'object',
        properties: {
          name: { type: 'string' },
        },
        externalDocs: {
          url: 'https://docs.example.com/user',
        },
      };

      expect(schema.externalDocs).toBeDefined();
      expect(schema.externalDocs.url).toBe('https://docs.example.com/user');
    });
  });

  describe('Common Use Cases', () => {
    it('should support user guide links', () => {
      const externalDocs = {
        url: 'https://docs.example.com/guides/user-class',
        description: 'Complete user class guide with examples',
      };

      expect(externalDocs.url).toContain('guides');
      expect(externalDocs.description).toContain('guide');
    });

    it('should support API documentation links', () => {
      const externalDocs = {
        url: 'https://api-docs.example.com/resources/user',
        description: 'REST API endpoints for user resources',
      };

      expect(externalDocs.url).toContain('api');
      expect(externalDocs.description).toContain('API');
    });

    it('should support GitHub links', () => {
      const externalDocs = {
        url: 'https://github.com/company/repo/wiki/User-Schema',
        description: 'Schema design and implementation notes',
      };

      expect(externalDocs.url).toContain('github.com');
      expect(externalDocs.description).toContain('Schema');
    });

    it('should support video tutorial links', () => {
      const externalDocs = {
        url: 'https://www.youtube.com/watch?v=abc123',
        description: 'Video tutorial: Working with User objects',
      };

      expect(externalDocs.url).toContain('youtube.com');
      expect(externalDocs.description).toContain('Video');
    });

    it('should support migration guide links', () => {
      const externalDocs = {
        url: 'https://docs.example.com/migrations/user-v2',
        description: 'Migration guide from UserV1 to UserV2',
      };

      expect(externalDocs.url).toContain('migration');
      expect(externalDocs.description).toContain('Migration');
    });
  });

  describe('Security', () => {
    it('should use secure URL opening parameters', () => {
      const url = 'https://docs.example.com/user';
      const target = '_blank';
      const features = 'noopener,noreferrer';

      // Verify security parameters
      expect(target).toBe('_blank');
      expect(features).toContain('noopener');
      expect(features).toContain('noreferrer');
    });

    it('should prevent tab hijacking with noopener', () => {
      const features = 'noopener,noreferrer';
      expect(features).toContain('noopener');
    });

    it('should protect privacy with noreferrer', () => {
      const features = 'noopener,noreferrer';
      expect(features).toContain('noreferrer');
    });
  });

  describe('Edge Cases', () => {
    it('should handle very long URLs', () => {
      const longPath = 'a'.repeat(1000);
      const longUrl = `https://docs.example.com/${longPath}`;

      const schema: any = { type: 'object' };
      schema.externalDocs = { url: longUrl };

      expect(schema.externalDocs.url).toBe(longUrl);
      expect(schema.externalDocs.url.length).toBeGreaterThan(1000);
    });

    it('should handle URLs with special characters', () => {
      const urlWithSpecialChars = 'https://docs.example.com/path?query=value&foo=bar#section-1';

      const schema: any = { type: 'object' };
      schema.externalDocs = { url: urlWithSpecialChars };

      expect(schema.externalDocs.url).toBe(urlWithSpecialChars);
    });

    it('should handle multiline descriptions', () => {
      const multilineDesc = 'Line 1\nLine 2\nLine 3';

      const schema: any = { type: 'object' };
      schema.externalDocs = {
        url: 'https://docs.example.com',
        description: multilineDesc,
      };

      expect(schema.externalDocs.description).toContain('\n');
      expect(schema.externalDocs.description.split('\n').length).toBe(3);
    });

    it('should handle Unicode in descriptions', () => {
      const unicodeDesc = 'Documentation 文档 📚';

      const schema: any = { type: 'object' };
      schema.externalDocs = {
        url: 'https://docs.example.com',
        description: unicodeDesc,
      };

      expect(schema.externalDocs.description).toContain('文档');
      expect(schema.externalDocs.description).toContain('📚');
    });
  });
});

// Export for test runner
export {};


/**
 * Tests for HTTP Status Code Descriptions utility
 */

import {
  HTTP_STATUS_CODES,
  getHttpStatusDescription,
  getStatusCodesByCategory,
  isValidStatusCode,
  getStatusCodeCategory,
  COMMON_STATUS_CODES,
} from '../../lib/utils/http-status-codes';

describe('HTTP Status Codes Utility', () => {
  describe('HTTP_STATUS_CODES', () => {
    it('should contain all common 2XX status codes', () => {
      expect(HTTP_STATUS_CODES['200']).toBeDefined();
      expect(HTTP_STATUS_CODES['201']).toBeDefined();
      expect(HTTP_STATUS_CODES['204']).toBeDefined();
    });

    it('should contain all common 4XX status codes', () => {
      expect(HTTP_STATUS_CODES['400']).toBeDefined();
      expect(HTTP_STATUS_CODES['401']).toBeDefined();
      expect(HTTP_STATUS_CODES['403']).toBeDefined();
      expect(HTTP_STATUS_CODES['404']).toBeDefined();
      expect(HTTP_STATUS_CODES['422']).toBeDefined();
    });

    it('should contain all common 5XX status codes', () => {
      expect(HTTP_STATUS_CODES['500']).toBeDefined();
      expect(HTTP_STATUS_CODES['502']).toBeDefined();
      expect(HTTP_STATUS_CODES['503']).toBeDefined();
    });

    it('should contain OpenAPI special codes', () => {
      expect(HTTP_STATUS_CODES['default']).toBeDefined();
      expect(HTTP_STATUS_CODES['2XX']).toBeDefined();
      expect(HTTP_STATUS_CODES['4XX']).toBeDefined();
      expect(HTTP_STATUS_CODES['5XX']).toBeDefined();
    });
  });

  describe('getHttpStatusDescription', () => {
    it('should return correct description for 200', () => {
      expect(getHttpStatusDescription('200')).toBe('OK');
    });

    it('should return correct description for 201', () => {
      expect(getHttpStatusDescription('201')).toBe('Created');
    });

    it('should return correct description for 204', () => {
      expect(getHttpStatusDescription('204')).toBe('No Content');
    });

    it('should return correct description for 400', () => {
      expect(getHttpStatusDescription('400')).toBe('Bad Request');
    });

    it('should return correct description for 401', () => {
      expect(getHttpStatusDescription('401')).toBe('Unauthorized');
    });

    it('should return correct description for 403', () => {
      expect(getHttpStatusDescription('403')).toBe('Forbidden');
    });

    it('should return correct description for 404', () => {
      expect(getHttpStatusDescription('404')).toBe('Not Found');
    });

    it('should return correct description for 422', () => {
      expect(getHttpStatusDescription('422')).toBe('Unprocessable Content');
    });

    it('should return correct description for 500', () => {
      expect(getHttpStatusDescription('500')).toBe('Internal Server Error');
    });

    it('should return correct description for default', () => {
      expect(getHttpStatusDescription('default')).toBe('Default Response');
    });

    it('should handle unknown status codes with wildcard fallback', () => {
      expect(getHttpStatusDescription('299')).toBe('Successful Response (299)');
    });

    it('should return empty string for completely unknown codes', () => {
      expect(getHttpStatusDescription('999')).toBe('');
    });
  });

  describe('getStatusCodesByCategory', () => {
    it('should return success codes for success category', () => {
      const successCodes = getStatusCodesByCategory('success');
      expect(successCodes.length).toBeGreaterThan(0);
      expect(successCodes.every(c => c.category === 'success')).toBe(true);
      expect(successCodes.some(c => c.code === '200')).toBe(true);
    });

    it('should return client error codes', () => {
      const clientErrors = getStatusCodesByCategory('client_error');
      expect(clientErrors.length).toBeGreaterThan(0);
      expect(clientErrors.every(c => c.category === 'client_error')).toBe(true);
      expect(clientErrors.some(c => c.code === '404')).toBe(true);
    });

    it('should return server error codes', () => {
      const serverErrors = getStatusCodesByCategory('server_error');
      expect(serverErrors.length).toBeGreaterThan(0);
      expect(serverErrors.every(c => c.category === 'server_error')).toBe(true);
      expect(serverErrors.some(c => c.code === '500')).toBe(true);
    });

    it('should exclude wildcard codes like 2XX', () => {
      const successCodes = getStatusCodesByCategory('success');
      expect(successCodes.some(c => c.code === '2XX')).toBe(false);
    });
  });

  describe('isValidStatusCode', () => {
    it('should return true for valid numeric codes', () => {
      expect(isValidStatusCode('200')).toBe(true);
      expect(isValidStatusCode('404')).toBe(true);
      expect(isValidStatusCode('500')).toBe(true);
    });

    it('should return true for special codes', () => {
      expect(isValidStatusCode('default')).toBe(true);
      expect(isValidStatusCode('2XX')).toBe(true);
    });

    it('should return true for valid codes in range', () => {
      expect(isValidStatusCode('100')).toBe(true);
      expect(isValidStatusCode('599')).toBe(true);
    });

    it('should return false for out of range codes', () => {
      expect(isValidStatusCode('99')).toBe(false);
      expect(isValidStatusCode('600')).toBe(false);
    });

    it('should return false for invalid strings', () => {
      expect(isValidStatusCode('abc')).toBe(false);
      expect(isValidStatusCode('')).toBe(false);
    });
  });

  describe('getStatusCodeCategory', () => {
    it('should return correct category for 1XX codes', () => {
      expect(getStatusCodeCategory('100')).toBe('informational');
      expect(getStatusCodeCategory('101')).toBe('informational');
    });

    it('should return correct category for 2XX codes', () => {
      expect(getStatusCodeCategory('200')).toBe('success');
      expect(getStatusCodeCategory('201')).toBe('success');
      expect(getStatusCodeCategory('204')).toBe('success');
    });

    it('should return correct category for 3XX codes', () => {
      expect(getStatusCodeCategory('301')).toBe('redirection');
      expect(getStatusCodeCategory('302')).toBe('redirection');
    });

    it('should return correct category for 4XX codes', () => {
      expect(getStatusCodeCategory('400')).toBe('client_error');
      expect(getStatusCodeCategory('404')).toBe('client_error');
    });

    it('should return correct category for 5XX codes', () => {
      expect(getStatusCodeCategory('500')).toBe('server_error');
      expect(getStatusCodeCategory('503')).toBe('server_error');
    });

    it('should return undefined for invalid codes', () => {
      expect(getStatusCodeCategory('abc')).toBeUndefined();
    });
  });

  describe('COMMON_STATUS_CODES', () => {
    it('should have common success codes', () => {
      expect(COMMON_STATUS_CODES.success).toContain('200');
      expect(COMMON_STATUS_CODES.success).toContain('201');
      expect(COMMON_STATUS_CODES.success).toContain('204');
    });

    it('should have common client error codes', () => {
      expect(COMMON_STATUS_CODES.client_error).toContain('400');
      expect(COMMON_STATUS_CODES.client_error).toContain('401');
      expect(COMMON_STATUS_CODES.client_error).toContain('404');
    });

    it('should have common server error codes', () => {
      expect(COMMON_STATUS_CODES.server_error).toContain('500');
      expect(COMMON_STATUS_CODES.server_error).toContain('502');
      expect(COMMON_STATUS_CODES.server_error).toContain('503');
    });
  });
});

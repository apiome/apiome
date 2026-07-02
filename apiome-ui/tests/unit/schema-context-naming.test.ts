/**
 * Unit tests for smart class naming from schema context (#753)
 */

import { getSmartClassName } from '../../lib/schema-context-naming';

describe('schema-context-naming (#753)', () => {
  describe('getSmartClassName', () => {
    it('returns schema key when schema is null or undefined', () => {
      expect(getSmartClassName('UserProfile', null)).toBe('UserProfile');
      expect(getSmartClassName('user_profile', undefined)).toBe('user_profile');
    });

    it('returns schema key when schema has no title or x-class-name', () => {
      expect(getSmartClassName('ApiResponse', { type: 'object', properties: {} })).toBe('ApiResponse');
      expect(getSmartClassName('user_profile', { description: 'A user' })).toBe('user_profile');
    });

    it('prefers title when present and uses it as class name', () => {
      expect(getSmartClassName('api_response', {
        type: 'object',
        title: 'API Response',
        properties: {},
      })).toBe('API Response');
      expect(getSmartClassName('user', { title: 'UserProfile', type: 'object' })).toBe('UserProfile');
    });

    it('strips non-identifier characters from title and normalizes spaces', () => {
      expect(getSmartClassName('x', { title: '  User   Profile  ', type: 'object' })).toBe('User Profile');
      expect(getSmartClassName('x', { title: 'Order-Item', type: 'object' })).toBe('OrderItem');
    });

    it('prefers x-class-name over title when both present', () => {
      const schema = {
        type: 'object',
        title: 'API Response',
        'x-class-name': 'HttpResponse',
        properties: {},
      };
      expect(getSmartClassName('api_response', schema)).toBe('HttpResponse');
    });

    it('prefers x-className over title when both present', () => {
      const schema = {
        type: 'object',
        title: 'User',
        'x-className': 'UserEntity',
        properties: {},
      };
      expect(getSmartClassName('user', schema)).toBe('UserEntity');
    });

    it('prefers x_class_name over title when both present', () => {
      const schema = {
        type: 'object',
        title: 'Pet',
        x_class_name: 'PetModel',
        properties: {},
      };
      expect(getSmartClassName('pet', schema)).toBe('PetModel');
    });

    it('priority order: x-class-name > x-className > x_class_name > title > key', () => {
      expect(getSmartClassName('k', {
        'x-class-name': 'A',
        'x-className': 'B',
        x_class_name: 'C',
        title: 'D',
      })).toBe('A');
      expect(getSmartClassName('k', { 'x-className': 'B', x_class_name: 'C', title: 'D' })).toBe('B');
      expect(getSmartClassName('k', { x_class_name: 'C', title: 'D' })).toBe('C');
      expect(getSmartClassName('k', { title: 'D' })).toBe('D');
      expect(getSmartClassName('k', { type: 'object' })).toBe('k');
    });

    it('returns key for empty or whitespace-only title', () => {
      expect(getSmartClassName('Fallback', { title: '', type: 'object' })).toBe('Fallback');
      expect(getSmartClassName('Fallback', { title: '   ', type: 'object' })).toBe('Fallback');
    });

    it('returns key for empty or whitespace-only x-class-name', () => {
      expect(getSmartClassName('Key', { 'x-class-name': '', title: 'Title', type: 'object' })).toBe('Title');
      expect(getSmartClassName('Key', { 'x-class-name': '   ', type: 'object' })).toBe('Key');
    });

    it('handles invalid schemaKey', () => {
      expect(getSmartClassName('', { title: 'Something' })).toBe('Unnamed');
      expect(getSmartClassName('' as any, null)).toBe('Unnamed');
    });

    it('trims schemaKey', () => {
      expect(getSmartClassName('  user_profile  ', { type: 'object' })).toBe('user_profile');
    });

    it('ignores non-string title or extension', () => {
      expect(getSmartClassName('k', { title: 123, type: 'object' })).toBe('k');
      expect(getSmartClassName('k', { 'x-class-name': null, type: 'object' })).toBe('k');
      expect(getSmartClassName('k', { title: {}, type: 'object' })).toBe('k');
    });
  });
});

/**
 * Unit tests for buildGroupMetadataForSync (#95) — group tags persisted in apiome.groups.metadata.
 */

import { describe, test, expect } from '@jest/globals';

import { buildGroupMetadataForSync } from '../../lib/utils/group-metadata';

describe('buildGroupMetadataForSync', () => {

  test('merges tags into existing metadata object', () => {
    const meta = buildGroupMetadataForSync({
      metadata: { shadow: 'md', icon: 'box' },
      tags: [{ id: 't1', name: 'API', color: 'primary' }],
      styleOptions: { shadow: 'sm', icon: 'folder' },
    });
    expect(meta.shadow).toBe('md');
    expect(meta.icon).toBe('box');
    expect(meta.tags).toEqual([{ id: 't1', name: 'API', color: 'primary' }]);
  });

  test('uses styleOptions as metadata base when metadata is absent', () => {
    const meta = buildGroupMetadataForSync({
      styleOptions: {
        borderStyle: 'solid',
        opacity: 0.5,
        shadow: 'lg',
        icon: 'database',
      },
      tags: [{ id: 't2', name: 'Core', color: 'default' }],
    });
    expect(meta.borderStyle).toBe('solid');
    expect(meta.opacity).toBe(0.5);
    expect(meta.shadow).toBe('lg');
    expect(meta.icon).toBe('database');
    expect(meta.tags).toEqual([{ id: 't2', name: 'Core', color: 'default' }]);
  });

  test('clears tags when empty array provided with metadata', () => {
    const meta = buildGroupMetadataForSync({
      metadata: { tags: [{ id: 'old' }], shadow: 'none' },
      tags: [],
    });
    expect(meta.tags).toEqual([]);
    expect(meta.shadow).toBe('none');
  });

  test('preserves existing metadata tags when tags are omitted', () => {
    const meta = buildGroupMetadataForSync({
      metadata: {
        tags: [{ id: 'existing', name: 'Existing', color: 'default' }],
        shadow: 'md',
      },
      styleOptions: { shadow: 'sm', icon: 'folder' },
    });
    expect(meta.tags).toEqual([{ id: 'existing', name: 'Existing', color: 'default' }]);
    expect(meta.shadow).toBe('md');
  });
});

import {
  edgeBelongsOnCanvas,
  ghostEdgeClassName,
  ghostNodeClassName,
} from '@/app/utils/canvas-ghost-mode';

describe('canvas-ghost-mode (#484)', () => {
  const visible = new Set(['a', 'b']);
  const allBase = new Set(['a', 'b', 'c', 'd']);

  describe('edgeBelongsOnCanvas', () => {
    it('ghosts off: requires both endpoints visible', () => {
      expect(edgeBelongsOnCanvas('a', 'b', visible, allBase, false)).toBe(true);
      expect(edgeBelongsOnCanvas('a', 'c', visible, allBase, false)).toBe(false);
    });

    it('ghosts on: requires both endpoints in base graph', () => {
      expect(edgeBelongsOnCanvas('a', 'c', visible, allBase, true)).toBe(true);
      expect(edgeBelongsOnCanvas('a', 'x', visible, allBase, true)).toBe(false);
    });
  });

  describe('ghostEdgeClassName', () => {
    it('empty when ghosts off', () => {
      expect(ghostEdgeClassName('a', 'b', visible, false)).toBe('');
    });

    it('marks edge when either endpoint is hidden', () => {
      expect(ghostEdgeClassName('a', 'b', visible, true)).toBe('');
      expect(ghostEdgeClassName('a', 'c', visible, true)).toBe('canvas-edge-ghost');
      expect(ghostEdgeClassName('c', 'd', visible, true)).toBe('canvas-edge-ghost');
    });
  });

  describe('ghostNodeClassName', () => {
    const group = { id: 'g1', nodeIds: ['a', 'c'] };

    it('empty when ghosts off', () => {
      expect(ghostNodeClassName('c', 'classNode', undefined, visible, false)).toBe('');
    });

    it('class node: ghost when not in visible set', () => {
      expect(ghostNodeClassName('a', 'classNode', undefined, visible, true)).toBe('');
      expect(ghostNodeClassName('c', 'classNode', undefined, visible, true)).toBe('canvas-node-ghost');
    });

    it('group node: ghost when no member is visible', () => {
      expect(ghostNodeClassName('g1', 'groupNode', group, visible, true)).toBe('');
      expect(ghostNodeClassName('g1', 'groupNode', { id: 'g1', nodeIds: ['c', 'd'] }, visible, true)).toBe(
        'canvas-node-ghost'
      );
    });
  });
});

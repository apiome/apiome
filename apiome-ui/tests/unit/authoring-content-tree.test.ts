/**
 * Content tree flattening and keyboard navigation (UXE-1.3).
 *
 * The WAI-ARIA tree pattern is the kind of contract that silently rots, so it
 * is tested as pure functions here rather than only through the rendered
 * component. The two properties that matter most: a collapsed node's children
 * are genuinely absent (not merely hidden, which would leave them reachable by
 * keyboard), and Arrow keys never move focus outside the visible rows.
 */

import {
  flattenAuthoringTree,
  resolveAuthoringTreeKey,
  revealAuthoringTreeNode,
  type AuthoringTreeNode,
} from '../../lib/authoring/content-tree';

const TREE: readonly AuthoringTreeNode[] = [
  {
    id: 'guides',
    label: 'Guides',
    children: [
      { id: 'start', label: 'Getting started' },
      { id: 'auth', label: 'Authentication' },
    ],
  },
  {
    id: 'pets',
    label: '/pets',
    children: [
      {
        id: 'post',
        label: 'POST /pets',
        children: [{ id: 'r201', label: '201 Created' }],
      },
    ],
  },
];

/**
 * Flatten the fixture with a given expansion set.
 *
 * @param expanded - Ids of expanded nodes.
 */
function rowsWith(...expanded: string[]) {
  return flattenAuthoringTree(TREE, new Set(expanded));
}

describe('flattenAuthoringTree', () => {
  it('omits the children of a collapsed node entirely', () => {
    const ids = rowsWith().map((row) => row.node.id);

    expect(ids).toEqual(['guides', 'pets']);
  });

  it('includes children once their parent is expanded', () => {
    const ids = rowsWith('guides').map((row) => row.node.id);

    expect(ids).toEqual(['guides', 'start', 'auth', 'pets']);
  });

  it('does not reveal grandchildren when only the grandparent is expanded', () => {
    const ids = rowsWith('pets').map((row) => row.node.id);

    expect(ids).toEqual(['guides', 'pets', 'post']);
    expect(ids).not.toContain('r201');
  });

  it('reports level, position and set size for aria attributes', () => {
    const rows = rowsWith('guides');
    const start = rows.find((row) => row.node.id === 'start')!;

    expect(start).toMatchObject({ level: 2, position: 1, setSize: 2 });
  });

  it('marks a childless node as not expandable, so it renders no aria-expanded', () => {
    const rows = rowsWith('guides');

    expect(rows.find((row) => row.node.id === 'start')!.expandable).toBe(false);
    expect(rows.find((row) => row.node.id === 'guides')!.expandable).toBe(true);
  });

  it('records ancestors nearest last, so a node can be revealed from a deep link', () => {
    const rows = rowsWith('pets', 'post');

    expect(rows.find((row) => row.node.id === 'r201')!.ancestorIds).toEqual(['pets', 'post']);
  });
});

describe('resolveAuthoringTreeKey', () => {
  it('moves down the visible rows', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'guides', 'ArrowDown')).toEqual({
      type: 'focus',
      nodeId: 'pets',
    });
  });

  it('does not move past the last row', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'pets', 'ArrowDown')).toEqual({ type: 'none' });
  });

  it('does not move above the first row', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'guides', 'ArrowUp')).toEqual({ type: 'none' });
  });

  it('expands a collapsed node with ArrowRight', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'guides', 'ArrowRight')).toEqual({
      type: 'expand',
      nodeId: 'guides',
    });
  });

  it('descends into an already expanded node with a second ArrowRight', () => {
    expect(resolveAuthoringTreeKey(rowsWith('guides'), 'guides', 'ArrowRight')).toEqual({
      type: 'focus',
      nodeId: 'start',
    });
  });

  it('does nothing on ArrowRight at a leaf', () => {
    expect(resolveAuthoringTreeKey(rowsWith('guides'), 'start', 'ArrowRight')).toEqual({
      type: 'none',
    });
  });

  it('collapses an expanded node with ArrowLeft', () => {
    expect(resolveAuthoringTreeKey(rowsWith('guides'), 'guides', 'ArrowLeft')).toEqual({
      type: 'collapse',
      nodeId: 'guides',
    });
  });

  it('ascends to the parent with ArrowLeft at a leaf', () => {
    expect(resolveAuthoringTreeKey(rowsWith('guides'), 'start', 'ArrowLeft')).toEqual({
      type: 'focus',
      nodeId: 'guides',
    });
  });

  it('does nothing on ArrowLeft at a collapsed root', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'guides', 'ArrowLeft')).toEqual({ type: 'none' });
  });

  it('jumps to the ends with Home and End', () => {
    const rows = rowsWith('guides');

    expect(resolveAuthoringTreeKey(rows, 'start', 'Home')).toEqual({
      type: 'focus',
      nodeId: 'guides',
    });
    expect(resolveAuthoringTreeKey(rows, 'start', 'End')).toEqual({ type: 'focus', nodeId: 'pets' });
  });

  it.each(['Enter', ' '])('activates the focused node with %j', (key) => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'pets', key)).toEqual({
      type: 'activate',
      nodeId: 'pets',
    });
  });

  it('leaves unrelated keys to the browser, so typing is never swallowed', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), 'guides', 'a')).toEqual({ type: 'none' });
  });

  it('starts at the first row when focus is unknown, so the tree is usable on first Tab', () => {
    expect(resolveAuthoringTreeKey(rowsWith(), undefined, 'ArrowDown')).toEqual({
      type: 'focus',
      nodeId: 'pets',
    });
  });

  it('does nothing at all on an empty tree', () => {
    expect(resolveAuthoringTreeKey([], undefined, 'ArrowDown')).toEqual({ type: 'none' });
  });
});

describe('revealAuthoringTreeNode', () => {
  it('expands every ancestor of the target', () => {
    const expanded = revealAuthoringTreeNode(TREE, new Set(), 'r201');

    expect([...expanded].sort()).toEqual(['pets', 'post']);
  });

  it('does not expand the target itself, which would be a side effect of revealing it', () => {
    expect(revealAuthoringTreeNode(TREE, new Set(), 'r201').has('r201')).toBe(false);
  });

  it('keeps existing expansion, so revealing one node does not collapse another', () => {
    const expanded = revealAuthoringTreeNode(TREE, new Set(['guides']), 'r201');

    expect(expanded.has('guides')).toBe(true);
  });

  it('returns the expansion unchanged for an unknown node', () => {
    expect([...revealAuthoringTreeNode(TREE, new Set(['guides']), 'nope')]).toEqual(['guides']);
  });
});

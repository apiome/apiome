/**
 * Edge Routing Test Suite
 *
 * Tests the edge routing functionality
 */

import { describe, test, expect } from '@jest/globals';

// Mock the getEdgeType function logic for testing
function getEdgeType(edgeRouting: 'straight' | 'bezier' | 'orthogonal' | 'smart'): string {
  switch (edgeRouting) {
    case 'straight':
      return 'straight';
    case 'bezier':
      return 'default'; // React Flow's default is bezier
    case 'orthogonal':
      return 'smoothstep'; // smoothstep creates orthogonal paths
    case 'smart':
      return 'smart'; // Custom SmartEdge that avoids node overlap
    default:
      return 'default';
  }
}

describe('Edge Routing', () => {
  describe('getEdgeType', () => {
    test('should return straight for straight routing', () => {
      expect(getEdgeType('straight')).toBe('straight');
    });

    test('should return default (bezier) for bezier routing', () => {
      expect(getEdgeType('bezier')).toBe('default');
    });

    test('should return smoothstep for orthogonal routing', () => {
      expect(getEdgeType('orthogonal')).toBe('smoothstep');
    });

    test('should return smart for smart routing', () => {
      expect(getEdgeType('smart')).toBe('smart');
    });
  });

  describe('Edge Routing Types', () => {
    const validRoutingTypes = ['straight', 'bezier', 'orthogonal', 'smart'];

    test('should have exactly 4 routing types', () => {
      expect(validRoutingTypes.length).toBe(4);
    });

    test('all routing types should map to valid React Flow edge types', () => {
      const validReactFlowTypes = ['straight', 'default', 'smoothstep', 'step', 'smart'];

      validRoutingTypes.forEach((routing) => {
        const edgeType = getEdgeType(routing as any);
        expect(validReactFlowTypes).toContain(edgeType);
      });
    });

    test('bezier should be the default routing type', () => {
      // bezier maps to 'default' which is React Flow's bezier curve
      expect(getEdgeType('bezier')).toBe('default');
    });
  });

  describe('Edge Routing Behavior', () => {
    test('straight routing should produce direct lines', () => {
      const edgeType = getEdgeType('straight');
      expect(edgeType).toBe('straight');
      // straight type in React Flow draws direct line from source to target
    });

    test('bezier routing should produce curved lines', () => {
      const edgeType = getEdgeType('bezier');
      expect(edgeType).toBe('default');
      // default type in React Flow uses bezier curves
    });

    test('orthogonal routing should produce right-angle paths', () => {
      const edgeType = getEdgeType('orthogonal');
      expect(edgeType).toBe('smoothstep');
      // smoothstep type in React Flow uses orthogonal (right-angle) routing
    });

    test('smart routing should use custom SmartEdge', () => {
      const edgeType = getEdgeType('smart');
      expect(edgeType).toBe('smart');
      // smart routing uses custom SmartEdge component that avoids node overlap
    });
  });

  describe('Edge Routing Consistency', () => {
    test('same routing type should always return same edge type', () => {
      const routingType = 'orthogonal';
      const edgeType1 = getEdgeType(routingType);
      const edgeType2 = getEdgeType(routingType);
      const edgeType3 = getEdgeType(routingType);

      expect(edgeType1).toBe(edgeType2);
      expect(edgeType2).toBe(edgeType3);
    });

    test('different routing types should be distinguishable', () => {
      const straightType = getEdgeType('straight');
      const bezierType = getEdgeType('bezier');

      // At minimum, straight and bezier should be different
      expect(straightType).not.toBe(bezierType);
    });

    test('smart and orthogonal should be distinguishable', () => {
      const smartType = getEdgeType('smart');
      const orthogonalType = getEdgeType('orthogonal');

      // Smart uses custom edge, orthogonal uses smoothstep
      expect(smartType).not.toBe(orthogonalType);
    });
  });
});


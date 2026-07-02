/**
 * Edge Styling Test Suite
 *
 * Tests the edge styling utilities and functionality
 */

import { describe, test, expect } from '@jest/globals';
import {
  getStrokeDashArray,
  getEdgeStrokeStyle,
  categorizeEdge,
  applyEdgeStyling
} from '../src/app/utils/edge-styling';

describe('Edge Styling Utilities', () => {
  describe('getStrokeDashArray', () => {
    test('should return undefined for solid style', () => {
      expect(getStrokeDashArray('solid')).toBeUndefined();
    });

    test('should return dash pattern for dashed style', () => {
      expect(getStrokeDashArray('dashed')).toBe('5,5');
    });

    test('should return dot pattern for dotted style', () => {
      expect(getStrokeDashArray('dotted')).toBe('2,3');
    });

    test('should return undefined for double style', () => {
      expect(getStrokeDashArray('double')).toBeUndefined();
    });
  });

  describe('getEdgeStrokeStyle', () => {
    test('should return basic stroke for solid style', () => {
      const result = getEdgeStrokeStyle('solid', '#3b82f6', 2);
      expect(result).toEqual({
        stroke: '#3b82f6',
        strokeWidth: 2,
      });
    });

    test('should include dash array for dashed style', () => {
      const result = getEdgeStrokeStyle('dashed', '#3b82f6', 2);
      expect(result.strokeDasharray).toBe('5,5');
      expect(result.stroke).toBe('#3b82f6');
    });

    test('should include dash array for dotted style', () => {
      const result = getEdgeStrokeStyle('dotted', '#3b82f6', 2);
      expect(result.strokeDasharray).toBe('2,3');
    });

    test('should use thicker stroke for double style', () => {
      const result = getEdgeStrokeStyle('double', '#3b82f6', 2);
      expect(result.strokeWidth).toBe(5); // 2 * 2.5
      expect(result.strokeDasharray).toBeUndefined();
    });
  });

  describe('categorizeEdge', () => {
    test('should categorize edge with both markers as bidirectional', () => {
      const edge = {
        source: 'A',
        target: 'B',
        markerStart: { type: 'arrow' },
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('bidirectional');
    });

    test('should categorize anyOf edge as optional', () => {
      const edge = {
        source: 'A',
        target: 'B',
        label: 'anyOf:User',
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('optional');
    });

    test('should categorize oneOf edge as optional', () => {
      const edge = {
        source: 'A',
        target: 'B',
        label: 'oneOf:User',
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('optional');
    });

    test('should categorize allOf edge as weak', () => {
      const edge = {
        source: 'A',
        target: 'B',
        label: 'allOf:User',
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('weak');
    });

    test('should categorize standard property edge as direct', () => {
      const edge = {
        source: 'A',
        target: 'B',
        label: 'user (1:1)',
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('direct');
    });

    test('should handle edge without label', () => {
      const edge = {
        source: 'A',
        target: 'B',
        markerEnd: { type: 'arrow' },
      };
      expect(categorizeEdge(edge)).toBe('direct');
    });
  });

  describe('applyEdgeStyling', () => {
    const defaultStyling = {
      directReferences: 'solid' as const,
      optionalReferences: 'dashed' as const,
      weakReferences: 'dotted' as const,
      bidirectional: 'double' as const,
      directColor: '#3b82f6',
      optionalColor: '#f97316',
      weakColor: '#8b5cf6',
      bidirectionalColor: '#ec4899',
    };

    test('should apply solid styling to direct reference', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'user (1:1)',
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      };

      const result = applyEdgeStyling(edge, defaultStyling);
      expect(result.style.strokeDasharray).toBeUndefined();
    });

    test('should apply dashed styling to optional reference', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'anyOf:User',
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      };

      const result = applyEdgeStyling(edge, defaultStyling);
      expect(result.style.strokeDasharray).toBe('5,5');
    });

    test('should apply dotted styling to weak reference', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'allOf:User',
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      };

      const result = applyEdgeStyling(edge, defaultStyling);
      expect(result.style.strokeDasharray).toBe('2,3');
    });

    test('should apply double styling to bidirectional', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        markerStart: { type: 'arrow' },
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      };

      const result = applyEdgeStyling(edge, defaultStyling);
      expect(result.style.strokeWidth).toBe(5); // 2 * 2.5 for double
    });

    test('should preserve original edge properties', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'user (1:1)',
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
        animated: true,
        type: 'smoothstep',
      };

      const result = applyEdgeStyling(edge, defaultStyling);
      expect(result.id).toBe('edge1');
      expect(result.source).toBe('A');
      expect(result.target).toBe('B');
      expect(result.animated).toBe(true);
      expect(result.type).toBe('smoothstep');
    });

    test('should use custom styling preferences', () => {
      const customStyling = {
        directReferences: 'dashed' as const,
        optionalReferences: 'dotted' as const,
        weakReferences: 'solid' as const,
        bidirectional: 'solid' as const,
        directColor: '#ef4444',
        optionalColor: '#22c55e',
        weakColor: '#06b6d4',
        bidirectionalColor: '#f59e0b',
      };

      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'user (1:1)',
        markerEnd: { type: 'arrow' },
        style: { stroke: '#3b82f6', strokeWidth: 2 },
      };

      const result = applyEdgeStyling(edge, customStyling);
      expect(result.style.strokeDasharray).toBe('5,5'); // dashed for direct
      expect(result.style.stroke).toBe('#ef4444'); // custom red color
    });
  });

  describe('Edge Styling Integration', () => {
    test('should handle edge without existing style', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        markerEnd: { type: 'arrow' },
      };

      const styling = {
        directReferences: 'solid' as const,
        optionalReferences: 'dashed' as const,
        weakReferences: 'dotted' as const,
        bidirectional: 'double' as const,
        directColor: '#3b82f6',
        optionalColor: '#f97316',
        weakColor: '#8b5cf6',
        bidirectionalColor: '#ec4899',
      };

      const result = applyEdgeStyling(edge, styling);
      expect(result.style).toBeDefined();
      expect(result.style.stroke).toBe('#3b82f6'); // direct color
    });

    test('should apply custom colors to edges', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        label: 'anyOf:User',
        markerEnd: { type: 'arrow', color: '#000000' },
        style: { stroke: '#000000', strokeWidth: 3 },
      };

      const styling = {
        directReferences: 'solid' as const,
        optionalReferences: 'dashed' as const,
        weakReferences: 'dotted' as const,
        bidirectional: 'double' as const,
        directColor: '#3b82f6',
        optionalColor: '#ea580c',
        weakColor: '#8b5cf6',
        bidirectionalColor: '#ec4899',
      };

      const result = applyEdgeStyling(edge, styling);
      expect(result.style.stroke).toBe('#ea580c'); // Optional color (orange)
      expect(result.markerEnd.color).toBe('#ea580c'); // Marker should match
    });

    test('should update marker colors to match edge color', () => {
      const edge = {
        id: 'edge1',
        source: 'A',
        target: 'B',
        markerStart: { type: 'arrow', color: '#000000' },
        markerEnd: { type: 'arrow', color: '#000000' },
        style: { stroke: '#000000', strokeWidth: 2 },
      };

      const styling = {
        directReferences: 'solid' as const,
        optionalReferences: 'dashed' as const,
        weakReferences: 'dotted' as const,
        bidirectional: 'double' as const,
        directColor: '#3b82f6',
        optionalColor: '#f97316',
        weakColor: '#8b5cf6',
        bidirectionalColor: '#ec4899',
      };

      const result = applyEdgeStyling(edge, styling);
      expect(result.markerStart.color).toBe('#ec4899'); // Bidirectional color
      expect(result.markerEnd.color).toBe('#ec4899'); // Bidirectional color
    });
  });
});


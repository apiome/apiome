/**
 * Edge Styling Utilities
 *
 * Converts edge style types to CSS stroke properties
 */

import type { EdgeStyleType, EdgeArrowStyle } from '../ade/studio/StudioContext';

/**
 * Convert edge arrow style to ReactFlow marker type
 */
export function getMarkerType(arrowStyle: EdgeArrowStyle): string {
  switch (arrowStyle) {
    case 'arrow':
      return 'arrowclosed';
    case 'diamond':
      return 'arrowclosed'; // We'll use SVG markers for diamond
    case 'circle':
      return 'arrowclosed'; // We'll use SVG markers for circle
    case 'open':
      return 'arrow';
    default:
      return 'arrowclosed';
  }
}

/**
 * Get custom marker ID for non-standard arrow styles
 * These markers should be defined as SVG defs in the canvas
 */
export function getCustomMarkerId(arrowStyle: EdgeArrowStyle, color: string): string | null {
  const colorId = color.replace('#', '');
  switch (arrowStyle) {
    case 'diamond':
      return `diamond-marker-${colorId}`;
    case 'circle':
      return `circle-marker-${colorId}`;
    default:
      return null;
  }
}

/**
 * Convert edge style type to strokeDasharray value
 */
export function getStrokeDashArray(styleType: EdgeStyleType, strokeWidth: number = 2): string | undefined {
  switch (styleType) {
    case 'solid':
      return undefined; // No dash array for solid lines
    case 'dashed':
      return '5,5'; // Medium dashes
    case 'dotted':
      return '2,3'; // Small dots with gaps
    case 'double':
      return undefined; // Double lines don't use dash array
    default:
      return undefined;
  }
}

/**
 * Get stroke style properties for an edge
 * Returns object with stroke properties to apply to edge style
 */
export function getEdgeStrokeStyle(
  styleType: EdgeStyleType,
  baseColor: string,
  strokeWidth: number = 2
): {
  stroke?: string;
  strokeWidth?: number;
  strokeDasharray?: string;
} {
  const baseStyle: any = {
    stroke: baseColor,
    strokeWidth,
  };

  const dashArray = getStrokeDashArray(styleType, strokeWidth);
  if (dashArray) {
    baseStyle.strokeDasharray = dashArray;
  }

  // For double lines, we'll use a thicker stroke with a lighter inner line
  // This is handled differently - we return special properties
  if (styleType === 'double') {
    return {
      stroke: baseColor,
      strokeWidth: strokeWidth * 2.5, // Make it thicker for double effect
      strokeDasharray: undefined,
    };
  }

  return baseStyle;
}

/**
 * Determine edge category based on edge properties
 * This helps categorize edges for styling
 */
export function categorizeEdge(edge: {
  label?: string;
  markerStart?: any;
  markerEnd?: any;
  source: string;
  target: string;
}): 'direct' | 'optional' | 'weak' | 'bidirectional' {
  // Bidirectional: has both start and end markers
  if (edge.markerStart && edge.markerEnd) {
    return 'bidirectional';
  }

  // Optional: typically composition types like anyOf, oneOf
  const label = edge.label?.toLowerCase() || '';
  if (label.includes('anyof') || label.includes('oneof')) {
    return 'optional';
  }

  // Weak: composition like allOf or references with specific patterns
  if (label.includes('allof')) {
    return 'weak';
  }

  // Direct: standard property references
  return 'direct';
}

/**
 * Apply edge styling based on category and user preferences
 */
export function applyEdgeStyling(
  edge: any,
  edgeStylingOptions: {
    directReferences: EdgeStyleType;
    optionalReferences: EdgeStyleType;
    weakReferences: EdgeStyleType;
    bidirectional: EdgeStyleType;
    directColor: string;
    optionalColor: string;
    weakColor: string;
    bidirectionalColor: string;
    directArrowStyle?: EdgeArrowStyle;
    optionalArrowStyle?: EdgeArrowStyle;
    weakArrowStyle?: EdgeArrowStyle;
    bidirectionalArrowStyle?: EdgeArrowStyle;
  }
): any {
  const category = categorizeEdge(edge);
  let styleType: EdgeStyleType;
  let color: string;
  let arrowStyle: EdgeArrowStyle;

  switch (category) {
    case 'direct':
      styleType = edgeStylingOptions.directReferences;
      color = edgeStylingOptions.directColor;
      arrowStyle = edgeStylingOptions.directArrowStyle || 'arrow';
      break;
    case 'optional':
      styleType = edgeStylingOptions.optionalReferences;
      color = edgeStylingOptions.optionalColor;
      arrowStyle = edgeStylingOptions.optionalArrowStyle || 'arrow';
      break;
    case 'weak':
      styleType = edgeStylingOptions.weakReferences;
      color = edgeStylingOptions.weakColor;
      arrowStyle = edgeStylingOptions.weakArrowStyle || 'arrow';
      break;
    case 'bidirectional':
      styleType = edgeStylingOptions.bidirectional;
      color = edgeStylingOptions.bidirectionalColor;
      arrowStyle = edgeStylingOptions.bidirectionalArrowStyle || 'arrow';
      break;
  }

  // Get the current stroke width
  const currentStrokeWidth = edge.style?.strokeWidth || 2;

  // Apply the styling with custom color
  const strokeStyle = getEdgeStrokeStyle(styleType, color, currentStrokeWidth);

  // Determine marker type based on arrow style
  const markerType = getMarkerType(arrowStyle);
  const customMarkerId = getCustomMarkerId(arrowStyle, color);

  // Update marker colors and types to match edge settings
  let updatedMarkerStart = undefined;
  let updatedMarkerEnd = undefined;

  if (edge.markerStart) {
    if (customMarkerId) {
      // Use custom SVG marker for diamond/circle
      updatedMarkerStart = `url(#${customMarkerId})`;
    } else {
      updatedMarkerStart = {
        ...edge.markerStart,
        type: markerType,
        color,
      };
    }
  }

  if (edge.markerEnd) {
    if (customMarkerId) {
      // Use custom SVG marker for diamond/circle
      updatedMarkerEnd = `url(#${customMarkerId})`;
    } else {
      updatedMarkerEnd = {
        ...edge.markerEnd,
        type: markerType,
        color,
      };
    }
  }

  return {
    ...edge,
    style: {
      ...edge.style,
      ...strokeStyle,
    },
    markerStart: updatedMarkerStart,
    markerEnd: updatedMarkerEnd,
  };
}


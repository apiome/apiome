/**
 * Shared layout constants for the migration canvas.
 * Values are chosen to match MigrationClassNode's actual rendered layout
 * (Tailwind: header py-2 + text-sm, content py-2, ul space-y-2.5, li min-h-[1.25rem])
 * so rule nodes align with property rows.
 */

// Node positions
export const FROM_NODE_X = 30;
export const TO_NODE_X = 650;
export const NODE_Y = 150;
export const RULE_NODE_X = 340;

// MigrationClassNode layout (px)
// Header: py-2 (8+8) + text-sm with line-height (~20px) ≈ 38
export const CLASS_NODE_HEADER_HEIGHT = 38;
// Content: py-2 top
export const CLASS_NODE_CONTENT_PADDING_TOP = 8;
// First property row center from content top: li min-h 20px → center at 10
export const CLASS_NODE_FIRST_ROW_CENTER_OFFSET = 10;
// Each row: li 20px + space-y-2.5 (10px)
export const CLASS_NODE_ROW_HEIGHT = 20;
export const CLASS_NODE_ROW_GAP = 10;

/** Y offset from class node top to the vertical center of the first property handle */
export const FIRST_PROPERTY_CENTER_OFFSET =
  CLASS_NODE_HEADER_HEIGHT +
  CLASS_NODE_CONTENT_PADDING_TOP +
  CLASS_NODE_FIRST_ROW_CENTER_OFFSET;

/** Vertical distance between property row centers */
export const PROPERTY_ROW_HEIGHT = CLASS_NODE_ROW_HEIGHT + CLASS_NODE_ROW_GAP;

/** Approximate height of a rule node (single output) for vertical centering; compact so it doesn't overlap "+" passthrough icons */
export const RULE_NODE_HEIGHT_ESTIMATE = 20;

/** Nudge rule nodes down so they don't overlap the "+" passthrough button on the row above */
const RULE_NODE_VERTICAL_NUDGE = 4;

/**
 * Y position for a rule node so its vertical center aligns with the i-th property row
 * of the from/to class node (both at NODE_Y), with a small nudge down to avoid overlapping "+" icons.
 */
export function ruleNodeYForPropertyIndex(propertyIndex: number): number {
  const centerY = NODE_Y + FIRST_PROPERTY_CENTER_OFFSET + propertyIndex * PROPERTY_ROW_HEIGHT;
  return centerY - RULE_NODE_HEIGHT_ESTIMATE / 2 + RULE_NODE_VERTICAL_NUDGE;
}

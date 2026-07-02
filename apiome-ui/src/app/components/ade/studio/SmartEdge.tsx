'use client';

import React, { useMemo } from 'react';
import { EdgeProps, getBezierPath, getSmoothStepPath, useNodes, Node } from '@xyflow/react';

interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * SmartEdge - A custom edge that routes around nodes to avoid overlap
 * Uses A* pathfinding algorithm to find the optimal path
 */
const SmartEdge: React.FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  markerStart,
  label,
  labelStyle,
  labelBgStyle,
  data,
}) => {
  const nodes = useNodes();

  // Get bounding boxes for all nodes except source and target
  const obstacles = useMemo(() => {
    const sourceId = data?.sourceNodeId;
    const targetId = data?.targetNodeId;

    return nodes
      .filter((node: Node) => node.id !== sourceId && node.id !== targetId && node.type !== 'groupNode')
      .map((node: Node): BoundingBox => ({
        x: node.position.x,
        y: node.position.y,
        width: (node.measured?.width as number) || (node.width as number) || 260,
        height: (node.measured?.height as number) || (node.height as number) || 200,
      }));
  }, [nodes, data?.sourceNodeId, data?.targetNodeId]);

  // Calculate smart path that avoids obstacles
  const { path, labelX, labelY } = useMemo(() => {
    // If no obstacles or straight line doesn't intersect anything, use simple path
    if (obstacles.length === 0 || !hasObstacleIntersection(sourceX, sourceY, targetX, targetY, obstacles)) {
      const [edgePath, labelX, labelY] = getSmoothStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
        borderRadius: 8,
      });
      return { path: edgePath, labelX, labelY };
    }

    // Calculate smart path using waypoints
    const waypoints = calculateSmartPath(
      sourceX,
      sourceY,
      targetX,
      targetY,
      obstacles,
      sourcePosition,
      targetPosition
    );

    // Convert waypoints to SVG path
    if (waypoints.length < 2) {
      const [edgePath, lx, ly] = getSmoothStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
        borderRadius: 8,
      });
      return { path: edgePath, labelX: lx, labelY: ly };
    }

    // Build path from waypoints
    const pathSegments: string[] = [`M ${waypoints[0].x} ${waypoints[0].y}`];

    for (let i = 1; i < waypoints.length; i++) {
      const prev = waypoints[i - 1];
      const curr = waypoints[i];
      const next = waypoints[i + 1];

      if (next) {
        // Add rounded corner
        const cornerRadius = 8;
        const dx1 = curr.x - prev.x;
        const dy1 = curr.y - prev.y;
        const dx2 = next.x - curr.x;
        const dy2 = next.y - curr.y;

        const len1 = Math.sqrt(dx1 * dx1 + dy1 * dy1);
        const len2 = Math.sqrt(dx2 * dx2 + dy2 * dy2);

        if (len1 > cornerRadius * 2 && len2 > cornerRadius * 2) {
          // Calculate corner start and end points
          const ratio1 = Math.min(cornerRadius, len1 / 2) / len1;
          const ratio2 = Math.min(cornerRadius, len2 / 2) / len2;

          const cornerStartX = curr.x - dx1 * ratio1;
          const cornerStartY = curr.y - dy1 * ratio1;
          const cornerEndX = curr.x + dx2 * ratio2;
          const cornerEndY = curr.y + dy2 * ratio2;

          pathSegments.push(`L ${cornerStartX} ${cornerStartY}`);
          pathSegments.push(`Q ${curr.x} ${curr.y} ${cornerEndX} ${cornerEndY}`);
        } else {
          pathSegments.push(`L ${curr.x} ${curr.y}`);
        }
      } else {
        pathSegments.push(`L ${curr.x} ${curr.y}`);
      }
    }

    // Calculate label position (middle of path)
    const midIndex = Math.floor(waypoints.length / 2);
    const midPoint = waypoints[midIndex];

    return {
      path: pathSegments.join(' '),
      labelX: midPoint.x,
      labelY: midPoint.y,
    };
  }, [sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, obstacles]);

  // Invisible wide path for easier hover (hit area ~20px instead of stroke width)
  const HIT_AREA_STROKE = 20;

  return (
    <>
      <path
        id={id}
        style={style}
        className="react-flow__edge-path"
        d={path}
        markerEnd={markerEnd}
        markerStart={markerStart}
        fill="none"
      />
      {/* Wider invisible path so hover doesn't require pixel-perfect cursor */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={HIT_AREA_STROKE}
        style={{ cursor: 'pointer' }}
      />
      {label && (
        <g transform={`translate(${labelX}, ${labelY})`} style={{ pointerEvents: 'none' }}>
          {(() => {
            const text = label as string;
            const w = Math.max(56, Math.min(180, text.length * 6.2 + 14));
            const h = 18;
            return (
              <>
                <rect
                  x={-w / 2}
                  y={-h / 2}
                  width={w}
                  height={h}
                  rx={4}
                  style={
                    labelBgStyle ?? {
                      fill: 'var(--node-surface-muted)',
                      stroke: 'var(--node-border)',
                      strokeWidth: 1,
                    }
                  }
                />
                <text
                  x={0}
                  y={3}
                  textAnchor="middle"
                  style={
                    labelStyle ?? {
                      fill: 'var(--node-text-muted)',
                      fontSize: 10,
                      fontWeight: 500,
                      letterSpacing: '-0.01em',
                      fontFamily:
                        'var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
                    }
                  }
                  className="react-flow__edge-text"
                >
                  {text}
                </text>
              </>
            );
          })()}
        </g>
      )}
    </>
  );
};

/**
 * Check if a line segment intersects with any obstacle
 */
function hasObstacleIntersection(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  obstacles: BoundingBox[]
): boolean {
  const padding = 20; // Extra padding around nodes

  for (const obs of obstacles) {
    const left = obs.x - padding;
    const right = obs.x + obs.width + padding;
    const top = obs.y - padding;
    const bottom = obs.y + obs.height + padding;

    // Check if line segment intersects rectangle
    if (lineIntersectsRect(x1, y1, x2, y2, left, top, right, bottom)) {
      return true;
    }
  }
  return false;
}

/**
 * Check if a line segment intersects a rectangle
 */
function lineIntersectsRect(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  left: number,
  top: number,
  right: number,
  bottom: number
): boolean {
  // Check if either endpoint is inside the rectangle
  if ((x1 >= left && x1 <= right && y1 >= top && y1 <= bottom) ||
      (x2 >= left && x2 <= right && y2 >= top && y2 <= bottom)) {
    return true;
  }

  // Check line intersection with each edge of the rectangle
  return (
    lineSegmentIntersection(x1, y1, x2, y2, left, top, right, top) ||
    lineSegmentIntersection(x1, y1, x2, y2, right, top, right, bottom) ||
    lineSegmentIntersection(x1, y1, x2, y2, left, bottom, right, bottom) ||
    lineSegmentIntersection(x1, y1, x2, y2, left, top, left, bottom)
  );
}

/**
 * Check if two line segments intersect
 */
function lineSegmentIntersection(
  x1: number, y1: number, x2: number, y2: number,
  x3: number, y3: number, x4: number, y4: number
): boolean {
  const denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1);
  if (Math.abs(denom) < 0.0001) return false;

  const ua = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / denom;
  const ub = ((x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)) / denom;

  return ua >= 0 && ua <= 1 && ub >= 0 && ub <= 1;
}

/**
 * Calculate smart path using orthogonal routing with obstacle avoidance
 */
function calculateSmartPath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  obstacles: BoundingBox[],
  sourcePosition: string,
  targetPosition: string
): { x: number; y: number }[] {
  const padding = 30; // Padding around obstacles

  // Create a simplified grid-based approach
  // First, try different routing strategies and pick the best one

  const strategies = [
    // Strategy 1: Go horizontal first, then vertical
    () => routeHorizontalFirst(sourceX, sourceY, targetX, targetY, obstacles, padding),
    // Strategy 2: Go vertical first, then horizontal
    () => routeVerticalFirst(sourceX, sourceY, targetX, targetY, obstacles, padding),
    // Strategy 3: Route around the left side
    () => routeAroundSide(sourceX, sourceY, targetX, targetY, obstacles, padding, 'left'),
    // Strategy 4: Route around the right side
    () => routeAroundSide(sourceX, sourceY, targetX, targetY, obstacles, padding, 'right'),
    // Strategy 5: Route around the top
    () => routeAroundSide(sourceX, sourceY, targetX, targetY, obstacles, padding, 'top'),
    // Strategy 6: Route around the bottom
    () => routeAroundSide(sourceX, sourceY, targetX, targetY, obstacles, padding, 'bottom'),
  ];

  // Try each strategy and pick the one with fewest intersections
  let bestPath: { x: number; y: number }[] = [];
  let minIntersections = Infinity;

  for (const strategy of strategies) {
    const path = strategy();
    const intersections = countPathIntersections(path, obstacles, padding);

    if (intersections < minIntersections) {
      minIntersections = intersections;
      bestPath = path;

      if (intersections === 0) break; // Found a clean path
    }
  }

  return bestPath;
}

/**
 * Route horizontal first, then vertical
 */
function routeHorizontalFirst(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  obstacles: BoundingBox[],
  padding: number
): { x: number; y: number }[] {
  const midX = (sourceX + targetX) / 2;

  return [
    { x: sourceX, y: sourceY },
    { x: midX, y: sourceY },
    { x: midX, y: targetY },
    { x: targetX, y: targetY },
  ];
}

/**
 * Route vertical first, then horizontal
 */
function routeVerticalFirst(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  obstacles: BoundingBox[],
  padding: number
): { x: number; y: number }[] {
  const midY = (sourceY + targetY) / 2;

  return [
    { x: sourceX, y: sourceY },
    { x: sourceX, y: midY },
    { x: targetX, y: midY },
    { x: targetX, y: targetY },
  ];
}

/**
 * Route around a specific side
 */
function routeAroundSide(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  obstacles: BoundingBox[],
  padding: number,
  side: 'left' | 'right' | 'top' | 'bottom'
): { x: number; y: number }[] {
  // Find the combined bounding box of all obstacles in the path
  const relevantObstacles = obstacles.filter(obs => {
    const minX = Math.min(sourceX, targetX) - padding;
    const maxX = Math.max(sourceX, targetX) + padding;
    const minY = Math.min(sourceY, targetY) - padding;
    const maxY = Math.max(sourceY, targetY) + padding;

    return (
      obs.x + obs.width >= minX &&
      obs.x <= maxX &&
      obs.y + obs.height >= minY &&
      obs.y <= maxY
    );
  });

  if (relevantObstacles.length === 0) {
    return routeHorizontalFirst(sourceX, sourceY, targetX, targetY, obstacles, padding);
  }

  // Calculate the outer bounds of all relevant obstacles
  let minObsX = Infinity, maxObsX = -Infinity;
  let minObsY = Infinity, maxObsY = -Infinity;

  for (const obs of relevantObstacles) {
    minObsX = Math.min(minObsX, obs.x);
    maxObsX = Math.max(maxObsX, obs.x + obs.width);
    minObsY = Math.min(minObsY, obs.y);
    maxObsY = Math.max(maxObsY, obs.y + obs.height);
  }

  const waypoints: { x: number; y: number }[] = [{ x: sourceX, y: sourceY }];

  switch (side) {
    case 'left': {
      const leftX = minObsX - padding;
      waypoints.push({ x: leftX, y: sourceY });
      waypoints.push({ x: leftX, y: targetY });
      break;
    }
    case 'right': {
      const rightX = maxObsX + padding;
      waypoints.push({ x: rightX, y: sourceY });
      waypoints.push({ x: rightX, y: targetY });
      break;
    }
    case 'top': {
      const topY = minObsY - padding;
      waypoints.push({ x: sourceX, y: topY });
      waypoints.push({ x: targetX, y: topY });
      break;
    }
    case 'bottom': {
      const bottomY = maxObsY + padding;
      waypoints.push({ x: sourceX, y: bottomY });
      waypoints.push({ x: targetX, y: bottomY });
      break;
    }
  }

  waypoints.push({ x: targetX, y: targetY });
  return waypoints;
}

/**
 * Count how many path segments intersect with obstacles
 */
function countPathIntersections(
  path: { x: number; y: number }[],
  obstacles: BoundingBox[],
  padding: number
): number {
  let count = 0;

  for (let i = 0; i < path.length - 1; i++) {
    const p1 = path[i];
    const p2 = path[i + 1];

    for (const obs of obstacles) {
      const left = obs.x - padding / 2;
      const right = obs.x + obs.width + padding / 2;
      const top = obs.y - padding / 2;
      const bottom = obs.y + obs.height + padding / 2;

      if (lineIntersectsRect(p1.x, p1.y, p2.x, p2.y, left, top, right, bottom)) {
        count++;
      }
    }
  }

  return count;
}

export default SmartEdge;


# Edge Routing Feature

## Overview

Added edge routing options to the canvas editor, allowing users to customize how edges (connection lines) are drawn between nodes.

## Routing Options

The following edge routing styles are now available:

### 1. Straight Lines
- **Type**: `straight`
- **Description**: Direct lines between connected nodes
- **Best For**: Simple diagrams with few connections
- **Visual**: Diagonal lines from source to target

### 2. Curved (Bezier)
- **Type**: `bezier`
- **Description**: Smooth curved connections using bezier curves
- **Best For**: General use, aesthetically pleasing
- **Visual**: S-shaped curves that flow naturally
- **Default**: Yes - this is the default option

### 3. Orthogonal (Right Angles)
- **Type**: `orthogonal`
- **Description**: Right-angle paths using only horizontal and vertical segments
- **Best For**: Technical diagrams, UML-style layouts
- **Visual**: Step-like paths with 90-degree turns

### 4. Smart Routing
- **Type**: `smart`
- **Description**: Custom edge component that intelligently routes around other nodes to avoid overlap
- **Best For**: Complex diagrams with many overlapping connections
- **Visual**: Orthogonal paths that automatically find clean routes around obstacles
- **Implementation**: Uses a custom `SmartEdge` component with pathfinding algorithm

## User Interface

### Accessing Edge Routing

1. Click the **Settings** button (gear icon) in the Studio Header
2. Scroll to the **Edge Routing** section
3. Click one of the four routing buttons:
   - **Straight** - Direct lines
   - **Curved** - Bezier curves (default)
   - **Orthogonal** - Right-angle paths
   - **Smart** - Automatic obstacle avoidance

### Visual Layout

The Edge Routing section displays a 2x2 grid of buttons:
```
[Straight]  [Curved]
[Orthogonal]  [Smart]
```

Each button includes:
- An icon representing the routing style
- The routing name
- Active state highlighting (indigo when selected)

A description below the buttons explains the currently selected routing style.

## Implementation Details

### Files Modified

1. **`/src/app/ade/studio/StudioContext.tsx`**
   - Added `EdgeRoutingType` type: `'straight' | 'bezier' | 'orthogonal' | 'smart'`
   - Added `edgeRouting` state with localStorage persistence
   - Added `setEdgeRouting` function to context
   - Default value: `'bezier'`

2. **`/src/app/ade/studio/components/StudioHeader.tsx`**
   - Added `edgeRouting` and `setEdgeRouting` to context destructuring
   - Added Edge Routing section with 2x2 button grid
   - Each button has:
     - Custom SVG icon
     - Routing name
     - Active state styling
     - Tooltip describing the routing behavior
   - Dynamic description text based on selected routing

3. **`/src/app/ade/studio/editor/page.tsx`**
   - Added `edgeRouting` to context imports
   - Added `getEdgeType()` helper function to convert routing type to React Flow edge type:
     - `straight` → `'straight'`
     - `bezier` → `'default'` (React Flow's bezier)
     - `orthogonal` → `'smoothstep'`
     - `smart` → `'smart'` (custom SmartEdge component)
   - Added `edgeTypes` with custom SmartEdge component
   - Updated all edge creation to use `getEdgeType()` and include `data` with node IDs
   - Added `edgeRouting` to useEffect dependency for edge regeneration

4. **`/src/app/components/ade/studio/SmartEdge.tsx`** (New)
   - Custom React Flow edge component for smart routing
   - Uses pathfinding algorithm to avoid node overlap
   - Tries multiple routing strategies:
     - Horizontal-first routing
     - Vertical-first routing
     - Route around left/right/top/bottom
   - Picks the path with fewest obstacle intersections
   - Features rounded corners at waypoints
   - Proper label positioning at path midpoint

### Technical Mapping

| Our Type | React Flow Edge Type | Description |
|----------|---------------------|-------------|
| `straight` | `straight` | Direct line |
| `bezier` | `default` | Bezier curve |
| `orthogonal` | `smoothstep` | Right-angle steps |
| `smart` | `smart` (custom) | Smart obstacle avoidance |

### State Persistence

- Edge routing preference is saved to browser localStorage as `edgeRouting`
- Persists across browser sessions
- Changes apply immediately to all edges on the canvas

## Usage Examples

### Technical Diagrams
Use **Orthogonal** routing for:
- UML class diagrams
- ERD diagrams
- System architecture diagrams
- Any diagram where right angles are preferred

### Simple Connections
Use **Straight** routing for:
- Minimal diagrams with few nodes
- When direct visual connection is important
- Performance-critical scenarios (simplest rendering)

### General Use
Use **Curved (Bezier)** routing for:
- Default general-purpose diagramming
- Aesthetically pleasing layouts
- Flowing, organic-looking connections

### Complex Layouts
Use **Smart** routing for:
- Diagrams with many overlapping connections
- When nodes are densely packed
- Automatic layout optimization

## Future Enhancements

Potential improvements for future iterations:

1. ✅ **Smart Routing** - Implemented pathfinding algorithm to avoid node overlap
2. **Edge Bundling** - Group parallel edges together
3. **Custom Corner Radius** - Adjustable smoothness for orthogonal routing
4. **Animation Options** - Different animation styles per routing type
5. **Per-Edge Routing** - Allow different routing for individual edges
6. **Routing Presets** - Save and load routing configurations
7. **A* Pathfinding** - More sophisticated pathfinding for complex layouts

## Compatibility

- ✅ Works with all edge styles (solid, dashed, dotted, double)
- ✅ Works with all edge colors
- ✅ Compatible with dark mode
- ✅ Persists across browser sessions
- ✅ Updates edges immediately on change
- ✅ No conflicts with existing edge features


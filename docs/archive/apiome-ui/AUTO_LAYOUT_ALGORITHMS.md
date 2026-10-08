# Auto Layout Algorithms Implementation

## Overview

This document describes the implementation of auto layout algorithms for the Apiome canvas editor. The implementation provides multiple layout algorithms to automatically arrange class nodes in different patterns.

## Architecture

The auto layout system consists of three main components:

### 1. `autoLayoutAlgorithms.ts`
Core algorithm implementations providing various layout strategies:

- **Hierarchical Layout** (4 variations: TB, LR, BT, RL)
  - Uses Dagre graph layout library
  - Organizes nodes in a hierarchy with dependencies flowing in one direction
  - Best for showing clear parent-child relationships
  - Configurable spacing and direction

- **Force-Directed Layout**
  - Physics-based simulation using spring and repulsion forces
  - Nodes with more connections are naturally pulled closer together
  - Creates organic, balanced layouts
  - Configurable spring strength, repulsion strength, and iteration count
  - Particularly good for showing clusters and relationships

- **Circular Layout**
  - Arranges all nodes in a circle
  - Orders nodes by connectivity to minimize edge crossings
  - Good for showing cyclic dependencies or equal-importance nodes
  - Configurable radius and start angle

- **Grid Layout**
  - Places nodes in a regular grid pattern
  - Optionally sorts alphabetically
  - Clean, organized appearance
  - Configurable columns and spacing

- **Layered Layout**
  - Organizes nodes into horizontal layers based on dependency depth
  - Uses BFS (Breadth-First Search) to assign layers
  - Root nodes (no incoming edges) are placed in layer 0
  - Good for visualizing dependency chains
  - Configurable layer height and node separation

### 2. `layoutUtils.ts`
Wrapper and utility functions providing backwards compatibility with existing code:

- Maintains the existing `getLayoutedElements()` API
- Maps old `LayoutDirection` to new `LayoutAlgorithm` types
- Re-exports new layout functions for convenience

### 3. `page.tsx` (Studio Page)
UI integration with enhanced controls:

- Algorithm dropdown selector with descriptions
- Quick direction buttons for hierarchical layouts
- Auto-layout toggle
- Loading states with progress messages
- Automatic view fitting after layout application

## Usage

### Basic Usage

```typescript
import { applyAutoLayout, type LayoutAlgorithm } from './autoLayoutAlgorithms';

// Apply force-directed layout
const layoutedNodes = applyAutoLayout(nodes, edges, {
  algorithm: 'force-directed',
  springStrength: 0.1,
  repulsionStrength: 3000,
  iterations: 100
});

// Apply circular layout
const layoutedNodes = applyAutoLayout(nodes, edges, {
  algorithm: 'circular',
  radius: 500
});

// Apply grid layout
const layoutedNodes = applyAutoLayout(nodes, edges, {
  algorithm: 'grid',
  columns: 4,
  sortAlphabetically: true
});
```

### Configuration Options

Each algorithm supports different configuration options:

#### Hierarchical Layouts
```typescript
{
  algorithm: 'hierarchical-tb' | 'hierarchical-lr' | 'hierarchical-bt' | 'hierarchical-rl',
  nodeWidth?: number,          // Default: 280
  nodeHeight?: number,         // Default: 180
  rankSeparation?: number,     // Default: 150
  nodeSeparation?: number,     // Default: 100
  edgeSeparation?: number      // Default: 30
}
```

#### Force-Directed Layout
```typescript
{
  algorithm: 'force-directed',
  springStrength?: number,     // Default: 0.1
  repulsionStrength?: number,  // Default: 3000
  iterations?: number          // Default: 100
}
```

#### Circular Layout
```typescript
{
  algorithm: 'circular',
  radius?: number,             // Default: max(400, nodes.length * 50)
  startAngle?: number          // Default: -π/2 (top)
}
```

#### Grid Layout
```typescript
{
  algorithm: 'grid',
  columns?: number,            // Default: ceil(sqrt(nodes.length))
  columnSpacing?: number,      // Default: 350
  rowSpacing?: number,         // Default: 250
  sortAlphabetically?: boolean // Default: true
}
```

#### Layered Layout
```typescript
{
  algorithm: 'layered',
  layerHeight?: number,        // Default: 250
  nodeSeparation?: number      // Default: 350
}
```

## UI Components

### Algorithm Selector

The layout control panel in the top-right corner provides:

1. **Auto Layout Toggle** - Enable/disable automatic layout
2. **Algorithm Dropdown** - Select from 8 layout algorithms
3. **Algorithm Description** - Context-sensitive help text
4. **Direction Buttons** - Quick access for hierarchical layouts (TB, LR, BT, RL)

### User Experience

- Layout changes are animated with smooth transitions
- Loading indicator shows during layout calculations
- View automatically fits after layout application
- Layout state persists between canvas operations
- Disabled state when auto-layout is off

## Algorithm Details

### Force-Directed Algorithm

The force-directed layout uses a physics simulation with two types of forces:

1. **Repulsion Forces** (Coulomb's Law)
   - All nodes repel each other
   - Force is inversely proportional to distance squared
   - Prevents nodes from overlapping

2. **Spring Forces** (Hooke's Law)
   - Connected nodes attract each other
   - Force is proportional to displacement from ideal length
   - Creates natural clustering

The simulation runs for a configurable number of iterations (default: 100), with velocity damping applied each frame to stabilize the layout.

### Circular Layout Optimization

The circular layout uses a connectivity-based ordering algorithm:

1. Start with the most connected node
2. Iteratively add nodes that are connected to already-placed nodes
3. Prefer nodes with more connections
4. This minimizes edge crossings and creates a more readable layout

### Layered Layout Algorithm

The layered layout uses breadth-first search (BFS) to assign depth levels:

1. Identify root nodes (nodes with no incoming edges)
2. Assign root nodes to layer 0
3. Use BFS to assign child nodes to subsequent layers
4. If multiple paths exist to a node, use the longest path
5. Handle disconnected components by treating orphan nodes as roots

## Performance Considerations

- **Force-Directed**: Most computationally intensive (O(n² * iterations))
  - Good for small to medium graphs (< 100 nodes)
  - Consider reducing iterations for larger graphs
  
- **Hierarchical**: Fast (O(n log n))
  - Scales well to large graphs
  - Best overall performance
  
- **Circular**: Very fast (O(n²) for connectivity ordering)
  - Linear time after ordering
  
- **Grid**: Fastest (O(n log n) for sorting)
  - Constant time for positioning
  
- **Layered**: Fast (O(n + e))
  - BFS traversal complexity

## Future Enhancements

Potential additions from the feature roadmap:

1. **Layout Presets**
   - Save custom layout configurations
   - Share layouts across projects
   - Version control for layouts

2. **Animation Controls**
   - Adjust transition speed
   - Pause/resume force-directed simulation
   - Step-by-step layout application

3. **Advanced Options**
   - Manual node pinning (fix positions)
   - Subgraph layouts (layout groups independently)
   - Custom clustering algorithms

4. **Layout Templates**
   - Pre-configured layouts for common patterns
   - Domain-specific layouts (e-commerce, auth, etc.)

## Testing

To test the layout algorithms:

1. Create a project with multiple classes and relationships
2. Toggle through different algorithms using the dropdown
3. Observe how nodes are arranged differently
4. For hierarchical layouts, try all four directions
5. For force-directed, watch the animation stabilize
6. For circular, check that highly-connected nodes are grouped

### Test Scenarios

- **Simple chain**: A → B → C → D (good for hierarchical)
- **Star pattern**: Central node with many connections (good for circular)
- **Grid pattern**: Independent nodes (good for grid)
- **Complex graph**: Multiple interconnected clusters (good for force-directed)
- **Deep hierarchy**: Multiple levels of dependencies (good for layered)

## Troubleshooting

### Layout doesn't apply
- Check that Auto Layout toggle is enabled
- Ensure nodes and edges data is loaded
- Check browser console for errors

### Layout looks incorrect
- Try a different algorithm for your graph structure
- Adjust configuration options (spacing, iterations, etc.)
- Check for circular dependencies

### Performance issues
- Reduce the number of iterations for force-directed
- Use hierarchical layout for large graphs
- Consider implementing incremental layout updates

## Code Examples

### Integrating in a Component

```typescript
import { applyAutoLayout } from './autoLayoutAlgorithms';
import { useCallback } from 'react';

function MyCanvas() {
  const applyLayout = useCallback((algorithm: LayoutAlgorithm) => {
    const layoutedNodes = applyAutoLayout(nodes, edges, { algorithm });
    setNodes(layoutedNodes);
    fitView({ padding: 0.2, duration: 400 });
  }, [nodes, edges]);

  return (
    <select onChange={(e) => applyLayout(e.target.value)}>
      <option value="hierarchical-tb">Hierarchical</option>
      <option value="force-directed">Force-Directed</option>
      <option value="circular">Circular</option>
      <option value="grid">Grid</option>
      <option value="layered">Layered</option>
    </select>
  );
}
```

## Dependencies

- `dagre` - Graph layout library for hierarchical layouts
- `@xyflow/react` - React Flow for canvas rendering
- Standard React hooks for state management

## References

- [Dagre Documentation](https://github.com/dagrejs/dagre)
- [Force-Directed Graph Drawing](https://en.wikipedia.org/wiki/Force-directed_graph_drawing)
- [React Flow Documentation](https://reactflow.dev/)


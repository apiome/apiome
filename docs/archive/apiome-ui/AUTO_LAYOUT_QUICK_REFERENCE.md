# Auto Layout Quick Reference

## Available Algorithms

| Algorithm | Icon | Best For | Complexity |
|-----------|------|----------|------------|
| **Hierarchical (Top-Down)** | 📊 ↓ | Clear parent-child relationships, dependency flows | O(n log n) |
| **Hierarchical (Left-Right)** | 📊 → | Wide graphs, horizontal space | O(n log n) |
| **Hierarchical (Bottom-Top)** | 📊 ↑ | Inverted hierarchies | O(n log n) |
| **Hierarchical (Right-Left)** | 📊 ← | RTL preference, horizontal space | O(n log n) |
| **Force-Directed** | 🔄 | Natural clustering, organic appearance | O(n² × iterations) |
| **Circular** | ⭕ | Cyclic dependencies, equal importance | O(n²) |
| **Grid** | ⊞ | Clean organization, alphabetical | O(n log n) |
| **Layered** | 📚 | Dependency depth visualization | O(n + e) |

## Quick Selection Guide

```
Need to show...
  ├─ Clear hierarchy? → Hierarchical
  ├─ Natural clusters? → Force-Directed
  ├─ Dependency depth? → Layered
  ├─ Cyclic patterns? → Circular
  └─ Clean grid? → Grid
```

## Keyboard Shortcuts (Future)

| Shortcut | Action |
|----------|--------|
| `Shift + L` | Toggle Auto Layout |
| `Shift + 1-8` | Quick algorithm switch |

## Common Configurations

### Best Performance
```typescript
algorithm: 'hierarchical-tb'  // Fastest
```

### Best Aesthetics
```typescript
algorithm: 'force-directed',
springStrength: 0.15,
repulsionStrength: 4000,
iterations: 150
```

### Best for Large Graphs (100+ nodes)
```typescript
algorithm: 'hierarchical-lr',
rankSeparation: 200,
nodeSeparation: 150
```

### Best for Small Graphs (< 20 nodes)
```typescript
algorithm: 'force-directed',
iterations: 200  // Can afford more iterations
```

## Tips & Tricks

1. **Start with Hierarchical** - It's fast and works for most cases
2. **Use Force-Directed for exploration** - See natural groupings
3. **Try Circular for equal nodes** - Good for state machines
4. **Use Grid for presentations** - Clean, professional look
5. **Use Layered for dependency analysis** - See depth at a glance

## Algorithm Behavior

### Hierarchical
- Roots at top/left, leaves at bottom/right
- Minimizes edge crossings
- Predictable, stable output

### Force-Directed
- Animated positioning
- Non-deterministic (varies each run)
- Connected nodes cluster together
- May need multiple runs to find good layout

### Circular
- Highly connected nodes grouped
- Predictable radius
- Good for small to medium graphs

### Grid
- Alphabetical by default
- Uniform spacing
- Ignores relationships

### Layered
- Depth-based layers
- Handles cycles gracefully
- Good for showing "levels"

## When to Disable Auto Layout

- **Manual positioning needed** - Specific arrangement required
- **Custom layouts** - Following domain conventions
- **Performance** - Very large graphs (500+ nodes)
- **Incremental updates** - Adding single nodes

## Integration Points

### On Load
```typescript
// Auto-layout applied when loading classes
useEffect(() => {
  if (autoLayoutEnabled) {
    const layouted = applyAutoLayout(nodes, edges, { algorithm: layoutAlgorithm });
    setNodes(layouted);
  }
}, [classData]);
```

### On Change
```typescript
// Layout applied when changing algorithm
const handleAlgorithmChange = (algo: LayoutAlgorithm) => {
  const layouted = applyAutoLayout(nodes, edges, { algorithm: algo });
  setNodes(layouted);
  setLayoutAlgorithm(algo);
};
```

### Manual Trigger
```typescript
// User can manually re-apply layout
const reapplyLayout = () => {
  const layouted = applyAutoLayout(nodes, edges, { algorithm: layoutAlgorithm });
  setNodes(layouted);
  fitView();
};
```

## Visual Indicators

- **Blue highlight** - Currently active algorithm/direction
- **Gray** - Available option
- **Dimmed/disabled** - Auto layout is off
- **Loading spinner** - Layout calculating (force-directed, large graphs)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Nodes overlap | Increase nodeSeparation/spacing |
| Layout too spread out | Decrease separation parameters |
| Force-directed won't stabilize | Increase iterations or damping |
| Circular too small | Increase radius parameter |
| Grid too many columns | Set explicit columns value |
| Layered uneven | Check for cycles in graph |

## Performance Benchmarks (Approximate)

| Nodes | Hierarchical | Force-Directed | Circular | Grid | Layered |
|-------|-------------|----------------|----------|------|---------|
| 10 | <10ms | ~50ms | <10ms | <5ms | <10ms |
| 50 | ~50ms | ~500ms | ~50ms | ~20ms | ~50ms |
| 100 | ~100ms | ~2s | ~100ms | ~50ms | ~100ms |
| 500 | ~500ms | >10s | ~500ms | ~100ms | ~500ms |

## API Reference

### Main Function
```typescript
applyAutoLayout(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions
): Node[]
```

### Helper Functions
```typescript
getLayoutAlgorithmName(algorithm: LayoutAlgorithm): string
getLayoutAlgorithmDescription(algorithm: LayoutAlgorithm): string
```

### Types
```typescript
type LayoutAlgorithm = 
  | 'hierarchical-tb' | 'hierarchical-lr' 
  | 'hierarchical-bt' | 'hierarchical-rl'
  | 'force-directed' | 'circular' 
  | 'grid' | 'layered'
```

## See Also

- [Full Documentation](./AUTO_LAYOUT_ALGORITHMS.md)
- [Feature Roadmap](../../FEATURE_ROADMAP.md)
- [Canvas Loading](./CANVAS_LOADING_PROGRESS_BAR.md)


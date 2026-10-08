# Auto Layout Visual Examples

This document shows examples of how different layout algorithms arrange the same set of nodes.

## Example Graph Structure

Consider a simple e-commerce domain model with the following classes and relationships:

```
User
├─ has many → Order
├─ has one → Cart
└─ has one → Profile

Order
├─ has many → OrderItem
└─ references → Payment

Product
├─ is referenced by → OrderItem
└─ is referenced by → CartItem

Cart
└─ has many → CartItem

Category
└─ has many → Product

Address
└─ is referenced by → User
```

## Layout Algorithm Visualizations

### 1. Hierarchical (Top-Down)

```
                    User
                     |
        +------------+------------+
        |            |            |
     Profile       Cart        Order
                     |            |
                  CartItem    +---+---+
                     |        |       |
                  Product  OrderItem Payment
                     |        |
                 Category  Product
```

**Characteristics:**
- Clear hierarchy from top to bottom
- Root node (User) at top
- Dependencies flow downward
- Good for showing ownership/containment

### 2. Hierarchical (Left-Right)

```
User ──┬── Profile
       ├── Cart ─── CartItem ─── Product ─── Category
       └── Order ──┬── OrderItem ─── Product
                   └── Payment
```

**Characteristics:**
- Hierarchy flows left to right
- Good for wide screens
- Natural reading order
- Better for long class names

### 3. Force-Directed Layout

```
        Category
            |
         Product ───────┐
         /    \         |
   CartItem  OrderItem  |
      |         |       |
    Cart      Order     |
      |         |       |
      └── User ─┴───────┘
          |
       Profile
       
      Payment (separate cluster)
      Address (separate cluster)
```

**Characteristics:**
- Natural clustering
- Connected nodes closer together
- Organic appearance
- Good for discovering relationships

### 4. Circular Layout

```
           User
          /    \
    Profile    Cart
       |        |
    Address  CartItem
       |        |
    Order ── Product
       |        |
   OrderItem  Category
       |        |
     Payment ─┘
```

**Characteristics:**
- All nodes equally spaced on circle
- Highly connected nodes grouped together
- Good for cyclic dependencies
- Compact arrangement

### 5. Grid Layout

```
Address      Cart         CartItem
Category     Order        OrderItem
Payment      Product      Profile
User
```

**Characteristics:**
- Alphabetically sorted
- Regular spacing
- Clean, professional
- Ignores relationships
- Good for listing/cataloging

### 6. Layered Layout

```
Layer 0:  User
Layer 1:  Profile    Cart       Order
Layer 2:  CartItem   OrderItem  Payment
Layer 3:  Product    
Layer 4:  Category
```

**Characteristics:**
- Organized by dependency depth
- Shows "levels" clearly
- Root nodes at top layer
- Good for understanding depth

## Real-World Use Cases

### Authentication System

**Best Layout:** Hierarchical (Top-Down)

```
            User
             |
    +--------+--------+
    |        |        |
  Session  Token    Role
                      |
                 Permission
```

### State Machine

**Best Layout:** Circular

```
      Pending
       /   \
   Active   Failed
      |   /
   Complete
```

### Microservices Architecture

**Best Layout:** Force-Directed

```
API Gateway ──┬── User Service
              ├── Order Service ─── Payment Service
              ├── Product Service ── Inventory Service
              └── Auth Service ──── Email Service
```

### Package Dependencies

**Best Layout:** Layered

```
Layer 0:  App
Layer 1:  UI Components    API Client
Layer 2:  Utils           HTTP Library
Layer 3:  Core Library
```

## Choosing the Right Algorithm

| Scenario | Recommended Algorithm | Why |
|----------|----------------------|-----|
| Simple parent-child | Hierarchical TB | Clear, predictable |
| Many sibling nodes | Hierarchical LR | Better use of space |
| Exploring relationships | Force-Directed | Natural clustering |
| State transitions | Circular | Cyclic flow |
| Documentation | Grid | Clean, organized |
| Dependency analysis | Layered | Shows depth |
| Complex interconnected | Force-Directed | Reveals patterns |
| Presenting to stakeholders | Hierarchical or Grid | Professional |

## Interactive Examples

When you apply these layouts in the studio:

1. **Start with your data**
   - Create classes
   - Add properties with $ref
   - Create composition relationships

2. **Try different layouts**
   - Select algorithm from dropdown
   - Watch transition animation
   - Compare results

3. **Refine the view**
   - Adjust zoom
   - Pan to focus area
   - Toggle mini-map

4. **Save your preference**
   - Layout persists during session
   - Applies to new nodes automatically
   - Can disable for manual positioning

## Algorithm Comparison Chart

```
Readability:
Hierarchical  ████████████ 12/10 (best for clarity)
Layered       ███████████  11/10 (depth visualization)
Grid          ██████████   10/10 (clean)
Circular      ████████     8/10  (compact)
Force         ███████      7/10  (organic but variable)

Performance:
Grid          ████████████ 12/10 (fastest)
Hierarchical  ███████████  11/10 (very fast)
Layered       ███████████  11/10 (BFS is fast)
Circular      ██████████   10/10 (fast)
Force         ████         4/10  (iterative, slow)

Relationship Display:
Force         ████████████ 12/10 (best for connections)
Hierarchical  ███████████  11/10 (clear dependencies)
Layered       ██████████   10/10 (depth-based)
Circular      ████████     8/10  (cyclic patterns)
Grid          ████         4/10  (ignores relationships)

Scalability:
Hierarchical  ████████████ 12/10 (handles large graphs)
Layered       ███████████  11/10 (scales well)
Grid          ███████████  11/10 (linear scaling)
Circular      ████████     8/10  (good to ~50 nodes)
Force         ████         4/10  (struggles >100 nodes)
```

## Tips for Best Results

### Hierarchical Layouts
- Works best with clear parent-child relationships
- If graph is too wide, use LR instead of TB
- Adjust rankSeparation for vertical spacing
- Adjust nodeSeparation for horizontal spacing

### Force-Directed Layout
- Increase iterations for more stable result
- Adjust springStrength to control connection tightness
- Increase repulsionStrength for more spacing
- Best with 10-100 nodes
- May need to run multiple times

### Circular Layout
- Radius auto-adjusts based on node count
- Works best with 5-50 nodes
- Good for showing all nodes at once
- Consider for equal-importance nodes

### Grid Layout
- Enable sortAlphabetically for easy finding
- Adjust columns based on screen width
- Good for documentation screenshots
- Use when relationships don't matter

### Layered Layout
- Shows dependency depth clearly
- Handles cycles by using longest path
- Good for understanding build order
- Orphan nodes placed in layer 0

## Animation and Transitions

All layout changes are smoothly animated:

1. **Loading State**
   - Progress spinner appears
   - Message shows current operation
   - Canvas is temporarily locked

2. **Layout Application**
   - Nodes smoothly transition to new positions
   - Edges redraw automatically
   - Duration: ~400ms

3. **View Fitting**
   - Canvas zooms/pans to show all nodes
   - Padding ensures nodes aren't at edges
   - Smooth animation

## Accessibility

- Keyboard navigation supported
- Screen reader friendly labels
- High contrast mode compatible
- Focus indicators on controls
- Tooltips for algorithm descriptions

## Browser Support

All modern browsers supported:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Requires JavaScript and WebGL for animations.

## See Also

- [Full Documentation](./AUTO_LAYOUT_ALGORITHMS.md)
- [Quick Reference](./AUTO_LAYOUT_QUICK_REFERENCE.md)
- [Feature Roadmap](../../FEATURE_ROADMAP.md)


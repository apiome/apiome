# Edge Animation Feature

## Overview

Added edge animation options to the canvas editor, allowing users to visualize data flow with animated edges.

## Animation Options

The following edge animation styles are available:

### 1. None (Static)
- **Type**: `none`
- **Description**: Static edges with no animation
- **Best For**: Clean, distraction-free diagrams
- **Default**: Yes

### 2. Flow
- **Type**: `flow`
- **Description**: Flowing dots animation showing data direction
- **Best For**: Visualizing data flow, API calls, message passing
- **Visual**: Small dots moving along the edge path

### 3. Pulse
- **Type**: `pulse`
- **Description**: Pulsing glow effect on edges
- **Best For**: Highlighting active connections, real-time data
- **Visual**: Edge opacity and width pulse in and out

### 4. Dash
- **Type**: `dash`
- **Description**: Animated marching dashes
- **Best For**: Showing continuous data streams, async operations
- **Visual**: Dashed line with moving segments

## User Interface

### Accessing Edge Animation

1. Click the **Settings** button (gear icon) in the Studio Header
2. Scroll to the **Edge Animation** section
3. Click one of the four animation buttons:
   - **None** - Static edges (default)
   - **Flow** - Flowing dots
   - **Pulse** - Pulsing glow
   - **Dash** - Marching dashes

### Visual Layout

The Edge Animation section displays a 2x2 grid of buttons:
```
[None]   [Flow]
[Pulse]  [Dash]
```

Each button includes:
- An icon representing the animation style
- The animation name
- Active state highlighting (indigo when selected)

A description below the buttons explains the currently selected animation style.

## Implementation Details

### Files Modified

1. **`/src/app/ade/studio/StudioContext.tsx`**
   - Added `EdgeAnimationType` type: `'none' | 'flow' | 'pulse' | 'dash'`
   - Added `edgeAnimation` state with localStorage persistence
   - Added `setEdgeAnimation` function to context
   - Default value: `'none'`

2. **`/src/app/ade/studio/components/StudioHeader.tsx`**
   - Added `edgeAnimation` and `setEdgeAnimation` to context imports
   - Added Edge Animation section with 2x2 button grid
   - Each button has custom SVG icon
   - Dynamic description text based on selected animation

3. **`/src/app/ade/studio/editor/page.tsx`**
   - Added `edgeAnimation` to context imports
   - Added `shouldAnimateEdges()` helper function
   - Added `getAnimationClassName()` helper function
   - Updated `createAllEdges()` to apply animation to edges
   - Added `edgeAnimation` to useEffect dependency
   - Added CSS keyframe animations:
     - `edge-flow`: Flowing dots effect
     - `edge-pulse`: Pulsing glow effect
     - `edge-dash`: Marching dashes effect

### CSS Animations

```css
/* Flow Animation - Moving dots along edge */
.edge-animation-flow .react-flow__edge-path {
  stroke-dasharray: 5;
  animation: edge-flow 1s linear infinite;
}

/* Pulse Animation - Glowing pulse effect */
.edge-animation-pulse .react-flow__edge-path {
  animation: edge-pulse 2s ease-in-out infinite;
}

/* Dash Animation - Marching dashes */
.edge-animation-dash .react-flow__edge-path {
  stroke-dasharray: 10 5;
  animation: edge-dash 0.5s linear infinite;
}
```

### State Persistence

- Edge animation preference is saved to browser localStorage as `edgeAnimation`
- Persists across browser sessions
- Changes apply immediately to all edges on the canvas

## Usage Examples

### API Flow Visualization
Use **Flow** animation to show:
- Request/response patterns
- Data flowing between services
- Message queue processing

### Real-time Data
Use **Pulse** animation for:
- WebSocket connections
- Live data streams
- Active/idle state indication

### Async Operations
Use **Dash** animation for:
- Background job processing
- Event-driven architectures
- Continuous integration pipelines

### Clean Presentation
Use **None** for:
- Documentation and screenshots
- Presentations
- Printed diagrams

## Compatibility

- ✅ Works with all edge routing types (straight, bezier, orthogonal, smart)
- ✅ Works with all edge styles (solid, dashed, dotted, double)
- ✅ Works with all edge colors
- ✅ Compatible with dark mode
- ✅ Persists across browser sessions
- ✅ Updates edges immediately on change

## Testing

- 16 tests for edge animation functionality
- Tests cover all animation types
- Tests verify class name generation
- Tests ensure animation type distinguishability

## Performance Notes

- Animations use CSS transforms for GPU acceleration
- Minimal impact on canvas performance
- Can be disabled (set to "None") for performance-critical scenarios


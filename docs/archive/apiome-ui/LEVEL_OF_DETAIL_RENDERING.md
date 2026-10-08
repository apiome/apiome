# Level of Detail (LOD) Rendering for ReactFlow Canvas

## Overview

The ReactFlow canvas now implements dynamic level-of-detail rendering that automatically adjusts the amount of information displayed based on the current zoom level. This improves performance and visual clarity when zoomed out to see the big picture.

## Implementation Details

### Zoom Tracking

The zoom level is tracked in the main Studio page component:

1. **State Management**: Added `zoomLevel` state variable initialized to 1 (100% zoom)
2. **Event Handling**: Added `onMove` handler to ReactFlow component that updates zoom level on viewport changes
3. **Data Propagation**: Zoom level is passed to all node components via their data prop

### Level of Detail Thresholds

The rendering adapts at different zoom levels:

#### At 50% or Less Zoom (Zoomed Out)
- **Class Name Only**: Only the class name and action buttons are visible
- All other details are hidden for maximum simplification
- Perfect for seeing the big picture with many nodes

#### At 50-75% Zoom
- **Class Name + Properties Fading In**: Properties start to become visible
- Description and tags still hidden
- Good for understanding class structure

#### At 75-100% Zoom  
- **Description and Tags Appearing**: Description and tags fade in
- Properties becoming more visible
- Smooth opacity transitions for all elements

#### At 100%+ Zoom (Zoomed In)
- **Full Detail**: All properties, descriptions, tags, and metadata are fully visible
- Maximum detail for focused work on specific classes

### Fade Transitions

All elements use CSS transitions for smooth opacity changes:

- **Properties**: `opacity: propertiesOpacity` - Fades out at 200% zoom
- **Description**: `opacity: descriptionOpacity` - Fades out starting at 150% zoom  
- **Tags**: `opacity: tagsOpacity` - Fades out with description
- **Transition**: All use `transition: 'opacity 0.3s ease-in-out'` for smooth changes

### Opacity Calculations

```typescript
const zoom = typedData.zoomLevel ?? 1;

// Properties fade out completely when zoomed out to 50% or less
const propertiesOpacity = Math.max(0, Math.min(1, (zoom - 0.5) / 0.5));

// Description fades out when zooming out to 75% or less
const descriptionOpacity = Math.max(0, Math.min(1, (zoom - 0.75) / 0.25));

// Tags fade at same rate as description
const tagsOpacity = descriptionOpacity;
```

### Conditional Rendering

Elements are conditionally rendered based on minimum opacity thresholds:

```typescript
const showProperties = propertiesOpacity > 0.05;
const showDescription = descriptionOpacity > 0.05;
const showTags = tagsOpacity > 0.05;
```

This prevents rendering invisible elements and improves performance.

## Benefits

1. **Better Performance**: Fewer DOM elements when zoomed out
2. **Improved Clarity**: Easier to see the overall structure at high zoom levels
3. **Smooth Experience**: Gradual fade transitions feel natural and polished
4. **Automatic Adaptation**: No manual controls needed - adapts to user's zoom level

## Modified Files

- `/src/app/ade/studio/page.tsx`: Added zoom tracking and data propagation
- `/src/app/components/ade/studio/ClassNode.tsx`: Implemented LOD rendering logic

## Future Enhancements

Potential improvements could include:

- Configurable zoom thresholds via user preferences
- Different LOD strategies for different node types
- Animation of node size changes at different zoom levels
- Performance optimizations for very large graphs (1000+ nodes)


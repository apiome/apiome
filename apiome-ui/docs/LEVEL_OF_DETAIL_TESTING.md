# Testing the Level of Detail Rendering

## Manual Testing Steps

1. **Navigate to the Studio**
   - Log in to the application
   - Navigate to the ADE Studio page
   - Load a project with multiple classes and properties

2. **Test Zoom Out (50% or less)**
   - Use the ReactFlow zoom controls or mouse wheel to zoom out
   - Zoom to 50% or less (you can see the zoom level in the ReactFlow controls)
   - **Expected**: Only class names and action buttons should be visible
   - **Expected**: Properties, descriptions, and tags should be completely hidden

3. **Test Mid-Range Zoom Out (50-75%)**
   - Zoom to approximately 50-75%
   - **Expected**: Properties should start to fade in as you zoom closer to 75%
   - **Expected**: Descriptions and tags should still be hidden
   - **Expected**: Smooth transitions as you zoom

4. **Test Near Normal Zoom (75-100%)**
   - Zoom to approximately 75-90%
   - **Expected**: Descriptions should start to fade in
   - **Expected**: Tags should start appearing with reduced opacity
   - **Expected**: Properties should be more visible

5. **Test Zoom In (100%+)**
   - Zoom in closer (100% or more)
   - **Expected**: All details fully visible at 100% opacity
   - **Expected**: Properties, descriptions, tags, and all metadata clearly visible
   - **Expected**: Zooming in further maintains full detail

6. **Test Smooth Transitions**
   - Slowly zoom in and out through the various levels
   - **Expected**: Smooth fade transitions between visibility levels
   - **Expected**: No sudden jumps or flickering
   - **Expected**: Transitions take approximately 0.3 seconds

## Verification Points

- [ ] Zoom level is tracked correctly
- [ ] Properties fade out when zooming out to 50% or less
- [ ] Description fades out when zooming out to 75% or less
- [ ] Tags fade with description
- [ ] All transitions are smooth (0.3s ease-in-out)
- [ ] No performance issues when zooming
- [ ] No console errors
- [ ] Class names remain visible at all zoom levels
- [ ] Action buttons remain functional at all zoom levels
- [ ] Full detail is visible at 100% zoom and above

## Performance Check

- Test with a large canvas (20+ nodes)
- Verify smooth zoom performance
- Check that invisible elements are not being rendered (use React DevTools)
- Verify no memory leaks during repeated zoom operations

## Edge Cases

- [ ] Very low zoom (25%) - should show only class names
- [ ] Very high zoom (200%+) - should show all details
- [ ] Rapid zoom changes - should handle smoothly
- [ ] Multiple rapid zoom in/out cycles - no flickering or stuck states


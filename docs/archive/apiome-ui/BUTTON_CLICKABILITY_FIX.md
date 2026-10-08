# Mermaid Button Clickability Fix

## Problem
The SVG and PNG export buttons appeared grayed out (disabled) even when the Mermaid diagram was successfully rendered and ready for export.

## Root Cause

### Original Implementation (Problematic)
```typescript
// In studio page
<button 
  disabled={!mermaidPreviewRef.current?.hasSvg()}
  onClick={() => mermaidPreviewRef.current?.exportSVG()}
>
  SVG
</button>
```

**Issue**: 
- `hasSvg()` is called during render to check if SVG is available
- The SVG state lives inside the MermaidPreview component
- When SVG state changes, it doesn't trigger a re-render in the parent
- React doesn't know the button should be re-enabled

### Why It Failed
1. MermaidPreview renders and starts loading the diagram
2. Parent component renders buttons as disabled (`hasSvg()` returns false)
3. MermaidPreview successfully renders SVG
4. Parent component **never re-renders** (no state change in parent)
5. Buttons stay disabled forever, even though SVG is ready

## Solution

### Callback Pattern (Working)
```typescript
// MermaidPreview.tsx - Child component
interface MermaidPreviewProps {
  code: string;
  onSvgReady?: (hasSvg: boolean) => void;  // ← New callback
}

useEffect(() => {
  const renderDiagram = async () => {
    try {
      const { svg } = await mermaid.render(id, code);
      setSvg(svg);
      onSvgReady?.(true);  // ← Notify parent: SVG is ready!
    } catch (err) {
      setSvg('');
      onSvgReady?.(false);  // ← Notify parent: Error, no SVG
    }
  };
  renderDiagram();
}, [code, onSvgReady]);
```

```typescript
// page.tsx - Parent component
const [mermaidSvgReady, setMermaidSvgReady] = useState(false);  // ← State in parent

<MermaidPreview
  code={mermaidCode}
  onSvgReady={setMermaidSvgReady}  // ← Pass state setter as callback
/>

<button 
  disabled={!mermaidSvgReady}  // ← Use parent state
  onClick={() => mermaidPreviewRef.current?.exportSVG()}
>
  SVG
</button>
```

### How It Works Now
1. MermaidPreview renders and starts loading the diagram
2. Parent component renders buttons as disabled (`mermaidSvgReady = false`)
3. MermaidPreview successfully renders SVG
4. MermaidPreview calls `onSvgReady(true)`
5. Parent's `setMermaidSvgReady(true)` is called
6. **Parent re-renders** with new state
7. Buttons become enabled 🎉

## Key Concepts

### React State and Re-rendering
- Components only re-render when:
  - Their own state changes
  - Their props change
  - Their parent re-renders
- Calling a method on a ref does NOT trigger re-renders

### Lifting State Up
- The parent needs to know about the SVG state
- Instead of asking the child "do you have SVG?", we:
  - Let the child tell the parent "I now have SVG!"
  - Store that information in parent state
  - Use that state to control the UI

### Callback Props Pattern
```typescript
// Common React pattern for child-to-parent communication

// Child tells parent: "Something happened!"
onSomethingHappened?.(data);

// Parent listens: "When that happens, update my state"
<Child onSomethingHappened={setMyState} />
```

## Files Changed

### MermaidPreview.tsx
- Added `onSvgReady?: (hasSvg: boolean) => void` to props
- Call `onSvgReady(true)` on successful render
- Call `onSvgReady(false)` on error
- Added to useEffect dependency array

### page.tsx
- Added `const [mermaidSvgReady, setMermaidSvgReady] = useState(false)`
- Changed button disabled from `!ref.hasSvg()` to `!mermaidSvgReady`
- Added `onSvgReady={setMermaidSvgReady}` prop to MermaidPreview

## Visual Flow

```
┌─────────────────────────────────────────────────┐
│ Parent Component (Studio Page)                 │
│                                                 │
│  State: mermaidSvgReady = false                │
│                                                 │
│  ┌──────────────────────────────────┐          │
│  │ [SVG] button (disabled)          │          │
│  │ disabled={!mermaidSvgReady}     │          │
│  └──────────────────────────────────┘          │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │ MermaidPreview Component               │   │
│  │                                         │   │
│  │ 1. Renders diagram                      │   │
│  │ 2. onSvgReady(true) ─────────────┐     │   │
│  └─────────────────────────────────────────┘   │
│                                    │            │
│  setMermaidSvgReady(true) ◄────────┘            │
│  mermaidSvgReady = true                        │
│  ↓ State changed, re-render!                   │
│                                                 │
│  ┌──────────────────────────────────┐          │
│  │ [SVG] button (enabled) ✓         │          │
│  │ disabled={!mermaidSvgReady}     │          │
│  └──────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
```

## Benefits

1. ✅ **Reactive UI**: Buttons automatically enable when SVG is ready
2. ✅ **Proper State Management**: Parent owns and controls UI state
3. ✅ **Better UX**: Users see disabled buttons until export is possible
4. ✅ **Error Handling**: Buttons stay disabled if rendering fails
5. ✅ **React Best Practices**: Using state instead of refs for UI logic

## Testing

To verify the fix works:

1. Open Studio page and select a project/version
2. Switch to Mermaid tab
3. Observe that SVG/PNG buttons start disabled (gray)
4. Wait for diagram to render
5. Buttons should become enabled (purple/green)
6. Click should trigger export successfully

---

**Date**: November 29, 2025  
**Issue**: SVG/PNG buttons not clickable  
**Status**: ✅ Fixed


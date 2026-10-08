# Auto Layout UI Guide

## Layout Control Panel Location

The Layout Control Panel is located in the **top-right corner** of the canvas.

```
┌─────────────────────────────────────────────────────────┐
│  [Project] [Version] [View Mode Tabs]          [Panel] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Canvas Area                                            │
│  (Class Nodes)                                   ┌──────┤
│                                                  │      │
│                                               ┌──┴──┐   │
│                                               │Auto │   │
│                                               │Layo│   │
│                                               │ut  │   │
│                                               │Panel│   │
│                                               └────┘   │
│                                                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Panel Structure

### Before (Original)
```
┌──────────────────────────┐
│ Auto Layout    [Toggle]  │
├──────────────────────────┤
│ [↓] [→] [↑] [←]         │
└──────────────────────────┘
```

### After (Enhanced)
```
┌───────────────────────────────────┐
│ Auto Layout          [Toggle]     │
├───────────────────────────────────┤
│ Algorithm                         │
│ ┌──────────────────────────────┐  │
│ │ 📊 Hierarchical (Top-Down) ▼│  │
│ └──────────────────────────────┘  │
│ Organizes nodes in a hierarchy    │
│ with dependencies flowing in      │
│ one direction                     │
├───────────────────────────────────┤
│ Direction                         │
│ ┌────┬────┬────┬────┐            │
│ │ ↓  │ →  │ ↑  │ ←  │            │
│ └────┴────┴────┴────┘            │
└───────────────────────────────────┘
```

## Algorithm Dropdown

When clicked, the dropdown expands to show all available algorithms:

```
┌──────────────────────────────────┐
│ 📊 Hierarchical (Top-Down)    ✓ │ ← Currently selected
├──────────────────────────────────┤
│ 📊 Hierarchical (Left-Right)    │
│ 📊 Hierarchical (Bottom-Top)    │
│ 📊 Hierarchical (Right-Left)    │
│ 🔄 Force-Directed               │
│ ⭕ Circular                      │
│ ⊞ Grid                          │
│ 📚 Layered                       │
└──────────────────────────────────┘
```

## Panel States

### 1. Auto Layout Enabled (Default)

```
┌───────────────────────────────────┐
│ Auto Layout          [●───]       │  ← Toggle ON (blue)
├───────────────────────────────────┤
│ Algorithm                         │
│ ┌──────────────────────────────┐  │
│ │ 🔄 Force-Directed         ▼│  │  ← Active selection
│ └──────────────────────────────┘  │
│ Physics-based simulation where    │  ← Description
│ connected nodes attract and       │
│ unconnected nodes repel           │
└───────────────────────────────────┘
```

### 2. Auto Layout Disabled

```
┌───────────────────────────────────┐
│ Auto Layout          [───○]       │  ← Toggle OFF (gray)
├───────────────────────────────────┤
│ Algorithm                         │
│ ┌──────────────────────────────┐  │
│ │ 📊 Hierarchical (Top-Down) ▼│  │  ← Dropdown disabled
│ └──────────────────────────────┘  │  (grayed out)
└───────────────────────────────────┘
```

### 3. Any Algorithm Selected

```
┌───────────────────────────────────┐
│ Auto Layout          [●───]       │
├───────────────────────────────────┤
│ Algorithm                         │
│ ┌──────────────────────────────┐  │
│ │ 📊 Hierarchical (Top-Down) ▼│  │
│ └──────────────────────────────┘  │
│ Organizes nodes in hierarchy...   │
└───────────────────────────────────┘
```

**Note:** Direction for hierarchical layouts is selected directly in the algorithm dropdown (e.g., "Hierarchical (Top-Down)", "Hierarchical (Left-Right)", etc.).

## Loading States

### During Layout Application

```
┌───────────────────────────────────┐
│ ╔═══════════════════════════════╗ │
│ ║   ⟳  Applying Force-Directed  ║ │
│ ║      layout...                ║ │
│ ╚═══════════════════════════════╝ │
└───────────────────────────────────┘
```

The loading overlay appears temporarily (1-3 seconds) while layout is being calculated.

## Interaction Flow

### Changing Algorithm

1. User clicks dropdown
2. Dropdown expands showing all algorithms
3. User clicks an algorithm
4. Loading indicator appears
5. Layout is applied with animation (~400ms)
6. Canvas auto-fits to show all nodes
7. Loading indicator disappears


### Toggling Auto Layout

1. User clicks toggle switch
2. Switch animates to new position
3. If turning OFF:
   - Dropdown/buttons become disabled (grayed)
   - Manual positioning is enabled
   - Current positions are preserved
4. If turning ON:
   - Dropdown/buttons become enabled
   - Layout is immediately applied
   - Canvas auto-fits

## Visual Indicators

### Colors

- **Blue (#2563eb)**: Active selection, enabled state
- **Gray (#6B7280)**: Inactive, available options
- **Light Gray (#D1D5DB)**: Disabled state
- **Red (#DC2626)**: Errors (if any)
- **White/Dark**: Background (theme-dependent)

### Icons

- **📊**: Hierarchical layouts
- **🔄**: Force-Directed layout
- **⭕**: Circular layout
- **⊞**: Grid layout
- **📚**: Layered layout

### Hover Effects

- Dropdown: Border changes from gray to blue
- Buttons: Background lightens
- Toggle: Slight scale increase
- All transitions: 200ms smooth

## Responsive Design

The panel maintains its position and size across different screen sizes:

- **Desktop (>1920px)**: Full panel, all text visible
- **Laptop (1366-1920px)**: Full panel, compact descriptions
- **Tablet (768-1366px)**: Panel shrinks slightly, shorter descriptions
- **Mobile (<768px)**: Panel becomes bottom sheet or drawer

## Keyboard Navigation

Future enhancement:

- `Tab`: Navigate between controls
- `Space/Enter`: Activate dropdown/buttons
- `Arrow Keys`: Navigate dropdown options
- `Esc`: Close dropdown
- `Shift + L`: Toggle auto layout
- `Shift + 1-8`: Quick algorithm switch

## Accessibility

### Screen Readers

Each control has proper ARIA labels:

```html
<select aria-label="Layout algorithm selector">
  <option>Hierarchical (Top-Down)</option>
  ...
</select>

<button aria-label="Apply top to bottom layout">↓</button>
```

### Focus Indicators

Visible focus ring appears when navigating with keyboard:

```
┌──────────────────────────────────┐
│ 📊 Hierarchical (Top-Down)    ▼│
└──────────────────────────────────┘
     ↑ Blue focus ring (2px)
```

### High Contrast Mode

All elements maintain sufficient contrast ratio (4.5:1 minimum):

- Text on background
- Button borders
- Active states
- Disabled states

## Dark Mode

The panel automatically adapts to dark theme:

### Light Mode
```
┌───────────────────────────────────┐
│ Auto Layout          [●───]       │
│ Background: White (#FFFFFF)       │
│ Text: Dark Gray (#1F2937)         │
│ Border: Light Gray (#E5E7EB)      │
└───────────────────────────────────┘
```

### Dark Mode
```
┌───────────────────────────────────┐
│ Auto Layout          [●───]       │
│ Background: Dark Gray (#1F2937)   │
│ Text: Light Gray (#F9FAFB)        │
│ Border: Gray (#374151)            │
└───────────────────────────────────┘
```

## Mobile Considerations

On mobile devices, the panel becomes a bottom sheet:

```
┌─────────────────────────┐
│                         │
│    Canvas Area          │
│                         │
│                         │
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ Layout Controls     │ │
│ │ Auto Layout [●───]  │ │
│ │ Algorithm: [▼]      │ │
│ │ [↓] [→] [↑] [←]    │ │
│ └─────────────────────┘ │
└─────────────────────────┘
```

Swipe up to expand, swipe down to minimize.

## Animation Examples

### Dropdown Expansion
```
Frame 1: ┌─────┐
         │ [▼] │
         └─────┘

Frame 2: ┌─────┐
         │ [▼] │
         ├─────┤
         │  1  │
         └─────┘

Frame 3: ┌─────┐
         │ [▼] │
         ├─────┤
         │  1  │
         │  2  │
         │  3  │
         └─────┘
```
Duration: 200ms, ease-out

### Layout Transition
```
Before:  A──B──C     After:    A
                               │
                               B
                               │
                               C
```
Duration: 400ms, smooth ease-in-out

### Toggle Switch
```
OFF: [───○]
     ↓ (100ms)
ON:  [●───]
```
With haptic feedback (on supported devices)

## Error States

If layout fails (rare):

```
┌───────────────────────────────────┐
│ ⚠️  Layout Failed                  │
│                                   │
│ Unable to apply layout algorithm. │
│ [Retry]  [Use Previous Layout]    │
└───────────────────────────────────┘
```

## Tips & Hints

Tooltips appear on hover:

```
     Hover here
         ↓
    ┌─────────────────────────┐
    │ [↓]                     │
    └─────────────────────────┘
         ↓
    ┌─────────────────────────┐
    │ Top to Bottom           │
    │ Best for clear          │
    │ hierarchies             │
    └─────────────────────────┘
```

## Summary

The new auto layout UI provides:

✅ **8 layout algorithms** accessible via dropdown
✅ **Quick direction controls** for hierarchical layouts  
✅ **Auto layout toggle** to enable/disable
✅ **Context-sensitive descriptions** for each algorithm
✅ **Smooth animations** and loading states
✅ **Responsive design** for all screen sizes
✅ **Accessibility** with keyboard and screen reader support
✅ **Dark mode** compatible
✅ **Professional appearance** matching existing UI

---

**Ready to use!** Navigate to Studio → Canvas and look for the panel in the top-right corner.


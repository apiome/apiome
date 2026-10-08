# Custom Dialog Visual Examples

## Dialog Variants

### Confirm Dialog Variants

#### 1. Danger Variant (Delete/Remove Actions)
```
┌─────────────────────────────────────────┐
│  🔴 Delete Project                      │
├─────────────────────────────────────────┤
│                                         │
│  Are you sure you want to delete this   │
│  project? This action cannot be undone. │
│                                         │
│          [Cancel]  [Delete]🔴          │
└─────────────────────────────────────────┘
```
- Red X icon
- Red delete button
- Used for destructive actions

#### 2. Warning Variant (Caution Required)
```
┌─────────────────────────────────────────┐
│  ⚠️ Publish Version                     │
├─────────────────────────────────────────┤
│                                         │
│  Are you sure you want to publish this  │
│  version? Once published, it cannot be  │
│  edited (but can be unpublished).       │
│                                         │
│          [Cancel]  [Publish]🟡         │
└─────────────────────────────────────────┘
```
- Warning triangle icon
- Orange/yellow button
- Used for actions requiring caution

### Alert Dialog Variants

#### 1. Error Variant
```
┌─────────────────────────────────────────┐
│  ❌ Error                               │
├─────────────────────────────────────────┤
│                                         │
│  Failed to delete project              │
│                                         │
│                      [OK]🔵            │
└─────────────────────────────────────────┘
```
- Red X circle icon
- Used for error messages

#### 2. Warning Variant
```
┌─────────────────────────────────────────┐
│  ⚠️ Warning                             │
├─────────────────────────────────────────┤
│                                         │
│  Please select a version from the       │
│  canvas first                           │
│                                         │
│                      [OK]🔵            │
└─────────────────────────────────────────┘
```
- Warning triangle icon
- Used for validation warnings

#### 3. Success Variant
```
┌─────────────────────────────────────────┐
│  ✅ Success                             │
├─────────────────────────────────────────┤
│                                         │
│  OpenAPI specification copied to        │
│  clipboard!                             │
│                                         │
│                      [OK]🔵            │
└─────────────────────────────────────────┘
```
- Green checkmark icon
- Used for success messages

#### 4. Info Variant
```
┌─────────────────────────────────────────┐
│  ℹ️ Information                         │
├─────────────────────────────────────────┤
│                                         │
│  This is an informational message      │
│                                         │
│                      [OK]🔵            │
└─────────────────────────────────────────┘
```
- Blue info icon
- Used for informational messages

## Comparison: Before vs After

### Before (Browser Native)
```
┌─────────────────────────────────────────┐
│ This page says:                         │
│                                         │
│ Are you sure you want to delete this    │
│ project? This action cannot be undone.  │
│                                         │
│              [OK] [Cancel]              │
└─────────────────────────────────────────┘
```
**Issues:**
- ❌ Generic browser styling
- ❌ No icon or visual indicator
- ❌ Doesn't match app theme
- ❌ "This page says:" text
- ❌ Plain gray buttons
- ❌ No color coding by severity

### After (Custom Dialog)
```
┌─────────────────────────────────────────┐
│  🔴 Delete Project                      │
├─────────────────────────────────────────┤
│                                         │
│  Are you sure you want to delete this   │
│  project? This action cannot be undone. │
│                                         │
│          [Cancel]  [Delete]🔴          │
└─────────────────────────────────────────┘
```
**Benefits:**
- ✅ Matches app theme (light/dark mode)
- ✅ Clear icon indicating danger
- ✅ Color-coded by severity
- ✅ Professional appearance
- ✅ Material-UI design patterns
- ✅ Custom title
- ✅ Proper button styling
- ✅ Shadows and elevation

## Theme Support

### Light Mode
```
┌─────────────────────────────────────────┐
│  ⚠️ Publish Version    [Light Theme]   │
├─────────────────────────────────────────┤
│  Background: White                      │
│  Text: Dark Gray/Black                  │
│  Border: Light Gray                     │
│  Shadow: Subtle gray shadow             │
│                                         │
│          [Cancel]  [Publish]🟡         │
└─────────────────────────────────────────┘
```

### Dark Mode
```
┌─────────────────────────────────────────┐
│  ⚠️ Publish Version    [Dark Theme]    │
├─────────────────────────────────────────┤
│  Background: Dark Gray                  │
│  Text: Light Gray/White                 │
│  Border: Medium Gray                    │
│  Shadow: Black shadow                   │
│                                         │
│          [Cancel]  [Publish]🟡         │
└─────────────────────────────────────────┘
```

## Responsive Design

### Desktop (1920x1080)
- Dialog width: 600px max
- Centered on screen
- Large padding
- Full-size buttons

### Tablet (768x1024)
- Dialog width: 500px max
- Adjusted padding
- Slightly smaller buttons

### Mobile (375x667)
- Dialog width: ~90% of screen
- Compact padding
- Full-width buttons
- Stacked layout

## Icon Legend

| Icon | Variant | Use Case |
|------|---------|----------|
| 🔴 ❌ | Danger/Error | Delete, Remove, Critical errors |
| ⚠️ 🟡 | Warning | Caution required, Validation |
| ℹ️ 🔵 | Info | Informational messages |
| ✅ 🟢 | Success | Successful operations |

## Animation Behavior

1. **Enter**: Fade in with slight zoom effect (0.95 → 1.0 scale)
2. **Exit**: Fade out with slight zoom effect (1.0 → 0.95 scale)
3. **Duration**: 200-300ms
4. **Backdrop**: Fade in/out with dialog

## Keyboard Interaction

```
┌─────────────────────────────────────────┐
│  ⚠️ Delete Item                         │
├─────────────────────────────────────────┤
│                                         │
│  Are you sure?                          │
│                                         │
│          [Cancel]  [Delete]←(focused)  │
└─────────────────────────────────────────┘

Press ESC     → Close dialog (cancel)
Press TAB     → Move focus between buttons
Press ENTER   → Activate focused button
Press SPACE   → Activate focused button
```

## Accessibility Features

- ✅ Proper ARIA labels
- ✅ Focus trap (focus stays in dialog)
- ✅ Screen reader announcements
- ✅ High contrast support
- ✅ Keyboard navigation
- ✅ Focus indicators
- ✅ Semantic HTML structure


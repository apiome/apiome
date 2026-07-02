# BETA Background - Complete Guide

## 🎯 What Was Done

I've implemented a repeating "BETA" watermark background for the login screen that's controlled by the `NEXT_PUBLIC_BETA_MODE` environment variable.

## 📋 Implementation Summary

### Files Created/Modified:

1. **`.env`** - Added `NEXT_PUBLIC_BETA_MODE=true`
2. **`.env.example`** - Added `NEXT_PUBLIC_BETA_MODE=true` (template)
3. **`src/app/login/BetaBackground.tsx`** - New component for the BETA watermark
4. **`src/app/login/LoginClient.tsx`** - Modified to conditionally show BetaBackground
5. **`public/beta-test.html`** - Test page to visualize the effect
6. **Documentation files** - Implementation and troubleshooting guides

### Visual Design:
- Large "BETA" text (120px) repeated in a grid pattern
- Rotated -45 degrees (diagonal)
- Light gray color with 25% opacity
- Fixed background that doesn't interfere with interactions
- Login card appears above with proper z-indexing

## 🚀 How to See the BETA Background

### Step 1: Restart Your Dev Server (CRITICAL!)

Environment variables are only loaded when the server starts, so you MUST restart:

```bash
# Stop the current server (Ctrl+C in the terminal)

# Then restart:
cd /Users/kenji/Development/apiome/apiome-ui
npm run dev
# or
yarn dev
```

### Step 2: View the Test Page

Once the server is running, open your browser to:
```
http://localhost:3000/beta-test.html
```

This standalone HTML page shows exactly what the BETA background looks like.

### Step 3: View the Login Page

Navigate to your login page. You should now see the same BETA watermark.

### Step 4: Check Browser Console

Open Developer Tools (F12 or Cmd+Option+I) and check the Console. You should see:
```
Beta Mode Environment Variable: true
Is Beta Mode Active: true
BetaBackground component rendered
```

If you see these messages, the component is rendering correctly.

## 🔧 Configuration

### Enable Beta Mode:
```bash
# In .env file:
NEXT_PUBLIC_BETA_MODE=true
```

### Disable Beta Mode:
```bash
# Option 1: Comment out the line
# NEXT_PUBLIC_BETA_MODE=true

# Option 2: Remove the line entirely

# Option 3: Set to empty string
NEXT_PUBLIC_BETA_MODE=
```

**Important:** After ANY change to `.env`, you MUST restart the dev server!

## 🎨 Customizing the Appearance

Edit `/src/app/login/BetaBackground.tsx` to adjust:

### Make More/Less Visible:
```typescript
opacity: 0.25,  // Increase for more visible (0.5), decrease for subtler (0.1)
```

### Change Color:
```typescript
color: '#D1D5DB',  // Light gray
// Try: '#EF4444' for red, '#3B82F6' for blue, etc.
```

### Adjust Size:
```typescript
fontSize: '120px',  // Increase for larger text
```

### Change Angle:
```typescript
transform: 'translate(-50%, -50%) rotate(-45deg)',  // Try -30deg or -60deg
```

### Adjust Spacing:
```typescript
gap: '40px',      // Row spacing
gap: '150px',     // Column spacing (in the nested style)
```

## 🐛 Troubleshooting

### "I don't see the BETA background"

1. **Did you restart the dev server?** This is the #1 reason it won't show up!
2. **Check the test page first** - `http://localhost:3000/beta-test.html`
3. **Check browser console** - Look for the console.log messages
4. **Check .env file** - Verify `NEXT_PUBLIC_BETA_MODE=true` is present
5. **Clear cache** - Try `rm -rf .next` then restart server

### "The background is too subtle"

Temporarily increase the opacity in `BetaBackground.tsx`:
```typescript
opacity: 0.5,  // Much more visible for testing
```

### "The background interferes with clicking"

The component has `pointer-events-none` which should prevent this. Verify it's still in the component:
```typescript
<div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
```

## 📝 Technical Details

- Uses React functional component with TypeScript
- Positioned with CSS `fixed` and `z-index: 0`
- Login card has `z-index: 10` to appear above
- Text generated using `Array.from()` to create grid
- Completely client-side (no server rendering needed)
- Uses inline styles for complex transforms
- Environment variable check happens on every render (efficient)

## ✅ Testing Checklist

- [ ] Dev server restarted after .env change
- [ ] Test page shows BETA watermark: `http://localhost:3000/beta-test.html`
- [ ] Login page shows BETA watermark
- [ ] Console shows debug messages
- [ ] Login form is still fully functional
- [ ] BETA text is visible but not distracting
- [ ] Background doesn't interfere with clicking
- [ ] Setting `NEXT_PUBLIC_BETA_MODE=` (empty) hides the background

## 🎓 Learning Points

1. **Environment Variables in Next.js**: Must prefix with `NEXT_PUBLIC_` for client-side access
2. **Server Restart**: Required when changing environment variables
3. **Z-Index Layering**: Background at z-0, content at z-10
4. **Pointer Events**: Use `pointer-events-none` to make backgrounds non-interactive
5. **CSS Transforms**: Combine translate and rotate for diagonal watermarks

## 📚 See Also

- `BETA_MODE_IMPLEMENTATION.md` - Original implementation details
- `BETA_BACKGROUND_TROUBLESHOOTING.md` - Detailed troubleshooting steps
- `beta-test.html` - Visual reference page

---

**Need Help?** Check the browser console for debug messages and verify the dev server was restarted after modifying `.env`.


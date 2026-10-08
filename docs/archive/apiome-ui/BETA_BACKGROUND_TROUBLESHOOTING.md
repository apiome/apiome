# Troubleshooting: BETA Background Not Showing

## Quick Visual Test

To see what the BETA background should look like, I've created a standalone HTML test page:

**Access it at:** `http://localhost:3000/beta-test.html`

This page shows exactly what the BETA background should look like without any dependencies. If you can see the BETA watermark on this test page, then the styling is correct.

## Quick Fix Steps

### 1. Restart the Development Server

The most important step is to **restart your Next.js development server** to pick up the new environment variable. Environment variables are only loaded when the server starts.

**Stop the current server:**
- Press `Ctrl+C` in the terminal where the dev server is running

**Start the server again:**
```bash
cd /Users/kenji/Development/apiome/apiome-ui
npm run dev
# or
yarn dev
```

### 2. Verify Environment Variable

Open your browser's Developer Console (F12 or Cmd+Option+I on Mac) and navigate to the login page. You should see two console log messages:

```
Beta Mode Environment Variable: true
Is Beta Mode Active: true
BetaBackground component rendered
```

If you see these messages, the component is rendering correctly.

### 3. Check What You Should See

The BETA background consists of:
- Large "BETA" text repeated in a grid pattern
- Rotated at -45 degrees (diagonal)
- Light gray color (#E5E7EB) with 15% opacity
- Should cover the entire background behind the login form

### 4. If Still Not Visible

**Increase the opacity temporarily to verify it's rendering:**

Edit `/src/app/login/BetaBackground.tsx` and change:
```typescript
opacity: 0.15,  // Change this to 0.5 or 0.8 temporarily
```

This will make the BETA text much more visible so you can confirm it's working.

### 5. Clear Next.js Cache (if needed)

Sometimes Next.js caches old builds:

```bash
cd /Users/kenji/Development/apiome/apiome-ui
rm -rf .next
npm run dev
```

### 6. Verify .env File

Make sure your `.env` file contains:
```
NEXT_PUBLIC_BETA_MODE=true
```

Note: The variable **must** start with `NEXT_PUBLIC_` to be accessible in client-side components.

## Changes Made

### Files Modified:
1. **`.env`** - Added `NEXT_PUBLIC_BETA_MODE=true`
2. **`.env.example`** - Added `NEXT_PUBLIC_BETA_MODE=true` 
3. **`src/app/login/BetaBackground.tsx`** - Created new component
4. **`src/app/login/LoginClient.tsx`** - Added BetaBackground import and conditional rendering

### Debugging Added:
- Console logs to verify environment variable is read
- Console log to verify BetaBackground component renders

## Testing Different Scenarios

### Enable Beta Mode:
```bash
# In .env
NEXT_PUBLIC_BETA_MODE=true
```

### Disable Beta Mode:
```bash
# Remove the line, comment it out, or set to empty:
# NEXT_PUBLIC_BETA_MODE=true
```
OR
```bash
NEXT_PUBLIC_BETA_MODE=
```

**Remember:** After any change to `.env`, you MUST restart the dev server!

## Quick Visual Test

If you want to make the BETA background very obvious for testing, temporarily edit `BetaBackground.tsx`:

```typescript
style={{
  // ... other styles ...
  color: '#EF4444',  // Red color
  opacity: 0.5,       // Much more visible
  fontSize: '150px',  // Larger text
}}
```

Once you confirm it's working, revert to the original subtle styling.


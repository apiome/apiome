# Beta Mode Background Implementation

## Overview
This implementation adds a repeating "BETA" text background to the login screen when the application is running in beta mode. The feature is controlled by an environment variable.

## Changes Made

### 1. Environment Variables
Added `NEXT_PUBLIC_BETA_MODE` to both `.env` and `.env.example`:
```
# Beta Mode - Set to any value to enable beta indicator on login screen
NEXT_PUBLIC_BETA_MODE=true
```

**Note:** The variable must be prefixed with `NEXT_PUBLIC_` to be accessible on the client side in Next.js.

### 2. BetaBackground Component
Created `/src/app/login/BetaBackground.tsx`:
- Displays "BETA" text repeated in a grid pattern
- Text is rotated -45 degrees for an angled appearance
- Styled with:
  - Large font size (120px)
  - Low opacity (10%)
  - Gray color
  - Pointer events disabled (won't interfere with interactions)
  - Fixed positioning to cover entire viewport
  - z-index 0 to stay in background

### 3. LoginClient.tsx Updates
- Imported the `BetaBackground` component
- Added beta mode check: `const isBetaMode = process.env.NEXT_PUBLIC_BETA_MODE;`
- Modified container div to use `relative` positioning
- Conditionally renders `BetaBackground` when `isBetaMode` is truthy
- Login card has `z-10` to stay above the background

## Usage

### Enable Beta Mode
Set the environment variable in `.env`:
```
NEXT_PUBLIC_BETA_MODE=true
```

### Disable Beta Mode
Either:
1. Remove the `NEXT_PUBLIC_BETA_MODE` line from `.env`, or
2. Comment it out, or
3. Set it to an empty string: `NEXT_PUBLIC_BETA_MODE=`

## Technical Details

- The background uses a fixed position and fills the entire viewport
- Pointer events are disabled so it doesn't interfere with user interactions
- The "BETA" text is created using nested arrays to generate multiple rows and columns
- The rotation is applied using CSS transforms
- The component is positioned with z-index 0, while the login card has z-index 10

## Testing

After making these changes:
1. Restart your Next.js development server to pick up the new environment variable
2. Navigate to the login page
3. You should see "BETA" repeated in the background at a 45-degree angle
4. To test without beta mode, comment out `NEXT_PUBLIC_BETA_MODE` in `.env` and restart

## Browser Compatibility
This implementation uses standard CSS and React features and should work in all modern browsers.


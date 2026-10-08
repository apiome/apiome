# Logo Theme Update

## Summary
Updated the Apiome Browse application to display theme-appropriate logo images in the navbar without accompanying text.

## Changes Made

### File: `src/app/components/Navbar.tsx`

**What Changed:**
- Added `Image` import from `next/image`
- Replaced the placeholder blue gradient logo (letter "O") with actual Apiome logo images
- Removed the text "Apiome" and "API Specification Browser" that was displayed next to the logo
- Logo now dynamically switches based on the current theme using CSS classes:
  - **Light mode**: `/Apiome-02.png`
  - **Dark mode**: `/Apiome-05.png`

**Implementation Details:**
```tsx
{/* Light mode logo */}
<Image
  src="/Apiome-02.png"
  alt="Apiome Logo"
  width={120}
  height={48}
  className="object-contain dark:hidden h-12 w-auto"
  priority
/>
{/* Dark mode logo */}
<Image
  src="/Apiome-05.png"
  alt="Apiome Logo"
  width={120}
  height={48}
  className="object-contain hidden dark:block h-12 w-auto"
  priority
/>
```

**Size Details:**
- Logo height: `h-12` (48px) - fits well within the navbar's 64px height
- Width: `w-auto` - maintains the image's aspect ratio
- The navbar has `h-16` (64px) total height, leaving proper padding around the logo

**Technical Approach:**
Instead of conditionally rendering a single Image component based on `resolvedTheme`, we render both images and use Tailwind CSS's `dark:` variant to show/hide the appropriate one. This approach:
- Avoids hydration mismatches between server and client
- Works correctly with Next.js Image optimization
- Eliminates caching issues where the wrong image might persist
- Ensures immediate visual response to theme changes

## How It Works

1. Both logo images are rendered in the DOM simultaneously
2. Tailwind CSS classes control visibility:
   - Light mode logo: `dark:hidden` (visible by default, hidden in dark mode)
   - Dark mode logo: `hidden dark:block` (hidden by default, visible in dark mode)
3. The ThemeProvider adds/removes the `dark` class on `document.documentElement`
4. CSS handles the switching instantly when the class changes
5. No JavaScript state is needed for the visual switching, eliminating hydration issues

## Image Files

Both required images are already present in the `public/` directory:
- `Apiome-02.png` - Light mode logo
- `Apiome-05.png` - Dark mode logo

## Benefits

- ✅ Seamless theme integration
- ✅ Automatic updates when theme changes
- ✅ Uses Next.js Image component for optimized loading
- ✅ `priority` flag ensures logo loads immediately
- ✅ No layout shift during theme transitions


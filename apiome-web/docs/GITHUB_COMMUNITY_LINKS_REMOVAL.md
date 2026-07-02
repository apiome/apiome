# GitHub and Community Links Removal

**Date:** January 20, 2026

## Summary

Removed/commented out all GitHub and Community (Discord) links from the apiome-web application since these resources don't exist yet.

## Changes Made

### 1. **Footer Component** (`src/app/components/Footer.tsx`)

#### Social Icons Section
- ✅ Commented out GitHub social icon
- ✅ Removed unused `Github` import from lucide-react
- ✅ Kept: Twitter, YouTube, LinkedIn icons

#### Resources Section
- ✅ Commented out "GitHub" link
- ✅ Commented out "Community" (Discord) link
- ✅ Kept: "Tutorials" link (YouTube)

**Before:** Tutorials, GitHub, Community  
**After:** Tutorials only

---

### 2. **Home Page** (`src/app/page.tsx`)

#### CTA Section
- ✅ Commented out "View on GitHub" button
- ✅ Kept: "Launch App" button

**Before:** Launch App + View on GitHub buttons  
**After:** Launch App button only

---

## Links Removed

| Type | URL | Location |
|------|-----|----------|
| Social Icon | `https://github.com/apiome` | Footer - Brand section |
| Resources Link | `https://github.com/apiome` | Footer - Resources section |
| Resources Link | `https://discord.gg/apiome` | Footer - Resources section |
| CTA Button | `https://github.com/apiome` | Home page - CTA section |

---

## Active External Links

The following external links remain active:

### Social Media
- ✅ Twitter: `https://twitter.com/objectifieddev`
- ✅ YouTube: `https://www.youtube.com/@objectifieddev`
- ✅ LinkedIn: `https://linkedin.com/company/apiome`

### Product Links
- ✅ Launch App: `https://app.apiome.app`
- ✅ Browse APIs: `https://browse.apiome.app`
- ✅ Documentation: `https://docs.apiome.app`

### Resources
- ✅ Tutorials: `https://www.youtube.com/@objectifieddev`

---

## Future Restoration

When GitHub and Community resources become available, uncomment the relevant sections in:

1. `/src/app/components/Footer.tsx` - Lines with `/* GitHub - Coming Soon */` and `/* Community - Coming Soon */`
2. `/src/app/page.tsx` - Line with `/* GitHub - Coming Soon */`
3. Add back the `Github` import in Footer.tsx: `import { Github, Twitter, Linkedin, Youtube } from 'lucide-react';`

---

## Notes

- All changes are properly commented with "Coming Soon" markers for easy restoration
- No functionality was broken - only non-existent links were removed
- The disabled community page (`src/app/community.disabled/`) still contains GitHub/Discord references but is not active

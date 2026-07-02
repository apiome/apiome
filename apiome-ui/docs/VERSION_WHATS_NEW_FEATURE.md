# Version Number and What's New Feature

## Overview

This feature adds a version number display next to the Apiome logo in the application header, with a clickable link that opens a "What's New" dialog showing release notes rendered from a markdown file.

## Implementation

### Components Added

1. **WhatsNewDialog Component** (`src/app/components/ade/WhatsNewDialog.tsx`)
   - Modal dialog that displays markdown content
   - Fetches and renders `/public/WHATS_NEW.md`
   - Supports GitHub Flavored Markdown (GFM)
   - Allows embedded HTML, images, and links
   - Styled for both light and dark modes

2. **Version Badge** (in `TopHeader.tsx`)
   - Displays current app version (e.g., "v0.1.0")
   - Clickable button that opens the What's New dialog
   - Styled with border and hover effects
   - Positioned next to the Apiome logo

### Files Modified

- `src/app/components/ade/TopHeader.tsx` - Added version badge and dialog
- `package.json` - Added markdown rendering dependencies

### Files Created

- `src/app/components/ade/WhatsNewDialog.tsx` - What's New dialog component
- `public/WHATS_NEW.md` - Markdown content for release notes

## Dependencies Added

The following packages were added to support markdown rendering:

```json
{
  "dependencies": {
    "react-markdown": "^9.0.1",
    "rehype-raw": "^7.0.0",
    "remark-gfm": "^4.0.0"
  },
  "devDependencies": {
    "@types/react-markdown": "^9.0.0"
  }
}
```

## Installation

To install the new dependencies, run:

```bash
npm install
# or
yarn install
# or
pnpm install
# or
bun install
```

## Usage

### Viewing What's New

1. Look for the version number badge (e.g., "v0.1.0") next to the Apiome logo in the top header
2. Click on the version badge to open the What's New dialog
3. Read the release notes and new features
4. Click the X button or click outside the dialog to close it

### Updating Release Notes

To update the "What's New" content:

1. Edit `/public/WHATS_NEW.md`
2. Use standard Markdown syntax
3. Supported features:
   - Headings (h1-h6)
   - Bold, italic, strikethrough
   - Lists (ordered and unordered)
   - Links (automatically open in new tab)
   - Images (placed in `/public` folder)
   - Code blocks (inline and block)
   - Blockquotes
   - Horizontal rules
   - Tables (via GFM)
   - Task lists (via GFM)
   - Emoji (via GFM)

### Updating Version Number

To update the version number:

1. Update `version` in `/package.json`
2. Update `APP_VERSION` constant in `src/app/components/ade/TopHeader.tsx` to match

### Example Markdown with Images

```markdown
# What's New in v0.2.0

## New Features

### Studio Canvas
![Studio Canvas](/screenshots/studio-canvas.png)

The new studio canvas provides an interactive way to design your data models.

- Drag and drop classes
- Auto-layout functionality
- Visual relationship editing

[Learn more](/docs/studio)
```

## Styling

The dialog is fully styled to match the application's design system:

- Responsive design (max-width: 768px)
- Dark mode support
- Tailwind CSS classes
- Custom markdown component styles
- Z-index: 3000 (appears above other elements)

## Features

### Markdown Rendering

- **GitHub Flavored Markdown**: Full support for GFM features
- **HTML Support**: Raw HTML can be embedded in markdown
- **Syntax Highlighting**: Code blocks are styled appropriately
- **Links**: All external links open in new tabs with security attributes
- **Images**: Images are responsive and rounded

### Dialog Behavior

- Click outside to close
- ESC key support (native browser behavior)
- Smooth animations
- Loading state while fetching content
- Error handling for failed content loads

### Accessibility

- Proper ARIA labels
- Keyboard navigation support
- Focus management
- Screen reader friendly

## Future Enhancements

Potential improvements for future versions:

1. **Version History**: Show previous release notes
2. **Automatic Popup**: Show dialog on first visit after update
3. **Dynamic Version**: Read version directly from package.json at build time
4. **Changelog API**: Fetch release notes from a backend API
5. **Search**: Search within release notes
6. **Notifications Badge**: Show indicator for unread release notes
7. **Localization**: Multi-language support for release notes

## Technical Notes

### Package Versions

- `react-markdown` v9.x - Latest stable version with React 19 support
- `remark-gfm` v4.x - GitHub Flavored Markdown plugin
- `rehype-raw` v7.x - Allows raw HTML in markdown

### Performance

- Markdown content is fetched on-demand (only when dialog opens)
- Content is cached in component state while dialog is open
- No impact on initial page load

### Security

- External links use `rel="noopener noreferrer"`
- Content is fetched from trusted local source
- HTML sanitization handled by rehype-raw

## Troubleshooting

### Dialog doesn't open
- Check browser console for errors
- Verify WhatsNewDialog component is imported correctly
- Ensure state management is working

### Markdown not rendering
- Verify `/public/WHATS_NEW.md` exists
- Check file permissions
- Review browser network tab for fetch errors

### Styles look wrong
- Ensure Tailwind CSS is properly configured
- Check dark mode detection is working
- Verify prose classes are available

## Example Content Structure

```markdown
# What's New in Apiome v0.1.0

Welcome to the initial release!

## 🎉 New Features

### Feature Name
Description of the feature with **bold** and *italic* text.

![Feature Screenshot](/images/feature.png)

- Bullet point 1
- Bullet point 2

## 🔧 Improvements

- Improvement 1
- Improvement 2

## 📚 Resources

- [Documentation](https://example.com/docs)
- [GitHub](https://github.com/your-repo)

---

**Thank you for using Apiome!**
```


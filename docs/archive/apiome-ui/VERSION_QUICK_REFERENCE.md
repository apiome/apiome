# Quick Reference: Updating Version & Release Notes

## When Releasing a New Version

### ✅ Checklist

- [ ] Update version number in `package.json`
- [ ] (Optional) Set `NEXT_PUBLIC_APP_BUILD_LABEL` at build time if the badge should show a build id instead of `v{version}`
- [ ] Update `public/WHATS_NEW.md` with new release notes
- [ ] Test the What's New dialog
- [ ] Commit all changes

---

## 1. Update Version Number

### File: `package.json`
```json
{
  "version": "0.2.0"  ← Change this
}
```

### Version badge

The header badge reads **`v{version}`** from `package.json` by default. For deploys that need a build stamp (for example `2026.05.05-84a231c`), set **`NEXT_PUBLIC_APP_BUILD_LABEL`** when running `next build`; that string is shown as-is on the badge.

---

## 2. Update Release Notes

### File: `public/WHATS_NEW.md`

**Replace the content** with your new release notes:

```markdown
# What's New in Apiome v0.2.0

Welcome to version 0.2.0! Here's what's new...

## 🎉 New Features

### Feature Name
Description of the feature.

- Key point 1
- Key point 2

![Screenshot](/images/feature-screenshot.png)

## 🔧 Improvements

- Improvement 1
- Improvement 2

## 🐛 Bug Fixes

- Fixed issue with...
- Resolved problem where...

---

**Thank you for using Apiome!**

*Last updated: [Date]*
```

---

## 3. Markdown Syntax Quick Reference

### Headings
```markdown
# Main Title (h1)
## Section (h2)
### Subsection (h3)
```

### Text Formatting
```markdown
**bold text**
*italic text*
~~strikethrough~~
`code`
```

### Lists
```markdown
Unordered:
- Item 1
- Item 2

Ordered:
1. First
2. Second

Task list:
- [x] Done
- [ ] Todo
```

### Links
```markdown
[Link text](https://example.com)
```

### Images
```markdown
![Alt text](/images/screenshot.png)

Note: Place images in /public/images/
```

### Code Blocks
```markdown
Inline: `const x = 1;`

Block:
```javascript
const example = () => {
  console.log('Hello');
};
```
```

### Emojis
```markdown
:rocket: :tada: :sparkles: :bug: :wrench:
```

Common ones:
- 🎉 `:tada:` - New features
- 🔧 `:wrench:` - Improvements
- 🐛 `:bug:` - Bug fixes
- 🚀 `:rocket:` - Performance
- ✨ `:sparkles:` - New additions
- 📚 `:books:` - Documentation

### Horizontal Line
```markdown
---
```

### Blockquote
```markdown
> Important note or quote
```

### Tables
```markdown
| Feature | Status |
|---------|--------|
| A       | Done   |
| B       | WIP    |
```

---

## 4. Adding Images

### Step 1: Save Image
```
/public/
  images/
    feature-screenshot.png  ← Place here
    new-ui.png
```

### Step 2: Reference in Markdown
```markdown
![Feature Description](/images/feature-screenshot.png)
```

**Tips:**
- Use descriptive filenames
- Optimize images (compress before adding)
- Use PNG for UI screenshots
- Use JPG for photos
- Keep under 500KB per image

---

## 5. Testing Your Changes

### Before Committing:

1. **Start dev server**:
   ```bash
   npm run dev
   ```

2. **Navigate to app**:
   - Go to `/ade/dashboard` or `/ade/studio`

3. **Check version badge**:
   - Should show new version number
   - E.g., "v0.2.0"

4. **Open What's New dialog**:
   - Click the version badge
   - Dialog should open smoothly

5. **Verify content**:
   - All headings render correctly
   - Lists are formatted properly
   - Images load and display
   - Links work and open in new tabs
   - Code blocks are styled correctly

6. **Test both modes**:
   - Try in light mode
   - Try in dark mode
   - Everything should be readable

7. **Test closing**:
   - Close with X button ✓
   - Close by clicking outside ✓

---

## 6. Content Template

Copy and paste this template for new releases:

```markdown
# What's New in Apiome v[VERSION]

Welcome to version [VERSION]! This release brings [brief overview].

---

## 🎉 New Features

### [Feature Name]
[Description of the feature and why it's useful]

**Highlights:**
- Key feature point 1
- Key feature point 2
- Key feature point 3

[Optional: Image or code example]

---

## 🔧 Improvements

- **[Area]**: Improved [specific improvement]
- **[Area]**: Enhanced [specific enhancement]
- **[Area]**: Optimized [specific optimization]

---

## 🐛 Bug Fixes

- Fixed issue where [description]
- Resolved problem with [description]
- Corrected behavior of [description]

---

## 🚀 Performance

- [Performance improvement description]
- [Another performance improvement]

---

## 📚 Documentation

New documentation added:
- [Doc title](link)
- [Doc title](link)

---

## 💬 Feedback

We'd love to hear your thoughts on these new features!

[Link to feedback form or GitHub issues]

---

**Thank you for using Apiome!** 🎉

*Released: [Date]*
```

---

## 7. Best Practices

### Writing Release Notes

✅ **Do:**
- Start with most exciting features
- Use clear, concise language
- Include visuals when possible
- Explain why features matter
- Link to detailed documentation
- Thank users for feedback
- Keep it positive and engaging

❌ **Don't:**
- Use technical jargon without explanation
- Write a wall of text without structure
- Forget to proofread
- Include internal-only information
- Make it too long (keep under 3 screens)

### Version Numbering

Follow semantic versioning:
- **Major** (1.0.0): Breaking changes
- **Minor** (0.1.0): New features, backwards compatible
- **Patch** (0.0.1): Bug fixes, small improvements

---

## 8. Example: Good vs. Bad

### ❌ Bad
```markdown
# v0.2.0

- Added stuff
- Fixed bugs
- Updated code
```

### ✅ Good
```markdown
# What's New in Apiome v0.2.0

## 🎉 New Features

### Export to TypeScript
You can now export your data models as TypeScript interfaces!

![Export Dialog](/images/export-typescript.png)

**How to use:**
1. Open your model in Studio
2. Click "Export" in the toolbar
3. Select "TypeScript"
4. Copy or download the generated code

This makes it easy to keep your code in sync with your models.

---

## 🔧 Improvements

- **Canvas Performance**: 50% faster rendering for large diagrams
- **Dark Mode**: Improved contrast for better readability
- **Mobile**: Better touch support on tablets

---

**Thank you for using Apiome!** 🎉
```

---

## 9. Troubleshooting

### Version badge shows old version
- Check both files are updated
- Restart dev server
- Clear browser cache

### Markdown not rendering
- Check syntax (use preview tool)
- Verify file saved as UTF-8
- Check for unclosed code blocks

### Images not showing
- Verify file path (relative to /public)
- Check file actually exists
- Check file permissions
- Try with just filename if in public root

### Dialog looks wrong
- Check dark mode is working
- Verify Tailwind classes are loading
- Check for console errors
- Clear browser cache

---

## 10. Quick Commands

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Lint code
npm run lint

# Install new dependencies (if needed)
npm install
```

---

## Summary

**To release a new version:**
1. Bump `"version"` in `package.json` (and set `NEXT_PUBLIC_APP_BUILD_LABEL` at build time only if you want a custom badge)
2. Write new release notes in WHATS_NEW.md
3. Test the feature
4. Commit changes

**Simple as that!** 🚀

---

## Need Help?

- **Full Docs**: `docs/VERSION_WHATS_NEW_FEATURE.md`
- **Visual Guide**: `docs/VERSION_VISUAL_GUIDE.md`
- **Install Guide**: `INSTALL_VERSION_FEATURE.md`
- **Summary**: `VERSION_FEATURE_SUMMARY.md`


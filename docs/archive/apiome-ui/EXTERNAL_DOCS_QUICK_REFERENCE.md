# External Documentation Quick Reference

## What is External Documentation?

External Documentation allows you to link your class definitions to additional documentation outside the OpenAPI specification, such as user guides, API references, wiki pages, or video tutorials.

## How to Add External Documentation

### Quick Steps

1. **Open Class Editor**
   - Create a new class or edit an existing one

2. **Find External Documentation Section**
   - Scroll down to find "External Documentation" (gray box)
   - Located after "Deprecated" and before "Extensions"

3. **Add URL**
   - Enter documentation URL in "Documentation URL" field
   - Example: `https://docs.example.com/classes/user`

4. **Add Description (Optional)**
   - Describe what the documentation contains
   - Example: `"Detailed user guide with examples"`

5. **Test Link**
   - Click "Check Link" button to verify URL
   - Opens in new tab

6. **Save**
   - Click Save to persist changes

## Field Details

### Documentation URL
- **Required:** Yes (if you want externalDocs)
- **Format:** Valid URL (http/https)
- **Example:** `https://docs.example.com/user-guide`

### Description
- **Required:** No
- **Format:** Plain text (can be multiline)
- **Example:** `"Complete guide with examples and best practices"`

## Check Link Button

### What It Does
- Opens the URL in a new browser tab
- Verifies the link is working
- Helps catch typos before saving

### When It Appears
- Only shows when URL field has content
- Grayed out in read-only mode

### How to Use
1. Type URL in "Documentation URL" field
2. "Check Link" button appears
3. Click button to test
4. New tab opens with your URL

## Common Use Cases

### 1. User Guides
```
URL: https://docs.example.com/guides/user-class
Description: Complete user class guide with examples
```

### 2. API Documentation
```
URL: https://api-docs.example.com/resources/user
Description: REST API endpoints for user resources
```

### 3. Wiki Pages
```
URL: https://wiki.company.com/schemas/user
Description: Internal wiki with design decisions
```

### 4. Migration Guides
```
URL: https://docs.example.com/migrations/user-v2
Description: Guide for migrating from v1 to v2
```

### 5. GitHub Examples
```
URL: https://github.com/company/repo/tree/main/examples/user
Description: Code examples and integration samples
```

### 6. Video Tutorials
```
URL: https://www.youtube.com/watch?v=abc123
Description: Video: Working with User objects
```

### 7. Confluence Pages
```
URL: https://confluence.company.com/display/API/User
Description: Technical specification and requirements
```

## Tips

### Best Practices
- ✅ Use HTTPS URLs when possible
- ✅ Keep descriptions concise but informative
- ✅ Test links before saving
- ✅ Update links when documentation moves
- ✅ Include version info in URL if needed

### Common Patterns
- Documentation sites: `https://docs.example.com/...`
- GitHub: `https://github.com/user/repo/...`
- Wiki: `https://wiki.example.com/...`
- Confluence: `https://confluence.example.com/...`
- YouTube: `https://www.youtube.com/watch?v=...`

### What to Link
- ✅ User guides
- ✅ API references
- ✅ Code examples
- ✅ Video tutorials
- ✅ Migration guides
- ✅ Design documents
- ✅ Best practices

### What NOT to Link
- ❌ Internal-only URLs (if API is public)
- ❌ Temporary/draft documents
- ❌ Broken or outdated links
- ❌ Non-documentation content

## Examples

### Example 1: Simple Link
```
Documentation URL: https://docs.example.com/user
Description: (leave empty)
```

**Result in OpenAPI:**
```json
{
  "externalDocs": {
    "url": "https://docs.example.com/user"
  }
}
```

### Example 2: With Description
```
Documentation URL: https://docs.example.com/user
Description: Comprehensive user guide with examples
```

**Result in OpenAPI:**
```json
{
  "externalDocs": {
    "url": "https://docs.example.com/user",
    "description": "Comprehensive user guide with examples"
  }
}
```

### Example 3: GitHub Wiki
```
Documentation URL: https://github.com/company/repo/wiki/User-Schema
Description: Schema design and implementation notes
```

### Example 4: Multiple Sections
For classes with complex documentation needs:
```
Documentation URL: https://docs.example.com/user
Description: Main guide. See also: API ref at /api/user and examples at /examples/user
```

## Viewing External Documentation

Once added, external documentation appears in:
- ✅ JSON view (externalDocs object)
- ✅ YAML view (externalDocs section)
- ✅ OpenAPI export files
- ✅ Generated documentation

## Editing/Removing

### To Edit
1. Open class editor
2. Modify URL or description
3. Click "Check Link" to verify
4. Save changes

### To Remove
1. Open class editor
2. Clear the URL field
3. Save changes
4. ExternalDocs will be removed from schema

## Troubleshooting

### "Check Link" Button Not Showing
- Make sure URL field has content
- Button appears automatically when you type

### Link Opens Wrong Page
- Check for typos in URL
- Verify URL is complete (includes https://)
- Test in browser directly

### Link Doesn't Open
- Check browser popup blocker
- Verify URL is valid
- Try copying URL and pasting in browser

### Changes Not Saving
- Make sure you clicked Save button
- Check for error messages
- Verify you're not in read-only mode

### Description Truncated
- Description field supports multiline text
- Can include multiple paragraphs
- No strict character limit

## FAQ

**Q: Is the URL required?**  
A: No, but if you want externalDocs in your schema, you must provide a URL.

**Q: Can I add multiple URLs?**  
A: Currently only one URL per class. Use description to reference additional links.

**Q: What URL formats are supported?**  
A: Any valid HTTP/HTTPS URL. File:// URLs not recommended.

**Q: Is the description required?**  
A: No, description is optional.

**Q: Can I link to internal documentation?**  
A: Yes, but consider if external consumers can access it.

**Q: Does "Check Link" validate the URL?**  
A: It opens the link in a new tab. You verify it works correctly.

**Q: Can I use relative URLs?**  
A: Not recommended. Use absolute URLs (https://...).

**Q: Will this work with all documentation tools?**  
A: Yes, it follows OpenAPI 3.1 standard, widely supported.

**Q: Can I use this for deprecated classes?**  
A: Yes! Great for linking to migration guides.

**Q: How do I link to a specific section?**  
A: Use URL fragments: `https://docs.example.com/user#properties`

## Related Features

- **Description Field:** Basic class description
- **Extensions:** Add custom metadata with x- properties
- **Tags:** Organize classes by category
- **Deprecated:** Mark old classes (link to migration guide)

## Advanced Usage

### Version-Specific Links
```
URL: https://docs.example.com/v2/user
Description: Documentation for version 2.0
```

### Anchor Links
```
URL: https://docs.example.com/schemas#user-class
Description: Jump to User Class section
```

### Query Parameters
```
URL: https://docs.example.com/search?q=user+class
Description: Search results for User Class
```

### Multi-Language Docs
```
URL: https://docs.example.com/en/user
Description: English documentation (also available in /es, /fr)
```

## Need Help?

- See full documentation: `/docs/EXTERNAL_DOCS_FEATURE.md`
- OpenAPI Spec: https://spec.openapis.org/oas/v3.1.0#external-documentation-object
- Ask your team about documentation standards
- Check existing classes for examples

---

**Quick Tip:** Always test your links with the "Check Link" button before saving!


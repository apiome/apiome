# External Documentation Feature

## Overview

The External Documentation feature allows users to add optional external documentation links to class definitions. This follows the OpenAPI 3.1 specification's `externalDocs` object, providing a way to reference additional documentation outside the OpenAPI specification itself.

## Implementation

### Components Modified

#### ClassEditDialog Component

**Location:** `/src/app/components/ade/studio/ClassEditDialog.tsx`

**Changes Made:**

1. **Form State Addition:**
   - Added `externalDocsUrl: ''` - URL to external documentation
   - Added `externalDocsDescription: ''` - Optional description of the external docs

2. **Schema Loading:**
   - Extracts `externalDocs.url` and `externalDocs.description` from schema on load
   - Populates form fields when editing existing classes

3. **Schema Building:**
   - Creates `externalDocs` object in schema if URL is provided
   - Only includes description if it's non-empty
   - URL is required for externalDocs to be added to schema

4. **UI Addition:**
   - External Documentation section added between Deprecated and Extensions
   - Styled Box with gray background for consistency
   - Documentation URL field with "Check Link" button
   - Optional description field
   - Disabled when in read-only mode

### Database Storage

External documentation is stored as part of the class schema in the `classes.schema` JSONB column as the `externalDocs` object.

**Example Schema with externalDocs:**
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" }
  },
  "externalDocs": {
    "url": "https://docs.example.com/classes/user",
    "description": "Detailed user guide with examples and best practices"
  }
}
```

## Features

### 1. Documentation URL Field
- **Type:** URL input field
- **Required:** No (but externalDocs won't be added if empty)
- **Validation:** Browser native URL validation
- **Placeholder:** `https://docs.example.com/classes/user`

### 2. Check Link Button
- **Icon:** ExternalLink (from lucide-react)
- **Behavior:** Opens URL in new tab with security attributes
- **Visibility:** Only shows when URL field has content
- **Security:** Uses `noopener,noreferrer` for security
- **Disabled:** When in read-only mode

### 3. Description Field
- **Type:** Multiline text input (2 rows)
- **Required:** No
- **Purpose:** Describe what the external documentation contains
- **Placeholder:** `e.g., Detailed user guide with examples`

## Usage

### Adding External Documentation

1. Open the Class Edit Dialog (create new or edit existing class)
2. Scroll to the "External Documentation" section (after Deprecated, before Extensions)
3. Enter a documentation URL in the "Documentation URL" field
4. Optionally add a description in the "Description" field
5. Click "Check Link" to verify the URL opens correctly
6. Save the class to persist the external documentation

### Checking the Link

1. Enter a URL in the "Documentation URL" field
2. Click the "Check Link" button that appears
3. A new browser tab opens with the URL
4. Verify the link is correct before saving

### Removing External Documentation

1. Clear the URL field
2. Save the class
3. The externalDocs object will be removed from the schema

## OpenAPI 3.1 Compliance

This implementation follows the OpenAPI 3.1.0 specification for External Documentation:

**Specification Reference:**
- [OpenAPI 3.1 - External Documentation Object](https://spec.openapis.org/oas/v3.1.0#external-documentation-object)

**Required Fields:**
- `url` (string) - REQUIRED. The URL for the target documentation

**Optional Fields:**
- `description` (string) - A description of the target documentation

**Implementation Details:**
- URL is required (externalDocs not added if URL is empty)
- Description is optional
- Both fields are trimmed before saving
- Stored at schema root level per OpenAPI spec

## Use Cases

### 1. User Guides
```json
{
  "externalDocs": {
    "url": "https://docs.example.com/guides/user-class",
    "description": "Complete user class guide with examples"
  }
}
```

### 2. API Documentation
```json
{
  "externalDocs": {
    "url": "https://api-docs.example.com/resources/user",
    "description": "REST API endpoints for user resources"
  }
}
```

### 3. Wiki Pages
```json
{
  "externalDocs": {
    "url": "https://wiki.example.com/schemas/user",
    "description": "Internal wiki with schema design decisions"
  }
}
```

### 4. Migration Guides
```json
{
  "externalDocs": {
    "url": "https://docs.example.com/migrations/user-v2",
    "description": "Migration guide from UserV1 to UserV2"
  }
}
```

### 5. Code Examples
```json
{
  "externalDocs": {
    "url": "https://github.com/example/repo/tree/main/examples/user",
    "description": "Code examples and integration samples"
  }
}
```

### 6. Video Tutorials
```json
{
  "externalDocs": {
    "url": "https://www.youtube.com/watch?v=example",
    "description": "Video tutorial: Working with User objects"
  }
}
```

## UI Design

### Visual Layout

```
┌──────────────────────────────────────────────┐
│ External Documentation                       │
│ Link to additional documentation outside     │
│ the OpenAPI specification                    │
│                                              │
│ Documentation URL                            │
│ [https://docs.example.com/...  ] [Check Link]│
│ URL to external documentation               │
│                                              │
│ Description (Optional)                       │
│ [                                      ]     │
│ [                                      ]     │
│ Optional description of external docs        │
└──────────────────────────────────────────────┘
```

### Component States

#### Empty State
- URL field: Empty
- Description field: Empty
- Check Link button: Hidden

#### With URL Only
- URL field: Contains URL
- Description field: Empty
- Check Link button: Visible and enabled

#### Complete
- URL field: Contains URL
- Description field: Contains description
- Check Link button: Visible and enabled

#### Read-Only Mode
- URL field: Disabled
- Description field: Disabled
- Check Link button: Disabled (but visible if URL exists)

## Technical Details

### Type Safety

```typescript
// Form state
{
  externalDocsUrl: string;
  externalDocsDescription: string;
}

// Schema output
{
  externalDocs?: {
    url: string;
    description?: string;
  }
}
```

### Schema Building Logic

```typescript
// Add externalDocs if URL is provided
if (formData.externalDocsUrl.trim()) {
  schema.externalDocs = {
    url: formData.externalDocsUrl.trim()
  };
  if (formData.externalDocsDescription.trim()) {
    schema.externalDocs.description = formData.externalDocsDescription.trim();
  }
}
```

### Schema Loading Logic

```typescript
// Extract from schema
externalDocsUrl: schema.externalDocs?.url || '',
externalDocsDescription: schema.externalDocs?.description || '',
```

### Check Link Implementation

```typescript
<Button
  startIcon={<ExternalLink size={16} />}
  onClick={() => {
    const url = formData.externalDocsUrl.trim();
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }}
>
  Check Link
</Button>
```

**Security Features:**
- `_blank` - Opens in new tab
- `noopener` - Prevents new page from accessing window.opener
- `noreferrer` - Doesn't send referrer information

## Benefits

### For Users
- Quick access to detailed documentation
- Centralized documentation links
- Easy verification of link validity
- Consistent documentation structure

### For Teams
- Standardized way to reference docs
- Better documentation discovery
- Reduced documentation duplication
- Improved onboarding experience

### For Documentation
- Single source of truth
- Easy to update external links
- Version-specific documentation
- Multi-format support (wiki, videos, code, etc.)

## Validation

### Client-Side
- URL field uses HTML5 URL validation
- Fields are trimmed before saving
- Empty URL = no externalDocs object created

### Recommendations
- Add server-side URL format validation
- Consider URL reachability checks
- Validate URL schemes (http/https)
- Check for broken links periodically

## Examples

### Basic Example
```typescript
// Form input
externalDocsUrl: "https://docs.example.com/user"
externalDocsDescription: ""

// Schema output
{
  "type": "object",
  "externalDocs": {
    "url": "https://docs.example.com/user"
  }
}
```

### Complete Example
```typescript
// Form input
externalDocsUrl: "https://docs.example.com/user"
externalDocsDescription: "Comprehensive user guide"

// Schema output
{
  "type": "object",
  "externalDocs": {
    "url": "https://docs.example.com/user",
    "description": "Comprehensive user guide"
  }
}
```

### Multiple Documentation Types

#### API Reference
```json
{
  "externalDocs": {
    "url": "https://api.example.com/reference/user",
    "description": "REST API reference documentation"
  }
}
```

#### GitHub Wiki
```json
{
  "externalDocs": {
    "url": "https://github.com/example/repo/wiki/User-Schema",
    "description": "Schema design and implementation notes"
  }
}
```

#### Confluence
```json
{
  "externalDocs": {
    "url": "https://confluence.example.com/display/API/User",
    "description": "Technical specification and use cases"
  }
}
```

## Backward Compatibility

✅ **100% Backward Compatible**
- Existing classes without externalDocs work unchanged
- Empty URL fields don't create externalDocs object
- No database migration required
- No breaking changes to APIs

## Browser Compatibility

- Modern browsers support window.open with security parameters
- URL input type works in all modern browsers
- Fallback to text input for older browsers

## Accessibility

- ✅ Keyboard accessible
- ✅ Screen reader labels
- ✅ ARIA attributes on button
- ✅ Clear focus indicators
- ✅ Semantic HTML

## Testing Checklist

- [ ] Create class with external docs URL only
- [ ] Create class with URL and description
- [ ] Edit class to add external docs
- [ ] Edit class to modify external docs
- [ ] Remove external docs (clear URL)
- [ ] Click "Check Link" button opens correct URL
- [ ] Check Link opens in new tab
- [ ] Verify in JSON view
- [ ] Verify in YAML view
- [ ] Verify in OpenAPI export
- [ ] Test with various URL formats
- [ ] Test with very long URLs
- [ ] Test with special characters in URL
- [ ] Test in read-only mode
- [ ] Test URL validation
- [ ] Test description with special characters
- [ ] Verify persistence after save/reload

## Future Enhancements

Potential improvements:
1. **URL Validation:** Real-time URL format validation
2. **Link Checking:** Automated broken link detection
3. **Templates:** Common documentation URL patterns
4. **Multiple Links:** Support multiple external doc links
5. **Icons:** Auto-detect and show icons for known doc platforms
6. **Preview:** Inline preview of documentation
7. **History:** Track changes to documentation links
8. **Suggestions:** Suggest relevant documentation based on class name

## Related Features

- **Extensions:** Can add custom doc-related extensions
- **Description:** Complements class description field
- **Tags:** Can organize classes by documentation status
- **Deprecated:** Often used together for migration docs

## Migration Notes

No database migration required. Feature is opt-in and backward compatible.

## Support

For questions or issues:
1. Check OpenAPI 3.1 specification
2. Review this documentation
3. Test with "Check Link" button
4. Contact your team lead

---

**Implementation Date:** December 12, 2025  
**Feature Status:** ✅ COMPLETE - Ready for Testing  
**OpenAPI Compliance:** ✅ Full OpenAPI 3.1 Support


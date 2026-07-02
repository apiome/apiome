# LLM Chat Markdown Rendering

## Overview
The LLM Import Dialog now supports real-time markdown parsing and rendering using `react-markdown` and `remark-gfm` libraries.

## Features

### Supported Markdown Elements

1. **Headings** (H1-H3)
   - Rendered with appropriate font sizes and weights
   - Proper spacing applied

2. **Text Formatting**
   - **Bold** text using `**text**`
   - *Italic* text using `*text*`
   - `Inline code` using backticks

3. **Code Blocks**
   - Syntax highlighting with language specification
   - Special treatment for JSON blocks (green text color)
   - Other code blocks with appropriate monospace font

4. **Lists**
   - Unordered lists with bullets
   - Ordered lists with numbers
   - Proper indentation and spacing

5. **Links**
   - External links with proper styling
   - Opens in new tab automatically
   - Hover effects

6. **Tables** (via remark-gfm)
   - Full table support with headers
   - Responsive overflow handling

7. **Blockquotes**
   - Left border styling
   - Italic text

8. **Horizontal Rules**
   - Divider lines for content separation

### GitHub Flavored Markdown (GFM)
The `remark-gfm` plugin enables:
- Strikethrough text using `~~text~~`
- Task lists with `- [ ]` and `- [x]`
- Tables
- Autolinks

## Implementation Details

### Real-Time Streaming
- Markdown is parsed and rendered in real-time as content streams from the LLM
- A blinking cursor appears at the end of streaming content to indicate active generation
- The cursor disappears once streaming is complete

### JSON Code Block Handling
- JSON code blocks are specially styled with:
  - Dark background (gray-900/black)
  - Green text color for JSON content
  - Language label in header
  - "Import This Spec" button appears below JSON blocks containing OpenAPI specifications

### Styling
- Uses Tailwind's `prose` classes for consistent typography
- Supports both light and dark modes
- Custom component overrides for specific elements
- Maintains consistency with the rest of the application's design system

## Usage

The markdown rendering is automatically applied to:
1. All assistant messages in the chat
2. Streaming content as it's being generated
3. Historical messages loaded from conversation

## Example

When the LLM responds with:

```markdown
# REST API for Blog

Here's an OpenAPI 3.1.0 specification:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Blog API",
    "version": "1.0.0"
  }
}
```

This will render with:
- A large heading for "REST API for Blog"
- Formatted explanation text
- A code block with JSON syntax highlighting
- An "Import This Spec" button below the JSON
```

The markdown is rendered instantly and updates in real-time as the LLM generates more content.

## Files Modified

1. **LLMImportDialog.tsx**
   - Added `ReactMarkdown` and `remarkGfm` imports
   - Updated `renderMessageContent()` function to use ReactMarkdown
   - Added custom component overrides for code blocks, headings, lists, etc.
   - Added streaming cursor support

2. **globals.css**
   - Added custom prose styles for markdown rendering
   - Ensured proper color inheritance for dark mode
   - Added spacing and typography adjustments

3. **jest.config.ts**
   - Added module name mappings for react-markdown mocks (for testing)

## Dependencies

- `react-markdown` ^10.1.0 - Main markdown parsing and rendering
- `remark-gfm` ^4.0.0 - GitHub Flavored Markdown support
- `rehype-raw` ^7.0.0 - HTML support in markdown (already installed)


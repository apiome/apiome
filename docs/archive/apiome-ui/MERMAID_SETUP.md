# Mermaid Diagram Rendering - Setup Guide

This document explains the new Mermaid diagram rendering feature and how to set it up.

## Overview

The Mermaid diagram feature now includes:
- **Preview Mode**: Visual rendering of the Mermaid class diagram
- **Code Mode**: View and edit the raw Mermaid syntax
- **Image Export**: Download diagrams as SVG or PNG files
- **Toggle Button**: Easily switch between preview and code views

## Installation Steps

1. **Install the mermaid package:**
   ```bash
   npm install mermaid
   # or
   yarn add mermaid
   # or
   pnpm add mermaid
   ```

2. **Restart the development server:**
   ```bash
   npm run dev
   ```

## Features

### 1. Preview Mode (Default)
- Renders the Mermaid diagram visually in the browser
- Provides a clean, interactive view of your class diagram
- Includes zoom and pan capabilities
- Shows clear error messages if the diagram syntax is invalid

### 2. Code Mode
- Shows the raw Mermaid syntax in a code editor
- Includes syntax highlighting
- Copy button to copy the code to clipboard
- Export button to download as .mmd file

### 3. Image Export (Preview Mode Only)
- **SVG Export**: Vector format, perfect for documentation and presentations
- **PNG Export**: Raster format with white background, good for embedding in documents

### 4. View Toggle
- Located in the header of the Mermaid view
- Two buttons: "Preview" (👁️) and "Code" (💻)
- Active mode is highlighted in blue
- Seamless switching between modes

## Usage

1. Navigate to the Studio page
2. Select a project and version
3. Switch to the "Mermaid" tab
4. By default, you'll see the rendered diagram (Preview mode)
5. Click "Code" to view the raw Mermaid syntax
6. Use the export buttons to save your diagram:
   - In Preview mode: SVG or PNG
   - In Code mode: .mmd file

## Technical Details

### Files Added/Modified

1. **New Component**: `src/app/components/ade/studio/MermaidPreview.tsx`
   - Handles Mermaid rendering using the mermaid library
   - Implements SVG and PNG export functionality
   - Displays error messages for invalid syntax

2. **Updated**: `src/app/ade/studio/page.tsx`
   - Added Eye and Code icons from lucide-react
   - Imported MermaidPreview component
   - Added mermaidViewMode state ('code' | 'preview')
   - Updated UI to include toggle buttons
   - Conditional rendering based on view mode

3. **Updated**: `package.json`
   - Added `mermaid` dependency (^11.4.1)

### Dependencies

- `mermaid` (^11.4.1): For rendering Mermaid diagrams
- Existing dependencies remain unchanged

## Troubleshooting

### Issue: "Cannot find module 'mermaid'"
**Solution**: Run `npm install` to install the new dependency

### Issue: Diagram not rendering
**Solution**: Check the browser console for syntax errors in the Mermaid code

### Issue: Export buttons not working
**Solution**: Ensure you're in Preview mode for image exports

### Issue: PNG export has no content
**Solution**: This can happen if the SVG hasn't fully rendered. Try clicking export again after a moment.

## Benefits

1. **Better Visualization**: See your class diagrams rendered beautifully
2. **Multiple Export Options**: Choose the format that works best for your needs
3. **Flexibility**: Switch between code and visual views as needed
4. **Professional Output**: High-quality SVG and PNG exports for documentation
5. **Error Handling**: Clear feedback when diagram syntax has issues

## Future Enhancements

Potential improvements for future versions:
- Dark mode support for rendered diagrams
- Additional export formats (PDF, JPEG)
- Inline editing of the Mermaid code
- Custom theme configuration
- Diagram zoom controls in preview mode

---

**Last Updated**: November 29, 2025


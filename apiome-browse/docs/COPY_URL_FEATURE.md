# Copy URL Feature

## Overview
Added a "Copy URL" button to the SpecViewer component that allows users to quickly copy the current document URL to their clipboard.

## Implementation Details

### Location
The button is positioned in the toolbar, directly to the right of the OpenAPI/Arazzo/JSON Schema button group, separated by a vertical bar divider.

### Functionality
- **Action**: Clicking the button copies the current document's API URL to the clipboard
- **URL Format**: The URL corresponds to the selected format:
  - OpenAPI: `${restApiBaseUrl}/schema/${tenantSlug}/${projectSlug}/${versionSlug}`
  - Arazzo: `${restApiBaseUrl}/arazzo/${tenantSlug}/${projectSlug}/${versionSlug}`
  - JSON Schema: `${restApiBaseUrl}/json/${tenantSlug}/${projectSlug}/${versionSlug}`

### User Experience
- **Default State**: Shows a link icon with "Copy URL" text
- **Copied State**: Changes to a checkmark icon with "Copied!" text for 2 seconds
- **Styling**: Matches the design system with proper dark mode support
- **Tooltip**: Includes a helpful tooltip "Copy document URL"

### Technical Changes

#### File Modified
`src/app/components/SpecViewer.tsx`

#### Changes Made
1. Added `urlCopied` state to track when URL has been copied
2. Created `copyUrl()` function that:
   - Determines the appropriate URL based on the current format
   - Copies the URL to clipboard using the Navigator Clipboard API
   - Shows confirmation feedback for 2 seconds
3. Restructured the toolbar layout to group the format tabs and Copy URL button together on the left side
4. Added a vertical separator bar between the format tabs and the Copy URL button
5. Added the "Copy URL" button with:
   - Appropriate styling matching the design system
   - Icon that changes based on copied state
   - Smooth transitions and hover effects

## Benefits
- **Easy Sharing**: Users can quickly share document URLs with others
- **API Integration**: Developers can easily copy URLs for use in their applications
- **Format-Aware**: The URL automatically updates when switching between OpenAPI, Arazzo, and JSON Schema formats
- **User Feedback**: Clear visual confirmation when the URL is copied

## Testing
To test the feature:
1. Navigate to any version page (e.g., `/tenant/demo/myapi/1.0.0`)
2. Locate the "Copy URL" button next to the format tabs
3. Click the button
4. Verify the URL is copied to clipboard
5. Switch between OpenAPI, Arazzo, and JSON Schema formats
6. Verify the copied URL changes accordingly


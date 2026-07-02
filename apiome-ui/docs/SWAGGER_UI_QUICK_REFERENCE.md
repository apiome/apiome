# Swagger UI Quick Reference

## Overview
The Studio now has three view modes: Canvas, Code, and Swagger.

## View Modes

### 1. Canvas View
- Visual class diagram with ReactFlow
- Drag-and-drop functionality
- Auto-layout options (TB, LR, BT, RL)
- Edit classes and properties

### 2. Code View
- Monaco Editor with syntax highlighting
- Toggle between JSON and YAML formats
- Read-only view of OpenAPI 3.1.0 specification
- Copy and Export functionality

### 3. Swagger View (NEW)
- Interactive Swagger UI component
- Explore API endpoints
- Test requests with "Try it out"
- View request/response schemas
- Search/filter endpoints
- Copy and Export OpenAPI spec

## Switching Between Views

Click the view switcher buttons in the header:
- **Canvas** - Visual diagram
- **Code** - Text editor  
- **Swagger** - API docs

## Swagger View Features

### Header Controls
- **Copy Spec**: Copies OpenAPI JSON to clipboard
- **Export Spec**: Downloads OpenAPI specification as JSON file

### Swagger UI Configuration
```typescript
<SwaggerUI
  spec={JSON.parse(openApiSpec)}
  docExpansion="list"              // Expand only tags
  defaultModelsExpandDepth={1}     // Show 1 level of models
  defaultModelExpandDepth={3}      // Expand models 3 levels deep
  displayRequestDuration={true}    // Show request timing
  filter={true}                    // Enable search/filter
  showExtensions={true}            // Show OpenAPI extensions
  showCommonExtensions={true}      // Show vendor extensions
  tryItOutEnabled={true}           // Enable "Try it out"
/>
```

### Using Swagger UI

1. **Expand Endpoints**: Click on any endpoint to see details
2. **Try It Out**: Click "Try it out" to test the endpoint
3. **View Schemas**: Expand models to see data structures
4. **Search**: Use the filter box to find specific endpoints
5. **Copy Examples**: Click examples to copy JSON

## Implementation Details

### Files Changed
- `src/app/ade/studio/page.tsx`
  - Added Swagger UI dynamic import
  - Added CSS import
  - Extended ViewMode type
  - Added Swagger view rendering
  - Added Swagger button to view switcher

### Dependencies Used
- `swagger-ui-react@^5.30.2` (already installed)
- `@types/swagger-ui-react@^5.18.0` (already installed)

### Dynamic Import
Swagger UI is dynamically imported to prevent SSR issues:
```typescript
const SwaggerUI = dynamic(() => import('swagger-ui-react'), {
  ssr: false,
  loading: () => <div>Loading Swagger UI...</div>
});
```

## Data Flow

1. User selects project and version
2. System loads classes and properties
3. `generateOpenApiSpec()` creates OpenAPI 3.1.0 spec
4. Spec is used in all three views:
   - Canvas: Visualizes as diagram
   - Code: Displays as JSON/YAML
   - Swagger: Renders as interactive UI

## Empty States

### No Project/Version Selected
Shows prompt to select a project and version

### No Classes Defined
Swagger view shows:
- Icon
- "No OpenAPI Specification Available"
- "Add classes and properties to generate API documentation"

## URL Structure
No URL changes - all views share the same route: `/ade/studio`

## Keyboard Shortcuts
No specific keyboard shortcuts for view switching (could be added in future)

## Browser Compatibility
Works in all modern browsers that support:
- ES6+
- React 19
- Next.js 16
- CSS Grid/Flexbox

## Performance Notes
- Swagger UI loads dynamically (doesn't block initial page load)
- Large OpenAPI specs may take a moment to render
- "Loading Swagger UI..." message shows during load

## Troubleshooting

### Swagger UI Not Loading
1. Check browser console for errors
2. Verify `swagger-ui-react` is installed
3. Check that OpenAPI spec is valid JSON

### Styles Not Applying
1. Verify CSS import: `import 'swagger-ui-react/swagger-ui.css';`
2. Check for CSS conflicts with Tailwind

### "Try It Out" Not Working
1. Ensure `tryItOutEnabled={true}` in config
2. Check CORS settings if testing real endpoints
3. Verify base URL configuration

## Future Enhancements

### Planned
- Dark mode theme for Swagger UI
- Custom authentication configuration
- Base URL configuration for testing
- Deep linking to specific endpoints
- Remember user's view preference

### Possible
- Export as standalone HTML
- Custom Swagger UI plugins
- Request/response mocking
- API versioning comparison

## Related Documentation
- [Full Implementation Guide](./SWAGGER_UI_INTEGRATION.md)
- [OpenAPI Generation Utility](../src/app/utils/openapi.ts)
- [Studio Context](../src/app/ade/studio/StudioContext.tsx)

## Support
For issues or questions:
1. Check TypeScript errors in IDE
2. Review browser console
3. Verify OpenAPI spec is valid
4. Check documentation files


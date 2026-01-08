# Objectified 02-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## New Features and Improvements

- Bug fixes:
  - Added support for missing patternProperties in the property editor
  - Added support for discriminator mapping in the class editor
  - Added support for prefixItems to allow for description and examples
  - Fixed dependentProperties editing in the class editor, adds a logic builder
  - Fixed unevaluatedProperties in comprehension section of schemas
  - Fixed if/then/else in comprehension section of schemas
  - Fixed additionalProperties in property editor to allow for types and schemas
  - Fixed overall application layout to use less memory and split out sections into separate paths
  - Fixed side-by-side diff comparison view for versions
  - Fixed deleting a group from the canvas now properly deletes the database record
  - Fixed property template button icon color in light mode (was appearing black instead of white)
  - Fixed click-to-focus behavior in the canvas
  - Fixed dark mode and light mode (takes precedence over system settings)
  - Fixed group class positions not saving to database when dragging classes within groups (regression)
    - Classes dragged into groups now immediately persist to database with position
    - Moving classes within groups now updates positions in database
    - Class positions within groups are now properly restored when canvas is reloaded
    - Fixed syncGroupsForVersion to save position_x and position_y for all classes in groups
- Implemented a more advanced import system
  - File imports
  - URL imports with tokens and authentication
  - GitHub and GitLab repository imports
  - Clipboard-based copy/paste editor
  - Class import now supports file, URL, clipboard, and Git repository import sources
  - Import performs a sanity check to make sure all class imports are valid
  - Adds Commit/Rollback system to allow users to apply or discard changes made during an import session
  - Import supports:
    - OpenAPI 3.1.x
    - Swagger 2.0
    - JSON Schema Draft 7, 2019-09, 2020-12
    - GraphQL SDL
- Canvas improvements
  - Added per-class theming: customize colors for individual class nodes
    - 16 predefined color themes in a 4x4 grid (Slate, Gray, Red, Orange, Yellow, Green, Teal, Cyan, Blue, Indigo, Violet, Purple, and more)
    - Custom background, border, header gradient, and text colors
    - Themes persist in canvas_metadata and save automatically
    - Easy-to-use color picker with visual color swatches
    - Hover effects with scaling and shadows for better visual feedback
    - Reset button to restore default styling
  - Application-wide theme system
    - 9 pre-built themes: Follow System, Light, Dark, High Contrast, Blueprint, Whiteboard, Solarized, Nord, Darcula
    - Real-time updates: When you change your OS theme, the app updates immediately
    - Theme selector in profile menu with visual previews
    - Each theme shows color palette and live text preview
    - Backward compatible with existing dark mode
  - Added the ability to import a class directly using the same import system 
  - Added ability to persist layout settings for versions
  - Added creation of groups on the canvas via drag-and-drop from the sidebar
  - Added save and load buttons for manual layout management
  - Added group styling options: custom icons, border styles (dashed/solid/dotted), shadow levels, and background opacity
  - Added "Level of Detail" modal toggling
  - Removed existing auto layout code, as it was not working as intended; will fix in a later release
  - Added custom snap-to-grid functionality
  - Added smart guidelines when dragging nodes for better alignment
  - Added spacing utility for multiple nodes (selected with Shift key)
  - Added simple automatic layout algorithm for arranging nodes (needs further refinement)
  - Added edge styling:
    - Styling for direct, optional, weak, and bidirectional relationships
    - Color selection for edges
    - Styling for edge connectors including smart edge routing
- Added property templates
  - Fixed property copying to a class that contains an object with nested properties
- Dashboard improvements
  - Version comparison now shows a more comprehensive list of changes, with the ability to filter by change type (added, removed, modified)

[//]: # (- Introducing Paths - API endpoint design canvas)

[//]: # (  - Drag-and-drop path nodes onto the canvas from the library panel)

[//]: # (  - Real-time path variable extraction from path patterns &#40;e.g., `/api/{userId}/orders/{orderId}`&#41;)

[//]: # (  - Automatic properties panel opens when path is added to canvas)

[//]: # (  - Configure path variables: description, type &#40;string/integer/number/boolean&#41;, example value, required flag)

[//]: # (  - Full database integration with `odb.api_paths` and `odb.path_operations` tables)

[//]: # (  - Path metadata: summary, description &#40;with Monaco Editor and Markdown support&#41;, tags, deprecated flag)

[//]: # (  - Changes are automatically saved to the database in real-time)

[//]: # (  - Visual node design with color-coded HTTP methods &#40;GET=green, POST=blue, DELETE=red, etc.&#41;)

[//]: # (  - Path variables displayed as badges on the path node)

[//]: # (  - Monaco Editor for description field with syntax highlighting and markdown support)

[//]: # (  - Cancel and Save buttons for explicit change control)

[//]: # (  - Deprecated paths show visual strikethrough and red warning badge)

[//]: # (  - Enhanced deprecated checkbox with prominent styling and warning message)

[//]: # (  - Tags multi-select using project-defined tags with color-coded badges)

[//]: # (  - External documentation links with URL and description fields, clickable link preview)

[//]: # (  - HTTP method nodes with auto-generate operation ID from path and verb &#40;e.g., getUserById, createOrder&#41;)

[//]: # (  - Method node properties: operation ID, summary, description with Monaco Editor)

[//]: # (  - Paths and operations load from database on canvas initialization with automatic connections)

[//]: # (  - Operations saved to database when connected to paths or via Save button)

[//]: # (  - Tags for operational grouping - assign multiple tags to paths from project-defined tags)

[//]: # (  - Tags saved to database with full CRUD support via path_tags join table)

[//]: # (  - **Tags for HTTP method operations** - assign tags to individual operations &#40;GET, POST, etc.&#41;)

[//]: # (  - Operation tags saved to database via operation_tags join table with full CRUD support)

[//]: # (  - Tags automatically load from database for both paths and operations)

[//]: # (  - **Request Body Binding** - Configure request body for HTTP methods &#40;POST, PUT, PATCH&#41;)

[//]: # (    - Content type selector &#40;application/json, multipart/form-data, etc.&#41;)

[//]: # (    - **Schema Picker Modal** - Browse and select schema classes from your version)

[//]: # (      - Search functionality to filter schemas)

[//]: # (      - Schema type badges &#40;object, enum, array&#41;)

[//]: # (      - Description preview)

[//]: # (      - Double-click or button to select)

[//]: # (    - Schema reference with browse button and clear functionality)

[//]: # (    - Description field for documentation)

[//]: # (    - Required toggle for mandatory request bodies)

[//]: # (    - Visual preview of configured request body with schema name)

[//]: # (    - Smart detection: GET/DELETE/OPTIONS/HEAD show "no body" message)

[//]: # (    - **Full database persistence** - Request body settings are saved and loaded from database)

[//]: # (      - Creates/updates/deletes request body records)

[//]: # (      - Saves content type with schema reference)

[//]: # (      - Loads existing request body when selecting method node)

[//]: # (  - Complete verification and testing suite included &#40;see docs/PATH_TAGS_TESTING.md&#41;)

[//]: # (  - Comprehensive unit tests &#40;53 tests&#41; covering all functionality &#40;see docs/PATH_TAGS_TESTS_COMPLETE.md&#41;)

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: January 1, 2026*


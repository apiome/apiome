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
- Implemented a more advanced import system
  - File imports
  - URL imports with tokens and authentication
  - GitHub and GitLab repository imports
  - Clipboard-based copy/paste editor
  - Class import now supports file, URL, clipboard, and Git repository import sources
  - Import performs a sanity check to make sure all class imports are valid
  - Adds Commit/Rollback system to allow users to apply or discard changes made during an import session
- Canvas improvements
  - Added the ability to import a class directly using the same import system 
  - Added ability to persist layout settings for versions
  - Added creation of groups on the canvas via drag-and-drop from the sidebar
  - Added Save and Load buttons for manual layout management
  - Added group styling options: custom icons, border styles (dashed/solid/dotted), shadow levels, and background opacity
  - Removed existing auto layout code, as it was not working as intended; will fix in a later release
- Added property templates
  - Fixed property copying to a class that contains an object with nested properties
- Introducing Paths - API endpoint design canvas
  - Drag-and-drop path nodes onto the canvas from the library panel
  - Real-time path variable extraction from path patterns (e.g., `/api/{userId}/orders/{orderId}`)
  - Automatic properties panel opens when path is added to canvas
  - Configure path variables: description, type (string/integer/number/boolean), example value, required flag
  - Full database integration with `odb.api_paths` and `odb.path_operations` tables
  - Path metadata: summary, description (with Monaco Editor and Markdown support), tags, deprecated flag
  - Changes are automatically saved to the database in real-time
  - Visual node design with color-coded HTTP methods (GET=green, POST=blue, DELETE=red, etc.)
  - Path variables displayed as badges on the path node
  - Monaco Editor for description field with syntax highlighting and markdown support
  - Cancel and Save buttons for explicit change control
  - Deprecated paths show visual strikethrough and red warning badge
  - Enhanced deprecated checkbox with prominent styling and warning message
  - Tags multi-select using project-defined tags with color-coded badges
  - External documentation links with URL and description fields, clickable link preview
  - HTTP method nodes with auto-generate operation ID from path and verb (e.g., getUserById, createOrder)
  - Method node properties: operation ID, summary, description with Monaco Editor
  - Paths and operations load from database on canvas initialization with automatic connections
  - Operations saved to database when connected to paths or via Save button

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: January 1, 2026*


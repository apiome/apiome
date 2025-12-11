# Objectified 01-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## New Features and Improvements

- Even more look and feel improvements
- Properties form and editor have an improved layout
- Properties options have been improved:
  - Numeric constraints now use OpenAPI 3.1 / JSON Schema draft 2020-12 format
  - Added radio button options for minimum/maximum constraints: Inclusive (≥/≤) vs Exclusive (>/<)
  - Adds multipleOf constraint for numeric properties
  - All property constraints are now properly preserved when dragging properties to classes
  - Boolean and null types now show "No additional constraints" message in the Constraints section
  - Array types now support "contains" schema
  - Added "minContains" and "maxContains" fields - specify minimum/maximum number of items that must match the contains schema
  - prefixItems:
    - Define ordered schemas for specific array positions (e.g., `[string, number, boolean]`)
    - Enable "Tuple Mode" checkbox in array properties
    - Add/remove/reorder prefix items with drag-and-drop
    - Each position can have its own type and constraints
    - Control additional items beyond prefix with custom schema
    - Perfect for coordinates, CSV-like data, function arguments, and database rows
- Fixed Mermaid PNG generation issue
- Property enumerations can now be:
  - Sorted in ascending or descending order
  - Repositioned as desired within the enumeration list
- Added GitLab support for linked accounts and repositories
- Enhanced class editing layout
  - Double-clicking a class node now edits the node instead of displaying it as code
  - Moved the JSON/YAML and example generation to the edit form
- Added new publication endpoints:
  - /v1/arazzo now generates Arazzo
  - /v1/json now generates JSON Schema
- Added new layout options for the canvas:
  - **Hierarchical** (Top-Down, Left-Right, Bottom-Top, Right-Left) - Organized hierarchy with dependency flow
  - **Force-Directed** - Physics-based organic layout with natural clustering
  - **Circular** - Nodes arranged in a circle, ideal for cyclic dependencies
  - **Grid** - Clean grid pattern with alphabetical ordering
  - **Layered** - Horizontal layers based on dependency depth
  - Smooth animations between layout transitions for professional polish
- Additional Canvas Updates:
  - Added the ability to tag classes
  - Class nodes now display tag names alongside the class name for better visual organization
- Generate tab now generates:
  - Python Code with Pydantic, Dataclass and SQLAlchemy models
  - TypeScript interfaces
  - GraphQL Type Definitions
  - Scala Case Classes with codec libraries:
    - Play JSON
    - Circe
    - No Codec (plain case classes)
  - SQL DDL Statements with dialects in
    - PostgreSQL
    - MySQL
    - SQL Server
    - Oracle
    - SQLite
  - Java DTOs as POJOs, Lombok, or Records class generation

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: December 10, 2025*


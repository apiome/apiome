# Objectified 03-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## New Features and Improvements

- Canvas Improvements:
  - Added top-to-bottom and left-to-right layout options
  - Added focused searching functionality for focused searching in canvases with large structures
  - Added export form for exporting canvas diagrams with multiple output options
  - Added ability to switch connection types for edges in the canvas
  - Added background configurations to the canvas
  - Added ability to enable/disable grid
- Paths Improvements:
  - Added API Key security schemes: define header, query, or cookie-based API keys in the Security tab and use them on operations (#410)
  - Added inline variable editor that can click parameters in the header of the path studio
  - Added primitives template usage in schema definitions
  - Added security requirements to HTTP Operation endpoint definitions
  - Added the ability to mark operations as deprecated
  - Added the ability to mark operations as private (exclusion from Swagger)
  - Added external documentation to operations
  - Added x-* extension tags to HTTP Operation definitions
  - Added security section:
    - Adds API Keys for Security options
    - Adds HTTP Authentication options (Basic, Bearer, Custom)
    - Adds OAuth2 security options
    - Adds OpenID security options
    - Adds TLS security options
    - Adds custom security schema options
  - Added ability to apply multiple security schemes to HTTP Operations (and/or)
  - Added ability to specify different security scopes on a per-operation basis
  - Added ability to mark an endpoint as public (i.e. requires no security)
  - Configure required OAuth2/OpenID Connect scopes per operation (#421)
  - Dragging a property to a variable chip in the header will apply that property's primitive settings to the bound variable
- OpenAPI Support:
  - Now at 100% support for class and properties definitions
- Bug fixes:
  - Fixed AI generation bug when creating $ref objects: was referring to properties, not the object itself.
  - Fixed $ref editing in classes - was opening a blank editing panel, now corrected.
  - Fixed canvas layout to auto-load a canvas position if one was saved previously, but only on the initial load.
  - Updated AI model list to only include supported generative models.

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: February 1, 2026*


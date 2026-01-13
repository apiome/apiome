# Objectified 02-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## New Features and Improvements

- New Features:
  - Added new Application Dashboard landing page - presents all Objectified applications in an organized tile layout.
- Bug fixes:
  - Fixed ClassNode color changes not being reflected immediately - the memo comparison function now correctly detects theme changes to trigger re-renders.
  - Fixed expand/collapse chevrons in ClassNode not responding - the memo comparison function now correctly detects expandedProperties changes.
  - Improves drag/drop behavior in class nodes.
  - Fixed property template list to show [optional] when nullable is selected.
  - Fixed property to show numeric precision when applicable.
  - Fixed canvas reload/reposition issue when adding or removing properties to a class.
  - Fixed composition handles (allOf/oneOf/anyOf) not repositioning when ClassNode height changes due to property list changes.
  - Fixed auto-layout to treat groups as single units - grouped classes maintain their exact relative positions within the group.
  - Fixed group member nodes jumping after auto-layout when dragging the group - properly synchronizes group position reference.
  - Fixed response nodes in path canvas - clicking a response node now shows the ResponsePropertiesPanel with existing description loaded for editing.
  - Class Template Library now shows the schema preview.
  - Properties and Class Template Form now includes a "close" button
  - Properties now allow multiple properties to be added without closing the form.
  - Properties Template Form now shows the inline properties when an "object" type is selected.
  - Condensed property flags into a compact horizontal layout.
  - Class node styling changes were not persisting properly, this is now fixed.
- Code Generation:
  - Added GraphQL - added support for input types, enums, and interfaces.
  - Added SQL DDL - added support for indexes, constraints, and foreign keys.
  - Added AsyncAPI 3.0.0 - generate event-driven API specifications with channels, messages, operations, and schema definitions for Kafka, AMQP, MQTT, WebSocket, and HTTP protocols.

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: January 11, 2026*


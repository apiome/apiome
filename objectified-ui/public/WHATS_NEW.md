# Objectified 02-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## New Features and Improvements

- New Features:
  - Added new Application Dashboard landing page - presents all Objectified applications in an organized tile layout
  - Added interactive quality score cards during import - click on any quality score card for more details
  - Added Chart View tab in import preview - shows a diagram before importing, showing how classes relate to each other through references
  - Various UI/UX improvements and optimizations for better performance and responsiveness
- Primitives:
  - Primitives can now be defined to use as templates for properties when defining property types
  - System is preloaded with ISO-standard JSON Schema primitives for common data type definitions
  - Properties can now apply primitive types to define their data types
  - Importing from files and URLs are supported
- Pathing:
  - Now implements the ability to create a path:
    - Create paths with multiple operations (GET, POST, PUT, DELETE, etc.) under the same endpoint
    - Support for path parameters, query parameters, headers, and request bodies
    - Visual representation of paths and operations in the Path Canvas
    - Ability to define responses for each operation with status codes and descriptions
    - Ability to generate class responses based on the defined responses in the path
    - Ability to link existing classes to path responses
    - Ability to define class request bodies for operations with class definitions and property definitions
    - Ability to create CRUD operations at the time a path is created
- Template Improvements:
  - Address classes: BillingAddress, ShippingAddress, AddressValidation
  - Analytics classes: PageView, AnalyticsEvent, Conversion, ABTest
  - Common classes: Money, Coordinates, DateRange, FileUpload, Pagination, SortOptions, AuditTimestamps
  - Communication classes: Message, Thread, MessageAttachment, ChatRoom
  - Compliance classes: GDPRConsent, DataRetention, AuditTrail, PrivacySettings
  - Content classes: MediaGallery, ContentTag, ContentComment, Rating, Article, FAQ
  - Integrations classes: WebhookEvent, APICredential, OAuthToken, EmailTemplate
  - Marketplace classes: Vendor, Commission, Dispute, Escrow
  - Notifications classes: PushNotification, EmailNotification, SMSNotification, NotificationPreference
  - Orders classes: Cart, EnhancedOrderItem, Refund, Shipment, Invoice
  - Payments classes: PaymentIntent, PaymentMethod, Subscription, Transaction, Payout
  - Products classes: ProductVariant, Inventory, ProductCategory, ProductReview, ProductPrice
  - Scheduling classes: Appointment, Availability, Calendar, Reminder
  - Security classes: Session, APIKeyAuth, SecurityEvent, IPWhiteList, RateLimit
  - Support classes: Ticket, TicketComment, SLA, KnowledgeBase
  - User/Auth classes: EnhancedUserProfile, Role, Permission, TwoFactorAuth, PasswordReset
- Import Improvements:
  - Adds AI Assistant to help create an OpenAPI specification from a natural language query
  - Adds SwaggerHub import support
- Bug fixes:
  - Fixed ClassNode color changes not being reflected immediately - the memo comparison function now correctly detects theme changes to trigger re-renders
  - Fixed expand/collapse chevrons in ClassNode not responding - the memo comparison function now correctly detects expandedProperties changes
  - Improves drag/drop behavior in class nodes
  - Fixed property template list to show [optional] when nullable is selected
  - Fixed property to show numeric precision when applicable
  - Fixed canvas reload/reposition issue when adding or removing properties to a class
  - Fixed composition handles (allOf/oneOf/anyOf) not repositioning when ClassNode height changes due to property list changes
  - Fixed auto-layout to treat groups as single units - grouped classes maintain their exact relative positions within the group
  - Fixed group member nodes jumping after auto-layout when dragging the group - properly synchronizes group position reference
  - Fixed response nodes in path canvas - clicking a response node now shows the ResponsePropertiesPanel with existing description loaded for editing
  - Fixed JSON Schema refs, was #/components/schemas, but this needs to be #/$defs according to the spec
  - Fixed Canvas Layout option so that Load is only available if a previous layout has been saved
  - Fixed issue with system theming not applying properly on initial load
  - Fixed edges in canvas so they don't overlap over the top of classes, but go underneath
  - Fixes theming issues with system mode (following light/dark modes)
  - Fixed template properties to indicate optional when type includes null
  - Fixed Properties Forms layouts to match design of Class Forms (separate general and advanced properties)
  - Compacted the look and feel of the Class nodes to reduce visual clutter and improve readability
  - Class Template Library now shows the schema preview
  - Properties and Class Template Form now includes a "close" button
  - Properties now allow multiple properties to be added without closing the form
  - Properties Template Form now shows the inline properties when an "object" type is selected
  - Condensed property flags into a compact horizontal layout
  - Class node styling changes were not persisting properly, this is now fixed
  - Removed Level of Detail settings, was causing confusion
- Code Generation:
  - Added GraphQL - added support for input types, enums, and interfaces
  - Added SQL DDL - added support for indexes, constraints, and foreign keys
  - Added AsyncAPI 3.0.0 - generate event-driven API specifications with channels, messages, operations, and schema definitions for Kafka, AMQP, MQTT, WebSocket, and HTTP protocols

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: January 15, 2026*


# Objectified 03-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

Improvements:
- Canvas: Expand, Collapse, Search, View Mode, and Tags live in a left slide-out drawer opened from the **Tools** control in the upper-left (#842)
- Canvas: group edit controls (style, color, rename, export, duplicate, bulk, delete) sit in a compact floating card above the frame (`-top-6`, `right: -2px`) so the title row stays readable on hover or when selected (#859)
- Studio: the amber “differs from defaults” hint appears in the dialog header next to the title for class and property editors so it stays visible (#856)
- Canvas: class node color, icon, hide, and delete controls appear in a compact bar attached to the upper-right outside the card while hovering (or while a popover is open) (#853)
- Canvas: class node property rows show the type chip by default; hovering a row swaps it for edit and remove actions on the right (#854)
- Canvas: nested groups up to three levels — drag group frames into each other, breadcrumb navigation and drill-in control, nested export/bulk/delete-all include descendant groups (#155)
- Canvas: group toolbar — export the group’s schemas as OpenAPI JSON or YAML (with referenced types), duplicate the whole group into a new frame, and apply bulk class updates (description prefix/suffix, tag, top-level read-only) (#156)
- Canvas: groups can collapse to a compact title bar (chevron); Alt+Shift+[ / ] collapse or expand all; your choices are remembered per version (#154)
- Canvas: presentation mode — save viewport slides, present in fullscreen with speaker notes, timer, and keyboard controls (#517)
- Canvas: layout auto-save uses a steady timer while edits are pending so saves occur every 30 seconds (or your chosen interval) without resetting on each move (#315)
- Canvas: schema timeline panel shows class count, relationships, and complexity across project versions (#323)
- Canvas: named layout saves store a PNG snapshot for thumbnail preview in the layout menu
- Canvas: export and import canvas layouts as versioned JSON (share across versions and projects)
- Canvas: layout import and named layout load restore edge handle routing when saved edge IDs match the canvas (#316)

Bug Fixes:
- Studio: deleting a group from the sidebar now removes it from the list and persists like canvas delete (nested frames, layout save) (#849)
- Studio: property editor XML section and object min/max properties use the same card, typography, and helper text patterns as the class form (#852)
- Canvas: empty group frames from drag-to-canvas now appear (visibility treated empty leaf groups as visible) (#848)
- Import now handles paths properly
- Improved Markdown rendering
- Improved layout of primitives form
- Improved layout of class form
- Improved layout of profile page
- Improved handling of light/dark system theme settings
- Conversion of forms to use modern components
- System-wide clean up of modern UI
- Publishing a version can select the visibility at the time of publish
- Improved published view page
  - Now displays the different types of object representations as a submenu (OpenAPI, Arazzo, JSON)
  - Now applies API Key when viewing private published pages
  - Fixes REST service to apply API Key on retrieval
- Improved layout of the linked accounts page
  - Linked accounts page is slightly wider matching those of other dashboard layouts
  - Provider cards now show PAT hints so users can match the PATs that were assigned
- Canvas: optional default named layout on open — save a personal or team (tenant) default per version
- Improvements in the canvas
  - Class node customization form is slightly more compact
  - Class and Properties forms now have tabs instead of button groupings
  - Export page now uses stylized monaco-editor to display export data
  - Class and Properties edit forms now display changed elements in more obvious colored background sections
  - Removal of groups and group classes are now working properly
  - Class nodes show the name of the singular reference - arrays were already correct
  - Class form was displaying a prompt for dependent schemas - this has been corrected
  - Class template library form is wider to show better detail
  - Class nodes show ghost preview of node while dragging
  - Property template button now appears properly when in dark mode
  - Property template form is also now wider to show better detail
  - Renaming a property no longer rearranges the entire canvas
  - Adding a reference to a class no longer rearranges the entire canvas
  - Now handles multiple saved layouts per version
  - Named layout saves keep version history with restore (up to 50 prior states per layout)
  - Adds auto-save layout changes every 30 seconds (configurable)
  - Adds the ability to save custom layout names per version
  - Adds view mode to show and hide all nodes except selected
    - Adds hiding by criteria
  - View Mode can show hidden nodes as semi-transparent (node ghosts) instead of removing them
  - Introduces the ability to hide/show individual nodes
  - Canvas **View mode** menu includes **Show all nodes** to restore full visibility after manual hides, filters, ghosts, isolate selection, or focus mode
- Project form:
  - Now includes the metadata section
  - Moved AI Assistant here
  - Shows creation metadata when editing

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: March 1, 2026*


# Objectified 05-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## UI
- Branch workflow is its own button in the canvas now, and compacted to fit most functionality that's in Versions now.
- Compacted the trending view in the projects page in the dashboard.
- Moved the add, import, and template buttons to the bottom of the classes and properties sidebar list so they don't obscure the lists.
- Added bottom header to show status of the canvas editor screens.
- Gitlike functionality will be redesigned; currently not working as expected, and will be perfected in a later release.
- Clicking on the warning chevron now eases in/out the warning for the project for sunset indicators.
- Clicking the tools chevron in the designer canvas now animates instead of just (dis)appearing.
- Layout form now looks associated with the button from which it appears.
- Clicking outside the layout form now dismisses it from the canvas.
- Added the ability to decide whether or not to save the layout image on a layout persist.
- Corrects schema metrics display when the schema list is empty.
- Corrects opacity of overlay buttons in canvas.

---

## Studio AI
- Added the Studio AI chatbot launcher and panel: a floating bubble in the bottom right of the canvas opens a slide-out panel with full-screen mode, toggled with `Cmd+Shift+A` / `Ctrl+Shift+A`.
- Filled out the Studio AI chat surface to the design guidelines: distinct user/assistant bubbles, typing indicator, markdown rendering, syntax-highlighted code blocks with a copy button, regenerate / thumbs up / thumbs down message actions, and a one-click import button when an assistant reply contains an OpenAPI spec in a ```json``` block.
- The Studio AI chatbot is now context-aware: each message you send carries a snapshot of your current project, version, classes, reusable properties, and canvas selection, and a "Sharing context" chip in the panel lets you inspect exactly what the assistant can see.
- The Studio AI chatbot now handles multi-turn conversations: follow-up prompts like "add a phone field", "remove priceCents", "make name required", "rename id to productId", "make it more like Stripe Charges", or simple clarification questions are recognized as edits to the previous reply, and the refined OpenAPI spec is re-shipped so you can keep iterating without restarting the thread.
- The Studio AI chatbot now persists conversations per project and version: a new toolbar above the chat surfaces "New", "History", "Export", and "Clear" actions, the history view lets you browse and search every saved thread, exporting downloads the active conversation as a markdown file, and the chat automatically restores your most recent thread when you reopen the panel.

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: April 22, 2026*


# Objectified 06-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## MCP
- MCP service is now live

## Import
- Race condition fixed in 3.0.1 specification imports
- Import supports Swagger 2.0 format
- Adds the ability to import multiple versions of the same project 

## Repositories
- Recent imports from repository metrics are now displayed
- Imports tab now shows the previously imported files from the repository
- Files in the imports tab now leads to the original file that was imported

## Export

## Studio
- Studio AI chat empty state offers example prompts for schema and API generation (#268).
- Studio AI chat treats plain-language domain descriptions (and similar phrasing) as requests to draft OpenAPI `components/schemas`, including when Ollama is connected (#267).
- AI chatbot lists Ollama models from your server and lets you pick which model answers each conversation (falls back to the offline assistant when Ollama is unavailable).
- Studio chatbot remembers your preferred Ollama tag per project (and per tenant), with an optional control to set a tenant-wide default when you are inside a project.
- Studio AI chat streams Ollama replies over SSE so assistant text appears incrementally as the model generates.
- Studio AI chat shows live token usage (estimated while streaming, then Ollama-reported counts when each reply finishes).
- Studio AI chat includes **Stop** while a reply is generating so you can cancel mid-stream; partial text is kept when the model had already streamed content.
- Studio AI chat shows an indeterminate progress bar while the assistant is generating a reply.
- Identical Ollama chat requests are served from an in-memory exact-match cache when a prior reply completed successfully, reducing load on your model server (disable with `OLLAMA_CHAT_CACHE_DISABLED`).
- When a request is not an exact key match, the chat route can still reuse a prior reply if the same model/task/context applies and Ollama returns a similar enough embedding for the message payload (cosine threshold, default 0.92); disable with `OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED` or tune with `OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD` (uses the same Ollama embed endpoint as snapshot vectorization).
- Ollama chat cache keys include a fingerprint of the version’s class and property schemas when you use the Studio AI chatbot, so edits to OpenAPI/JSON Schema state do not reuse stale cached replies.
- Studio AI chat **Preview changes** opens a modal with a formatted OpenAPI summary and JSON before **Apply import** runs the import action (cancel returns you to the chat with no import).
- Assistant replies that include phrases such as **Create this class**, **Add these properties**, **Apply to current class**, or **Copy to clipboard** (with a JSON or YAML code block) show quick-action buttons: new class, open the selected class for editing, or copy the fenced payload.
- **Create this class** opens a preview before continuing (#528); the preview shows class metadata and the generated schema as formatted **JSON Schema** (#529). Each property is summarized with a **suggested JSON Schema type** (including refs and arrays) (#530). Confirming opens Add Class in AI mode with that reply seeded. Create Class with AI uses the same preview via **Preview & create**.

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: May 4, 2026*


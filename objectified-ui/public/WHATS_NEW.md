# Objectified 06-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## MCP
- MCP service is now live

## CLI
- **`objectified-cli`**: `objectified versions list <project>` lists schema revisions from `GET /v1/versions/{tenant}/{project_id}` with tags merged from version tags, `--state` / `--limit` / `--all` / `--sort` / `--reverse`, frozen revisions marked (`❄` with color or `[frozen]` with `--no-color`), and `--json` for the filtered slice (#3208).
- **`objectified-cli`**: `objectified projects create` adds projects via `POST /v1/projects/{tenant_slug}`—interactive `@inquirer/prompts` wizard on a TTY, or CI flags (`--name`, `--slug`, `--description`, `--domain`, `--visibility`, `--yes`); `--from-file` JSON/YAML validated with JSON Schema; `--dry-run` prints the POST body; domain ids validated against cached `GET …/domains` (fallback catalog); slug format + pre-create uniqueness (exit **6** conflict, **7** validation) (#3204).
- **`objectified-cli`**: `objectified projects show <slug-or-id>` resolves UUID vs slug (`GET /v1/projects/{tenant}/by-slug/{slug}` or `GET /v1/projects/{tenant}/{id}`), prints rich detail with version/tag summaries and up to **10** workflow-audit rows; `--json` returns the project object plus `activity[]` (#3203).
- **`objectified-cli`**: `objectified projects list` calls `GET /v1/projects/{tenant_slug}` with an 80-column table (slug, name, domain, versions, latest published), `--limit` / `--all`, `--sort`, `--filter`, `--search`, `--columns`, `--include-deleted`, and top-level `--json` array output (#3202).
- **`objectified-cli`**: `objectified tenants list` and `objectified tenants info <slug>` call `GET /v1/tenants/me` and `GET /v1/tenants/{slug}` (REST support in `objectified-rest`); stable `--json`; active profile tenant marker; `--limit` / `--offset` pagination for large tenant lists (#3198).
- **`objectified-cli`**: `objectified tenants use <slug>` validates access with `HEAD /v1/tenants/{slug}`, writes `tenant_slug` under `profile.<name>` in config.toml, supports `--clear`, global `--tenant` (over `OBJECTIFIED_TENANT` then config), exit **4**/**5** with hints and typo suggestions (#3199).
- **`objectified-cli`**: secure credential storage — `keytar` OS keychain first, AES-256-GCM encrypted file fallback (`credentials.enc`) when libsecret/keychain is missing; profile-scoped vault merge/delete; `auth logout` clears both stores; optional `expires_at` / `tenant_slug` on stored OAuth; documented threat model in `objectified-cli/docs/cli-security.md`; CI builds `keytar` on Linux, macOS, and Windows (#3197).
- **`objectified-cli`**: `objectified auth status` / `whoami` calls `GET /v1/auth/cli/whoami` for tenant, user, plan, and token metadata; stable `--json` schema; stored OAuth silently refreshes on 401 before retrying whoami (#3196).
- **`objectified-cli`**: API-key auth (`--api-key`, `OBJECTIFIED_API_KEY`, `--api-key-file`), keychain storage via `auth login --api-key`, `auth status`, API-key precedence over OAuth, redacted verbose logging, and exit **4** for rejected credentials on authenticated requests (#3195).
- **`objectified-cli`**: `objectified auth login` (PKCE loopback + browser or `--no-browser` / headless stdin code) and `objectified auth logout` (`--all-profiles`); tokens stored per profile in the OS keychain via `keytar`, bearer hydration for API calls (#3194).
- **`objectified-cli`**: `objectified completion install|show|uninstall` for bash, zsh, fish, and PowerShell; manifest-backed static completions plus REST-backed suggestions cached five minutes under `~/.cache/objectified/completion/` (#3193).
- **`objectified-cli`**: rich `--help` (≥2 examples per command, flag groups **COMMON** / **OUTPUT** / **AUTH**, **SEE ALSO** links), `objectified docs` topic browser + prose topics, troff **man** pages under `man/man1/`, `oclif readme`-synced **README.md**, and CI guard for generated artifacts (#3192).
- **`objectified-cli`**: shared error layer (`ObjectifiedCliError`, documented exit codes via `objectified docs errors`, stderr template with hints + request-id, `--verbose` / `OBJECTIFIED_DEBUG=1` stacks only), Levenshtein did-you-mean for unknown commands, HTTP status → exit-code mapping, and fetch retries per idempotent vs non-idempotent verbs (#3191).
- **`objectified-cli`**: OpenAPI codegen (`yarn codegen` → `src/generated/`), typed `@hey-api/client-fetch` SDK, `lib/client.ts` wrapper (retries, `Retry-After`, 401 hook, request IDs), ESLint single-import guard, `codegen:check` in tests, and `projects list` backed by the generated client (#3190).
- New **`objectified-cli`** package (oclif v4) adds the `objectified` binary scaffold with `hello`, `--version`, and `--help` (#3186).
- **`objectified-cli`**: shared global flags on `BaseCommand` (`--base-url`, `--profile`, `--api-key`, `--config`, `--json`, `--no-color`, `--quiet`, `--verbose`), TOML profile resolution, root help text for precedence rules, argv normalization for globals-before-subcommand, and stub `projects list` (#3187).
- **`objectified-cli`**: TOML config with XDG / Windows paths, `default_profile`, `objectified config path|get|set|list`, auto-created `config.toml` (`0600` on Unix), strict profile validation, env-based API keys only, and tenant slug from config/env (#3188).
- **`objectified-cli`**: shared output layer (`lib/output.ts`) with `this.output` on `BaseCommand` — tables (`cli-table3`), stable sorted JSON/YAML, ora spinners, stderr warnings/errors, and TTY / `--json` / `--quiet` / `--no-color` / `LANG=C` behavior; Vitest snapshots cover render modes (#3189).

## Import
- Race condition fixed in 3.0.1 specification imports
- Import supports Swagger 2.0 format
- Adds the ability to import multiple versions of the same project 

## Repositories
- Recent imports from repository metrics are now displayed
- Imports tab now shows the previously imported files from the repository
- Files in the imports tab now leads to the original file that was imported

## UI
- Adds the ability to view projects that were deleted (show deleted toggle)
- Introduces undelete for soft deleted projects

## Export

## Dashboard
- **Published Versions**: opening a **private** revision’s OpenAPI, Swagger UI, Arazzo, or JSON Schema link **reuses an API key saved in this browser** for the current tenant when present, so you are not prompted every time; otherwise the key dialog appears, with optional **remember** and a **clear saved key** control (#3132).
- **Versions** timeline table (**version**, **revision / changelog**, **status**, **created by**, **created**) is **sortable** from the column headers: click to sort ascending, click again to toggle descending (#2983).
- **Projects** table columns (**name**, **description**, **quality trend**, **status**, **creator**, **created**, **updated**) are **sortable** from the header: click to sort ascending, click again to toggle descending (#2982).
- Projects list includes a **Show deleted** switch; when on, soft-deleted projects appear with a **Deleted** badge and **Restore** or **permanent delete** in the row menu (#2981).

## Studio
- **Schema Metrics** includes **Canvas layout intelligence**: analyzes the live ReactFlow graph (strongly connected components, hubs, hierarchy roots, weakly connected islands), recommends **Top→Bottom** vs **Left→Right** auto-layout, adds matching **Suggestions**, and optional **AI narrative** via Ollama (`canvas_layout_recommendations`) (#623).
- Property **Examples** (Advanced Constraints) supports **Generate example with AI** (Ollama): adds a realistic JSON example from the property name, optional description, schema snapshot, and nested member hints on class properties (#622).
- **Paths** operation **Docs** tab supports **Generate summary & description** (Ollama): drafts OpenAPI **summary** and Markdown **description** from the HTTP method, path template, path parameters, and optional operationId (#621).
- **Class description** in **Edit class** supports **Generate with AI** (Ollama): drafts short documentation from the class name, linked member properties (names, types, optional member descriptions), and composition (allOf / anyOf / oneOf) (#620).
- **Property description** fields support **Generate with AI** (Ollama): drafts short documentation from the property name and JSON Schema type — in **Add/Edit Property** (sidebar library) and **Edit class property** on the canvas (#619).
- Studio AI **best-practice tips** now include **performance** hints (caching, queues, pagination, search projections, bulk I/O, media payloads, feeds/timelines) when matching names appear on classes or reusable properties (#618).
- **Studio AI chat** surfaces **domain-aware best-practice tips** from the project’s **domain category** (set on the project in the dashboard) and from **auth / multi-tenant style class names**; tips appear in the chat empty state, the **Sharing context** popover, the prompt preamble sent to the model, and the offline demo’s **Improvement suggestions** (#615).
- Each **domain category** now contributes **several industry-specific modeling patterns** (not a single generic line), for example inventory and checkout idempotency for e-commerce and ledger-style money movement for finance (#616).
- Studio AI **best-practice tips** now include **security-hardening** hints from domain (payment card handling, PHI encryption), auth-related class names, secret- or password-like property names, and webhook-oriented classes (#617).
- **Schema Metrics** adds a **technical debt** score (0–100, higher = more remediation pressure): weighted documentation/naming gaps, schema and dependency-graph load, conditional branching, cycles, chain depth, mean cognitive load, isolated classes, and wide-class pressure—with a factor breakdown in the panel, **AI metrics digest**, **version score compare**, **timeline PDF**, and **PDF score report** (#614).
- **Schema Metrics** adds a **maintainability index** (0–100, higher = easier to evolve): composite from documentation, naming, inverted schema and dependency-graph complexity, mean cognitive load, and class-size pressure—with a factor breakdown in the panel, **AI metrics digest**, **version score compare**, and **PDF score report** (#613).
- **Schema Metrics** counts **conditional schema cyclomatic** (#612): if/then/else decision points are summed from class and property JSON Schemas, fed into the **aggregate complexity** breakdown, **per-class cognitive** score (new If column), **AI metrics digest**, **version score compare**, and **PDF score report**.
- **Schema Metrics** adds **dependency graph complexity** (0–100 on property references and class-level allOf/anyOf/oneOf only): headline score with factor breakdown in the panel, **AI metrics digest**, and **PDF score report** (#611).
- **Schema Metrics** includes **cognitive complexity per class** (props plus weighted outgoing dependency edges; anyOf/oneOf count double) and feeds the same scores into the **AI improvement suggestions** metrics digest (#610).
- **AI improvement suggestions** supports **bulk apply**: when the model returns structured **apply** targets (empty class or property descriptions), select rows and **Apply selected** to fill documentation on the canvas in one pass (#256).
- **AI improvement suggestions** shows an optional **estimated overall score impact** (points on the 0–100 Studio composite) per row when the model supplies it; the metrics digest includes the **current overall score** so estimates stay grounded (#255).
- **AI improvement suggestions** (Schema Metrics **lightbulb**) now labels each item with **effort** (quick win, standard, larger effort), **sorts quick wins to the top**, and adds an **Effort** line when you copy a row (#254).
- **Schema Metrics** panel includes a **lightbulb** control that opens **AI improvement suggestions**: Ollama reads live canvas metrics (documentation %, naming compliance, complexity, samples of gaps) and returns a structured, copy-friendly list of actionable ideas (#253).
- **Add Property** and **Edit Property** include **Analyze** on the Basics step (advanced Form view includes it in Basics): opens the same **AI property suggestions** dialog as the sidebar robot control (#276).
- The **AI property suggestions** dialog opens when you start **Add Class** (or **Create this class** from chat), when the new **class name** reaches two characters, after saving your **first** or **third** property in a single-property add (not during bulk **Add all suggested**), from **AI suggest properties** in the sidebar, or when chat includes **Open AI property suggestions** (#275).
- **Suggest properties with AI** names the bulk queue action **Add all suggested** (clearer next to **Open in Add Property**) (#274).
- **AI suggest properties** and **Suggest types with AI** list each row with a short **explanation** (model `thinking`, optional `explanation` / `rationale`, or description fallback) so you can scan rationales before opening the detail panel (#273).
- **Add Property** includes **Suggest types with AI** (when Ollama is configured): enter a property name, ask for alternatives (formats, refs, domain hints such as FHIR), **edit the schema JSON** if you want tweaks, then **Apply to form** to load it (#269, #272).
- Properties sidebar includes an **AI suggest properties** control (robot): describe what you need, review thinking and summary, **pick a suggestion from the list**, use **Add all suggested** or **Reject all** (or reject individual rows), **edit name, description, and schema** in the detail panel, then **Open in Add Property** or **Add all suggested** to step through Add Property for each remaining suggestion (#609, #270, #271, #272, #274).
- Studio AI chat schema refinements infer JSON Schema type and common constraints from well-known property names (`email`, `createdAt`, `age`, `price`, `isActive`) when you add a field without specifying a type; the class-skeleton Ollama prompt uses the same conventions (#277).
- Chat refinement inference now adds typical validation hints from names—string lengths, numeric bounds, regex patterns, and marking `id` as required when added without a type (#278).
- Studio AI assistant (live Ollama and offline demo) appends an **Improvement suggestions** section after OpenAPI sketches—actionable bullets such as pagination, `allOf` inheritance, discriminators, splitting large schemas, and standard error shapes (#495).
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
- **Create this class** opens a preview before continuing (#528); the preview shows class metadata and the generated schema as formatted **JSON Schema** (#529). Each property is summarized with a **suggested JSON Schema type** (including refs and arrays) (#530). **Relationships** lists `$ref` links inferred from the schema and optional **Suggested relationships** bullets from the assistant (#531). **Ask assistant to refine** in that preview sends follow-ups (for example add a phone field, make email required, password length rules, audit timestamps); the chat records the turn and refreshes the preview when the model returns a valid class JSON (#532). Confirming opens Add Class in AI mode with that reply seeded. Create Class with AI uses the same preview via **Preview & create**.

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: May 5, 2026*


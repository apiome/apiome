# Apiome 08-2026 RC5

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

- Large lists:
  - **Catalog** and the **Versions** table show 50 rows at a time, with *Showing 1–50 of 1000 items* and page buttons in the foot. A catalog of a thousand items now opens and filters as quickly as one of fifty
- API Formats:
  - Hardening import functionality
  - Adds formats:
    - MCP import and export
    - Kong import and export
    - Arazzo 1.1 import and export
    - AsyncAPI 2.x export
    - OData v2/v3 import and export
    - WSDL 2.0 import and export
    - Avro IDL (`.avdl`) import and export
    - Swagger 1.2 import
    - Postman Collection v2.0 import
    - Natural / ADABAS DDM import — a DDM listing becomes a record with every field's format and byte length and the assumptions those lengths rest on; multiple-value fields and periodic groups become arrays bounded by the occurrence counts a Natural view in the same upload states, and descriptors and superdescriptors become declared key metadata with their source byte ranges
    - IMS DBD and PSB import — an IMS database description becomes nested records rebuilt from each segment's `PARENT`, with every field at its byte offset and the assumptions those positions rest on; a program specification block becomes the program's view, and each `PROCOPT` its declared access profile (get, insert, replace, delete, path); a `PARENT` that names no segment is refused rather than re-rooted
    - PL/I structure import — `DCL` structures and their `%INCLUDE` members become records with a byte-accurate storage map (offsets, lengths, alignment padding, `UNION` overlays) and the assumptions those byte counts rest on; a member missing from the upload marks the record it sits in partial instead of leaving it silently short
    - VSAM and CICS BMS import — IDCAMS cluster definitions and LISTCAT listings become records with their primary and alternate keys at their offsets, and BMS mapsets become screen records whose fields keep their row, column, picture and attributes; the record layout a cluster cannot describe is listed in the coverage ledger
    - Hoppscotch and Thunder Client export — export any HTTP API as a Hoppscotch or Thunder Client collection plus its environment: one saved request per operation, foldered by tag, against a baseUrl variable; credentials are written as empty placeholder variables, never values, and a collection exported from either client imports back to the same operations
    - SoapUI / ReadyAPI project import — a SoapUI or ReadyAPI project becomes one API: WSDL interfaces are read by the WSDL importer (from the project's cached copy or a WSDL uploaded beside it), REST interfaces become operations with inferred schemas, and test suites are kept as declared tests shown on the item's Overview; saved credentials are never kept
    - Thunder Client collection import — a VS Code Thunder Client collection and its environment files become one REST API: folders as operation groups, requests as operations with inferred body schemas, `{{baseUrl}}` as a server variable; saved credentials are never kept, and tests and pre-request steps are listed in the coverage ledger
    - Hoppscotch collection import — a collection and its environment files become one REST API: folders as operation groups, requests as operations with inferred body schemas, `<<baseUrl>>` as a server variable; saved credentials are never kept, and scripts are listed in the coverage ledger
    - AWS API Gateway (REST and HTTP API exports) import
    - Azure API Management (definitions and policies) import
    - Apigee proxy bundle import
    - Envoy xDS route configuration and Istio VirtualService import (service-mesh routes, labelled inferred)
    - Traefik, nginx, HAProxy, Consul and Tyk configuration import (reverse-proxy routes, labelled inferred; nginx read through a documented directive subset)
    - TypeScript types import — the exported interfaces, type aliases and enums of a `.ts` / `.d.ts` module or module set, read by the TypeScript compiler; conditional, mapped and template-literal types are listed as parsing limits, never turned into `any`
    - Zod schemas import — a module's exported Zod schemas with their validation constraints (lengths, patterns, formats, bounds), run in a sandbox with no network and a time limit; `refine`, `transform` and `brand` are listed in the coverage ledger
    - tRPC router import — procedures as query, mutation and subscription operations, nested routers as operation groups, and Zod inputs and outputs with their constraints
    - Pydantic models import — models, `Field` constraints, enums and unions from a Python module, read as text so the module is never run; `create_model` and validators are listed in the coverage ledger
    - CUE, Pkl and Dhall import — typed configuration schemas with their constraints, evaluated by each language's own tool in a sandbox with no network; CUE comprehensions, Pkl late binding and Dhall functions are listed in the coverage ledger
    - LwM2M / IPSO and Matter import — device models become catalog items: LwM2M objects as data schemas with units, ranges and read/write access on each resource, executable resources as operations; Matter clusters as attributes, commands and events, and a device type as the clusters it includes; object links, undeclared standard types and clusters outside the upload are listed in the coverage ledger
    - SHACL, OWL / RDFS and JSON-LD import — shapes graphs, ontologies and JSON-LD contexts become data schemas: shapes and classes as records with inheritance, cardinality and datatype constraints, JSON-LD terms with their IRIs kept as provenance; OWL's open-world inference and SHACL shape cycles are listed in the coverage ledger, and imports outside the upload are refused, never fetched
    - ROS 2 interfaces import — `.msg`, `.srv` and `.action` files, or a whole interface package, become records, request/response operations and action feedback channels; bounded strings and arrays keep their limits, and references to packages outside the upload are listed in the coverage ledger
    - MQTT Sparkplug B import — payloads (NBIRTH, DBIRTH, DDATA …) or a topic-namespace description become MQTT channels with metrics as the message schema; DATA payloads imported beside their BIRTH get their metric names from its aliases, and payload-only imports are labelled inferred
    - OPC UA NodeSet2 import — an industrial information model's object, variable and data types, methods (as operations) and references, with its namespaces and model versions; a companion model imports beside the model that requires it, and the address space stays under Format details
    - Declared, inferred and synthesized — every catalog item labels what its source stated and what Apiome inferred (from example bodies, sample requests or route tables) or synthesized (names for anonymous types); the Overview badges each inferred entity with its evidence, a Provenance filter narrows to one kind, and the `provenance.inferred-construct-ratio` lint rule reports the inferred share — set it to error in a style guide to keep inferred sources from being published
    - Gateway export to Envoy xDS, Istio, Traefik, AWS API Gateway, Azure API Management and Apigee — six new Export Studio cards under REST & HTTP, each checked against its product's rules; **Push back** now works for AWS, Azure APIM and Apigee gateway configs
    - A2A Agent Card import (skills and tags, live discovery from `/.well-known/agent-card.json`)
    - ACP agent manifest import (agents and capabilities, live discovery from a server's `/agents`)
    - Agentic-web site manifest import (agents.json, agent.json, agents.txt, llms.txt): endpoints, actions, payment layers and the A2A / ACP / MCP descriptors to discover next
    - Registry crawl connectors: point a connector at an A2A agent registry, a CNCF xRegistry or a FHIR server, and every artifact becomes its own catalog item, re-crawled incrementally
    - CNCF xRegistry import: CloudEvents schema groups, message definitions and endpoints (MQTT, AMQP, Kafka, NATS, HTTP) as one event catalog entry; registry crawls now bring in message groups and endpoints too
    - Protobuf editions 2023/2024 normalization parity
    - RELAX NG import
    - DTD import
    - Schematron import
    - CDDL (RFC-8610) import and export
    - Apache Arrow/Flight import
    - Open Data Contract Standard (ODCS v3.1) import and export
    - Kafka Connect schema import and export
    - dbt model and semantic-manifest import
    - SQL DDL import
    - NCPDP SCRIPT and Telecom import (NewRx, RxFill, RxChangeRequest and other SCRIPT transactions; Telecommunication D.0 B1/B2/B3 claims): each message's transaction type detected and recorded, Telecom segments and fields as native structure with the declared versus observed transaction count, and the capability panel naming the supported versions and stating no implementation guide was consulted
    - FIX Orchestra import: a repository's messages become record types, code sets enums and groups lists, with `presence` mapped to optionality and constraints (`forbidden` kept as a declared constraint, never dropped), repositories split with XInclude imported as one set, and an Orchestra item suggested as a link for the FIX message items of the same message type
    - Format details: every EDI and vertical-messaging format (X12, EDIFACT, TRADACOMS, IDoc, SWIFT MT, HL7 v3 / CDA, NACHA, DICOM, NCPDP, FIX Orchestra) shows a **No implementation guide was consulted** banner naming the syntax read, the guides not applied and the claims recorded as the sender's
    - DICOM import (Part 10 files and DICOM JSON metadata): SOP classes, attributes keyed by tag with their VR, nested sequences and Structured Report content trees; pixel data is never read, stored or analysed, and no patient value is kept at the default value-visibility policy
    - NACHA ACH import (PPD, CCD, WEB, TEL batches with addenda): batches and entries as native structure, batch and file control totals shown as declared versus observed; SEPA pain.001, pain.008 and pacs.008 files routed to the ISO 20022 importer with the message id and SEPA profile recorded
    - TRADACOMS import (order, invoice, delivery and acknowledgment files) and EDI dialect profiles: EANCOM and ODETTE/VDA interchanges recognised on the EDIFACT importer, the applied profile shown in provenance and the capability panel
    - HL7 v3 / CDA import (CCD, discharge summary, other C-CDA documents): header and section hierarchy, RIM data types as canonical types, template ids recorded as asserted claims marked not validated
    - SWIFT MT import (MT103, MT202 COV, MT940, MT942): blocks and fields with option letters and code words, MT↔MX correspondence shown as a documented note
    - SAP IDoc import and export: flat-file (EDI_DC40) and XML IDocs, segment definitions for flat fields, the hierarchy from segment numbers, IDoc XML export
    - UN/EDIFACT import (ORDERS, INVOIC, DESADV …): `UNA` delimiters honoured, the whole interchange on the Format details tab, declared versus observed control counts
  - Linting rule pack updates for scoring new import types
    - Data contracts are now scored on their own terms: ownership, service levels, freshness,
      retention, column documentation, row identity, classification and declared quality checks
  - Added pills to supported format list to show the source and type that the API format provides
  - Every format now declares which versions it reads and writes, and which version an export produces by default
- CLI:
  - Install the `apiome` command line on Linux or macOS with one line: `curl -fsSL https://get.apiome.dev | sh` — installs `apiome` system-wide into `/usr/bin` (`/usr/local/bin` on macOS), or into `~/.local/bin` with `--user` (re-run to upgrade; `--uninstall` to remove)
  - `apiome login` signs the CLI in through your browser: approve the code on Apiome's **/cli/login** page, choose a workspace, and the CLI saves a 14-day API key for it — no copying keys out of the app; `apiome logout` revokes it
  - `apiome projects update <slug-or-id>` changes a project's name, slug (`--rename`, with confirmation), description or domain — or applies an edited `projects get --json` dump (`--from-file`); `--dry-run` shows the diff, and a project changed by someone else in the meantime is never overwritten (exit 6)
  - `apiome projects delete <slug-or-id>` shows what will be removed, then deletes the project permanently once you type its slug — or archives it restorably with `--archive`; a project with published versions is refused unless `--force` (exit 6)
  - `apiome projects export <slug-or-id>` writes a whole project — versions, classes, paths, tags and migration plans — as one deterministic JSON or YAML document (`--gzip`, `--versions`, `--include`/`--exclude`) for backups, environment diffs and migrations
  - `apiome versions fork <project> <version> --into <project> --to <x.y.z>` forks a version into another project with its lineage recorded — `--dry-run` shows the classes and properties it would copy
  - `apiome versions unpublish <project> <version> --reason '…'` takes a release back: it previews what will happen, asks you to type the version, moves tags such as `latest` back to the previous published version, notifies webhook subscribers and records the reason (shown by `versions get`); the only published version is refused unless `--force` (exit 6)
  - `apiome versions freeze <project> <version>` pins a published version's OpenAPI document byte-for-byte — `/v1/schema` keeps serving that exact snapshot (SHA-256 shown) even when classes change later; `--unfreeze` is refused once someone has downloaded it, unless an administrator forces it
  - `apiome versions compatibility <project>` is a CI gate for breaking changes between two versions (default: latest vs the previous published one) — exit 6 on a breaking change, 8 when the server can't answer; `--allow-removals`, `--ignore <rule>`, `--json`, and `--sarif` for GitHub code scanning
  - `apiome versions delete <project> <version>` removes a draft once you type its version; tags pointing at it are listed and need `--detach-tags`, and a published or frozen version needs `--force` (which unpublishes and unfreezes it first, with `--reason`)
  - `apiome tags list <project>` and `apiome tags show <project> <tag>` list a project's version tags — the version each points to, its channel, when it was updated and who created it
  - `apiome tags create <project> <tag> --version <version>` points a new version tag at a version (`--description`, `--from-file`); a name that already exists exits 6
  - `apiome tags update <project> <tag> --version <version>` moves a tag ("promote 2.1.0 to stable") after showing who may be affected — mock traffic, frozen-snapshot downloads and other tags on the current version; `--dry-run`, `--description`, `--yes`
  - `apiome tags delete <project> <tag>` removes a version tag once you type its name; the version it points to is left alone
  - `apiome properties list <project>` shows each property's type, whether it is required and which classes use it — filter with `--type`, `--search` and `--unused`
  - `apiome properties show <project> <property>` shows one property's type, constraints, examples and description, and every class attribute that uses it; a mistyped name suggests the closest ones
  - `apiome properties create <project>` adds a property from a primitive — answer the prompts (type part of a primitive's name to search) or pass `--name`, `--primitive`, `--description` and `--example`, or `--from-file` with JSON or YAML; examples are checked against the primitive first, and every problem is listed by field (exit 7)
  - `apiome properties update <project> <property>` renames a property, changes its description or examples, re-copies its schema from another primitive (refused while classes require it, unless `--allow-breaking`), or marks it required on every class that uses it — with a `--dry-run` diff, and `--from-file` that refuses to overwrite a newer edit
  - `apiome properties delete <project> <property>` checks which classes use a property first — unused, you type its name to delete it; in use, it lists the class attributes and stops, unless `--force --yes` removes them and deletes the property in one step (never in published versions)
  - `apiome properties copy <project> <names> --to <project>` reuses property definitions in another project of the same tenant — one, several (comma-separated) or `--all`, with `--rename`, `--update` to overwrite and `--dry-run`; nothing is written if a schema refers to a primitive the tenant does not have
  - `apiome classes list <project> <version>` lists a version's classes with their property count, tags and description — filter with `--tag` and `--search`, or add `--with-properties` to see every class's properties
  - `apiome classes create <project> <version>` adds a class to a draft version with its properties (each optional or required) and tags — answer the prompts, or pass `--name`, `--property amount:required` and `--tag`, or `--from-file` with JSON or YAML; missing tags are created, and a half-made class is removed again if a step fails
  - `apiome schema arazzo <tenant>/<project>/<version>` downloads a published version's Arazzo workflows as YAML (or `--format json`), the whole bundle or one class with `--class`; `--expect-sha256` refuses to write a document whose bytes changed
  - `apiome schema json <tenant>/<project>/<version>` downloads a published version's JSON Schema — the whole bundle or one class with `--class`, ready to pipe into a code generator; same `--format`, `--output` and `--expect-sha256` flags as `schema arazzo`, JSON by default
  - `apiome schema diff <tenant>/<project> <v1> <v2>` shows which paths, classes and properties changed between two published versions — a summary, a unified diff, JSON or SARIF; add `--exit-code` for a one-line CI check that fails when your pinned version has moved
  - `apiome browse open <tenant>/<project>/<version>` opens that page of the browse app in your browser — a tenant, a project, a version or a compare page; `--print-url` prints the link instead, for CI or SSH
  - `apiome connectors shadow-report` prints the shadow-API report; `--fail-on shadow,drift` fails a CI job (exit 6) only for the categories you name
- Sign-up:
  - A sign-up page at **/signup**: every sign-in provider plus the email form, following the sign-up policy (closed and invite-only installations show a notice and the sign-in link); **Create one** on the sign-in page opens it
  - Create an account with your email address and a password: Apiome emails a confirmation link that works once and expires in 24 hours, then signs you in and starts setting up your first organization
  - Administrators choose who can create an account — **Open**, **Invite only** or **Closed**, with an optional list of allowed email domains — on **System settings** in the admin console, with no restart; the same policy covers email and every sign-in provider
  - The old sign-up request queue and the admin console's **Pending Signups** tab are retired: people still waiting are emailed a link to create their account themselves
  - Sign-up is protected against scripted accounts: rate limits on sign-up and **Resend email**, disposable email addresses refused (administrators can add more domains under **Blocked email domains**), and an optional Cloudflare Turnstile check on the email form; each refusal says why, and administrators see them under **Recent blocked sign-ups** on **System settings**
- Mock Services:
  - Several mock services have been improved including mock rules and testing via UI and JSON rules
- Design system:
  - New status strip: several statuses about one object in one row of chips, with one detail open at a time, instead of a stack of banners
  - Catalog: an item's open tab is kept in the page address (`?tab=lint`), so you can link a teammate straight to it; the **⋯**, sort and format menus wrap with the arrow keys, and closing a dialog puts focus back on the button that opened it
  - Catalog: give an item a **domain** and **tags** (**⋯ → Categorize…**, or **Categorize…** on its page) and filter the list by domain and tag, next to the paradigm the import detected
  - Catalog: an item's **Provenance** tab is now two columns — the import's four steps, and **Toolchain & routing** with the revision fingerprint, **Publishable: false** and why the import put it in the catalog
  - Catalog: tick several items (cards or table, with **Select all**) to convert, delete or undelete them together — bulk convert previews each item's fidelity and asks for each low-fidelity acknowledgement (or one for all), and any item that fails is listed with its reason
  - Catalog: while the list, an item or one of its tabs loads, placeholders in the shape of the content hold its place, so nothing jumps when it arrives
  - Catalog: the list starts near the top of the page — the explainer shows once (**Learn more** or **Got it**), the numbers fold into one line with **Show stats** for the full statistics, and **How the catalog works** in the page description (or **Which formats can I import?** in the import wizard) explains the catalog and lists the supported formats
  - Catalog: an item synced by a connector says so on its **Provenance** tab — the connector, the remote API and the remote revision it came from — and the catalog's **Source** filter has **Catalog connector**
  - Catalog: **Open in Designer** on an item's page (when your workspace has Designer) shows it in Studio read-only — its normalized model and raw source, with no edit, save or publish; convert it to edit it
  - Versions: one toolbar on the version list — search, lifecycle, **Any time** (a date popover with Last 7 days, Last 30 days and This quarter), **All authors**, the state chips and sort — with **Clear filters (n)** while anything is filtered; the filters are kept in the page address, so a filtered list can be shared
  - Versions: switch project from the last breadcrumb step (type to filter), and find Merge branches, Sunset timeline, Published surface, Export studio and **Copy link** (⌘⇧C) under **⋯** — the header keeps Compare, Import and New version
  - Versions: import files from several repositories (one per service) into one project and they merge into one API — a class or path two repositories both define stops the import and names both files; the new **Sources** tab lists the contributing repositories and where every class and path came from
  - Versions: **Sync back to repositories** on the **Sources** tab renders a version and opens a pull request into the files it was imported from — preview the change report first; each repository chooses which projects may (an allow or deny list), the target branch, the commit message and the reviewers in its **Settings** tab
  - Versions: a **Federation** switch on the **Sources** tab chooses whether repository imports merge into one API or replace it, and **Merge history** (also a repository's **Sync history** on its **Imports** tab) lists every merge, conflict and replacement — open a conflict to compare both files' definitions line by line
  - Versions: the compatibility, what’s-new and deprecation banners are now one **Status** row of chips — click a chip to open its detail and actions — so the version list starts higher on the page
  - Home: a **Time spent** panel shows your own active time per project over the last 7 or 30 days — counted while a project is open on Versions and you are using the page, and visible only to you
  - Versions: **New version** asks whether to **Copy paths** when you copy from a version — classes are always copied, and paths come too unless you untick it
  - Navigation: **Tenants** moves from the rail to the workspace switcher's last row, **Manage workspaces…**, and the **Data browser** and **Migrations** tools get rows in your user menu — all three are still in ⌘K
  - Navigation: the **Workspace** group in the rail starts folded, showing how many pages it holds, so the rail fits a laptop screen without scrolling — click its heading to open it, and the rail remembers your choice
  - Launcher: only apps you can open get a card — **Control Panel** (now with when you last opened it), your plan's apps and **Browser**. Products not available yet are named on one **Coming next** line that links to What's new, and the hero shows how many versions **need attention**
  - Single sign-on: connect a company's own SAML 2.0 or OIDC identity provider from the admin console's **System settings**, for the email domains it owns; its people choose **Sign in with SSO** on the sign-in page
  - Pages fill wide screens: content now spans the area beside the sidebar (at least 95 % of it, up to 2,400 px) instead of a centred 1,440 px column; form pages keep their 920 px width
  - Import wizard: press **1**–**5** on the first step to choose File Upload, URL Import, Clipboard Paste, Git Repository or SwaggerHub — each card shows its number
  - Import wizard: it opens at wizard width and only as tall as the step needs, lists your three most recent imports under the source cards, and its forward button reads **Continue**; the **Profile** hero band is flat
  - Repositories and a repository's page open closer to the list: their stat cards become one summary line (**Show stats** opens them), Refresh activity becomes a *1 stale · 1 failed* chip that opens the panel in a drawer, and a repository's file filters sit behind **Filters** (the preset stays in the toolbar) and are kept in the page address
  - A repository's page has one **Branch** control, on the **Files** tab; the header keeps **Rescan**. Sources and sign-in providers that are not available yet are listed dimmed with **Coming soon** instead of as buttons that do nothing
  - Accessibility on Catalog, Projects and Versions: closing a dialog (Import to catalog, Convert to OpenAPI, Publish, Export and the rest) returns focus to the button that opened it; “Good” scores and the B grade read in a darker ink that meets contrast in every theme, and the code panes have names a screen reader announces
  - Catalog, Projects and Versions never go blank on a slow or failed request: each pane and dialog shows a placeholder while it loads, and a failed read says what failed with **Try again** — a failure no longer looks like “No projects yet” or “No versions yet”, and **View spec** no longer shows a placeholder document
  - Export: the **Export** dialog offers the 53 formats listed on *Export a spec*; a format that only writes back a source imported in that format (EDI X12, HL7 v2, SAP IDoc, …) is greyed out for any other source with the reason on its card, instead of failing after you click **Export**, and CloudEvents export works from REST sources
  - Members opens closer to the roster: the seat card becomes one summary line (members, active, pending, suspended, seats used and the plan, with a thin seat bar from 80 %), and the SSO and SCIM cards become one **Coming next** line that links to What's new
  - Lint posture and Sunset timeline open closer to the data: Lint posture's four tiles and grades card fold into one summary line with grade chips (**Show stats** opens them), and the Sunset timeline's warning banner becomes a **Where these warnings come from** link
  - Versions: **Heatmap** in a version's **Actions** menu shows its classes as tiles colored by complexity, recent change, how many classes reference them, or documentation completeness
  - Favorite projects: your pinned projects are listed in a **Favorite projects** card on Profile and lead the command palette (⌘K) under **Favorites**
  - Home: pin up to 8 projects with **Pin to Home** in a project's **⋯** menu on Projects; they stay at the top of Home under **Pinned projects**, where each row can be unpinned
  - Home: a new **Recently viewed** panel lists the projects you last opened in this workspace, with the latest version, when you viewed it and how often — kept per person, so it follows you across devices
  - New facts line and first-visit callout: a list page's stats fit in one line with **Show stats** to open the full grid, and explainers show once with **Got it**
- Documentation:
  - The user guide is now a searchable documentation site, grouped by job; **Help & docs** links open it
  - Docs pages show product screenshots in light and dark, retaken from the product every week
  - A new Getting started guide walks from sign-in to a published, browsable spec
  - **Full release notes** at the foot of this dialog opens a post per release on the documentation site, with every REST API change and links to the issues

## Bug Fixes

- Catalog, Projects and Versions:
  - **Home** no longer offers **Import a spec**, **New project** or **Create an API key** to a role that can't use them
  - The Catalog's **Source** filter no longer offers **Catalog connector**, which can't apply until connectors ship
  - The **New version** dialog points at **Compare**, not the hidden **Merge branches**; the Catalog import guide no longer says Arazzo creates projects
- Import:
  - Importing a spec larger than 1 MB from **Projects** or **Versions** no longer fails with *Body exceeded 1 MB limit*; the wizard now accepts specs up to 25 MB (set `APIOME_SERVER_ACTION_BODY_LIMIT` to change it)
  - Fixed upload to accept all file format extensions instead of just the 10 it had previously
  - Fixes dependency for AsyncAPI to re-enable import functionality
  - Fixing durability of import process, added extra tests to REST service test suite
  - Fixing bulk import functionality:
    - Now includes the ability to bulk import into existing or new projects without having to validate all selections
    - Visual indicator of the bulk import is now implemented properly
- MCP:
  - Hardens tool array emit for LLM tool summary
- Sign-in providers:
  - Providers saved on the admin screen now reach sign-in in containers: the app and Studio read the REST address from `REST_API_BASE_URL` at runtime, and the log names the address when it cannot be reached
- Studio:
  - Fixed the Studio container failing to cache optimized images (`EACCES` on `.next/cache`)
- Two-factor sign-in:
  - Sign in with a backup code when you cannot reach your authenticator
  - Trust a device for 30 days to skip the second step there
  - Two-factor sign-in now locks for 15 minutes after 10 wrong codes in a row, and says so
  - Accounts that sign in with GitHub, GitLab, Microsoft or Google can now turn two-factor on, and are asked for their code after signing in with the provider
  - A locked-out user's two-factor can be reset by an administrator, or by a workspace owner for a member of their workspace only; the reset is audited and the user is prompted to set it up again
  - New accounts are offered two-factor as the last step of setting up their first organization — **Protect your account** sets up Authy or Google Authenticator there, or **Skip for now** and turn it on later from **Profile → Security**, which reminds you while it is off
  - Workspace owners can require two-factor for every member, with a grace period (7 days by default): **Tenants → Manage → Security**. Members without it see a reminder, then must set it up before using the app once the grace period ends; **Members** marks who is due or overdue
- Governance:
  - **Shadow APIs** (Govern): what your connected gateways serve that the catalog does not describe, with possible matches, drift and undeployed APIs — link, import or ignore each with a reason
  - **Connectors** (Bring in): add a gateway with a dry run that shows what it would sync before anything is saved, then see each connector's items, runs and settings; Git refreshes and connector runs share one **Recent runs** ledger
  - **Teams**: group workspace members into named teams with a contact e-mail, chat, on-call and documentation links, each member a lead or a member; **Roles** has a new **Teams** row (Owner and Admin manage teams, Editor and Viewer can view them)
  - **Owner findings**: lint regressions, breaking changes, verification drift, failing deploy gates, MCP trust drift, shadow APIs and failed connector syncs now reach the owner team in the notification centre (one switch per type in **Preferences → Notifications**) and its chat channel
  - **Ownership in the lists**: Catalog, Projects, MCP servers, Published and Consumers show each entity's owner team, with a **Suggested** badge and one-click **Confirm**; filter any of them by team, assign one owner to many items from the Catalog and Projects bulk bar, and see each team's members, what it owns and its recent findings under **Workspace → Teams**
  - **Ownership policy**: a catch-all team for findings nobody owns and an optional "require an owner to publish" gate, under the tenant's **Ownership** settings; the publish dialog shows the owner gate (off, met or blocked), and **Workspace → Teams** lists ownership drift — deleted or empty owner teams and suggestions never confirmed
  - **Dependency graph**: Apiome now records what depends on what — consumers on the fields they use, conversions, identity links, MCP sources, gateway deployments and repositories — keeping vanished dependencies visible as stale for 30 days; read it over REST (`/v1/graph/…/edges`)
  - **Declared dependencies**: say what an API depends on with `x-apiome-depends-on` in its spec, a Backstage `catalog-info.yaml` in its repository (`consumesApis`, `dependsOn`), the REST API or `apiome graph declare`; names that match nothing are listed as unresolved instead of being dropped
  - **Blast radius**: ask what a change to an operation or schema affects — direct and transitive consumers with their owner teams, plus the verification runs, contracts, deploy-gate results, SDK targets, agent tools, mock packs and deprecated-version consumers it invalidates — with `POST /v1/graph/…/blast-radius` or `apiome graph impact`
  - **Dependency graph screens**: a **Dependencies** tab on every project, catalog item and MCP server (the edges grouped by kind with provenance, owners and stale edges, then a drawing you can expand node by node), a **Govern → Dependency graph** page to search and filter every connected entity, and a **Blast radius** drawer that lists who is affected and the evidence a change invalidates
  - **Usage ingest**: traffic sources can send usage events to `POST /v1/tenants/{tenant}/usage/ingest` with a key from the new **Usage source** preset (`usage:ingest`, which allows nothing else); tokens, cookies, emails and query values are scrubbed before anything is counted, and calls are matched against published versions only
  - **Bindings and traffic** (Projects → Consumers): tell the usage index how to recognise a consumer — a header, API key or JWT claim value (hashed, never shown again) or a user-agent pattern — then compare what it declares with what it really calls, and add an undeclared operation to its contract in one click; unattributed calls are counted as anonymous
  - **Runtime edges and suggested consumers**: the Dependencies tab shows what consumers really call (with call counts and the last day seen) in an **Observed at runtime** column beside the declared edges, and lists clients seen in traffic that aren't registered — **Register consumer** adds one with its binding in a click; blast radius can follow runtime callers only
  - **Schema registry for Kafka**: point `confluent-kafka`, `kafka-avro-serializer` or Spring at `/registry/schema/{tenant}` to register and look up Avro, JSON Schema and Protobuf schemas with no client change; create its key with the new **Schema registry: read** or **read + write** preset (`registry:read`, `registry:write`). Until compatibility rules ship, a new version registers only under level `NONE`
  - **MCP registry connector**: add an MCP registry (the official registry, Azure API Center, a Kong registry or another Apiome workspace) under **Bring in → Connectors**; each server with a reachable remote joins your MCP servers with its repository and packages linked, then is discovered and graded, and the connector's **Items** tab says why any other server was not added
  - **Schema registry in the app and CLI**: Avro, JSON Schema and Protobuf catalog items get a **Subjects** tab (versions, schema ids, compatibility level, attach and detach) and a **Registry** chip in the Catalog; **Workspace → Schema registry** sets the default level and mode and gives copy-paste serializer configuration for Python, Java and Spring with your registry URL; `apiome registry subjects|versions|register|compat|config` does the same from a terminal
  - **Catalog home across kinds**: the Catalog counts Projects, catalog items, MCP servers, consumers, connectors and teams in tiles that filter one cross-kind list (with owners, search and **Load more**), and shows **Unowned**, **Stale** and **Shadow** callouts that open the pages dealing with them; `GET /v1/catalog/{tenant}/entities` lists every kind in one shape
  - **Agents and models**: register the AI agents that call your APIs (runtime, model, agent keys) and the models they run on under **Bring in → Catalog**; an agent becomes a consumer of every API its keys can call — in impact, the blast radius and the dependency graph — its key revocations mark those edges stale, and a model's deprecation date shows on every agent that runs on it
  - **Gateway environments as entities**: each connector environment is now a **gateway config** — a connector's new **Environments** tab opens its page with the APIs it serves, auth and rate-limit posture, the declared loss (no schemas), an owner and its graph; **Push back** exports a catalog item back to Kong with the fidelity report first (AWS, Azure APIM and Apigee follow with FMT-7.7); `deployed_on` edges now point at the environment
  - **Catalog facts**: catalog items, Projects, MCP servers, connectors, gateway environments, agents and models show a **Facts** checklist — owner, consumers, dependencies, freshness, deployment, shadow APIs, registry level, trust baseline — each Met, Not met, Not applicable or Not assessed with its evidence; no score until maturity ladders arrive
  - **Migrate from Backstage or Compass**: repository scans read `catalog-info.yaml` (`kind: API` definitions are imported; components, systems, domains, groups and owners become suggestions), and **Import to catalog** takes a **Compass export**; **Catalog → Import reports** lists what is waiting — **Create team**, **Register component** or **Apply to** an existing Project — and every unmapped field. Nothing becomes an owner or a component without a click; accepted components are a new catalog kind with links, an owner and declared dependencies
  - **Schema registry connector**: add a Confluent, Karapace or Apicurio schema registry under **Bring in → Connectors** (basic auth, a bearer token or none); every subject is mirrored on a schedule as a schema subject with its versions, schema ids and compatibility level, each new version becomes a catalog revision, and the connector's **Items** tab says why a subject was not mirrored
- Security:
  - **Catalog**, **Projects** and **Versions** show each button and menu item only to a role that can use it: a **Viewer** sees reads and **Export**, an **Editor** everything but **Publish** / **Unpublish**, an **Owner** everything. The table is on the Roles help page, and converting a catalog item now needs `projects:create` in the REST API too
  - Linked-account sign-in tokens and personal access tokens are now encrypted at rest
  - Sign-in redirects and the session cookie now follow the Public Suffix List, so an installation on a shared hosting domain (such as `*.vercel.app` or `*.co.uk`) no longer trusts its neighbours
  - Linking a sign-in provider and linking related APIs can now only be started from Apiome's own pages, and a sign-in during a database outage no longer trusts the remembered workspace
  - Editing, deleting, restoring and permanently deleting a project from **Projects** or **Catalog** now checks that you are signed in, that the project is in your workspace and that your role allows it (`projects:edit` / `projects:delete`) — the same rule the REST API applies; creating a project is checked the same way and always lands in your current workspace
  - Every change the app makes on your behalf now checks who you are first: your profile, password and linked accounts only accept your own account; workspace members and settings need a workspace administrator; API keys need `api_keys:create`, `api_keys:edit` or `api_keys:delete`; making a version public or private needs `versions:publish`; an import can only be started (`imports:create`) and followed by the person who started it; and the admin console needs the admin sign-in

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: June 23, 2026*


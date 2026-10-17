# Apiome 08-2026 RC5

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

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
  - Linting rule pack updates for scoring new import types
    - Data contracts are now scored on their own terms: ownership, service levels, freshness,
      retention, column documentation, row identity, classification and declared quality checks
  - Added pills to supported format list to show the source and type that the API format provides
  - Every format now declares which versions it reads and writes, and which version an export produces by default
- CLI:
  - Install the `apiome` command line on Linux or macOS with one line: `curl -fsSL https://get.apio.me | bash` (re-run to upgrade; `--uninstall` to remove)
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
- Sign-up:
  - Administrators choose who can create an account — **Open**, **Invite only** or **Closed**, with an optional list of allowed email domains — on **System settings** in the admin console, with no restart; the same policy covers email and every sign-in provider
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
  - Versions: one toolbar on the version list — search, lifecycle, **Any time** (a date popover with Last 7 days, Last 30 days and This quarter), **All authors**, the state chips and sort — with **Clear filters (n)** while anything is filtered; the filters are kept in the page address, so a filtered list can be shared
  - Versions: switch project from the last breadcrumb step (type to filter), and find Merge branches, Sunset timeline, Published surface, Export studio and **Copy link** (⌘⇧C) under **⋯** — the header keeps Compare, Import and New version
  - Versions: the compatibility, what’s-new and deprecation banners are now one **Status** row of chips — click a chip to open its detail and actions — so the version list starts higher on the page
  - New facts line and first-visit callout: a list page's stats fit in one line with **Show stats** to open the full grid, and explainers show once with **Got it**
- Documentation:
  - The user guide is now a searchable documentation site, grouped by job; **Help & docs** links open it
  - Docs pages show product screenshots in light and dark, retaken from the product every week
  - A new Getting started guide walks from sign-in to a published, browsable spec
  - **Full release notes** at the foot of this dialog opens a post per release on the documentation site, with every REST API change and links to the issues

## Bug Fixes

- Import:
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
- Security:
  - Linked-account sign-in tokens and personal access tokens are now encrypted at rest
  - Sign-in redirects and the session cookie now follow the Public Suffix List, so an installation on a shared hosting domain (such as `*.vercel.app` or `*.co.uk`) no longer trusts its neighbours
  - Linking a sign-in provider and linking related APIs can now only be started from Apiome's own pages, and a sign-in during a database outage no longer trusts the remembered workspace

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: June 23, 2026*


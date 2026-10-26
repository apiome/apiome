# Apiome 10-2026 RC7

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

- Suite Access:
  - **Designer** and **Developer** now show in the **Build** section and on the launcher only for a user an administrator gives **Suite Access** (admin console → **Users** → ⋮ → **Grant Suite Access**). A license, including the free plan, no longer shows them
- Version:
  - The version shown on the home page, in the user menu and on **Help & docs** now names its release candidate (`RC7`)
- API Formats:
  - Adds formats:
    - Bruno collection import — a Bruno collection folder (`bruno.json` and its `.bru` files) imports as one REST API from an archive or straight from git, with the same result either way: folders as operation groups, requests as operations with inferred body schemas, `{{baseUrl}}` as a server variable and whole-variable parameters with their value as default; credentials and secret variables are never kept, and scripts and tests are listed in the coverage ledger
    - Insomnia collection import — an Insomnia v4 (JSON) or v5 (YAML) export and its environment files become one REST API: folders as operation groups, requests as operations with inferred body schemas, `{{ _.baseUrl }}` as a server variable and whole-variable parameters with their environment value as default; saved credentials, secret variables and cookie jars are never kept, and scripts, template tags, gRPC and WebSocket requests are listed in the coverage ledger
    - HAR capture import — save your browser's devtools Network log (or a proxy capture) as HAR and catalog the API it called: repeated calls become parameterized operations with request and response schemas inferred from the traffic, page assets and analytics are left out, each host becomes its own catalog item, and cookies and credentials are never kept
  - Collection source cards — **HAR (inferred)**, **Insomnia collection** and **Bruno collection** each have a card in **Import to catalog** (HAR with an activity icon), take a file or a `.zip` / `.tar.gz` archive, and import from the CLI with `apiome import har`, `apiome import insomnia` and `apiome import bruno`. A single Bruno `.bru` request is no longer mistaken for an `.http` file
  - OpenAPI 3.2 QUERY and custom methods — a path's `query` operation and its `additionalOperations` entries (such as `REPORT`) import as path operations with their request and response schemas, keep their method token, and export to `x-apiome-query-operation` / `x-apiome-additional-operations` so they survive a round-trip
  - OpenAPI 3.2 streaming responses — an `itemSchema` under JSON Lines (`application/jsonl`), JSON text sequences (`application/json-seq`) or Server-Sent Events (`text/event-stream`) imports its element schema as a class tagged `x-apiome-stream-kind`, the operation links to it, and **Analyze** lists the streaming media types under **Feature compatibility**
  - Secret scrubbing for collections and captures — Postman, Insomnia, Bruno, HAR and `.http` imports always strip credentials, whatever your workspace's scrub policy says. Variables keep their names but not their secret values, auth becomes security-scheme stubs in the converted OpenAPI document, and the catalog item's **Provenance** tab lists every redaction in a new **Secret scrub** row

## Bug Fixes

- Sign-in:
  - Confirming a new account no longer flashes *We could not sign you in automatically* before the **Let's set up your first workspace** screen
  - **Sign In** stays disabled while you are being signed in, instead of turning back on and inviting a second click; it comes back only if the attempt fails
  - The sign-in page's *Watch our intro video* link, which no longer worked, is now **Explore our YouTube** and opens the Apiome YouTube channel
- Admin console:
  - Signing up again with the address of a deleted account no longer fails with *We could not send the confirmation email*. Deleting a user now releases their email address and linked sign-ins, signs them out everywhere, and the reason for a failed sign-up is logged
  - A disabled or deleted account can no longer sign in with its password
  - The **Users** list shows each account's **Created** date instead of *Invalid Date*, and a new **Last active** column shows its last sign-in or activity (*Never* for an unused account). Email and password sign-ins are now recorded too, not just provider sign-ins

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: October 25, 2026*


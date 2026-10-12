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
- Sign-up:
  - Administrators choose who can create an account — **Open**, **Invite only** or **Closed**, with an optional list of allowed email domains — on **System settings** in the admin console, with no restart; the same policy covers email and every sign-in provider
- Mock Services:
  - Several mock services have been improved including mock rules and testing via UI and JSON rules
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
- Studio:
  - Fixed the Studio container failing to cache optimized images (`EACCES` on `.next/cache`)
- Two-factor sign-in:
  - Sign in with a backup code when you cannot reach your authenticator
  - Trust a device for 30 days to skip the second step there
  - Two-factor sign-in now locks for 15 minutes after 10 wrong codes in a row, and says so
  - Accounts that sign in with GitHub, GitLab, Microsoft or Google can now turn two-factor on, and are asked for their code after signing in with the provider
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


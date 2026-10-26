---
title: "Secrets in collections and captures"
description: "How Apiome strips credentials from collections, captures and request files."
sidebar_position: 38.5
tags: [import, security, secrets, postman, insomnia, bruno, har, http-file]
---

Collections and captures are the riskiest files you can import. A Postman environment, an Insomnia
export, a Bruno folder, a HAR recording or a `.http` request file often carries a live bearer token,
a session cookie or an API key. Apiome strips every credential from these files before it stores
anything. **You cannot switch this off.**

This page covers five importers:

- **Postman** (collections and environment files)
- [**Insomnia**](./insomnia-import.md)
- [**Bruno**](./bruno-import.md)
- [**HAR**](./har-import.md) (captured traffic)
- **`.http` / `.rest`** request files (VS Code and JetBrains)

## Scrubbing is always on

For every other format, your workspace's secret-scrub policy picks the mode: **enforce**, or
**warn-only** while you try the policy out. For these five, Apiome ignores the policy. An import
always:

- runs in **enforce** mode, even when your workspace is warn-only;
- runs **entropy detection**, even when your workspace has it turned off;
- names the policy tier `format_locked` in its scrub report.

The secret-scrub policy API refuses a per-format override for any of these formats. Sending one to
`PUT /v1/tenants/{tenant_slug}/governance/secret-scrub-policy` returns `422`. Reading the policy
lists them under `lockedFormats`. See the [governance reference](../reference/rest/governance.md).

## What Apiome stores

| What you upload | What is stored |
| --- | --- |
| One file (a collection, a capture, a request file) | The file with each credential replaced by `«redacted»`. The rest of the file is unchanged, so it can still be converted later. |
| An archive or a git selection (a Bruno folder, a Postman fileset) | When any member holds a credential, the archive itself is **withheld**: only its member list is stored. A clean archive is stored as uploaded. |

The catalog item is built from the same scrubbed values. Request headers, query values, bodies,
example URLs and saved samples never keep a credential. An `Authorization` header keeps only its
scheme word: `Bearer eyJ…` is stored as `Bearer «redacted»`.

## Variables keep their names, not their secrets

Requests are written against variables (`{{baseUrl}}`, `{{token}}`), so Apiome keeps every variable
**name**. It keeps a variable's **value** only when the value is not a credential.

- **A secret variable keeps its name only.** A variable is treated as a secret when its name says so
  (`apiKey`, `accessToken`, `password` …) or when its value looks like a credential. The catalog item
  records it with `"secret": true` and no value.
- **A reference stays a reference.** A value written as `{{token}}` is kept as written.
- **A base-URL variable becomes a server variable.** In Insomnia and Bruno imports, a request URL
  that starts with a variable (`{{baseUrl}}/orders`) gives the API a `{baseUrl}` server. The
  variable's value is the default, unless the value is a secret. A Postman `baseUrl` with a plain
  value becomes the server URL. A Postman `baseUrl` with no value, or with a credential in it,
  becomes a `{baseUrl}` server with no default, for you to fill in.
- **Exporting back to Postman** writes a secret variable with an empty value, ready for you to fill
  in.

## Auth becomes security-scheme stubs

An import records **that** an API uses auth, and how it is sent. It never records the credential.
This information comes from Postman, Insomnia and Bruno auth blocks, and from the `Authorization`,
API-key and `Cookie` headers in captures and request files. When you
[convert the item to OpenAPI](./convert-to-openapi.md), each scheme becomes a stub under
`components.securitySchemes`:

| Declared or observed auth | OpenAPI stub |
| --- | --- |
| Bearer token, JWT | `type: http`, `scheme: bearer` |
| Basic | `type: http`, `scheme: basic` |
| Digest | `type: http`, `scheme: digest` |
| OAuth 2.0 | `type: oauth2` with no flows. Fill in the flows and their URLs. |
| API key | `type: apiKey` with the header or query name the source declared (`X-API-Key` when it named none) |
| Session cookie | `type: apiKey`, `in: cookie` |
| Request signing (AWS Signature, Hawk, NTLM …) | `type: apiKey`, `in: header`, `name: Authorization` |

Every stub has the description *"Stub recorded at import: the scheme type only — no credential
material was kept."*

- **An operation requires a scheme only if the request itself declared one.** Auth inherited from a
  whole Postman collection becomes a stub, but no operation is marked as requiring it.
- **Swagger 2.0 output drops the stubs.** An OAuth 2 stub has no flow to write, so the conversion
  report notes `security-scheme-stubs-dropped`.

## The scrub report

Every import records what it redacted: the credential **types** and **sites**, never a value. The
report appears in two places:

- **The import job summary**, under `secret_scrub`.
- **The catalog item's Provenance tab**, in the **Secret scrub** row of **Toolchain & routing**.
  The row shows how many values were redacted, their types, and *Always enforced for this format*.
  Open **redaction sites** to see every one, as `line 18 · authorization-header`. For an archive
  member, the site is shown as `member:line`.

<Screenshot id="catalog-item-provenance-secret-scrub" alt="The Provenance tab of a HAR capture: the Secret scrub row reads 5 redacted, lists the credential types, and its redaction sites are expanded" />

An item imported before Apiome recorded the report shows **Not recorded** in that row.

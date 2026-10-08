---
title: "Classified diff"
description: "REST endpoints tagged classified-diff: 1 operation."
sidebar_position: 12
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `classified-diff` · 1 operation

## `POST /v1/diff/{tenant_slug}/classified` {#post-classified-diff-v1-diff-tenant-slug-classified-post}

**Post Classified Diff**

Classify changes between a stored base revision and a stored or inline head.

Supports **stored-vs-stored** (``head: {project, version}``) and
**inline-vs-stored** (``head: {inline}``) for the CI PR use case. Inline
documents larger than 10MB UTF-8 are rejected with ``413``.

Default response is JSON (:class:`ClassifiedDiffResponse`). When ``Accept``
includes ``text/markdown`` or ``text/md``, returns the CTG-1.3 markdown
changelog for the same classification (used by ``apiome diff --format md``).

With ``consumers: true`` the response also carries the CTG-4.2 per-consumer analysis —
``consumers`` on the body, and the touched handles on each change — and the markdown gains a
"Consumer impact" section. Consumers are those registered against the **base** project, since
that is the published contract they declared against; the flag needs
``consumer_contracts:view``.

Operation id: `post_classified_diff_v1_diff__tenant_slug__classified_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for post classified diff.

- `application/json` — [`ClassifiedDiffRequest`](#schema-classifieddiffrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Classified JSON by default, or CTG-1.3 markdown when ``Accept: text/markdown`` (or ``text/md``) is sent. | `application/json` [`ClassifiedDiffResponse`](#schema-classifieddiffresponse); `text/markdown` string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ClassifiedDiffRequest` {#schema-classifieddiffrequest}

Request body for classified diff: stored base vs stored or inline head.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `base` | `ClassifiedDiffStoredRef` | yes | Stored baseline revision (published contract / older side). |
| `head` | `ClassifiedDiffStoredRef` or `ClassifiedDiffInlineHead` | yes | Head side: either another stored ``{project, version}`` or ``{inline}`` candidate document text. |
| `consumers` | boolean | no | Include the CTG-4.2 per-consumer analysis for the base project's registered consumers. Requires ``consumer_contracts:view``. |

### `ClassifiedDiffResponse` {#schema-classifieddiffresponse}

Classified change list with summary counts, max severity, and resolved sides.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `changes` | array of `ClassifiedDiffChangeOut` | no | Changes. |
| `counts` | map of integer | no | Counts. |
| `maxSeverity` | string or null | no | Max Severity. |
| `base` | `ClassifiedDiffResolvedStored` | yes | Base. |
| `head` | `ClassifiedDiffHeadMeta` | yes | Head. |
| `consumers` | `ConsumerImpactReport` or null | no | CTG-4.2 per-consumer verdicts, present only when ``consumers: true`` was sent. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

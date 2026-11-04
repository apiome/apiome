---
title: "Serve your catalog as an xRegistry"
description: "Point xRegistry and CloudEvents tools at Apiome's read-only xRegistry API."
sidebar_position: 5.7
tags: [xregistry, cloudevents, schema registry, browse, export]
---

Apiome serves your organization's **published** APIs as a read-only
[xRegistry](https://xregistry.io), the CloudEvents project's catalog API. Point an xRegistry client,
a CloudEvents code generator or any tool that reads xRegistry at it, and it lists and fetches your
schemas and CloudEvents message definitions directly, with nothing to download or keep in sync. To
hand someone a file instead, [export an xRegistry document](./export-a-spec.md#xregistry-from-any-source).

## When to use it

- **A tool should read your event catalog live.** It follows the registry's own links, and a newly
  published version appears within five minutes.
- **Share your public events with anyone.** The public registry needs no account.
- **Read private APIs from your own tooling.** Members of the organization use the private registry
  with an API key.

## The two registries

| Registry | Address | Who | What it holds |
|---|---|---|---|
| **Public** | `/v1/browse/tenants/{tenant_slug}/xregistry` | Anyone, no sign-in | Each project's latest **published, public** version. Never a private or draft version, even when you send credentials |
| **Private** | `/v1/xregistry/{tenant_slug}` | Members of the organization (JWT or API key) | Each project's latest **published** version, public or private. Never a draft, and never another organization's |

Both are on the REST API (for example `https://api.example.com/v1/browse/tenants/acme/xregistry`).
Each organization's Browse page links its public registry as **xRegistry**, next to **For agents**.

## What is in the registry

Each project contributes its latest published version, written the way the
[xRegistry export](./export-a-spec.md#how-the-item-is-written-to-xregistry) writes it:

| In the registry | What it is |
|---|---|
| `/schemagroups/{project}` | One schema group per project, named by its slug |
| `/schemagroups/{project}/schemas/{schema}` | One JSON Schema (draft 2020-12) per type; its one version is named after the project version (`1.4.0`) |
| `/messagegroups/{project}.{group}` | One message group per service with events, prefixed with the project slug |
| `/messagegroups/{project}.{group}/messages/{message}` | One CloudEvents message definition per publish or subscribe operation: `type`, `source`, `datacontenttype` and a `dataschemaxid` that names its payload schema |

A project with neither a type nor an event (a gateway configuration, an agent card) adds nothing.

## Read it

Every request is a `GET`. Start at the registry and follow the links it returns:

| Path | Returns |
|---|---|
| `/` | The registry: `registryid`, `schemagroupsurl` and `schemagroupscount`, `messagegroupsurl` and `messagegroupscount` |
| `/capabilities`, `/model` | What the server supports (read-only, `inline`, no pagination) and the two group types |
| `/schemagroups`, `/messagegroups` | Every group, by id |
| `/{groups}/{group}` | One group, with its `schemasurl` or `messagesurl` and count |
| `/{groups}/{group}/schemas`, `…/messages` | Every resource of the group, with its attributes |
| `/schemagroups/{group}/schemas/{schema}` | The **schema document** itself, with its attributes in `xRegistry-*` headers |
| `/messagegroups/{group}/messages/{message}` | The message definition (a message has no separate document) |
| `…/{resource}$details` | A resource's attributes instead of its document |
| `…/{resource}/versions`, `…/versions/{version}` | Its one version, and that version's document or `$details` |

Add `?inline=*` to the registry or a group to get everything below it in one response. Every entity
carries `xid`, `self`, `epoch`, `createdat` and `modifiedat`. An unknown path is `404`.

```bash
# The whole public registry in one response
curl -s "https://api.example.com/v1/browse/tenants/acme/xregistry?inline=*"

# One schema document
curl -s https://api.example.com/v1/browse/tenants/acme/xregistry/schemagroups/orders/schemas/Order

# The private registry, with an API key
curl -s -H "X-API-Key: $APIOME_API_KEY" https://api.example.com/v1/xregistry/acme/messagegroups
```

## Limits

- **Read-only.** There is no `PUT`, `POST` or `DELETE`; publish a version in Apiome to change the
  registry.
- **Rate limit.** Both registries share the public export limit per client address; over it, a
  request gets `429` with `Retry-After`.
- **Caching.** Public responses may be reused for five minutes, private ones for one minute.
- **No endpoints.** The registry holds schemas and message definitions only; xRegistry `endpoints`
  are not served.

## Related

- [xRegistry from any source](./export-a-spec.md#xregistry-from-any-source): the same projection as a
  downloadable document.
- [Import a CNCF xRegistry](../bring-in/xregistry-import.md): read an xRegistry into the catalog.
- [Browse published specs](./browse-published-specs.md): what is published and public.

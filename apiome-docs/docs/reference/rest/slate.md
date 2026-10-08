---
title: "Slate"
description: "REST endpoints tagged slate: 17 operations."
sidebar_position: 61
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate` · 17 operations

## `GET /v1/slate/domains/{domain_id}` {#get-domain-detail-v1-slate-domains-domain-id-get}

**Get Domain Detail**

Return one domain with its DNS instructions, checklist and certificate state.

Operation id: `get_domain_detail_v1_slate_domains__domain_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get domain detail. | `application/json` [`DomainResponse`](#schema-domainresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/domains/{domain_id}` {#remove-domain-v1-slate-domains-domain-id-delete}

**Remove Domain**

Detach a domain from its lane.

The row is deleted rather than tombstoned: it is what makes the global hostname claim and the
issuance authorization true, and a retained row would keep a hostname claimed against whoever
registers it next.

Operation id: `remove_domain_v1_slate_domains__domain_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for remove domain. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/domains/{domain_id}/certificate` {#probe-domain-certificate-v1-slate-domains-domain-id-certificate-post}

**Probe Domain Certificate**

Complete a TLS handshake with the host and record what it is serving.

This is the whole of "Renew now" as an honest action. Renewal is the edge's job and it does it
on a schedule; what an operator actually wants from that button is confirmation, so this
measures the live host and reports the certificate it found — including, when the serial has
changed, that a renewal has already happened.

A probe that fails is recorded and returned as a 200 with ``tlsStatus: "error"`` and the
reason, for the same reason a failed DNS check is: an unreachable host is a state to display,
not an exception to raise.

Operation id: `probe_domain_certificate_v1_slate_domains__domain_id__certificate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for probe domain certificate. | `application/json` [`DomainResponse`](#schema-domainresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/domains/{domain_id}/primary` {#make-domain-primary-v1-slate-domains-domain-id-primary-post}

**Make Domain Primary**

Make a domain the lane's canonical host; the others become redirects to it.

Refused for an unverified host: a canonical host that does not resolve here would redirect
every alias to a name that fails, taking the working aliases down with it.

Operation id: `make_domain_primary_v1_slate_domains__domain_id__primary_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for make domain primary. | `application/json` [`DomainResponse`](#schema-domainresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/domains/{domain_id}/renewal` {#set-domain-renewal-v1-slate-domains-domain-id-renewal-post}

**Set Domain Renewal**

Switch automatic certificate renewal on or off.

Switching it off withdraws the edge's authorization to obtain a certificate for the host at
all, so it parks a domain immediately rather than in ninety days' time.

Operation id: `set_domain_renewal_v1_slate_domains__domain_id__renewal_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set domain renewal.

- `application/json` — [`RenewalRequest`](#schema-renewalrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set domain renewal. | `application/json` [`DomainResponse`](#schema-domainresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/domains/{domain_id}/verify` {#verify-domain-v1-slate-domains-domain-id-verify-post}

**Verify Domain**

Read the tenant's public DNS now and record whether ownership is proven.

A failed check is a 200 with ``verified: false``, not an error: "the record is not there yet"
is the normal state of a domain someone attached ninety seconds ago, and answering 4xx would
make the screen show an error banner for the expected path. Only an inability to *ask* — a
resolver that timed out, a truncated answer — is a 502, because that is a statement about this
platform rather than about the tenant's DNS.

Operation id: `verify_domain_v1_slate_domains__domain_id__verify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify domain. | `application/json` [`VerifyResponse`](#schema-verifyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}` {#get-environment-state-v1-slate-environments-environment-id-get}

**Get Environment State**

Report what a lane is serving, how far it reached, and against what budget.

Operation id: `get_environment_state_v1_slate_environments__environment_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get environment state. | `application/json` [`EnvironmentResponse`](#schema-environmentresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/domains` {#list-environment-domains-v1-slate-environments-environment-id-domains-get}

**List Environment Domains**

List a lane's custom domains with their DNS instructions and certificate state.

Operation id: `list_environment_domains_v1_slate_environments__environment_id__domains_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list environment domains. | `application/json` [`DomainListResponse`](#schema-domainlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/domains` {#attach-environment-domain-v1-slate-environments-environment-id-domains-post}

**Attach Environment Domain**

Attach a hostname to a lane and answer with the DNS records that make it work.

The domain starts unverified and with no certificate: nothing has been proven, and because
``/tls/authorize`` refuses an unverified host, nothing is being provisioned either.

Operation id: `attach_environment_domain_v1_slate_environments__environment_id__domains_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for attach environment domain.

- `application/json` — [`AttachDomainRequest`](#schema-attachdomainrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for attach environment domain. | `application/json` [`DomainResponse`](#schema-domainresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/promote` {#promote-release-v1-slate-environments-environment-id-promote-post}

**Promote Release**

Route a lane to an already-built artifact. Never rebuilds.

A refused promotion still records an audit entry naming the reason, so an operator can
later see what was attempted and why it was stopped.

Operation id: `promote_release_v1_slate_environments__environment_id__promote_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for promote release.

- `application/json` — [`ActivationRequest`](#schema-activationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for promote release. | `application/json` [`ActivationResponse`](#schema-activationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/rollback` {#rollback-environment-v1-slate-environments-environment-id-rollback-post}

**Rollback Environment**

Route a lane back to its most recent retained artifact.

Deliberately does not consult approval freshness: requiring fresh sign-off to *stop*
serving a bad release would make the approval policy an outage amplifier.

Operation id: `rollback_environment_v1_slate_environments__environment_id__rollback_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for rollback environment.

- `application/json` — [`ActivationRequest`](#schema-activationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for rollback environment. | `application/json` [`ActivationResponse`](#schema-activationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/releases/{release_id}` {#get-release-detail-v1-slate-releases-release-id-get}

**Get Release Detail**

Load one release with its full evidence.

Operation id: `get_release_detail_v1_slate_releases__release_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `release_id` | path | string | yes | Path parameter identifying the release id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get release detail. | `application/json` [`ReleaseBody`](#schema-releasebody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/sites` {#list-managed-sites-v1-slate-sites-get}

**List Managed Sites**

List the tenant's managed sites with their environment lanes.

This is how the Release Center resolves a project to a site and its lanes; it works in
terms of a project and a version, not a site id. An empty list is a legitimate answer
meaning "this project is not hosted", which is different from an error.

Operation id: `list_managed_sites_v1_slate_sites_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `projectId` | query | string or null | no | Restrict to one project's sites. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list managed sites. | `application/json` [`SiteListResponse`](#schema-sitelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/sites/{site_id}/releases` {#list-site-releases-v1-slate-sites-site-id-releases-get}

**List Site Releases**

List a site's release timeline, newest first.

Operation id: `list_site_releases_v1_slate_sites__site_id__releases_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `site_id` | path | string | yes | Path parameter identifying the site id segment. |
| `environmentId` | query | string or null | no | Restrict the timeline to one environment. |
| `limit` | query | integer | no | Maximum releases to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list site releases. | `application/json` [`ReleaseListResponse`](#schema-releaselistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/sites/{site_id}/releases` {#create-site-release-v1-slate-sites-site-id-releases-post}

**Create Site Release**

Record a built release, refusing an artifact whose signature does not verify.

Verification happens at *record* time as well as at activation. Storing an
unverifiable artifact and only discovering it during an incident promotion would put
the discovery at the worst possible moment.

Operation id: `create_site_release_v1_slate_sites__site_id__releases_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `site_id` | path | string | yes | Path parameter identifying the site id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create site release.

- `application/json` — [`CreateReleaseRequest`](#schema-createreleaserequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create site release. | `application/json` [`ReleaseBody`](#schema-releasebody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/sites/{site_id}/retention` {#run-retention-v1-slate-sites-site-id-retention-post}

**Run Retention**

Reap artifacts that have fallen outside the site's rollback window.

Retention and rollback capability are the same setting, so the sweep is deliberately
conservative: the active release is never reaped, and only releases that once served
are candidates.

Operation id: `run_retention_v1_slate_sites__site_id__retention_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `site_id` | path | string | yes | Path parameter identifying the site id segment. |
| `environmentId` | query | string | yes | Environment whose history to sweep. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run retention. | `application/json` [`RetentionResponse`](#schema-retentionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/tls/authorize` {#authorize-tls-v1-slate-tls-authorize-get}

**Authorize Tls**

Answer the edge's on-demand TLS question: may this hostname be issued for?

**Unauthenticated by necessity and by design.** The caller is a TLS handshake, which has no
session to present. It supplies a hostname it already has and learns only whether this
platform will serve it — the same thing it would learn by connecting. Every other route on
this surface requires VERSIONS/PUBLISH.

Answers 200 only for a domain that exists, is verified, and has renewal enabled; everything
else is 403, which is what Caddy reads as "do not order a certificate". A permissive answer
here would let anyone point a hostname at us and have certificates issued in our ACME account
until the rate limit stopped them, so the check is a single conjunction with no fallbacks.

Operation id: `authorize_tls_v1_slate_tls_authorize_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `domain` | query | string | yes | The hostname the edge received over SNI. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for authorize tls. | `application/json` [`AuthorizeResponse`](#schema-authorizeresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ActivationRequest` {#schema-activationrequest}

Promote or roll back a lane.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `releaseId` | string or null | no | Release to promote. Ignored by rollback, which selects its own target. |
| `dryRun` | boolean | no | Run every gate and return the plan without changing routing. |
| `requireApproval` | boolean | no | Enforce this lane's approval policy for the promotion. |

### `ActivationResponse` {#schema-activationresponse}

Outcome of a promotion or rollback.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | Applied. |
| `dryRun` | boolean | yes | Dry Run. |
| `plan` | object | yes | Plan. |
| `activationId` | string or null | no | Activation ID. |
| `routingVersion` | integer or null | no | Routing Version. |
| `activatedAt` | string or null | no | Activated At. |

### `AttachDomainRequest` {#schema-attachdomainrequest}

Attach a hostname to a lane.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `host` | string | yes | The domain, with or without a scheme — it is normalized here. |
| `isPrimary` | boolean | no | Make this the lane's canonical host, demoting the current one. |
| `verificationMethod` | string or null | no | Override the derived method (cname for a subdomain, txt for an apex). Provided because apex detection is a heuristic, not the Public Suffix List. |

### `AuthorizeResponse` {#schema-authorizeresponse}

The edge's on-demand TLS answer for one hostname.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain` | string | yes | Domain. |
| `allowed` | boolean | yes | Allowed. |
| `reason` | string | yes | For the edge's log. Not shown to a browser. |

### `CreateReleaseRequest` {#schema-createreleaserequest}

Record a built release and its artifact.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | Lane the release targets. |
| `releaseRef` | string | yes | Short human-quotable id, unique per site. |
| `source` | `ReleaseSourceBody` | yes | Provenance source for the record (for example human or imported). |
| `contentDigest` | string | yes | Digest of the rendered bytes. |
| `sourceDigest` | string | yes | Digest of the source inputs. |
| `configDigest` | string | yes | Digest of the build configuration. |
| `signature` | string | yes | Detached signature over the three digests. |
| `signatureKeyId` | string | yes | Id of the signing key. |
| `storageUri` | string | yes | Where the artifact bytes live. |
| `manifest` | object | no | Build manifest / SBOM. |
| `pageCount` | integer | no | Rendered page count. |
| `sizeBytes` | integer | no | Total artifact size in bytes. |
| `status` | enum `"ready"`, `"review"` | no | Initial state of the built release. |
| `impact` | object | no | Cache/security consequences of activation. |

### `DomainListResponse` {#schema-domainlistresponse}

A lane's domains and the edge policy that applies to all of them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | Environment ID. |
| `domains` | array of `DomainBody` | no | Domains. |
| `tlsPolicy` | `TlsPolicyBody` | yes | Tls Policy. |
| `dnsTarget` | string | yes | The platform hostname custom domains are pointed at. |

### `DomainResponse` {#schema-domainresponse}

One domain, plus the edge policy, so a single-domain screen needs one call.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain` | `DomainBody` | yes | Domain. |
| `tlsPolicy` | `TlsPolicyBody` | yes | Tls Policy. |

### `EnvironmentResponse` {#schema-environmentresponse}

Lane state: what is serving, how far it reached, and against what budget.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `siteId` | string | yes | Site ID. |
| `kind` | string | yes | Kind. |
| `name` | string | yes | Human-readable name. |
| `activeReleaseId` | string or null | yes | Active Release ID. |
| `routingVersion` | integer | yes | Routing Version. |
| `robotsExcluded` | boolean | yes | Robots Excluded. |
| `accessPolicy` | string | yes | Access Policy. |
| `expiresAt` | string or null | no | Expires At. |
| `rollout` | object | no | Rollout. |
| `activationSlo` | object | no | Activation Slo. |
| `domains` | array of object | no | Domains. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ReleaseBody` {#schema-releasebody}

One immutable release, shaped to the Release Center's release record.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `releaseRef` | string | yes | Release Ref. |
| `environment` | string | yes | Environment. |
| `environmentId` | string | yes | Environment ID. |
| `status` | string | yes | Status. |
| `source` | `ReleaseSourceBody` | yes | Provenance source for the record (for example human or imported). |
| `artifact` | `ReleaseArtifactBody` | yes | Artifact. |
| `actor` | `ReleaseActorBody` | yes | Actor. |
| `createdAt` | string | yes | Created At. |
| `activatedAt` | string or null | no | Activated At. |
| `activationCompletedAt` | string or null | no | Activation Completed At. |
| `deactivatedAt` | string or null | no | Deactivated At. |
| `traffic` | object or null | no | Traffic. |
| `impact` | object | no | Impact. |
| `domains` | array of object | no | Domains. |
| `checks` | array of object | no | Checks. |
| `phases` | array of object | no | Phases. |
| `approvals` | array of object | no | Approvals. |
| `changedPages` | array of object | no | Changed Pages. |
| `logs` | array of object | no | Logs. |
| `audit` | array of object | no | Audit. |

### `ReleaseListResponse` {#schema-releaselistresponse}

The release timeline.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `releases` | array of [`ReleaseBody`](#schema-releasebody) | yes | Releases. |

### `RenewalRequest` {#schema-renewalrequest}

Switch automatic certificate renewal for a domain.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `autoRenew` | boolean | yes | Whether the edge may obtain and renew certificates. |

### `RetentionResponse` {#schema-retentionresponse}

Outcome of a retention sweep.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reaped` | integer | yes | Reaped. |
| `reapedReleaseIds` | array of string | yes | Reaped Release IDs. |
| `retainedReleases` | integer | yes | Retained Releases. |

### `SiteListResponse` {#schema-sitelistresponse}

The tenant's managed sites.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sites` | array of `SiteBody` | yes | Sites. |

### `VerifyResponse` {#schema-verifyresponse}

The outcome of an ownership check.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain` | `DomainBody` | yes | Domain. |
| `verified` | boolean | yes | Verified. |
| `detail` | string | yes | What was observed — the actionable part of a failure. |
| `tlsPolicy` | `TlsPolicyBody` | yes | Tls Policy. |

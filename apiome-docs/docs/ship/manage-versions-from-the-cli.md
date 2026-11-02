---
title: "Manage versions from the CLI"
description: "Cut, inspect, publish, freeze, compare and delete versions with apiome versions."
sidebar_position: 2.1
tags: [versions, cli, ci]
---

`apiome versions` covers a version's whole life from a terminal or a CI job, with the same
rules as the **Versions** screen (`/ade/dashboard/versions`):
1. Cut a draft.
2. Check what changed.
3. Gate it on compatibility.
4. Publish and freeze it.
5. Take it back or delete it when needed.

Every command calls the REST surface under `/v1/versions/{tenant_slug}/{project_id}` with your API
key, so a script can do everything the UI does without a browser.

Use it when you:
- cut a version on every release tag in CI;
- block a merge that breaks the previous published version;
- script a release (create, check, publish, freeze);
- inspect a version without opening the UI.

## Before you start

- **Install** the CLI and **sign in**: see [Install the CLI](../reference/install-the-cli.md) and the
  [CLI quick-start](../reference/cli-quickstart.md). In CI, set `APIOME_API_KEY`,
  `APIOME_BASE_URL` and `APIOME_TENANT_ID` instead of signing in.
- A project is named by its **slug** (`payments-api`) or UUID. A version is named by its **label**
  (`2.1.0` or `v2.1.0`) or revision UUID. `show`, `create --base`, `fork` and `compatibility` also
  accept a **version tag** (`stable`, `latest`).
- Put `--json` before the command (`apiome --json versions show …`) to get machine-readable output.

## The commands

| Command | What it does | REST |
| --- | --- | --- |
| `apiome versions list --project-id <id>` | List a project's versions (all projects without `--project-id`) | `GET /v1/versions/{tenant}/{project}` |
| `apiome versions show <project> <version>` | One version: state, dates, notes, tags, class and path changes, a compatibility summary and spec URLs | `GET …/{version}`, `POST …/compatibility` |
| `apiome versions get <version-id> --project-id <id>` | The raw version record, by UUID | `GET …/{version}` |
| `apiome versions create <project> --version 1.2.0` | Cut a draft version | `POST /v1/versions/{tenant}/{project}` |
| `apiome versions fork <project> <version> --into <project> --to 3.0.0` | Copy a version into another project, keeping its lineage | `POST …/fork` |
| `apiome versions compatibility <project> --base 2.0.0 --head 2.1.0` | Check two versions for breaking changes (a CI gate) | `POST …/compatibility` |
| `apiome versions publish <version> --project <project>` | Publish a version | `POST …/{version}/publish` |
| `apiome versions unpublish <project> <version> --reason '…'` | Take a published version back, with a recorded reason | `POST …/{version}/unpublish` |
| `apiome versions freeze <project> <version>` | Pin a published version's OpenAPI document byte-for-byte | `POST …/{version}/freeze-schema` |
| `apiome versions delete <project> <version>` | Delete a version after typing it to confirm | `DELETE …/{version}` |

Every option is listed in the [`apiome versions` reference](../reference/cli/versions.md).

## Cut a draft

```bash
apiome versions create payments-api --version 2.2.0 --notes 'Adds idempotency keys to /charges'
```

1. **Pick the label.** `--version` is a plain `MAJOR.MINOR.PATCH`. A pre-release such as `2.2.0-rc.1`
   is refused, because the server does not accept it. A label the project already has exits `6`
   before anything is written.
2. **Describe it.** Use `--notes` for a short note, or `--notes-file ./CHANGELOG.md` to use a UTF-8
   markdown file as the changelog (not both).
3. **Choose what it starts from.** Classes are copied from the latest published version. Pass
   `--base 2.1.0` (a label, UUID or tag) to copy another version, `--empty` to start with no classes,
   and `--copy-paths` to copy the base's paths too.
4. **Run it.** The command finds the project's head itself: the branch tip, or the newest revision
   when there are no branches. Pass `--branch <name>` when the project has several branches.

If someone else pushed between the lookup and the create, the command exits `1` with
`The project's head moved to … ; re-run the command`. The new version is always a **draft**;
publish it with `apiome versions publish`. `--from-file ./version.json` sends a full request body,
and the flags override its fields.

## Inspect a version

```bash
apiome versions show payments-api stable
```

```text
(tag 'stable' → 2.1.0)
Payments API v2.1.0  ★ stable, latest
────────────────────────────────────────
State:        published
Created:      2026-10-02 09:12 by kenji@example.com
Published:    2026-10-04 12:42
Frozen:       no
Notes:        Adds /refunds

Classes:      24    (3 added, 1 removed, 5 modified vs 2.0.0)
Paths:        18    (2 added, 0 removed, 4 modified vs 2.0.0)
Compatibility:1 breaking, 2 warnings, 9 info vs 2.0.0

Specs:
  OpenAPI 3.1   →  https://api.example.com/v1/schema/acme/payments-api/2.1.0
  Swagger UI    →  https://api.example.com/v1/swagger/acme/payments-api/2.1.0
  Arazzo        →  https://api.example.com/v1/arazzo/acme/payments-api/2.1.0
  JSON Schema   →  https://api.example.com/v1/json/acme/payments-api/2.1.0
```

The version is compared with the one before it: the most recent **published** version created
earlier, else the most recent one.
- A **class** counts as modified when a property was added, removed or changed.
- A **path** counts as modified when its summary, description or metadata changed.
- The **compatibility** line counts the findings of the server's compatibility engine (the same
  ones `versions compatibility` reports). It reads `not compared` for a project's first version, or
  when the server cannot compare the two.
- `--json` returns the version record plus `state`, `frozen`, `tags`, `matchedBy`, `classes`,
  `paths`, `compatibility_summary` and `spec_urls`.

## A release job

```bash
# On a release tag: cut the version, gate it, publish and freeze it.
apiome versions create payments-api --version "$VERSION" --notes-file CHANGELOG.md
apiome versions compatibility payments-api --head "$VERSION"     # exits 6 on a breaking change
apiome versions publish "$VERSION" --project payments-api
apiome versions freeze payments-api "$VERSION" --yes
```

`compatibility` compares `--head` with the most recent published version before it unless you pass
`--base`. It exits `6` on an unsuppressed breaking change and `8` when no verdict could be reached;
see the [version compatibility gate](../reference/ci/version-compatibility-gate.md) for the GitHub
Actions recipe and SARIF output.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Done |
| `1` | The server refused the request (for `create`, also: the head moved — re-run) |
| `2` | A bad argument, or a project, version or tag that does not exist |
| `6` | The command's refusal: the label already exists (`create`, `fork`), a breaking change (`compatibility`), the last published version (`unpublish`), a downloaded snapshot (`freeze --unfreeze`), a published or tagged version (`delete`) |
| `8` | `compatibility` could not reach a verdict |

The full list is in [Exit codes](../reference/cli/exit-codes.md).

## Related

- [Cut a version](./cut-a-version.md): the same step in the UI and over REST
- [Publish a version](./publish-a-version.md): publishing, unpublishing and freezing
- [Compare published versions](./compare-published-versions.md): the comparison in the UI
- [Versions](../build/versions.mdx): the Versions screen

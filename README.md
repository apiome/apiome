# Objectified

Objectified is an OpenAPI 3.2.0 Specification Application that provides a visual editor
for creating and editing Schema Objects and Properties.

## Goals

The Objectified application is a work in progress.

The goals of the project are:

- Provide user and group tenancy for schema definitions and sharing
- Provide visual editing of schemas class and property definitions
- Provide a database for storing schemas
- Provide a visual editor to create REST schemas using OpenAPI 3.2.0 Specifications

Eventually, the project will provide a database for storing data according to the
defined schemas.

## The Story

This is the 5th iteration of the project, effectively started in 2001 with Webplasm (see Webplasm
database, now defunct.)  Official work on this project started in 2021.

## Getting Started

Bring up the full local spine (Postgres, migrations, dev seed data, the REST API on `:8000`, and the
MCP server on `:8765`) with Docker:

```bash
docker compose up --build --wait
docker compose run --rm seed   # loads the dev tenant (acme-corp) + sample API key
```

### Golden path (does it all work?)

The end-to-end **golden path** — `import OpenAPI → edit a class & a path → lint → cut a version →
publish → view in browse → export via CLI → query via MCP` — is both a smoke test and the executable
definition of "the product works." Run it against a clean stack with:

```bash
scripts/golden_path/run.sh
```

See [docs/GOLDEN_PATH.md](docs/GOLDEN_PATH.md) for the step-by-step automated harness and the manual
UI checklist.

### Your first project in ~10 minutes

A fresh tenant is never empty: a curated, **published** sample project ("Pet Store") is provisioned
automatically on tenant creation (and by the dev seed), so you have a browsable spec to learn from
on day one.

1. **Seed the dev stack** (loads the `acme-corp` tenant + the published `petstore-sample` project):

   ```bash
   docker compose run --rm seed
   ```

2. **Sign in** to the UI (dev login: `ada@example.com` / `objectified-dev`) and open **Control
   Panel → Dashboard**. The **Get started** checklist tracks your progress and links each step.

3. **Designer** (`/ade/studio`): create a project, then **Add a class → Browse templates** to drop
   one of the 50 built-in starter class templates onto the canvas.

4. **Versions** (`/ade/dashboard/versions`): **cut a version**, then **Publish** it (public).

5. **View in Browse**: open your published version to see its OpenAPI spec render — or open the
   seeded **petstore-sample** project first to see the finished shape end to end.

Every newly created tenant (self-signup, admin panel, or `objectified-db tenants create
--sample-creator <user>`) gets the same sample via the shared `odb.provision_sample_project()`
routine. See [`objectified-db/README.md`](objectified-db/README.md) and
[`docs/runbooks/BACKUP_AND_DR.md`](docs/runbooks/BACKUP_AND_DR.md) for operational details.

## LLMs Used

LLMs are used in conjunction with development.  They do not replace development, they simply augment the
engineering tasks.

This is a list of the LLMs used, and their purposes.

| Model | Purpose |
|-------|---------|
| qwen3.6 | Pull request code reviews |
| opus4.8 | UI/UX component improvements, issue completeness |
| Cursor Auto | Most trivial development tasks |
| gpt-5.5 | Planning, Roadmaps, Ticket Implementation |

## Development Tools Used

Engineering tools all vary, but the primary ones used are:

- Cursor
- Copilot CLI
- Claude CLI

## Contributing

Fork the project, and off you go.  Please feel free to contribute to the project in the form of pull requests,
bug reports, fixes, and so on.  We encourage users to contribute!

## Donations

Donations to help with the Anthropic Claude, Cursor, and GitHub Copilot token budget are always appreciated.

## License

Apache 2.0 Licensed!


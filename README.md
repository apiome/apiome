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


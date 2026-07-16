# CLI quick-start

`apiome` is the command-line client for the Apiome REST API: import documents, inspect
tenant resources, lint, and export specs from the terminal. It follows [clig.dev](https://clig.dev/)
conventions — structured `--help`, sensible exit codes, tables on stdout, diagnostics on stderr.

Full details live in [`apiome-cli/README.md`](../../apiome-cli/README.md); this page is the
30-second start.

---

## Install & run

**Requirements:** Python ≥ 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
cd apiome-cli
uv sync
uv run apiome --version
```

Convenience runner (loads `.env`, ensures the venv):

```bash
./run.sh doctor
./run.sh projects list
./run.sh                 # interactive prompt (TTY) or one-command-per-line (piped)
```

## Configure

Resolution order is **flags > env vars > dotenv > config file > defaults**.

| Setting | Env var | Default |
|---|---|---|
| REST base URL | `APIOME_BASE_URL` | `http://localhost:8000` |
| Tenant (slug or UUID) | `APIOME_TENANT_ID` | — |
| API key (`X-API-Key`) | `APIOME_API_KEY` | — |
| UI session token | `APIOME_SESSION_TOKEN` | — |

Persist defaults to `~/.config/apiome/config.toml` via the CLI:

```bash
apiome config set base-url http://localhost:8000
apiome config set tenant   acme-corp
apiome config set api-key  obj_your_key_here
apiome config show          # secrets masked
```

Get an API key from the UI: **Dashboard → API keys** (`/ade/dashboard/api-keys`).

## First commands

```bash
apiome doctor                      # connectivity check (no auth)
apiome health                      # REST health JSON
apiome projects list               # needs tenant + API key
apiome import openapi ./spec.yaml  # import (waits for the job)
apiome lint --project <p> --version <v> --min-grade B
apiome spec export --project <p> --version <v> -o spec.json
```

## Cross-format export & projection evidence

`export` emits a version to another format (AsyncAPI, GraphQL SDL, Proto3, Avro, …) and
predicts its fidelity first. Before trusting a lossy export, page the **machine-readable
projection evidence** — one row per source construct with its status, cause category,
and reviewed explanation, tied to a stable snapshot hash:

```bash
apiome export targets  --project <p> --version <v>              # emitters + fidelity tier
apiome export evidence --project <p> --version <v> --target avro
apiome --json export evidence --project <p> --target avro       # summary + rows + next_cursor
apiome export avro --project <p> --version <v> --output User.avsc   # the export itself
```

**Non-zero exits are deliberate CI gates:** a `lossy`/`types-only` export exits `1`
unless you pass `--force` (or confirm at a TTY), and an export job submitted with an
acknowledged snapshot that no longer matches the current preview fails with a
`STALE_PREVIEW` error (exit `1`) telling you to re-preview and re-acknowledge. See
[export-fidelity.md](export-fidelity.md) for how to read the evidence.

## Command groups

| Group | What it does |
|---|---|
| `doctor`, `health` | Connectivity / health (no auth) |
| `auth` | Inspect signed-in identity and accessible tenants |
| `config` | Show / set / unset saved defaults |
| `projects`, `properties`, `schemas`, `types` | List & fetch tenant resources |
| `versions`, `paths`, `operations`, `workflows` | Inspect a project version's surface |
| `import` | Import OpenAPI / Swagger / Arazzo / JSON Schema (`auto` detects) |
| `lint` | Server-computed quality score & findings |
| `spec` | Export reconstructed OpenAPI / Arazzo documents |
| `export` | Emit a version to another format; list targets; page projection evidence |
| `repos` | List & inspect linked Git repositories |

Useful global flags: `--json` (raw JSON for scripting), `--tenant`, `--api-key`, `--base-url`,
`--verbose`, `--timeout`. Run `apiome help` or `apiome <group> --help` for the rest.

## Related

- [import-a-spec.md](import-a-spec.md), [lint-and-quality.md](lint-and-quality.md),
  [export-a-spec.md](export-a-spec.md) — the spine, from the CLI
- [ci-diff-gate.md](ci-diff-gate.md) — GitHub Action wrapping `apiome diff` for PR gates
- [api-reference.md](api-reference.md) — the routes behind these commands

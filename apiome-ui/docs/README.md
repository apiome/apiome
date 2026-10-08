# apiome-ui/docs

This folder holds only the **contributor references** that apiome-ui's code, tests and env templates
point at by path (sign-in provider setup, the auth error-code contract, accessibility budgets, the
MCP UI primitives) and the package [changelog](CHANGELOG.md).

- **Product documentation** lives on the documentation site, <https://apiome.github.io/apiome/>
  (source: [`apiome-docs/`](../../apiome-docs/README.md)).
- **Older implementation notes** were moved to [`docs/archive/apiome-ui/`](../../docs/archive/apiome-ui/)
  by DOCS-1.14 (#5631); [`docs/archive/INVENTORY.md`](../../docs/archive/INVENTORY.md) lists them.
- A new `.md` here fails `scripts/check-loose-docs.sh` unless it is listed in
  `scripts/loose-docs-allowlist.txt` — write a site page instead.

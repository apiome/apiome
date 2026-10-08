# Archive — read-only history

These are the implementation notes that used to sit beside the code — fix summaries, feature
write-ups, test journeys, demo scripts and planning notes from `apiome-ui/docs/`, `apiome-browse/docs/`,
`apiome-db/docs/` and `docs/next-steps/`. They were moved here by DOCS-1.14
([#5631](https://github.com/apiome/apiome/issues/5631)) so their history stays browsable.

**They do not describe Apiome as it is.** Many describe screens, file names and behaviour that
have since changed. For the product today, read the documentation site:
**<https://apiome.github.io/apiome/>** (source: [`apiome-docs/`](../../apiome-docs/README.md)).

- [`INVENTORY.md`](INVENTORY.md) lists every Markdown file that was triaged — kept, migrated or
  archived — with the site page that now covers each archived note's area.
- Folders mirror where a file came from: `apiome-ui/`, `apiome-browse/`, `apiome-db/`, and
  `repository/` for the repository's own `docs/` folder.
- Do not edit or add files here. Write new documentation on the site; see
  [Contribute to the docs](https://apiome.github.io/apiome/admin/contribute-to-the-docs).
  `scripts/check-loose-docs.sh` fails a pull request that adds a loose `.md` under `apiome-*/docs/`.

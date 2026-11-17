# Changesets

This folder holds the release notes for **apiome-cli** (`@apiome/cli`) until they ship. Every pull
request that changes `apiome-cli/` adds one changeset:

```bash
cd apiome-cli
npx changeset        # pick @apiome/cli, the bump (patch / minor / major) and write the note
```

Commit the `.changeset/<random-name>.md` file it writes. A docs-only or test-only pull request can
skip it with the `no-cli-release` label instead.

To ship, a maintainer runs `yarn workspace @apiome/cli release:version` on a
`changeset-release/<name>` branch — it collects every changeset, bumps the version and updates
`apiome-cli/CHANGELOG.md` — and merges it as a `Release: apiome-cli vX.Y.Z` pull request. The
release is then published on GitHub (**Releases → Draft a new release**), which creates the
`cli-vX.Y.Z` tag.

Other workspaces are not released with changesets (they are listed under `ignore` in
`config.json`). The full guide is **Release the CLI** in the docs site
(`apiome-docs/docs/admin/release-the-cli.md`).

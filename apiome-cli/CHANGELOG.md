# @apiome/cli

## 0.142.0

### Minor Changes

- 4ed9afc: Releases are versioned with changesets: each pull request adds a changeset, a `Release: apiome-cli vX.Y.Z` pull request bumps the version and this changelog, and merging it pushes the `cli-vX.Y.Z` tag.
- b2c28f0: `apiome export graphql --federation` writes Apollo Federation v2 subgraph SDL (an `@link` header and an `@key` on every entity) and sends the option to the fidelity preview, so each synthesized key is counted as SYNTH.

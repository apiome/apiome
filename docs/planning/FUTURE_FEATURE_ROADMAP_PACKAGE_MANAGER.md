# Apiome: Package Manager - Feature Roadmap

> A package manager and registry specifically for schemas—like npm/pip for data definitions—enabling teams to publish, discover, install, and share versioned schema packages across organizations and the community.
>
> **Revenue Model**: Private registry hosting, enterprise features, premium packages
>
> **Tech Stack**: NextJS (app router), Radix UI, PostgreSQL, S3-compatible object storage (package tarballs), Redis (download counts, caching), OpenAPI 3.1, CLI (Node.js)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Publish versioned schema packages with semver to the public registry
- Install packages via CLI (`obj install @scope/package-name`) with dependency resolution
- Package metadata storage with descriptions, keywords, license, author, and README
- Lock file generation for reproducible installations across environments
- Browsable package discovery UI with search, filtering, and popularity ranking
- Dependency tree resolution with conflict detection and peer dependency support
- Private registry support for enterprise tenants with access control
- CLI authentication via API tokens with scoped permissions

---

## Epic 1: Registry & Package Storage

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                            | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|---------------------------------------------------|----------|
| 1.1 (#1176) | Package Format Specification       | Define the `.objpkg` package format: manifest, schema files, metadata        | `enhancement`, `mvp`, `package-manager`           | Yes      |
| 1.2 (#1177) | Registry Storage Backend           | S3-backed storage for package tarballs with PostgreSQL metadata              | `enhancement`, `mvp`, `package-manager`, `rest`   | Yes      |
| 1.3 (#1178) | Package Versioning & Semver Engine | Semver parsing, comparison, range resolution, and pre-release support        | `enhancement`, `mvp`, `package-manager`           | Yes      |
| 1.4 (#1179) | Registry REST API                  | Full CRUD API for package publishing, retrieval, and metadata queries        | `enhancement`, `mvp`, `package-manager`, `rest`   | No       |
| 1.5 (#1180) | Package Integrity & Signatures     | SHA-512 integrity hashes and optional GPG signing for package verification   | `enhancement`, `package-manager`                  | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1176) — Package Format Specification

Before anything can be published or installed, the package format must be defined. This issue specifies the `.objpkg` format—a gzipped tarball containing the schema files, a manifest, and optional documentation—establishing the contract between the CLI, the registry, and consumers.

The package manifest (`obj-package.json`) contains: `name` (scoped: `@scope/name` or unscoped), `version` (semver), `description`, `keywords[]`, `license` (SPDX identifier), `author` (name + email), `repository` (URL), `dependencies` (package name → semver range), `peerDependencies`, `schemas[]` (list of `.json` schema files in the package), and `main` (entry point schema file).

The tarball structure is:

```
package/
├── obj-package.json          # manifest
├── README.md                 # optional documentation
├── CHANGELOG.md              # optional changelog
├── schemas/
│   ├── user.schema.json      # schema files
│   ├── order.schema.json
│   └── product.schema.json
└── examples/
    └── sample-data.json      # optional example data
```

Schema files within a package use local `$ref` pointers for intra-package references (`./product.schema.json#/definitions/SKU`) and namespaced `$ref` for cross-package references (`@stripe/payment-schemas/schemas/charge.schema.json`). The format specification document is published as a versioned reference at `/docs/package-format`.

**Acceptance Criteria**

- `obj-package.json` manifest schema is defined with all required and optional fields
- Tarball structure is specified with `schemas/` directory and optional `examples/`, `README.md`
- Intra-package `$ref` resolution follows relative path conventions
- Cross-package `$ref` uses the `@scope/package/path` namespacing convention
- The format specification is versioned (starting at v1) to allow future evolution
- A JSON Schema for `obj-package.json` is published for manifest validation

**Part of Epic: Registry & Package Storage**

---

#### 1.2 (#1177) — Registry Storage Backend

The registry needs a storage layer that scales from dozens to millions of packages while keeping costs manageable. This issue builds the dual-layer storage: S3-compatible object storage for package tarballs (the heavy bytes) and PostgreSQL for structured metadata (the queryable data).

When a package is published, the tarball is uploaded to S3 with a key pattern: `packages/@{scope}/{name}/{version}/{name}-{version}.tgz`. The PostgreSQL `packages` table stores: `id`, `name`, `scope`, `description`, `created_at`, `updated_at`, `owner_id`, `is_private`, `deprecated_message`. The `package_versions` table stores: `id`, `package_id`, `version`, `tarball_url`, `tarball_sha512`, `manifest_json` (full `obj-package.json`), `published_at`, `published_by`, `yanked` (boolean).

Download counts are tracked in Redis with hourly rollups to PostgreSQL for reporting. A CDN layer (CloudFront/CloudFlare) sits in front of S3 for fast tarball downloads. Package metadata queries hit PostgreSQL through the registry REST API (issue 1.4).

The storage backend is internal infrastructure; external consumers interact only through the REST API and CLI. However, the storage architecture must support the future private registry feature (Epic 4) where tenants get isolated S3 prefixes and PostgreSQL schemas.

**Acceptance Criteria**

- Package tarballs are stored in S3 with the specified key pattern
- PostgreSQL tables for `packages` and `package_versions` are created with proper indexes
- Download counts are tracked in Redis and rolled up to PostgreSQL hourly
- Tarball uploads are validated for maximum size (50MB) and correct gzip format
- CDN is configured for tarball download acceleration
- The storage layer supports tenant isolation for future private registry use

**Part of Epic: Registry & Package Storage**

---

#### 1.3 (#1178) — Package Versioning & Semver Engine

Semantic versioning is the backbone of dependency management. This issue builds the semver engine that parses, compares, and resolves version ranges throughout the package manager—used by the CLI for dependency resolution, the registry for version queries, and the UI for version display.

The engine implements the full semver 2.0.0 specification: `MAJOR.MINOR.PATCH` with optional pre-release (`-alpha.1`, `-beta.2`, `-rc.1`) and build metadata (`+build.123`). Version range resolution supports: exact (`1.2.3`), caret (`^1.2.3` — compatible with minor), tilde (`~1.2.3` — compatible with patch), range (`>=1.0.0 <2.0.0`), hyphen (`1.0.0 - 2.0.0`), and wildcard (`1.x`, `1.2.x`).

The engine also handles dist-tags: `latest` (most recent stable), `next` (pre-release channel), and custom tags. Dist-tags are mutable pointers stored in PostgreSQL; version numbers are immutable once published.

Version ordering, comparison, and range satisfaction are exposed as a shared library used by both the CLI (client-side resolution) and the registry API (server-side queries like "give me the highest version matching ^2.1.0"). The library is published as a standalone npm package for ecosystem consumption.

**Acceptance Criteria**

- Full semver 2.0.0 parsing including pre-release identifiers and build metadata
- All range specifiers (`^`, `~`, `>=`, `<`, hyphen, wildcard) resolve correctly
- Pre-release versions sort correctly (alpha < beta < rc < release)
- Dist-tags (`latest`, `next`, custom) resolve to specific versions
- The semver library is usable both server-side (registry) and client-side (CLI)
- Edge cases are handled: `0.x` caret behavior, pre-release range inclusion rules

**Part of Epic: Registry & Package Storage**

---

#### 1.4 (#1179) — Registry REST API

The registry API is the central interface through which the CLI, the web UI, and integrations interact with the package registry. This issue builds the full REST API conforming to OpenAPI 3.1.

Core endpoints include: `PUT /api/v1/registry/{scope}/{name}` (publish a new version — accepts multipart with tarball and manifest), `GET /api/v1/registry/{scope}/{name}` (package metadata with all versions), `GET /api/v1/registry/{scope}/{name}/{version}` (specific version metadata and tarball URL), `DELETE /api/v1/registry/{scope}/{name}/{version}` (yank/unpublish within 72-hour window), `GET /api/v1/registry/-/search?q={query}&keywords={kw}` (search packages).

Authentication uses bearer tokens issued via `POST /api/v1/registry/tokens` with scoped permissions: `publish` (publish packages to owned scopes), `read` (download private packages), `admin` (manage scope membership). Token scopes prevent a CI/CD token from being usable for publishing unrelated packages.

Rate limiting protects the registry: 100 requests/minute for authenticated users, 30 for anonymous. Publish operations are limited to 10/hour per scope to prevent spam. The API returns standard pagination with `Link` headers for list endpoints.

**Acceptance Criteria**

- Publish endpoint accepts multipart upload with tarball and manifest, validates both, and stores
- Package metadata endpoint returns all versions with their manifests and tarball URLs
- Search endpoint supports full-text query, keyword filtering, and pagination
- Yank/unpublish is allowed within 72 hours of publication; after that, versions are permanent
- Authentication tokens support scoped permissions (publish, read, admin)
- OpenAPI 3.1 specification is published and kept in sync with the implementation

**Part of Epic: Registry & Package Storage**

---

#### 1.5 (#1180) — Package Integrity & Signatures

Supply chain attacks target package registries. This issue adds integrity verification and optional cryptographic signing to ensure that packages have not been tampered with between publish and install.

Every published package receives a SHA-512 hash of its tarball, stored in the `package_versions` table and returned in the metadata API response. The CLI verifies this hash after downloading a tarball and before extracting. Hash mismatches abort installation with a clear error message naming the package and expected vs. actual hash.

Optional GPG signing allows publishers to sign their packages with a private key. The public key is registered on their registry profile via `PUT /api/v1/registry/users/{userId}/gpg-keys`. Signed packages include a detached signature file in the tarball. During installation, the CLI verifies the signature against the publisher's registered public key when `--verify-signatures` is enabled or when the project's `.objrc` requires it.

The integrity system also tracks a provenance record: who published the package (user or CI/CD token), from which IP, at what time, and optionally from which Git commit (if the CLI detects a Git repository during publish). This provenance is displayable on the package page in the web UI.

**Acceptance Criteria**

- SHA-512 hash is computed and stored for every published tarball
- CLI verifies the hash after download and aborts on mismatch with a clear error
- GPG signing is supported: publishers register public keys, CLI verifies signatures
- Provenance records (publisher, IP, timestamp, Git commit) are stored per version
- The package detail page displays integrity hash and provenance information
- `--verify-signatures` flag on `obj install` enables mandatory signature checking

**Part of Epic: Registry & Package Storage**

---

## Epic 2: CLI & Installation Tooling

### Summary Table

| #   | Title                            | Description                                                                  | Labels                                          | Parallel |
|-----|----------------------------------|------------------------------------------------------------------------------|-------------------------------------------------|----------|
| 2.1 (#1182) | `obj` CLI Core & Authentication  | Build the CLI binary with auth, config, and command framework                | `enhancement`, `mvp`, `package-manager`         | Yes      |
| 2.2 (#1183) | `obj install` & Dependency Resolver | Install packages with transitive dependency resolution and lock files      | `enhancement`, `mvp`, `package-manager`         | No       |
| 2.3 (#1184) | `obj publish` Workflow           | Publish packages with pre-publish validation, README rendering, and prompts  | `enhancement`, `mvp`, `package-manager`         | No       |
| 2.4 (#1185) | Lock File & Deterministic Installs | Generate and consume `obj-lock.json` for reproducible dependency trees     | `enhancement`, `mvp`, `package-manager`         | No       |
| 2.5 (#1186) | Offline Cache & Performance      | Local package cache, parallel downloads, and offline installation support    | `enhancement`, `package-manager`                | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#1182) — `obj` CLI Core & Authentication

The CLI is the primary interface for schema package management. This issue builds the `obj` command-line tool with the command framework, authentication flow, and configuration management that all other CLI features build upon.

The CLI is distributed as an npm package (`npm install -g @apiome/cli`) and also as standalone binaries for macOS, Linux, and Windows. The command framework supports subcommands (`obj install`, `obj publish`, `obj search`, `obj login`), global flags (`--registry`, `--verbose`, `--json`), and per-command flags.

Authentication uses `obj login` which opens a browser to the Apiome OAuth flow and receives a token via localhost callback. The token is stored in `~/.objrc` (user-level config) or `$OBJ_TOKEN` environment variable for CI/CD. Token refresh is handled automatically. For CI/CD environments, `obj login --token <token>` accepts a pre-generated API token.

Configuration cascades from: defaults → `~/.objrc` (user) → `.objrc` (project) → command flags → environment variables. The project-level `.objrc` specifies the registry URL, default scope, and package manager preferences.

**Acceptance Criteria**

- `obj --help` displays all available subcommands with descriptions
- `obj login` opens browser OAuth flow and stores token in `~/.objrc`
- `obj login --token <token>` supports headless CI/CD authentication
- Configuration cascades correctly: defaults → user → project → flags → env vars
- The CLI is installable via `npm install -g @apiome/cli`
- `--json` flag outputs machine-readable JSON for all commands (for scripting)

**Part of Epic: CLI & Installation Tooling**

---

#### 2.2 (#1183) — `obj install` & Dependency Resolver

Installing a package means downloading it, resolving its dependencies, and importing its schemas into the current Apiome project. This issue builds the `obj install` command and the dependency resolution algorithm.

`obj install @stripe/payment-schemas` adds the package to `obj-package.json` dependencies, resolves the full dependency tree, downloads all packages, and extracts schemas into an `obj_modules/` directory. The resolver uses a SAT-solver-inspired algorithm that finds the maximal satisfying set of package versions given all version constraints. When conflicts are irreconcilable (package A requires `foo@^1.0` and package B requires `foo@^2.0`), the resolver reports the conflict chain and suggests resolution strategies.

```
obj install @stripe/payment-schemas@^2.0

Resolving dependencies...
  @stripe/payment-schemas@2.1.3
  ├── @apiome/core-types@1.5.0
  ├── @apiome/currency-schemas@1.2.1
  │   └── @apiome/core-types@1.5.0 (deduped)
  └── @apiome/address-schemas@1.0.4

Downloaded 4 packages in 1.2s
Extracted schemas to obj_modules/

✓ Installation complete
```

The resolver supports `peerDependencies` (requirements on the consumer's dependency tree rather than the package's own) and `optionalDependencies` (allowed to fail without blocking installation). Hoisting flattens the dependency tree when possible to minimize duplication.

After installation, the CLI runs schema validation to ensure all cross-package `$ref` pointers resolve correctly. Broken references are reported as warnings (optional deps) or errors (required deps).

**Acceptance Criteria**

- `obj install <package>` adds the package to `obj-package.json` and downloads it
- Transitive dependencies are resolved and downloaded recursively
- Version conflicts report the full conflict chain with involved packages and constraints
- `peerDependencies` are checked against the consumer's dependency tree
- Cross-package `$ref` pointers are validated after installation
- The `obj_modules/` directory structure mirrors the package hierarchy

**Part of Epic: CLI & Installation Tooling**

---

#### 2.3 (#1184) — `obj publish` Workflow

Publishing is a high-stakes operation—once a version is out, consumers depend on it. This issue builds the `obj publish` command with pre-publish validation, dry-run mode, and interactive prompts to catch mistakes before they reach the registry.

`obj publish` reads the current directory's `obj-package.json`, validates the manifest (required fields, valid semver, valid SPDX license), validates all schema files (JSON Schema compliance, `$ref` resolution), builds the tarball, and uploads to the registry. A `--dry-run` flag performs all validation and builds the tarball locally without uploading, showing exactly what would be published.

Before publishing, the CLI runs a checklist: (1) Is the version number higher than the latest published version? (2) Are there uncommitted changes in the Git working tree? (3) Does the README exist? (4) Do all tests pass (if a test command is configured in `obj-package.json`)? Each check is displayed with pass/fail indicators. Failures on critical checks (version number, schema validation) block publishing; warnings (uncommitted changes, missing README) prompt for confirmation.

The publish workflow also supports `obj publish --access public|restricted` to control whether the package is publicly visible or restricted to the scope's members. Publishing to an existing scope requires the user's token to have `publish` permission on that scope.

**Acceptance Criteria**

- `obj publish` validates manifest, schemas, and builds tarball before uploading
- `--dry-run` performs all checks and shows the tarball contents without uploading
- Pre-publish checklist reports pass/fail for version increment, uncommitted changes, README, and tests
- Critical check failures block publishing; warnings prompt for confirmation
- `--access public|restricted` controls package visibility
- Publishing requires a valid authentication token with `publish` scope permission

**Part of Epic: CLI & Installation Tooling**

---

#### 2.4 (#1185) — Lock File & Deterministic Installs

Without a lock file, `obj install` might resolve to different versions on different machines (when dependencies use ranges). This issue implements `obj-lock.json`—a file that records the exact resolved version and integrity hash for every package in the dependency tree, ensuring reproducible installations.

The lock file records: package name, exact resolved version, tarball URL, SHA-512 integrity hash, and the resolved versions of each package's own dependencies. When `obj-lock.json` exists, `obj install` uses it instead of resolving fresh, downloading the exact versions specified. This makes installations deterministic across machines, CI/CD runs, and time.

`obj install` updates the lock file when: (1) it runs without an existing lock file, (2) `obj-package.json` has changed since the lock was generated, or (3) `obj install --update` is explicitly requested. The `obj ci` command is a strict-mode install that fails if the lock file is missing or out of sync with `obj-package.json`—intended for CI/CD pipelines where determinism is mandatory.

The lock file is human-readable JSON with comments explaining why each version was chosen (which dependency required it). It should be committed to version control.

**Acceptance Criteria**

- `obj install` generates `obj-lock.json` when it doesn't exist
- Subsequent `obj install` with an existing lock file uses exact recorded versions
- Lock file includes integrity hashes that are verified on install
- `obj ci` fails if the lock file is missing or out of sync with `obj-package.json`
- `obj install --update` re-resolves all dependencies and regenerates the lock file
- Lock file format is human-readable with dependency chain comments

**Part of Epic: CLI & Installation Tooling**

---

#### 2.5 (#1186) — Offline Cache & Performance

Downloading the same packages repeatedly wastes bandwidth and slows CI/CD pipelines. This issue adds a local cache, parallel downloads, and offline installation support to make the CLI fast in all environments.

The local cache stores downloaded tarballs in `~/.obj-cache/` keyed by `{name}/{version}/{hash}.tgz`. Before downloading from the registry, the CLI checks the cache. Cache entries are validated by their SHA-512 hash (from the lock file or registry metadata). The cache is shared across all projects on the machine, so installing a common dependency like `@apiome/core-types` only downloads it once.

Parallel downloads fetch up to 8 packages simultaneously (configurable via `--concurrency`). A progress bar shows overall download progress with per-package status. Download failures retry 3 times with exponential backoff before reporting an error.

Offline mode (`obj install --offline`) installs exclusively from the local cache, failing if any package is not cached. This enables air-gapped environments and CI/CD setups that pre-warm the cache. `obj cache add <package@version>` pre-fetches a package into the cache without installing it.

**Acceptance Criteria**

- Downloaded tarballs are cached in `~/.obj-cache/` and reused on subsequent installs
- Cache hits skip the download entirely; integrity is verified by SHA-512 hash
- Parallel downloads fetch up to 8 packages simultaneously with progress indication
- `--offline` mode installs from cache only, failing if any package is not cached
- `obj cache add <package@version>` pre-fetches packages into the cache
- `obj cache clean` removes all cached packages; `obj cache ls` lists cached packages

**Part of Epic: CLI & Installation Tooling**

---

## Epic 3: Discovery & Marketplace UI

### Summary Table

| #   | Title                              | Description                                                                 | Labels                                          | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------|-------------------------------------------------|----------|
| 3.1 (#1188) | Package Search & Browsing          | Web UI for searching, filtering, and browsing the public package registry   | `enhancement`, `mvp`, `package-manager`         | Yes      |
| 3.2 (#1189) | Package Detail Page                | Rich package page with README, versions, dependencies, and download stats   | `enhancement`, `mvp`, `package-manager`         | Yes      |
| 3.3 (#1190) | Popularity & Quality Rankings      | Compute and display quality scores, popularity metrics, and trending badges | `enhancement`, `package-manager`                | No       |
| 3.4 (#1191) | Vulnerability Scanning             | Scan packages for known vulnerabilities and alert consumers                 | `enhancement`, `package-manager`                | No       |
| 3.5 (#1192) | License Compatibility Checking     | Analyze dependency tree for license conflicts and compliance issues         | `enhancement`, `package-manager`                | Yes      |

### Detailed Issue Descriptions

---

#### 3.1 (#1188) — Package Search & Browsing

Discoverability is what turns a registry into an ecosystem. This issue builds the public-facing search and browsing UI where developers find schema packages for their use case.

The search page lives at `/packages` in the NextJS app. It features a prominent search bar with full-text search across package names, descriptions, keywords, and README content. Results are ranked by a composite score: text relevance × quality score × popularity (download count). Filters narrow results by: keyword tags, license, scope (organization), and recency.

The browsing experience includes curated categories: "E-Commerce", "Healthcare", "Finance", "IoT", "Social", etc., displayed as a grid of cards on the homepage. Each category links to a pre-filtered search. A "Trending" section highlights packages with the highest download growth in the past 7 days.

The search API powers both the web UI and the CLI's `obj search` command: `GET /api/v1/registry/-/search?q={query}&keywords={kw}&sort={relevance|downloads|recent}&page={n}`. The page uses Radix `TextField` for search input, `Select` for sort/filter dropdowns, `Badge` for keyword tags, and a card layout for results.

**Acceptance Criteria**

- Full-text search covers package name, description, keywords, and README content
- Results rank by composite score combining relevance, quality, and popularity
- Filters for keywords, license, scope, and recency narrow results accurately
- Curated category cards on the homepage link to pre-filtered searches
- "Trending" section displays packages with highest 7-day download growth
- Search API returns paginated results consumable by both the web UI and CLI

**Part of Epic: Discovery & Marketplace UI**

---

#### 3.2 (#1189) — Package Detail Page

When a developer clicks on a package, they need comprehensive information to decide whether to use it. This issue builds the package detail page with README rendering, version history, dependency tree, download statistics, and quick-start instructions.

The detail page is a NextJS page at `/packages/[scope]/[name]`. The main content area renders the package's README as formatted markdown with syntax-highlighted code blocks. A sidebar displays: latest version, published date, license, weekly downloads, dependencies count, and a copy-to-clipboard install command (`obj install @scope/name`).

The page includes tabs (Radix `Tabs`): **README** (default), **Versions** (sortable table of all versions with dates, sizes, and changelog excerpts), **Dependencies** (interactive tree view showing the full dependency graph), **Dependents** (packages that depend on this one), and **Schema Preview** (render the package's schema files as expandable JSON trees).

```
┌─────────────────────────────────────────────────────┐
│  @stripe/payment-schemas                     v2.1.3 │
│                                                     │
│  ┌─────────────────────────┐  ┌──────────────────┐  │
│  │                         │  │  Install:        │  │
│  │  README content         │  │  obj install     │  │
│  │  rendered as markdown   │  │  @stripe/payment │  │
│  │                         │  │                  │  │
│  │  ## Getting Started     │  │  License: MIT    │  │
│  │  ...                    │  │  Downloads: 12K  │  │
│  │                         │  │  Deps: 3         │  │
│  │                         │  │  Published: 2d   │  │
│  │                         │  │                  │  │
│  └─────────────────────────┘  └──────────────────┘  │
│                                                     │
│  [README] [Versions] [Dependencies] [Schema]        │
└─────────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- README renders as formatted markdown with syntax-highlighted code blocks
- Sidebar displays version, license, downloads, dependencies count, and install command
- Versions tab lists all versions with publication date, size, and changelog excerpt
- Dependencies tab renders an interactive tree view of the full dependency graph
- Schema Preview tab renders the package's schema files as expandable JSON
- Install command is copy-to-clipboard with a single click

**Part of Epic: Discovery & Marketplace UI**

---

#### 3.3 (#1190) — Popularity & Quality Rankings

Raw download counts are a noisy signal. This issue computes composite quality and popularity scores that help developers distinguish well-maintained packages from abandoned or low-quality ones.

The quality score (0–100) evaluates: **maintenance** (25%) — how recently was the package updated, is there a changelog, does the author respond to issues? **Documentation** (25%) — does the package have a README, are schemas well-described, are examples included? **Schema quality** (25%) — do schemas pass the Copilot quality scorer, are `$ref` patterns used correctly? **Ecosystem** (25%) — how many dependents, is the license permissive, are dependencies up to date?

The popularity score combines: weekly downloads (normalized against the registry median), download growth trend (rising/flat/declining), GitHub stars (if repository URL points to GitHub), and number of dependent packages. These signals are computed nightly by a background job.

Scores are displayed on the package detail page as Radix `Progress` bars and on search results as color-coded Radix `Badge` components (green ≥ 80, yellow ≥ 50, red < 50). A "Staff Pick" badge is manually assigned by registry curators for exceptional packages.

**Acceptance Criteria**

- Quality score (0–100) is computed from maintenance, documentation, schema quality, and ecosystem metrics
- Popularity score combines downloads, growth trend, GitHub stars, and dependent count
- Scores are recomputed nightly by a background job
- Search results display quality and popularity badges using Radix `Badge`
- Package detail pages show score breakdowns with Radix `Progress` bars
- "Staff Pick" badge is assignable by registry curators via admin API

**Part of Epic: Discovery & Marketplace UI**

---

#### 3.4 (#1191) — Vulnerability Scanning

Schema packages can contain security issues: overly permissive types that allow injection, `$ref` patterns that enable denial-of-service through recursive expansion, or deprecated encryption schemas. This issue adds automated vulnerability scanning to the registry.

The scanner runs on every newly published package and periodically re-scans existing packages. It checks for: (1) recursive `$ref` loops that could cause infinite expansion, (2) schemas without maximum constraints on arrays/strings (potential memory exhaustion), (3) use of deprecated or insecure patterns (e.g., MD5 hash format), (4) known vulnerability advisories published by the Apiome security team.

Vulnerabilities are assigned severity levels (critical, high, medium, low) and stored as advisories in the registry database. The package detail page displays vulnerability badges. The CLI checks for vulnerabilities during `obj install` and reports them as warnings (medium/low) or errors (critical/high, with `--force` override).

An advisory API (`GET /api/v1/registry/-/advisories`) powers the vulnerability database. Registry admins publish advisories via `POST /api/v1/registry/-/advisories` with affected package, version range, severity, description, and recommended action (upgrade, patch, remove).

**Acceptance Criteria**

- Newly published packages are automatically scanned for security issues
- Recursive `$ref` loops are detected and flagged as high-severity vulnerabilities
- Unbounded array/string schemas without maximum constraints trigger medium-severity warnings
- Known advisories are checked during `obj install` and reported to the user
- Advisory API supports publishing, querying, and acknowledging vulnerabilities
- Package detail pages display vulnerability badges with severity levels

**Part of Epic: Discovery & Marketplace UI**

---

#### 3.5 (#1192) — License Compatibility Checking

Mixing incompatible licenses in a dependency tree creates legal risk. This issue adds automated license analysis that checks every dependency's license for compatibility with the consumer's project license.

The checker builds a license graph from the dependency tree, reading each package's `license` field from its manifest. It classifies licenses into compatibility groups: permissive (MIT, BSD, Apache 2.0), weak copyleft (LGPL, MPL), strong copyleft (GPL, AGPL), and proprietary. Incompatible combinations (e.g., GPL dependency in an MIT project) are flagged.

The analysis is available via `obj licenses` (CLI command) which prints a table of all dependencies with their licenses and compatibility status, and via the web UI on the package detail page's Dependencies tab as color-coded license badges. The REST API endpoint is `GET /api/v1/registry/{scope}/{name}/{version}/licenses`.

The checker supports `.objrc` configuration for: `allowedLicenses` (whitelist), `deniedLicenses` (blacklist), and `overrides` (manual license declarations for packages with missing or incorrect license fields). CI/CD integration enables `obj licenses --fail-on=copyleft` to block builds with license violations.

**Acceptance Criteria**

- Dependency tree license analysis runs via `obj licenses` CLI command
- Incompatible license combinations are detected and flagged (e.g., GPL in MIT project)
- License classification covers permissive, weak copyleft, strong copyleft, and proprietary
- `.objrc` supports `allowedLicenses`, `deniedLicenses`, and `overrides` configuration
- `--fail-on` flag enables CI/CD enforcement of license policies
- Web UI displays license badges on the dependency tree with compatibility indicators

**Part of Epic: Discovery & Marketplace UI**

---

## Epic 4: Publishing & Enterprise Features

### Summary Table

| #   | Title                              | Description                                                                | Labels                                          | Parallel |
|-----|------------------------------------|----------------------------------------------------------------------------|-------------------------------------------------|----------|
| 4.1 (#1194) | CI/CD Publishing Integration       | GitHub Actions, GitLab CI, and Jenkins plugins for automated publishing    | `enhancement`, `package-manager`, `rest`        | Yes      |
| 4.2 (#1195) | Deprecation & Lifecycle Management | Deprecate versions/packages with consumer notifications and sunset dates  | `enhancement`, `package-manager`, `rest`        | Yes      |
| 4.3 (#1196) | Private Registry & Tenant Isolation| Enterprise private registries with isolated storage and access control     | `enhancement`, `package-manager`, `rest`        | No       |
| 4.4 (#1197) | Scope & Team Management           | Manage organization scopes, team membership, and publishing permissions    | `enhancement`, `package-manager`, `rest`        | No       |
| 4.5 (#1198) | Audit Logging & Compliance        | Comprehensive audit trail for all registry operations                     | `enhancement`, `package-manager`                | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1194) — CI/CD Publishing Integration

Manual publishing is error-prone and doesn't scale. This issue builds CI/CD integrations that automatically publish schema packages when tagged releases are pushed, with pre-publish validation and conditional publishing based on branch rules.

The primary integration is a GitHub Action (`@apiome/publish-action`) that: (1) checks out the repository, (2) validates the package manifest and schemas, (3) runs tests if configured, (4) publishes to the registry using a stored `OBJ_TOKEN` secret, and (5) posts a comment on the release with the published version and install command. The action supports configuration for: registry URL, dist-tag (stable releases get `latest`, pre-releases get `next`), and access level.

A GitLab CI template and Jenkins plugin provide equivalent functionality. All integrations support dry-run mode for PR/MR pipelines—validating the package without publishing—so issues are caught before merge.

The CI/CD token used for publishing should have the minimum required scope (`publish` for the package's scope). The integrations guide the user through token creation with the correct permissions. Configuration documentation is published at `/docs/ci-cd-publishing`.

**Acceptance Criteria**

- GitHub Action publishes on tagged releases with `OBJ_TOKEN` secret authentication
- Dry-run mode runs in PR pipelines to validate without publishing
- Dist-tag assignment (`latest` vs. `next`) is configurable based on release type
- GitLab CI template provides equivalent publish functionality
- Pre-publish validation catches manifest and schema issues before upload
- Documentation covers token creation, Action setup, and GitLab/Jenkins configuration

**Part of Epic: Publishing & Enterprise Features**

---

#### 4.2 (#1195) — Deprecation & Lifecycle Management

Packages evolve, and old versions eventually need to be retired. This issue builds the deprecation workflow that allows publishers to deprecate individual versions or entire packages, notify affected consumers, and set sunset dates after which the version is no longer installable.

Deprecation is triggered via `obj deprecate @scope/name@version "Migration message"` or the REST API `PUT /api/v1/registry/{scope}/{name}/{version}/deprecate`. The deprecation message explains why the version is deprecated and what consumers should use instead. Deprecated packages display a yellow warning banner on their detail page and trigger a warning during `obj install`.

Sunset dates extend deprecation with a hard deadline. After the sunset date, the deprecated version returns 410 Gone from the tarball download endpoint, forcing consumers to upgrade. Sunset dates are configurable via `PUT /api/v1/registry/{scope}/{name}/{version}/sunset` with a `date` parameter.

Consumer notifications are sent via email and in-app notification to all users who have downloaded the deprecated version in the last 90 days. The notification includes the deprecation message, sunset date (if set), and a link to the recommended replacement.

**Acceptance Criteria**

- `obj deprecate` sets a deprecation message on a version or entire package
- Deprecated packages display a warning banner on the detail page and during install
- Sunset dates make versions uninstallable (410 Gone) after the specified date
- Consumer notifications are sent to users who downloaded the version in the last 90 days
- Deprecation is reversible via `obj undeprecate` within 30 days
- The deprecation message is included in `obj install` warnings and package metadata API

**Part of Epic: Publishing & Enterprise Features**

---

#### 4.3 (#1196) — Private Registry & Tenant Isolation

Enterprises need private schema registries that are invisible to the public and isolated from other tenants. This issue builds multi-tenant private registries with dedicated storage, access control, and optional proxy-through to the public registry.

Each enterprise tenant gets a private registry at a unique URL (`registry.apiome.app/{tenant}`). Private packages are stored in isolated S3 prefixes and PostgreSQL schemas. Access requires authentication with a token that has `read` permission on the tenant's scope. Unauthenticated requests receive 404 (not 401/403) to prevent registry enumeration.

The proxy feature allows private registries to fall through to the public registry for non-private packages. When `obj install @stripe/payment-schemas` is requested from a private registry that doesn't have it, the registry proxies the request to the public registry, downloads the package, caches it locally, and serves it to the client. This means enterprises can use a single registry URL for both private and public packages.

Private registry administration is a NextJS page at `/packages/enterprise/[tenantId]` using Radix `Table` for package listing, `Dialog` for access control management, and `Switch` for enabling/disabling the public proxy.

**Acceptance Criteria**

- Enterprise tenants get isolated private registries with dedicated S3 prefixes
- Private packages return 404 to unauthenticated requests (no information leakage)
- The public proxy falls through for packages not found in the private registry
- Proxied packages are cached in the private registry for subsequent requests
- Access control is per-scope: only authenticated users with `read` permission can download
- Admin UI at `/packages/enterprise/[tenantId]` manages packages and access with Radix components

**Part of Epic: Publishing & Enterprise Features**

---

#### 4.4 (#1197) — Scope & Team Management

Scopes (e.g., `@stripe`, `@internal`) organize packages by ownership. This issue builds the team and scope management system where organizations create scopes, invite members, and assign publishing permissions.

Scopes are created via `POST /api/v1/registry/scopes` with a unique name (validated for format: lowercase alphanumeric with hyphens). Each scope has an owner (the creating user) and can have multiple teams with different permission levels: **admin** (manage members and scope settings), **publish** (publish packages to the scope), **read** (download private packages in the scope).

Team management is handled at `/packages/teams/[scopeName]` with Radix `Table` for member listing, `Dialog` for invitations, and `Select` for role assignment. Invitations are sent via email with a one-click accept link. Pending invitations are listed with Radix `Badge` indicating their status.

The scope settings page at `/packages/scopes/[scopeName]/settings` allows admins to: rename the scope (with redirects from old name), transfer ownership, configure default package visibility (public/private), and set publishing policies (require 2FA, require GPG signature, restrict IP ranges).

**Acceptance Criteria**

- Scopes are created with unique names and owned by the creating user
- Teams support admin, publish, and read permission levels per scope
- Email invitations are sent with one-click accept links
- Scope settings allow renaming (with redirect), ownership transfer, and policy configuration
- Publishing policies can enforce 2FA, GPG signatures, and IP restrictions
- The team management page uses Radix `Table`, `Dialog`, and `Select` components

**Part of Epic: Publishing & Enterprise Features**

---

#### 4.5 (#1198) — Audit Logging & Compliance

Enterprise registries need a complete audit trail for compliance. This issue adds comprehensive logging for all registry operations: publish, download, deprecation, access control changes, and token management.

Every registry operation generates an audit event stored in an append-only PostgreSQL table: `event_type`, `actor_id`, `actor_type` (user | token | system), `resource_type` (package | version | scope | team), `resource_id`, `action` (publish | download | deprecate | member_add | token_create | ...), `metadata` (JSON with operation-specific details), `ip_address`, `user_agent`, `timestamp`.

The audit log is queryable via `GET /api/v1/registry/audit?scope={scope}&action={action}&from={date}&to={date}` with pagination and filtering. Logs are retained according to the tenant's retention policy (default 2 years, configurable). Exports are available in CSV and JSON formats for integration with enterprise SIEM systems.

The audit log viewer is a NextJS page at `/packages/audit` with Radix `Table` for event listing, `Select` for filters, and `DatePicker` for time range selection. Each event is expandable to show full metadata.

**Acceptance Criteria**

- All registry operations generate audit events in the append-only log
- Events include actor, resource, action, metadata, IP, and timestamp
- The audit API supports filtering by scope, action, actor, and time range
- Log retention is configurable per tenant (default 2 years)
- CSV and JSON export formats are supported for SIEM integration
- The audit viewer at `/packages/audit` displays filterable, paginated events

**Part of Epic: Publishing & Enterprise Features**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Registry & Package Storage):**
- 1.1 (Package Format), 1.2 (Storage Backend), and 1.3 (Semver Engine) are independent foundations and can all be developed in parallel.
- 1.4 (Registry API) depends on 1.1 (manifest format), 1.2 (storage), and 1.3 (version resolution) and should follow them.
- 1.5 (Integrity & Signatures) depends on 1.2 for the storage layer but can be developed once storage is available.

**Epic 2 (CLI & Installation Tooling):**
- 2.1 (CLI Core) must be completed first as all other CLI commands build on it.
- 2.2 (Install), 2.3 (Publish), and 2.5 (Offline Cache) can be developed in parallel after 2.1.
- 2.4 (Lock File) depends on 2.2 for the dependency resolver and should follow it.

**Epic 3 (Discovery & Marketplace UI):**
- 3.1 (Search & Browsing) and 3.2 (Package Detail Page) can be developed in parallel as independent pages.
- 3.3 (Rankings) depends on 3.1 for the search results display and 3.2 for the detail page layout.
- 3.4 (Vulnerability Scanning) and 3.5 (License Checking) are independent analysis engines that can be built in parallel.

**Epic 4 (Publishing & Enterprise Features):**
- 4.1 (CI/CD Integration) and 4.2 (Deprecation) can be developed in parallel.
- 4.3 (Private Registry) depends on 1.2 (storage backend) for tenant-isolated storage.
- 4.4 (Scope Management) depends on 4.3 for private scope functionality.
- 4.5 (Audit Logging) is independent and can be developed in parallel with any other issue.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 3 can be developed by separate teams. Epic 3 consumes the API defined in Epic 1 (issue 1.4), but the UI team can work against API mocks.
- Epic 2 (CLI) depends on Epic 1 (registry API) but can be developed against a mock registry.
- Epic 4 extends Epics 1 and 2 with enterprise features and should start after their core functionality is complete.

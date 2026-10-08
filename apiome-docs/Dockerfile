# syntax=docker/dockerfile:1

# Image for the Apiome documentation site (Docusaurus) — a static build served by nginx.
#
# Build from the repository root: apiome-docs is a Yarn workspace, so the root manifest and
# lockfile are needed to install it reproducibly.
#   docker build -f apiome-docs/Dockerfile -t apiome-docs .
#   docker run --rm -p 3200:8080 apiome-docs        # → http://localhost:3200/
#
# The site is served from `/` by default. Pass DOCS_URL / DOCS_BASE_URL to build it for another
# origin or a sub-path (the base URL must start and end with `/`; for a sub-path, put the
# container behind a proxy that strips that prefix):
#   docker build -f apiome-docs/Dockerfile --build-arg DOCS_URL=https://docs.example.com .

# Stage 1: install the docs workspace's dependencies and build the static site.
FROM --platform=$BUILDPLATFORM node:24-alpine AS builder
WORKDIR /repo

RUN corepack enable && corepack prepare yarn@4.12.0 --activate

# Yarn validates the lockfile against every workspace, so every workspace manifest is copied;
# `workspaces focus` then installs only what apiome-docs needs.
COPY package.json yarn.lock .yarnrc.yml ./
COPY apiome-cli/package.json apiome-cli/
COPY apiome-db/package.json apiome-db/
COPY apiome-mcp/package.json apiome-mcp/
COPY apiome-mock/package.json apiome-mock/
COPY apiome-ui/package.json apiome-ui/
COPY apiome-browse/package.json apiome-browse/
COPY apiome-rest/package.json apiome-rest/
COPY mock-action/package.json mock-action/
COPY apiome-docs/package.json apiome-docs/
RUN --mount=type=cache,target=/root/.yarn/berry/cache \
    yarn workspaces focus apiome-docs

COPY apiome-docs/ apiome-docs/
# The rolling "Unreleased" release-notes post is generated at build time from the REST
# changelog and the app's What's new (DOCS-1.12).
COPY scripts/package.json scripts/gen-release-notes.ts scripts/
COPY apiome-rest/CHANGELOG.md apiome-rest/
COPY apiome-ui/public/WHATS_NEW.md apiome-ui/public/

ARG DOCS_URL=http://localhost
ARG DOCS_BASE_URL=/
ENV DOCS_URL=${DOCS_URL} \
    DOCS_BASE_URL=${DOCS_BASE_URL}

# Page rules, then the production build (broken links and anchors fail it) — same as `yarn docs:check`.
RUN yarn workspace apiome-docs check

# Stage 2: serve the static build as a non-root user on :8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runner

COPY apiome-docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /repo/apiome-docs/build /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

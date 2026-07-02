# apiome-db: TypeScript CLI (migrate + admin commands)
FROM node:20-bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json tsconfig.json ./
COPY src ./src

RUN npm install && npm run build

FROM node:20-bookworm-slim

# postgresql-client supplies pg_dump / pg_restore, which the `backup` command group shells out to
# for full-cluster (`backup create --full`) and full-restore operations. Without it those commands
# fail at runtime, so the production deploy (docs/runbooks/PRODUCTION_DEPLOY.md) — which runs
# scheduled backups from this very image — would have no working full-backup path.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    NODE_ENV=production

WORKDIR /app

COPY package.json ./
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY scripts ./scripts/
COPY seed ./seed/

# Default: apply pending Flyway migrations (override with users, tenants, ping, etc.).
# Note: `seed` is dev-only and refuses to run under NODE_ENV=production; it is never
# invoked automatically here.
ENTRYPOINT ["node", "dist/cli.js"]
CMD ["migrate"]

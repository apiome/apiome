# objectified-db: TypeScript CLI (migrate + admin commands)
FROM node:20-bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json tsconfig.json ./
COPY src ./src

RUN npm install && npm run build

FROM node:20-bookworm-slim

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

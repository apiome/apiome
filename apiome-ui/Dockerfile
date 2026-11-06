# Dockerfile for Apiome UI (Next.js)
# Supports: linux/amd64, linux/arm64

# Stage 1: Dependencies
FROM --platform=$BUILDPLATFORM node:alpine AS deps
WORKDIR /app

# Install dependencies for native modules (bcrypt, pg)
# Retried: a CDN or DNS blip fetching the package index otherwise fails the whole build.
RUN for attempt in 1 2 3; do \
      apk add --no-cache libc6-compat python3 make g++ && exit 0; \
      echo "apk add failed (attempt $attempt), retrying" >&2; sleep 15; \
    done; exit 1

# Copy package files only
COPY package.json ./

# Install ALL dependencies (including dev deps) for build
# Using npm to avoid yarn workspace complications. There is no lockfile here, so npm resolves fresh
# on every build: `--legacy-peer-deps` keeps a newly published upstream peer range (e.g.
# @better-auth/core 1.7.x against @better-auth/sso's exact @better-auth/utils pin) from failing the
# build with ERESOLVE, and package.json `overrides` pins the versions the app is tested with.
#
# Retried as a whole: with no lockfile a just-published version can be listed in the registry before
# its tarball reaches the CDN (a 404 npm itself does not retry), and a network blip fails it too.
RUN for attempt in 1 2 3; do \
      npm install --legacy-peer-deps && exit 0; \
      echo "npm install failed (attempt $attempt), retrying" >&2; sleep 30; \
    done; exit 1


# Stage 2: Builder
FROM --platform=$BUILDPLATFORM node:alpine AS builder
WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy application code
COPY . .

# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application
RUN npm run build

# Place static assets and public files next to server.js, so the runner copies one finished tree.
# server.js sits in a package subdirectory of the standalone output (outputFileTracingRoot is the
# monorepo root), so it is found rather than assumed.
RUN SERVER="$(find /app/.next/standalone -maxdepth 3 -name server.js ! -path '*/node_modules/*' | head -1)" && \
    APP_DIR="$(dirname "$SERVER")" && \
    mkdir -p "$APP_DIR/.next" && \
    cp -r /app/.next/static "$APP_DIR/.next/static" && \
    cp -r /app/public "$APP_DIR/public"

# Stage 3: Runner (Production)
FROM node:alpine AS runner
WORKDIR /app

# Set to production environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
# The working directory itself (not recursive: its contents arrive owned, below).
RUN chown nextjs:nodejs /app

# Copy the standalone output already owned by the non-root user. Owning it at COPY time, not with a
# later `chown -R`, matters: a recursive chown rewrites every file into a new layer, which is slow
# and stores the whole tree (node_modules included) a second time.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --chown=nextjs:nodejs --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Set hostname to allow external connections
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Start the application from the standalone package directory
ENTRYPOINT ["/docker-entrypoint.sh"]


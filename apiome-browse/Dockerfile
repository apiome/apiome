# Dockerfile for Apiome Browse (Next.js)
# Supports: linux/amd64, linux/arm64
#
# Build from the repository root: `docker build -f apiome-browse/Dockerfile .`
# The Try-It modules in lib/tryit/ re-export the shared ones in apiome-ui/lib/tryit/ (DWX-4.2), so
# the build stages keep the monorepo layout — /app/apiome-browse beside /app/apiome-ui/lib/tryit —
# and the `../../../apiome-ui/...` imports resolve as they do in a checkout.
# apiome-browse/Dockerfile.dockerignore limits the context to those two directories.

# Stage 1: Dependencies
FROM --platform=$BUILDPLATFORM node:24-alpine AS deps
WORKDIR /app/apiome-browse

# Install dependencies for native modules (bcrypt, pg)
RUN apk add --no-cache libc6-compat python3 make g++

# Copy package files
COPY apiome-browse/package.json ./

# Install ALL dependencies (including dev deps) for build
# TypeScript is needed to transpile next.config.ts
RUN yarn install

# Stage 2: Builder
FROM --platform=$BUILDPLATFORM node:24-alpine AS builder
WORKDIR /app/apiome-browse

# Copy dependencies from deps stage
COPY --from=deps /app/apiome-browse/node_modules ./node_modules

# Copy application code (including .env.production) and the shared Try-It modules it re-exports
COPY apiome-browse/ ./
COPY apiome-ui/lib/tryit/ /app/apiome-ui/lib/tryit/

# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application (will read from .env.production automatically)
RUN yarn build

# Stage 3: Runner (Production)
FROM node:24-alpine AS runner
WORKDIR /app

# Set to production environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy package files for yarn start command
COPY --from=builder /app/apiome-browse/package.json ./package.json

# Copy node_modules (production dependencies)
COPY --from=builder /app/apiome-browse/node_modules ./node_modules

# Copy Next.js build output
COPY --from=builder /app/apiome-browse/.next ./.next

# Copy public directory
COPY --from=builder /app/apiome-browse/public ./public

# Copy next.config.ts if it exists
COPY --from=builder /app/apiome-browse/next.config.ts* ./

# Set ownership to non-root user
RUN chown -R nextjs:nodejs /app

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3003

# Set hostname to allow external connections
ENV HOSTNAME="0.0.0.0"
ENV PORT=3003

# Start the application
CMD ["yarn", "start", "-p", "3003", "-H", "0.0.0.0"]

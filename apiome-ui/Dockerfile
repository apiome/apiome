# Dockerfile for Apiome UI (Next.js)
# Supports: linux/amd64, linux/arm64

# Stage 1: Dependencies
FROM --platform=$BUILDPLATFORM node:20-alpine AS deps
WORKDIR /app

# Install dependencies for native modules (bcrypt, pg)
RUN apk add --no-cache libc6-compat python3 make g++

# Copy package files only
COPY package.json ./

# Install ALL dependencies (including dev deps) for build
# Using npm to avoid yarn workspace complications
RUN npm install


# Stage 2: Builder
FROM --platform=$BUILDPLATFORM node:20-alpine AS builder
WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy application code
COPY . .

# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application
RUN npm run build

# Stage 3: Runner (Production)
FROM node:20-alpine AS runner
WORKDIR /app

# Set to production environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy standalone output, then place static assets and public files next to server.js
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static /tmp/_next_static
COPY --from=builder /app/public /tmp/public
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN SERVER="$(find /app -maxdepth 3 -name server.js ! -path '*/node_modules/*' | head -1)" && \
    APP_DIR="$(dirname "$SERVER")" && \
    mkdir -p "$APP_DIR/.next" && \
    cp -r /tmp/_next_static "$APP_DIR/.next/static" && \
    cp -r /tmp/public "$APP_DIR/public" && \
    rm -rf /tmp/_next_static /tmp/public && \
    chmod +x /docker-entrypoint.sh

# Set ownership to non-root user
RUN chown -R nextjs:nodejs /app /docker-entrypoint.sh

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Set hostname to allow external connections
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Start the application from the standalone package directory
ENTRYPOINT ["/docker-entrypoint.sh"]


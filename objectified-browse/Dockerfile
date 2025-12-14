# Dockerfile for Objectified Browse (Next.js)
# Supports: linux/amd64, linux/arm64

# Stage 1: Dependencies
FROM --platform=$BUILDPLATFORM node:20-alpine AS deps
WORKDIR /app

# Install dependencies for native modules (bcrypt, pg)
RUN apk add --no-cache libc6-compat python3 make g++

# Copy package files
COPY package.json ./

# Install ALL dependencies (including dev deps) for build
# TypeScript is needed to transpile next.config.ts
RUN yarn install

# Stage 2: Builder
FROM --platform=$BUILDPLATFORM node:20-alpine AS builder
WORKDIR /app

# Build arguments for configuration
ARG NEXT_PUBLIC_BASE_PATH=""
ARG NEXT_PUBLIC_REST_API_BASE_URL="http://localhost:8000/v1"

# Set environment variables from build args
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH
ENV NEXT_PUBLIC_REST_API_BASE_URL=$NEXT_PUBLIC_REST_API_BASE_URL

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy application code
COPY . .

# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application
RUN yarn build

# Stage 3: Runner (Production)
FROM node:20-alpine AS runner
WORKDIR /app

# Set to production environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy package files for yarn start command
COPY --from=builder /app/package.json ./package.json

# Copy node_modules (production dependencies)
COPY --from=builder /app/node_modules ./node_modules

# Copy Next.js build output
COPY --from=builder /app/.next ./.next

# Copy public directory
COPY --from=builder /app/public ./public

# Copy next.config.ts if it exists
COPY --from=builder /app/next.config.ts* ./

# Set ownership to non-root user
RUN chown -R nextjs:nodejs /app

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3001

# Set hostname to allow external connections
ENV HOSTNAME="0.0.0.0"
ENV PORT=3001

# Start the application
CMD ["yarn", "start"]

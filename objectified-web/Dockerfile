# Dockerfile for Objectified Web (Next.js Marketing Site)
# Supports: linux/amd64, linux/arm64

# Stage 1: Dependencies (full install for build)
FROM --platform=$BUILDPLATFORM node:20-alpine AS deps
WORKDIR /app

RUN apk add --no-cache libc6-compat python3 make g++

# Copy package manifest (add yarn.lock or package-lock.json for reproducible installs)
COPY package.json ./

RUN yarn install

# Stage 2: Builder
FROM --platform=$BUILDPLATFORM node:20-alpine AS builder
WORKDIR /app

# Copy package manifest, then deps, then app source (.dockerignore excludes node_modules from context)
COPY package.json ./
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

RUN yarn build

# Stage 3: Runner (Production)
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

# Install production dependencies only in runner so node_modules is correct and minimal
RUN corepack enable
COPY --from=builder /app/package.json ./package.json
RUN yarn install --production --ignore-optional

# Copy built app and config
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts* ./

RUN chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3002
ENV HOSTNAME="0.0.0.0"
ENV PORT=3002

CMD ["node", "node_modules/next/dist/bin/next", "start", "-p", "3002", "-H", "0.0.0.0"]

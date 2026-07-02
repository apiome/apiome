# Docker Build Fix - Yarn Configuration

## Problem
Docker build was failing with:
```
ERROR: failed to build: failed to solve: process "/bin/sh -c if [ -f yarn.lock ]..." did not complete successfully: exit code: 1
```

## Root Cause
The Dockerfile had conditional logic to check for `yarn.lock` or `package-lock.json`, but **neither file existed** in the project. This caused the build to fail during the dependency installation step.

## Solution
Simplified the Dockerfile to use `yarn install` directly without conditional logic or lock file requirements.

## Changes Made

### Before (Problematic):

```dockerfile
# Copy package files
COPY ../package.json yarn.lock* package-lock.json* ./

# Install with conditional logic
RUN if [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then npm ci; \
    else yarn install; \
    fi
```

### After (Fixed):
```dockerfile
# Copy package files
COPY package.json ./

# Install ALL dependencies
RUN yarn install
```

### Also Simplified Runner Stage:
```dockerfile
# Before: Copying lock files that don't exist
COPY --from=builder /app/yarn.lock* ./yarn.lock
COPY --from=builder /app/package-lock.json* ./package-lock.json

# After: Only copy what exists
COPY --from=builder /app/package.json ./package.json
```

## Complete Dockerfile Structure

### Stage 1: Dependencies
- Copies `package.json`
- Runs `yarn install` to install all dependencies
- No lock file required

### Stage 2: Builder  
- Copies `node_modules` from deps stage
- Copies source code
- Runs `yarn build`

### Stage 3: Runner
- Copies only necessary files:
  - `package.json`
  - `node_modules`
  - `.next` build output
  - `public` directory
  - `next.config.ts`
- Runs as non-root user
- Starts with `yarn start`

## Build Status: ✅ SUCCESS

The Docker image now builds successfully:
```bash
docker build -t apiome-browse:latest .
```

Build output confirms:
- ✅ Dependencies installed with yarn
- ✅ Next.js build completed
- ✅ Production image created
- ✅ Image tagged successfully

## Next Steps

Run the container:
```bash
docker run -d \
  -p 3001:3000 \
  --env-file .env \
  --name apiome-browse \
  --restart unless-stopped \
  apiome-browse:latest
```

Or use npm scripts:
```bash
npm run docker:build   # Build image
npm run docker:run     # Run container  
npm run docker:logs    # View logs
```

## Note on Lock Files

The project currently runs without a lock file. To add deterministic builds:

**Option 1: Add yarn.lock**
```bash
yarn install  # Generates yarn.lock
git add yarn.lock
git commit -m "Add yarn.lock for deterministic builds"
```

Then update Dockerfile to use `--frozen-lockfile`:
```dockerfile
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile
```

**Option 2: Add package-lock.json**
```bash
npm install  # Generates package-lock.json  
git add package-lock.json
git commit -m "Add package-lock.json"
```

Then switch Dockerfile to npm:
```dockerfile
COPY package.json package-lock.json ./
RUN npm ci
```

For now, the Dockerfile works without lock files using `yarn install`.


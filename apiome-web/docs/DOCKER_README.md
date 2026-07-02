# Apiome Web - Docker Setup

This directory contains Docker configuration for the Apiome Web marketing site.

## 📋 Prerequisites

- Docker 20.10 or later
- Docker Compose v2.0 or later (optional, for docker-compose setup)
- Docker Buildx (for multi-platform builds)

## 🚀 Quick Start

### Option 1: Using Docker Compose (Recommended)

```bash
# Start the application
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the application
docker-compose down
```

The application will be available at `http://localhost:3002`

### Option 2: Using Docker directly

```bash
# Build the image
docker build -t apiome-web:latest .

# Run the container
docker run -d \
  --name apiome-web \
  -p 3002:3002 \
  apiome-web:latest

# View logs
docker logs -f apiome-web

# Stop and remove
docker stop apiome-web
docker rm apiome-web
```

### Option 3: Using build scripts

```bash
# Simple build
./build.sh

# Build and test locally
./build-docker.sh --test

# Build and save to tar file
./build-docker.sh --save

# Build and push to registry (requires DOCKER_REGISTRY env var)
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push
```

## 🏗️ Docker Files

### Dockerfile

Multi-stage Dockerfile optimized for Next.js production builds:

- **Stage 1 (deps)**: Installs dependencies
- **Stage 2 (builder)**: Builds the Next.js application
- **Stage 3 (runner)**: Minimal production image with only runtime dependencies

**Features:**
- Multi-platform support (linux/amd64, linux/arm64)
- Non-root user for security
- Optimized layer caching
- Small image size (~150MB)

### docker-compose.yml

Docker Compose configuration for easy local development and deployment.

**Default settings:**
- Port: 3002
- Restart policy: unless-stopped
- Network: apiome-network (bridge)

### .dockerignore

Excludes unnecessary files from Docker build context to improve build speed and reduce image size.

## 🔧 Configuration

### Environment Variables

Configure the application using environment variables in docker-compose.yml or Docker run command:

```yaml
environment:
  # Base path configuration (if deploying to subdirectory)
  - NEXT_PUBLIC_BASE_PATH=/web
  
  # External URLs
  - NEXT_PUBLIC_APP_URL=https://app.apiome.app
  - NEXT_PUBLIC_BROWSE_URL=https://browse.apiome.app
  - NEXT_PUBLIC_DOCS_URL=https://docs.apiome.app
```

### Custom Port

To run on a different port:

**Docker Compose:**
```yaml
ports:
  - "8080:3002"  # Host:Container
```

**Docker CLI:**
```bash
docker run -d -p 8080:3002 apiome-web:latest
```

## 📦 Build Scripts

### build.sh

Simple build script for local development:

```bash
./build.sh
```

Builds the image as `apiome-web:latest`.

### build-docker.sh

Advanced build script with multiple options:

```bash
# Build only
./build-docker.sh --build

# Build and test locally
./build-docker.sh --test

# Build and save to tar file
./build-docker.sh --save

# Build and push to registry
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push

# Build, save, and push (if registry set)
./build-docker.sh --all

# Show help
./build-docker.sh --help
```

**Environment Variables:**
- `DOCKER_REGISTRY`: Registry URL (e.g., `docker.io/username`, `myregistry.com`)
- `VERSION`: Image version tag (default: timestamp)
- `TAG`: Additional tag (default: `latest`)

**Examples:**

```bash
# Build with custom version
VERSION=1.0.0 ./build-docker.sh --build

# Build and push to Docker Hub
DOCKER_REGISTRY=docker.io/myuser ./build-docker.sh --push

# Build and push to private registry
DOCKER_REGISTRY=registry.company.com/apiome ./build-docker.sh --push
```

## 🏷️ Image Tags

The build script creates two tags:
- `${IMAGE_NAME}:latest` - Always points to latest build
- `${IMAGE_NAME}:${VERSION}` - Specific version (timestamp or custom)

Example:
```
apiome-web:latest
apiome-web:20260120-143022
```

## 🔍 Troubleshooting

### Container won't start

Check logs:
```bash
docker logs apiome-web
# or
docker-compose logs
```

### Port already in use

Either:
1. Stop the conflicting service
2. Use a different port (see Custom Port section)

### Build fails

1. Ensure Docker daemon is running: `docker info`
2. Check disk space: `df -h`
3. Clear build cache: `docker builder prune`
4. Rebuild without cache: `docker build --no-cache -t apiome-web:latest .`

### Image size too large

The production image should be around 150-200MB. If larger:
1. Check .dockerignore is properly configured
2. Ensure multi-stage build is working
3. Verify only production dependencies are included

## 🚢 Production Deployment

### Docker Swarm

```bash
# Initialize swarm (if not already done)
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml apiome

# Check status
docker stack services apiome

# Remove stack
docker stack rm apiome
```

### Kubernetes

Create deployment and service:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: apiome-web
spec:
  replicas: 3
  selector:
    matchLabels:
      app: apiome-web
  template:
    metadata:
      labels:
        app: apiome-web
    spec:
      containers:
      - name: apiome-web
        image: apiome-web:latest
        ports:
        - containerPort: 3002
        env:
        - name: NEXT_PUBLIC_APP_URL
          value: "https://app.apiome.app"
---
apiVersion: v1
kind: Service
metadata:
  name: apiome-web
spec:
  selector:
    app: apiome-web
  ports:
  - port: 80
    targetPort: 3002
  type: LoadBalancer
```

### Docker Registry

Push to private registry:

```bash
# Tag image
docker tag apiome-web:latest registry.company.com/apiome-web:latest

# Push image
docker push registry.company.com/apiome-web:latest
```

Or use the build script:
```bash
DOCKER_REGISTRY=registry.company.com ./build-docker.sh --push
```

## 🔒 Security

### Non-root User

The container runs as a non-root user (`nextjs:nodejs`, UID 1001) for security.

### Read-only Filesystem

To run with read-only filesystem:

```bash
docker run -d \
  --name apiome-web \
  --read-only \
  --tmpfs /tmp \
  -p 3002:3002 \
  apiome-web:latest
```

### Security Scanning

Scan image for vulnerabilities:

```bash
# Using Docker Scout
docker scout cves apiome-web:latest

# Using Trivy
trivy image apiome-web:latest
```

## 📊 Monitoring

### Health Check

Add health check to docker-compose.yml:

```yaml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3002"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### Resource Limits

Limit container resources:

```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
    reservations:
      cpus: '0.5'
      memory: 256M
```

## 🔄 Updates

### Update running container

```bash
# Pull latest image
docker pull apiome-web:latest

# Stop and remove old container
docker stop apiome-web
docker rm apiome-web

# Start new container
docker run -d \
  --name apiome-web \
  -p 3002:3002 \
  apiome-web:latest
```

### Update with Docker Compose

```bash
# Pull and restart
docker-compose pull
docker-compose up -d
```

## 📝 Notes

- The application runs on port 3002 by default
- Next.js telemetry is disabled in production
- Build uses Yarn for package management
- Supports both AMD64 and ARM64 architectures
- Image includes only production dependencies
- Static assets are served from the .next directory

## 🆘 Support

For issues or questions:
- Check logs: `docker logs apiome-web`
- Visit: https://docs.apiome.app
- Watch tutorials: https://www.youtube.com/@objectifieddev

## 📄 License

Copyright © 2026 Apiome. All rights reserved.

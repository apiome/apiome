# Docker Build Script Documentation

## Overview

The `build-docker.sh` script automates the process of building, testing, and preparing the Apiome UI Docker image for deployment to remote servers.

## Features

- ✅ **Automated Build** - Builds Docker image with version tags
- ✅ **Image Testing** - Tests the image before deployment
- ✅ **Image Export** - Saves image to compressed tar file
- ✅ **Registry Push** - Pushes to Docker registry (optional)
- ✅ **Deployment Package** - Creates ready-to-deploy package
- ✅ **Deployment Scripts** - Generates deployment automation scripts
- ✅ **Error Handling** - Stops on errors, provides clear feedback

## Quick Start

### Basic Build

```bash
./build-docker.sh
```

This will:
1. Build the Docker image
2. Test the image
3. Save to tar file
4. Generate deployment scripts

### Build and Push to Registry

```bash
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push
```

### Build Deployment Package

```bash
./build-docker.sh --package
```

Creates a complete deployment package with:
- Compressed Docker image
- Deployment script
- Docker compose file
- Environment template
- README

## Command Line Options

### `--tag TAG`
Set custom image tag (default: `latest`)

```bash
./build-docker.sh --tag v1.0.0
```

### `--version VERSION`
Set custom version (default: timestamp)

```bash
./build-docker.sh --version 1.0.0
```

### `--registry REGISTRY`
Specify Docker registry URL

```bash
./build-docker.sh --registry myregistry.com
```

### `--no-test`
Skip image testing (faster build)

```bash
./build-docker.sh --no-test
```

### `--no-save`
Skip saving to tar file

```bash
./build-docker.sh --no-save
```

### `--push`
Push image to Docker registry

```bash
./build-docker.sh --push
```

### `--package`
Create complete deployment package

```bash
./build-docker.sh --package
```

### `--help`
Show usage information

```bash
./build-docker.sh --help
```

## Environment Variables

### `DOCKER_REGISTRY`
Docker registry URL for pushing images

```bash
export DOCKER_REGISTRY=myregistry.com
./build-docker.sh --push
```

### `VERSION`
Custom version for the build

```bash
export VERSION=1.0.0
./build-docker.sh
```

### `TAG`
Custom tag for the image

```bash
export TAG=production
./build-docker.sh
```

## Build Process

### 1. Pre-Build Checks
- Verifies Docker is installed and running
- Checks required files exist (Dockerfile, package.json, etc.)

### 2. Image Build
- Builds multi-stage Docker image
- Tags with both `latest` and version-specific tag
- Adds build metadata

### 3. Image Testing
- Starts test container on port 3001
- Verifies container starts successfully
- Tests application responds to HTTP requests
- Cleans up test container

### 4. Image Export
- Saves Docker image to tar file
- Compresses with gzip
- Shows file size information

### 5. Registry Push (Optional)
- Pushes image to specified registry
- Pushes both `latest` and version tags

### 6. Deployment Files
- Generates deployment shell script
- Creates docker-compose.yml for remote deployment
- Includes environment template

### 7. Deployment Package (Optional)
- Creates complete deployment package
- Includes all necessary files
- Compressed tar.gz archive

## Output Files

After running the script, you'll have:

### Always Created
- `deploy-YYYYMMDD-HHMMSS.sh` - Deployment script
- `docker-compose.deploy-YYYYMMDD-HHMMSS.yml` - Compose file

### With Default Options
- `apiome-ui-YYYYMMDD-HHMMSS.tar.gz` - Compressed image

### With `--package` Option
- `apiome-ui-deploy-YYYYMMDD-HHMMSS.tar.gz` - Complete package

## Usage Examples

### Example 1: Development Build

```bash
# Quick build for testing
./build-docker.sh --no-save
```

### Example 2: Production Build with Registry

```bash
# Build and push to production registry
DOCKER_REGISTRY=registry.company.com ./build-docker.sh \
  --tag production \
  --version 1.0.0 \
  --push
```

### Example 3: Complete Deployment Package

```bash
# Create package for remote deployment
./build-docker.sh \
  --tag v1.0.0 \
  --version 1.0.0 \
  --package
```

This creates: `apiome-ui-deploy-1.0.0.tar.gz`

### Example 4: Fast Build for CI/CD

```bash
# Skip testing and save steps
./build-docker.sh \
  --no-test \
  --no-save \
  --push
```

## Deployment to Remote Server

### Option 1: Using Deployment Package

1. **Build package locally:**
```bash
./build-docker.sh --package
```

2. **Transfer to server:**
```bash
scp apiome-ui-deploy-*.tar.gz user@server:/opt/
```

3. **On remote server:**
```bash
cd /opt
tar xzf apiome-ui-deploy-*.tar.gz
cd apiome-ui-deploy-*
cp .env.template .env
nano .env  # Configure
./deploy.sh
```

### Option 2: Using Registry

1. **Build and push:**
```bash
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push
```

2. **On remote server:**
```bash
docker pull myregistry.com/apiome-ui:latest
docker run -d -p 3000:3000 --env-file .env myregistry.com/apiome-ui:latest
```

### Option 3: Manual Transfer

1. **Build and save:**
```bash
./build-docker.sh
```

2. **Transfer image:**
```bash
scp apiome-ui-*.tar.gz user@server:/opt/
```

3. **On remote server:**
```bash
gunzip -c apiome-ui-*.tar.gz | docker load
docker run -d -p 3000:3000 --env-file .env apiome-ui:latest
```

## Deployment Package Contents

When using `--package`, the generated archive contains:

```
apiome-ui-deploy-YYYYMMDD-HHMMSS/
├── README.md                          # Deployment instructions
├── .env.template                       # Environment variables template
├── docker-compose.yml                  # Docker compose configuration
├── deploy.sh                           # Automated deployment script
└── apiome-ui-YYYYMMDD-HHMMSS.tar.gz  # Docker image (if --no-save not used)
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build and Push Docker Image

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Login to Registry
        run: echo "${{ secrets.DOCKER_PASSWORD }}" | docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
      
      - name: Build and Push
        env:
          DOCKER_REGISTRY: myregistry.com
          VERSION: ${{ github.ref_name }}
        run: |
          cd apiome-ui
          ./build-docker.sh --push --package
      
      - name: Upload Artifact
        uses: actions/upload-artifact@v3
        with:
          name: deployment-package
          path: apiome-ui/apiome-ui-deploy-*.tar.gz
```

### GitLab CI Example

```yaml
build-docker:
  stage: build
  script:
    - cd apiome-ui
    - ./build-docker.sh --push --package
  artifacts:
    paths:
      - apiome-ui/apiome-ui-deploy-*.tar.gz
  only:
    - tags
```

## Troubleshooting

### Build Fails

**Problem:** Docker build fails
```bash
# Check Docker is running
docker info

# Clean build with no cache
./build-docker.sh --no-test
docker build --no-cache -t apiome-ui .
```

### Test Fails

**Problem:** Test container won't start
```bash
# Check port 3001 is available
lsof -i :3001

# Skip test step
./build-docker.sh --no-test
```

### Registry Push Fails

**Problem:** Cannot push to registry
```bash
# Login to registry first
docker login myregistry.com

# Verify registry URL
echo $DOCKER_REGISTRY

# Try push manually
docker push myregistry.com/apiome-ui:latest
```

### Permission Denied

**Problem:** Script is not executable
```bash
chmod +x build-docker.sh
```

## Best Practices

### Version Tagging

Use semantic versioning:
```bash
./build-docker.sh --tag v1.0.0 --version 1.0.0
```

### Registry Authentication

Login before pushing:
```bash
docker login myregistry.com
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push
```

### Build Cache

Keep Docker cache for faster builds:
```bash
# Don't prune system between builds
# Only prune when needed
docker system prune -a
```

### Testing

Always test before pushing to production:
```bash
# Build and test
./build-docker.sh

# Manual test
docker run -p 3000:3000 apiome-ui:latest
```

## Performance Tips

### Faster Builds

```bash
# Skip testing for development
./build-docker.sh --no-test

# Skip save for quick iterations
./build-docker.sh --no-test --no-save
```

### Smaller Images

The script already uses multi-stage builds, but you can optimize further:
- Update Dockerfile to remove unused dependencies
- Use .dockerignore to exclude unnecessary files

### Parallel Builds

Build multiple versions in parallel:
```bash
./build-docker.sh --tag dev &
./build-docker.sh --tag staging &
wait
```

## Security Considerations

### Image Scanning

After build, scan for vulnerabilities:
```bash
docker scan apiome-ui:latest
```

### Registry Security

Use private registries for production:
```bash
DOCKER_REGISTRY=private-registry.company.com ./build-docker.sh --push
```

### Secrets Management

Never include secrets in the image:
- Use environment variables
- Mount secrets at runtime
- Use Docker secrets or external vaults

## Support

For issues or questions:
- Check logs: `docker logs <container>`
- Verify build: `docker images apiome-ui`
- Test manually: `docker run -it apiome-ui:latest sh`

---

**Last Updated**: December 6, 2024
**Script Version**: 1.0
**Compatible With**: Docker 24.0+, Next.js 16.0.7

